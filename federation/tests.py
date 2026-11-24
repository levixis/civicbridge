import json,secrets,time
from unittest import skipUnless
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from common.demo import demo_subject
from common.tokens import encode,jwk
from .models import FederatedIdentity

class RelyingPartyTests(TestCase):
    def attempt(self):
        session=self.client.session
        session['oidc']={'state':'s'*32,'nonce':'n'*32,'verifier':'v'*48,'at':time.time()}
        session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    def token(self,subject='subject-test',**override):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        now=int(time.time())
        claims={'iss':settings.SSO_ISSUER,'aud':settings.SSO_CLIENT_ID,'nonce':'n'*32,'sub':subject,'name':'Untrusted profile','iat':now,'exp':now+120}|override
        return encode(claims,key),{'keys':[jwk(key.public_key())]}
    def callback(self,token,keys,state='s'*32):
        with patch('federation.views.bounded_request',return_value=(json.dumps({'id_token':token}).encode(),'application/json')),patch('federation.views.get_json',return_value=keys):
            return self.client.get('/sso/callback/',{'state':state,'code':'sample-code'})
    def test_state_mismatch_blocks_network(self):
        for state in ['wrong', 'é']:
            with self.subTest(state=state):
                self.attempt()
                with patch('federation.views.bounded_request') as transport:
                    self.assertEqual(self.client.get('/sso/callback/', {'state': state}).status_code, 400)
                    transport.assert_not_called()
    def test_provisioned_subject_only_not_name(self):
        user=User.objects.create_user('trusted-account',is_staff=True)
        FederatedIdentity.objects.create(issuer=settings.SSO_ISSUER,subject='subject-test',user=user)
        self.attempt();token,keys=self.token(name='someone-else')
        self.assertEqual(self.callback(token,keys).status_code,302)
        self.assertEqual(int(self.client.session['_auth_user_id']),user.pk)
    def test_invalid_audience_cannot_log_in(self):
        self.attempt();token,keys=self.token(aud='attacker')
        self.assertEqual(self.callback(token,keys).status_code,400)
        self.assertNotIn('_auth_user_id',self.client.session)
    def test_shared_sign_in_returns_to_local_page_and_rejects_external_redirects(self):
        user = User.objects.create_user('shared-account')
        FederatedIdentity.objects.create(issuer=settings.SSO_ISSUER, subject='subject-test', user=user)
        for target, expected in [('/services/new/1/', '/services/new/1/'),
                                 ('//external.example/path', settings.SSO_HOME),
                                 ('/\\external.example/path', settings.SSO_HOME)]:
            with self.subTest(target=target):
                self.client.get('/sso/login/', {'next': target})
                attempt = self.client.session['oidc']
                token, keys = self.token(nonce=attempt['nonce'])
                response = self.callback(token, keys, state=attempt['state'])
                self.assertRedirects(response, expected, fetch_redirect_response=False)
    def test_unbound_identity_does_not_take_existing_staff_account(self):
        user=User.objects.create_user('Untrusted profile',is_staff=True)
        self.attempt();token,keys=self.token()
        response=self.callback(token,keys)
        if settings.SSO_AUTO_PROVISION:
            self.assertEqual(response.status_code,302)
            fresh=User.objects.get(pk=int(self.client.session['_auth_user_id']))
            self.assertNotEqual(fresh.pk,user.pk);self.assertFalse(fresh.is_staff)
            self.assertFalse(fresh.groups.exists())
        else:
            self.assertEqual(response.status_code,400)
            self.assertNotIn('_auth_user_id',self.client.session)

    @override_settings(SSO_DEPARTMENT_ROUTES={
        str(demo_subject('revenue')): 'http://127.0.0.1:8001/sso/login/',
        str(demo_subject('municipality')): 'http://127.0.0.1:8002/sso/login/',
    })
    def test_departmental_identity_uses_its_registry_without_a_citizen_account(self):
        for department, port in [('revenue', 8001), ('municipality', 8002)]:
            with self.subTest(department=department):
                self.attempt()
                token, keys = self.token(subject=str(demo_subject(department)), name=department)
                count = User.objects.count()
                response = self.callback(token, keys)
                self.assertRedirects(response, f'http://127.0.0.1:{port}/sso/login/', fetch_redirect_response=False)
                self.assertEqual(User.objects.count(), count)
                self.assertNotIn('_auth_user_id', self.client.session)

    def test_department_name_does_not_determine_a_new_identity_destination(self):
        self.attempt()
        token, keys = self.token(subject='unrecognised-subject', name='revenue')
        response = self.callback(token, keys)
        if settings.SSO_AUTO_PROVISION:
            self.assertRedirects(response, settings.SSO_HOME, fetch_redirect_response=False)
            user = User.objects.get(pk=self.client.session['_auth_user_id'])
            self.assertFalse(user.is_staff)
        else:
            self.assertEqual(response.status_code, 400)

    @skipUnless(settings.SSO_CLIENT_ID == 'portal', 'Portal staff entry point')
    def test_staff_sign_in_requires_the_selected_department_role(self):
        from django.contrib.auth.models import Group
        user = User.objects.create_user('department-reviewer')
        user.groups.add(Group.objects.create(name='Education Officers'))
        FederatedIdentity.objects.create(issuer=settings.SSO_ISSUER, subject='education-test', user=user)
        for department, subject, expected in [
            ('education', 'education-test', '/staff/'),
            ('welfare', 'education-test', '/staff/login/'),
            ('education', 'unknown-citizen', '/staff/login/'),
        ]:
            with self.subTest(department=department, subject=subject):
                response = self.client.get('/staff/sign-in/' + department + '/')
                self.assertIn('prompt=login', response['Location'])
                attempt = self.client.session['oidc']
                token, keys = self.token(subject=subject, nonce=attempt['nonce'])
                before = User.objects.count()
                self.assertRedirects(self.callback(token, keys, state=attempt['state']), expected, fetch_redirect_response=False)
                self.assertEqual(User.objects.count(), before)
