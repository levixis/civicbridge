import uuid
from datetime import datetime
from django.conf import settings
from django.core import signing
from django.db import transaction, DatabaseError
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_GET
from .models import IncomeCertificate, Disclosure, SourceEvent
from .forms import CertificateForm


@require_GET
def health(request):
    try:
        IncomeCertificate.objects.exists()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "service": "revenue", "contract": "v1"})


@require_GET
def income_api(request, resident):
    if not constant_time_compare(
        request.headers.get("Authorization", ""), "Bearer " + settings.REVENUE_API_TOKEN
    ):
        return JsonResponse({"error": "unauthorised"}, status=401)
    try:
        grant = signing.loads(
            request.headers.get("X-Consent-Grant", ""),
            key=settings.GRANT_SIGNING_KEY,
            salt="civicbridge.exchange.v1",
            max_age=60,
        )
        if not isinstance(grant, dict):
            raise ValueError()
        expires = datetime.fromisoformat(grant["expires"])
        if expires.tzinfo is None or expires <= timezone.now():
            raise ValueError()
        if (
            grant["resident"] != resident
            or grant["scope"] != "income_certificate"
            or grant["audience"] != "revenue"
            or not isinstance(grant["purpose"], str)
            or not 1 <= len(grant["purpose"]) <= 120
        ):
            raise ValueError()
        application = uuid.UUID(grant["application"])
        revision = uuid.UUID(grant["revision"])
        request_id = uuid.UUID(request.headers.get("X-Request-ID", ""))
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        return JsonResponse({"error": "invalid_consent_grant"}, status=403)
    record = IncomeCertificate.objects.filter(resident_number=resident).first()
    if not record:
        return JsonResponse({"error": "not_found"}, status=404)
    with transaction.atomic():
        disclosure, created = Disclosure.objects.get_or_create(
            request_id=request_id,
            defaults={
                "resident_number": resident,
                "application_reference": application,
                "consent_revision": revision,
            },
        )
        if (
            disclosure.resident_number != resident
            or disclosure.application_reference != application
            or disclosure.consent_revision != revision
        ):
            return JsonResponse({"error": "request_id_conflict"}, status=409)
    response = JsonResponse(record.payload())
    response["Cache-Control"] = "no-store"
    return response


@login_required
def registry(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Revenue staff access required.")
    records = IncomeCertificate.objects.order_by("resident_number")
    q = request.GET.get("q", "").strip()
    if q:
        records = records.filter(resident_number__icontains=q)
    from django.core.paginator import Paginator

    return render(
        request,
        "registry.html",
        {
            "records": Paginator(records, 25).get_page(request.GET.get("page")),
            "q": q,
            "disclosures": Disclosure.objects.order_by("-accessed_at")[:20],
        },
    )


@login_required
def certificate_form(request, pk=None):
    if not request.user.is_staff:
        return HttpResponseForbidden("Revenue staff access required.")
    obj = get_object_or_404(IncomeCertificate, pk=pk) if pk else None
    form = CertificateForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            record = form.save()
            SourceEvent.objects.create(
                action="update" if obj else "issue",
                actor=request.user.username,
                certificate_number=record.certificate_number,
            )
        messages.success(request, "Certificate saved in the Revenue database.")
        return redirect("registry")
    return render(
        request,
        "source_form.html",
        {"form": form, "title": "Update certificate" if obj else "Issue certificate"},
    )
