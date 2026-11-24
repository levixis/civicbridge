import json
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .connectors import ExchangeError
from .crypto import unseal
from .models import Application, Audit, SandboxRun
from .sandbox import (
    ENDPOINT,
    HEADERS,
    cancel,
    enqueue,
    official_exchange,
    sample_request,
    tick_sandbox,
    visible_result,
)


@override_settings(SANDBOX_ENABLED=True)
class SandboxTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "sandbox-owner", email="private@example.org"
        )
        self.other = User.objects.create_user("other")
        self.client.force_login(self.owner)

    def response(
        self, status=200, body=b'{"sample":true}', content_type="application/json"
    ):
        result = MagicMock()
        result.__enter__.return_value = result
        result.status_code = status
        result.headers = {"Content-Type": content_type}
        result.iter_content.return_value = [body]
        return result

    def test_official_exact_contract_and_no_private_data(self):
        with patch(
            "portal.sandbox.requests.post", return_value=self.response()
        ) as post:
            result = official_exchange()
        args, kwargs = post.call_args
        self.assertEqual(args, (ENDPOINT,))
        self.assertEqual(kwargs["headers"], HEADERS)
        self.assertEqual(kwargs["json"], sample_request())
        self.assertNotIn("private@example.org", json.dumps(kwargs))
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (3, 8))
        self.assertTrue(result["sample_data"])

    def test_fixture_stays_separate_from_real_applications(self):
        run = enqueue(self.owner, "fixture")
        with patch("portal.sandbox.requests.post") as post:
            self.assertTrue(tick_sandbox())
            post.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, "received")
        self.assertNotIn("Fictional Test Citizen", run.encrypted_response)
        self.assertIn("Fictional Test Citizen", visible_result(run)["body"])
        self.assertEqual(Application.objects.count(), 0)
        self.assertTrue(
            Audit.objects.filter(action="sandbox.exchange", outcome="received").exists()
        )

    def test_official_404_stored_as_failed_without_retries(self):
        run = enqueue(self.owner, "official")
        with patch(
            "portal.sandbox.requests.post",
            return_value=self.response(404, b'{"error":"record_not_found"}'),
        ):
            tick_sandbox()
        run.refresh_from_db()
        self.assertEqual(
            (run.status, run.attempts, run.http_status), ("failed", 1, 404)
        )
        self.assertIn("record_not_found", unseal(run.encrypted_response)["body"])
        self.assertFalse(tick_sandbox())

    def test_http_503_backoff_then_success(self):
        run = enqueue(self.owner, "official")
        with patch("portal.sandbox.requests.post", return_value=self.response(503)):
            tick_sandbox()
        run.refresh_from_db()
        self.assertEqual((run.status, run.attempts), ("queued", 1))
        self.assertGreater(run.run_after, timezone.now())
        self.assertFalse(tick_sandbox())
        SandboxRun.objects.filter(pk=run.pk).update(run_after=timezone.now())
        with patch("portal.sandbox.requests.post", return_value=self.response()):
            tick_sandbox()
        run.refresh_from_db()
        self.assertEqual((run.status, run.http_status), ("received", 200))
        self.assertEqual(run.last_error, "")

    def test_timeout_retries_stop_after_four(self):
        run = enqueue(self.owner, "official")
        for attempt in range(4):
            SandboxRun.objects.filter(pk=run.pk).update(run_after=timezone.now())
            with patch("portal.sandbox.requests.post", side_effect=requests.Timeout):
                tick_sandbox()
        run.refresh_from_db()
        self.assertEqual((run.status, run.attempts), ("failed", 4))

    def test_duplicate_active_run_is_reused(self):
        run = enqueue(self.owner, "fixture")
        self.assertEqual(enqueue(self.owner, "official").pk, run.pk)
        self.assertEqual(SandboxRun.objects.count(), 1)

    def test_run_limit_returns_form_error(self):
        for _ in range(10):
            SandboxRun.objects.create(
                owner=self.owner,
                mode="fixture",
                status="received",
                expires_at=timezone.now() + timedelta(hours=24),
            )
        response = self.client.post(
            reverse("sandbox"), {"mode": "official", "consent": "on"}
        )
        self.assertContains(response, "ten sandbox runs per hour")
        self.assertEqual(SandboxRun.objects.count(), 10)

    def test_adapter_over_actual_loopback_http_with_exact_contract(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread

        captured = []

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                request_body = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                captured.append((self.path, dict(self.headers), request_body))
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.end_headers()
                self.wfile.write(b"<Certificate>Explicit test XML only</Certificate>")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/certificate/v3/edistrictup/incer"
            # Only the test replaces the constant origin; production accepts no URL input.
            with patch("portal.sandbox.ENDPOINT", url):
                result = official_exchange()
            self.assertEqual(result["http_status"], 200)
            self.assertEqual(captured[0][0], "/certificate/v3/edistrictup/incer")
            self.assertEqual(captured[0][2], sample_request())
            self.assertEqual(
                captured[0][1]["X-APISETU-APIKEY"], HEADERS["X-APISETU-APIKEY"]
            )
            self.assertEqual(
                captured[0][1]["X-APISETU-CLIENTID"], HEADERS["X-APISETU-CLIENTID"]
            )
            self.assertEqual(result["content_type"], "application/xml")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_revoke_during_http_cannot_restore_response(self):
        run = enqueue(self.owner, "official")

        def callback(*args, **kwargs):
            cancel(self.owner, run.pk)
            return self.response()

        with patch("portal.sandbox.requests.post", side_effect=callback):
            tick_sandbox()
        run.refresh_from_db()
        self.assertEqual((run.status, run.encrypted_response), ("cancelled", ""))

    def test_expiry_blocks_inflight_commit_and_purges_completed(self):
        run = enqueue(self.owner, "fixture")
        tick_sandbox()
        SandboxRun.objects.filter(pk=run.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        run.refresh_from_db()
        self.assertEqual(visible_result(run), {})
        tick_sandbox()
        run.refresh_from_db()
        self.assertEqual((run.status, run.encrypted_response), ("expired", ""))

    def test_expired_lease_is_recovered_and_stale_token_cannot_commit(self):
        run = enqueue(self.owner, "official")
        SandboxRun.objects.filter(pk=run.pk).update(
            status="running",
            attempts=1,
            lease_token=uuid.uuid4(),
            lease_until=timezone.now() - timedelta(seconds=1),
        )

        def callback(*args, **kwargs):
            SandboxRun.objects.filter(pk=run.pk).update(lease_token=uuid.uuid4())
            return self.response()

        with patch("portal.sandbox.requests.post", side_effect=callback):
            tick_sandbox()
        run.refresh_from_db()
        self.assertEqual(run.attempts, 2)
        self.assertEqual(run.encrypted_response, "")

    def test_unsupported_html_oversize_invalid_json_and_redirect_rejected(self):
        for response in [
            self.response(content_type="text/html"),
            self.response(body=b"x" * 65537),
            self.response(body=b"invalid"),
            self.response(302, content_type="text/html"),
        ]:
            with self.subTest(response=response), patch(
                "portal.sandbox.requests.post", return_value=response
            ), self.assertRaises(ExchangeError):
                official_exchange()

    def test_no_consent_no_job_and_invalid_mode_no_job(self):
        self.client.post(reverse("sandbox"), {"mode": "official"})
        self.client.post(reverse("sandbox"), {"mode": "live", "consent": "on"})
        self.assertEqual(SandboxRun.objects.count(), 0)

    def test_owner_only_and_csrf_required(self):
        response = self.client.post(
            reverse("sandbox"), {"mode": "fixture", "consent": "on"}
        )
        run = SandboxRun.objects.get()
        self.assertRedirects(response, reverse("sandbox_detail", args=[run.pk]))
        from django.test import Client

        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(
            csrf.post(reverse("sandbox_revoke", args=[run.pk])).status_code, 403
        )
        self.client.force_login(self.other)
        for name in ["sandbox_detail", "sandbox_status", "sandbox_revoke"]:
            url = reverse(name, args=[run.pk])
            response = (
                self.client.post(url)
                if name == "sandbox_revoke"
                else self.client.get(url)
            )
            self.assertEqual(response.status_code, 404)

    def test_no_store_and_html_payload_escaped(self):
        run = enqueue(self.owner, "official")
        with patch(
            "portal.sandbox.requests.post",
            return_value=self.response(body=b'{"text":"<script>alert(1)</script>"}'),
        ):
            tick_sandbox()
        response = self.client.get(reverse("sandbox_detail", args=[run.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(
            self.client.get(reverse("sandbox_status", args=[run.pk]))["Cache-Control"],
            "private, no-store",
        )

    @override_settings(SANDBOX_ENABLED=False)
    def test_disabled_sandbox_does_not_call_network(self):
        self.assertEqual(self.client.get(reverse("sandbox")).status_code, 403)
        with self.assertRaises(ExchangeError):
            enqueue(self.owner, "official")
        with patch("portal.sandbox.requests.post") as post:
            tick_sandbox()
            post.assert_not_called()
