import uuid
from datetime import datetime
from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.crypto import constant_time_compare

def validate(request, subject, scope, audience, token):
    if not constant_time_compare(request.headers.get('Authorization', ''), 'Bearer '+token):
        raise PermissionError('unauthorised')
    try:
        grant=signing.loads(request.headers.get('X-Consent-Grant',''), key=settings.GRANT_SIGNING_KEY, salt='civicbridge.exchange.v1', max_age=60)
        expires=datetime.fromisoformat(grant['expires'])
        if not expires.tzinfo or expires <= timezone.now() or grant['resident']!=subject or grant['scope']!=scope or grant['audience']!=audience:
            raise ValueError()
        if not isinstance(grant['purpose'], str) or not 1 <= len(grant['purpose']) <= 120:
            raise ValueError()
        return uuid.UUID(request.headers['X-Request-ID']), uuid.UUID(grant['application']), uuid.UUID(grant['revision'])
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        raise PermissionError('invalid_consent_grant')
