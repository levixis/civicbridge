import csv, io
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET
from common.grants import validate
from .models import ResidentRecord, Disclosure

@require_GET
def health(request):
    ResidentRecord.objects.exists()
    return JsonResponse({'status':'ok','service':'municipality','contract':'v1'})

@require_GET
def record_api(request, subject, legacy=False):
    scope='household_certificate' if legacy else 'residence_certificate'
    try:
        request_id, application, revision=validate(request, subject, scope, 'municipality', settings.MUNICIPAL_API_TOKEN)
    except PermissionError as e:
        return JsonResponse({'error':str(e)}, status=401 if str(e)=='unauthorised' else 403)
    record=ResidentRecord.objects.filter(person_key=subject).first()
    if not record:
        return JsonResponse({'error':'not_found'},status=404)
    with transaction.atomic():
        receipt, _=Disclosure.objects.get_or_create(pk=request_id, defaults={'person_key':subject,'scope':scope,'application_reference':application,'revision':revision})
        if (receipt.person_key,receipt.scope,receipt.application_reference,receipt.revision)!=(subject,scope,application,revision):
            return JsonResponse({'error':'request_id_conflict'},status=409)
    if legacy:
        output=io.StringIO()
        writer=csv.writer(output)
        writer.writerow(['PERSON_KEY','RECORD_NO','FULL_NAME','MEMBERS','ISSUED','EXPIRES','CONFIRMED'])
        writer.writerow([record.person_key,record.record_no+'-H',record.full_name,record.members,record.issued.isoformat(),record.expires.isoformat(),str(record.confirmed).lower()])
        response=HttpResponse(output.getvalue(),content_type='text/csv')
    else:
        response=JsonResponse({'person_key':record.person_key,'record_no':record.record_no,'full_name':record.full_name,'district':record.district,'ward':record.ward,'issued':record.issued.isoformat(),'expires':record.expires.isoformat(),'confirmed':record.confirmed})
    response['Cache-Control']='no-store'
    return response

class ResidentForm(forms.ModelForm):
    class Meta:
        model=ResidentRecord
        fields=['person_key','record_no','full_name','district','ward','members','issued','expires','confirmed']
        widgets={'issued':forms.DateInput(attrs={'type':'date'}),'expires':forms.DateInput(attrs={'type':'date'})}
    def clean(self):
        data=super().clean()
        if data.get('issued') and data.get('expires') and data['expires']<data['issued']:
            raise forms.ValidationError('Expiry must follow issue date.')
        if not 1<=data.get('members',1)<=100:
            raise forms.ValidationError('Household size must be 1–100.')
        return data

@login_required
def registry(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('Municipal staff required.')
    return render(request,'municipal_registry.html',{'records':ResidentRecord.objects.order_by('person_key')[:100]})

@login_required
def edit(request, pk=None):
    if not request.user.is_staff:
        return HttpResponseForbidden('Municipal staff required.')
    form=ResidentForm(request.POST or None,instance=get_object_or_404(ResidentRecord,pk=pk) if pk else None)
    if request.method=='POST' and form.is_valid():
        form.save()
        return redirect('registry')
    return render(request,'source_form.html',{'form':form,'title':'Municipal resident record'})
