from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Grant an existing account a reviewed organisational role."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("role", choices=["education", "operator", "welfare", "municipal"])

    def handle(self, *args, **options):
        user = User.objects.filter(username=options["username"]).first()
        if not user:
            raise CommandError("Create the user account first.")
        group, _ = Group.objects.get_or_create(
            name={
                "education": "Education Officers",
                "operator": "Integration Operators",
                "welfare": "Welfare Officers",
                "municipal": "Municipal Reviewers",
            }[options["role"]]
        )
        user.groups.add(group)
        self.stdout.write("Role provisioned for " + user.username)
