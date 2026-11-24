import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand,CommandError
from django.utils import timezone
from municipal.models import ResidentRecord
from federation.models import FederatedIdentity
from common.demo import demo_subject
class Command(BaseCommand):
    def handle(self,*args,**kwargs):
        if not settings.DEBUG: raise CommandError('Development seed requires DEBUG.')
        user,created=User.objects.get_or_create(username='municipality',defaults={'is_staff':True})
        if created:
            password=secrets.token_urlsafe(15);user.set_password(password);user.save()
            self.stdout.write('Municipal local account: municipality / '+password)
        FederatedIdentity.objects.get_or_create(issuer=settings.SSO_ISSUER,subject=str(demo_subject('municipality')),defaults={'user':user})
        ResidentRecord.objects.get_or_create(person_key='MUN-MH-2001',defaults={'record_no':'RES-MH-2026-2001','full_name':'Aarav Patil','district':'Pune','ward':'Ward 12','members':4,'issued':timezone.localdate(),'expires':timezone.localdate()+timedelta(days=365),'confirmed':True})
        self.stdout.write('Fictional municipal source records ready.')
