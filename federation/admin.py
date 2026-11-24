from django.contrib import admin
from .models import FederatedIdentity
@admin.register(FederatedIdentity)
class ReadOnly(admin.ModelAdmin):
    readonly_fields=['issuer','subject','user']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
