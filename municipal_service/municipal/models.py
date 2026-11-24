from django.db import models
from django.utils import timezone

class ResidentRecord(models.Model):
    person_key = models.CharField(max_length=40, unique=True)
    record_no = models.CharField(max_length=40, unique=True)
    full_name = models.CharField(max_length=120)
    district = models.CharField(max_length=100)
    ward = models.CharField(max_length=60)
    members = models.PositiveIntegerField(default=1)
    issued = models.DateField()
    expires = models.DateField()
    confirmed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

class Disclosure(models.Model):
    request_id = models.UUIDField(primary_key=True)
    person_key = models.CharField(max_length=40)
    scope = models.CharField(max_length=40)
    application_reference = models.UUIDField()
    revision = models.UUIDField()
    accessed_at = models.DateTimeField(default=timezone.now)

class LoginAttempt(models.Model):
    key=models.CharField(max_length=64,unique=True)
    failures=models.PositiveIntegerField(default=0)
    window_started=models.DateTimeField(default=timezone.now)
