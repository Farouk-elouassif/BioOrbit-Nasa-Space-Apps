"""Focused workbook checks plus ingestion/acknowledgment persistence coverage."""
from datetime import datetime, timedelta, timezone
import json
from django.test import SimpleTestCase, TestCase, RequestFactory
from .alerts.engine import Point, Frame, average, evaluate
from .alerts.service import extract_inputs
from .alerts.api import acknowledge_view
from .ingestion.service import ingest
from .ingestion.validation import validate_payload
from .test_ingestion import cabin
from .models import MonitoringAlert

NOW=datetime(2026,11,14,12,tzinfo=timezone.utc)

def frame(metric,value,seconds=0,step=30,domain='astronaut'):
    points=[Point(value,NOW-timedelta(seconds=s),str(s),{'activity':'resting'}) for s in range(seconds,-1,-step)]
    return Frame(NOW,{metric:points[-1]},lambda code,start,end:[p for p in points if start<=p.at<=end],domain=domain)

class AlertRuleTests(SimpleTestCase):
    def test_heart_rate_requires_five_minutes(self):
        self.assertEqual(evaluate(frame('heart_rate',140))['heart_rate']['state'],'pending')
        self.assertEqual(evaluate(frame('heart_rate',140,300))['heart_rate']['tier'],'caution')
    def test_exercise_does_not_trigger_resting_rule(self):
        f=frame('heart_rate',150,300)
        f.latest['heart_rate'].context['activity']='exercising'
        self.assertEqual(evaluate(f)['heart_rate']['state'],'insufficient_data')
    def test_missing_news2_is_not_zero(self):
        d=evaluate(frame('respiratory_rate',16))['news2']
        self.assertEqual(d['state'],'insufficient_data');self.assertIn('consciousness',d['missing'])
    def test_oxygen_absolute_floor_and_co2_window(self):
        self.assertEqual(evaluate(frame('o2_partial_pressure',120,domain='cabin'))['cabin_o2']['tier'],'emergency')
        self.assertIsNone(evaluate(frame('co2_partial_pressure',5,domain='cabin'))['cabin_co2']['tier'])
        self.assertEqual(evaluate(frame('co2_partial_pressure',5,3600,300,'cabin'))['cabin_co2']['tier'],'warning')
    def test_averaging_rejects_gaps_and_uses_time(self):
        p=[Point(2,NOW-timedelta(hours=1),'a'),Point(4,NOW-timedelta(minutes=30),'b')]
        self.assertIsNone(average(p,NOW-timedelta(hours=1),NOW))
        self.assertEqual(average(p,NOW-timedelta(hours=1),NOW,max_gap=1800),3)
    def test_supplemental_inputs_require_types_units_and_cannot_override_metrics(self):
        inputs={'noaa_s_level':{'value':1,'unit':'S-level'},'consciousness':{'value':'alert'},
                'headache':{'value':'severe'},'heart_rate':{'value':200,'unit':'bpm'},
                'projected_event_dose_msv':{'value':220,'unit':'wrong'},'supplemental_oxygen':{'value':False}}
        result=extract_inputs({'rule_inputs':inputs},NOW,'x')
        self.assertEqual(set(result),{'noaa_s_level','consciousness','supplemental_oxygen'})
    def test_storm_boolean_does_not_invent_noaa_alert(self):
        self.assertIsNone(evaluate(frame('is_solar_storm',True,domain='cabin'))['solar_storm']['tier'])

class AlertIntegrationTests(TestCase):
    def send(self,value,minute):
        at=NOW+timedelta(minutes=minute)
        event=cabin(metric='o2_partial_pressure',value=value,unit='mmHg',measured_at=at.isoformat(),emitted_at=at.isoformat())
        ingest(validate_payload(event));return event
    def test_ingestion_duplicate_acknowledgment_and_three_reading_stepdown(self):
        original=self.send(120,0)
        alert=MonitoringAlert.objects.get(rule_code='cabin_o2')
        self.assertEqual(alert.tier,'emergency')
        from .queries.dashboard import dashboard
        snapshot=dashboard({})
        self.assertEqual(snapshot['alerts'][0]['metric_id'],'o2_partial_pressure')
        self.assertEqual(snapshot['cabin']['alerts'][0]['tier'],'emergency')
        ingest(validate_payload(original));alert.refresh_from_db();self.assertEqual(alert.normal_count,0)
        request=RequestFactory().post('/alerts/1/acknowledge',json.dumps({'tier':'emergency'}),content_type='application/json')
        self.assertEqual(acknowledge_view(request,alert.pk).status_code,200)
        alert.refresh_from_db();self.assertTrue(alert.is_active);self.assertIsNotNone(alert.acknowledged_at)
        # One full hour of fresh normal oxygen is needed before normal counts advance.
        for minute in range(1,64):self.send(150,minute)
        alert.refresh_from_db();self.assertEqual(alert.tier,'warning');self.assertTrue(alert.is_active)
        self.assertEqual(alert.normal_count,1)
