"""Session-authenticated crew reports, sharing the existing alert transaction."""
import json
import math
from datetime import timedelta
from uuid import UUID, uuid4

from django.contrib.auth import authenticate, login, logout
from django.db import DatabaseError, transaction
from django.db.models import Max
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .alerts.service import ENUM_INPUTS, evaluate_run
from .ingestion.catalogue import ACTIVITIES, CATALOGUE
from .ingestion.service import ingest
from .ingestion.validation import IngestionError, validate_payload
from .models import CrewCheckIn, LatestMeasurement, MeasurementEvent, SimulationRun
from .views import finite_float, reject_constant, unique_keys

SYMPTOMS = {'chest_pain', 'collapse', 'breathlessness', 'breathlessness_at_rest',
    'new_confusion', 'neurological_signs', 'confusion', 'sweating', 'shaking',
    'lightheadedness', 'fainting', 'vision_change', 'nausea', 'vomiting',
    'ecg_alarm', 'sudden_severe_headache'}
RANGES = {'heart_rate': (1, 300), 'respiratory_rate': (1, 100), 'spo2': (1, 100),
    'systolic_blood_pressure': (1, 300), 'diastolic_blood_pressure': (1, 200),
    'blood_glucose': (1, 1000), 'body_temperature': (25, 45),
    'sleep_duration': (0, 24), 'mood': (0, 10)}


def body(request):
    if request.content_type != 'application/json':
        raise ValueError('Send application/json.')
    if len(request.body) > 16384:
        raise ValueError('Report is too large.')
    data = json.loads(request.body, parse_constant=reject_constant,
                      parse_float=finite_float, object_pairs_hook=unique_keys)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object.')
    return data


def can_report(user):
    return user.is_authenticated and user.has_perm('core.add_crewcheckin')


@never_cache
@ensure_csrf_cookie
@require_http_methods(['GET', 'POST', 'DELETE'])
def session_view(request):
    if request.method == 'POST':
        try:
            data = body(request)
            if not isinstance(data.get('username'), str) or not isinstance(data.get('password'), str):
                raise ValueError('Enter your username and password.')
            user = authenticate(request, username=data['username'], password=data['password'])
            if user is None or not user.has_perm('core.add_crewcheckin'):
                return JsonResponse({'message': 'Sign-in failed or this account cannot record crew reports.'}, status=403)
            login(request, user)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            return JsonResponse({'message': str(exc)}, status=400)
    elif request.method == 'DELETE':
        logout(request)
    return JsonResponse({'authenticated': request.user.is_authenticated,
                         'can_checkin': can_report(request.user)})


def serialize(report):
    return {'id': str(report.pk), 'run_id': report.run_id,
        'astronaut_id': report.astronaut.astronaut_code,
        'name': report.astronaut.name or report.astronaut.astronaut_code,
        'observed_at': report.observed_at, 'created_at': report.created_at,
        'measurements': report.measurements, 'rule_inputs': report.rule_inputs,
        'activity': report.activity, 'notes': report.notes}


def validate_report(data):
    if set(data) - {'id', 'run_id', 'astronaut_id', 'measurements', 'rule_inputs', 'activity', 'meal_context', 'notes'}:
        raise ValueError('Unknown check-in fields.')
    identity = UUID(str(data['id']))
    if any(not isinstance(data.get(k), str) or not 0 < len(data[k]) <= 100 for k in ('run_id', 'astronaut_id')):
        raise ValueError('Select a run and crew member.')
    activity = data.get('activity')
    if activity not in ACTIVITIES:
        raise ValueError('Select the measurement activity.')
    measurements = data.get('measurements', {})
    if not isinstance(measurements, dict) or set(measurements) - set(RANGES):
        raise ValueError('Unsupported manual measurement.')
    for code, value in measurements.items():
        lo, hi = RANGES[code]
        if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f'{code} must be between {lo} and {hi}.')
    if 'blood_glucose' in measurements and data.get('meal_context') not in ('fasting', 'after_meal'):
        raise ValueError('Glucose requires fasting or after_meal context.')
    inputs = data.get('rule_inputs', {})
    if not isinstance(inputs, dict) or set(inputs) - SYMPTOMS - {'consciousness', 'supplemental_oxygen', 'headache'}:
        raise ValueError('Unsupported clinical observation.')
    for code, value in inputs.items():
        if code == 'consciousness':
            if not isinstance(value, str) or value not in ENUM_INPUTS['consciousness']:
                raise ValueError('Invalid consciousness observation.')
        elif code == 'headache':
            if type(value) is not int or not 0 <= value <= 3:
                raise ValueError('Headache severity must be 0–3.')
        elif type(value) is not bool:
            raise ValueError('Symptom findings must be true or false; omission means unknown.')
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 4000:
        raise ValueError('Notes must be at most 4000 characters.')
    if not measurements and not inputs and not notes.strip():
        raise ValueError('Enter a measurement, finding or note.')
    return identity, measurements, inputs, activity, notes


