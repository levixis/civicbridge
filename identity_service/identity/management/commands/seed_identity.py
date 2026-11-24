import secrets
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand,CommandError
from django.db.models import Q
from identity.models import Subject
from common.demo import demo_subject
class Command(BaseCommand):
    help='Create fictional local identity accounts. Prints new passwords once.'
    def handle(self,*args,**kwargs):
        if not settings.DEBUG: raise CommandError('Development seed requires DEBUG.')
        for name in ['citizen','education','welfare','operator','revenue','municipality']:
            user,created=User.objects.get_or_create(username=name)
            if created:
                password=secrets.token_urlsafe(15)
                user.set_password(password);user.save()
                self.stdout.write(f'Identity sign-in: {name} / {password}')
            subject, _ = Subject.objects.get_or_create(user=user, defaults={'identifier': demo_subject(name)})
            email = f'{name}@civicbridge.test'
            email_taken = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists()
            if subject.identifier == demo_subject(name) and not user.email and not email_taken:
                user.email = email
                user.save(update_fields=['email'])
