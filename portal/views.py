from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from .models import Citizen, Application, Consent, Event, Audit
from .forms import RegistrationForm, ApplicationForm, ConsentForm, DecisionForm
from .permissions import is_officer, is_operator, is_revenue
from .services import exchange, revoke, decide, log, grant_consent, current_consent
from .connectors import CONNECTORS


def home(request):
    return render(request, "home.html")


def register(request):
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        with transaction.atomic():
            # Serialize the identifier checks and insert with other portal sign-ups.
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        ["civicbridge.portal.registration"],
                    )
            if form.is_valid():
                user = form.save()
                Citizen.objects.create(user=user)
        if form.is_valid():
            login(request, user)
            return redirect("platform_catalog")
    return render(
        request,
        "form.html",
        {
            "form": form,
            "title": "Create your citizen account",
            "subtitle": "One account for a connected service journey.",
            "button": "Create account",
        },
    )


@login_required
def dashboard(request):
    if is_officer(request.user):
        return redirect("officer")
    if is_operator(request.user):
        return redirect("monitor")
    citizen = get_object_or_404(Citizen, user=request.user)
    apps = Application.objects.filter(citizen=citizen).order_by("-created_at")
    active = Consent.objects.filter(
        application__citizen=citizen, revoked_at=None, expires_at__gt=timezone.now()
    ).count()
    return render(
        request,
        "dashboard.html",
        {
            "apps": apps,
            "citizen": citizen,
            "total": apps.count(),
            "approved": apps.filter(status="approved").count(),
            "active": active,
            "identity_links": citizen.identitylink_set.all(),
            "identity_requests": citizen.identityrequest_set.order_by("-created_at")[
                :5
            ],
        },
    )


@login_required
def apply(request):
    citizen = get_object_or_404(Citizen, user=request.user)
    form = ApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            app = form.save(commit=False)
            app.citizen = citizen
            app.save()
            Event.objects.create(
                application=app, label="Scholarship application submitted to Education"
            )
            log(
                request.user,
                app,
                "application.create",
                "success",
                "Application submitted; no certificate uploaded.",
            )
        return redirect("detail", pk=app.pk)
    return render(
        request,
        "form.html",
        {
            "form": form,
            "title": "Apply for a scholarship",
            "subtitle": "Your income certificate can be fetched from Revenue with your consent.",
            "button": "Submit application",
        },
    )


def accessible_app(user, pk):
    qs = Application.objects.select_related("citizen__user")
    if not is_officer(user):
        qs = qs.filter(citizen__user=user)
    return get_object_or_404(qs, pk=pk)


@login_required
def detail(request, pk):
    app = accessible_app(request.user, pk)
    consent = Consent.objects.filter(application=app).first()
    document = app.document_snapshot if current_consent(app) else {}
    return render(
        request,
        "detail.html",
        {
            "app": app,
            "consent": consent,
            "document": document,
            "consent_form": ConsentForm(),
            "decision_form": DecisionForm(),
            "owner": app.citizen.user_id == request.user.pk,
            "audits": Audit.objects.filter(application=app)[:20],
            "jobs": app.jobs.order_by("-created_at")[:10],
        },
    )


@login_required
@require_POST
def grant(request, pk):
    app = get_object_or_404(Application, pk=pk, citizen__user=request.user)
    form = ConsentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Tick the consent checkbox to authorise sharing.")
        return redirect("detail", pk=pk)
    ok, msg = grant_consent(request.user, pk)
    (messages.success if ok else messages.error)(request, msg)
    return redirect("detail", pk=pk)


@login_required
@require_POST
def fetch(request, pk):
    accessible_app(request.user, pk)
    ok, msg = exchange(request.user, pk)
    (messages.success if ok else messages.error)(request, msg)
    return redirect("detail", pk=pk)


@login_required
@require_POST
def revoke_view(request, pk):
    get_object_or_404(Application, pk=pk, citizen__user=request.user)
    ok, msg = revoke(request.user, pk)
    (messages.success if ok else messages.error)(request, msg)
    return redirect("detail", pk=pk)


@login_required
def officer(request):
    if not is_officer(request.user):
        return HttpResponseForbidden("Education officer access required.")
    status = request.GET.get("status", "")
    apps = Application.objects.select_related("citizen__user").order_by("-created_at")
    if status in Application.Status.values:
        apps = apps.filter(status=status)
    return render(
        request,
        "officer.html",
        {
            "apps": Paginator(apps, 25).get_page(request.GET.get("page")),
            "status": status,
            "choices": Application.Status.choices,
        },
    )


@login_required
@require_POST
def decision(request, pk):
    if not is_officer(request.user):
        return HttpResponseForbidden("Education officer access required.")
    get_object_or_404(Application, pk=pk)
    form = DecisionForm(request.POST)
    if form.is_valid():
        ok, msg = decide(
            request.user, pk, form.cleaned_data["decision"], form.cleaned_data["note"]
        )
        (messages.success if ok else messages.error)(request, msg)
    else:
        messages.error(
            request, "Choose a decision and provide a note of at most 500 characters."
        )
    return redirect("detail", pk=pk)


