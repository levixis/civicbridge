import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from portal.models import Citizen
from portal.crypto import unseal


class ServiceDefinition(models.Model):
    code = models.SlugField(max_length=60)
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=1000)
    department = models.CharField(max_length=60)
    workflow = models.JSONField()
    sla_hours = models.PositiveIntegerField(default=72)
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['code', 'version'], name='service_version')]
        ordering = ['code', '-version']

    def clean(self):
        from .contracts import validate_workflow
        validate_workflow(self.workflow)
        if not 1 <= self.sla_hours <= 8760:
            raise ValidationError('Service deadline must be between 1 and 8760 hours.')

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if old.published and any(getattr(old, f) != getattr(self, f) for f in
                                    ['code', 'version', 'title', 'description', 'department', 'workflow', 'sla_hours']):
                raise ValidationError('Published versions are immutable. Create a new version.')
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} v{self.version}'


class ServiceRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    citizen = models.ForeignKey(Citizen, on_delete=models.PROTECT)
    definition = models.ForeignKey(ServiceDefinition, on_delete=models.PROTECT)
    workflow = models.JSONField()  # Immutable snapshot of the published version.
    details = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default='awaiting_consent')
    step = models.PositiveIntegerField(default=0)
    encrypted_records = models.TextField(blank=True)
    due_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def records(self):
        return unseal(self.encrypted_records) if self.encrypted_records else {}

    @property
    def current_step(self):
        return self.workflow[self.step] if self.step < len(self.workflow) else None

    @property
    def terminal(self):
        return self.status in ['approved', 'rejected']

    @property
    def overdue(self):
        return (self.completed_at or timezone.now()) > self.due_at


class ShareConsent(models.Model):
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='consents')
    connector = models.CharField(max_length=40)
    scope = models.CharField(max_length=40)
    purpose = models.CharField(max_length=120)
    revision = models.UUIDField(default=uuid.uuid4)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    granted_at = models.DateTimeField(default=timezone.now)

    @property
    def active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['request', 'connector', 'scope'], name='request_scoped_consent')]


class FetchTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='tasks')
    step = models.PositiveIntegerField()
    consent_revision = models.UUIDField()
    status = models.CharField(max_length=16, default='queued')
    attempts = models.PositiveIntegerField(default=0)
    run_after = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['request'], condition=models.Q(status__in=['queued', 'running']), name='one_active_platform_fetch')]
        indexes = [models.Index(fields=['status', 'run_after'])]


class ReviewDecision(models.Model):
    request = models.ForeignKey(ServiceRequest, on_delete=models.PROTECT, related_name='decisions')
    step = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=12)
    note = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['request', 'step'], name='one_platform_step_decision')]


class DomainEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(ServiceRequest, on_delete=models.PROTECT, related_name='events')
    kind = models.CharField(max_length=60)
    sequence = models.PositiveIntegerField()
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['created_at', 'id']
        constraints = [models.UniqueConstraint(fields=['request', 'sequence'], name='ordered_request_event')]


class EventDelivery(models.Model):
    event = models.ForeignKey(DomainEvent, on_delete=models.CASCADE, related_name='deliveries')
    target = models.CharField(max_length=40)
    status = models.CharField(max_length=16, default='queued')
    attempts = models.PositiveIntegerField(default=0)
    run_after = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'target'], name='one_event_target')]
        indexes = [models.Index(fields=['status', 'run_after'])]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    event = models.ForeignKey(DomainEvent, on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'event'], name='one_notification_event')]


class ConnectorMeasurement(models.Model):
    connector = models.CharField(max_length=40)
    scope = models.CharField(max_length=40)
    success = models.BooleanField()
    elapsed_ms = models.PositiveIntegerField()
    error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DeadlineBreach(models.Model):
    request = models.OneToOneField(ServiceRequest, on_delete=models.PROTECT)
    detected_at = models.DateTimeField(auto_now_add=True)


class IdentityClaim(models.Model):
    citizen = models.ForeignKey(Citizen, on_delete=models.PROTECT)
    department = models.CharField(max_length=40)
    external_id = models.CharField(max_length=40)
    status = models.CharField(max_length=16, default='pending')
    evidence = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=300, blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['citizen', 'department'], condition=models.Q(status='pending'), name='one_platform_identity_claim')]


class AuditHead(models.Model):
    id = models.PositiveIntegerField(primary_key=True, default=1)
    sequence = models.PositiveBigIntegerField(default=0)
    digest = models.CharField(max_length=64, default='0' * 64)


class IntegrityAudit(models.Model):
    sequence = models.PositiveBigIntegerField(primary_key=True)
    record = models.JSONField()
    previous = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Integrity audit entries are append-only.')
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValidationError('Integrity audit entries cannot be deleted through the application.')
