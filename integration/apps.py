from django.apps import AppConfig
class IntegrationConfig(AppConfig):
    name='integration'
    def ready(self):
        from django.db.models.signals import post_save
        from portal.models import Audit
        def capture(sender,instance,created,**kwargs):
            if created:
                from .audit import append
                append(instance.actor, 'legacy.'+instance.action, detail=f'Audit {instance.pk}: {instance.detail}',outcome=instance.outcome)
        post_save.connect(capture,sender=Audit,weak=False,dispatch_uid='platform_legacy_audit')
