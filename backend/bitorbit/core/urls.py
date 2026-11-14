from django.urls import path
from .views import ingest_events
from .read_views import dashboard_view, trends_view

urlpatterns = [
    path("dashboard", dashboard_view, name="dashboard"),
    path("trends", trends_view, name="trends"),
    path('ingest/events', ingest_events, name='ingest-events'),
    path('ingest/events/', ingest_events),
]
