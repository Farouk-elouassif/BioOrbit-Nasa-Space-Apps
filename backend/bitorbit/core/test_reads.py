"""Operational read contract and PostgreSQL-backed dashboard integration tests."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from .ingestion.service import ingest
from .ingestion.validation import validate_payload
from .models import Astronaut, Mission, SimulationRun
from .queries.dashboard import ReadError, reading
from .test_ingestion import observation, cabin, profile


class ReadSerializationTests(SimpleTestCase):
    def test_false_and_zero_values_and_simulated_freshness(self):
        when=timezone.now()
        source=SimpleNamespace(raw_payload={'source':'bioorbit-simulator','simulated':True},emitted_at=when,received_at=when)
        row=SimpleNamespace(metric_id='is_solar_storm',numeric_value=None,boolean_value=False,metric=SimpleNamespace(unit='boolean'),
                            measured_at=when,source_event=source,source_event_id='uuid',context={})
        result=reading(row,when+timedelta(seconds=1000))
        self.assertIs(result['value'],False)
        self.assertEqual(result['freshness'],'overdue')
        row.metric_id='heart_rate';row.numeric_value=0;row.boolean_value=None
        self.assertEqual(reading(row,when)['value'],0)
        self.assertEqual(reading(row,when)['freshness'],'current')
        self.assertEqual(reading(row,when-timedelta(seconds=10))['age_simulated_seconds'],0)


@override_settings(ROOT_URLCONF='core.urls')
class ReadRequestTests(SimpleTestCase):
    @patch('core.read_views.dashboard',return_value={'run':None,'crew':[]})
    def test_dashboard_is_read_only_and_does_not_need_ingestion_token(self,service):
        response=self.client.get('/dashboard',{'run_id':'demo-001'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertEqual(response.json()['crew'],[])
        self.assertEqual(service.call_args.args[0]['run_id'],'demo-001')
        self.assertEqual(self.client.post('/dashboard').status_code,405)

    @patch('core.read_views.trends',return_value={'points':[]})
    def test_empty_trends_are_not_fabricated(self,service):
        self.assertEqual(self.client.get('/trends').json()['points'],[])

    @patch('core.read_views.trends',side_effect=ReadError('Unknown run',404))
    def test_query_errors(self,service):
        response=self.client.get('/trends')
        self.assertEqual(response.status_code,404)
        self.assertEqual(response.json()['message'],'Unknown run')

    @patch('core.read_views.dashboard',side_effect=OperationalError('offline'))
    def test_database_error_is_retryable(self,service):
        with self.assertLogs('core.read_views',level='ERROR'):
            response=self.client.get('/dashboard')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('offline',response.content.decode())


@override_settings(ROOT_URLCONF='core.urls')
class ReadDatabaseTests(TestCase):
    def insert(self,records):
        return ingest(validate_payload({'schema_version':'1.0','events':records}))

    def test_dashboard_empty_database(self):
        data=self.client.get('/dashboard').json()
        self.assertIsNone(data['run'])
        self.assertEqual(data['crew'],[])

    def test_ingested_crew_measurements_baseline_and_cabin(self):
        self.insert([observation(),observation(astronaut_id='AST_002',value=75),cabin(),profile()])
        response=self.client.get('/dashboard')
        self.assertEqual(response.status_code,200,response.content)
        data=response.json()
        self.assertEqual(len(data['crew']),2)
        self.assertEqual(data['run']['id'],'demo-001')
        self.assertEqual(data['run']['mission_day'],1)
        person=data['crew'][0]
        self.assertEqual(person['measurements']['heart_rate']['value'],68)
        self.assertEqual(person['baselines']['heart_rate']['count'],14)
        self.assertEqual(person['heart_rate_history'][0]['value'],68)
        self.assertIs(data['cabin']['measurements']['is_solar_storm']['value'],False)
        self.assertFalse(data['alerts_available'])

    def test_run_filter_does_not_mix_other_run_participants(self):
        self.insert([observation(),observation(run_id='next-run',astronaut_id='AST_002',value=90)])
        data=self.client.get('/dashboard',{'run_id':'demo-001'}).json()
        self.assertEqual([p['id'] for p in data['crew']],['AST_001'])
        self.assertEqual(data['crew'][0]['measurements']['heart_rate']['value'],68)
        self.assertEqual(self.client.get('/dashboard',{'run_id':'missing'}).status_code,404)
        self.assertEqual(self.client.get('/dashboard',{'run_id':'demo-001','habitat_id':'missing'}).status_code,404)

    def test_history_aggregates_real_observations_and_accepts_alias(self):
        self.insert([observation(value=60),observation(value=80,measured_at='2026-11-14T01:30:00Z')])
        response=self.client.get('/trends',{'run_id':'demo-001','astronaut_id':'AST_001','metric':'heart_rate','window':'24h'})
        self.assertEqual(response.status_code,200,response.content)
        points=response.json()['points']
        self.assertEqual(len(points),1)
        self.assertEqual(points[0]['value'],70)
        self.assertEqual(points[0]['count'],2)
        self.assertEqual(self.client.get('/trends',{'run_id':'demo-001','astronaut_id':'AST_001','metric':'glucose'}).status_code,200)

    def test_history_validation_and_missing_metric_data(self):
        self.insert([observation()])
        query={'run_id':'demo-001','astronaut_id':'AST_001','metric':'body_temperature'}
        self.assertEqual(self.client.get('/trends',query).json()['points'],[])
        for change in ({'window':'forever'},{'metric':'unknown'},{'astronaut_id':'missing'}):
            self.assertIn(self.client.get('/trends',{**query,**change}).status_code,(404,422))

    def test_interval_totals_sum_and_cumulative_values_take_maximum(self):
        self.insert([observation(metric='fluid_intake',unit='L',value=.5),
                     observation(metric='fluid_intake',unit='L',value=.7,measured_at='2026-11-14T02:00:00Z'),
                     observation(metric='mission_cumulative_radiation_dose',unit='mSv',value=1),
                     observation(metric='mission_cumulative_radiation_dose',unit='mSv',value=2,measured_at='2026-11-14T02:00:00Z')])
        for metric,expected,aggregation in [('fluid_intake',1.2,'sum'),('mission_cumulative_radiation_dose',2,'max')]:
            data=self.client.get('/trends',{'run_id':'demo-001','astronaut_id':'AST_001','metric':metric,'window':'7d'}).json()
            self.assertAlmostEqual(data['points'][0]['value'],expected)
            self.assertEqual(data['aggregation'],aggregation)
