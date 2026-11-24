import secrets
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from registry.models import IncomeCertificate


class Command(BaseCommand):
    help = "Create fictional development records and a source staff account."

    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError("Development seed is disabled outside DEBUG mode.")
        user, created = User.objects.get_or_create(
            username="revenue", defaults={"is_staff": True}
        )
        if created:
            password = secrets.token_urlsafe(15)
            user.set_password(password)
            user.save()
            self.stdout.write("Revenue staff account created; password: " + password)
        IncomeCertificate.objects.get_or_create(
            resident_number="REV-MH-1001",
            defaults={
                "certificate_number": "INC-MH-2026-1001",
                "resident_name": "Aarav Patil",
                "yearly_income": 180000,
                "district_name": "Pune",
                "issue_date": timezone.localdate(),
                "expiry_date": timezone.localdate() + timedelta(days=365),
                "verified": True,
            },
        )
        self.stdout.write(
            "Revenue development records ready. Existing account passwords unchanged."
        )
        from federation.models import FederatedIdentity
        from common.demo import demo_subject
        FederatedIdentity.objects.get_or_create(issuer=settings.SSO_ISSUER, subject=str(demo_subject('revenue')), defaults={'user':user})
