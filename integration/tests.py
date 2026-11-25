import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError
from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from portal.models import Application,Citizen,IdentityLink
from portal.connectors import ExchangeError
from portal.services import exchange,grant_consent
from portal.worker import claim_job,process_job
from .models import *
from . import engine
from .adapters import REGISTRY
from .contracts import validate_record
from .audit import append,verify
from common.demo import demo_subject
from federation.models import FederatedIdentity
from django.conf import settings

WORKFLOW=[{'id':'income','kind':'fetch','connector':'revenue','scope':'income_certificate'},
 {'id':'residence','kind':'fetch','connector':'municipality','scope':'residence_certificate'},
 {'id':'household','kind':'fetch','connector':'municipality_legacy','scope':'household_certificate'},
 {'id':'welfare','kind':'review','role':'Welfare Officers'}]

def record(scope='income_certificate'):
    attrs={'income_certificate':{'annual_income':180000},'residence_certificate':{'district':'Pune'},'household_certificate':{'members':4}}[scope]
    return {'schema_version':'1.0','type':scope,'document_id':'TEST-CERT','subject_id':'TEST-ID','holder':'Fictional Citizen',
        'issuer':'revenue' if scope=='income_certificate' else 'municipality','issued_on':timezone.localdate().isoformat(),
        'valid_until':(timezone.localdate()+timedelta(days=30)).isoformat(),'verified':True,'attributes':attrs}

class PlatformTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('citizen')
        self.citizen=Citizen.objects.create(user=self.user)
        self.other=User.objects.create_user('other');Citizen.objects.create(user=self.other)
        self.welfare=User.objects.create_user('welfare');self.welfare.groups.add(Group.objects.create(name='Welfare Officers'))
        self.operator=User.objects.create_user('operator');self.operator.groups.add(Group.objects.create(name='Integration Operators'))
        self.service=ServiceDefinition.objects.create(code='housing',title='Housing test',description='Fictional local records',department='Welfare',workflow=WORKFLOW,published=True)
        self.req=engine.submit(self.user,self.citizen,self.service,{'description':'Test request'})
        self.client.force_login(self.user)

    def fetch_all(self):
        for _ in range(3):
            self.req.refresh_from_db()
            step=self.req.current_step
            with patch.object(type(REGISTRY[step['connector']]),'fetch',return_value=record(step['scope'])):
                engine.process_fetch(engine.claim(FetchTask))
        self.req.refresh_from_db()

    def test_multi_source_journey_scoped_consent_and_review(self):
        engine.grant(self.user,self.req.pk);self.fetch_all()
        self.assertEqual(self.req.status,'review')
        self.assertEqual(set(self.req.records),{'income','residence','household'})
        self.assertNotIn('Fictional Citizen',self.req.encrypted_records)
        self.assertEqual(self.req.consents.count(),3)
        engine.review(self.welfare,self.req.pk,'approved','Reviewed local data')
        self.req.refresh_from_db();self.assertEqual(self.req.status,'approved')
        self.assertIsNotNone(self.req.completed_at)
        self.assertTrue(verify()[0])

    def test_no_consent_and_repeated_grants(self):
        self.assertIsNone(engine.claim(FetchTask))
        engine.grant(self.user,self.req.pk)
        first_consent = self.req.consents.first()
        engine.grant(self.user,self.req.pk)
        self.assertEqual(FetchTask.objects.count(),1)
        latest_consent = self.req.consents.first()
        self.assertEqual(latest_consent.revision, first_consent.revision)
        self.assertEqual(latest_consent.expires_at, first_consent.expires_at)
        self.assertEqual(self.req.events.filter(kind='consent.granted').count(), 1)
        self.assertEqual(IntegrityAudit.objects.filter(record__action='consent.grant').count(), 1)

    def test_revocation_during_exchange_discards_response(self):
        engine.grant(self.user,self.req.pk)
        def callback(*args):
            engine.revoke(self.user,self.req.pk)
            return record()
        with patch.object(type(REGISTRY['revenue']),'fetch',side_effect=callback):
            engine.process_fetch(engine.claim(FetchTask))
        self.req.refresh_from_db()
        self.assertEqual(self.req.encrypted_records,'')
        self.assertEqual(self.req.status,'awaiting_consent')
        self.assertFalse(FetchTask.objects.filter(status='succeeded').exists())

    def test_expiry_denies_view_and_review_before_purge(self):
        engine.grant(self.user,self.req.pk);self.fetch_all()
        self.req.consents.update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ExchangeError):engine.review(self.welfare,self.req.pk,'approved','Not allowed')
        page=self.client.get(reverse('platform_detail',args=[self.req.pk]))
        self.assertNotContains(page,'Fictional Citizen')
        engine.maintain();self.req.refresh_from_db()
        self.assertEqual(self.req.encrypted_records,'')

    def test_expired_permissions_require_fresh_fetch(self):
        engine.grant(self.user,self.req.pk);self.fetch_all()
        self.req.consents.update(expires_at=timezone.now()-timedelta(seconds=1))
        engine.grant(self.user,self.req.pk);self.req.refresh_from_db()
        self.assertEqual((self.req.status,self.req.step,self.req.encrypted_records),('processing',0,''))

    def test_retries_exhaust_and_user_can_retry(self):
        engine.grant(self.user,self.req.pk)
        for _ in range(4):
            FetchTask.objects.filter(status='queued').update(run_after=timezone.now())
            with patch.object(type(REGISTRY['revenue']),'fetch',side_effect=ExchangeError('Offline',True)):
                engine.process_fetch(engine.claim(FetchTask))
        self.req.refresh_from_db();self.assertEqual(self.req.status,'exchange_failed')
        engine.grant(self.user,self.req.pk)
        engine.grant(self.user,self.req.pk)
        self.assertEqual(FetchTask.objects.filter(status='queued').count(),1)
        self.assertEqual(self.req.events.filter(kind='consent.granted').count(), 1)
        self.assertEqual(self.req.events.get(kind='exchange.retried').payload['status'], 'processing')
        self.assertEqual(IntegrityAudit.objects.filter(record__action='exchange.retry').count(), 1)

    def test_lease_recovery_and_stale_worker_cannot_commit(self):
        engine.grant(self.user,self.req.pk)
        abandoned=engine.claim(FetchTask)
        FetchTask.objects.filter(pk=abandoned.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        replacement=engine.claim(FetchTask)
        self.assertNotEqual(abandoned.lease_token,replacement.lease_token)
        with patch.object(type(REGISTRY['revenue']),'fetch') as fetch:
            engine.process_fetch(abandoned);fetch.assert_not_called()

    def test_wrong_role_owner_and_duplicate_decision_denied(self):
        engine.grant(self.user,self.req.pk);self.fetch_all()
        for actor in [self.user,self.other,self.operator]:
            with self.assertRaises(ExchangeError):engine.review(actor,self.req.pk,'approved','No authority')
        engine.review(self.welfare,self.req.pk,'approved','Approved')
        with self.assertRaises(ExchangeError):engine.review(self.welfare,self.req.pk,'approved','Again')
        self.assertEqual(ReviewDecision.objects.count(),1)

    def test_intermediate_reviews_and_withdrawal_need_new_journey(self):
        flow=WORKFLOW[:1]+[{'id':'education','kind':'review','role':'Education Officers'}]+WORKFLOW[1:]
        service=ServiceDefinition.objects.create(code='multi',title='Two reviews',description='Test',department='Welfare',workflow=flow,published=True)
        req=engine.submit(self.user,self.citizen,service,{})
        education=User.objects.create_user('education');education.groups.add(Group.objects.create(name='Education Officers'))
        engine.grant(self.user,req.pk)
        with patch.object(type(REGISTRY['revenue']),'fetch',return_value=record()):engine.process_fetch(engine.claim(FetchTask))
        engine.review(education,req.pk,'approved','First review')
        engine.revoke(self.user,req.pk);req.refresh_from_db()
        self.assertEqual(req.status,'withdrawn')
        with self.assertRaises(ExchangeError):engine.grant(self.user,req.pk)
        self.assertEqual(req.decisions.count(),1)

    def test_workflow_versions_are_immutable_and_snapshotted(self):
        self.service.workflow=WORKFLOW[:1]+WORKFLOW[-1:]
        with self.assertRaises(ValidationError):self.service.save()
        self.req.refresh_from_db();self.assertEqual(self.req.workflow,WORKFLOW)
        for bad in [[{'id':'bad','kind':'shell','command':'x'}],WORKFLOW+WORKFLOW, [{'id':'url','kind':'fetch','connector':'http://attacker','scope':'income_certificate'},WORKFLOW[-1]]]:
            with self.assertRaises(ValidationError):ServiceDefinition.objects.create(code='bad',title='Bad',description='Test',department='X',workflow=bad)

    def test_old_workflow_link_redirects_new_applications(self):
        newer = ServiceDefinition.objects.create(
            code=self.service.code, version=self.service.version + 1, title=self.service.title,
            description=self.service.description, department=self.service.department,
            workflow=WORKFLOW, published=True,
        )
        self.client.force_login(self.user)
        old_path = reverse('platform_create', args=[self.service.pk])
        new_path = reverse('platform_create', args=[newer.pk])
        self.assertRedirects(self.client.get(old_path), new_path)
        self.assertRedirects(self.client.post(old_path, {'description': 'Old form'}), new_path)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(self.client.post(new_path, {'description': 'New version'}).status_code, 302)
        self.assertTrue(ServiceRequest.objects.filter(definition=newer).exists())
        self.req.refresh_from_db()
        self.assertEqual(self.req.definition, self.service)

    def test_owner_boundaries_csrf_and_operator_only_configuration(self):
        self.client.force_login(self.other)
        for name in ['platform_detail','platform_tracker']:
            self.assertEqual(self.client.get(reverse(name,args=[self.req.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('platform_configure')).status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post(reverse('platform_revoke',args=[self.req.pk])).status_code,403)

    def test_non_text_connector_or_scope_returns_workflow_form_error(self):
        self.client.force_login(self.operator)
        for field, value in [('connector', {}), ('scope', [])]:
            with self.subTest(field=field):
                response = self.client.post(reverse('platform_configure'), {
                    'code': 'invalid', 'version': 1, 'title': 'Invalid', 'description': 'Test',
                    'department': 'Welfare', 'sla_hours': 72,
                    'workflow': json.dumps([WORKFLOW[0] | {field: value}, WORKFLOW[-1]]),
                })
                self.assertContains(response, 'Connector and scope must be text.')
        self.assertFalse(ServiceDefinition.objects.filter(code='invalid').exists())

    def test_event_notifications_idempotent_and_dead_letter_retry(self):
        delivery=EventDelivery.objects.filter(target='notifications').first()
        engine.process_delivery(engine.claim(EventDelivery))
        delivery.refresh_from_db();self.assertEqual(delivery.status,'delivered')
        delivery.status='queued';delivery.save();engine.process_delivery(engine.claim(EventDelivery))
        self.assertEqual(Notification.objects.count(),1)
        # Force transient provider failures until the durable delivery is dead-lettered.
        provider=EventDelivery.objects.exclude(target='notifications').first()
        EventDelivery.objects.exclude(pk=provider.pk).update(status='delivered')
        for _ in range(4):
            provider.run_after=timezone.now();provider.save()
            with patch.object(type(REGISTRY['revenue']),'deliver',side_effect=ExchangeError('Offline',True)):
                engine.process_delivery(engine.claim(EventDelivery))
            provider.refresh_from_db()
        self.assertEqual(provider.status,'failed')
        self.client.force_login(self.operator)
        self.client.post(reverse('platform_retry_delivery',args=[provider.pk]))
        provider.refresh_from_db();self.assertEqual((provider.status,provider.attempts),('queued',0))

    def test_deadline_alert_occurs_once(self):
        ServiceRequest.objects.filter(pk=self.req.pk).update(due_at=timezone.now()-timedelta(hours=1))
        engine.maintain();engine.maintain()
        self.assertEqual(DeadlineBreach.objects.count(),1)
        self.assertEqual(DomainEvent.objects.filter(kind='deadline.breached').count(),1)
        EventDelivery.objects.exclude(event__kind='deadline.breached', target='notifications').update(status='delivered')
        engine.process_delivery(engine.claim(EventDelivery))
        self.assertTrue(Notification.objects.filter(user=self.operator,event__kind='deadline.breached').exists())

    def test_identity_conflict_is_not_silently_merged(self):
        other=Citizen.objects.get(user=self.other)
        IdentityLink.objects.create(citizen=other,department='municipality',external_id='DUPLICATE')
        claim=IdentityClaim.objects.create(citizen=self.citizen,department='municipality',external_id='DUPLICATE')
        self.client.force_login(self.operator)
        response=self.client.post(reverse('platform_claim_review',args=[claim.pk]),{'decision':'approved','evidence':'CASE-001','note':'Verified'})
        self.assertContains(response,'Identity conflict')
        self.assertFalse(IdentityLink.objects.filter(citizen=self.citizen,department='municipality').exists())

    def test_citizen_can_withdraw_and_replace_only_their_own_pending_link_request(self):
        identities = reverse('platform_identities')
        details = {'department': 'municipality', 'external_id': 'WRONG-ID'}
        self.assertRedirects(self.client.post(identities, details), identities)
        claim = IdentityClaim.objects.get(citizen=self.citizen)
        withdraw = reverse('platform_withdraw_claim', args=[claim.pk])
        self.assertContains(self.client.get(identities), 'Pending operator review')
        self.assertEqual(self.client.get(withdraw).status_code, 405)
        outsider = Client()
        outsider.force_login(self.other)
        self.assertEqual(outsider.post(withdraw).status_code, 404)
        self.assertRedirects(self.client.post(withdraw), identities)
        claim.refresh_from_db()
        self.assertEqual(claim.status, 'withdrawn')
        self.assertFalse(IdentityLink.objects.filter(citizen=self.citizen).exists())
        self.assertTrue(verify()[0])
        self.assertRedirects(self.client.post(identities, details | {'external_id': 'CORRECT-ID'}), identities)
        self.assertEqual(IdentityClaim.objects.get(citizen=self.citizen, status='pending').external_id, 'CORRECT-ID')

    def test_identity_correction_invalidates_existing_grants(self):
        IdentityLink.objects.create(citizen=self.citizen,department='municipality',external_id='OLD')
        engine.grant(self.user,self.req.pk);self.fetch_all()
        claim=IdentityClaim.objects.create(citizen=self.citizen,department='municipality',external_id='NEW')
        self.client.force_login(self.operator)
        self.client.post(reverse('platform_claim_review',args=[claim.pk]),{'decision':'approved','evidence':'CASE-002','note':'Corrected ownership'})
        self.req.refresh_from_db();self.assertEqual(self.req.encrypted_records,'')
        self.assertFalse(self.req.consents.filter(revoked_at=None).exists())

    def test_revenue_correction_removes_legacy_document_and_cancels_exchanges(self):
        IdentityLink.objects.create(citizen=self.citizen, department='revenue', external_id='OLD')
        legacy = Application.objects.create(citizen=self.citizen)
        grant_consent(self.user, legacy.pk)
        legacy.refresh_from_db()
        legacy.document_snapshot = {'holder': 'Previous record'}
        legacy.status = Application.Status.APPROVED
        legacy.officer_note = 'Original decision'
        legacy.save()

        in_progress = Application.objects.create(citizen=self.citizen)
        grant_consent(self.user, in_progress.pk)
        exchange(self.user, in_progress.pk)
        running_job = claim_job()
        queued = Application.objects.create(citizen=self.citizen)
        grant_consent(self.user, queued.pk)
        exchange(self.user, queued.pk)
        claim = IdentityClaim.objects.create(citizen=self.citizen, department='revenue', external_id='NEW')

        self.assertEqual(self.client.get(reverse('document_download', args=[legacy.pk])).status_code, 200)
        operator = Client()
        operator.force_login(self.operator)

        def approve_correction(*args):
            response = operator.post(reverse('platform_claim_review', args=[claim.pk]), {
                'decision': 'approved', 'evidence': 'CASE-003', 'note': 'Corrected ownership',
            })
            self.assertRedirects(response, reverse('platform_claims'))
            received = record()
            return received['attributes'] | {
                'document_id': 'OLD-CERT', 'type': 'income_certificate', 'holder': 'Previous record',
                'district': 'Pune', 'issued_on': received['issued_on'], 'valid_until': received['valid_until'],
                'verified': True, 'source': 'Revenue API',
            }

        with patch('portal.connectors.RevenueConnector.fetch', side_effect=approve_correction) as fetch:
            process_job(running_job)
            fetch.assert_called_once()

        for application in [in_progress, queued]:
            application.refresh_from_db()
            self.assertEqual(application.status, Application.Status.PENDING)
            self.assertEqual(application.encrypted_document, '')
            self.assertEqual(application.jobs.get().status, 'cancelled')
            self.assertIsNotNone(application.consent.revoked_at)
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, Application.Status.APPROVED)
        self.assertEqual(legacy.officer_note, 'Original decision')
        self.assertEqual(legacy.encrypted_document, '')
        self.assertIsNotNone(legacy.consent.revoked_at)
        self.assertEqual(self.client.get(reverse('document_download', args=[legacy.pk])).status_code, 403)

    def test_audit_tampering_and_tail_deletion_detected(self):
        self.assertTrue(verify()[0])
        tail=IntegrityAudit.objects.order_by('-sequence').first()
        IntegrityAudit.objects.filter(pk=tail.pk).update(record={'tampered':True})
        self.assertFalse(verify()[0])

    def test_audit_tail_deletion_detected(self):
        IntegrityAudit.objects.order_by('-sequence').first().__class__.objects.filter(sequence=AuditHead.objects.get(pk=1).sequence).delete()
        self.assertFalse(verify()[0])

    def test_deleted_audit_head_is_detected(self):
        AuditHead.objects.all().delete()
        self.assertFalse(verify()[0])

    def test_invalid_shared_schema_is_rejected(self):
        for data in [record()|{'schema_version':'2.0'},record()|{'verified':False},record()|{'attributes':{'annual_income':True}},record()|{'valid_until':'1999-01-01'}]:
            with self.assertRaises(ExchangeError):validate_record(data)

    def test_legacy_csv_schema_mapping(self):
        mapped=REGISTRY['municipality_legacy'].map_record({'PERSON_KEY':'TEST-ID','RECORD_NO':'HH1','FULL_NAME':'Test','MEMBERS':'4','ISSUED':timezone.localdate().isoformat(),'EXPIRES':(timezone.localdate()+timedelta(days=10)).isoformat(),'CONFIRMED':'true'},'household_certificate')
        self.assertEqual(validate_record(mapped)['attributes']['members'],4)

    def test_ui_pages_render_for_authorised_roles(self):
        for name in ['platform_catalog','platform_workspace','platform_notifications','platform_identities']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200)
        self.client.force_login(self.operator)
        for name in ['platform_configure','platform_claims','platform_monitor']:
            with patch.object(type(REGISTRY['revenue']),'health',return_value={'name':'local','status':'Test'}):
                self.assertEqual(self.client.get(reverse(name)).status_code,200)

    def test_operator_workspace_leads_to_pending_identity_requests(self):
        claim = IdentityClaim.objects.create(citizen=self.citizen, department='municipality', external_id='123')
        self.client.force_login(self.operator)
        with patch.object(type(REGISTRY['revenue']), 'health', return_value={'name': 'local', 'status': 'Test'}):
            response = self.client.get(reverse('platform_workspace'), follow=True)
        self.assertEqual(response.redirect_chain, [(reverse('platform_monitor'), 302)])
        self.assertContains(response, '1 request waiting for review')
        self.assertContains(response, 'Review identity requests')
        queue = self.client.get(reverse('platform_claims'))
        self.assertContains(queue, reverse('platform_claim_review', args=[claim.pk]))
        self.assertContains(queue, 'Review request')

    def test_reviewer_workspace_puts_ready_applications_first(self):
        engine.grant(self.user, self.req.pk)
        self.fetch_all()
        newer = engine.submit(self.user, self.citizen, self.service, {'description': 'Awaiting consent'})
        self.client.force_login(self.welfare)
        response = self.client.get(reverse('platform_workspace'))
        self.assertContains(response, 'Ready for your decision')
        self.assertEqual([item.pk for item in response.context['requests']], [self.req.pk, newer.pk])

    def test_existing_departmental_portal_profile_redirects_to_its_registry(self):
        for department in ['revenue', 'municipality']:
            with self.subTest(department=department):
                subject = str(demo_subject(department))
                user = User.objects.create_user('legacy-' + department)
                citizen = Citizen.objects.create(user=user)
                FederatedIdentity.objects.create(issuer=settings.SSO_ISSUER, subject=subject, user=user)
                self.client.force_login(user)
                destination = settings.SSO_DEPARTMENT_ROUTES[subject]
                for method, path in [('get', reverse('platform_workspace')), ('post', reverse('platform_create', args=[self.service.pk]))]:
                    self.client.force_login(user)
                    response = getattr(self.client, method)(path, {'description': 'Test'})
                    self.assertRedirects(response, destination, fetch_redirect_response=False)
                    self.assertNotIn('_auth_user_id', self.client.session)
                self.assertFalse(ServiceRequest.objects.filter(citizen=citizen).exists())
                self.assertTrue(Citizen.objects.filter(pk=citizen.pk).exists())