@login_required
def monitor(request):
    if not is_operator(request.user):
        return HttpResponseForbidden("Integration operator access required.")
    return render(
        request,
        "monitor.html",
        {
            "connectors": [c.health() for c in CONNECTORS.values()],
            "logs": Audit.objects.select_related("actor").all()[:50],
            "exchanges": Audit.objects.filter(
                action="document.fetch", outcome="success"
            ).count(),
            "denied": Audit.objects.filter(outcome="denied").count(),
            "failed": Audit.objects.filter(outcome="failed").count(),
            "links": Citizen.objects.filter(identitylink__isnull=False)
            .distinct()
            .count(),
            "pending_jobs": ExchangeJob.objects.filter(
                status__in=["queued", "running"]
            ).count(),
            "workers": WorkerHeartbeat.objects.all(),
        },
    )


@login_required
@require_GET
def tracker_api(request, pk):
    app = accessible_app(request.user, pk)
    return JsonResponse(
        {
            "reference": str(app.reference),
            "status": app.status,
            "status_label": app.get_status_display(),
            "updated_at": app.updated_at.isoformat(),
            "events": list(app.events.values("label", "created_at")),
        }
    )


@login_required
@require_POST
def exchange_api(request, pk):
    accessible_app(request.user, pk)
    ok, msg = exchange(request.user, pk)
    job = app_job(pk) if ok else None
    return JsonResponse(
        {"ok": ok, "message": msg, "job_id": str(job.pk) if job else None},
        status=202 if ok else 409,
    )


from .models import IdentityLink, IdentityRequest, ExchangeJob, WorkerHeartbeat
from .forms import IdentityRequestForm, IdentityReviewForm
from django.db import IntegrityError, DatabaseError
from django.core.paginator import Paginator


def app_job(pk):
    return ExchangeJob.objects.filter(application_id=pk).order_by("-created_at").first()


@login_required
def identity_request(request):
    citizen = get_object_or_404(Citizen, user=request.user)
    form = IdentityRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if IdentityLink.objects.filter(citizen=citizen, department="revenue").exists():
            messages.error(
                request,
                "You already have a verified link. Contact the operator for corrections.",
            )
        else:
            try:
                with transaction.atomic():
                    req = IdentityRequest.objects.create(
                        citizen=citizen, external_id=form.cleaned_data["external_id"]
                    )
                    Audit.objects.create(
                        actor=request.user,
                        citizen=citizen,
                        action="identity.request",
                        outcome="success",
                        detail="Citizen requested manual identity verification.",
                    )
                messages.success(
                    request,
                    "Identity verification requested. The operator must verify ownership before linking.",
                )
            except IntegrityError:
                messages.error(request, "A request is already awaiting review.")
        return redirect("dashboard")
    return render(
        request,
        "form.html",
        {
            "form": form,
            "title": "Request a Revenue identity link",
            "subtitle": "Entering an ID does not grant access. The operator verifies your ownership through an approved evidence process.",
            "button": "Request verification",
        },
    )


@login_required
def identity_queue(request):
    if not is_operator(request.user):
        return HttpResponseForbidden("Integration operator access required.")
    records = (
        IdentityRequest.objects.select_related("citizen__user")
        .filter(status="pending")
        .order_by("created_at")
    )
    return render(
        request,
        "identities.html",
        {"requests": Paginator(records, 25).get_page(request.GET.get("page"))},
    )


@login_required
def identity_review(request, pk):
    if not is_operator(request.user):
        return HttpResponseForbidden("Integration operator access required.")
    item = get_object_or_404(IdentityRequest, pk=pk)
    form = IdentityReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                item = IdentityRequest.objects.select_for_update().get(pk=pk)
                if item.status != "pending":
                    messages.error(request, "This request is already reviewed.")
                    return redirect("identity_queue")
                if form.cleaned_data["decision"] == "approved":
                    IdentityLink.objects.create(
                        citizen=item.citizen,
                        department="revenue",
                        external_id=item.external_id,
                    )
                item.status = form.cleaned_data["decision"]
                item.note = form.cleaned_data["note"]
                item.verification_reference = form.cleaned_data[
                    "verification_reference"
                ]
                item.reviewer = request.user
                item.reviewed_at = timezone.now()
                item.save()
                Audit.objects.create(
                    actor=request.user,
                    citizen=item.citizen,
                    action="identity." + item.status,
                    outcome="success",
                    detail="Operator recorded manual verification; reference: "
                    + item.verification_reference,
                )
            messages.success(request, "Identity review saved.")
            return redirect("identity_queue")
        except IntegrityError:
            messages.error(
                request,
                "This citizen or Revenue ID is already linked. No new link was saved.",
            )
    return render(
        request,
        "form.html",
        {
            "form": form,
            "title": "Review identity request",
            "subtitle": str(item.citizen)
            + " → "
            + item.external_id
            + ". Verify evidence through your approved process before approval.",
            "button": "Record review",
        },
    )


@require_GET
def health(request):
    try:
        Application.objects.exists()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "service": "civicbridge"})


@login_required
@require_GET
def document_download(request, pk):
    app = accessible_app(request.user, pk)
    if not current_consent(app):
        return HttpResponseForbidden("Active consent required.")
    if not app.encrypted_document:
        return HttpResponseForbidden("No shared certificate is available.")
    log(
        request.user,
        app,
        "document.download",
        "success",
        "Authorised user downloaded the shared certificate JSON.",
    )
    response = JsonResponse(app.document_snapshot, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = (
        'attachment; filename="certificate-' + str(app.reference) + '.json"'
    )
    response["Cache-Control"] = "private, no-store"
    return response
