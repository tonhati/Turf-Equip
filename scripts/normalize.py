"""
Turf-Equip value normalizer.

Turns a raw on-page string into a clean number in the schema's unit.

Design rules:
  1. The target unit comes from the CANONICAL COLUMN NAME. `working_width_in`
     means inches. This is schema convention #1, reused as executable logic --
     a column with no unit suffix is a schema bug and raises here.
  2. Nothing is silently coerced. A value that cannot be parsed with confidence
     returns ok=False with a reason and the raw string preserved. A blank in the
     database means "unknown"; it must never mean "we guessed wrong quietly."
  3. Dual-unit strings are handled by extracting EVERY (value, unit) pair and
     picking the one that matches the target -- so Toro's imperial-first
     `100" (254 cm)` and Deere's metric-first `203 cm / 80 in.` both work with
     no per-brand ordering rule.
  4. Every result is range-checked. Most unit mistakes produce a plausible-looking
     number (0.8 m/s read as mph), so the range check is the real safety net,
     not the parser.
"""

import math
import re

# --- units -------------------------------------------------------------------

# Everything converts to a base unit per dimension, then out to the target.
TO_BASE = {
    # length -> inch
    "in": 1.0, "cm": 1 / 2.54, "mm": 1 / 25.4, "m": 39.3701, "ft": 12.0,
    # mass -> pound
    "lb": 1.0, "kg": 2.20462,
    # speed -> mph
    "mph": 1.0, "kph": 0.621371, "m_s": 2.23694,
    # area -> acre
    "acre": 1.0, "m2": 0.000247105, "hectare": 2.47105, "sqft": 1 / 43560,
    # area rate -> acre/hr
    "acre_hr": 1.0, "hectare_hr": 2.47105,
    # volume -> gallon
    "gal": 1.0, "liter": 0.264172,
    # displacement -> cc
    "cc": 1.0, "liter_disp": 1000.0, "cu_in": 16.3871,
    # power -> hp
    "hp": 1.0, "kw": 1.34102,
    # energy -> kwh
    "kwh": 1.0, "wh": 0.001,
    # time -> hour
    "hr": 1.0, "min": 1 / 60,
    # pass-through
    "pct": 1.0, "v": 1.0, "ah": 1.0, "db": 1.0, "count": 1.0,
}

DIMENSION = {
    "length": {"in", "cm", "mm", "m", "ft"},
    "mass": {"lb", "kg"},
    "speed": {"mph", "kph", "m_s"},
    "area": {"acre", "m2", "hectare", "sqft"},
    "area_rate": {"acre_hr", "hectare_hr"},
    "volume": {"gal", "liter"},
    "displacement": {"cc", "liter_disp", "cu_in"},
    "power": {"hp", "kw"},
    "energy": {"kwh", "wh"},
    "time": {"hr", "min"},
    "percent": {"pct"},
    "voltage": {"v"}, "charge": {"ah"}, "sound": {"db"}, "count": {"count"},
}

def dimension_of(unit):
    for dim, members in DIMENSION.items():
        if unit in members:
            return dim
    return None

# Longest spellings first so "cu in" is not eaten by "in", and "m/s" not by "m".
UNIT_WORDS = [
    (r"cubic\s*inches|cu\.?\s*in\.?", "cu_in"),
    (r"kilowatt-?hours?|kwh", "kwh"),
    (r"hectares?/\s*hr|hectares?\s*per\s*hour|ha/hr", "hectare_hr"),
    (r"acres?\s*(?:per|/)\s*(?:hour|hr)", "acre_hr"),
    (r"kilometers?\s*per\s*hour|km/h|kph", "kph"),
    (r"meters?\s*per\s*second|m/s", "m_s"),
    (r"square\s*feet|sq\.?\s*ft", "sqft"),
    (r"hectares?|\bha\b", "hectare"),
    (r"square\s*met(?:er|re)s?|m²|m2", "m2"),
    (r"u\.?s\.?\s*gal(?:lons?)?\.?|gal(?:lons?)?\.?", "gal"),
    (r"lit(?:er|re)s?|\bl\b", "liter"),
    (r"pounds?|lbs?\.?", "lb"),
    (r"kilograms?|kgs?\b", "kg"),
    (r"inch(?:es)?|\bin\.?|\"|″|”", "in"),
    (r"centimet(?:er|re)s?|\bcm\b", "cm"),
    (r"millimet(?:er|re)s?|\bmm\b", "mm"),
    (r"\bfeet\b|\bft\.?|'|′", "ft"),
    (r"met(?:er|re)s?\b|\bm\b", "m"),
    (r"acres?", "acre"),
    (r"\bmph\b|miles?\s*per\s*hour", "mph"),
    (r"horsepower|\bhp\b", "hp"),
    (r"kilowatts?|\bkw\b", "kw"),
    (r"watt-?hours?|\bwh\b", "wh"),
    (r"hours?|\bhrs?\.?|\bh\b", "hr"),
    (r"minutes?|\bmins?\.?", "min"),
    (r"volts?|\bv\b", "v"),
    (r"amp-?hours?|\bah\b", "ah"),
    (r"decibels?|\bdb\b", "db"),
    (r"degrees?|°", "deg"),
    (r"%", "pct"),
]

