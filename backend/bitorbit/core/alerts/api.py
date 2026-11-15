"""Alert read contract and CSRF-protected acknowledgment for the onboard console."""
import json
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET,require_POST

from core.models import MonitoringAlert
from core.ingestion.catalogue import canonical_metric,CATALOGUE
from .service import PATTERN_SOURCE,recheck_seconds
from .spec import COLORS,PARAMETERS,RANK,WORKBOOK


def serialize(alert,anchor=None):
    source=PARAMETERS.get(PATTERN_SOURCE.get(alert.rule_code,alert.rule_code),{})
    return {'id':alert.pk,'rule_code':alert.rule_code,'title':source.get('name',alert.rule_code.replace('_',' ').title()),
            'domain':alert.domain,'astronaut_id':alert.astronaut.astronaut_code if alert.astronaut_id else None,
            'habitat_id':alert.habitat.habitat_code if alert.habitat_id else None,'zone_id':alert.zone_id,
            'metric_id':canonical_metric(source.get('id'),alert.domain) if canonical_metric(source.get('id'),alert.domain) in CATALOGUE else None,
            'region_index':alert.region_index,'tier':alert.tier,'color':COLORS[alert.tier],
            'message':alert.message,'evidence':alert.evidence,'actions':alert.actions,'recipients':alert.recipients,
            'rule_reference':{'condition':source.get(alert.tier), 'unit':source.get('unit'),
                              'lower_limit':source.get('lower_limit'), 'upper_limit':source.get('upper_limit')},
            'detected_at':alert.detected_at,'last_observation_at':alert.last_observation_at,
            'recheck_due_at':alert.recheck_due_at,'recheck_interval_seconds':recheck_seconds(alert.rule_code,alert.tier),
            'recheck_overdue':bool(anchor and anchor>=alert.recheck_due_at),
            'acknowledged_at':alert.acknowledged_at,'acknowledged_for_at':alert.acknowledged_for_at,
            'normal_count':alert.normal_count,'provenance':alert.provenance,'is_active':alert.is_active}


def active_alerts(run,anchor=None):
    rows=list(MonitoringAlert.objects.filter(run=run,is_active=True).select_related('astronaut','habitat'))
    rows.sort(key=lambda a:(-RANK[a.tier],0 if a.rule_code=='pattern_cabin_first' else 1,-a.last_observation_at.timestamp(),a.pk))
    return [serialize(a,anchor) for a in rows]


@require_GET
def alerts_view(request):
    from core.queries.dashboard import ReadError,choose_run,run_clock
    from django.db import DatabaseError
    try:
        run=choose_run(request.GET.get('run_id'))
        if run is None:return JsonResponse({'alerts':[],'run_id':None,'prototype':True})
        _,anchor=run_clock(run)
        return JsonResponse({'alerts':active_alerts(run,anchor),'run_id':run.pk,'prototype':True})
    except ReadError as exc:return JsonResponse({'error':'invalid_query','message':str(exc)},status=exc.status)
    except DatabaseError:return JsonResponse({'error':'storage_unavailable'},status=503)


@require_GET
def rules_view(request):
    return JsonResponse({**WORKBOOK,'evaluation_notes':{
        'precedence':'Highest matching tier wins; three distinct normal observations lower one tier.',
        'missing_data':'Not evaluated; never assumed normal or zero.',
        'news2':'Space-adjusted prototype; complete scoring requires seven inputs. A coherent partial lower bound can escalate at 5/7; missing components remain unknown.',
        'continuous_gap_tolerance_seconds':900,'persistence_max_gap_seconds':60,
        'prototype_choices':['One-hour humidity mean because workbook average duration is unspecified.',
            'Resting in-flight baseline: ≥20 valid samples over ≥24h, from prior seven days excluding last 24h.',
            'Integer NEWS2 bands round numeric readings to nearest integer; raw values remain unchanged.',
            'Diastolic drift uses the observed in-flight band with ±5 mmHg prototype tolerance.',
            'An unplanned cabin pressure fall >6.9 kPa within 10 minutes is a prototype Emergency.',
            'Explicit source flags are required where prose does not define a numerical cutoff.'],
    }})


@require_POST
def acknowledge_view(request,alert_id):
    from django.db import DatabaseError
    try:
        if request.content_type!='application/json':return JsonResponse({'error':'unsupported_media_type'},status=415)
        if len(request.body)>4096:return JsonResponse({'error':'request_too_large'},status=413)
        data=json.loads(request.body)
        if not isinstance(data,dict) or not isinstance(data.get('tier'),str) or data['tier'] not in RANK:return JsonResponse({'error':'expected_current_tier'},status=422)
        with transaction.atomic():
            alert=MonitoringAlert.objects.select_for_update().filter(pk=alert_id).first()
            if alert is None:return JsonResponse({'error':'alert_not_found'},status=404)
            if not alert.is_active or data['tier']!=alert.tier:
                return JsonResponse({'error':'alert_changed','message':'Alert changed; refresh and review it before acknowledgment.'},status=409)
            if alert.acknowledged_at is None:
                alert.acknowledged_at=timezone.now();alert.acknowledged_for_at=alert.last_observation_at
                alert.save(update_fields=['acknowledged_at','acknowledged_for_at','updated_at'])
        return JsonResponse({'id':alert.pk,'acknowledged_at':alert.acknowledged_at,'is_active':alert.is_active})
    except (ValueError,UnicodeDecodeError):return JsonResponse({'error':'invalid_json'},status=400)
    except DatabaseError:return JsonResponse({'error':'storage_unavailable'},status=503)
