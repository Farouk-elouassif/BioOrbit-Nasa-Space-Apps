"""Foreground CLI: bounded backfill, live ticks, controls, export, and delivery."""
import argparse
import json
import logging
import math
import os
import signal
import sqlite3
import sys
import time
import uuid
from dataclasses import asdict

from .contracts import ENVIRONMENTS
from .model import Config, DAY
from .storage import Store
from .transport import Client, DeliveryError

log = logging.getLogger(__name__)


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('Must be positive and finite')
    return result


def nonnegative(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError('Must be finite and nonnegative')
    return result


def parser():
    p = argparse.ArgumentParser(description='BioOrbit synthetic telemetry service (no clinical interpretation)')
    p.add_argument('--state', default=os.environ.get('SIM_STATE_PATH', 'data/simulation.sqlite3'))
    p.add_argument('--verbose', action='store_true')
    sub = p.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init', help='Initialize stable preflight profiles and mission state')
    init.add_argument('--mission-id', default='MARS_001'); init.add_argument('--habitat-id', default='HAB_001')
    init.add_argument('--astronauts', type=int, default=3); init.add_argument('--seed', type=int, default=42)
    init.add_argument('--environment', choices=ENVIRONMENTS, default='transit_spacecraft')
    init.add_argument('--start', default='2026-11-14T00:00:00Z')
    init.add_argument('--duration-days', type=positive, default=180.)
    init.add_argument('--speed', type=positive, default=1.)
    init.add_argument('--preflight-days', type=int, default=14)
    init.add_argument('--run-id', default='demo-001')
    init.add_argument('--error-level', type=nonnegative, default=0., help='Percentage of in-flight measurements to inject abnormal values into (0–100)')
    init.add_argument('--surface-body', choices=('moon','mars'), default='mars')
    scenario = sub.add_parser('scenario', help='Schedule explicit synthetic measurements/context from JSON')
    scenario.add_argument('--file', required=True)
    history = sub.add_parser('history', help='Append days of mission history to existing state')
    history.add_argument('--days', type=positive, default=30.)
    history.add_argument('--interval', type=positive, default=300., help='Frequent historical sampling, simulated seconds')
    live = sub.add_parser('live', help='Foreground streaming; Ctrl+C stops safely')
    live.add_argument('--interval', type=positive, default=5., help='Real seconds between ticks')
    live.add_argument('--speed', type=positive, help='Override saved simulated seconds per real second')
    live.add_argument('--ticks', type=int, help='Optional finite tick count')
    for target in (history, live):
        target.add_argument('--endpoint', default=os.environ.get('SIM_INGEST_URL'))
        target.add_argument('--batch-size', type=int, default=500)
        target.add_argument('--single', action='store_true')
        target.add_argument('--timeout', type=positive, default=10.)
        target.add_argument('--retries', type=int, default=3)
    export = sub.add_parser('export', help='Atomic JSONL snapshot including profiles')
    export.add_argument('--output', required=True)
    send = sub.add_parser('send', help='Replay all pending events to HTTP endpoint')
    send.add_argument('--endpoint', default=os.environ.get('SIM_INGEST_URL'))
    send.add_argument('--batch-size', type=int, default=500); send.add_argument('--single', action='store_true')
    send.add_argument('--timeout', type=positive, default=10.); send.add_argument('--retries', type=int, default=3)
    storm = sub.add_parser('storm', help='Schedule a persistent solar storm')
    storm.add_argument('--after', type=nonnegative, default=0., help='Simulated seconds from now')
    storm.add_argument('--duration', type=positive, default=21600., help='Simulated seconds')
    storm.add_argument('--peak', type=positive, default=12., help='Cabin target peak, mSv/day')
    storm.add_argument('--noaa-s-level', type=int, choices=range(6), default=1, help='Explicit synthetic severity; not inferred from radiation')
    symptom=sub.add_parser('symptom', help='Report a synthetic symptom until normal clears it')
    symptom.add_argument('--astronaut', required=True)
    from .scenarios import SYMPTOMS
    symptom.add_argument('symptom', choices=SYMPTOMS)
    sub.add_parser('normal', help='Cancel storms; radiation relaxes gradually to ambient')
    speed = sub.add_parser('speed'); speed.add_argument('value', type=positive)
    env = sub.add_parser('environment'); env.add_argument('value', choices=ENVIRONMENTS)
    sub.add_parser('status')
    reset = sub.add_parser('reset', help='Destructively replace this local simulation with a new run identity')
    reset.add_argument('--confirm', action='store_true', required=True)
    reset.add_argument('--run-id', help='Default: fresh UUID; new identity avoids collision with an old run')
    return p


def make_client(args):
    if not args.endpoint:
        return None
    return Client(args.endpoint, os.environ.get('SIM_INGEST_TOKEN'), args.timeout, args.retries, single=args.single)


def run(args):
    store = Store(args.state)
    try:
        if args.command == 'init':
            config = Config(**{key: getattr(args, key) for key in asdict(Config())})
            count = store.initialize(config)
            log.info('Initialized %d astronauts; journaled %d preflight/initial events', config.astronauts, count)
        elif args.command in ('history', 'live'):
            if args.batch_size < 1 or args.retries < 0 or (args.command == 'live' and args.ticks is not None and args.ticks < 1):
                raise ValueError('Batch size/ticks must be positive; retries nonnegative')
            client = make_client(args)
            if args.command == 'live' and args.speed:
                store.control('speed', value=args.speed)
            stopping = False
            def stop(signum, frame):
                nonlocal stopping
                stopping = True
            previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                initial = store.load().state['seconds']
                target = min(initial + args.days * DAY, store.load().config.duration_days * DAY) if args.command == 'history' else None
                ticks = total = 0
                while not stopping:
                    engine = store.load()
                    if engine.state['seconds'] >= engine.config.duration_days * DAY - 1e-8:
                        break
                    if target is not None:
                        remaining = target - engine.state['seconds']
                        if remaining <= 1e-8:
                            break
                        count = store.advance(delta=min(args.interval, remaining))
                    else:
                        # Nominal tick clock: pauses/retries do not silently add mission time.
                        deadline = time.monotonic() + args.interval
                        while not stopping and time.monotonic() < deadline:
                            time.sleep(min(.1, max(0, deadline - time.monotonic())))
                        if stopping:
                            break
                        count = store.advance(real_interval=args.interval)
                    ticks += 1; total += count
                    if client and (target is None or ticks % 20 == 0):
                        try:
                            client.flush(store, args.batch_size, max_batches=4)
                        except DeliveryError as exc:
                            log.error('%s', exc)
                    if ticks % 100 == 0:
                        log.info('Committed %d ticks / %d events; mission day %.3f', ticks, total, store.load().state['seconds']/DAY)
                    if target is None and args.ticks is not None and ticks >= args.ticks:
                        break
                if client and not stopping:
                    client.flush(store, args.batch_size)
                log.info('Stopped with state saved: %d ticks, %d new events, day %.6f', ticks, total, store.load().state['seconds']/DAY)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
        elif args.command == 'export':
            store.load(); store.export(args.output)
            log.info('Exported %d events to %s', store.count(), args.output)
        elif args.command == 'send':
            client = make_client(args)
            if client is None:
                raise ValueError('Provide --endpoint or SIM_INGEST_URL')
            log.info('Delivered %d events', client.flush(store, args.batch_size))
        elif args.command == 'scenario':
            with open(args.file, encoding='utf-8') as handle:
                store.control('scenario', data=json.load(handle))
            log.info('Synthetic scenario scheduled')
        elif args.command == 'symptom':
            store.control('symptom', astronaut=args.astronaut, symptom=args.symptom)
            log.info('Synthetic symptom recorded')
        elif args.command == 'storm':
            store.control('storm', after=args.after, duration=args.duration, peak=args.peak, noaa_s_level=args.noaa_s_level)
            log.info('Solar storm scheduled')
        elif args.command in ('normal', 'speed', 'environment'):
            store.control(args.command, **({'value': args.value} if hasattr(args, 'value') else {}))
            log.info('Control applied: %s', args.command)
        elif args.command == 'reset':
            engine = store.load()
            engine.config.run_id = args.run_id or str(uuid.uuid4())
            if engine.config.run_id == json.loads(store.db.execute('SELECT config FROM checkpoint').fetchone()[0])['run_id']:
                raise ValueError('Reset requires a new run ID; use a separate state path for identical replay')
            store.reset(engine.config)
            log.info('Reset to new run %s', engine.config.run_id)
        elif args.command == 'status':
            engine = store.load()
            print(json.dumps({'config': asdict(engine.config), 'mission_seconds': engine.state['seconds'],
                              'measured_at': engine.iso(engine.state['seconds']), 'events': store.count(),
                              'storms': engine.state['storms'],
                              'crew': [{'astronaut_id': c['id'], 'mission_dose_mSv': c['mission_dose'],
                                        'preflight_career_dose_mSv': c['baseline']['preflight_career_radiation_dose'],
                                        'total_career_dose_mSv': c['baseline']['preflight_career_radiation_dose']+c['mission_dose']}
                                       for c in engine.state['crew']]}, indent=2))
        return 0
    finally:
        store.close()


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    try:
        return run(args)
    except (ValueError, OSError, sqlite3.Error, DeliveryError) as exc:
        log.error('%s', exc)
        return 1


if __name__ == '__main__':
    sys.exit(main())
