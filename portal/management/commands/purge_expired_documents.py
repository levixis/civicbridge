from django.core.management.base import BaseCommand
from portal.worker import purge_expired


class Command(BaseCommand):
    def handle(self, *args, **options):
        self.stdout.write(str(purge_expired()) + " expired document copies removed.")
