from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction,IntegrityError
from federation.models import FederatedIdentity
class Command(BaseCommand):
    help='Bind an existing local account to an independently verified identity-provider subject.'
    def add_arguments(self,parser):
        parser.add_argument('username');parser.add_argument('subject')
    def handle(self,*args,**options):
        user=User.objects.filter(username=options['username']).first()
        if not user:raise CommandError('Create the reviewed local account first.')
        subject=options['subject']
        if not 1<=len(subject)<=200:raise CommandError('Invalid subject identifier.')
        try:
            with transaction.atomic():
                identity,created=FederatedIdentity.objects.get_or_create(issuer=settings.SSO_ISSUER,subject=subject,defaults={'user':user})
                if identity.user_id!=user.pk:raise CommandError('Subject is already bound to another account.')
        except IntegrityError:raise CommandError('The account is already bound to a different subject.')
        self.stdout.write('Verified identity binding recorded. No role was granted.')
