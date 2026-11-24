import hashlib
import json
import secrets
import time
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.views import LogoutView
from django.db import transaction, IntegrityError
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET
from common.http import origin, bounded_request, get_json, TransportError
from common.tokens import b64, validate
from .models import FederatedIdentity


class SharedSignOutView(LogoutView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        request.session['shared_sign_in_required'] = True
        return response


@require_GET
def start(request, expected_role=None):
    issuer=origin(settings.SSO_ISSUER, settings.ALLOW_LOCAL_HTTP)
    state,nonce,verifier=secrets.token_urlsafe(32),secrets.token_urlsafe(32),secrets.token_urlsafe(48)
    next_url = request.GET.get('next', '')
    if not (next_url.startswith('/') and not next_url.startswith('//') and
            url_has_allowed_host_and_scheme(next_url, allowed_hosts=set())):
        next_url = ''
    request.session['oidc']={'state':state,'nonce':nonce,'verifier':verifier,'at':time.time(),'next':next_url,'role':expected_role}
    params = {'client_id':settings.SSO_CLIENT_ID,
        'redirect_uri':settings.SSO_REDIRECT_URI,'response_type':'code','scope':'openid',
        'state':state,'nonce':nonce,'code_challenge':b64(hashlib.sha256(verifier.encode()).digest()),'code_challenge_method':'S256'}
    if expected_role or request.GET.get('prompt') == 'login' or request.session.get('shared_sign_in_required'):
        params['prompt'] = 'login'
    return redirect(issuer + '/authorize/?' + urlencode(params))

@require_GET
def callback(request):
    attempt=request.session.pop('oidc', None)
    state=request.GET.get('state','')
    if not attempt or not state or not constant_time_compare(state,attempt['state']) or time.time()-attempt['at']>300:
        return HttpResponseBadRequest('Sign-in state expired or did not match. Start sign-in again.')
    try:
        issuer=origin(settings.SSO_ISSUER, settings.ALLOW_LOCAL_HTTP)
        backchannel=origin(settings.SSO_BACKCHANNEL_URL, settings.ALLOW_LOCAL_HTTP)
        body,kind=bounded_request('POST',backchannel+'/token/', auth=(settings.SSO_CLIENT_ID,settings.SSO_CLIENT_SECRET),
            data={'grant_type':'authorization_code','code':request.GET.get('code',''),'redirect_uri':settings.SSO_REDIRECT_URI,'code_verifier':attempt['verifier']})
        if kind!='application/json': raise ValueError()
        token=json.loads(body)['id_token']
        # JWKS is retrieved only from the configured issuer, never a token-supplied URL.
        keys=get_json(backchannel+'/jwks/')
        claims=validate(token, keys, issuer, settings.SSO_CLIENT_ID, attempt['nonce'])
        expected_role = attempt.get('role')
        if expected_role and not FederatedIdentity.objects.filter(
            issuer=issuer, subject=claims['sub'], user__is_active=True, user__groups__name=expected_role,
        ).exists():
            messages.error(request, 'This account does not have access to the selected department. Choose your department and use its staff account.')
            return redirect('staff_login')
        destination = getattr(settings, 'SSO_DEPARTMENT_ROUTES', {}).get(claims['sub'])
        if destination:
            logout(request)
            return redirect(destination)
        with transaction.atomic():
            identity=FederatedIdentity.objects.select_related('user').filter(issuer=issuer,subject=claims['sub']).first()
            if identity:
                user=identity.user
            elif settings.SSO_AUTO_PROVISION:
                # Never match usernames/emails and never take staff roles from token claims.
                user=User.objects.create(username='sso_'+secrets.token_hex(12),first_name=str(claims.get('name','Citizen'))[:150])
                user.set_unusable_password()
                user.save()
                FederatedIdentity.objects.create(issuer=issuer,subject=claims['sub'],user=user)
                from portal.models import Citizen
                Citizen.objects.create(user=user)
            else:
                return HttpResponseBadRequest('This identity is not provisioned for this department.')
            if not user.is_active:
                return HttpResponseBadRequest('This local account is disabled.')
        login(request,user,backend='django.contrib.auth.backends.ModelBackend')
        request.session.pop('shared_sign_in_required', None)
        return redirect('staff_workspace' if expected_role else (attempt.get('next') or settings.SSO_HOME))
    except (TransportError, ValueError, KeyError, TypeError, IntegrityError):
        return HttpResponseBadRequest('Shared sign-in failed validation or the identity provider is unavailable.')
    except Exception:
        # Cryptographic verification errors never expose token contents.
        return HttpResponseBadRequest('Shared sign-in failed token verification.')
