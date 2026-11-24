import json
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import SandboxRun
from .connectors import ExchangeError
from .sandbox import (
    CONTRACT_URL,
    ENDPOINT,
    cancel,
    enqueue,
    sample_request,
    visible_result,
)


class SandboxForm(forms.Form):
    mode = forms.ChoiceField(
        choices=[
            ("official", "Official API Setu sandbox (internet required)"),
            ("fixture", "Local classroom fixture (offline)"),
        ]
    )
    consent = forms.BooleanField(
        label="I authorise this sample-only test and storage of its response for 24 hours."
    )


def private(response):
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def workspace(request):
    if not settings.SANDBOX_ENABLED:
        return HttpResponseForbidden("Sandbox workspace is disabled.")
    form = SandboxForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            run = enqueue(request.user, form.cleaned_data["mode"])
            return redirect("sandbox_detail", pk=run.pk)
        except ExchangeError as error:
            form.add_error(None, str(error))
    runs = SandboxRun.objects.filter(owner=request.user).order_by("-created_at")
    return private(
        render(
            request,
            "sandbox.html",
            {
                "form": form,
                "runs": Paginator(runs, 20).get_page(request.GET.get("page")),
                "endpoint": ENDPOINT,
                "contract_url": CONTRACT_URL,
                "sample_request": json.dumps(sample_request(), indent=2),
            },
        )
    )


@login_required
@require_GET
def detail(request, pk):
    run = get_object_or_404(SandboxRun, pk=pk, owner=request.user)
    return private(
        render(
            request, "sandbox_detail.html", {"run": run, "result": visible_result(run)}
        )
    )


@login_required
@require_GET
def status(request, pk):
    run = get_object_or_404(SandboxRun, pk=pk, owner=request.user)
    return private(
        JsonResponse(
            {
                "status": run.status,
                "active": run.active,
                "attempts": run.attempts,
                "http_status": run.http_status,
            }
        )
    )


@login_required
@require_POST
def revoke(request, pk):
    get_object_or_404(SandboxRun, pk=pk, owner=request.user)
    cancel(request.user, pk)
    messages.success(request, "Sandbox consent revoked and stored response removed.")
    return redirect("sandbox_detail", pk=pk)
