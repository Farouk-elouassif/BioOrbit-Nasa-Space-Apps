"""Crew report authorization, persistence, alert wiring and replay checks."""
import json
from datetime import timedelta
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, SimpleTestCase, TestCase

from .alerts.engine import Frame, Point, evaluate
from .alerts.service import evaluate_run, references
from .ingestion.service import ingest
from .ingestion.validation import validate_payload
from .models import CrewCheckIn, LatestMeasurement, MeasurementEvent, MonitoringAlert, SimulationRun
from .test_alerts import NOW
from .test_ingestion import observation


class InferredRuleTests(SimpleTestCase):
    def test_unplanned_pressure_drop_and_boundaries(self):
        for drop,age,planned,tier in [(7,600,False,'emergency'),(6.9,600,False,None),
                                    (7,601,False,None),(7,600,True,None)]:
            p=Point(90,NOW,'current',{'planned_pressure_change':planned})
            old=Point(90+drop,NOW-timedelta(seconds=age),'old')
            f=Frame(NOW,{'total_cabin_pressure':p},lambda code,start,end:[q for q in [old,p] if start<=q.at<=end],domain='cabin')
            self.assertEqual(evaluate(f)['cabin_pressure']['tier'],tier)

    def test_diastolic_measured_band_and_explicit_override(self):
        for value,tier in [(65,None),(80,'advisory')]:
            f=Frame(NOW,{'diastolic_blood_pressure':Point(value,NOW,'bp',{'activity':'resting'})},lambda *args:[],
                    inflight_baseline={'diastolic_blood_pressure':{'min':64,'max':70,'mean':67}})
            self.assertEqual(evaluate(f)['bp_diastolic']['tier'],tier)
        f.latest['diastolic_drift_from_baseline']=Point(True,NOW,'manual')
        f.latest['diastolic_blood_pressure'].value=67
        self.assertEqual(evaluate(f)['bp_diastolic']['tier'],'advisory')

    def test_ecg_uses_associated_findings(self):
        for symptom,tier in [(None,'caution'),('lightheadedness','warning'),('nausea','warning'),('chest_pain','emergency')]:
            points={'ecg_alarm':Point(True,NOW,'ecg')}
            if symptom:points[symptom]=Point(True,NOW,'symptom')
            f=Frame(NOW,points,lambda *args:[])
            self.assertEqual(evaluate(f)['ecg_flag']['tier'],tier)


