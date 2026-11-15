"""Explicit synthetic facts and bounded, replayable fault-injection scenarios.

Scenario values are test inputs, never inferred clinical or NOAA classifications.
"""
from copy import deepcopy
import math
import json
from datetime import datetime
from .contracts import ACTIVITIES, CATALOGUE, validate_event

SYMPTOMS = ('ecg_alarm', 'ecg_alarm_with_symptoms', 'ecg_alarm_with_chest_pain_or_collapse', 'breathlessness', 'breathlessness_at_rest', 'lightheadedness', 'fainting',
    'symptoms_present', 'sweating', 'shaking', 'confusion', 'withdrawal',
    'loss_of_appetite', 'loss_of_interest', 'nausea', 'vomiting', 'dizziness',
    'chest_pain', 'collapse', 'new_confusion', 'neurological_signs',
    'diastolic_drift_from_baseline', 'reaction_slower_two_tests', 'flank_pain',
    'vision_change', 'amsler_acuity', 'cabin_event_last24h',
    'spco_rise_after_cabin_event', 'spmet_rise_after_cabin_event', 'within_24h_eva',
    'numbness', 'weakness', 'breathing_trouble', 'joint_pain', 'tingling', 'skin_change',
    'exercise_below_plan_7days', 'urinary_calcium_rising')


def normal_inputs(engine, seconds, person):
    # Explicit synthetic observations, including negative findings. Their source is
    # carried by the normal event envelope and scenario evidence.
    from .model import RADIATION
    active, _ = engine.storm_at(seconds)
    # Project the scheduled event's excess dose by integrating its sin² envelope.
    # NOAA severity remains an explicit scenario input, never inferred from dose.
    dose = sum(max(0, s['peak'] - RADIATION[engine.config.environment])
               * s['duration'] / (2 * 86400)
               for s in engine.state['storms'] if s['start'] <= seconds < s['start'] + s['duration'])
    inputs = {'noaa_s_level': {'value': max((s.get('noaa_s_level',0) for s in engine.state['storms'] if s['start']<=seconds<s['start']+s['duration']),default=0), 'unit': 'S-level'},
              'projected_event_dose_msv': {'value': dose, 'unit': 'mSv'},
              'dose_rate_rising': {'value': engine.storm_at(seconds)[1] > engine.storm_at(max(0,seconds-60))[1]},
              'rapid_pressure_loss': {'value': False}}
    if person is not None:
        inputs.update({code: {'value': False} for code in SYMPTOMS})
        hour = (seconds / 3600 + person['index'] * .25) % 24
        inputs.update({'consciousness': {'value': 'alert'}, 'supplemental_oxygen': {'value': False},
            'hours_awake': {'value': max(0, hour - 6) if 6 <= hour < 22 else 0, 'unit': 'hours'},
            'headache': {'value': 0, 'unit': 'severity 0–3'},
            'urine_colour': {'value': 'pale'},
            'urine_volume': {'value': 2.8, 'unit': 'L/day'},
            'fitness': {'value': 100, 'unit': '% of pre-mission; mL/min/kg',
                        'context': {'quantity': 'percent_of_preflight'}}})
    return inputs


def validate_scenario(engine, data):
    if not isinstance(data, dict) or set(data) - {'name','after','duration','astronaut_id','measurements','context'}:
        raise ValueError('Invalid scenario fields')
    result = deepcopy(data)
    after, duration = result.get('after', 0), result.get('duration')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (after,duration)) or after < 0 or duration <= 0:
        raise ValueError('Scenario requires nonnegative after and positive duration in simulated seconds')
    who = result.get('astronaut_id')
    if who is not None and who not in {p['id'] for p in engine.state['crew']}:
        raise ValueError('Unknown scenario astronaut_id; omit for cabin')
    if not isinstance(result.get('measurements', {}), dict) or not isinstance(result.get('context', {}), dict):
        raise ValueError('Scenario measurements/context must be objects')
    for code, value in result.get('measurements', {}).items():
        if code not in CATALOGUE or CATALOGUE[code][1] != ('astronaut' if who else 'cabin'):
            raise ValueError('Scenario metric does not belong to subject')
        if code == 'is_solar_storm':
            if type(value) is not bool: raise ValueError('Storm presence must be boolean')
        elif type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ValueError('Scenario measurement must be finite and nonnegative')
        elif code in ('spo2','relative_humidity') and value > 100 or code in ('mood','stress_level') and value > 10:
            raise ValueError('Scenario value exceeds scale')
    context=result.get('context', {})
    if 'activity' in context and context['activity'] not in ACTIVITIES:
        raise ValueError('Invalid scenario activity')
    if 'sleep_period' in context and type(context['sleep_period']) is not bool:
        raise ValueError('sleep_period must be a boolean')
    if 'surface_body' in context and context['surface_body'] not in ('moon','mars'):
        raise ValueError('surface_body must be moon or mars')
    # Validate context by JSON encoding now, before it can poison a checkpoint.
    json.dumps(result, allow_nan=False)
    if 'rule_inputs' in result.get('context', {}) and not isinstance(result['context']['rule_inputs'], dict):
        raise ValueError('rule_inputs must be an object')
    for code, entry in context.get('rule_inputs', {}).items():
        if not isinstance(code,str) or not code or len(code)>100 or not isinstance(entry,dict) or 'value' not in entry:
            raise ValueError('Each rule input requires a short code and a value object')
        value=entry['value']
        if type(value) not in (int,float,bool,str):raise ValueError('Rule input value must be scalar')
        if type(value) in (int,float) and (not math.isfinite(value) or value<0 or not isinstance(entry.get('unit'),str) or not entry['unit']):
            raise ValueError('Numeric rule inputs require a finite nonnegative value and explicit unit')
    result['start'] = engine.state['seconds'] + after
    result['end'] = result['start'] + duration
    return result


def apply(engine, events):
    for event in events:
        seconds = (datetime.fromisoformat(event['measured_at'].replace('Z','+00:00')) - engine.start).total_seconds()
        for scenario in engine.state.get('scenarios', []):
            if not scenario['start'] <= seconds < scenario['end'] or event['astronaut_id'] != scenario.get('astronaut_id'):
                continue
            values = scenario.get('measurements', {})
            # The event envelope follows a scenario activity override too.
            if scenario.get('context', {}).get('activity') == 'eva':event['zone_id']='EVA'
            elif 'activity' in scenario.get('context', {}):event['zone_id']='CABIN_MAIN'
            if event['metric'] in values: event['value'] = values[event['metric']]
            context = deepcopy(scenario.get('context', {}))
            inputs = context.pop('rule_inputs', {})
            event['context'].update(context)
            event['context'].setdefault('rule_inputs', {}).update(inputs)
            event['context']['scenario'] = scenario.get('name', 'injected_test')
        validate_event(event)
    return events
