from django.db import models


class RevenueRecord(models.Model):
    # A deliberately different source schema: legacy field names and external IDs.
    resident_number = models.CharField(max_length=40, unique=True)
    certificate_number = models.CharField(max_length=40, unique=True)
    resident_name = models.CharField(max_length=120)
    yearly_income = models.PositiveIntegerField()
    district_name = models.CharField(max_length=100)
    issue_date = models.DateField()
    expiry_date = models.DateField()
    verified = models.BooleanField(default=True)

    def __str__(self):
        return self.certificate_number
