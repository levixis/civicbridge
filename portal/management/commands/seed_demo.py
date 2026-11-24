import secrets
from datetime import date, timedelta
from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from portal.models import Citizen, IdentityLink


class Command(BaseCommand):
    help = "Create fictional development accounts and a linked identity. Password printed once; existing accounts preserved."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password", help="Optional local demo password (minimum 10 characters)."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError("Development seed is disabled outside DEBUG mode.")
        password = options["password"] or secrets.token_urlsafe(12)
        if len(password) < 10:
            raise CommandError("Demo password must be at least 10 characters.")
        roles = {"education": "Education Officers", "operator": "Integration Operators"}
        for username in ["citizen", *roles]:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": (
                        "Aarav" if username == "citizen" else username.title()
                    ),
                    "last_name": "Patil" if username == "citizen" else "Demo",
                },
            )
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(f"Created {username} / {password}")
            else:
                self.stdout.write(f"Kept existing {username}; password unchanged.")
            if username in roles:
                group, _ = Group.objects.get_or_create(name=roles[username])
                user.groups.add(group)
            else:
                citizen, _ = Citizen.objects.get_or_create(user=user)
                IdentityLink.objects.get_or_create(
                    citizen=citizen,
                    department="revenue",
                    defaults={"external_id": "REV-MH-1001"},
                )
        self.stdout.write(
            "Demo records ready. Use createsuperuser for an admin account. Source records must be seeded separately with revenue_service/manage.py seed_revenue."
        )
