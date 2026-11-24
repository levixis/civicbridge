import uuid
from django.db import models
from django.utils import timezone


class IncomeCertificate(models.Model):
    resident_number = models.CharField(max_length=40, unique=True)
    certificate_number = models.CharField(max_length=40, unique=True)
    resident_name = models.CharField(max_length=120)
    yearly_income = models.PositiveBigIntegerField()
    district_name = models.CharField(max_length=100)
    issue_date = models.DateField()
    expiry_date = models.DateField()
    verified = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.certificate_number

    def payload(self):
        return {
            key: getattr(self, key)
            for key in [
                "resident_number",
                "certificate_number",
                "resident_name",
                "yearly_income",
                "district_name",
                "verified",
            ]
        } | {
            "issue_date": self.issue_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat(),
        }


class Disclosure(models.Model):
    request_id = models.UUIDField(primary_key=True)
    resident_number = models.CharField(max_length=40)
    application_reference = models.UUIDField()
    consent_revision = models.UUIDField()
    accessed_at = models.DateTimeField(default=timezone.now)


class SourceEvent(models.Model):
    action = models.CharField(max_length=40)
    actor = models.CharField(max_length=150)
    certificate_number = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    window_started = models.DateTimeField(default=timezone.now)
