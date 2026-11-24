import base64,hashlib,json,secrets,time
from urllib.parse import urlparse,parse_qs
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase,Client
from common.tokens import b64,jwk,encode,validate
from .models import AuthorizationCode, LoginAttempt
class IdentityTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('identity-user', email='identity-user@civicbridge.test', password='Example-password-567!')
        self.client.force_login(self.user)
        self.verifier=secrets.token_urlsafe(48)
        self.params={'client_id':'portal','redirect_uri':settings.SSO_CLIENTS['portal']['redirect'],'response_type':'code','scope':'openid','state':secrets.token_urlsafe(32),'nonce':secrets.token_urlsafe(32),'code_challenge':b64(hashlib.sha256(self.verifier.encode()).digest()),'code_challenge_method':'S256'}
    def code(self):
        response=self.client.get('/authorize/',self.params)
        self.assertEqual(response.status_code,302)
        return parse_qs(urlparse(response['Location']).query)['code'][0]
    def redeem(self,code,**overrides):
        values={'grant_type':'authorization_code','code':code,'redirect_uri':self.params['redirect_uri'],'code_verifier':self.verifier}|overrides
        header=base64.b64encode(('portal:'+settings.SSO_CLIENTS['portal']['secret']).encode()).decode()
        return self.client.post('/token/',values,HTTP_AUTHORIZATION='Basic '+header)
    def test_authorization_code_pkce_and_signed_identity(self):
        response=self.redeem(self.code());self.assertEqual(response.status_code,200)
        claims=validate(response.json()['id_token'],self.client.get('/jwks/').json(),settings.SSO_ISSUER,'portal',self.params['nonce'])
        self.assertEqual(claims['aud'],'portal')
        self.assertNotIn('staff',claims)
    def test_code_cannot_be_redeemed_twice(self):
        code=self.code();self.assertEqual(self.redeem(code).status_code,200)
        self.assertEqual(self.redeem(code).status_code,400)
    def test_wrong_pkce_redirect_and_client_secret(self):
        code=self.code()
        self.assertEqual(self.redeem(code,code_verifier='x'*48).status_code,400)
        self.assertEqual(self.redeem(code,redirect_uri='http://attacker.test/').status_code,400)
        self.assertEqual(self.client.post('/token/',{}).status_code,401)
        header = base64.b64encode('portal:é'.encode()).decode()
        self.assertEqual(self.client.post('/token/', HTTP_AUTHORIZATION='Basic '+header).status_code, 401)
    def test_unregistered_redirect_and_plain_pkce_rejected(self):
        self.assertEqual(self.client.get('/authorize/',self.params|{'redirect_uri':'http://attacker.test/'}).status_code,400)
        self.assertEqual(self.client.get('/authorize/',self.params|{'code_challenge_method':'plain'}).status_code,400)
    def test_sign_in_prompt_requires_credentials_and_protects_post_with_csrf(self):
        from urllib.parse import urlencode

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        path = '/authorize/?' + urlencode(self.params | {'prompt': 'login'})
        response = client.get(path)
        self.assertContains(response, 'Email or username')
        self.assertFalse(AuthorizationCode.objects.exists())
        creds = {'username': self.user.username, 'password': 'wrong-password'}
        self.assertEqual(client.post(path, creds).status_code, 403)
        csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(client.post(path, creds, HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        self.assertFalse(AuthorizationCode.objects.exists())
        creds = {'username': self.user.email.upper(), 'password': 'Example-password-567!'}
        response = client.post(path, creds, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AuthorizationCode.objects.get().subject.user, self.user)
    def test_username_and_email_share_the_same_attempt_limit(self):
        client = Client()
        for identifier in (self.user.username, self.user.email.upper()):
            response = client.post('/accounts/login/', {'username': identifier, 'password': 'wrong-password'})
            self.assertContains(response, 'Enter a valid email or username and password.')
        self.assertEqual(LoginAttempt.objects.get().failures, 2)

    def test_signup_email_can_sign_in_and_cannot_be_reused(self):
        password = 'Example-signup-password-45!'
        info = {'username': 'new-person', 'email': 'new-person@civicbridge.test', 'password1': password, 'password2': password}
        self.assertRedirects(Client().post('/accounts/register/', info), '/')
        client = Client()
        self.assertRedirects(client.post('/accounts/login/', {'username': info['email'].upper(), 'password': password}), '/')
        self.assertEqual(int(client.session['_auth_user_id']), User.objects.get(username=info['username']).pk)
        duplicate = Client().post('/accounts/register/', info | {'username': 'different-person', 'email': info['email'].upper()})
        self.assertContains(duplicate, 'An identity already uses this email address.')
        self.assertFalse(User.objects.filter(username='different-person').exists())
    def test_expired_code_and_disabled_identity_rejected(self):
        code=self.code()
        from datetime import timedelta
        from django.utils import timezone
        AuthorizationCode.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.redeem(code).status_code,400)
        code=self.code();self.user.is_active=False;self.user.save()
        self.assertEqual(self.redeem(code).status_code,400)
    def test_token_audience_nonce_expiry_and_signature_checks(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048);keys={'keys':[jwk(key.public_key())]}
        now=int(time.time());claims={'iss':settings.SSO_ISSUER,'aud':'portal','sub':'test','nonce':'correct','iat':now,'exp':now+120}
        for altered in [claims|{'aud':'revenue'},claims|{'nonce':'wrong'},claims|{'exp':now-1},claims|{'iss':'http://attacker.test'}]:
            with self.assertRaises(ValueError):validate(encode(altered,key),keys,settings.SSO_ISSUER,'portal','correct')
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(ValueError):validate(encode(claims,other),keys,settings.SSO_ISSUER,'portal','correct')
    def test_discovery_and_csrf_protected_signup(self):
        self.assertEqual(self.client.get('/.well-known/openid-configuration').json()['code_challenge_methods_supported'],['S256'])
        csrf=Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post('/accounts/register/',{'username':'new'}).status_code,403)
