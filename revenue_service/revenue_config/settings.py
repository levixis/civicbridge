import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")
SECRET_KEY = os.environ["REVENUE_DJANGO_SECRET_KEY"]
REVENUE_API_TOKEN = os.environ["REVENUE_API_TOKEN"]
GRANT_SIGNING_KEY = os.environ["GRANT_SIGNING_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get(
    "REVENUE_ALLOWED_HOSTS", "localhost,127.0.0.1,revenue"
).split(",")
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "registry", "source_bridge", "federation",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "registry.throttle.ThrottleMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "revenue_config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get(
            "REVENUE_SQLITE_PATH", str(BASE_DIR / "revenue.sqlite3")
        ),
    }
}
if os.environ.get("REVENUE_POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["REVENUE_POSTGRES_HOST"],
            "PORT": os.environ.get("REVENUE_POSTGRES_PORT", "5432"),
            "NAME": os.environ.get("REVENUE_POSTGRES_DB", "revenue"),
            "USER": os.environ["REVENUE_POSTGRES_USER"],
            "PASSWORD": os.environ["REVENUE_POSTGRES_PASSWORD"],
            "CONN_MAX_AGE": 60,
        }
    }
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR.parent / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_TZ = True
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "registry"
LOGOUT_REDIRECT_URL = "login"
WSGI_APPLICATION = "revenue_config.wsgi.application"
SESSION_COOKIE_NAME = "revenue_sessionid"
CSRF_COOKIE_NAME = "revenue_csrftoken"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 3600
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
# Source API lives on a trusted internal network; portal->source HTTPS is required for remote deployments.
SECURE_REDIRECT_EXEMPT = (
    [r"^health/$", r"^api/v1/"]
    if os.environ.get("ALLOW_LOCAL_HTTP", "0") == "1"
    else []
)
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
CSRF_TRUSTED_ORIGINS = [
    x for x in os.environ.get("REVENUE_CSRF_TRUSTED_ORIGINS", "").split(",") if x
]
if os.environ.get("TRUST_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
DATA_UPLOAD_MAX_MEMORY_SIZE = 1048576

SOURCE_API_TOKEN = REVENUE_API_TOKEN
SOURCE_NAME = "Revenue"
SSO_CLIENT_ID = "revenue"
SSO_AUTO_PROVISION = False
from common.sso_settings import configure
configure(globals(), BASE_DIR.parent, "revenue", 8001)
