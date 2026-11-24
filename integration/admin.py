from django.contrib import admin
from .models import ServiceDefinition,ServiceRequest,ShareConsent,FetchTask,ReviewDecision,DomainEvent,EventDelivery,Notification,ConnectorMeasurement,DeadlineBreach,IdentityClaim,AuditHead,IntegrityAudit
@admin.register(ServiceDefinition,ServiceRequest,ShareConsent,FetchTask,ReviewDecision,DomainEvent,EventDelivery,Notification,ConnectorMeasurement,DeadlineBreach,IdentityClaim,AuditHead,IntegrityAudit)
class ReadOnly(admin.ModelAdmin):
    def get_readonly_fields(self,request,obj=None): return [field.name for field in self.model._meta.fields]
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False
