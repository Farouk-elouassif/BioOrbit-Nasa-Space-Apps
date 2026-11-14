"""Read-only APIs for the shared, local crew console. No ingestion token is exposed."""
import logging

from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .queries.dashboard import ReadError, dashboard, trends

log=logging.getLogger(__name__)


def respond(service,params):
    try:
        response=JsonResponse(service(params))
    except ReadError as exc:
        response=JsonResponse({'error':'invalid_query','message':str(exc)},status=exc.status)
    except DatabaseError:
        log.exception('Operational read failed')
        response=JsonResponse({'error':'storage_unavailable','message':'Backend storage is unavailable. Retry shortly.'},status=503)
    response['Cache-Control']='no-store'
    return response


@require_GET
def dashboard_view(request):
    return respond(dashboard,request.GET)


@require_GET
def trends_view(request):
    return respond(trends,request.GET)
