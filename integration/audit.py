import hashlib
import hmac
import json
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import AuditHead, IntegrityAudit


def digest(sequence, record, previous):
    encoded = json.dumps({'sequence': sequence, 'record': record, 'previous': previous}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hmac.new(settings.AUDIT_CHAIN_KEY.encode(), encoded, hashlib.sha256).hexdigest()


@transaction.atomic
def append(actor, action, request=None, detail='', outcome='success'):
    AuditHead.objects.get_or_create(pk=1)
    head = AuditHead.objects.select_for_update().get(pk=1)
    sequence = head.sequence + 1
    record = {'at': timezone.now().isoformat(), 'actor_id': str(actor.pk) if actor else 'system',
              'action': action, 'request': str(request.pk) if request else '',
              'outcome': outcome, 'detail': str(detail)[:250]}
    signature = digest(sequence, record, head.digest)
    IntegrityAudit.objects.create(sequence=sequence, record=record, previous=head.digest, digest=signature)
    head.sequence, head.digest = sequence, signature
    head.save()
    return signature


def verify():
    previous, count = '0' * 64, 0
    for entry in IntegrityAudit.objects.order_by('sequence').iterator():
        count += 1
        if entry.sequence != count or entry.previous != previous or not hmac.compare_digest(entry.digest, digest(entry.sequence, entry.record, previous)):
            return False, f'Integrity failure at sequence {entry.sequence}.'
        previous = entry.digest
    head = AuditHead.objects.filter(pk=1).first()
    if count and head is None:
        return False, 'Audit head is missing.'
    if head and (head.sequence != count or head.digest != previous):
        return False, 'Audit head differs from the stored chain (possible tail deletion).'
    return True, {'sequence': count, 'digest': previous}
