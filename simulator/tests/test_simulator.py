import json
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from space_sim.cli import main
from space_sim.contracts import CATALOGUE, timestamp, validate_event
from space_sim.model import Config, DAY, Engine, PERIODIC, RADIATION, activity_at
from space_sim.storage import Store
from space_sim.transport import Client, DeliveryError


def engine(**kwargs):
    e = Engine(Config(**kwargs))
    e.preflight_events(); e.initial_events()
    return e


def comparable(events):
    return [{k: v for k, v in e.items() if k != 'emitted_at'} for e in events]


class ModelTests(unittest.TestCase):
    def test_preflight_profiles_statistics_and_units(self):
        e = Engine(Config()); events = e.preflight_events()
        self.assertEqual(len(e.state['crew']), 3)
        profiles = [v for v in events if v['kind'] == 'preflight_profile']
        self.assertEqual(len(profiles), 3)
        for c, profile in zip(e.state['crew'], profiles):
            self.assertEqual(len(c['samples']), 14)
            self.assertEqual(len(c['statistics']), 12)
            self.assertGreater(c['baseline']['systolic_blood_pressure'], c['baseline']['diastolic_blood_pressure'])
            self.assertGreater(c['baseline']['heart_rate'], 40)
            self.assertLess(c['baseline']['heart_rate'], 100)
            self.assertEqual(profile['profile']['preflight_radiation_unit'], 'mSv/year')
            self.assertEqual(profile['profile']['career_radiation_unit'], 'mSv')
            for metric, stats in c['statistics'].items():
                self.assertAlmostEqual(stats['mean'], sum(row[metric] for row in c['samples']) / 14)
                self.assertGreaterEqual(stats['stddev'], 0)
        self.assertEqual(len({c['baseline']['heart_rate'] for c in e.state['crew']}), 3)
        times = [v['measured_at'] for v in events]
        self.assertEqual(times, sorted(times))
        for event in events:
            validate_event(event)

    def test_seed_reproducibility(self):
        a, b = engine(), engine()
        self.assertEqual(comparable(a.advance(6*3600)), comparable(b.advance(6*3600)))
        self.assertEqual(a.state['crew'], b.state['crew'])
        self.assertNotEqual(a.state['crew'][0]['baseline'], engine(seed=43).state['crew'][0]['baseline'])

    def test_activity_effect_and_schedule(self):
        e = engine(astronauts=1)
        e.advance(5*3600); sleeping = e.state['crew'][0]['values']['heart_rate']
        e.advance(2.5*3600); exercising = e.state['crew'][0]['values']['heart_rate']
        self.assertGreater(exercising, sleeping + 40)
        self.assertGreater(e.state['crew'][0]['values']['respiratory_rate'], 20)
        self.assertEqual(activity_at(0, 0), 'sleeping')
        self.assertEqual(activity_at(3*DAY+14*3600, 0), 'eva')

    def test_periodic_schedules_not_lost_by_sparse_sampling(self):
        e = engine(astronauts=1)
        events = e.advance(DAY)
        for metric, interval in PERIODIC.items():
            actual = [v for v in events if v['metric'] == metric]
            expected = 1 if metric in ('sleep_duration', 'mood') else int(DAY/interval)
            self.assertEqual(len(actual), expected, metric)
            for v in actual:
                seconds = (timestamp(v['measured_at'])-e.start).total_seconds()
                self.assertEqual(seconds % interval, 21600 if metric in ('sleep_duration', 'mood') else 0)
        self.assertLess(len([v for v in events if v['metric']=='mood']), len([v for v in events if v['metric']=='body_temperature']))
        self.assertTrue(all(v['context']['meal_context'] in ('fasting','after_meal') for v in events if v['metric']=='blood_glucose'))

    def test_sleep_summary_matches_schedule(self):
        e = engine(astronauts=1)
        first = [v for v in e.advance(6*3600) if v['metric']=='sleep_duration'][0]
        self.assertAlmostEqual(first['value'], 6*e.state['crew'][0]['sleep_quality'], places=6)
        second = [v for v in e.advance(DAY) if v['metric']=='sleep_duration'][0]
        self.assertAlmostEqual(second['value'], 8*e.state['crew'][0]['sleep_quality'], places=6)

    def test_cabin_coherence_and_physical_consistency(self):
        e = engine(); readings = []
        for _ in range(20):
            events = e.advance(5)
            cabin = e.state['cabin']; readings.append(dict(cabin))
            self.assertLess(cabin['o2_partial_pressure'], cabin['total_cabin_pressure']*7.50062)
            self.assertTrue(all(v['astronaut_id'] is None for v in events if v['domain']=='cabin'))
        for previous, current in zip(readings, readings[1:]):
            self.assertLess(abs(current['cabin_temperature']-previous['cabin_temperature']), .1)
            self.assertLess(abs(current['co2_partial_pressure']-previous['co2_partial_pressure']), .1)
        self.assertLess(e.state['crew'][0]['values']['heart_rate'], e.state['crew'][0]['baseline']['heart_rate'])

    def test_storm_persists_rises_and_recovers(self):
        e = engine(astronauts=1); e.add_storm(600, 7200, 15)
        self.assertFalse(e.storm_at(599)[0]); self.assertTrue(e.storm_at(600)[0])
        self.assertAlmostEqual(e.storm_at(4200)[1], 15)
        e.advance(4200)
        peak_cabin = e.state['cabin']['radiation_level']
        peak_person = e.state['crew'][0]['values']['personal_radiation_dose_rate']
        self.assertGreater(peak_cabin, 12); self.assertGreater(peak_person, 8)
        events = e.advance(4*3600)
        self.assertFalse(e.storm_at(e.state['seconds'])[0])
        self.assertLess(e.state['cabin']['radiation_level'], 2.)
        self.assertTrue(all(type(v['value']) is bool for v in events if v['metric']=='is_solar_storm'))

    def test_short_storm_is_integrated_between_sparse_observations(self):
        normal=engine(astronauts=1);storm=engine(astronauts=1)
        storm.add_storm(20,30,200)
        normal.advance(300);storm.advance(300)
        self.assertGreater(storm.state['crew'][0]['mission_dose'],normal.state['crew'][0]['mission_dose'])
        self.assertFalse(storm.storm_at(300)[0])

    def test_environment_radiation(self):
        for environment, target in RADIATION.items():
            e = engine(environment=environment)
            e.advance(3600)
            self.assertAlmostEqual(e.state['cabin']['radiation_level'], target, delta=.08)

    def test_radiation_trapezoid_integral_and_career(self):
        e = engine(astronauts=1)
        c = e.state['crew'][0]; before = c['values']['personal_radiation_dose_rate']
        e.advance(60)
        after = c['values']['personal_radiation_dose_rate']
        self.assertAlmostEqual(c['mission_dose'], (before+after)*.5*60/DAY, places=12)
        values = {v['metric']:v['value'] for v in e.advance(60) if v['astronaut_id']==c['id']}
        self.assertAlmostEqual(values['total_career_radiation_dose'], values['mission_cumulative_radiation_dose']+c['baseline']['preflight_career_radiation_dose'], places=7)
        initial = c['mission_dose']; e.advance(DAY)
        self.assertGreater(c['mission_dose'], initial)

    def test_event_contract_and_unique_ordered_stream(self):
        e = engine(); events=[]
        for _ in range(100):events.extend(e.advance(5))
        for v in events:validate_event(v)
        self.assertEqual(len(events), len({v['event_id'] for v in events}))
        self.assertEqual([v['measured_at'] for v in events], sorted(v['measured_at'] for v in events))
        original=dict(events[0]); original['unit']='invalid'
        with self.assertRaises(ValueError):validate_event(original)
        original=dict(events[0]); original['value']=True
        with self.assertRaises(ValueError):validate_event(original)
        original=dict(events[0]); original['value']=float('nan')
        with self.assertRaises(ValueError):validate_event(original)

    def test_configuration_and_duration_validation(self):
        for kwargs in ({'speed':0},{'astronauts':0},{'environment':'earth'},{'duration_days':float('nan')}):
            with self.assertRaises(ValueError):engine(**kwargs)
        e = engine(duration_days=.01); e.advance(3600)
        self.assertEqual(e.state['seconds'], DAY*.01)
        self.assertEqual(e.advance(5), [])
        with self.assertRaises(ValueError):e.add_storm(-10, 1, 10)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'state.sqlite3'
        self.store=Store(self.path);self.store.initialize(Config())
    def tearDown(self):
        self.store.close();self.directory.cleanup()
    def test_restart_exact_continuation_no_double_count(self):
        expected = engine(); expected.advance(300); expected_events=expected.advance(300)
        self.store.advance(delta=300); dose=self.store.load().state['crew'][0]['mission_dose']
        self.store.close();self.store=Store(self.path)
        self.assertEqual(self.store.load().state['crew'][0]['mission_dose'],dose)
        self.store.advance(delta=300)
        self.assertEqual(self.store.load().state['crew'],expected.state['crew'])
        events=list(self.store.events())[-len(expected_events):]
        self.assertEqual(comparable(events),comparable(expected_events))
    def test_acceleration_history_then_live(self):
        self.store.advance(delta=DAY)
        self.store.control('speed',value=60)
        self.store.advance(real_interval=5)
        self.assertEqual(self.store.load().state['seconds'],DAY+300)
        times=[v['measured_at'] for v in self.store.events()]
        self.assertEqual(times,sorted(times))
    def test_atomic_rollback(self):
        before=self.store.count();seconds=self.store.load().state['seconds']
        original=self.store._save
        def fail(engine,events):
            original(engine,events)
            raise RuntimeError('simulated crash before commit')
        with patch.object(self.store,'_save',side_effect=fail):
            with self.assertRaises(RuntimeError):self.store.advance(delta=300)
        self.assertEqual(self.store.count(),before)
        self.assertEqual(self.store.load().state['seconds'],seconds)
    def test_controls_and_export(self):
        self.store.control('storm',after=0,duration=7200,peak=10)
        self.store.advance(delta=3600)
        self.assertGreater(self.store.load().state['cabin']['radiation_level'],8)
        self.store.control('normal');self.store.advance(delta=3600)
        self.assertLess(self.store.load().state['cabin']['radiation_level'],2)
        self.store.control('environment',value='surface_base')
        output=Path(self.directory.name)/'events.jsonl';self.store.export(output)
        events=[json.loads(v) for v in output.read_text().splitlines()]
        self.assertEqual(len(events),self.store.count())
        self.assertFalse(output.with_name(output.name+'.tmp').exists())
    def test_cli_bounded_sample(self):
        self.assertEqual(main(['--state',str(self.path),'live','--ticks','2','--interval','.001','--speed','1000']),0)
        self.assertAlmostEqual(self.store.load().state['seconds'],2)
        self.assertEqual(main(['--state',str(self.path),'reset','--confirm','--run-id','next']),0)
        self.assertEqual(self.store.load().state['seconds'],0)
        self.assertEqual(main(['--state',str(self.path),'init']),1)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.store=Store(Path(self.directory.name)/'state.sqlite3');self.store.initialize(Config())
    def tearDown(self):self.store.close();self.directory.cleanup()
    def test_real_http_failure_retry_ack_replay_and_single(self):
        captured=[];calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                events=payload.get('events',[payload]);calls.append(events)
                if len(calls)==1:
                    self.send_response(503);self.end_headers();return
                captured.extend(events)
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'accepted_event_ids':[v['event_id'] for v in events]}).encode())
        try:
            server=HTTPServer(('127.0.0.1',0),Handler)
        except PermissionError:
            self.skipTest('Execution sandbox denies local sockets; run this integration test on your machine')
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/ingest'
            client=Client(url,backoff=0)
            batch=self.store.pending(client.destination,5)
            client.send(batch);self.store.acknowledge(client.destination,batch)
            self.assertEqual(calls[0],calls[1])
            self.assertEqual(len(captured),5)
            self.assertNotEqual(self.store.pending(client.destination,1)[0]['event_id'],batch[0]['event_id'])
            self.assertEqual(len(self.store.pending(Client(url+'/other').destination,5)),5)
            single=Client(url,single=True);single.flush(self.store,max_batches=1)
            self.assertEqual(len(calls[-1]),1)
            self.assertEqual(len(captured),6)
        finally:server.shutdown();thread.join();server.server_close()
    def test_http_request_encoding_retries_success_and_resume(self):
        calls=[];client=Client('http://localhost:8000/ingest',token='test-token',backoff=0)
        class Response:
            def __init__(self,events):self.events=events
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'accepted_event_ids':[e['event_id'] for e in self.events]}).encode()
        def receive(request,**kwargs):
            calls.append(request)
            if len(calls)==1:raise urllib.error.HTTPError(client.url,503,'Unavailable',{},None)
            payload=json.loads(request.data)
            return Response(payload.get('events',[payload]))
        with patch('urllib.request.OpenerDirector.open',side_effect=receive):
            self.assertEqual(client.flush(self.store,batch_size=4,max_batches=1),4)
            self.assertEqual(calls[0].data,calls[1].data)
            self.assertEqual(calls[1].get_header('Authorization'),'Bearer test-token')
            self.assertEqual(calls[1].method,'POST')
            first_ids={e['event_id'] for e in json.loads(calls[1].data)['events']}
            self.assertTrue(first_ids.isdisjoint(e['event_id'] for e in self.store.pending(client.destination,4)))
            single=Client(client.url,single=True)
            self.assertEqual(single.flush(self.store,max_batches=1),1)
            self.assertEqual(json.loads(calls[-1].data)['kind'],'measurement')

    def test_permanent_failure_no_ack(self):
        client=Client('http://localhost:9/ingest',backoff=0)
        error=urllib.error.HTTPError(client.url,400,'Bad Request',{},None)
        with patch('urllib.request.OpenerDirector.open',side_effect=error) as request:
            with self.assertRaises(DeliveryError):client.flush(self.store,max_batches=1)
            self.assertEqual(request.call_count,1)
        self.assertEqual(len(self.store.pending(client.destination,10)),10)
    def test_network_retries_and_malformed_ack(self):
        delays=[];client=Client('http://localhost:9/ingest',retries=2,sleeper=delays.append)
        with patch('urllib.request.OpenerDirector.open',side_effect=urllib.error.URLError('offline')) as request:
            with self.assertRaises(DeliveryError):client.send(self.store.pending(client.destination,2))
            self.assertEqual(request.call_count,3)
            self.assertEqual(delays,[.5,1.])
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"accepted_event_ids": []}'
        with patch('urllib.request.OpenerDirector.open',return_value=Response()):
            with self.assertRaises(DeliveryError):client.flush(self.store,max_batches=1)
        self.assertEqual(len(self.store.pending(client.destination,10)),10)
    def test_success_then_ack_crash_replays_identical_ids(self):
        client=Client('http://localhost:9/ingest');seen=[]
        def send(events):seen.append([e['event_id'] for e in events])
        with patch.object(client,'send',side_effect=send):
            with patch.object(self.store,'acknowledge',side_effect=RuntimeError('crash after server accepted')):
                with self.assertRaises(RuntimeError):client.flush(self.store,batch_size=3,max_batches=1)
            client.flush(self.store,batch_size=3,max_batches=1)
        self.assertEqual(seen[0],seen[1])


if __name__=='__main__':unittest.main()
