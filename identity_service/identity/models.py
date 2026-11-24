import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
class Subject(models.Model):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    identifier=models.UUIDField(default=uuid.uuid4,unique=True)
class AuthorizationCode(models.Model):
    digest=models.CharField(max_length=64,primary_key=True)
    subject=models.ForeignKey(Subject,on_delete=models.CASCADE)
    client=models.CharField(max_length=40)
    redirect=models.CharField(max_length=200)
    nonce=models.CharField(max_length=100)
    challenge=models.CharField(max_length=43)
    expires_at=models.DateTimeField()
    redeemed_at=models.DateTimeField(null=True)
class LoginAttempt(models.Model):
    key=models.CharField(max_length=64,unique=True)
    failures=models.PositiveIntegerField(default=0)
    window_started=models.DateTimeField(default=timezone.now)
