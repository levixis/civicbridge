import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UsernameField


def resolve_login_username(identifier):
    identifier = unicodedata.normalize('NFKC', identifier.strip())
    if '@' not in identifier or len(identifier) > 254:
        return identifier

    user_model = get_user_model()
    usernames = user_model._default_manager.values_list('username', flat=True)
    if usernames.filter(username=identifier).exists():
        return identifier
    try:
        return usernames.get(email__iexact=identifier)
    except (user_model.DoesNotExist, user_model.MultipleObjectsReturned):
        return identifier


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = UsernameField(
        label='Email or username',
        max_length=254,
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}),
    )
    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Enter a valid email or username and password.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].max_length = 254
        self.fields['username'].widget.attrs['maxlength'] = 254

    def clean(self):
        if identifier := self.cleaned_data.get('username'):
            self.cleaned_data['username'] = resolve_login_username(identifier)
        return super().clean()
