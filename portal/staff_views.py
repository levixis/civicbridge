from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import views as auth
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET

from common.demo import demo_subject
from federation.views import start
from integration.views import workspace
from .forms import StaffAuthenticationForm
from .permissions import is_operator, is_portal_staff


DEPARTMENTS = {
    "revenue": ("Revenue", "Issue and manage income certificates.", None),
    "municipality": ("Municipality", "Manage residence and household records.", None),
    "education": ("Education", "Review scholarship applications.", "Education Officers"),
    "welfare": ("Welfare", "Review housing assistance applications.", "Welfare Officers"),
    "operations": ("Platform operations", "Verify department links and manage service workflows.", "Integration Operators"),
}


class StaffLoginView(auth.LoginView):
    template_name = "staff_login.html"
    authentication_form = StaffAuthenticationForm

    def get_success_url(self):
        return reverse("staff_workspace")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["departments"] = [
            {"code": code, "name": name, "description": description}
            for code, (name, description, role) in DEPARTMENTS.items()
        ]
        context["staff_sign_in"] = True
        return context


@require_GET
def staff_start(request, department):
    if department not in DEPARTMENTS:
        raise Http404()
    role = DEPARTMENTS[department][2]
    if role is None:
        destination = settings.SSO_DEPARTMENT_ROUTES[str(demo_subject(department))]
        return redirect(destination + "?" + urlencode({"prompt": "login"}))
    return start(request, expected_role=role)


@login_required(login_url="staff_login")
def staff_workspace(request):
    if is_operator(request.user):
        return redirect("platform_monitor")
    if not is_portal_staff(request.user):
        return redirect("platform_workspace")
    return workspace(request, staff=True)
