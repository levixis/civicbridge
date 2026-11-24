import uuid
from datetime import timedelta
from django.conf import settings
from django.core import signing
from django.test import TestCase
from django.utils import timezone
from .models import ResidentRecord,Disclosure
class MunicipalTests(TestCase):
    def setUp(self):
        ResidentRecord.objects.create(person_key='MUN-TEST',record_no='RES-TEST',full_name='Fictional Test Citizen',district='Pune',ward='12',members=4,issued=timezone.localdate(),expires=timezone.localdate()+timedelta(days=30),confirmed=True)
    def headers(self,scope='residence_certificate',**overrides):
        grant={'resident':'MUN-TEST','application':str(uuid.uuid4()),'revision':str(uuid.uuid4()),'scope':scope,'audience':'municipality','purpose':'Housing assistance','expires':(timezone.now()+timedelta(hours=1)).isoformat()}|overrides
        return {'HTTP_AUTHORIZATION':'Bearer '+settings.MUNICIPAL_API_TOKEN,'HTTP_X_CONSENT_GRANT':signing.dumps(grant,key=settings.GRANT_SIGNING_KEY,salt='civicbridge.exchange.v1'),'HTTP_X_REQUEST_ID':str(uuid.uuid4())}
    def test_json_and_legacy_csv_records(self):
        response=self.client.get('/api/v1/residence/MUN-TEST/',**self.headers())
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['person_key'],'MUN-TEST')
        response=self.client.get('/api/v1/legacy/household/MUN-TEST/',**self.headers('household_certificate'))
        self.assertEqual(response.status_code,200);self.assertIn(b'MEMBERS',response.content)
        self.assertEqual(Disclosure.objects.count(),2)
    def test_authentication_and_scope_enforced(self):
        self.assertEqual(self.client.get('/api/v1/residence/MUN-TEST/').status_code,401)
        response = self.client.get('/api/v1/residence/MUN-TEST/', HTTP_AUTHORIZATION='Bearer é')
        self.assertEqual(response.status_code, 401)
        for overrides in [{'audience':'revenue'},{'scope':'household_certificate'},{'resident':'OTHER'},{'expires':(timezone.now()-timedelta(minutes=1)).isoformat()}]:
            self.assertEqual(self.client.get('/api/v1/residence/MUN-TEST/',**self.headers(**overrides)).status_code,403)
    def test_idempotency_and_conflicting_request_id(self):
        headers=self.headers();self.client.get('/api/v1/residence/MUN-TEST/',**headers)
        self.client.get('/api/v1/residence/MUN-TEST/',**headers)
        other=self.headers();other['HTTP_X_REQUEST_ID']=headers['HTTP_X_REQUEST_ID']
        self.assertEqual(self.client.get('/api/v1/residence/MUN-TEST/',**other).status_code,409)
        self.assertEqual(Disclosure.objects.count(),1)
    def test_citizen_cannot_edit_source(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user('citizen'))
        self.assertEqual(self.client.get('/records/new/').status_code,403)
