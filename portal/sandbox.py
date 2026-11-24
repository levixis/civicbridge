"""Isolated API Setu sample exchanges. Never called by scholarship decisions."""

import json
import time
import uuid
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .connectors import ExchangeError
from .crypto import seal, unseal
from .models import Audit, SandboxRun

ENDPOINT = "https://sandbox.api-setu.in/certificate/v3/edistrictup/incer"
CONTRACT_URL = "https://sandbox.api-setu.in/api-collection/edistrictup/0#/docs/paths/certificate-v3-edistrictup-incer/post"
SAMPLE_PATH = Path(__file__).parent / "sandbox_samples" / "edistrictup_income.json"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    # Public playground demonstration values, not private API credentials.
    "X-APISETU-APIKEY": "demokey123456ABCD789",
    "X-APISETU-CLIENTID": "in.gov.sandbox",
}


def sample_request():
    return deepcopy(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))


def official_exchange():
    """Send ONLY the official fixed sample: no account data or local identifiers."""
    try:
        with requests.post(
            ENDPOINT,
            headers=HEADERS,
            json=sample_request(),
            timeout=(3, 8),
            allow_redirects=False,
            stream=True,
        ) as response:
            body = bytearray()
            deadline = time.monotonic() + 20
            for chunk in response.iter_content(4096):
                body.extend(chunk)
                if len(body) > 65536:
                    raise ExchangeError("Sandbox response exceeded 64 KiB.")
                if time.monotonic() > deadline:
                    raise ExchangeError(
                        "Sandbox response exceeded the time limit.", True
                    )
            content_type = (
                response.headers.get("Content-Type", "").split(";")[0].lower()
            )
            if content_type not in {
                "application/json",
                "application/xml",
                "text/xml",
                "application/pdf",
            }:
                raise ExchangeError("Sandbox returned an unsupported response type.")
            # Binary PDF downloads are deliberately not rendered as active content.
            if content_type == "application/pdf":
                import base64

                text = base64.b64encode(body).decode("ascii")
            else:
                text = bytes(body).decode("utf-8")
                if content_type == "application/json":
                    text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            return {
                "http_status": response.status_code,
                "content_type": content_type,
                "body": text,
                "sample_data": True,
                "source": "Official API Setu sandbox",
            }
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise ExchangeError(
            "Official sandbox is temporarily unreachable.", True
        ) from exc
    except (requests.RequestException, ValueError) as exc:
        raise ExchangeError("Sandbox response could not be read.") from exc


def fixture_exchange():
    """Explicit classroom fixture; does not impersonate an official response."""
    return {
        "http_status": 200,
        "content_type": "application/json",
        "body": json.dumps(
            {
                "fixture": True,
                "certificate_number": "TEST-INCOME-001",
                "resident_name": "Fictional Test Citizen",
                "yearly_income": 180000,
                "district_name": "Test District",
            },
            indent=2,
        ),
        "sample_data": True,
        "source": "Local classroom fixture (no government request)",
    }


def audit(run, outcome, detail):
    Audit.objects.create(
        actor=run.owner,
        citizen=None,
        action="sandbox.exchange",
        outcome=outcome,
        detail=f"{run.id} / {run.mode}: {detail}"[:250],
    )


def enqueue(owner, mode):
    if not settings.SANDBOX_ENABLED:
        raise ExchangeError("Sandbox workspace is disabled.")
    if mode not in {"official", "fixture"}:
        raise ExchangeError("Unknown sandbox mode.")
    with transaction.atomic():
        # Serialise submissions for this owner, including on PostgreSQL.
        get_user_model().objects.select_for_update().get(pk=owner.pk)
        existing = SandboxRun.objects.filter(
            owner=owner, status__in=["queued", "running"]
        ).first()
        if existing:
            return existing
        if (
            SandboxRun.objects.filter(
                owner=owner, created_at__gte=timezone.now() - timedelta(hours=1)
            ).count()
            >= 10
        ):
            raise ExchangeError(
                "Limit reached: ten sandbox runs per hour. Try again later."
            )
        run = SandboxRun.objects.create(
            owner=owner, mode=mode, expires_at=timezone.now() + timedelta(hours=24)
        )
        audit(run, "queued", "Sample-only consent recorded locally for 24 hours.")
        return run


def cancel(owner, pk):
    with transaction.atomic():
        run = SandboxRun.objects.select_for_update().get(pk=pk, owner=owner)
        run.revoked_at = timezone.now()
        run.encrypted_response = ""
        run.status = "cancelled"
        run.lease_until = None
        run.save()
        audit(run, "revoked", "Consent revoked; stored sample response removed.")


def visible_result(run):
    return unseal(run.encrypted_response) if run.active else {}


def tick_sandbox():
    now = timezone.now()
    # Update acquires row locks; a completing worker rechecks the state under lock.
    expired = (
        SandboxRun.objects.filter(expires_at__lte=now)
        .exclude(status="expired")
        .exclude(status="cancelled")
    )
    expired.update(status="expired", encrypted_response="", lease_until=None)
    if not settings.SANDBOX_ENABLED:
        SandboxRun.objects.filter(status__in=["queued", "running"]).update(
            status="cancelled", encrypted_response="", last_error="Sandbox disabled."
        )
        return False
    eligible = (
        Q(status="queued", run_after__lte=now)
        | Q(status="running", lease_until__lt=now)
    ) & Q(expires_at__gt=now, revoked_at=None)
    run = SandboxRun.objects.filter(eligible).order_by("created_at").first()
    if not run:
        return False
    token = uuid.uuid4()
    if (
        not SandboxRun.objects.filter(pk=run.pk)
        .filter(eligible)
        .update(
            status="running",
            lease_token=token,
            lease_until=now + timedelta(seconds=60),
            attempts=F("attempts") + 1,
        )
    ):
        return False
    run.refresh_from_db()
    result, error = None, None
    try:
        if run.attempts > 4:
            raise ExchangeError("Maximum sandbox attempts exceeded.")
        result = official_exchange() if run.mode == "official" else fixture_exchange()
        if not 200 <= result["http_status"] < 300:
            error = ExchangeError(
                f"Sandbox HTTP {result['http_status']}. No certificate was verified.",
                result["http_status"] in {429, 500, 502, 503, 504},
            )
    except ExchangeError as exc:
        error = exc
    except Exception:
        error = ExchangeError("Sandbox processing failed unexpectedly.", True)
    with transaction.atomic():
        run = SandboxRun.objects.select_for_update().get(pk=run.pk)
        if run.status != "running" or run.lease_token != token:
            return True
        if not run.active or not settings.SANDBOX_ENABLED or not run.owner.is_active:
            run.status = "cancelled"
            run.encrypted_response = ""
            run.lease_until = None
            run.save()
            return True
        if result:
            run.http_status = result["http_status"]
            run.encrypted_response = seal(result)
        run.lease_until = None
        run.last_error = str(error) if error else ""
        if error:
            if error.retryable and run.attempts < 4:
                run.status = "queued"
                run.run_after = timezone.now() + timedelta(seconds=5 * 2**run.attempts)
            else:
                run.status = "failed"
        else:
            run.status = "received"
        run.save()
        audit(
            run,
            run.status,
            run.last_error
            or "Sample response received; no identity or eligibility verified.",
        )
    return True
