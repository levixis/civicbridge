import base64
import hashlib
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render,redirect
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from common.authentication import EmailOrUsernameAuthenticationForm
from common.tokens import b64, jwk, encode
from common.http import identity_issuer
from .forms import IdentityRegistrationForm
from .models import Subject,AuthorizationCode

def private_key():
    return serialization.load_pem_private_key(settings.IDENTITY_PRIVATE_KEY_PATH.read_bytes(),password=None)

@require_GET
def health(request):
    Subject.objects.exists()
    private_key()
    return JsonResponse({'status':'ok','service':'identity'})

@require_GET
def jwks(request):
    response=JsonResponse({'keys':[jwk(private_key().public_key())]})
    response['Cache-Control']='public, max-age=60'
    return response

@require_GET
def discovery(request):
    base=identity_issuer(settings.SSO_ISSUER,settings.ALLOW_LOCAL_HTTP)
    return JsonResponse({'issuer':base,'authorization_endpoint':base+'/authorize/','token_endpoint':base+'/token/',
        'jwks_uri':base+'/jwks/','response_types_supported':['code'],'grant_types_supported':['authorization_code'],
        'subject_types_supported':['public'],'id_token_signing_alg_values_supported':['RS256'],
        'scopes_supported':['openid'],'token_endpoint_auth_methods_supported':['client_secret_basic'],
        'code_challenge_methods_supported':['S256']})

@require_http_methods(['GET', 'POST'])
@never_cache
def authorize(request):
    params=request.GET
    client=settings.SSO_CLIENTS.get(params.get('client_id'))
    if not client or params.get('redirect_uri')!=client['redirect']:
        return HttpResponseBadRequest('Unknown client or unregistered redirect URI.')
    if (params.get('response_type')!='code' or params.get('scope')!='openid' or params.get('code_challenge_method')!='S256'
        or not re.fullmatch(r'[A-Za-z0-9_-]{43}',params.get('code_challenge',''))
        or not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',params.get('state',''))
        or not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',params.get('nonce',''))):
        return HttpResponseBadRequest('Invalid authorization parameters.')
    if params.get('prompt') == 'login':
        form = EmailOrUsernameAuthenticationForm(request, data=request.POST if request.method == 'POST' else None)
        if request.method == 'GET' or not form.is_valid():
            return render(request, 'idp_login.html', {'form': form, 'switching': True})
        login(request, form.get_user())
    elif request.method == 'POST':
        return HttpResponseBadRequest('A sign-in prompt is required to submit credentials here.')
    elif not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    subject,_=Subject.objects.get_or_create(user=request.user)
    code=secrets.token_urlsafe(40)
    AuthorizationCode.objects.create(digest=hashlib.sha256(code.encode()).hexdigest(),subject=subject,
        client=params['client_id'],redirect=client['redirect'],nonce=params['nonce'],challenge=params['code_challenge'],expires_at=timezone.now()+timedelta(seconds=60))
    response=redirect(client['redirect']+'?'+urlencode({'code':code,'state':params['state']}))
    response['Cache-Control']='no-store'
    response['Referrer-Policy']='no-referrer'
    return response

@csrf_exempt  # Client-secret authentication, not an authenticated browser endpoint.
@require_POST
def token(request):
    def error(status=400):
        response=JsonResponse({'error':'invalid_grant' if status==400 else 'invalid_client'},status=status)
        response['Cache-Control']='no-store'
        return response
    try:
        header=request.headers.get('Authorization','')
        if not header.startswith('Basic ') or len(header)>1000: return error(401)
        client_id,secret=base64.b64decode(header[6:],validate=True).decode().split(':',1)
        client=settings.SSO_CLIENTS.get(client_id)
        if not client or not constant_time_compare(client['secret'],secret): return error(401)
        verifier=request.POST.get('code_verifier','')
        if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}',verifier) or request.POST.get('grant_type')!='authorization_code': return error()
        raw_code=request.POST.get('code','')
        if not 20<=len(raw_code)<=100: return error()
        with transaction.atomic():
            code=AuthorizationCode.objects.select_for_update().select_related('subject__user').filter(pk=hashlib.sha256(raw_code.encode()).hexdigest()).first()
            if (not code or code.redeemed_at or code.expires_at<=timezone.now() or code.client!=client_id or code.redirect!=request.POST.get('redirect_uri')
                or not code.subject.user.is_active or not constant_time_compare(code.challenge,b64(hashlib.sha256(verifier.encode()).digest()))):
                return error()
            # Compare-and-swap also prevents duplicate redemption on local SQLite.
            if not AuthorizationCode.objects.filter(pk=code.pk,redeemed_at=None).update(redeemed_at=timezone.now()): return error()
            now=int(time.time())
            identity_token=encode({'iss':settings.SSO_ISSUER.rstrip('/'),'sub':str(code.subject.identifier),'aud':client_id,
                'iat':now,'exp':now+120,'nonce':code.nonce,'name':code.subject.user.get_full_name() or code.subject.user.username},private_key())
        response=JsonResponse({'id_token':identity_token,'token_type':'Bearer','expires_in':120,
            'access_token':secrets.token_urlsafe(32),'scope':'openid'})
        response['Cache-Control']='no-store'
        response['Pragma']='no-cache'
        return response
    except (ValueError, UnicodeError):
        return error()

def home(request): return render(request,'idp_home.html')

def register(request):
    form = IdentityRegistrationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            # Check after inserting so concurrent SQLite sign-ups serialize before checking.
            other_users = type(user).objects.exclude(pk=user.pk)
            if user.email and other_users.filter(Q(email__iexact=user.email) | Q(username__iexact=user.email)).exists():
                form.add_error('email', 'An identity already uses this email address.')
            if '@' in user.username and other_users.filter(email__iexact=user.username).exists():
                form.add_error('username', 'Choose a username that is different from an existing sign-in email.')
            if form.errors:
                transaction.set_rollback(True)
            else:
                Subject.objects.create(user=user)
        if not form.errors:
            login(request, user)
            return redirect('home')
    return render(request, 'idp_register.html', {'form': form})
