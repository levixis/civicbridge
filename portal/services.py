import uuid
from django.db import transaction
from django.utils import timezone
from .models import Application, Consent, Event, Audit, ExchangeJob
from .connectors import ExchangeError, validate_document
from .permissions import is_officer


def log(actor, app, action, outcome, detail):
    return Audit.objects.create(
        actor=actor,
        citizen=app.citizen,
        application=app,
        action=action,
        outcome=outcome,
        detail=detail,
    )


def current_consent(app):
    consent = Consent.objects.filter(application=app).first()
    return (
        consent
        if consent and consent.active and consent.scope == "income_certificate"
        else None
    )


@transaction.atomic
def exchange(actor, pk):
    app = (
        Application.objects.select_for_update(of=("self",))
        .select_related("citizen__user")
        .get(pk=pk)
    )
    if not (actor.pk == app.citizen.user_id or is_officer(actor)):
        log(
            actor, app, "document.request", "denied", "Caller lacks application access."
        )
        return False, "Access denied."
    consent = current_consent(app)
    if not consent:
        log(
            actor,
            app,
            "document.request",
            "denied",
            "Missing, expired or revoked consent.",
        )
        return False, "An active citizen consent is required."
    if app.status in ["approved", "rejected"]:
        return False, "Application is already decided."
    if ExchangeJob.objects.filter(
        application=app, status__in=["queued", "running"]
    ).exists():
        return True, "An exchange is already queued or running."
    ExchangeJob.objects.create(
        application=app, requested_by=actor, consent_revision=consent.revision
    )
    app.status = "processing"
    app.document_snapshot = {}
    app.save()
    Event.objects.create(application=app, label="Document exchange queued")
    log(
        actor,
        app,
        "document.request",
        "success",
        "Durable job created for an authenticated Revenue API exchange.",
    )
    return True, "Exchange queued. The worker will fetch and validate the certificate."


@transaction.atomic
def grant_consent(actor, pk):
    app = Application.objects.select_for_update(of=("self",)).get(pk=pk, citizen__user=actor)
    if app.status in ["approved", "rejected"]:
        return False, "Application is already decided."
    if current_consent(app):
        return True, "Consent is already active."
    from datetime import timedelta

    Consent.objects.update_or_create(
        application=app,
        defaults={
            "revision": uuid.uuid4(),
            "granted_at": timezone.now(),
            "expires_at": timezone.now() + timedelta(days=7),
            "revoked_at": None,
            "scope": "income_certificate",
        },
    )
    ExchangeJob.objects.filter(
        application=app, status__in=["queued", "running"]
    ).update(status="cancelled", last_error="Consent replaced.")
    app.status = "pending"
    app.document_snapshot = {}
    app.save()
    Event.objects.create(
        application=app,
        label="Citizen authorised income certificate sharing for 7 days",
    )
    log(
        actor,
        app,
        "consent.grant",
        "success",
        "Revenue → Education, income certificate only, 7-day expiry.",
    )
    return True, "Consent recorded. You can now request the certificate."


def clear_shared_document(app, reason):
    revoked = Consent.objects.filter(application=app, revoked_at=None).update(
        revoked_at=timezone.now()
    )
    cancelled = ExchangeJob.objects.filter(
        application=app, status__in=["queued", "running"]
    ).update(status="cancelled", lease_until=None, lease_token=None, last_error=reason)
    if not (revoked or cancelled or app.encrypted_document):
        return False
    app.encrypted_document = ""
    if app.status in [Application.Status.VERIFIED, Application.Status.PROCESSING]:
        app.status = Application.Status.PENDING
    app.save()
    return True


@transaction.atomic
def invalidate_revenue_link(actor, citizen):
    applications = list(
        Application.objects.select_for_update().filter(citizen=citizen).order_by("pk")
    )
    for app in applications:
        if clear_shared_document(app, "Reviewed Revenue identity link changed."):
            Event.objects.create(
                application=app,
                label="Revenue identity link corrected; permission ended and shared copy removed",
            )
            log(
                actor, app, "document.identity_changed", "success",
                "Revenue identity link corrected; old consent and shared data invalidated.",
            )


@transaction.atomic
def revoke(actor, pk):
    app = Application.objects.select_for_update(of=("self",)).get(pk=pk, citizen__user=actor)
    consent = Consent.objects.filter(application=app).first()
    if not consent:
        return False, "No consent exists."
    if consent.revoked_at:
        return True, "Access is already revoked."
    clear_shared_document(app, "Consent revoked.")
    Event.objects.create(
        application=app, label="Citizen revoked access; shared document copy removed"
    )
    log(
        actor,
        app,
        "consent.revoke",
        "success",
        "Jobs cancelled and encrypted shared document removed; history retained.",
    )
    return True, "Access revoked and shared document copy removed."


@transaction.atomic
def decide(actor, pk, decision, note):
    app = Application.objects.select_for_update().get(pk=pk)
    if not is_officer(actor):
        return False, "Education officer access required."
    if app.status != "verified":
        return False, "Verify the certificate before making a decision."
    if not current_consent(app):
        return False, "Citizen consent has expired or been revoked."
    try:
        validate_document(app.document_snapshot)
    except ExchangeError as error:
        return False, str(error)
    if decision not in ["approved", "rejected"]:
        return False, "Invalid decision."
    app.status = decision
    app.officer_note = note
    app.save()
    Event.objects.create(
        application=app, label="Education decision: " + app.get_status_display()
    )
    log(
        actor,
        app,
        "application." + decision,
        "success",
        "Education officer recorded a decision.",
    )
    return True, "Decision saved and the citizen tracker updated."
