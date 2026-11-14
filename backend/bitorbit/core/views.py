"""Machine-to-machine simulator ingestion; no session login or UI authentication."""
import json
import logging
import math
import secrets

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .ingestion.service import ingest
from .ingestion.validation import IngestionError, validate_payload

log = logging.getLogger(__name__)


def reject_constant(value):
    raise ValueError('Non-finite numbers are not valid JSON measurements')


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite number')
    return result


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object key')
        result[key] = value
    return result


@csrf_exempt
@require_POST
def ingest_events(request):
    expected = settings.SIM_INGEST_TOKEN
    if not expected:
        return JsonResponse({'error': 'ingestion_unconfigured'}, status=503)
    supplied = request.headers.get('Authorization', '')
    if not secrets.compare_digest(supplied.encode(), ('Bearer '+expected).encode()):
        response = JsonResponse({'error': 'unauthorized'}, status=401)
        response['WWW-Authenticate'] = 'Bearer'
        return response
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'unsupported_media_type'}, status=415)
    try:
        body = request.body
        if len(body) > settings.INGEST_MAX_BODY_BYTES:
            raise RequestDataTooBig
        payload = json.loads(body.decode('utf-8'), parse_constant=reject_constant,
                             parse_float=finite_float, object_pairs_hook=unique_keys)
        events = validate_payload(payload, settings.INGEST_MAX_BATCH_SIZE)
        result = ingest(events)  # Transaction commits before the acknowledgment is constructed.
    except RequestDataTooBig:
        return JsonResponse({'error': 'request_too_large'}, status=413)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return JsonResponse({'error': 'invalid_json'}, status=400)
    except IngestionError as exc:
        error = {'error': exc.code, 'message': str(exc)}
        if exc.index is not None:
            error['event_index'] = exc.index
        return JsonResponse(error, status=exc.status)
    except DatabaseError:
        log.exception('Ingestion transaction failed; batch was not acknowledged')
        response = JsonResponse({'error': 'storage_unavailable', 'message': 'Retry this batch with the same event IDs.'}, status=503)
        response['Retry-After'] = '2'
        return response
    return JsonResponse(result)
