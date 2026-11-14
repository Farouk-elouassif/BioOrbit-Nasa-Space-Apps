"""BioOrbit operational schema. Ingestion and analytical export are separate concerns."""
from uuid import uuid4

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now
from django.utils import timezone


class Domain(models.TextChoices):
    ASTRONAUT = 'astronaut', 'Astronaut'
    CABIN = 'cabin', 'Cabin'


class ValueType(models.TextChoices):
    NUMERIC = 'numeric', 'Numeric'
    BOOLEAN = 'boolean', 'Boolean'


class AggregationKind(models.TextChoices):
    POINT = 'point', 'Point'
    CUMULATIVE = 'cumulative', 'Cumulative'
    INTERVAL_TOTAL = 'interval_total', 'Interval total'
    BOOLEAN = 'boolean', 'Boolean'


class EventKind(models.TextChoices):
    MEASUREMENT = 'measurement', 'Measurement'
    PREFLIGHT_PROFILE = 'preflight_profile', 'Preflight profile'


class Phase(models.TextChoices):
    PREFLIGHT = 'preflight', 'Preflight'
    INFLIGHT = 'inflight', 'In-flight'


class BronzeStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    EXPORTED = 'exported', 'Exported'


class Mission(models.Model):
    mission_code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200, null=True, blank=True)
    status = models.CharField(max_length=30, default='planned', db_default='planned', null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'missions'

    def __str__(self):
        return self.mission_code


class Habitat(models.Model):
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT, related_name='habitats')
    habitat_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        db_table = 'habitats'
        constraints = [models.UniqueConstraint(fields=['mission', 'habitat_code'], name='uq_habitat_mission_code')]

    def __str__(self):
        return self.habitat_code


class Astronaut(models.Model):
    astronaut_code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        db_table = 'astronauts'

    def __str__(self):
        return self.astronaut_code


class MissionCrew(models.Model):
    pk = models.CompositePrimaryKey('mission_id', 'astronaut_id')
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT, related_name='crew_assignments')
    astronaut = models.ForeignKey(Astronaut, on_delete=models.PROTECT, related_name='mission_assignments')
    habitat = models.ForeignKey(Habitat, on_delete=models.PROTECT, related_name='crew_assignments', null=True, blank=True)

    class Meta:
        db_table = 'mission_crew'


class SimulationRun(models.Model):
    run_id = models.CharField(max_length=100, primary_key=True)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT, related_name='simulation_runs')
    environment = models.CharField(max_length=50)
    created_at = models.DateTimeField(default=timezone.now, db_default=Now(), null=True, blank=True)
    is_active = models.BooleanField(default=True, db_default=True, null=True, blank=True)

    class Meta:
        db_table = 'simulation_runs'

    def __str__(self):
        return self.run_id


class MetricCatalog(models.Model):
    code = models.CharField(max_length=100, primary_key=True)
    domain = models.CharField(max_length=20, choices=Domain.choices)
    unit = models.CharField(max_length=30)
    value_type = models.CharField(max_length=20, choices=ValueType.choices)
    aggregation_kind = models.CharField(max_length=30, choices=AggregationKind.choices,
                                        default=AggregationKind.POINT, db_default='point', null=True, blank=True)

    class Meta:
        db_table = 'metric_catalog'
        constraints = [
            models.CheckConstraint(condition=Q(domain__in=Domain.values), name='valid_metric_domain'),
            models.CheckConstraint(condition=Q(value_type__in=ValueType.values), name='valid_metric_value_type'),
            models.CheckConstraint(condition=Q(aggregation_kind__in=AggregationKind.values), name='valid_metric_aggregation'),
        ]

    def __str__(self):
        return self.code


# Explicit IS NULL/IS NOT NULL clauses preserve the XOR checks in PostgreSQL.
EXACTLY_ONE_VALUE = (
    Q(numeric_value__isnull=False, boolean_value__isnull=True)
    | Q(numeric_value__isnull=True, boolean_value__isnull=False)
)
VALID_SUBJECT = (
    Q(domain=Domain.CABIN, astronaut__isnull=True)
    | Q(domain=Domain.ASTRONAUT, astronaut__isnull=False)
)


