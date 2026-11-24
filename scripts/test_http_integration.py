"""Real loopback HTTP test: isolated databases, source/portal/worker processes, no connector mocks."""

import os, sys, tempfile, subprocess, socket, time, secrets, json
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def command(args, cwd, env):
    result = subprocess.run(
        [sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError(result.stderr)


def wait_health(url, process):
    import requests

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("A test service exited before readiness.")
        try:
            if requests.get(url, timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise RuntimeError("Test service did not become ready.")


def post(session, base, path, values):
    session.get(base + path, timeout=5)
    token = session.cookies.get("csrftoken")
    response = session.post(
        base + path,
        data=values | {"csrfmiddlewaretoken": token},
        headers={"Referer": base + path},
        timeout=10,
        allow_redirects=False,
    )
    assert response.status_code == 302, (
        path,
        response.status_code,
        response.text[:200],
    )
    return response


def main():
    import requests

    processes = []
    with tempfile.TemporaryDirectory(prefix="civicbridge-http-") as temp:
        env = os.environ.copy()
        env.update(
            {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
        )
        # Keep both databases independent and avoid any configured PostgreSQL service in local smoke tests.
        env.pop("POSTGRES_HOST", None)
        env.pop("REVENUE_POSTGRES_HOST", None)
        portal_port = free_port()
        source_port = free_port()
        base = f"http://127.0.0.1:{portal_port}"
        source = f"http://127.0.0.1:{source_port}"
        env.update(
            {
                "DJANGO_DEBUG": "1",
                "SQLITE_PATH": temp + "/portal.sqlite3",
                "REVENUE_SQLITE_PATH": temp + "/source.sqlite3",
                "REVENUE_API_URL": source,
                "ALLOW_LOCAL_HTTP": "1",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
                "REVENUE_ALLOWED_HOSTS": "127.0.0.1,localhost",
                "SANDBOX_ENABLED": "1",
            }
        )
        # dot-env does not override the explicit isolated values above.
        command(["manage.py", "migrate", "--noinput"], ROOT, env)
        command(
            ["manage.py", "migrate", "--noinput"],
            ROOT / "revenue_service",
            env | {"DJANGO_SETTINGS_MODULE": "revenue_config.settings"},
        )
        command(
            ["manage.py", "seed_revenue"],
            ROOT / "revenue_service",
            env | {"DJANGO_SETTINGS_MODULE": "revenue_config.settings"},
        )
        os.environ.update(env)
        sys.path.insert(0, str(ROOT))
        import django

        django.setup()
        from django.contrib.auth.models import User, Group
        from portal.models import Application, IdentityRequest, ExchangeJob

        password = secrets.token_urlsafe(20)
        for username, role in [
            ("operator", "Integration Operators"),
            ("education", "Education Officers"),
        ]:
            user = User.objects.create_user(username, password=password)
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
        logs = open(temp + "/services.log", "w+")
        try:
            source_process = subprocess.Popen(
                [
                    sys.executable,
                    "manage.py",
                    "runserver",
                    f"127.0.0.1:{source_port}",
                    "--noreload",
                ],
                cwd=ROOT / "revenue_service",
                env=env | {"DJANGO_SETTINGS_MODULE": "revenue_config.settings"},
                stdout=logs,
                stderr=logs,
            )
            processes.append(source_process)
            portal_process = subprocess.Popen(
                [
                    sys.executable,
                    "manage.py",
                    "runserver",
                    f"127.0.0.1:{portal_port}",
                    "--noreload",
                ],
                cwd=ROOT,
                env=env,
                stdout=logs,
                stderr=logs,
            )
            processes.append(portal_process)
            wait_health(source + "/health/", source_process)
            wait_health(base + "/health/", portal_process)
            assert (
                requests.get(
                    source + "/api/v1/income/REV-MH-1001/", timeout=5
                ).status_code
                == 401
            )
            citizen = requests.Session()
            post(
                citizen,
                base,
                "/accounts/register/",
                {
                    "username": "real-http-citizen",
                    "first_name": "Aarav",
                    "last_name": "Patil",
                    "email": "integration@example.org",
                    "password1": password,
                    "password2": password,
                },
            )
            post(citizen, base, "/identity/request/", {"external_id": "REV-MH-1001"})
            item = IdentityRequest.objects.get(
                citizen__user__username="real-http-citizen"
            )
            operator = requests.Session()
            post(
                operator,
                base,
                "/staff/login/",
                {"username": "operator", "password": password},
            )
            post(
                operator,
                base,
                f"/identity/review/{item.pk}/",
                {
                    "decision": "approved",
                    "verification_reference": "TEST-VERIFIED-1",
                    "note": "Fictional test identity verified.",
                },
            )
            response = post(
                citizen,
                base,
                "/applications/new/",
                {
                    "institution": "Integration School",
                    "course": "BTech",
                    "statement": "Real HTTP integration verification using fictional test records.",
                },
            )
            detail = response.headers["Location"]
            pk = int(detail.strip("/").split("/")[-1])
            post(citizen, base, detail + "consent/", {"agree": "on"})
            post(citizen, base, detail + "fetch/", {})
            post(citizen, base, detail + "fetch/", {})
            assert ExchangeJob.objects.filter(application_id=pk).count() == 1
            # Terminate the source to prove failure is retried, not mistaken for verification.
            source_process.terminate()
            source_process.wait(timeout=5)
            command(["manage.py", "run_exchange_worker", "--once"], ROOT, env)
            job = ExchangeJob.objects.get(application_id=pk)
            assert job.status == "queued" and job.attempts == 1
            print("PASS: source outage retained the job and scheduled a retry.")
            source_process = subprocess.Popen(
                [
                    sys.executable,
                    "manage.py",
                    "runserver",
                    f"127.0.0.1:{source_port}",
                    "--noreload",
                ],
                cwd=ROOT / "revenue_service",
                env=env | {"DJANGO_SETTINGS_MODULE": "revenue_config.settings"},
                stdout=logs,
                stderr=logs,
            )
            processes.append(source_process)
            wait_health(source + "/health/", source_process)
            from django.utils import timezone

            ExchangeJob.objects.filter(pk=job.pk).update(run_after=timezone.now())
            worker = subprocess.Popen(
                [sys.executable, "manage.py", "run_exchange_worker"],
                cwd=ROOT,
                env=env,
                stdout=logs,
                stderr=logs,
            )
            processes.append(worker)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                tracker = citizen.get(
                    base + f"/api/v1/applications/{pk}/", timeout=5
                ).json()
                if tracker["status"] == "verified":
                    break
                time.sleep(0.3)
            else:
                raise AssertionError(
                    "Exchange failed to complete after source recovery."
                )
            app = Application.objects.get(pk=pk)
            assert "Aarav" not in app.encrypted_document
            assert app.document_snapshot["annual_income"] == 180000
            assert (
                citizen.get(base + detail + "document/", timeout=5).status_code == 200
            )
            education = requests.Session()
            post(
                education,
                base,
                "/staff/login/",
                {"username": "education", "password": password},
            )
            post(
                education,
                base,
                f"/education/{pk}/decision/",
                {
                    "decision": "approved",
                    "note": "Verified through an independent source API.",
                },
            )
            assert (
                citizen.get(base + f"/api/v1/applications/{pk}/", timeout=5).json()[
                    "status"
                ]
                == "approved"
            )
            post(citizen, base, detail + "revoke/", {})
            assert (
                citizen.get(base + detail + "document/", timeout=5).status_code == 403
            )
            app.refresh_from_db()
            assert app.encrypted_document == "" and app.status == "approved"
            outsider = requests.Session()
            post(
                outsider,
                base,
                "/accounts/register/",
                {
                    "username": "outsider",
                    "first_name": "Other",
                    "last_name": "Citizen",
                    "email": "other@example.org",
                    "password1": password,
                    "password2": password,
                },
            )
            assert outsider.get(base + detail, timeout=5).status_code == 404
            assert citizen.get(base + "/monitor/", timeout=5).status_code == 403
            # Sandbox is a separate owner-scoped workflow, driven by the same real worker.
            from portal.models import SandboxRun

            response = post(
                citizen, base, "/sandbox/", {"mode": "fixture", "consent": "on"}
            )
            sandbox_detail = response.headers["Location"]
            run_id = sandbox_detail.strip("/").split("/")[-1]
            sandbox_deadline = time.monotonic() + 15
            while time.monotonic() < sandbox_deadline:
                state = citizen.get(base + sandbox_detail + "status/", timeout=5).json()
                if state["status"] == "received":
                    break
                time.sleep(0.3)
            else:
                raise AssertionError("Local sandbox fixture did not complete.")
            run = SandboxRun.objects.get(pk=run_id)
            assert "Fictional Test Citizen" not in run.encrypted_response
            page = citizen.get(base + sandbox_detail, timeout=5)
            assert (
                "Local classroom fixture" in page.text
                and "Fictional Test Citizen" in page.text
            )
            assert page.headers["Cache-Control"] == "private, no-store"
            assert outsider.get(base + sandbox_detail, timeout=5).status_code == 404
            assert (
                outsider.get(base + sandbox_detail + "status/", timeout=5).status_code
                == 404
            )
            post(citizen, base, sandbox_detail + "revoke/", {})
            run.refresh_from_db()
            assert run.status == "cancelled" and run.encrypted_response == ""
            app.refresh_from_db()
            assert app.status == "approved" and Application.objects.count() == 1
            print(
                "PASS: sandbox fixture via real HTTP/worker, encrypted sample response, owner isolation, revocation and scholarship separation."
            )
            # Source writes only its own disclosure receipt table, not a gateway table.
            result = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "shell",
                    "-c",
                    "from registry.models import Disclosure; print(Disclosure.objects.count())",
                ],
                cwd=ROOT / "revenue_service",
                env=env | {"DJANGO_SETTINGS_MODULE": "revenue_config.settings"},
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip().splitlines()[-1] == "1"
            print(
                "PASS: registration → reviewed identity → consent → HTTP exchange → retry/recovery → encrypted storage → officer decision → tracker → revocation."
            )
            print(
                "PASS: duplicate requests, independent disclosure receipt, ownership and role isolation."
            )
        except Exception:
            logs.flush()
            logs.seek(0)
            print(logs.read()[-12000:], file=sys.stderr)
            raise
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            logs.close()


if __name__ == "__main__":
    main()
