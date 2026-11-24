from django import forms
from django.core.validators import RegexValidator
from .models import IncomeCertificate


class CertificateForm(forms.ModelForm):
    resident_number = forms.CharField(
        max_length=40,
        validators=[
            RegexValidator(r"^[A-Za-z0-9-]+$", "Use letters, digits and hyphens only.")
        ],
    )

    class Meta:
        model = IncomeCertificate
        fields = [
            "resident_number",
            "certificate_number",
            "resident_name",
            "yearly_income",
            "district_name",
            "issue_date",
            "expiry_date",
            "verified",
        ]
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        values = super().clean()
        if (
            values.get("issue_date")
            and values.get("expiry_date")
            and values["expiry_date"] < values["issue_date"]
        ):
            raise forms.ValidationError("Expiry must not precede issue date.")
        return values
