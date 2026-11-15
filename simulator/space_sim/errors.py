"""Deterministic abnormal test readings; Django remains the alert authority."""
import hashlib
from .contracts import validate_event

# Values deliberately cross implemented thresholds. Windowed rules still need
# enough history, and these fixtures do not alter the physical state/integrator.
VALUES = {
    'heart_rate': 145., 'respiratory_rate': 27., 'spo2': 89.,
    'systolic_blood_pressure': 85., 'diastolic_blood_pressure': 100.,
    'blood_glucose': 50., 'body_temperature': 39.5, 'sleep_duration': 4.,
    'mood': 1., 'stress_level': 10., 'fluid_intake': .1,
    'personal_radiation_dose_rate': 12., 'mission_cumulative_radiation_dose': 250.,
    'total_career_radiation_dose': 500., 'co2_partial_pressure': 5.,
    'o2_partial_pressure': 120., 'total_cabin_pressure': 30.,
    'cabin_temperature': 30., 'relative_humidity': 70., 'noise_level': 80.,
    'dust_concentration': .5, 'radiation_level': 12., 'is_solar_storm': True,
}


def inject(engine, events):
    level=engine.config.error_level
    if not level:return events
    people={p['id']:p for p in engine.state['crew']}
    for event in events:
        if event['kind']!='measurement' or event['phase']!='inflight':continue
        # Independent of the dynamics RNG, batch size, retries and restart timing.
        score=int.from_bytes(hashlib.sha256(('error:'+event['event_id']).encode()).digest()[:8],'big') / 2**64
        selected=score < level/100
        event['context']['error_injection']={'selected':selected,'percentage':level}
        if not selected:continue
        code=event['metric'];context=event['context'];inputs=context.setdefault('rule_inputs',{})
        event['value']=people[event['astronaut_id']]['baseline']['body_mass']*.9 if code=='body_mass' else VALUES[code]
        if code in ('heart_rate','respiratory_rate','spo2','systolic_blood_pressure','body_temperature'):
            context['activity']='resting';event['zone_id']='CABIN_MAIN'
        if code=='diastolic_blood_pressure':inputs['diastolic_drift_from_baseline']={'value':True}
        if code=='blood_glucose':
            context['meal_context']='fasting';inputs['shaking']={'value':True}
        if code=='body_temperature':inputs['symptoms_present']={'value':True}
        if code=='sleep_duration':inputs['hours_awake']={'value':20,'unit':'hours'}
        if code=='fluid_intake':
            inputs.update({'urine_volume':{'value':1.,'unit':'L/day'},'urine_colour':{'value':'dark'},'flank_pain':{'value':True}})
        if code=='dust_concentration':context['surface_body']=engine.config.surface_body
        if code=='is_solar_storm':
            inputs.update({'noaa_s_level':{'value':2,'unit':'S-level'},
                           'projected_event_dose_msv':{'value':220.,'unit':'mSv'}})
        validate_event(event)
    return events
