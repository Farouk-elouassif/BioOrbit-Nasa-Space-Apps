"""Simulator wire catalogue v1.0; kept independent of the simulator runtime."""
CATALOGUE = {
    'heart_rate': ('bpm', 'astronaut'),
    'systolic_blood_pressure': ('mmHg', 'astronaut'),
    'diastolic_blood_pressure': ('mmHg', 'astronaut'),
    'blood_glucose': ('mg/dL', 'astronaut'),
    'body_temperature': ('°C', 'astronaut'),
    'respiratory_rate': ('breaths/min', 'astronaut'),
    'spo2': ('%', 'astronaut'),
    'sleep_duration': ('hours', 'astronaut'),
    'mood': ('0–10', 'astronaut'),
    'stress_level': ('0–10', 'astronaut'),
    'fluid_intake': ('L', 'astronaut'),
    'body_mass': ('kg', 'astronaut'),
    'preflight_radiation_level': ('mSv/year', 'astronaut'),
    'preflight_career_radiation_dose': ('mSv', 'astronaut'),
    'personal_radiation_dose_rate': ('mSv/day', 'astronaut'),
    'mission_cumulative_radiation_dose': ('mSv', 'astronaut'),
    'total_career_radiation_dose': ('mSv', 'astronaut'),
    'co2_partial_pressure': ('mmHg', 'cabin'),
    'o2_partial_pressure': ('mmHg', 'cabin'),
    'total_cabin_pressure': ('kPa', 'cabin'),
    'cabin_temperature': ('°C', 'cabin'),
    'relative_humidity': ('%', 'cabin'),
    'noise_level': ('dBA', 'cabin'),
    'dust_concentration': ('mg/m³', 'cabin'),
    'radiation_level': ('mSv/day', 'cabin'),
    'is_solar_storm': ('boolean', 'cabin'),
}
ENVIRONMENTS = ('transit_spacecraft', 'space_station', 'rover', 'surface_base')
ACTIVITIES = ('resting', 'sleeping', 'working', 'exercising', 'eva')

PREFLIGHT_METRICS = (
    'heart_rate', 'systolic_blood_pressure', 'diastolic_blood_pressure',
    'blood_glucose', 'body_temperature', 'respiratory_rate', 'spo2',
    'sleep_duration', 'mood', 'body_mass', 'preflight_radiation_level',
    'preflight_career_radiation_dose',
)
CUMULATIVE = {'mission_cumulative_radiation_dose', 'total_career_radiation_dose', 'preflight_career_radiation_dose'}
INTERVAL_TOTAL = {'sleep_duration', 'fluid_intake'}


def metric_spec(code):
    unit, domain = CATALOGUE[code]
    boolean = code == 'is_solar_storm'
    return {'unit': unit, 'domain': domain,
            'value_type': 'boolean' if boolean else 'numeric',
            'aggregation_kind': 'boolean' if boolean else 'cumulative' if code in CUMULATIVE else 'interval_total' if code in INTERVAL_TOTAL else 'point'}

# Data.xlsx identifiers are accepted at the wire boundary. Existing database codes
# remain canonical so older journal events and latest-value keys stay compatible.
WORKBOOK_ALIASES = {
    'bp_systolic': 'systolic_blood_pressure',
    'bp_diastolic': 'diastolic_blood_pressure',
    'resp_rate': 'respiratory_rate',
    'core_temp': 'body_temperature',
    'glucose': 'blood_glucose',
    'sleep_hours': 'sleep_duration',
    'stress': 'stress_level',
    'cabin_co2': 'co2_partial_pressure',
    'cabin_o2': 'o2_partial_pressure',
    'cabin_pressure': 'total_cabin_pressure',
    'cabin_temp': 'cabin_temperature',
    'cabin_humidity': 'relative_humidity',
    'noise': 'noise_level',
    'dust': 'dust_concentration',
    # Workbook radiation thresholds refer to the career budget, not just this mission.
    'rad_cumulative': 'total_career_radiation_dose',
}
DOMAIN_ALIASES = {
    ('rad_rate', 'astronaut'): 'personal_radiation_dose_rate',
    ('rad_rate', 'cabin'): 'radiation_level',
}
UNIT_ALIASES = {
    ('heart_rate', 'beats/min'): 'bpm',
    ('sleep_duration', 'h/night'): 'hours',
    ('mood', '0–10 slider'): '0–10',
    ('stress_level', '0–10 slider'): '0–10',
}


def canonical_metric(code, domain):
    if not isinstance(code, str) or not isinstance(domain, str):
        return code  # The validator reports invalid types.
    return DOMAIN_ALIASES.get((code, domain), WORKBOOK_ALIASES.get(code, code))


def canonical_unit(code, unit):
    if not isinstance(code, str) or not isinstance(unit, str):
        return unit
    return UNIT_ALIASES.get((code, unit), unit)
