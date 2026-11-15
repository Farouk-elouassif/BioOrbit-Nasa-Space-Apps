"""Contract/request checks run offline; database integration tests run via manage.py test."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from .ingestion.catalogue import CATALOGUE, PREFLIGHT_METRICS, WORKBOOK_ALIASES, canonical_metric
from .ingestion.service import latest_key, supersedes
from .ingestion.validation import Conflict, IngestionError, normalize_identifiers, utc, validate_payload
from .models import (
    Astronaut, Habitat, LatestMeasurement, MeasurementEvent, MetricCatalog,
    Mission, MissionCrew, PreflightBaseline, PreflightProfile, SimulationRun,
)


def observation(**changes):
    result = {'schema_version': '1.0', 'kind': 'measurement', 'event_id': str(uuid4()),
              'run_id': 'demo-001', 'mission_id': 'MARS_001', 'habitat_id': 'HAB_001',
              'zone_id': 'CABIN_MAIN', 'astronaut_id': 'AST_001', 'domain': 'astronaut',
              'phase': 'inflight', 'environment': 'transit_spacecraft', 'metric': 'heart_rate',
              'value': 68, 'unit': 'bpm', 'measured_at': '2026-11-14T01:00:00Z',
              'emitted_at': '2026-11-14T10:00:00Z', 'source': 'bioorbit-simulator',
              'simulated': True, 'context': {'activity': 'resting', 'scenario': 'normal'}}
    result.update(changes)
    return result


def profile():
    event = observation(kind='preflight_profile', phase='preflight', measured_at='2026-11-13T23:59:59Z')
    for key in ('metric', 'unit', 'value'):
        event.pop(key)
    event['profile'] = {'baseline_statistics': {
        code: {'mean': 1.5, 'min': 1, 'max': 2, 'stddev': .1, 'count': 14, 'unit': CATALOGUE[code][0]}
        for code in PREFLIGHT_METRICS}, 'preflight_radiation_level': 2.,
        'preflight_radiation_unit': 'mSv/year', 'career_radiation_dose': 40.,
        'career_radiation_unit': 'mSv', 'window_start': '2026-11-01T00:00:00Z',
        'window_end': '2026-11-13T00:00:00Z'}
    return event


def cabin(**changes):
    return observation(**{'domain': 'cabin', 'astronaut_id': None, 'metric': 'is_solar_storm',
                           'unit': 'boolean', 'value': False, 'context': {'scenario': 'normal'}, **changes})


class IngestionValidationTests(SimpleTestCase):
    def test_single_batch_profile_and_boolean(self):
        self.assertEqual(len(validate_payload(observation())), 1)
        data = {'schema_version': '1.0', 'events': [observation(), cabin(), profile()]}
        validated = validate_payload(data)
        self.assertEqual(len(validated), 3)
        self.assertIs(validated[1].payload['value'], False)
        self.assertEqual(len(validated[2].payload['profile']['baseline_statistics']), 12)

    def test_rejects_bad_identifiers_units_types_and_context(self):
        invalid = [{'event_id': 'invalid'}, {'run_id': 'a'*101}, {'metric': 'unknown'},
                   {'unit': 'percent'}, {'value': True}, {'value': -1}, {'value': float('inf')},
                   {'value': 10**4000}, {'astronaut_id': None}, {'domain': 'unknown'},
                   {'environment': []}, {'context': []}, {'context': {'activity': 'unknown'}},
                   {'schema_version': '2.0'}, {'simulated': False}, {'extra': 1},
                   {'measured_at': '2026-11-14T00:00:00'}, {'emitted_at': 'not-a-date'}]
        for updates in invalid:
            with self.subTest(updates=list(updates)), self.assertRaises(IngestionError):
                validate_payload(observation(**updates))
        with self.assertRaises(IngestionError):
            validate_payload(cabin(value=0))
        with self.assertRaises(IngestionError):
            validate_payload(observation(metric='blood_glucose', unit='mg/dL'))
        with self.assertRaises(IngestionError):
            validate_payload(observation(metric='spo2', unit='%', value=101))

    def test_bad_batches_and_profile_statistics(self):
        for payload in (None, [], {'schema_version': '1.0', 'events': []},
                        {'schema_version': '1.0', 'events': [observation()]*3},
                        {'schema_version': '2.0', 'events': [observation()]}):
            with self.assertRaises(IngestionError):
                validate_payload(payload, maximum=2)
        for alteration in ('count', 'mean', 'missing', 'window'):
            event = profile()
            if alteration == 'count': event['profile']['baseline_statistics']['heart_rate']['count'] = True
            if alteration == 'mean': event['profile']['baseline_statistics']['heart_rate']['mean'] = 10
            if alteration == 'missing': event['profile']['baseline_statistics'].pop('mood')
            if alteration == 'window': event['profile']['window_end'] = '2027-01-01T00:00:00Z'
            with self.assertRaises(IngestionError): validate_payload(event)

    def test_same_batch_conflicts_and_input_not_mutated(self):
        event = observation(); original = deepcopy(event)
        validate_payload(event)
        self.assertEqual(event, original)
        self.assertEqual(len(validate_payload({'schema_version': '1.0', 'events': [event, event]})), 2)
        with self.assertRaises(Conflict) as raised:
            validate_payload({'schema_version': '1.0', 'events': [event, {**event, 'value': 90}]})
        self.assertEqual(raised.exception.index, 1)

    def test_all_workbook_aliases_keep_raw_input_and_canonical_projection(self):
        for alias, canonical in WORKBOOK_ALIASES.items():
            unit, domain = CATALOGUE[canonical]
            data = observation(metric=alias, unit=unit, domain=domain, value=8,
                               astronaut_id='AST_001' if domain=='astronaut' else None)
            if canonical=='blood_glucose':data['context']['meal_context']='fasting'
            original=deepcopy(data)
            item=validate_payload(data)[0]
            self.assertEqual(item.payload['metric'],canonical)
            self.assertEqual(item.raw_payload,original)
            self.assertEqual(data,original)

    def test_domain_specific_radiation_mapping(self):
        for domain, canonical in [('cabin','radiation_level'),('astronaut','personal_radiation_dose_rate')]:
            item=validate_payload(observation(metric='rad_rate',unit='mSv/day',domain=domain,
                                    astronaut_id='AST_001' if domain=='astronaut' else None))[0]
            self.assertEqual(item.payload['metric'],canonical)
        self.assertEqual(canonical_metric('rad_cumulative','astronaut'),'total_career_radiation_dose')
        with self.assertRaises(IngestionError):
            validate_payload(cabin(metric='solar_storm',unit='boolean'))

    def test_equivalent_units_and_semantic_unit_mismatch(self):
        for alias, unit, expected in [('heart_rate','beats/min','bpm'),('sleep_hours','h/night','hours'),
                                      ('mood','0–10 slider','0–10'),('stress','0–10 slider','0–10')]:
            item=validate_payload(observation(metric=alias,unit=unit,value=8))[0]
            self.assertEqual(item.payload['unit'],expected)
            self.assertEqual(item.raw_payload['unit'],unit)
        with self.assertRaises(IngestionError):
            validate_payload(observation(metric='fluid_intake',unit='L/day',value=2.5))
        with self.assertRaises(IngestionError):
            validate_payload(observation(metric='cabin_o2',unit='%',domain='cabin',astronaut_id=None))

    def test_profile_alias_keys_and_normalized_duplicate_replay(self):
        event=profile();original=deepcopy(event)
        replacements={'systolic_blood_pressure':'bp_systolic','diastolic_blood_pressure':'bp_diastolic',
                      'respiratory_rate':'resp_rate','body_temperature':'core_temp',
                      'blood_glucose':'glucose','sleep_duration':'sleep_hours'}
        stats=event['profile']['baseline_statistics']
        for canonical,alias in replacements.items():stats[alias]=stats.pop(canonical)
        item=validate_payload(event)[0]
        self.assertEqual(item.payload,validate_payload(original)[0].payload)
        self.assertIn('bp_systolic',item.raw_payload['profile']['baseline_statistics'])
        event['profile']['baseline_statistics']['systolic_blood_pressure']=deepcopy(stats['bp_systolic'])
        with self.assertRaises(IngestionError):validate_payload(event)

    def test_alias_and_canonical_forms_share_one_event_identity(self):
        canonical=observation(metric='systolic_blood_pressure',unit='mmHg')
        alias={**canonical,'metric':'bp_systolic'}
        result=validate_payload({'schema_version':'1.0','events':[canonical,alias]})
        self.assertEqual(result[0].payload,result[1].payload)
        self.assertEqual(normalize_identifiers(alias),canonical)
        with self.assertRaises(Conflict):
            validate_payload({'schema_version':'1.0','events':[canonical,{**alias,'value':120}]})

    def test_latest_order_and_keys(self):
        old = SimpleNamespace(measured_at=utc('2026-11-14T01:00:00Z', 'time'), source_event_id=UUID(int=2))
        self.assertFalse(supersedes(validate_payload(observation(measured_at='2026-11-14T00:00:00Z'))[0], old))
        self.assertTrue(supersedes(validate_payload(observation(event_id=str(UUID(int=3))))[0], old))
        self.assertFalse(supersedes(validate_payload(observation(event_id=str(UUID(int=1))))[0], old))
        self.assertEqual(latest_key('run', 'astronaut', 1, 2, 'A', 'hr'), latest_key('run', 'astronaut', 1, 3, 'B', 'hr'))
        self.assertNotEqual(latest_key('run', 'cabin', None, 2, 'A', 'co2'), latest_key('run', 'cabin', None, 2, 'B', 'co2'))


@override_settings(ROOT_URLCONF='core.urls', SIM_INGEST_TOKEN='test-token', INGEST_MAX_BATCH_SIZE=1000,
                   INGEST_MAX_BODY_BYTES=4*1024*1024, DATA_UPLOAD_MAX_MEMORY_SIZE=4*1024*1024)
class IngestionRequestTests(SimpleTestCase):
    def post(self, payload, **kwargs):
        return self.client.post('/ingest/events', json.dumps(payload), content_type='application/json',
                                HTTP_AUTHORIZATION='Bearer test-token', **kwargs)

    @patch('core.views.ingest')
    def test_acknowledgment_and_optional_trailing_slash(self, ingest):
        event = observation()
        ingest.return_value = {'accepted_event_ids': [event['event_id']], 'created_count': 1, 'duplicate_count': 0}
        response = self.post(event)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['accepted_event_ids'], [event['event_id']])
        response = self.client.post('/ingest/events/', json.dumps(event), content_type='application/json', HTTP_AUTHORIZATION='Bearer test-token')
        self.assertEqual(response.status_code, 200)

    @patch('core.views.ingest')
    def test_auth_and_methods(self, ingest):
        self.assertEqual(self.client.get('/ingest/events').status_code, 405)
        self.assertEqual(self.client.post('/ingest/events', '{}', content_type='application/json').status_code, 401)
        with override_settings(SIM_INGEST_TOKEN=''):
            self.assertEqual(self.post(observation()).status_code, 503)
        self.assertFalse(ingest.called)

    @patch('core.views.ingest')
    def test_bad_json_never_reaches_storage(self, ingest):
        for body in ('{', '{"value":NaN}', '{"value":1e999}', '{"a":1,"a":2}', b'\xff'):
            response = self.client.post('/ingest/events', body, content_type='application/json', HTTP_AUTHORIZATION='Bearer test-token')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post(observation(unit='invalid')).status_code, 422)
        self.assertFalse(ingest.called)

    @patch('core.views.ingest')
    def test_limits_and_media_type(self, ingest):
        self.assertEqual(self.client.post('/ingest/events', '{}', content_type='text/plain', HTTP_AUTHORIZATION='Bearer test-token').status_code, 415)
        with override_settings(INGEST_MAX_BODY_BYTES=10):
            self.assertEqual(self.post(observation()).status_code, 413)
        with override_settings(INGEST_MAX_BATCH_SIZE=1):
            self.assertEqual(self.post({'schema_version':'1.0','events':[observation(),observation()]}).status_code, 422)
        self.assertFalse(ingest.called)

    @patch('core.views.ingest', side_effect=Conflict('Payload differs'))
    def test_conflict_response(self, ingest):
        self.assertEqual(self.post(observation()).status_code, 409)

    @patch('core.views.ingest', side_effect=OperationalError('database unavailable'))
    def test_retryable_database_error(self, ingest):
        with self.assertLogs('core.views', level='ERROR'):
            response = self.post(observation())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Retry-After'], '2')
        self.assertNotIn('accepted_event_ids', response.json())


@override_settings(ROOT_URLCONF='core.urls', SIM_INGEST_TOKEN='test-token', INGEST_MAX_BATCH_SIZE=1000,
                   INGEST_MAX_BODY_BYTES=4*1024*1024)
class IngestionDatabaseTests(TestCase):
    def post(self, events):
        payload = events if isinstance(events, dict) else {'schema_version':'1.0','events':events}
        return self.client.post('/ingest/events', json.dumps(payload), content_type='application/json', HTTP_AUTHORIZATION='Bearer test-token')

    def test_batch_persists_metadata_journal_preflight_and_latest(self):
        data = [observation(), cabin(), profile()]
        response = self.post(data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['created_count'], 3)
        self.assertEqual(MeasurementEvent.objects.count(), 3)
        self.assertEqual(LatestMeasurement.objects.count(), 2)
        self.assertEqual(PreflightProfile.objects.count(), 1)
        self.assertEqual(PreflightBaseline.objects.count(), 12)
        for model in (Mission, Habitat, Astronaut, SimulationRun, MissionCrew):
            self.assertEqual(model.objects.count(), 1, model)
        self.assertEqual(MeasurementEvent.objects.count(), 3)
        latest = LatestMeasurement.objects.get(domain='cabin')
        self.assertIs(latest.boolean_value, False)
        self.assertIsNone(latest.numeric_value)
        self.assertEqual(MeasurementEvent.objects.get(event_id=data[0]['event_id']).raw_payload, data[0])

    def test_replay_and_duplicates_inside_batch(self):
        event = observation()
        self.assertEqual(self.post([event,event]).json()['created_count'], 1)
        self.assertEqual(self.post(event).json()['duplicate_count'], 1)
        self.assertEqual(MeasurementEvent.objects.count(), 1)
        self.assertEqual(LatestMeasurement.objects.count(), 1)

    def test_conflicting_id_rolls_back_whole_batch(self):
        event = observation(); self.post(event)
        fresh = observation(run_id='other-run', mission_id='OTHER_MISSION')
        response = self.post([fresh, {**event, 'value': 200}])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(MeasurementEvent.objects.count(), 1)
        self.assertFalse(Mission.objects.filter(mission_code='OTHER_MISSION').exists())
        self.assertEqual(LatestMeasurement.objects.get().numeric_value, 68)

    def test_invalid_batch_writes_nothing(self):
        response = self.post([observation(), observation(unit='invalid')])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(MeasurementEvent.objects.count(), 0)
        self.assertEqual(Mission.objects.count(), 0)

    def test_late_history_does_not_regress_latest_or_environment(self):
        late = observation(measured_at='2026-11-14T06:00:00Z',value=80,environment='surface_base')
        self.assertEqual(self.post(late).status_code, 200)
        self.assertEqual(self.post(observation(value=65)).status_code, 200)
        self.assertEqual(LatestMeasurement.objects.get().numeric_value, 80)
        self.assertEqual(SimulationRun.objects.get().environment, 'surface_base')
        self.assertEqual(MeasurementEvent.objects.count(), 2)

    def test_timestamps_tie_break_deterministically(self):
        for identity, value in ((2,70),(3,71),(1,69)):
            self.assertEqual(self.post(observation(event_id=str(UUID(int=identity)),value=value)).status_code, 200)
        self.assertEqual(LatestMeasurement.objects.get().numeric_value, 71)

    def test_preflight_measurements_do_not_enter_live_view(self):
        response = self.post(observation(phase='preflight'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MeasurementEvent.objects.count(), 1)
        self.assertEqual(LatestMeasurement.objects.count(), 0)

    def test_preflight_profile_immutable_but_replay_safe(self):
        event = profile()
        self.assertEqual(self.post(event).status_code, 200)
        self.assertEqual(self.post(event).status_code, 200)
        self.assertEqual(self.post({**event,'event_id':str(uuid4())}).status_code, 409)
        self.assertEqual(PreflightProfile.objects.count(), 1)
        self.assertEqual(MeasurementEvent.objects.count(), 1)

    def test_existing_run_cannot_move_to_another_mission(self):
        self.post(observation())
        self.assertEqual(self.post(observation(mission_id='OTHER')).status_code, 409)
        self.assertEqual(Mission.objects.count(), 1)

    def test_workbook_alias_stores_canonical_metric_and_preserves_source(self):
        event=observation(metric='bp_systolic',unit='mmHg',value=112)
        self.assertEqual(self.post(event).status_code,200)
        stored=MeasurementEvent.objects.get()
        self.assertEqual(stored.metric_id,'systolic_blood_pressure')
        self.assertEqual(stored.raw_payload['metric'],'bp_systolic')
        self.assertEqual(LatestMeasurement.objects.get().metric_id,'systolic_blood_pressure')
        self.assertFalse(MetricCatalog.objects.filter(code='bp_systolic').exists())
        self.assertEqual(self.post({**event,'metric':'systolic_blood_pressure'}).json()['duplicate_count'],1)
        self.assertEqual(MeasurementEvent.objects.count(),1)

    def test_existing_canonical_event_accepts_alias_replay(self):
        event=observation(metric='respiratory_rate',unit='breaths/min',value=14)
        self.assertEqual(self.post(event).status_code,200)
        self.assertEqual(self.post({**event,'metric':'resp_rate'}).json()['duplicate_count'],1)
        self.assertEqual(MeasurementEvent.objects.count(),1)

    def test_profile_aliases_use_canonical_baseline_foreign_keys(self):
        event=profile()
        stats=event['profile']['baseline_statistics']
        stats['glucose']=stats.pop('blood_glucose')
        self.assertEqual(self.post(event).status_code,200)
        self.assertTrue(PreflightBaseline.objects.filter(metric_id='blood_glucose').exists())
        self.assertFalse(MetricCatalog.objects.filter(code='glucose').exists())
        canonical=deepcopy(event)
        stats=canonical['profile']['baseline_statistics']
        stats['blood_glucose']=stats.pop('glucose')
        self.assertEqual(self.post(canonical).json()['duplicate_count'],1)

    def test_catalogue_conflict_rejects_batch(self):
        MetricCatalog.objects.create(code='heart_rate', domain='astronaut', unit='wrong', value_type='numeric')
        self.assertEqual(self.post(observation()).status_code, 409)
        self.assertEqual(MeasurementEvent.objects.count(), 0)
