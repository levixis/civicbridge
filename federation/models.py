from django.conf import settings
from django.db import models

class FederatedIdentity(models.Model):
    issuer=models.CharField(max_length=200)
    subject=models.CharField(max_length=200)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['issuer','subject'],name='federated_subject'),models.UniqueConstraint(fields=['issuer','user'],name='one_federated_account')]
