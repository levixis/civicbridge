from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path, include
from federation import views as sso
from portal.forms import CitizenAuthenticationForm
from portal.staff_views import StaffLoginView, staff_start, staff_workspace

urlpatterns = [
    path('staff/login/', StaffLoginView.as_view(), name='staff_login'),
    path('staff/sign-in/<slug:department>/', staff_start, name='staff_start'),
    path('staff/', staff_workspace, name='staff_workspace'),
    path('sso/login/', sso.start, name='sso_start'),
    path('sso/callback/', sso.callback, name='sso_callback'),
    path('services/', include('integration.urls')),
    path(
        "accounts/password-reset/",
        auth.PasswordResetView.as_view(
            template_name="password_reset_form.html",
            email_template_name="password_reset_email.txt",
            subject_template_name="password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/sent/",
        auth.PasswordResetDoneView.as_view(template_name="password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth.PasswordResetConfirmView.as_view(
            template_name="password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/complete/",
        auth.PasswordResetCompleteView.as_view(
            template_name="password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth.LoginView.as_view(template_name="login.html", authentication_form=CitizenAuthenticationForm),
        name="login",
    ),
    path("accounts/logout/", sso.SharedSignOutView.as_view(), name="logout"),
    path("", include("portal.urls")),
]
