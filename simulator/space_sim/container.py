"""Container lifecycle: initialize once, resume backfill, then foreground live ticks."""
import logging
import math
import os
import signal

from .cli import main as cli_main
from .model import Config, DAY
from .storage import Store

log = logging.getLogger(__name__)


def number(env, name, default, allow_zero=False):
    value = float(env.get(name, str(default)))
    if not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        raise ValueError(f'{name} must be finite and {"nonnegative" if allow_zero else "positive"}')
    return value


def prepare(store, env, stopping=lambda: False):
    """Backfill to an absolute mission offset, never append history on each restart."""
    interval = number(env, 'SIM_HISTORY_INTERVAL', 300)
    days = number(env, 'SIM_HISTORY_DAYS', 30, allow_zero=True)
    if not store.db.execute('SELECT 1 FROM checkpoint WHERE id=1').fetchone():
        config = Config(
            mission_id=env.get('SIM_MISSION_ID', 'MARS_001'),
            habitat_id=env.get('SIM_HABITAT_ID', 'HAB_001'),
            astronauts=int(env.get('SIM_ASTRONAUTS', '3')),
            environment=env.get('SIM_ENVIRONMENT', 'transit_spacecraft'),
            seed=int(env.get('SIM_SEED', '42')),
            start=env.get('SIM_START', '2026-11-14T00:00:00Z'),
            duration_days=number(env, 'SIM_DURATION_DAYS', 180),
            speed=number(env, 'SIM_SPEED', 1),
            preflight_days=int(env.get('SIM_PREFLIGHT_DAYS', '14')),
            run_id=env.get('SIM_RUN_ID', 'demo-001'),
            surface_body=env.get('SIM_SURFACE_BODY', 'mars'),
            error_level=number(env, 'SIM_ERROR_LEVEL', 0, allow_zero=True),
        )
        store.initialize(config)
        log.info('Created mission %s with %d astronauts', config.mission_id, config.astronauts)
    engine = store.load()
    if 'SIM_ERROR_LEVEL' in env:
        level=number(env, 'SIM_ERROR_LEVEL', 0, allow_zero=True)
        if level!=engine.config.error_level:
            store.control('error-level', value=level)
            engine=store.load()
    target = min(days, engine.config.duration_days) * DAY
    log.info('Resuming day %.6f; startup history target day %.6f', engine.state['seconds']/DAY, target/DAY)
    ticks = 0
    while not stopping():
        remaining = target - store.load().state['seconds']
        if remaining <= 1e-8:
            break
        store.advance(delta=min(interval, remaining))
        ticks += 1
        if ticks % 100 == 0:
            log.info('Backfill checkpoint: day %.3f', store.load().state['seconds']/DAY)
    return not stopping()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    # The CLI owns signals during live generation; this handler covers initialization/backfill.
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    store = None
    try:
        env = os.environ
        state = env.get('SIM_STATE_PATH', '/data/simulation.sqlite3')
        live_interval = number(env, 'SIM_EMIT_INTERVAL', 5)
        batch_size = int(env.get('SIM_BATCH_SIZE', '500'))
        timeout = number(env, 'SIM_HTTP_TIMEOUT', 10)
        retries = int(env.get('SIM_HTTP_RETRIES', '3'))
        ticks = env.get('SIM_LIVE_TICKS', '')
        if batch_size < 1 or retries < 0 or (ticks and int(ticks) < 1):
            raise ValueError('Batch size/ticks must be positive; retries nonnegative')
        store = Store(state)
        ready = prepare(store, env, lambda: stopped)
        store.close(); store = None
        if not ready or stopped:
            log.info('Stopped during startup; committed history will resume next time')
            return 0
        log.info('Starting live generation (%ss/tick); HTTP delivery %s', live_interval,
                 'enabled' if env.get('SIM_INGEST_URL') else 'disabled; events saved locally')
        args = ['--state', state, 'live', '--interval', str(live_interval),
                '--batch-size', str(batch_size), '--timeout', str(timeout), '--retries', str(retries)]
        if ticks:
            args.extend(['--ticks', ticks])
        return cli_main(args)
    except Exception as exc:
        log.error('Simulator startup failed: %s', exc)
        return 1
    finally:
        if store is not None:
            store.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
