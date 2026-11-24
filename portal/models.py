import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class Citizen(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    phone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class IdentityLink(models.Model):
    citizen = models.ForeignKey(Citizen, on_delete=models.CASCADE)
    department = models.CharField(max_length=30)
    external_id = models.CharField(max_length=40)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["citizen", "department"], name="one_link_per_department"
            ),
            models.UniqueConstraint(
                fields=["department", "external_id"], name="unique_external_identity"
            ),
        ]


class Application(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting consent"
        PROCESSING = "processing", "Exchange in progress"
        VERIFIED = "verified", "Document verified"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    citizen = models.ForeignKey(Citizen, on_delete=models.CASCADE)
    institution = models.CharField(max_length=120)
    course = models.CharField(max_length=120)
    statement = models.TextField(max_length=800)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    encrypted_document = models.TextField(blank=True, default="")

    @property
    def document_snapshot(self):
        from .crypto import unseal

        return unseal(self.encrypted_document)

    @document_snapshot.setter
    def document_snapshot(self, value):
        from .crypto import seal

        self.encrypted_document = seal(value) if value else ""

    officer_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.reference)


class Consent(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE)
    revision = models.UUIDField(default=uuid.uuid4, editable=False)
    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    scope = models.CharField(max_length=40, default="income_certificate")
    purpose = models.CharField(
        max_length=120, default="Scholarship eligibility verification"
    )

    @property
    def active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()


class Event(models.Model):
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="events"
    )
    label = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class Audit(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    citizen = models.ForeignKey(Citizen, on_delete=models.SET_NULL, null=True)
    application = models.ForeignKey(
        Application, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=60)
    outcome = models.CharField(max_length=20)
    detail = models.CharField(max_length=250)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class ExchangeJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="jobs"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    consent_revision = models.UUIDField()
    status = models.CharField(
        max_length=15,
        default="queued",
        choices=[
            (x, x.title())
            for x in ["queued", "running", "succeeded", "failed", "cancelled"]
        ],
    )
    attempts = models.PositiveIntegerField(default=0)
    run_after = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application"],
                condition=models.Q(status__in=["queued", "running"]),
                name="one_live_exchange_per_application",
            )
        ]
        indexes = [models.Index(fields=["status", "run_after"])]


class IdentityRequest(models.Model):
    citizen = models.ForeignKey(Citizen, on_delete=models.CASCADE)
    external_id = models.CharField(max_length=40)
    verification_reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=12,
        default="pending",
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["citizen"],
                condition=models.Q(status="pending"),
                name="one_pending_identity_request",
            )
        ]


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    window_started = models.DateTimeField(default=timezone.now)


class WorkerHeartbeat(models.Model):
    name = models.CharField(max_length=60, unique=True)
    last_seen = models.DateTimeField(default=timezone.now)


class SandboxRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mode = models.CharField(
        max_length=12,
        choices=[
            ("official", "Official API Setu"),
            ("fixture", "Local classroom fixture"),
        ],
    )
    status = models.CharField(
        max_length=12,
        default="queued",
        choices=[
            (s, s.title())
            for s in ["queued", "running", "received", "failed", "cancelled", "expired"]
        ],
    )
    attempts = models.PositiveIntegerField(default=0)
    run_after = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    consent_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    encrypted_response = models.TextField(blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner"],
                condition=models.Q(status__in=["queued", "running"]),
                name="one_live_sandbox_per_owner",
            )
        ]
        indexes = [models.Index(fields=["status", "run_after"])]