@never_cache
@require_http_methods(['GET', 'POST'])
def checkins_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'message': 'Sign in to record or read crew check-ins.'}, status=401)
    if not can_report(request.user):
        return JsonResponse({'message': 'This account cannot record crew check-ins.'}, status=403)
    try:
        if request.method == 'GET':
            run_id = request.GET.get('run_id', '')
            reports = CrewCheckIn.objects.filter(run_id=run_id).select_related('astronaut')[:100]
            return JsonResponse({'checkins': [serialize(r) for r in reports]})
        data = body(request)
        identity, measurements, inputs, activity, notes = validate_report(data)
        with transaction.atomic():
            run = SimulationRun.objects.select_for_update().filter(pk=data['run_id']).first()
            if run is None or not run.is_active:
                return JsonResponse({'message': 'Select an active mission run.'}, status=404)
            latest = LatestMeasurement.objects.filter(run=run, domain='astronaut',
                astronaut__astronaut_code=data['astronaut_id']).select_related('astronaut', 'habitat', 'source_event').order_by('-measured_at').first()
            if latest is None:
                return JsonResponse({'message': 'Crew member has no observations in this run.'}, status=404)
            stored_measurements = {'values': measurements, 'meal_context': data.get('meal_context') if 'blood_glucose' in measurements else None}
            typed_inputs = {code: {'value': value, **({'unit': 'severity 0–3'} if code == 'headache' else {})} for code, value in inputs.items()}
            previous = CrewCheckIn.objects.filter(pk=identity).select_related('astronaut').first()
            if previous:
                if (previous.run_id != run.pk or previous.astronaut_id != latest.astronaut_id or
                    previous.recorded_by_id != request.user.pk or previous.measurements != stored_measurements or
                    previous.rule_inputs != typed_inputs or previous.activity != activity or previous.notes != notes):
                    return JsonResponse({'message': 'This report ID already has different contents.'}, status=409)
                return JsonResponse(serialize(previous))
            at = MeasurementEvent.objects.filter(run=run, phase='inflight').aggregate(at=Max('measured_at'))['at']
            report_at = CrewCheckIn.objects.filter(run=run).aggregate(at=Max('observed_at'))['at']
            at = max(at, report_at) if report_at else at
            at += timedelta(microseconds=1)
            report = CrewCheckIn.objects.create(id=identity, run=run, astronaut=latest.astronaut,
                recorded_by=request.user, observed_at=at, measurements=stored_measurements,
                rule_inputs=typed_inputs, activity=activity, notes=notes)
            events = []
            for code, value in measurements.items():
                context = {'activity': activity, 'checkin_id': str(identity), 'recorded_by': request.user.pk}
                if code == 'blood_glucose': context['meal_context'] = data['meal_context']
                events.append({'schema_version': '1.0', 'kind': 'measurement', 'event_id': str(uuid4()),
                    'run_id': run.pk, 'mission_id': run.mission.mission_code, 'habitat_id': latest.habitat.habitat_code,
                    'zone_id': 'EVA' if activity == 'eva' else latest.zone_id,
                    'astronaut_id': latest.astronaut.astronaut_code, 'domain': 'astronaut', 'phase': 'inflight',
                    'metric': code, 'value': value, 'unit': CATALOGUE[code][0], 'measured_at': at.isoformat(),
                    'emitted_at': timezone.now().isoformat(), 'source': 'crew-checkin', 'simulated': True,
                    'environment': run.environment, 'context': context})
            if events: ingest(validate_payload({'schema_version':'1.0','events':events}, 10))
            else: evaluate_run(run)
        return JsonResponse(serialize(report), status=201)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, RecursionError) as exc:
        return JsonResponse({'message': str(exc)}, status=422)
    except IngestionError as exc:
        return JsonResponse({'message': str(exc)}, status=exc.status)
    except DatabaseError:
        return JsonResponse({'message': 'Storage unavailable; retry this report with the same ID.'}, status=503)
