import hashlib
import json
import uuid
from datetime import datetime
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import EventReceipt, ApplicationMirror

@csrf_exempt  # Authenticated service-to-service API: never accepts browser session credentials.
@require_POST
def receive(request):
    if not constant_time_compare(request.headers.get('Authorization', ''), 'Bearer '+settings.SOURCE_API_TOKEN):
        return JsonResponse({'error':'unauthorised'}, status=401)
    try:
        if len(request.body) > 16384:
            raise ValueError()
        raw = json.loads(request.body)
        event_id, req_id = uuid.UUID(raw['id']), uuid.UUID(raw['request'])
        sequence, payload = raw['sequence'], raw['payload']
        stamp = datetime.fromisoformat(raw['created_at'])
        if type(sequence) is not int or not 1 <= sequence <= 10000 or not stamp.tzinfo or not isinstance(payload, dict):
            raise ValueError()
        if payload.get('schema_version') != '1.0' or set(payload) != {'schema_version','service','version','status','step','label'}:
            raise ValueError()
        for k, limit in [('service',60), ('status',24), ('label',180)]:
            if not isinstance(payload[k], str) or not 1 <= len(payload[k]) <= limit:
                raise ValueError()
        if not isinstance(raw['kind'], str) or not 1 <= len(raw['kind']) <= 60:
            raise ValueError()
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error':'invalid_event'}, status=400)
    try:
        with transaction.atomic():
            receipt, created = EventReceipt.objects.get_or_create(pk=event_id, defaults={
                'request_id':req_id, 'sequence':sequence, 'kind':raw['kind'], 'payload':payload, 'digest':digest, 'created_at':stamp})
            if receipt.digest != digest:
                return JsonResponse({'error':'event_id_conflict'}, status=409)
            mirror, _ = ApplicationMirror.objects.get_or_create(request_id=req_id, defaults={
                'sequence':sequence, 'service':payload['service'], 'status':payload['status'], 'label':payload['label'], 'updated_at':stamp})
            # Conditional update prevents delayed retries from moving the tracker backwards.
            ApplicationMirror.objects.filter(pk=req_id, sequence__lt=sequence).update(sequence=sequence,
                service=payload['service'], status=payload['status'], label=payload['label'], updated_at=stamp)
    except IntegrityError:
        return JsonResponse({'error':'event_sequence_conflict'}, status=409)
    response = JsonResponse({'received':True, 'duplicate':not created})
    response['Cache-Control']='no-store'
    return response

@login_required
def tracker(request):
    if not request.user.is_staff:
        return HttpResponseForbidden('Source department staff access required.')
    return render(request, 'source_tracker.html', {'mirrors':ApplicationMirror.objects.order_by('-updated_at')[:100], 'source_name':settings.SOURCE_NAME})
