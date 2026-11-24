from django.contrib import admin
from .models import (
    Citizen,
    IdentityLink,
    Application,
    Consent,
    Event,
    Audit,
    ExchangeJob,
    IdentityRequest,
    WorkerHeartbeat,
    SandboxRun,
)

admin.site.site_header = "CivicBridge Administration"
admin.site.register(Citizen)


@admin.register(IdentityLink)
class IdentityLinkAdmin(admin.ModelAdmin):
    readonly_fields = ["citizen", "department", "external_id"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["reference", "citizen", "status", "created_at"]
    readonly_fields = [
        "reference",
        "citizen",
        "institution",
        "course",
        "statement",
        "status",
        "document_snapshot",
        "officer_note",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(
    Audit, Consent, Event, ExchangeJob, IdentityRequest, WorkerHeartbeat, SandboxRun
)
class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