class BronzeExportBatch(models.Model):
    """Persist batch membership before filesystem I/O so retries use the same file."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    relative_path = models.CharField(max_length=1024, unique=True)
    event_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now, db_default=Now())
    exported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'bronze_export_batches'
        constraints = [models.CheckConstraint(condition=Q(event_count__gte=1), name='valid_bronze_batch_count')]
        indexes = [models.Index(fields=['created_at'], condition=Q(exported_at__isnull=True), name='idx_pending_bronze_batches')]


class MeasurementEvent(models.Model):
    event_id = models.UUIDField(primary_key=True)
    run = models.ForeignKey(SimulationRun, db_column='run_id', on_delete=models.PROTECT, related_name='measurement_events')
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT, related_name='measurement_events')
    habitat = models.ForeignKey(Habitat, on_delete=models.PROTECT, related_name='measurement_events')
    astronaut = models.ForeignKey(Astronaut, on_delete=models.PROTECT, related_name='measurement_events', null=True, blank=True)
    zone_id = models.CharField(max_length=100)
    kind = models.CharField(max_length=30, choices=EventKind.choices)
    phase = models.CharField(max_length=20, choices=Phase.choices)
    domain = models.CharField(max_length=20, choices=Domain.choices)
    metric = models.ForeignKey(MetricCatalog, db_column='metric_code', on_delete=models.PROTECT,
                               related_name='measurement_events', null=True, blank=True)
    numeric_value = models.FloatField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    measured_at = models.DateTimeField()
    emitted_at = models.DateTimeField()
    received_at = models.DateTimeField(default=timezone.now, db_default=Now(), null=True, blank=True)
    context = models.JSONField(blank=True, default=dict, db_default={})
    raw_payload = models.JSONField(blank=True)
    bronze_status = models.CharField(max_length=20, choices=BronzeStatus.choices,
                                    default=BronzeStatus.PENDING, db_default='pending')
    bronze_exported_at = models.DateTimeField(null=True, blank=True)
    bronze_batch = models.ForeignKey(BronzeExportBatch, on_delete=models.PROTECT, related_name='events', null=True, blank=True)

    class Meta:
        db_table = 'measurement_events'
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=EventKind.values), name='valid_event_kind'),
            models.CheckConstraint(condition=Q(phase__in=Phase.values), name='valid_event_phase'),
            models.CheckConstraint(condition=Q(domain__in=Domain.values), name='valid_event_domain'),
            models.CheckConstraint(condition=Q(bronze_status__in=BronzeStatus.values), name='valid_bronze_status'),
            models.CheckConstraint(
                condition=(
                    Q(kind=EventKind.PREFLIGHT_PROFILE, phase=Phase.PREFLIGHT, domain=Domain.ASTRONAUT,
                      astronaut__isnull=False, metric__isnull=True, numeric_value__isnull=True, boolean_value__isnull=True)
                    | (Q(kind=EventKind.MEASUREMENT, metric__isnull=False) & EXACTLY_ONE_VALUE)
                ),
                name='valid_event_value',
            ),
            models.CheckConstraint(condition=VALID_SUBJECT, name='valid_event_subject'),
        ]
        indexes = [
            models.Index(fields=['received_at'], condition=Q(bronze_status=BronzeStatus.PENDING), name='idx_pending_bronze'),
            models.Index(fields=['run', 'astronaut', 'metric', '-measured_at'], name='idx_measurement_history'),
        ]

    def __str__(self):
        return str(self.event_id)


class PreflightProfile(models.Model):
    run = models.ForeignKey(SimulationRun, db_column='run_id', on_delete=models.PROTECT, related_name='preflight_profiles')
    astronaut = models.ForeignKey(Astronaut, on_delete=models.PROTECT, related_name='preflight_profiles')
    source_event = models.OneToOneField(MeasurementEvent, db_column='source_event_id', on_delete=models.PROTECT,
                                       related_name='preflight_profile', null=True, blank=True)
    preflight_radiation_level = models.FloatField(null=True, blank=True, help_text='Estimated preflight background rate, mSv/year.')
    career_radiation_dose = models.FloatField(null=True, blank=True, help_text='Accumulated occupational dose before this mission, mSv.')
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'preflight_profiles'
        constraints = [models.UniqueConstraint(fields=['run', 'astronaut'], name='uq_preflight_run_astronaut')]


class PreflightBaseline(models.Model):
    pk = models.CompositePrimaryKey('profile_id', 'metric_id')
    profile = models.ForeignKey(PreflightProfile, on_delete=models.PROTECT, related_name='baselines')
    metric = models.ForeignKey(MetricCatalog, db_column='metric_code', on_delete=models.PROTECT, related_name='preflight_baselines')
    mean = models.FloatField()
    stddev = models.FloatField()
    min_value = models.FloatField()
    max_value = models.FloatField()
    sample_count = models.IntegerField()

    class Meta:
        db_table = 'preflight_baselines'
        constraints = [models.CheckConstraint(condition=Q(sample_count__gte=2), name='valid_baseline_sample_count')]


class LatestMeasurement(models.Model):
    run = models.ForeignKey(SimulationRun, db_column='run_id', on_delete=models.PROTECT, related_name='latest_measurements')
    domain = models.CharField(max_length=20, choices=Domain.choices)
    astronaut = models.ForeignKey(Astronaut, on_delete=models.PROTECT, related_name='latest_measurements', null=True, blank=True)
    habitat = models.ForeignKey(Habitat, on_delete=models.PROTECT, related_name='latest_measurements')
    zone_id = models.CharField(max_length=100)
    metric = models.ForeignKey(MetricCatalog, db_column='metric_code', on_delete=models.PROTECT, related_name='latest_measurements')
    numeric_value = models.FloatField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    context = models.JSONField(blank=True, default=dict, db_default={})
    measured_at = models.DateTimeField()
    source_event = models.ForeignKey(MeasurementEvent, db_column='source_event_id', on_delete=models.PROTECT,
                                     related_name='latest_measurements')
    updated_at = models.DateTimeField(default=timezone.now, db_default=Now(), null=True, blank=True)

    class Meta:
        db_table = 'latest_measurements'
        constraints = [
            models.CheckConstraint(condition=Q(domain__in=Domain.values), name='valid_latest_domain'),
            models.CheckConstraint(condition=EXACTLY_ONE_VALUE, name='valid_latest_value'),
            models.CheckConstraint(condition=VALID_SUBJECT, name='valid_latest_subject'),
            models.UniqueConstraint(fields=['run', 'astronaut', 'metric'], condition=Q(domain=Domain.ASTRONAUT), name='uq_latest_astronaut'),
            models.UniqueConstraint(fields=['run', 'habitat', 'zone_id', 'metric'], condition=Q(domain=Domain.CABIN), name='uq_latest_cabin'),
        ]
