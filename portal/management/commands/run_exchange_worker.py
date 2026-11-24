import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from portal.worker import tick


class Command(BaseCommand):
    help = "Process durable HTTP exchange jobs; run as a supervised process."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            worked = tick()
            if options["once"]:
                break
            if not worked:
                time.sleep(2)