NUM = r"\d[\d,]*\.?\d*"   # unsigned: a hyphen here is a range, not a sign

def target_unit(field):
    """Read the target unit off the column name. Schema convention #1."""
    for suffix, unit in [
        ("_acres_hr", "acre_hr"), ("_acres", "acre"), ("_acre", "acre"),
        ("_in", "in"), ("_lb", "lb"), ("_mph", "mph"), ("_pct", "pct"),
        ("_hp", "hp"), ("_kw", "kw"), ("_cc", "cc"), ("_gal", "gal"),
        ("_kwh", "kwh"), ("_ah", "ah"), ("_v", "v"), ("_db", "db"),
        ("_hr", "hr"), ("_min", "min"),
    ]:
        if field.endswith(suffix):
            return unit
    if field.startswith("num_") or field.endswith("_sensors") or field.endswith("_units"):
        return "count"
    raise ValueError(f"no unit suffix on canonical field '{field}' -- schema bug")

def _backfill_units(pairs):
    """In `1.18 - 3.54 in` only the last value carries the unit.
    An unlabeled number inherits the unit of the next labeled one."""
    out, carry = [], None
    for value, unit in reversed(pairs):
        carry = unit or carry
        out.append((value, unit or carry))
    return list(reversed(out))


def _is_bound(field):
    """'min'/'max' if the field is one end of a range, else None."""
    if "_min" in field or field.startswith("min_"):
        return "min"
    if "_max" in field or field.startswith("max_"):
        return "max"
    return None


def convert(value, from_unit, to_unit):
    if from_unit == to_unit:
        return value
    # Slope: degrees to percent is trigonometry, not a ratio.
    if from_unit == "deg" and to_unit == "pct":
        return math.tan(math.radians(value)) * 100
    if from_unit == "liter" and to_unit == "cc":
        from_unit = "liter_disp"
    if to_unit == "cc" and from_unit == "liter":
        from_unit = "liter_disp"
    if dimension_of(from_unit) != dimension_of(to_unit):
        raise ValueError(f"cannot convert {from_unit} to {to_unit}")
    return value * TO_BASE[from_unit] / TO_BASE[to_unit]

# --- plausibility ranges -----------------------------------------------------
# The real safety net. A wrong unit usually yields a believable number.

RANGES = {
    "working_width_in": (5, 300),
    "cut_height_min_in": (0.05, 6),   # greens/fairway reels cut to 2 mm = 0.078 in
    "cut_height_max_in": (0.2, 10),
    "max_slope_pct": (5, 100),
    "weight_lb": (10, 25000),
    "mowing_speed_mph": (0.5, 20), "mow_speed_max_mph": (0.5, 20),
    "transport_speed_max_mph": (1, 30), "reverse_speed_max_mph": (0.5, 20),
    "max_area_acres": (0.05, 60), "recommended_area_acres": (0.05, 60),
    "area_per_charge_acres": (0.05, 60), "area_capacity_acres_hr": (0.1, 40),
    "battery_voltage_v": (12, 900), "battery_capacity_ah": (1, 400),
    "battery_energy_kwh": (0.1, 200), "charge_time_hr": (0.1, 24),
    "engine_hp": (3, 300), "fuel_capacity_gal": (0.5, 200),
    "engine_displacement_cc": (50, 8000), "noise_db": (30, 110),
    "reel_diameter_in": (3, 12), "overall_length_in": (20, 400),
    "overall_width_in": (15, 400), "height_to_rops_in": (20, 150),
}

