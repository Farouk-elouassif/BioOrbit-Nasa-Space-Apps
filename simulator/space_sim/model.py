"""Time-based synthetic dynamics, independent of storage and HTTP."""
import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from .contracts import CATALOGUE, ENVIRONMENTS, utcnow, validate_event

DAY = 86400.0
RADIATION = {'transit_spacecraft': 1.8, 'space_station': .35, 'rover': .8, 'surface_base': .67}
FREQUENT = ('heart_rate', 'respiratory_rate', 'spo2', 'personal_radiation_dose_rate',
            'mission_cumulative_radiation_dose', 'total_career_radiation_dose')
PERIODIC = {'systolic_blood_pressure': 3600., 'diastolic_blood_pressure': 3600.,
            'blood_glucose': 14400., 'body_temperature': 1800.,
            'sleep_duration': DAY, 'mood': DAY, 'stress_level': 21600., 'fluid_intake': 21600.}


@dataclass
class Config:
    mission_id: str = 'MARS_001'
    habitat_id: str = 'HAB_001'
    astronauts: int = 3
    environment: str = 'transit_spacecraft'
    seed: int = 42
    start: str = '2026-11-14T00:00:00Z'
    duration_days: float = 180.
    speed: float = 1.
    preflight_days: int = 14
    run_id: str = 'demo-001'

    def validate(self):
        if self.environment not in ENVIRONMENTS:
            raise ValueError('Unsupported environment')
        if not 1 <= self.astronauts <= 100 or not 2 <= self.preflight_days <= 365:
            raise ValueError('Astronauts: 1–100; preflight days: 2–365')
        if not all(math.isfinite(v) and v > 0 for v in (self.speed, self.duration_days)):
            raise ValueError('Speed and duration must be positive finite numbers')
        start = datetime.fromisoformat(self.start.replace('Z', '+00:00'))
        if start.tzinfo is None or start.utcoffset().total_seconds() != 0:
            raise ValueError('Mission start must have a UTC timezone')
        if any(not isinstance(v, str) or not v for v in (self.mission_id, self.habitat_id, self.run_id)):
            raise ValueError('Mission, habitat, and run IDs cannot be empty')
        return self


def tuples(value):
    return tuple(tuples(x) for x in value) if isinstance(value, list) else value


