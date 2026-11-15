"""PostgreSQL schema for raw history, current state, baselines and alerts."""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now
from django.utils import timezone
from django.conf import settings
import uuid


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


class CrewCheckIn(models.Model):
    """Authenticated observations in mission time; not synthetic sensor samples."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(SimulationRun, on_delete=models.PROTECT)
    astronaut = models.ForeignKey(Astronaut, on_delete=models.PROTECT)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    measurements = models.JSONField(default=dict)
    rule_inputs = models.JSONField(default=dict)
    activity = models.CharField(max_length=20)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-observed_at', '-created_at']
        indexes = [models.Index(fields=['run', 'astronaut', 'observed_at'], name='idx_checkin_run_person_time')]


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

    class Meta:
        db_table = 'measurement_events'
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=EventKind.values), name='valid_event_kind'),
            models.CheckConstraint(condition=Q(phase__in=Phase.values), name='valid_event_phase'),
            models.CheckConstraint(condition=Q(domain__in=Domain.values), name='valid_event_domain'),
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


class MonitoringAlert(models.Model):
    run = models.ForeignKey(SimulationRun, on_delete=models.PROTECT, related_name='monitoring_alerts')
    subject_key = models.CharField(max_length=240)
    rule_code = models.CharField(max_length=100)
    domain = models.CharField(max_length=20, choices=Domain.choices)
    astronaut = models.ForeignKey(Astronaut, on_delete=models.PROTECT, null=True, blank=True)
    habitat = models.ForeignKey(Habitat, on_delete=models.PROTECT, null=True, blank=True)
    zone_id = models.CharField(max_length=100, default='', blank=True)
    region_index = models.PositiveSmallIntegerField(null=True, blank=True)
    tier = models.CharField(max_length=20, choices=[(v,v.title()) for v in ('advisory','caution','warning','emergency')])
    message = models.TextField()
    evidence = models.JSONField(default=dict)
    actions = models.JSONField(default=list)
    recipients = models.TextField(blank=True)
    provenance = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    detected_at = models.DateTimeField()
    last_observation_at = models.DateTimeField()
    recheck_due_at = models.DateTimeField()
    normal_count = models.PositiveSmallIntegerField(default=0)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_for_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'monitoring_alerts'
        constraints = [
            models.UniqueConstraint(fields=['run','subject_key','rule_code'], name='uq_alert_rule_subject'),
            models.CheckConstraint(condition=Q(tier__in=['advisory','caution','warning','emergency']), name='valid_alert_tier'),
            models.CheckConstraint(condition=Q(domain__in=Domain.values), name='valid_alert_domain'),
        ]
        indexes = [models.Index(fields=['run','is_active'], name='idx_active_run_alerts')]


class AlertAssessment(models.Model):
    run = models.ForeignKey(SimulationRun, on_delete=models.PROTECT, related_name='alert_assessments')
    subject_key = models.CharField(max_length=240)
    evaluated_at = models.DateTimeField()
    coverage = models.JSONField(default=dict)

    class Meta:
        db_table = 'alert_assessments'
        constraints = [models.UniqueConstraint(fields=['run','subject_key'], name='uq_alert_assessment_subject')]


class LatestRuleInput(models.Model):
    """Independent projection: an omitted fact never erases a prior observation."""
    run = models.ForeignKey(SimulationRun, on_delete=models.PROTECT)
    subject_key = models.CharField(max_length=240)
    code = models.CharField(max_length=100)
    value = models.JSONField()
    observed_at = models.DateTimeField()
    context = models.JSONField(default=dict)
    source_event = models.ForeignKey(MeasurementEvent, on_delete=models.PROTECT)

    class Meta:
        db_table = 'latest_rule_inputs'
        constraints = [models.UniqueConstraint(fields=['run','subject_key','code'], name='uq_latest_rule_input')]
