"""Run the four Django services behind one HTTPS address for a classroom demo."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from common.http import origin


ROOT = Path(__file__).resolve().parents[1]
WEB_SERVICES = (
    (ROOT, 8000, "config.wsgi:application", ("seed_demo", "seed_platform")),
    (ROOT / "revenue_service", 8001, "revenue_config.wsgi:application", ("seed_revenue",)),
    (ROOT / "municipal_service", 8002, "municipal_config.wsgi:application", ("seed_municipal",)),
    (ROOT / "identity_service", 8003, "identity_config.wsgi:application", ("seed_identity",)),
)


def main():
    public_url = origin(os.environ.get("CIVICBRIDGE_PUBLIC_URL") or os.environ["RENDER_EXTERNAL_URL"])
    host = urlsplit(public_url).hostname
    port = int(os.environ.get("PORT", "10000"))
    if not 1024 <= port <= 65535 or port in range(8000, 8004):
        raise SystemExit("Choose a PORT above 1023 and outside 8000–8003.")

    env = os.environ | {
        "DJANGO_DEBUG": "0",
        "TRUST_PROXY": "1",
        "ALLOW_LOCAL_HTTP": "1",
        "SANDBOX_ENABLED": "0",
        "EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend",
        "DJANGO_ALLOWED_HOSTS": f"{host},127.0.0.1",
        "REVENUE_ALLOWED_HOSTS": f"{host},127.0.0.1",
        "MUNICIPAL_ALLOWED_HOSTS": f"{host},127.0.0.1",
        "IDENTITY_ALLOWED_HOSTS": f"{host},127.0.0.1",
        "REVENUE_API_URL": "http://127.0.0.1:8001",
        "MUNICIPAL_API_URL": "http://127.0.0.1:8002",
        "SSO_ISSUER": f"{public_url}/identity",
        "SSO_BACKCHANNEL_URL": "http://127.0.0.1:8003",
        "SSO_PORTAL_REDIRECT": f"{public_url}/sso/callback/",
        "SSO_REVENUE_REDIRECT": f"{public_url}/revenue/sso/callback/",
        "SSO_MUNICIPALITY_REDIRECT": f"{public_url}/municipality/sso/callback/",
    }
    env.pop("DJANGO_SETTINGS_MODULE", None)
    for role in ("CITIZEN", "EDUCATION", "WELFARE", "OPERATOR", "REVENUE", "MUNICIPALITY"):
        if len(env.get(f"DEMO_{role}_PASSWORD", "")) < 16:
            raise SystemExit(f"Set DEMO_{role}_PASSWORD to a unique password of at least 16 characters.")

    subprocess.run([sys.executable, "scripts/init_env.py"], cwd=ROOT, env=env, check=True)
    seed_env = env | {"DJANGO_DEBUG": "1"}
    for directory, _, _, commands in WEB_SERVICES:
        label = "portal" if directory == ROOT else directory.name
        print(f"Preparing the {label} database and fictional demo records.", flush=True)
        initialization = "\n".join([
            "from django.core.management import call_command",
            "call_command('migrate', interactive=False, verbosity=0)",
            *(f"call_command({command!r})" for command in commands),
        ])
        subprocess.run(
            [sys.executable, "manage.py", "shell", "--command", initialization],
            cwd=directory, env=seed_env, check=True, stdout=subprocess.DEVNULL,
        )

    nginx_config = ROOT / "deploy/nginx.conf"
    runtime_config = Path("/tmp/civicbridge-nginx.conf")
    runtime_config.write_text(nginx_config.read_text().replace("PUBLIC_PORT", str(port)))

    processes = []
    try:
        for directory, local_port, application, _ in WEB_SERVICES:
            processes.append(subprocess.Popen(
                [sys.executable, "-m", "gunicorn", application, "--workers", "1", "--bind",
                 f"127.0.0.1:{local_port}", "--forwarded-allow-ips", "127.0.0.1", "--no-control-socket"],
                cwd=directory, env=env,
            ))
        processes.append(subprocess.Popen([sys.executable, "manage.py", "run_exchange_worker"], cwd=ROOT, env=env))
        processes.append(subprocess.Popen(["nginx", "-c", str(runtime_config), "-g", "daemon off;"]))
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise SystemExit("A CivicBridge service stopped. Review its output.")
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


def stop(signum, frame):
    raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop)
    main()
