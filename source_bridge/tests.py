import json,uuid
import unittest
from django.conf import settings
from django.test import TestCase
from django.utils import timezone
if 'source_bridge' in settings.INSTALLED_APPS:
    from .models import EventReceipt,ApplicationMirror

def load_tests(loader, tests, pattern):
    return tests if 'source_bridge' in settings.INSTALLED_APPS else unittest.TestSuite()
class SourceEventsTests(TestCase):
    def event(self,sequence=1,status='processing'):
        return {'id':str(uuid.uuid4()),'request':str(self.req),'sequence':sequence,'kind':'request.updated',
            'created_at':timezone.now().isoformat(),'payload':{'schema_version':'1.0','service':'housing','version':1,'status':status,'step':1,'label':'Test event'}}
    def setUp(self): self.req=uuid.uuid4()
    def send(self,event,token=None):
        return self.client.post('/api/v1/events/',json.dumps(event),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+(token or settings.SOURCE_API_TOKEN))
    def test_unauthenticated_rejected(self):
        for token in ['wrong', 'é']:
            with self.subTest(token=token):
                self.assertEqual(self.send(self.event(), token=token).status_code, 401)
        self.assertEqual(EventReceipt.objects.count(),0)
    def test_duplicate_delivery_is_idempotent(self):
        event=self.event();self.assertEqual(self.send(event).status_code,200)
        response=self.send(event);self.assertTrue(response.json()['duplicate'])
        self.assertEqual(EventReceipt.objects.count(),1)
    def test_delayed_event_cannot_regress_tracker(self):
        self.send(self.event(3,'approved'));self.send(self.event(1,'processing'))
        self.assertEqual(ApplicationMirror.objects.get().status,'approved')
        self.assertEqual(ApplicationMirror.objects.get().sequence,3)
    def test_event_id_and_sequence_conflicts(self):
        event=self.event();self.send(event)
        altered=event|{'kind':'tampered'}
        self.assertEqual(self.send(altered).status_code,409)
        self.assertEqual(self.send(self.event()).status_code,409)
    def test_invalid_payload_rejected(self):
        event=self.event();event['payload']['citizen_id']='unexpected'
        self.assertEqual(self.send(event).status_code,400)
        self.assertEqual(EventReceipt.objects.count(),0)
    def test_source_staff_only_tracker(self):
        from django.contrib.auth.models import User
        user=User.objects.create_user('ordinary')
        self.client.force_login(user);self.assertEqual(self.client.get('/tracker/').status_code,403)
        user.is_staff=True;user.save()
        self.assertEqual(self.client.get('/tracker/').status_code,200)
