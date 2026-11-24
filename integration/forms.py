import json
from django import forms
from django.core.validators import RegexValidator
from .models import ServiceDefinition
from .adapters import REGISTRY

class ServiceForm(forms.ModelForm):
    class Meta:
        model=ServiceDefinition
        fields=['code','version','title','description','department','sla_hours','workflow','published']
        widgets={'workflow':forms.Textarea(attrs={'rows':14}),'description':forms.Textarea(attrs={'rows':3})}

class RequestForm(forms.Form):
    description=forms.CharField(max_length=800,widget=forms.Textarea(attrs={'rows':4}),label='Why are you applying?')

class ConsentForm(forms.Form):
    agree=forms.BooleanField(label='I allow the departments listed above to share these records for this application for up to seven days.')

class ReviewForm(forms.Form):
    decision=forms.ChoiceField(choices=[('approved','Approve this step'),('rejected','Reject application')])
    note=forms.CharField(max_length=500,widget=forms.Textarea(attrs={'rows':3}))

class ClaimForm(forms.Form):
    department=forms.ChoiceField(choices=[(v,v.title()) for v in sorted({a.department for a in REGISTRY.values()})])
    external_id = forms.CharField(
        label='ID issued by the department',
        max_length=40,
        validators=[RegexValidator(r'^[A-Za-z0-9-]+$', 'Use letters, digits and hyphens.')],
    )

class ClaimReviewForm(forms.Form):
    decision=forms.ChoiceField(choices=[('approved','Approve reviewed link'),('rejected','Reject claim')])
    evidence=forms.CharField(max_length=120,label='Evidence or verification case reference')
    note=forms.CharField(max_length=300,widget=forms.Textarea(attrs={'rows':3}))
