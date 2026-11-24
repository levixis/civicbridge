import json
from cryptography.fernet import Fernet
from django.conf import settings


def seal(value):
    return (
        Fernet(settings.DOCUMENT_ENCRYPTION_KEY.encode())
        .encrypt(json.dumps(value, sort_keys=True).encode())
        .decode()
    )


def unseal(value):
    return (
        json.loads(
            Fernet(settings.DOCUMENT_ENCRYPTION_KEY.encode()).decrypt(value.encode())
        )
        if value
        else {}
    )