class CrewCheckInTests(TestCase):
    def setUp(self):
        ingest(validate_payload(observation()))
        self.user=get_user_model().objects.create_user(username='crew',password='test-crew-pass')
        self.user.user_permissions.add(Permission.objects.get(codename='add_crewcheckin'))
        self.client.force_login(self.user)

    def report(self,**changes):
        data={'id':str(uuid4()),'run_id':'demo-001','astronaut_id':'AST_001','activity':'resting',
              'rule_inputs':{'chest_pain':True},'notes':'Crew observation'}
        data.update(changes)
        return data

    def post(self,data):
        return self.client.post('/api/v1/check-ins',json.dumps(data),content_type='application/json')

    def test_symptom_only_report_persists_and_triggers_without_fake_measurement(self):
        before=MeasurementEvent.objects.count()
        response=self.post(self.report())
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(MeasurementEvent.objects.count(),before)
        dashboard=self.client.get('/api/v1/dashboard',{'run_id':'demo-001'}).json()
        self.assertEqual(dashboard['run']['observation_time'],response.json()['observed_at'])
        self.assertEqual(dashboard['crew'][0]['measurements']['heart_rate']['value'],68)
        self.assertEqual(CrewCheckIn.objects.get().recorded_by,self.user)
        self.assertEqual(MonitoringAlert.objects.get(rule_code='acute_symptoms').tier,'emergency')
        reports=self.client.get('/api/v1/check-ins',{'run_id':'demo-001'}).json()['checkins']
        self.assertEqual(reports[0]['rule_inputs']['chest_pain']['value'],True)

    def test_simulator_negatives_cannot_erase_manual_symptom(self):
        self.assertEqual(self.post(self.report()).status_code,201)
        event=observation(measured_at='2026-11-14T01:01:00Z',context={'activity':'resting','rule_inputs':{'chest_pain':{'value':False}}})
        ingest(validate_payload(event))
        alert=MonitoringAlert.objects.get(rule_code='acute_symptoms')
        self.assertEqual(alert.normal_count,0)
        self.assertEqual(alert.tier,'emergency')
        # A reviewed negative replaces the positive; omission does not.
        response=self.post(self.report(rule_inputs={'chest_pain':False}))
        self.assertEqual(response.status_code,201,response.content)

    def test_all_named_indicators_enter_journal_and_after_meal_low_glucose_alerts(self):
        values={'heart_rate':80,'systolic_blood_pressure':115,'diastolic_blood_pressure':70,
                'body_temperature':37,'blood_glucose':48,'sleep_duration':7,'mood':8}
        data=self.report(measurements=values,meal_context='after_meal',rule_inputs={'consciousness':'alert','supplemental_oxygen':False})
        response=self.post(data)
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(MeasurementEvent.objects.filter(raw_payload__source='crew-checkin').count(),7)
        self.assertEqual(LatestMeasurement.objects.get(metric_id='blood_glucose').numeric_value,48)
        self.assertEqual(MonitoringAlert.objects.get(rule_code='glucose').tier,'caution')

    def test_report_retry_is_idempotent_and_conflict_rejected(self):
        data=self.report(measurements={'blood_glucose':48},meal_context='after_meal')
        first=self.post(data)
        self.assertEqual(first.status_code,201,first.content)
        count=MeasurementEvent.objects.count()
        self.assertEqual(self.post(data).status_code,200)
        self.assertEqual(MeasurementEvent.objects.count(),count)
        self.assertEqual(CrewCheckIn.objects.count(),1)
        self.assertEqual(self.post({**data,'notes':'Changed'}).status_code,409)

    def test_authentication_permission_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.post(self.report()).status_code,401)
        other=get_user_model().objects.create_user(username='viewer',password='viewer-pass')
        self.client.force_login(other)
        self.assertEqual(self.post(self.report()).status_code,403)
        secure=Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post('/api/v1/check-ins',json.dumps(self.report()),content_type='application/json').status_code,403)
        cookie=secure.get('/api/v1/session').cookies['csrftoken'].value
        response=secure.post('/api/v1/check-ins',json.dumps(self.report()),content_type='application/json',HTTP_X_CSRFTOKEN=cookie)
        self.assertEqual(response.status_code,201,response.content)

    def test_invalid_findings_cannot_be_silently_ignored(self):
        for changes in [{'rule_inputs':{'chest_pain':'yes'}},{'measurements':{'spo2':101}},
                        {'rule_inputs':{'unknown_flag':True}},{'astronaut_id':'AST_999'},
                        {'measurements':{'blood_glucose':48}}]:
            self.assertIn(self.post(self.report(**changes)).status_code,(404,422))
        self.assertFalse(CrewCheckIn.objects.exists())

    def test_signed_in_ecg_alarm_reaches_engine(self):
        response=self.post(self.report(rule_inputs={'ecg_alarm':True,'lightheadedness':True}))
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(MonitoringAlert.objects.get(rule_code='ecg_flag').tier,'warning')

    def test_pressure_loss_is_inferred_through_ingestion(self):
        from .test_ingestion import cabin
        for value,minute in [(101,0),(93,5)]:
            ingest(validate_payload(cabin(metric='total_cabin_pressure',unit='kPa',value=value,
                measured_at=f'2026-11-14T01:{minute:02}:00Z')))
        self.assertEqual(MonitoringAlert.objects.get(rule_code='cabin_pressure').tier,'emergency')

    def test_session_login_requires_csrf_and_report_permission(self):
        secure=Client(enforce_csrf_checks=True)
        credentials=json.dumps({'username':'crew','password':'test-crew-pass'})
        self.assertEqual(secure.post('/api/v1/session',credentials,content_type='application/json').status_code,403)
        token=secure.get('/api/v1/session').cookies['csrftoken'].value
        response=secure.post('/api/v1/session',credentials,content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(response.json()['can_checkin'])
        self.assertFalse(secure.get('/api/v1/check-ins',{'run_id':'demo-001'}).json()['checkins'])

    def test_diastolic_reference_is_built_from_history_and_triggers(self):
        anchor=NOW+timedelta(days=3)
        events=[observation(metric='diastolic_blood_pressure',unit='mmHg',value=67,
                    measured_at=(anchor-timedelta(hours=h)).isoformat()) for h in range(48,23,-1)]
        events.append(observation(metric='diastolic_blood_pressure',unit='mmHg',value=80,measured_at=anchor.isoformat()))
        ingest(validate_payload({'schema_version':'1.0','events':events}))
        self.assertEqual(MonitoringAlert.objects.get(rule_code='bp_diastolic').tier,'advisory')
