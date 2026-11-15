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

class AlertFixRegressionTests(SimpleTestCase):
    def test_work_and_exertion_low_oxygen(self):
        for activity in ('working','exercising','eva'):
            f=frame('spo2',89,300)
            for p in f.history('spo2',360):p.context['activity']=activity
            self.assertEqual(evaluate(f)['spo2']['tier'],'caution')

    def test_sleep_bands_and_resting_drift(self):
        for metric,value,rule in [('heart_rate',45,'heart_rate'),('respiratory_rate',10,'resp_rate')]:
            f=frame(metric,value,300)
            for p in f.history(metric,360):p.context['activity']='sleeping'
            f.baselines['heart_rate']={'min':60,'max':75,'median':68,'stddev':2}
            self.assertIsNone(evaluate(f)[rule]['tier'])

    def test_systolic_tolerance_does_not_suppress_absolute_low(self):
        for value,tier in [(105,None),(90,'caution')]:
            f=frame('systolic_blood_pressure',value)
            f.inflight={'systolic_blood_pressure':{'min':109,'max':115,'mean':112}}
            self.assertEqual(evaluate(f)['bp_systolic']['tier'],tier)

    def test_all_meal_glucose_and_symptoms(self):
        for value,symptom,tier in [(69,None,'advisory'),(53,None,'caution'),(60,'shaking','caution'),(60,'confusion','emergency')]:
            f=frame('blood_glucose',value)
            f.latest['blood_glucose'].context['meal_context']='after_meal'
            if symptom:f.latest[symptom]=Point(True,NOW,symptom)
            self.assertEqual(evaluate(f)['glucose']['tier'],tier)

    def test_partial_news2_escalates_but_missing_is_not_normal(self):
        points={m:[Point(v,NOW-timedelta(seconds=t),m+str(t),{'activity':'resting'}) for t in range(300,-1,-30)]
                for m,v in [('heart_rate',135),('respiratory_rate',26),('spo2',90),('systolic_blood_pressure',88)]}
        f=Frame(NOW,{m:p[-1] for m,p in points.items()},lambda code,start,end:[p for p in points.get(code,[]) if start<=p.at<=end])
        d=evaluate(f)['news2']
        self.assertEqual(d['tier'],'emergency');self.assertEqual(d['evidence']['total'],12)
        self.assertTrue(d['evidence']['partial']);self.assertIn('consciousness',d['missing'])
        self.assertEqual(evaluate(frame('respiratory_rate',16))['news2']['state'],'insufficient_data')

    def test_last_fasting_reading_remains_evaluated(self):
        f=frame('blood_glucose',120)
        f.latest['blood_glucose'].context['meal_context']='after_meal'
        fasting=Point(115,NOW-timedelta(hours=4),'fasting',{'meal_context':'fasting'})
        f._history=lambda code,start,end:[fasting] if code=='blood_glucose' else []
        result=evaluate(f)['glucose']
        self.assertEqual(result['tier'],'advisory')
        self.assertEqual(result['observed_at'],fasting.at)

    def test_partial_news2_rejects_stale_components(self):
        f=frame('respiratory_rate',26)
        f.latest['systolic_blood_pressure']=Point(88,NOW-timedelta(minutes=6),'old',{'activity':'resting'})
        result=evaluate(f)['news2']
        self.assertEqual(result['state'],'insufficient_data')
        self.assertEqual(result['evidence']['total'],3)
        self.assertIn('systolic_blood_pressure',result['missing'])

    def test_post_exertion_suppresses_high_not_low_values(self):
        for value,expected in [(140,'insufficient_data'),(40,'triggered')]:
            f=frame('heart_rate',value,300)
            original=f._history
            exercise=Point(150,NOW-timedelta(minutes=10),'exercise',{'activity':'exercising'})
            f._history=lambda code,start,end: [exercise]+original(code,start,end)
            self.assertEqual(evaluate(f)['heart_rate']['state'],expected)


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


