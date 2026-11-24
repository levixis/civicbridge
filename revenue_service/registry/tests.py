import uuid
from datetime import date, timedelta
from django.test import TestCase
from django.core import signing
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from .models import IncomeCertificate, Disclosure


class SourceApiTests(TestCase):
    def setUp(self):
        IncomeCertificate.objects.create(
            resident_number="REV-1",
            certificate_number="INC-1",
            resident_name="Test Owner",
            yearly_income=123000,
            district_name="Pune",
            issue_date=date.today(),
            expiry_date=date.today() + timedelta(days=365),
            verified=True,
        )
        self.grant = {
            "resident": "REV-1",
            "application": str(uuid.uuid4()),
            "revision": str(uuid.uuid4()),
            "scope": "income_certificate",
            "purpose": "Scholarship eligibility verification",
            "audience": "revenue",
            "expires": (timezone.now() + timedelta(days=7)).isoformat(),
        }
        self.headers = {
            "HTTP_AUTHORIZATION": "Bearer " + settings.REVENUE_API_TOKEN,
            "HTTP_X_REQUEST_ID": str(uuid.uuid4()),
        }

    def fetch(self, grant=None, resident="REV-1"):
        signed = signing.dumps(
            grant or self.grant,
            key=settings.GRANT_SIGNING_KEY,
            salt="civicbridge.exchange.v1",
        )
        return self.client.get(
            "/api/v1/income/" + resident + "/",
            HTTP_X_CONSENT_GRANT=signed,
            **self.headers
        )

    def test_authorised_disclosure(self):
        response = self.fetch()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["yearly_income"], 123000)
        self.assertEqual(Disclosure.objects.count(), 1)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_missing_or_invalid_bearer_denied(self):
        self.assertEqual(self.client.get("/api/v1/income/REV-1/").status_code, 401)
        response = self.client.get("/api/v1/income/REV-1/", HTTP_AUTHORIZATION="Bearer é")
        self.assertEqual(response.status_code, 401)

    def test_invalid_signature_denied(self):
        self.assertEqual(
            self.client.get(
                "/api/v1/income/REV-1/", HTTP_X_CONSENT_GRANT="invalid", **self.headers
            ).status_code,
            403,
        )

    def test_wrong_scope_denied(self):
        self.grant["scope"] = "all_records"
        self.assertEqual(self.fetch().status_code, 403)

    def test_identity_mismatch_denied(self):
        self.assertEqual(self.fetch(resident="OTHER").status_code, 403)

    def test_expired_grant_denied(self):
        self.grant["expires"] = (timezone.now() - timedelta(seconds=1)).isoformat()
        self.assertEqual(self.fetch().status_code, 403)

    def test_wrong_audience_denied(self):
        self.grant["audience"] = "other"
        self.assertEqual(self.fetch().status_code, 403)

    def test_idempotent_receipt(self):
        self.fetch()
        self.fetch()
        self.assertEqual(Disclosure.objects.count(), 1)

    def test_request_id_reuse_for_other_application_denied(self):
        self.fetch()
        self.grant["application"] = str(uuid.uuid4())
        self.assertEqual(self.fetch().status_code, 409)

    def test_citizen_cannot_use_source_registry(self):
        user = User.objects.create_user("normal")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/").status_code, 403)

    def test_source_staff_ui(self):
        user = User.objects.create_user("staff", is_staff=True)
        self.client.force_login(user)
        for path in ["/", "/certificates/new/", "/certificates/1/"]:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_service_health(self):
        self.assertEqual(self.client.get("/health/").status_code, 200)
