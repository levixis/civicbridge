from django.urls import path
from django.contrib.auth import views as auth
from django.contrib import admin
from registry import views
from source_bridge import views as events
from federation import views as sso

urlpatterns = [
    path('sso/login/', sso.start, name='sso_start'),
    path('sso/callback/', sso.callback, name='sso_callback'),
    path('api/v1/events/', events.receive),
    path('tracker/', events.tracker, name='source_tracker'),
    path("", views.registry, name="registry"),
    path("certificates/new/", views.certificate_form, name="issue"),
    path("certificates/<int:pk>/", views.certificate_form, name="edit"),
    path(
        "accounts/login/",
        auth.LoginView.as_view(template_name="source_login.html"),
        name="login",
    ),
    path("accounts/logout/", sso.SharedSignOutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("health/", views.health),
    path("api/v1/income/<str:resident>/", views.income_api),
]
