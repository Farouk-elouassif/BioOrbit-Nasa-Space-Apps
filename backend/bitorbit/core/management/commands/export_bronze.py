"""Foreground Bronze export command; --watch is used by Docker Compose."""
import argparse
import logging
import math
import os
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from core.bronze.exporter import export_pending
from core.bronze.files import BronzeFileError

log = logging.getLogger(__name__)


def positive_int(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('Must be a positive integer')
    return result


def positive_float(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return result


class Command(BaseCommand):
    help = 'Export committed raw measurement events to durable, partitioned Bronze JSON files.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--root', help='Override BRONZE_ROOT')
        parser.add_argument('--batch-size', type=positive_int, default=os.environ.get('BRONZE_BATCH_SIZE', '1000'))
        parser.add_argument('--max-batches', type=positive_int, help='Maximum files per pass')
        parser.add_argument('--watch', action='store_true', help='Poll until SIGINT/SIGTERM')
        parser.add_argument('--interval', type=positive_float, default=os.environ.get('BRONZE_POLL_INTERVAL', '2'))

    def handle(self, *args, **options):
        root = options['root'] or settings.BRONZE_ROOT
        stopped = threading.Event()
        def stop(signum, frame):
            stopped.set()
        previous = {}
        if threading.current_thread() is threading.main_thread():
            previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            self.stdout.write(f'Bronze exporter: root={root}, batch_size={options["batch_size"]}')
            while not stopped.is_set():
                close_old_connections()
                try:
                    for receipt in export_pending(root, options['batch_size'], options['max_batches'], stopped.is_set):
                        self.stdout.write(f'Exported {receipt["event_count"]} events: {receipt["path"]}')
                except (OSError, DatabaseError, BronzeFileError) as exc:
                    if not options['watch']:
                        raise CommandError(f'Bronze export failed; pending data retained: {exc}') from exc
                    log.exception('Bronze export failed; pending data retained for retry')
                    self.stderr.write(f'Export failed; retrying in {options["interval"]}s')
                if not options['watch']:
                    break
                stopped.wait(options['interval'])
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            self.stdout.write('Bronze exporter stopped.')
