from datetime import date, timedelta
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import Citizen, Application, Consent, IdentityLink, Audit
from .services import exchange, revoke, decide
from .worker import tick, claim_job, process_job, purge_expired
from .models import ExchangeJob, IdentityRequest
from .connectors import ExchangeError
from .forms import CitizenAuthenticationForm, StaffAuthenticationForm


class SignInSeparationTests(TestCase):
    def setUp(self):
        self.citizen = User.objects.create_user("citizen-sign-in")
        Citizen.objects.create(user=self.citizen)
        self.reviewer = User.objects.create_user("reviewer-sign-in")
        self.reviewer.groups.add(Group.objects.create(name="Education Officers"))

    def test_citizen_and_staff_have_separate_sign_in_pages(self):
        citizen_page = self.client.get(reverse("login"))
        self.assertContains(citizen_page, "<h1>Citizen sign-in</h1>", html=True)
        self.assertContains(citizen_page, reverse("staff_login"))
        staff_page = self.client.get(reverse("staff_login"))
        self.assertContains(staff_page, "<h1>Department staff sign-in</h1>", html=True)
        for department in ["revenue", "municipality", "education", "welfare", "operations"]:
            self.assertContains(staff_page, reverse("staff_start", args=[department]))
        self.assertNotContains(staff_page, "Start application")

    def test_local_sign_in_forms_enforce_their_account_type(self):
        CitizenAuthenticationForm().confirm_login_allowed(self.citizen)
        StaffAuthenticationForm().confirm_login_allowed(self.reviewer)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            CitizenAuthenticationForm().confirm_login_allowed(self.reviewer)
        with self.assertRaises(ValidationError):
            StaffAuthenticationForm().confirm_login_allowed(self.citizen)

    def test_source_staff_sign_in_uses_its_department_and_prompts_for_credentials(self):
        from django.conf import settings
        from common.demo import demo_subject
        for department in ["revenue", "municipality"]:
            with self.subTest(department=department):
                response = self.client.get(reverse("staff_start", args=[department]))
                destination = settings.SSO_DEPARTMENT_ROUTES[str(demo_subject(department))]
                self.assertRedirects(response, destination + "?prompt=login", fetch_redirect_response=False)

    def test_reviewer_with_a_citizen_profile_still_gets_the_staff_workspace(self):
        Citizen.objects.create(user=self.reviewer)
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse("staff_workspace"))
        self.assertContains(response, "<h1>Review workspace</h1>", html=True)
        self.assertNotContains(response, "Browse services")
        self.assertNotContains(response, ">My applications</a>")
        self.assertNotContains(self.client.get(reverse("platform_catalog")), "Start application")

    def test_citizen_cannot_enter_a_review_workspace(self):
        self.client.force_login(self.citizen)
        self.assertRedirects(self.client.get(reverse("staff_workspace")), reverse("platform_workspace"))


class WorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="TestPassword726!")
        self.other = User.objects.create_user("other", password="TestPassword726!")
        self.officer = User.objects.create_user("officer", password="TestPassword726!")
        self.officer.groups.add(Group.objects.create(name="Education Officers"))
        self.citizen = Citizen.objects.create(user=self.owner)
        Citizen.objects.create(user=self.other)
        IdentityLink.objects.create(
            citizen=self.citizen, department="revenue", external_id="REV-1"
        )
        self.fetch_patch = patch(
            "portal.connectors.RevenueConnector.fetch",
            return_value={
                "document_id": "INC-1",
                "type": "income_certificate",
                "holder": "Owner Demo",
                "annual_income": 100000,
                "district": "Pune",
                "issued_on": date.today().isoformat(),
                "valid_until": (date.today() + timedelta(days=365)).isoformat(),
                "verified": True,
                "source": "Revenue API",
            },
        )
        self.fetch_patch.start()
        self.addCleanup(self.fetch_patch.stop)
        self.app = Application.objects.create(
            citizen=self.citizen,
            institution="Demo college",
            course="BTech",
            statement="Scholarship request",
        )

    def consent(self):
        return Consent.objects.create(
            application=self.app, expires_at=timezone.now() + timedelta(days=7)
        )

    def test_end_to_end_exchange_and_approval(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("grant", args=[self.app.pk]), {"agree": "on"}
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("fetch", args=[self.app.pk]))
        tick()
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "verified")
        self.assertEqual(self.app.document_snapshot["annual_income"], 100000)
        self.assertEqual(
            self.client.get(reverse("detail", args=[self.app.pk])).status_code, 200
        )
        self.client.force_login(self.officer)
        response = self.client.post(
            reverse("decision", args=[self.app.pk]),
            {"decision": "approved", "note": "Checked the fictional record."},
        )
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "approved")
        self.client.force_login(self.owner)
        result = self.client.get(reverse("tracker_api", args=[self.app.pk])).json()
        self.assertEqual(result["status"], "approved")
        self.assertEqual(len(result["events"]), 4)

    def test_no_consent_no_exchange_and_audited(self):
        ok, _ = exchange(self.owner, self.app.pk)
        self.assertFalse(ok)
        self.assertTrue(Audit.objects.filter(outcome="denied").exists())
        self.app.refresh_from_db()
        self.assertEqual(self.app.document_snapshot, {})

    def test_expired_consent_blocks_exchange_and_decision(self):
        consent = self.consent()
        exchange(self.owner, self.app.pk)
        tick()
        tick()
        consent.expires_at = timezone.now() - timedelta(seconds=1)
        consent.save()
        self.assertFalse(exchange(self.owner, self.app.pk)[0])
        self.assertFalse(decide(self.officer, self.app.pk, "approved", "note")[0])
        self.client.force_login(self.owner)
        response = self.client.get(reverse("detail", args=[self.app.pk]))
        self.assertEqual(response.context["document"], {})

    def test_revocation_removes_copy_and_blocks_future_fetch(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        tick()
        self.assertTrue(revoke(self.owner, self.app.pk)[0])
        self.app.refresh_from_db()
        self.assertEqual(self.app.document_snapshot, {})
        self.assertEqual(self.app.status, "pending")
        self.assertFalse(exchange(self.officer, self.app.pk)[0])
        self.assertTrue(
            Audit.objects.filter(action="document.fetch", outcome="success").exists()
        )

    def test_revocation_after_decision_retains_status(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        tick()
        decide(self.officer, self.app.pk, "approved", "note")
        revoke(self.owner, self.app.pk)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "approved")
        self.assertEqual(self.app.document_snapshot, {})

    def test_other_citizen_cannot_read_or_mutate(self):
        self.consent()
        self.client.force_login(self.other)
        for name in ["detail", "tracker_api"]:
            self.assertEqual(
                self.client.get(reverse(name, args=[self.app.pk])).status_code, 404
            )
        for name in ["grant", "fetch", "revoke", "exchange_api"]:
            self.assertEqual(
                self.client.post(
                    reverse(name, args=[self.app.pk]), {"agree": "on"}
                ).status_code,
                404,
            )
        self.assertFalse(exchange(self.other, self.app.pk)[0])

    def test_citizen_cannot_act_as_officer_or_operator(self):
        self.client.force_login(self.owner)
        for name in ["officer", "monitor", "identity_queue"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("decision", args=[self.app.pk]),
                {"decision": "approved", "note": "bad"},
            ).status_code,
            403,
        )

    def test_bad_source_is_rejected(self):
        self.consent()
        with patch(
            "portal.connectors.RevenueConnector.fetch",
            return_value={"annual_income": "invalid"},
        ):
            self.assertTrue(exchange(self.owner, self.app.pk)[0])
            tick()
        self.app.refresh_from_db()
        self.assertEqual(self.app.document_snapshot, {})
        self.assertTrue(Audit.objects.filter(outcome="failed").exists())

    def test_missing_identity_link_is_visible_failure(self):
        self.consent()
        IdentityLink.objects.all().delete()
        self.fetch_patch.stop()
        exchange(self.owner, self.app.pk)
        tick()
        job = ExchangeJob.objects.get(application=self.app)
        self.assertEqual(job.status, "failed")
        self.assertIn("identity", job.last_error)

    def test_expired_source_certificate_rejected(self):
        self.consent()
        payload = self.fetch_patch.target.fetch.return_value.copy()
        payload["valid_until"] = (date.today() - timedelta(days=1)).isoformat()
        with patch("portal.connectors.RevenueConnector.fetch", return_value=payload):
            exchange(self.owner, self.app.pk)
            tick()
        self.assertEqual(ExchangeJob.objects.get(application=self.app).status, "failed")

    def test_post_only_and_csrf(self):
        self.client.force_login(self.owner)
        for name in ["grant", "fetch", "revoke", "exchange_api"]:
            self.assertEqual(
                self.client.get(reverse(name, args=[self.app.pk])).status_code, 405
            )
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        self.assertEqual(
            strict.post(
                reverse("grant", args=[self.app.pk]), {"agree": "on"}
            ).status_code,
            403,
        )

    def test_all_workspaces_render(self):
        for name in ["home", "register", "login"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.client.force_login(self.owner)
        for name in ["dashboard", "apply"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("detail", args=[self.app.pk])).status_code, 200
        )
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get(reverse("officer")).status_code, 200)
        user = User.objects.create_user("integrationoperator")
        user.groups.add(Group.objects.create(name="Integration Operators"))
        self.client.force_login(user)
        with patch(
            "portal.connectors.RevenueConnector.health",
            return_value={"name": "Revenue", "mode": "HTTP", "status": "Available"},
        ):
            self.assertEqual(self.client.get(reverse("monitor")).status_code, 200)
        self.assertEqual(self.client.get(reverse("identity_queue")).status_code, 200)

    def test_registration_creates_profile_and_session(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newstudent",
                "first_name": "New",
                "last_name": "Student",
                "email": "new@example.com",
                "password1": "Demo-New-Pass726!",
                "password2": "Demo-New-Pass726!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Citizen.objects.filter(user__username="newstudent").exists())
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        response = self.client.post(
            reverse("login"), {"username": "NEW@EXAMPLE.COM", "password": "Demo-New-Pass726!"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get(username="newstudent").pk)

    def test_registration_rejects_conflicting_sign_in_identifiers(self):
        User.objects.create_user("existing", email="existing@example.com")
        User.objects.create_user("alias@example.com")
        defaults = {
            "first_name": "New", "last_name": "Student",
            "password1": "Demo-New-Pass726!", "password2": "Demo-New-Pass726!",
        }
        cases = [
            ("newstudent", "EXISTING@example.com", "This email address is already used for portal sign-in."),
            ("newstudent", "ALIAS@example.com", "This email address is already used for portal sign-in."),
            ("EXISTING@example.com", "new@example.com", "This username is already used as a portal sign-in email."),
        ]
        for username, email, message in cases:
            with self.subTest(username=username, email=email):
                response = self.client.post(reverse("register"), defaults | {"username": username, "email": email})
                self.assertContains(response, message)
                self.assertFalse(User.objects.filter(username=username).exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unchecked_consent_not_saved(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("grant", args=[self.app.pk]), {})
        self.assertFalse(Consent.objects.filter(application=self.app).exists())

    def test_api_exchange_obeys_same_rules(self):
        self.client.force_login(self.owner)
        url = reverse("exchange_api", args=[self.app.pk])
        self.assertEqual(self.client.post(url).status_code, 409)
        self.consent()
        self.assertEqual(self.client.post(url).status_code, 202)

    def test_wrong_consent_scope_blocks_exchange(self):
        consent = self.consent()
        consent.scope = "another_document"
        consent.save()
        self.assertFalse(exchange(self.owner, self.app.pk)[0])
        self.app.refresh_from_db()
        self.assertEqual(self.app.document_snapshot, {})

    def test_storage_is_encrypted(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        tick()
        self.app.refresh_from_db()
        self.assertNotIn("Owner Demo", self.app.encrypted_document)
        self.assertEqual(self.app.document_snapshot["holder"], "Owner Demo")

    def test_duplicate_requests_create_one_job(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        exchange(self.owner, self.app.pk)
        self.assertEqual(ExchangeJob.objects.filter(application=self.app).count(), 1)
        tick()
        self.assertEqual(
            Audit.objects.filter(action="document.fetch", outcome="success").count(), 1
        )

    def test_retry_then_success(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        with patch(
            "portal.connectors.RevenueConnector.fetch",
            side_effect=ExchangeError("Unavailable", retryable=True),
        ):
            tick()
        job = ExchangeJob.objects.get(application=self.app)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.attempts, 1)
        job.run_after = timezone.now()
        job.save()
        tick()
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.attempts, 2)

    def test_retry_exhaustion(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        with patch(
            "portal.connectors.RevenueConnector.fetch",
            side_effect=ExchangeError("Unavailable", retryable=True),
        ):
            for _ in range(4):
                ExchangeJob.objects.filter(application=self.app).update(
                    run_after=timezone.now()
                )
                tick()
        self.assertEqual(ExchangeJob.objects.get(application=self.app).status, "failed")

    def test_revocation_during_network_call_discards_response(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        valid = self.fetch_patch.target.fetch.return_value.copy()

        def source(*args):
            revoke(self.owner, self.app.pk)
            return valid

        with patch("portal.connectors.RevenueConnector.fetch", side_effect=source):
            tick()
        self.app.refresh_from_db()
        self.assertEqual(self.app.document_snapshot, {})
        self.assertEqual(
            ExchangeJob.objects.get(application=self.app).status, "cancelled"
        )

    def test_worker_recovers_abandoned_lease(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        first = claim_job()
        self.assertIsNotNone(first)
        ExchangeJob.objects.filter(pk=first.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        second = claim_job()
        self.assertNotEqual(first.lease_token, second.lease_token)
        process_job(first)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "processing")
        process_job(second)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, "verified")

    def test_retention_removes_expired_copy(self):
        consent = self.consent()
        exchange(self.owner, self.app.pk)
        tick()
        consent.expires_at = timezone.now() - timedelta(seconds=1)
        consent.save()
        self.assertEqual(purge_expired(), 1)
        self.app.refresh_from_db()
        self.assertEqual(self.app.document_snapshot, {})

    def test_citizen_cannot_self_link(self):
        IdentityLink.objects.all().delete()
        self.client.force_login(self.owner)
        self.client.post(reverse("identity_request"), {"external_id": "REV-2"})
        self.assertEqual(
            IdentityRequest.objects.filter(citizen=self.citizen).count(), 1
        )
        self.assertFalse(IdentityLink.objects.filter(citizen=self.citizen).exists())

    def test_operator_approves_identity_with_evidence(self):
        IdentityLink.objects.all().delete()
        item = IdentityRequest.objects.create(citizen=self.citizen, external_id="REV-2")
        operator = User.objects.create_user("operator")
        operator.groups.add(Group.objects.create(name="Integration Operators"))
        self.client.force_login(operator)
        response = self.client.post(
            reverse("identity_review", args=[item.pk]),
            {
                "decision": "approved",
                "verification_reference": "VERIFIED-CASE-1",
                "note": "Evidence checked through approved process.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            IdentityLink.objects.filter(
                citizen=self.citizen, external_id="REV-2"
            ).exists()
        )

    def test_download_requires_live_consent(self):
        self.consent()
        exchange(self.owner, self.app.pk)
        tick()
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(
                reverse("document_download", args=[self.app.pk])
            ).status_code,
            200,
        )
        revoke(self.owner, self.app.pk)
        self.assertEqual(
            self.client.get(
                reverse("document_download", args=[self.app.pk])
            ).status_code,
            403,
        )

    def test_login_lockout(self):
        for _ in range(5):
            self.client.post(
                reverse("login"), {"username": "owner", "password": "wrong"}
            )
        self.assertEqual(
            self.client.post(
                reverse("login"), {"username": "owner", "password": "wrong"}
            ).status_code,
            429,
        )

    def test_password_reset_does_not_enumerate_accounts(self):
        self.assertEqual(
            self.client.post(
                reverse("password_reset"), {"email": "missing@example.org"}
            ).status_code,
            302,
        )

    def test_removed_officer_role_blocks_pending_job(self):
        self.consent()
        exchange(self.officer, self.app.pk)
        self.officer.groups.clear()
        tick()
        self.assertEqual(
            ExchangeJob.objects.get(application=self.app).status, "cancelled"
        )
