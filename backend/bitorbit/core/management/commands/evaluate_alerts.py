"""Evaluate the current stored mission state without starting another worker."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import SimulationRun
from core.alerts.service import evaluate_run

class Command(BaseCommand):
    help='Evaluate workbook alerts for existing latest measurements (one pass).'
    def add_arguments(self, parser):
        parser.add_argument('--run-id', help='Defaults to all active simulation runs.')
    def handle(self, *args, **options):
        runs=SimulationRun.objects.all()
        runs=runs.filter(pk=options['run_id']) if options['run_id'] else runs.filter(is_active=True)
        ids=list(runs.order_by('pk').values_list('pk',flat=True))
        if options['run_id'] and not ids:raise CommandError('Unknown simulation run')
        for identity in ids:
            with transaction.atomic():
                run=SimulationRun.objects.select_for_update().get(pk=identity)
                evaluate_run(run)
            self.stdout.write(self.style.SUCCESS(f'Evaluated {identity}'))
