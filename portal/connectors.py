import json, time
from datetime import date
from urllib.parse import urlparse, quote
import requests
from django.conf import settings
from django.core import signing
from django.utils import timezone
from .models import IdentityLink


class ExchangeError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class RevenueConnector:
    code = "revenue"

    def _url(self, path):
        base = settings.REVENUE_API_URL.rstrip("/")
        parsed = urlparse(base)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ["", "/"]
        ):
            raise ExchangeError("Revenue API origin is misconfigured.")
        if parsed.scheme != "https" and not (
            settings.ALLOW_LOCAL_HTTP and parsed.scheme == "http"
        ):
            raise ExchangeError("Revenue API requires HTTPS.")
        return base + path

    def fetch(self, citizen, consent, job_id):
        link = IdentityLink.objects.filter(
            citizen=citizen, department=self.code
        ).first()
        if not link:
            raise ExchangeError(
                "An operator-approved Revenue identity link is required."
            )
        grant = {
            "resident": link.external_id,
            "application": str(consent.application.reference),
            "revision": str(consent.revision),
            "scope": "income_certificate",
            "purpose": consent.purpose,
            "audience": "revenue",
            "expires": consent.expires_at.isoformat(),
        }
        signed = signing.dumps(
            grant, key=settings.GRANT_SIGNING_KEY, salt="civicbridge.exchange.v1"
        )
        headers = {
            "Authorization": "Bearer " + settings.REVENUE_API_TOKEN,
            "X-Consent-Grant": signed,
            "X-Request-ID": str(job_id),
        }
        try:
            with requests.get(
                self._url("/api/v1/income/" + quote(link.external_id, safe="") + "/"),
                headers=headers,
                timeout=(3, 8),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise ExchangeError(
                        "Revenue API response " + str(response.status_code) + ".",
                        retryable=response.status_code in [429, 500, 502, 503, 504],
                    )
                if "application/json" not in response.headers.get("Content-Type", ""):
                    raise ExchangeError(
                        "Revenue API returned an unsupported content type."
                    )
                body = b""
                deadline = time.monotonic() + 20
                for chunk in response.iter_content(4096):
                    if time.monotonic() > deadline:
                        raise ExchangeError(
                            "Revenue response exceeded the time limit.", retryable=True
                        )
                    body += chunk
                    if len(body) > 65536:
                        raise ExchangeError(
                            "Revenue API response exceeded the document limit."
                        )
                raw = json.loads(body)
        except (requests.Timeout, requests.ConnectionError) as error:
            raise ExchangeError(
                "Revenue API is temporarily unreachable.", retryable=True
            ) from error
        except (ValueError, requests.RequestException) as error:
            raise ExchangeError("Revenue API response could not be read.") from error
        if not isinstance(raw, dict):
            raise ExchangeError("Revenue API returned an invalid document.")
        if raw.get("resident_number") != link.external_id:
            raise ExchangeError("Source identity did not match the verified link.")
        return {
            "document_id": raw.get("certificate_number"),
            "type": "income_certificate",
            "holder": raw.get("resident_name"),
            "annual_income": raw.get("yearly_income"),
            "district": raw.get("district_name"),
            "issued_on": raw.get("issue_date"),
            "valid_until": raw.get("expiry_date"),
            "verified": raw.get("verified"),
            "source": "Revenue API",
        }

    def health(self):
        try:
            response = requests.get(
                self._url("/health/"), timeout=(2, 3), allow_redirects=False
            )
            available = response.status_code == 200
        except (requests.RequestException, ExchangeError):
            available = False
        return {
            "name": "Revenue API",
            "mode": "Authenticated HTTP adapter",
            "status": "Available" if available else "Unavailable",
        }


def validate_document(data):
    required = [
        "document_id",
        "type",
        "holder",
        "annual_income",
        "district",
        "issued_on",
        "valid_until",
        "verified",
        "source",
    ]
    if not isinstance(data, dict) or not set(required).issubset(data):
        raise ExchangeError("Source returned an incomplete document.")
    if data["type"] != "income_certificate" or data["verified"] is not True:
        raise ExchangeError("Document is not a verified income certificate.")
    if (
        type(data["annual_income"]) is not int
        or not 0 <= data["annual_income"] <= 10**12
    ):
        raise ExchangeError("Source income value is invalid.")
    for key in ["document_id", "holder", "district", "source"]:
        if not isinstance(data[key], str) or not 0 < len(data[key].strip()) <= 200:
            raise ExchangeError("Source text value is invalid.")
    try:
        issued = date.fromisoformat(data["issued_on"])
        expiry = date.fromisoformat(data["valid_until"])
    except (ValueError, TypeError):
        raise ExchangeError("Source date is invalid.")
    if (
        issued > timezone.localdate()
        or expiry < timezone.localdate()
        or expiry < issued
    ):
        raise ExchangeError("Certificate is expired or dates are inconsistent.")
    return {key: data[key] for key in required}


CONNECTORS = {"revenue": RevenueConnector()}