def activity_at(seconds, index):
    """Eight-hour sleep opportunity, staggered exercise, periodic scheduled EVA."""
    hour = (seconds / 3600 + index * .25) % 24
    if hour < 6 or hour >= 22:
        return 'sleeping'
    if 7 + index % 3 <= hour < 8 + index % 3:
        return 'exercising'
    if int(seconds // DAY) % 7 == 3 and 13 <= hour < 15 and index % 2 == 0:
        return 'eva'
    if 8 <= hour < 18:
        return 'working'
    return 'resting'


class Engine:
    def __init__(self, config, state=None):
        self.config = config.validate()
        self.start = datetime.fromisoformat(config.start.replace('Z', '+00:00'))
        self.rng = random.Random(config.seed)
        if state is not None:
            self.state = state
            self.rng.setstate(tuples(state['rng']))
            return
        self.state = {'seconds': 0., 'sequence': 0, 'storms': [], 'next_periodic': {},
                      'crew': [], 'cabin': {}, 'rng': None}
        self._profiles()
        self.state['cabin'] = {'co2_partial_pressure': 2.1, 'o2_partial_pressure': 149.,
                               'total_cabin_pressure': 101.2, 'cabin_temperature': 22.,
                               'relative_humidity': 43., 'noise_level': 49.,
                               'dust_concentration': .015, 'radiation_level': RADIATION[config.environment]}
        for person in self.state['crew']:
            person['values'] = dict(person['baseline'])
            person['values']['stress_level'] = 3.
            person['values']['fluid_intake'] = 0.
            person['values']['personal_radiation_dose_rate'] = RADIATION[config.environment] * person['shielding']
            person['mission_dose'] = 0.
            person['sleep_seconds'] = 0.
            person['sleep_quality'] = .85 + .1 * self.rng.random()
        self.state['next_periodic'] = {k: (6 * 3600. if k in ('sleep_duration', 'mood') else 0.) for k in PERIODIC}

    def _profiles(self):
        # Separate RNG keeps profile generation stable independently of later sampling.
        rng = random.Random(self.config.seed)
        for i in range(self.config.astronauts):
            fitness = rng.uniform(0, 1)
            mass = rng.uniform(60, 85) + fitness * 3
            baseline = {'heart_rate': 72 - fitness * 18 + rng.gauss(0, 1.5),
                        'systolic_blood_pressure': 119 - fitness * 8 + rng.gauss(0, 2),
                        'diastolic_blood_pressure': 78 - fitness * 5 + rng.gauss(0, 1),
                        'blood_glucose': 92 - fitness * 5 + rng.gauss(0, 2),
                        'body_temperature': rng.uniform(36.65, 37.05),
                        'respiratory_rate': 16 - fitness * 3,
                        'spo2': 98 + fitness * .8, 'sleep_duration': rng.uniform(7.3, 8.3),
                        'mood': rng.uniform(7, 9), 'body_mass': mass,
                        'preflight_radiation_level': rng.uniform(1.6, 2.4),
                        'preflight_career_radiation_dose': rng.uniform(8, 160)}
            samples = []
            noise = {'heart_rate': 2., 'systolic_blood_pressure': 3., 'diastolic_blood_pressure': 2.,
                     'blood_glucose': 3., 'body_temperature': .08, 'respiratory_rate': .5,
                     'spo2': .2, 'sleep_duration': .35, 'mood': .4, 'body_mass': .2,
                     'preflight_radiation_level': .04, 'preflight_career_radiation_dose': 0.}
            for day in range(self.config.preflight_days):
                shared = rng.gauss(0, .5)
                sample = {}
                for key, value in baseline.items():
                    observation = value + rng.gauss(0, noise[key])
                    if key in ('heart_rate', 'respiratory_rate'):
                        observation += shared
                    sample[key] = round(max(0, min(100 if key == 'spo2' else 10 if key == 'mood' else float('inf'), observation)), 4)
                samples.append(sample)
            stats = {k: {'mean': statistics.mean(row[k] for row in samples),
                         'stddev': statistics.stdev(row[k] for row in samples),
                         'min': min(row[k] for row in samples), 'max': max(row[k] for row in samples),
                         'count': len(samples), 'unit': CATALOGUE[k][0]} for k in baseline}
            self.state['crew'].append({'id': f'AST_{i+1:03}', 'index': i, 'baseline': baseline,
                                       'samples': samples, 'statistics': stats,
                                       'fitness': fitness, 'shielding': rng.uniform(.78, .95)})

    def iso(self, seconds):
        return (self.start + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')

    def snapshot(self):
        self.state['rng'] = self.rng.getstate()
        return self.state

    def event(self, metric, value, seconds, person=None, phase='inflight', context=None):
        self.state['sequence'] += 1
        identity = f'{self.config.run_id}/{self.config.mission_id}/{self.config.seed}/{self.config.start}/{self.state["sequence"]}'
        event = {'schema_version': '1.0', 'kind': 'measurement', 'event_id': str(uuid5(NAMESPACE_URL, identity)),
                 'run_id': self.config.run_id, 'mission_id': self.config.mission_id,
                 'habitat_id': self.config.habitat_id, 'zone_id': 'CABIN_MAIN' if not person else ('EVA' if activity_at(seconds, person['index']) == 'eva' and phase == 'inflight' else 'CABIN_MAIN'),
                 'astronaut_id': person['id'] if person else None,
                 'domain': 'astronaut' if person else 'cabin', 'phase': phase,
                 'metric': metric, 'value': value if type(value) is bool else round(value, 8),
                 'unit': CATALOGUE[metric][0], 'measured_at': self.iso(seconds), 'emitted_at': utcnow(),
                 'source': 'bioorbit-simulator', 'simulated': True, 'environment': self.config.environment,
                 'context': context or {}}
        if person:
            event['context'].setdefault('activity', 'resting' if phase == 'preflight' else activity_at(seconds, person['index']))
        return validate_event(event)

    def preflight_events(self):
        events = []
        for i, person in enumerate(self.state['crew']):
            person['index'] = i
        # Timestamp-first ordering across the entire crew, never per-astronaut blocks.
        for day in range(self.config.preflight_days):
            seconds = (day - self.config.preflight_days) * DAY
            for person in self.state['crew']:
                for metric, value in person['samples'][day].items():
                    context = {'activity': 'resting'}
                    if metric == 'blood_glucose':
                        context['meal_context'] = 'fasting'
                    events.append(self.event(metric, value, seconds, person, 'preflight', context))
        for person in self.state['crew']:
            profile = self.event('body_mass', person['baseline']['body_mass'], -1., person, 'preflight')
            profile.pop('metric'); profile.pop('value'); profile.pop('unit')
            profile['kind'] = 'preflight_profile'
            profile['profile'] = {'baseline_statistics': person['statistics'],
                                  'preflight_radiation_level': person['baseline']['preflight_radiation_level'],
                                  'preflight_radiation_unit': 'mSv/year',
                                  'career_radiation_dose': person['baseline']['preflight_career_radiation_dose'],
                                  'career_radiation_unit': 'mSv',
                                  'window_start': self.iso(-self.config.preflight_days * DAY),
                                  'window_end': self.iso(-DAY)}
            events.append(validate_event(profile))
        return events

    def storm_at(self, seconds):
        extra = 0.
        active = False
        base = RADIATION[self.config.environment]
        for storm in self.state['storms']:
            t = (seconds - storm['start']) / storm['duration']
            if 0 <= t < 1:
                active = True
                extra += max(0, storm['peak'] - base) * math.sin(math.pi * t) ** 2
        return active, base + extra

    def add_storm(self, start, duration, peak):
        if not all(math.isfinite(v) for v in (start, duration, peak)) or start < self.state['seconds'] or duration <= 0 or peak <= RADIATION[self.config.environment]:
            raise ValueError('Storm must start now/later, have positive duration, and peak above ambient')
        self.state['storms'].append({'start': start, 'duration': duration, 'peak': peak})

    def _smooth(self, old, target, dt, tau, noise=0.):
        alpha = 1 - math.exp(-dt / tau)
        # OU-like correlated process; fluctuations scale with elapsed simulated time.
        return old + alpha * (target - old) + self.rng.gauss(0, noise) * math.sqrt(alpha)

    def _advance(self, end):
        while self.state['seconds'] < end - 1e-8:
            before = self.state['seconds']
            dt = min(60., end - before)
            for storm in self.state['storms']:
                if before < storm['start'] < before + dt:
                    dt = storm['start'] - before
                elif storm['start'] <= before < storm['start'] + storm['duration']:
                    dt = min(dt, storm['duration'] / 24, storm['start'] + storm['duration'] - before)
            t = before + dt
            cabin = self.state['cabin']
            activities = [activity_at(before + dt / 2, i) for i in range(self.config.astronauts)]
            workload = sum({'sleeping': 0., 'resting': .2, 'working': .6, 'exercising': 1.4, 'eva': 0.}[a] for a in activities) / len(activities)
            daily = math.sin(2 * math.pi * (t / DAY - .25))
            targets = {'co2_partial_pressure': 1.9 + workload * .65,
                       'o2_partial_pressure': 149 - workload * .8,
                       'total_cabin_pressure': 101.2,
                       'cabin_temperature': 22 + .7 * daily + workload * .3,
                       'relative_humidity': 42 + workload * 7,
                       'noise_level': 44 + workload * 18,
                       'dust_concentration': (.04 if self.config.environment in ('rover', 'surface_base') else .012) + workload * .004}
            for metric, target in targets.items():
                noise = {'co2_partial_pressure': .025, 'o2_partial_pressure': .08, 'total_cabin_pressure': .02,
                         'cabin_temperature': .025, 'relative_humidity': .15, 'noise_level': .3, 'dust_concentration': .0003}[metric]
                cabin[metric] = max(0, self._smooth(cabin[metric], target, dt, 600, noise))
                if metric == 'relative_humidity':
                    cabin[metric] = min(100., cabin[metric])
            _, radiation_target = self.storm_at(t)
            cabin['radiation_level'] = max(0, self._smooth(cabin['radiation_level'], radiation_target, dt, 120., .008))
            for i, person in enumerate(self.state['crew']):
                a = activities[i]; values = person['values']; baseline = person['baseline']
                exertion = {'resting': 0, 'sleeping': -.18, 'working': .18, 'exercising': 1., 'eva': .65}[a]
                stress = 2.3 + exertion * 2.5 + max(0, cabin['co2_partial_pressure'] - 2.4) * .5
                temperature_shift = min(1., t / (75 * DAY)) * .65
                target_hr = baseline['heart_rate'] + exertion * (65 + person['fitness'] * 12)
                target_rr = baseline['respiratory_rate'] + exertion * 15
                hour = (t / 3600) % 24
                meal_distance = min((hour - meal) % 24 for meal in (7, 12, 18))
                meal = 32 * math.exp(-meal_distance / 1.1) if meal_distance < 4 else 0
                targets_person = {'heart_rate': target_hr, 'respiratory_rate': target_rr,
                                  'spo2': baseline['spo2'] - max(0, exertion) * .6,
                                  'systolic_blood_pressure': baseline['systolic_blood_pressure'] - min(6, t / DAY * .2) + exertion * 20,
                                  'diastolic_blood_pressure': baseline['diastolic_blood_pressure'] - min(4, t / DAY * .15) + exertion * 5,
                                  'blood_glucose': baseline['blood_glucose'] + meal - max(0, exertion) * 5,
                                  'body_temperature': baseline['body_temperature'] + temperature_shift + .14 * daily + max(0, exertion) * .25,
                                  'stress_level': stress,
                                  'mood': baseline['mood'] - max(0, stress - 3) * .3 + daily * .15}
                for metric, target in targets_person.items():
                    noise = .4 if metric == 'heart_rate' else .13 if metric == 'respiratory_rate' else .015 if metric in ('body_temperature', 'spo2') else .1
                    new = self._smooth(values[metric], target, dt, 180 if metric in ('heart_rate', 'respiratory_rate') else 900, noise)
                    upper = 100 if metric == 'spo2' else 10 if metric in ('mood', 'stress_level') else float('inf')
                    values[metric] = max(0, min(upper, new))
                if a == 'sleeping':
                    person['sleep_seconds'] += dt * person['sleep_quality']
                # Fluid is a sum over a six-hour window, not an instantaneous stream.
                values['fluid_intake'] += dt / DAY * (2.5 + max(0, exertion) * 1.5)
                factor = person['shielding'] * (1.55 if a == 'eva' else 1.)
                old_rate = values['personal_radiation_dose_rate']
                rate = cabin['radiation_level'] * factor
                person['mission_dose'] += (old_rate + rate) * .5 * dt / DAY
                values['personal_radiation_dose_rate'] = rate
            self.state['seconds'] = t

    def _emit(self, frequent, periodic):
        t = self.state['seconds']; events = []
        active, _ = self.storm_at(t)
        scenario = 'solar_storm' if active else 'normal'
        context = {'scenario': scenario}
        if frequent:
            for metric, value in self.state['cabin'].items():
                events.append(self.event(metric, value, t, context=dict(context)))
            events.append(self.event('is_solar_storm', active, t, context=dict(context)))
        for person in self.state['crew']:
            for metric in ((*FREQUENT,) if frequent else ()) + tuple(periodic):
                details = dict(context)
                if metric == 'mission_cumulative_radiation_dose':
                    value = person['mission_dose']
                elif metric == 'total_career_radiation_dose':
                    value = person['mission_dose'] + person['baseline']['preflight_career_radiation_dose']
                elif metric == 'sleep_duration':
                    value = person['sleep_seconds'] / 3600
                    details['window'] = 'since_previous_sleep_summary'
                    person['sleep_seconds'] = 0.
                else:
                    value = person['values'][metric]
                if metric == 'fluid_intake':
                    details['window'] = 'since_previous_fluid_summary'
                    person['values'][metric] = 0.
                if metric == 'blood_glucose':
                    hour = t / 3600 % 24
                    details['meal_context'] = 'fasting' if hour < 7 else 'after_meal'
                events.append(self.event(metric, value, t, person, context=details))
        return events

    def initial_events(self):
        periodic = [k for k, due in self.state['next_periodic'].items() if due == 0]
        events = self._emit(True, periodic)
        for key in periodic:
            self.state['next_periodic'][key] += PERIODIC[key]
        return events

    def advance(self, delta):
        if not math.isfinite(delta) or delta <= 0:
            raise ValueError('Time increment must be positive and finite')
        end = min(self.state['seconds'] + delta, self.config.duration_days * DAY)
        if end <= self.state['seconds']:
            return []
        events = []
        while self.state['seconds'] < end - 1e-8:
            boundary = min(end, min(self.state['next_periodic'].values()))
            self._advance(boundary)
            due = [k for k, value in self.state['next_periodic'].items() if value <= boundary + 1e-8]
            frequent = abs(boundary - end) < 1e-8
            events.extend(self._emit(frequent, due))
            for key in due:
                self.state['next_periodic'][key] += PERIODIC[key]
        return events
