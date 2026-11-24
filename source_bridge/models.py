from django.db import models

class EventReceipt(models.Model):
    id = models.UUIDField(primary_key=True)
    request_id = models.UUIDField()
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=60)
    payload = models.JSONField()
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['request_id', 'sequence'], name='source_event_sequence')]

class ApplicationMirror(models.Model):
    request_id = models.UUIDField(primary_key=True)
    sequence = models.PositiveIntegerField()
    service = models.CharField(max_length=60)
    status = models.CharField(max_length=24)
    label = models.CharField(max_length=180)
    updated_at = models.DateTimeField()
