from django import forms
from django.contrib.auth.forms import UserCreationForm


class IdentityRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=False,
        max_length=254,
        help_text='Add an email address if you want to use it for shared sign-in.',
    )

    class Meta(UserCreationForm.Meta):
        fields = ('username', 'email')
