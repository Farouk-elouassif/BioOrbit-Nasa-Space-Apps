from django.urls import path
from .views import ingest_events
from .read_views import dashboard_view, trends_view
from .alerts.api import alerts_view, rules_view, acknowledge_view

urlpatterns = [
    path("alerts", alerts_view, name="alerts"),
    path("alert-rules", rules_view, name="alert-rules"),
    path("alerts/<int:alert_id>/acknowledge", acknowledge_view, name="acknowledge-alert"),
    path("dashboard", dashboard_view, name="dashboard"),
    path("trends", trends_view, name="trends"),
    path('ingest/events', ingest_events, name='ingest-events'),
    path('ingest/events/', ingest_events),
]
