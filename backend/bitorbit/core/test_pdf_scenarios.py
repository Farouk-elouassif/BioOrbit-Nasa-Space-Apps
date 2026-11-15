"""PDF threshold boundaries, explicit recovery, and simulator-to-Django scenarios."""
from datetime import timedelta
from pathlib import Path
import sys
from uuid import uuid4
from django.test import SimpleTestCase, TestCase
from .test_alerts import NOW, frame
from .alerts.engine import Point, Frame, evaluate, patterns
from .alerts.service import persist, frame_from_rows
from .models import SimulationRun, Mission, MonitoringAlert, LatestRuleInput, LatestMeasurement
from .ingestion.validation import validate_payload
from .ingestion.service import ingest

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'simulator'))
from space_sim.model import Engine, Config, DAY


class PdfRuleTests(SimpleTestCase):
    def test_pdf_vital_boundaries(self):
        cases=[('heart_rate',40,'caution'),('heart_rate',50,'advisory'),('heart_rate',90,None),
            ('heart_rate',91,'advisory'),('heart_rate',130,'advisory'),('heart_rate',131,'caution'),
            ('respiratory_rate',8,'caution'),('respiratory_rate',9,'advisory'),('respiratory_rate',20,None),
            ('respiratory_rate',21,'advisory'),('respiratory_rate',25,'caution'),
            ('spo2',91,'caution'),('spo2',93,'advisory'),('spo2',95,'advisory'),('spo2',96,None),
            ('systolic_blood_pressure',90,'caution'),('systolic_blood_pressure',100,'advisory'),
            ('systolic_blood_pressure',111,None),('systolic_blood_pressure',220,'caution'),
            ('body_temperature',35,'caution'),('body_temperature',36,'advisory'),
            ('body_temperature',39.1,'advisory')]
        rules={'systolic_blood_pressure':'bp_systolic','body_temperature':'core_temp','respiratory_rate':'resp_rate'}
        for metric,value,tier in cases:
            with self.subTest(metric=metric,value=value):
                self.assertEqual(evaluate(frame(metric,value,300))[rules.get(metric,metric)]['tier'],tier)

    def test_conditional_and_daily_pdf_rules(self):
        cases=[('blood_glucose',60,'glucose',{'meal_context':'fasting'},'advisory'),
               ('blood_glucose',60,'glucose',{'meal_context':'after_meal'},'advisory'),
               ('body_mass',75,'body_mass',{},'advisory')]
        for metric,value,rule,context,tier in cases:
            f=frame(metric,value);f.latest[metric].context.update(context)
            f.baselines['body_mass']={'mean':80}
            self.assertEqual(evaluate(f)[rule]['tier'],tier)
        for metric,flag,value,rule in [('blood_glucose','shaking',60,'glucose'),
            ('systolic_blood_pressure','lightheadedness',88,'bp_systolic'),
            ('body_temperature','symptoms_present',39.4,'core_temp')]:
            f=frame(metric,value);f.latest[metric].context['meal_context']='fasting'
            f.latest[flag]=Point(True,NOW,flag)
            self.assertEqual(evaluate(f)[rule]['tier'],'caution' if metric=='blood_glucose' else 'warning')
        for metric,value,median,rule in [('mood',6,8,'mood'),('stress_level',5,3,'stress')]:
            points=[Point(value,NOW-timedelta(days=d),str(d)) for d in range(3)]
            f=Frame(NOW,{metric:points[0]},lambda code,start,end:[p for p in points if start<=p.at<=end],
                    baselines={metric:{'median':median}})
            self.assertEqual(evaluate(f)[rule]['tier'],'advisory')
        points=[Point(5,NOW-timedelta(days=d),str(d)) for d in range(3)]
        f=Frame(NOW,{'sleep_duration':points[0]},lambda code,start,end:points if code=='sleep_duration' else [])
        self.assertEqual(evaluate(f)['sleep_hours']['tier'],'advisory')
        # Complete non-overlapping six-hour intake summaries across three days.
        fluid=[Point(.4,NOW.replace(hour=0)-timedelta(hours=i*6),str(i),{'interval_seconds':21600}) for i in range(12)]
        f=Frame(NOW,{'fluid_intake':fluid[0]},lambda code,start,end:sorted([p for p in fluid if start<=p.at<=end],key=lambda p:p.at) if code=='fluid_intake' else [])
        self.assertEqual(evaluate(f)['fluid_intake']['tier'],'advisory')

    def test_environment_and_radiation_boundaries(self):
        for metric,rule,value,tier in [('o2_partial_pressure','cabin_o2',121,'emergency'),
            ('o2_partial_pressure','cabin_o2',122,'caution'),('o2_partial_pressure','cabin_o2',145,None),
            ('total_cabin_pressure','cabin_pressure',34.5,None),('total_cabin_pressure','cabin_pressure',104,'caution'),
            ('cabin_temperature','cabin_temp',27,None),('cabin_temperature','cabin_temp',28,'advisory'),
            ('relative_humidity','cabin_humidity',60,None),('relative_humidity','cabin_humidity',61,'advisory'),
            ('total_career_radiation_dose','rad_cumulative',299,None),
            ('total_career_radiation_dose','rad_cumulative',300,'advisory'),
            ('total_career_radiation_dose','rad_cumulative',450,'caution')]:
            with self.subTest(metric=metric,value=value):
                self.assertEqual(evaluate(frame(metric,value,3600,300,'cabin'))[rule]['tier'],tier)
        for body,limit in [('moon',.3),('mars',.1)]:
            for value,tier in [(limit,None),(limit+.001,'caution')]:
                f=frame('dust_concentration',value,domain='cabin');f.environment='surface_base'
                f.latest['dust_concentration'].context['surface_body']=body
                self.assertEqual(evaluate(f)['dust']['tier'],tier)
        for environment,value,tier in [('space_station',1.3,None),('transit_spacecraft',1.31,'advisory'),
                                       ('rover',.9,None),('surface_base',.91,'advisory')]:
            f=frame('radiation_level',value,int(DAY),300,'cabin');f.environment=environment
            self.assertEqual(evaluate(f)['rad_rate']['tier'],tier)

    def test_noise_energy_window_and_work_sleep_context(self):
        for sleeping,value,tier in [(True,50,None),(True,51,'advisory'),(False,60,None),
                                    (False,61,'advisory'),(False,72,'caution')]:
            f=frame('noise_level',value,16*3600,300,'cabin')
            f.latest['noise_level'].context['sleep_period']=sleeping
            history=f._history
            def tagged(*args):
                samples=history(*args)
                for sample in samples:sample.context['sleep_period']=sleeping
                return samples
            f._history=tagged
            self.assertEqual(evaluate(f)['noise']['tier'],tier)

    def test_work_history_cannot_establish_sleep_exposure(self):
        f=frame('noise_level',55,8*3600,300,'cabin')
        history=f._history
        def tagged(*args):
            samples=history(*args)
            for sample in samples:sample.context['sleep_period']=sample.at==NOW
            return samples
        f._history=tagged;f.latest['noise_level'].context['sleep_period']=True
        self.assertEqual(evaluate(f)['noise']['state'],'insufficient_data')

    def test_normal_awake_observation_cannot_clear_missing_sleep_history(self):
        f=frame('sleep_duration',5)
        f.latest['hours_awake']=Point(2,NOW,'awake')
        self.assertEqual(evaluate(f)['sleep_hours']['state'],'insufficient_data')

    def test_patterns_report_normal_and_keep_unknown_inputs_unknown(self):
        points={code:Point(False,NOW,code) for code in ('within_24h_eva','numbness','weakness','new_confusion',
            'breathing_trouble','joint_pain','tingling','skin_change','dose_rate_rising','cabin_event_last24h',
            'spco_rise_after_cabin_event','spmet_rise_after_cabin_event')}
        points['noaa_s_level']=Point(0,NOW,'noaa')
        f=Frame(NOW,points,lambda *args:[]);patterns(f)
        for code in ('pattern_after_eva','pattern_solar_storm','pattern_smoke_toxic'):
            self.assertEqual(f.decisions[code]['state'],'normal')
        f=Frame(NOW,{},lambda *args:[]);patterns(f)
        self.assertEqual(f.decisions['pattern_after_eva']['state'],'insufficient_data')
        points['within_24h_eva'].value=True;points['numbness'].value=True
        f=Frame(NOW,points,lambda *args:[]);patterns(f)
        self.assertEqual(f.decisions['pattern_after_eva']['tier'],'emergency')


