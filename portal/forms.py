from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db.models import Q
from .models import Application
from common.authentication import EmailOrUsernameAuthenticationForm
from .permissions import is_portal_staff


class CitizenAuthenticationForm(EmailOrUsernameAuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not hasattr(user, "citizen") or is_portal_staff(user):
            raise forms.ValidationError("Use Department staff sign-in for this account.", code="staff_account")


class StaffAuthenticationForm(EmailOrUsernameAuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not is_portal_staff(user):
            raise forms.ValidationError("A department staff account is required. Citizens can use Citizen sign-in.", code="citizen_account")


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=70)
    last_name = forms.CharField(max_length=70)
    email = forms.EmailField()

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
        ]

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        username = cleaned_data.get("username")
        accounts = User.objects.all()
        if email and accounts.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            self.add_error("email", "This email address is already used for portal sign-in.")
        if username and "@" in username and accounts.filter(email__iexact=username).exists():
            self.add_error("username", "This username is already used as a portal sign-in email.")
        return cleaned_data


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ["institution", "course", "statement"]
        widgets = {"statement": forms.Textarea(attrs={"rows": 4})}


class ConsentForm(forms.Form):
    agree = forms.BooleanField(
        label="I authorise Education to read my income certificate from Revenue for this application for 7 days. I can revoke this access."
    )


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[("approved", "Approve"), ("rejected", "Reject")]
    )
    note = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))


from django.core.validators import RegexValidator


class IdentityRequestForm(forms.Form):
    external_id = forms.CharField(
        max_length=40,
        label="Revenue resident ID",
        validators=[
            RegexValidator(r"^[A-Za-z0-9-]+$", "Use letters, digits and hyphens only.")
        ],
    )


class IdentityReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[("approved", "Approve link"), ("rejected", "Reject request")]
    )
    verification_reference = forms.CharField(
        max_length=120, label="Verified evidence or case reference"
    )
    note = forms.CharField(max_length=300, widget=forms.Textarea(attrs={"rows": 3}))
