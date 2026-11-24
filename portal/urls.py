from django.urls import path
from . import views
from . import sandbox_views

urlpatterns = [
    path("sandbox/", sandbox_views.workspace, name="sandbox"),
    path("sandbox/<uuid:pk>/", sandbox_views.detail, name="sandbox_detail"),
    path("sandbox/<uuid:pk>/status/", sandbox_views.status, name="sandbox_status"),
    path("sandbox/<uuid:pk>/revoke/", sandbox_views.revoke, name="sandbox_revoke"),
    path("health/", views.health, name="health"),
    path("identity/request/", views.identity_request, name="identity_request"),
    path("identity/review/", views.identity_queue, name="identity_queue"),
    path("identity/review/<int:pk>/", views.identity_review, name="identity_review"),
    path(
        "applications/<int:pk>/document/",
        views.document_download,
        name="document_download",
    ),
    path("", views.home, name="home"),
    path("accounts/register/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("applications/new/", views.apply, name="apply"),
    path("applications/<int:pk>/", views.detail, name="detail"),
    path("applications/<int:pk>/consent/", views.grant, name="grant"),
    path("applications/<int:pk>/fetch/", views.fetch, name="fetch"),
    path("applications/<int:pk>/revoke/", views.revoke_view, name="revoke"),
    path("education/", views.officer, name="officer"),
    path("education/<int:pk>/decision/", views.decision, name="decision"),
    path("monitor/", views.monitor, name="monitor"),
    path("api/v1/applications/<int:pk>/", views.tracker_api, name="tracker_api"),
    path(
        "api/v1/applications/<int:pk>/exchange/",
        views.exchange_api,
        name="exchange_api",
    ),
]
