import os
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR=Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent/'.env')
SECRET_KEY=os.environ['IDENTITY_DJANGO_SECRET_KEY']
DEBUG=os.environ.get('DJANGO_DEBUG','1')=='1'
ALLOW_LOCAL_HTTP=os.environ.get('ALLOW_LOCAL_HTTP','0')=='1'
ALLOWED_HOSTS=os.environ.get('IDENTITY_ALLOWED_HOSTS','localhost,127.0.0.1').split(',')
INSTALLED_APPS=['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','identity']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','identity.throttle.ThrottleMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF='identity_config.urls'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'], 'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('IDENTITY_SQLITE_PATH',str(BASE_DIR/'identity.sqlite3'))}}
AUTH_PASSWORD_VALIDATORS=[{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
STATIC_URL='static/'
STATIC_ROOT=BASE_DIR/'staticfiles'
STATICFILES_DIRS=[BASE_DIR.parent/'static']
STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
LANGUAGE_CODE='en-in'
TIME_ZONE='Asia/Kolkata'
USE_TZ=True
LOGIN_URL='login'
LOGIN_REDIRECT_URL='home'
LOGOUT_REDIRECT_URL='home'
SESSION_COOKIE_NAME='identity_sessionid'
CSRF_COOKIE_NAME='identity_csrftoken'
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE='Lax'
SESSION_COOKIE_AGE=3600
SESSION_COOKIE_SECURE=not DEBUG
CSRF_COOKIE_SECURE=not DEBUG
SECURE_SSL_REDIRECT=not DEBUG
SECURE_HSTS_SECONDS=31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS=not DEBUG
SECURE_HSTS_PRELOAD=not DEBUG
SECURE_REDIRECT_EXEMPT=[r'^health/$']
if ALLOW_LOCAL_HTTP:
    SECURE_REDIRECT_EXEMPT += [r'^token/$', r'^jwks/$']
if os.environ.get('TRUST_PROXY') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
DATA_UPLOAD_MAX_MEMORY_SIZE=32768
WSGI_APPLICATION='identity_config.wsgi.application'
SSO_ISSUER=os.environ.get('SSO_ISSUER','http://127.0.0.1:8003')
IDENTITY_PRIVATE_KEY_PATH=Path(os.environ.get('IDENTITY_PRIVATE_KEY_PATH',str(BASE_DIR.parent/'private/identity.pem')))
SSO_CLIENTS={c:{'secret':os.environ['SSO_'+c.upper()+'_SECRET'],'redirect':os.environ.get('SSO_'+c.upper()+'_REDIRECT',f'http://127.0.0.1:{p}/sso/callback/')} for c,p in [('portal',8000),('revenue',8001),('municipality',8002)]}
