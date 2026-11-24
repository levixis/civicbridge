import argparse, subprocess, sys, time, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = os.environ.copy()
ENV.pop("DJANGO_SETTINGS_MODULE", None)
ENV.update({
    'DJANGO_DEBUG':'1', 'ALLOW_LOCAL_HTTP':'1',
    'POSTGRES_HOST':'', 'REVENUE_POSTGRES_HOST':'', 'MUNICIPAL_POSTGRES_HOST':'',
    'SQLITE_PATH':str(ROOT/'db.sqlite3'),
    'REVENUE_SQLITE_PATH':str(ROOT/'revenue_service/revenue.sqlite3'),
    'MUNICIPAL_SQLITE_PATH':str(ROOT/'municipal_service/municipal.sqlite3'),
    'IDENTITY_SQLITE_PATH':str(ROOT/'identity_service/identity.sqlite3'),
    'REVENUE_API_URL':'http://127.0.0.1:8001', 'MUNICIPAL_API_URL':'http://127.0.0.1:8002',
    'SSO_ISSUER':'http://127.0.0.1:8003', 'SSO_BACKCHANNEL_URL':'http://127.0.0.1:8003',
    'SSO_PORTAL_REDIRECT':'http://127.0.0.1:8000/sso/callback/',
    'SSO_REVENUE_REDIRECT':'http://127.0.0.1:8001/sso/callback/',
    'SSO_MUNICIPALITY_REDIRECT':'http://127.0.0.1:8002/sso/callback/',
    'IDENTITY_PRIVATE_KEY_PATH':str(ROOT/'private/identity.pem'),
})
parser = argparse.ArgumentParser()
parser.add_argument("--seed", action="store_true")
args = parser.parse_args()


def run(*command, cwd=ROOT):
    subprocess.run([sys.executable, *command], cwd=cwd, env=ENV, check=True)


run("scripts/init_env.py")
run("manage.py", "migrate")
run("manage.py", "migrate", cwd=ROOT / "revenue_service")
run("manage.py", "migrate", cwd=ROOT / "municipal_service")
run("manage.py", "migrate", cwd=ROOT / "identity_service")
if args.seed:
    run("manage.py", "seed_demo")
    run("manage.py", "seed_revenue", cwd=ROOT / "revenue_service")
    run("manage.py", "seed_municipal", cwd=ROOT / "municipal_service")
    run("manage.py", "seed_identity", cwd=ROOT / "identity_service")
    run("manage.py", "seed_platform")
processes = []
try:
    for folder, port in [("municipal_service", 8002), ("identity_service", 8003)]:
        processes.append(subprocess.Popen([sys.executable,"manage.py","runserver",f"127.0.0.1:{port}","--noreload"],cwd=ROOT/folder,env=ENV))
    processes.append(
        subprocess.Popen(
            [sys.executable, "manage.py", "runserver", "127.0.0.1:8001", "--noreload"],
            cwd=ROOT / "revenue_service", env=ENV,
        )
    )
    processes.append(
        subprocess.Popen(
            [sys.executable, "manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
            cwd=ROOT, env=ENV,
        )
    )
    processes.append(
        subprocess.Popen([sys.executable, "manage.py", "run_exchange_worker"], cwd=ROOT, env=ENV)
    )
    print(
        "CivicBridge: http://127.0.0.1:8000/ | Revenue: http://127.0.0.1:8001/ | Municipality: http://127.0.0.1:8002/ | Identity: http://127.0.0.1:8003/ | Ctrl+C stops all five processes.",
        flush=True,
    )
    while all(p.poll() is None for p in processes):
        time.sleep(1)
    raise SystemExit("A service exited. Check its output above.")
except KeyboardInterrupt:
    print("Stopping local services.")
finally:
    for p in processes:
        if p.poll() is None:
            p.terminate()
    for p in processes:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
