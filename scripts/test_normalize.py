"""Real strings copied from the five tier-1 manufacturer sites."""
import sys
from normalize import normalize

CASES = [
    # (raw string, canonical field, parser, source_unit, expected or None)
    ("13.78 in",                 "working_width_in",       "number",     "in",  13.78),
    ("100\" (254 cm)",           "working_width_in",       "dual_unit",  "in",  100.0),   # Toro: imperial first
    ("203 cm / 80 in.",          "working_width_in",       "dual_unit",  "in",  80.0),    # Deere: metric first
    ("638 cm",                   "working_width_in",       "dual_unit",  "in",  251.18),  # cm only -> convert
    ("40.7",                     "working_width_in",       "number",     "in",  40.7),    # Echo: unit in label
    ("0.8 m/s",                  "mowing_speed_mph",       "number",     "m_s", 1.79),    # Kress publishes m/s
    ("up to 5.6 mph",            "mowing_speed_mph",       "number",     "mph", 5.6),
    ("6 mph / 9.7 kph",          "mowing_speed_mph",       "dual_unit",  "mph", 6.0),
    ("0 - 8 mph (0 - 12.8 km/h)","mow_speed_max_mph",      "dual_unit",  "mph", 8.0),
    ("12.8 km/h / 8 mph",        "mow_speed_max_mph",      "dual_unit",  "mph", 8.0),
    ("40%",                      "max_slope_pct",          "percent",    "pct", 40.0),
    ("22° / 40%",                "max_slope_pct",          "percent",    "pct", 40.0),    # prefer the percent
    ("45°",                      "max_slope_pct",          "percent",    "pct", 100.0),   # deg -> tan, not ratio
    ("1.18 - 3.54 in",           "cut_height_min_in",      "number_range","in", 1.18),
    ("1.18 - 3.54 in",           "cut_height_max_in",      "number_range","in", 3.54),
    ("2-28.5 mm / 0.078-1.125 in.","cut_height_max_in",    "dual_unit",  "in",  1.125),
    ("2-28.5 mm / 0.078-1.125 in.","cut_height_min_in",    "dual_unit",  "in",  0.078),
    ("26.68 lbs",                "weight_lb",              "number",     "lb",  26.68),
    ("159",                      "weight_lb",              "number",     "lb",  159.0),   # Echo: unit in label
    ("10,900 lbs (4,944 kg)",    "weight_lb",              "dual_unit",  "lb",  10900.0), # comma thousands
    ("52.9",                     "weight_lb",              "number",     "kg",  116.62),  # EU kg -> lb
    ("9 acre",                   "max_area_acres",         "number",     "acre",9.0),
    ("75,000",                   "max_area_acres",         "number",     "m2",  18.53),   # m2 -> acres
    ("48 V",                     "battery_voltage_v",      "number",     "v",   48.0),
    ("10 Ah",                    "battery_capacity_ah",    "number",     "ah",  10.0),
    ("10 kWh",                   "battery_energy_kwh",     "number",     "kwh", 10.0),
    ("9 hours",                  "charge_time_hr",         "number",     "hr",  9.0),
    ("2.5 hours",                "charge_time_hr",         "number",     "hr",  2.5),
    ("14 U.S. gal. (53 L)",      "fuel_capacity_gal",      "dual_unit",  "gal", 14.0),
    ("45.4 L / 12 U.S. gal.",    "fuel_capacity_gal",      "dual_unit",  "gal", 12.0),
    ("60 gal (227 liters)",      "fuel_capacity_gal",      "dual_unit",  "gal", 60.0),
    ("31 kW / 41.6 hp",          "engine_hp",              "dual_unit",  "hp",  41.6),
    ("1.568 L / 95.69 cu in.",   "engine_displacement_cc", "dual_unit",  "cc",  1568.0),
    ("58 db",                    "noise_db",               "number",     "db",  58.0),
    ("2.85",                     "overall_length_in",      "number",     "ft",  34.2),    # Echo feet -> inches
    ("111\" (281.9 cm)",         "overall_length_in",      "dual_unit",  "in",  111.0),
    ("✓",                        "fleet_management",       "boolean_check","",  True),
    # --- these SHOULD be refused, not guessed ---
    ("Refer to operator's manual.", "max_slope_pct",       "prose",      "",    None),
    ("With 5\" cutting units: 2WD - 2,776 lbs.", "weight_lb","compound", "lb",  None),
    ("Mowing 12.8 km/h; Transport 19.3 km/h; Reverse 9.6 km/h", "transport_speed_max_mph","compound","mph",None),
    ("0.8",                      "mowing_speed_mph",       "number",     "mph", 0.8),     # unit trap survives range check
    ("400",                      "max_slope_pct",          "percent",    "pct", None),    # nonsense -> refused
]

passed = failed = 0
for raw, field, parser, unit, expect in CASES:
    r = normalize(raw, field, parser, unit)
    if expect is None:
        good = not r.ok
    else:
        good = r.ok and (r.value is True if expect is True else abs(r.value - expect) <= max(0.02, abs(expect) * 0.005))
    passed, failed = (passed + good, failed + (not good))
    print(f"{'ok ' if good else 'FAIL'} {field:24} {r}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
