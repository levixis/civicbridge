from django.core.management.base import BaseCommand, CommandError
from portal.sandbox import ENDPOINT, official_exchange
from portal.connectors import ExchangeError


class Command(BaseCommand):
    help = "Send the official fixed public API Setu sample; no account data or private credentials."

    def handle(self, *args, **options):
        try:
            result = official_exchange()
        except ExchangeError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"Endpoint: {ENDPOINT}")
        self.stdout.write(f"HTTP {result['http_status']} / {result['content_type']}")
        self.stdout.write(
            "Sample-only response; no citizen identity or eligibility verified."
        )
        if result["http_status"] != 200:
            self.stdout.write(result["body"])
