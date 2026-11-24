import uuid
from datetime import timedelta
from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone
from .models import Application, ExchangeJob, Event, Consent, WorkerHeartbeat
from .services import current_consent, log
from .connectors import CONNECTORS, validate_document, ExchangeError


def claim_job():
    now = timezone.now()
    eligible = Q(status="queued", run_after__lte=now) | Q(
        status="running", lease_until__lt=now
    )
    with transaction.atomic():
        # Atomic compare-and-swap claims work on PostgreSQL and single-process local SQLite.
        job = (
            ExchangeJob.objects.filter(eligible)
            .order_by("run_after", "created_at")
            .first()
        )
        if not job:
            return None
        token = uuid.uuid4()
        claimed = (
            ExchangeJob.objects.filter(pk=job.pk)
            .filter(eligible)
            .update(
                status="running",
                lease_until=now + timedelta(seconds=60),
                lease_token=token,
                attempts=F("attempts") + 1,
            )
        )
        if not claimed:
            return None
        job.refresh_from_db()
        return job


def process_job(job):
    token = job.lease_token
    with transaction.atomic():
        app = (
            Application.objects.select_for_update(of=("self",))
            .select_related("citizen__user")
            .get(pk=job.application_id)
        )
        live = (
            ExchangeJob.objects.select_for_update()
            .filter(pk=job.pk, status="running", lease_token=token)
            .first()
        )
        if not live:
            return
        consent = current_consent(app)
        from .permissions import is_officer

        actor = job.requested_by
        if not actor or not (actor.pk == app.citizen.user_id or is_officer(actor)):
            cancel_job(job, app, "Requester no longer has application access.")
            return
        if (
            not consent
            or consent.revision != job.consent_revision
            or app.status in ["approved", "rejected"]
        ):
            cancel_job(job, app, "Consent is no longer active.")
            return
        if job.attempts > 4:
            fail_job(job, app, "Maximum exchange attempts exceeded.")
            return
    error = None
    data = None
    try:
        data = validate_document(
            CONNECTORS["revenue"].fetch(app.citizen, consent, job.id)
        )
    except ExchangeError as exc:
        error = exc
    except Exception:
        import logging

        logging.getLogger(__name__).error(
            "Unexpected exchange worker error for job %s", job.pk
        )
        error = ExchangeError(
            "Exchange processing failed unexpectedly.", retryable=True
        )
    # Network IO never holds the application row lock. Recheck consent and lease after IO.
    with transaction.atomic():
        app = Application.objects.select_for_update().get(pk=job.application_id)
        if (
            not ExchangeJob.objects.select_for_update()
            .filter(pk=job.pk, status="running", lease_token=token)
            .first()
        ):
            return
        consent = current_consent(app)
        from .permissions import is_officer

        actor = job.requested_by
        if not actor or not (actor.pk == app.citizen.user_id or is_officer(actor)):
            cancel_job(job, app, "Requester no longer has application access.")
            return
        if (
            not consent
            or consent.revision != job.consent_revision
            or app.status in ["approved", "rejected"]
        ):
            cancel_job(job, app, "Consent changed while the exchange was running.")
            return
        if error:
            log(job.requested_by, app, "document.fetch", "failed", str(error))
            if error.retryable and job.attempts < 4:
                job.status = "queued"
                job.run_after = timezone.now() + timedelta(seconds=2**job.attempts * 5)
                job.last_error = str(error)
                job.lease_until = None
                job.save()
                Event.objects.create(
                    application=app,
                    label="Source temporarily unavailable; retry scheduled",
                )
            else:
                fail_job(job, app, str(error))
            return
        app.document_snapshot = data
        app.status = "verified"
        app.save()
        job.status = "succeeded"
        job.last_error = ""
        job.lease_until = None
        job.save()
        Event.objects.create(
            application=app,
            label="Revenue API certificate validated and shared with Education",
        )
        log(
            job.requested_by,
            app,
            "document.fetch",
            "success",
            "HTTP exchange completed; validated certificate stored encrypted.",
        )


def cancel_job(job, app, reason):
    job.status = "cancelled"
    job.last_error = reason
    job.save()
    if app.status == "processing":
        app.status = "pending"
        app.save()
    log(job.requested_by, app, "document.fetch", "denied", reason)


def fail_job(job, app, reason):
    job.status = "failed"
    job.last_error = reason
    job.lease_until = None
    job.save()
    app.status = "pending"
    app.save()
    Event.objects.create(
        application=app, label="Document exchange failed; a new request can be made"
    )


def purge_expired():
    ids = (
        Application.objects.filter(consent__expires_at__lte=timezone.now())
        .exclude(encrypted_document="")
        .values_list("pk", flat=True)
    )
    count = 0
    for pk in list(ids[:200]):
        with transaction.atomic():
            app = Application.objects.select_for_update().get(pk=pk)
            if current_consent(app):
                continue
            app.encrypted_document = ""
            if app.status in ["verified", "processing"]:
                app.status = "pending"
            app.save()
            count += 1
            log(
                None,
                app,
                "document.purge",
                "success",
                "Expired shared document removed by retention worker.",
            )
    return count


def tick():
    WorkerHeartbeat.objects.update_or_create(
        name="exchange-worker", defaults={"last_seen": timezone.now()}
    )
    purge_expired()
    job = claim_job()
    if job:
        process_job(job)
    from .sandbox import tick_sandbox

    sandbox_worked = tick_sandbox()
    from integration.engine import tick_platform
    platform_worked = tick_platform()
    return job is not None or sandbox_worked or platform_worked