class PdfIntegrationTests(TestCase):
    def setUp(self):
        self.engine=Engine(Config(astronauts=1,run_id='pdf-'+str(uuid4()),preflight_days=2))
        events=self.engine.preflight_events()+self.engine.initial_events()
        ingest(validate_payload({'schema_version':'1.0','events':events}))
        self.mission_run=SimulationRun.objects.get(pk=self.engine.config.run_id)

    def send(self, seconds=30):
        events=self.engine.advance(seconds)
        ingest(validate_payload({'schema_version':'1.0','events':events}))
        return events

    def test_supplemental_facts_survive_omission_and_late_replay(self):
        self.engine.add_scenario({'duration':60,'astronaut_id':'AST_001','context':{
            'rule_inputs':{'breathlessness':{'value':True}}}})
        events=self.send()
        fact=LatestRuleInput.objects.get(run=self.mission_run,code='breathlessness')
        self.assertTrue(fact.value)
        # A newer measurement without rule_inputs must not erase the fact.
        e=next(v for v in events if v['metric']=='heart_rate');e['event_id']=str(uuid4())
        e['measured_at']=self.engine.iso(40);e['context'].pop('rule_inputs')
        ingest(validate_payload(e))
        fact.refresh_from_db();self.assertTrue(fact.value)
        rows=list(LatestMeasurement.objects.filter(run=self.mission_run,domain='astronaut').select_related('source_event'))
        f=frame_from_rows(self.mission_run,rows,fact.observed_at+timedelta(seconds=10),fact.observed_at,person=rows[0].astronaut_id)
        self.assertTrue(f.point('breathlessness',3600).value)
        self.send(60);fact.refresh_from_db();self.assertFalse(fact.value)
        e['event_id']=str(uuid4());e['measured_at']=self.engine.iso(35)
        e['context']['rule_inputs']={'breathlessness':{'value':True}}
        ingest(validate_payload(e));fact.refresh_from_db();self.assertFalse(fact.value)

    def test_post_eva_emergency_fully_recovers_and_replay_does_not_count(self):
        self.engine.add_scenario({'duration':60,'astronaut_id':'AST_001','context':{
            'rule_inputs':{'within_24h_eva':{'value':True},'numbness':{'value':True}}}})
        self.send()
        alert=MonitoringAlert.objects.get(run=self.mission_run,rule_code='pattern_after_eva')
        self.assertEqual(alert.tier,'emergency')
        for i in range(12):
            events=self.send()
            ingest(validate_payload({'schema_version':'1.0','events':events}))
        alert.refresh_from_db();self.assertFalse(alert.is_active)
        self.assertIsNotNone(alert.resolved_at)

    def test_synthetic_noaa_storm_trigger_and_recovery(self):
        self.engine.add_scenario({'duration':60,'astronaut_id':'AST_001','context':{'rule_inputs':{
            'noaa_s_level':{'value':2,'unit':'S-level'},'projected_event_dose_msv':{'value':220,'unit':'mSv'},
            'dose_rate_rising':{'value':True}}}})
        self.send()
        alert=MonitoringAlert.objects.get(run=self.mission_run,rule_code='pattern_solar_storm')
        self.assertEqual(alert.tier,'warning')
        for i in range(9):self.send()
        alert.refresh_from_db();self.assertFalse(alert.is_active)

    def test_news2_can_evaluate_from_simulator_spot_checks(self):
        # Establish genuine prior resting observations, spanning a full day and
        # excluding the most recent 24h, then ingest a coherent current spot check.
        for i in range(49):self.send(3600)
        for i in range(11):self.send(30)
        from .models import AlertAssessment
        assessment=AlertAssessment.objects.get(run=self.mission_run,subject_key__startswith='astronaut:')
        self.assertNotEqual(assessment.coverage['news2']['state'],'insufficient_data',assessment.coverage)

    def test_lifecycle_for_every_tier_holds_unknown_and_repeated_observations(self):
        # Isolate the lifecycle from individual thresholds; each tier must traverse
        # every lower tier and resolve only on distinct normal observations.
        for rank,tier in enumerate(('advisory','caution','warning','emergency'),1):
            key='test:'+tier;at=NOW
            def commit(at,state='normal',level=None):
                f=Frame(at,{},lambda *args:[])
                f.decisions['pattern_after_eva']={'tier':level,'state':state,'observed_at':at,
                    'message':'test','evidence':{}}
                persist(self.mission_run,key,'astronaut',f)
            commit(at,level=tier)
            for n in range(1,rank*3+1):
                at+=timedelta(seconds=30);commit(at)
                commit(at)  # repeated evaluation must not advance normal_count
                commit(at+timedelta(seconds=1),state='insufficient_data')
                alert=MonitoringAlert.objects.get(run=self.mission_run,subject_key=key)
                self.assertEqual(alert.is_active,n<rank*3)
