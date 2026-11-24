import secrets
from django.conf import settings
from django.contrib.auth.models import User,Group
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from integration.models import ServiceDefinition
from portal.models import Citizen,IdentityLink
from federation.models import FederatedIdentity
from common.demo import demo_subject

class Command(BaseCommand):
    help='Install local example workflows, identity mappings and a Welfare reviewer.'
    @transaction.atomic
    def handle(self,*args,**kwargs):
        if not settings.DEBUG: raise CommandError('Development seed requires DEBUG.')
        user,created=User.objects.get_or_create(username='welfare')
        if created:
            password=secrets.token_urlsafe(15);user.set_password(password);user.save()
            self.stdout.write('Welfare portal account: welfare / '+password)
        group,_=Group.objects.get_or_create(name='Welfare Officers');user.groups.add(group)
        Group.objects.get_or_create(name='Municipal Reviewers')
        for username in ['citizen','education','welfare','operator']:
            account=User.objects.filter(username=username).first()
            if account: FederatedIdentity.objects.get_or_create(issuer=settings.SSO_ISSUER,subject=str(demo_subject(username)),defaults={'user':account})
        citizen=Citizen.objects.filter(user__username='citizen').first()
        if citizen: IdentityLink.objects.get_or_create(citizen=citizen,department='municipality',defaults={'external_id':'MUN-MH-2001'})
        examples=[
          ('student-scholarship','Student scholarship','Education',48,[
            {'id':'income','kind':'fetch','connector':'revenue','scope':'income_certificate'},
            {'id':'education_review','kind':'review','role':'Education Officers'}]),
          ('housing-assistance','Housing assistance','Welfare',72,[
            {'id':'income','kind':'fetch','connector':'revenue','scope':'income_certificate'},
            {'id':'residence','kind':'fetch','connector':'municipality','scope':'residence_certificate'},
            {'id':'household','kind':'fetch','connector':'municipality_legacy','scope':'household_certificate'},
            {'id':'welfare_review','kind':'review','role':'Welfare Officers'}]),
        ]
        for code,title,department,hours,workflow in examples:
            ServiceDefinition.objects.get_or_create(code=code,version=1,defaults={'title':title,'department':department,'description':'Local departmental service using reviewed identity links and consent. Seed records are fictional.','workflow':workflow,'sla_hours':hours,'published':True})
        self.stdout.write('Two versioned services and fictional identity mappings ready.')