class BatchAlertIntegrationTests(TestCase):
    @staticmethod
    def oxygen(value, seconds, run_id):
        at = NOW + timedelta(seconds=seconds)
        return cabin(metric='o2_partial_pressure', value=value, unit='mmHg',
                     measured_at=at.isoformat(), emitted_at=at.isoformat(), run_id=run_id)

    @staticmethod
    def batch(events):
        return ingest(validate_payload({'schema_version': '1.0', 'events': events}))

    def test_batch_preserves_intermediate_emergency_and_duplicate_replay(self):
        events = [self.oxygen(120, 0, 'batch-emergency'),
                  self.oxygen(150, 5, 'batch-emergency')]
        # Wire order must not change mission-time evaluation order.
        self.batch(list(reversed(events)))
        alert = MonitoringAlert.objects.get(run_id='batch-emergency', rule_code='cabin_o2')
        self.assertEqual(alert.tier, 'emergency')
        self.assertTrue(alert.is_active)
        self.assertEqual(alert.detected_at, NOW)
        self.assertEqual(alert.normal_count, 0)  # No complete normal hour yet.
        result = self.batch(events)
        self.assertEqual(result['created_count'], 0)
        alert.refresh_from_db()
        self.assertEqual(alert.tier, 'emergency')
        self.assertEqual(alert.normal_count, 0)

    def test_batch_and_single_delivery_have_identical_recovery(self):
        for run_id, batched in [('single-recovery', False), ('batch-recovery', True)]:
            events = [self.oxygen(120, 0, run_id)] + [
                self.oxygen(150, minute * 60, run_id) for minute in range(1, 65)]
            if batched:
                self.batch(list(reversed(events)))
            else:
                for event in events:
                    ingest(validate_payload(event))
        fields = ('tier', 'is_active', 'normal_count', 'detected_at',
                  'last_observation_at', 'recheck_due_at', 'resolved_at')
        single = MonitoringAlert.objects.get(run_id='single-recovery', rule_code='cabin_o2')
        batched = MonitoringAlert.objects.get(run_id='batch-recovery', rule_code='cabin_o2')
        self.assertEqual(single.tier, 'warning')
        self.assertEqual(tuple(getattr(single, field) for field in fields),
                         tuple(getattr(batched, field) for field in fields))

    def test_supplemental_emergency_is_not_overwritten_by_later_negative(self):
        events = []
        for seconds in range(5):
            at = NOW + timedelta(seconds=seconds)
            events.append(cabin(metric='total_cabin_pressure', value=101, unit='kPa',
                run_id='batch-facts', measured_at=at.isoformat(), emitted_at=at.isoformat(),
                context={'rule_inputs': {'rapid_pressure_loss': {'value': seconds == 0}}}))
        self.batch(events)
        alert = MonitoringAlert.objects.get(run_id='batch-facts', rule_code='cabin_pressure')
        self.assertEqual(alert.tier, 'warning')  # Three normals lower Emergency one tier.
        self.assertEqual(alert.normal_count, 1)
        self.assertEqual(alert.detected_at, NOW)

    def test_simultaneous_observations_are_evaluated_together(self):
        from unittest.mock import patch
        from .alerts.service import evaluate_run
        from .models import LatestMeasurement
        snapshots = []
        def inspect(run):
            snapshots.append(set(LatestMeasurement.objects.filter(run=run)
                                 .values_list('metric_id', flat=True)))
            evaluate_run(run)
        at = NOW.isoformat()
        events = [self.oxygen(120, 0, 'batch-simultaneous'),
                  cabin(metric='total_cabin_pressure', value=101, unit='kPa',
                        run_id='batch-simultaneous', measured_at=at, emitted_at=at)]
        with patch('core.alerts.service.evaluate_run', side_effect=inspect):
            self.batch(events)
        self.assertEqual(snapshots, [{'o2_partial_pressure', 'total_cabin_pressure'}])

    def test_late_batch_does_not_rewind_current_alert_or_environment(self):
        current = self.oxygen(120, 120, 'late-batch')
        current['environment'] = 'surface_base'
        ingest(validate_payload(current))
        alert = MonitoringAlert.objects.get(run_id='late-batch', rule_code='cabin_o2')
        before = (alert.tier, alert.last_observation_at, alert.normal_count)
        self.batch([self.oxygen(150, seconds, 'late-batch') for seconds in (0, 30, 60)])
        alert.refresh_from_db()
        self.assertEqual((alert.tier, alert.last_observation_at, alert.normal_count), before)
        self.assertEqual(alert.run.environment, 'surface_base')