class Result:
    def __init__(self, ok, value=None, raw="", unit=None, reason="", flags=None):
        self.ok, self.value, self.raw = ok, value, raw
        self.unit, self.reason = unit, reason
        self.flags = flags or []
    def __repr__(self):
        if self.ok:
            f = (" [" + ",".join(self.flags) + "]") if self.flags else ""
            return f"OK    {self.value:>12,.4g} {self.unit}{f}   <- {self.raw!r}"
        return f"SKIP  {'-':>12}      {self.reason:24} <- {self.raw!r}"

def find_pairs(text):
    """Every (number, unit) pair in the string, in order of appearance."""
    pairs = []
    for m in re.finditer(NUM, text):
        num = float(m.group().replace(",", ""))
        tail = text[m.end():m.end() + 22]
        unit = None
        for pattern, name in UNIT_WORDS:
            um = re.match(r"\s*(?:" + pattern + r")", tail, re.I)
            if um:
                unit = name
                break
        pairs.append((num, unit))
    return pairs

def normalize(raw, field, parser, source_unit=""):
    """Raw page string -> Result in the field's canonical unit."""
    raw = (raw or "").strip()
    if not raw:
        return Result(False, raw=raw, reason="empty")

    if parser in ("text", "prose", "compound"):
        return Result(False, raw=raw, reason=f"{parser}: needs review")

    if parser == "boolean_check":
        truthy = {"✓", "yes", "standard", "true", "included", "√"}
        return Result(True, raw.lower() in truthy, raw, "bool")

    want = target_unit(field)
    pairs = [p for p in find_pairs(raw) if p[0] is not None]
    if not pairs:
        return Result(False, raw=raw, reason="no number found")

    flags = []
    if parser == "percent":
        # Prefer an explicit percent; fall back to degrees, converted.
        cand = [(v, u) for v, u in pairs if u == "pct"] or \
               [(v, u) for v, u in pairs if u == "deg"]
        if not cand:
            cand = [(pairs[0][0], "pct")]
            flags.append("unit assumed")
        value, unit = cand[0]
        if unit == "deg":
            flags.append("converted from degrees")
    elif parser == "number_range" or (parser == "dual_unit" and _is_bound(field)):
        # `2-28.5 mm / 0.078-1.125 in.` is a range AND a dual-unit string.
        # Keep the pairs already in the target unit; fall back to all of them.
        filled = _backfill_units(pairs)
        in_target = [(v, u) for v, u in filled if u == want]
        if in_target:
            usable, unit = in_target, want
        else:
            usable = filled
            unit = next((u for _, u in filled if u), None)
        values = [v for v, _ in usable]
        value = max(values) if _is_bound(field) == "max" else min(values)
    else:
        # number / dual_unit: prefer a pair already in the target unit,
        # else the first pair carrying any convertible unit.
        same = [(v, u) for v, u in pairs if u == want]
        if same:
            value, unit = same[0]
        else:
            conv = [(v, u) for v, u in pairs
                    if u and (dimension_of(u) == dimension_of(want)
                              or (u == "deg" and want == "pct"))]
            if conv:
                value, unit = conv[0]
                flags.append(f"converted from {unit}")
            else:
                value, unit = pairs[0][0], None

    if unit is None:
        unit = source_unit or want
        if unit != want:
            flags.append(f"unit taken from label ({unit})")
        else:
            flags.append("unit assumed")
    try:
        value = convert(value, unit, want)
    except ValueError as e:
        return Result(False, raw=raw, reason=str(e))

    lo, hi = RANGES.get(field, (None, None))
    if lo is not None and not (lo <= value <= hi):
        return Result(False, raw=raw, reason=f"out of range ({value:.4g} vs {lo}-{hi})")

    return Result(True, round(value, 4), raw, want, flags=flags)
