import json
from django.core.management.base import BaseCommand,CommandError
from integration.audit import verify
class Command(BaseCommand):
    help='Verify the HMAC audit chain; print a checkpoint for independent retention.'
    def handle(self,*args,**kwargs):
        ok,result=verify()
        if not ok: raise CommandError(result)
        self.stdout.write(json.dumps(result,sort_keys=True))
