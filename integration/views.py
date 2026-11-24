from collections import defaultdict
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction,IntegrityError
from django.db.models import Avg,Count
from django.http import HttpResponseForbidden,JsonResponse
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST,require_GET
from portal.models import Citizen,IdentityLink,Application
from portal.permissions import is_operator, is_portal_staff
from portal.connectors import ExchangeError
from portal.services import invalidate_revenue_link
from .models import ServiceDefinition,ServiceRequest,Notification,IdentityClaim,EventDelivery,ConnectorMeasurement,AuditHead,IntegrityAudit
from .forms import ServiceForm,RequestForm,ConsentForm,ReviewForm,ClaimForm,ClaimReviewForm
from . import engine
from .adapters import REGISTRY
from .audit import append
from .contracts import ROLES
from .presentation import REQUEST_STATUSES, describe_service, describe_steps

def private(response):
    response['Cache-Control']='private, no-store'
    return response

def can_view(user, req, roles=None):
    if not user.is_active:
        return False
    if req.citizen.user_id == user.pk:
        return True
    if roles is None:
        roles = set(user.groups.values_list('name', flat=True))
    return any(step['kind'] == 'review' and step['role'] in roles for step in req.workflow)

def accessible(user, pk):
    req=get_object_or_404(ServiceRequest.objects.select_related('citizen__user','definition'),pk=pk)
    if not can_view(user,req):
        from django.http import Http404
        raise Http404()
    return req

def catalog(request):
    services = {}
    for definition in ServiceDefinition.objects.filter(published=True).order_by('code', '-version'):
        if definition.code not in services:
            steps = list(describe_steps(definition.workflow))
            services[definition.code] = {
                'definition': definition,
                'description': describe_service(definition),
                'records': [step for step in steps if step['kind'] == 'fetch'],
                'reviewers': dict.fromkeys(step['label'] for step in steps if step['kind'] == 'review'),
            }
    can_apply = not request.user.is_authenticated or (
        hasattr(request.user, 'citizen') and not is_portal_staff(request.user)
    )
    return private(render(request, 'platform/catalog.html', {'services': services.values(), 'can_apply': can_apply}))

@login_required
def create(request, pk):
    definition=get_object_or_404(ServiceDefinition,pk=pk,published=True)
    citizen = getattr(request.user, 'citizen', None)
    if citizen is None or is_portal_staff(request.user):
        messages.info(request, 'Sign in with a citizen account to start an application.')
        return redirect('platform_workspace')
    form=RequestForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        req=engine.submit(request.user,citizen,definition,form.cleaned_data)
        return redirect('platform_detail',pk=req.pk)
    return private(render(request, 'platform/apply.html', {
        'form': form, 'definition': definition, 'description': describe_service(definition),
    }))

@login_required
def workspace(request, staff=False):
    citizen = None if staff or is_portal_staff(request.user) else getattr(request.user, 'citizen', None)
    requests = ServiceRequest.objects.select_related('definition','citizen__user').order_by('-created_at')
    if citizen:
        requests = requests.filter(citizen=citizen)
    else:
        roles = set(request.user.groups.values_list('name', flat=True))
        if not roles.intersection(ROLES) and is_operator(request.user):
            return redirect('platform_monitor')
        requests = [req for req in requests if can_view(request.user, req, roles)]
        for item in requests:
            step = item.current_step
            item.ready_for_review = item.status == 'review' and step is not None and step.get('role') in roles
        requests.sort(key=lambda item: not item.ready_for_review)
    legacy=Application.objects.filter(citizen=citizen).order_by('-created_at') if citizen else []
    page = Paginator(requests, 25).get_page(request.GET.get('page'))
    for item in page:
        item.status_label = 'Ready for your decision' if getattr(item, 'ready_for_review', False) else REQUEST_STATUSES.get(item.status, item.status)
    return private(render(request,'platform/workspace.html',{'requests':page,'legacy':legacy,'citizen':citizen}))

@login_required
def detail(request, pk):
    req=accessible(request.user,pk)
    try: records=engine.valid_records(req)
    except ExchangeError: records={}
    steps = list(describe_steps(req.workflow))
    owner = req.citizen.user_id == request.user.pk
    permissions = {(item.connector, item.scope): item for item in req.consents.all()}
    expired = any(item.revoked_at is None and not item.active for item in permissions.values())
    linked = set(req.citizen.identitylink_set.values_list('department', flat=True)) if owner else set()
    requirements = [step for step in steps if step['kind'] == 'fetch']
    for step in requirements:
        step['permission'] = permissions.get((step['connector'], step['scope']))
        step['record'] = records.get(step['id'])
    missing_links = dict.fromkeys(step['source'] for step in steps[req.step:]
                                 if step['kind'] == 'fetch' and step['department'] not in linked) if owner else {}
    return private(render(request, 'platform/detail.html', {
        'req': req, 'status_label': REQUEST_STATUSES.get(req.status, req.status), 'steps': steps,
        'has_records': bool(records),
        'requirements': requirements, 'owner': owner, 'missing_links': missing_links,
        'can_grant': owner and not req.terminal and req.status != 'withdrawn' and (
            req.status in ('awaiting_consent', 'exchange_failed') or expired),
        'can_revoke': owner and any(item.revoked_at is None for item in permissions.values()),
        'can_review': not owner and req.status == 'review' and engine.authorised(request.user, req),
        'consent_form': ConsentForm(), 'review_form': ReviewForm(),
        'events': req.events.all(), 'decisions': req.decisions.select_related('actor'),
    }))

@login_required
@require_POST
def grant(request,pk):
    get_object_or_404(ServiceRequest,pk=pk,citizen__user=request.user)
    if not ConsentForm(request.POST).is_valid():
        messages.error(request,'Tick the sharing consent checkbox.')
    else:
        try:
            engine.grant(request.user,pk);messages.success(request,'Sharing permission saved.')
        except ExchangeError as e: messages.error(request,str(e))
    return redirect('platform_detail',pk=pk)

@login_required
@require_POST
def revoke(request,pk):
    get_object_or_404(ServiceRequest,pk=pk,citizen__user=request.user)
    engine.revoke(request.user,pk)
    messages.success(request,'Access revoked and shared copies removed. Completed decisions remain recorded.')
    return redirect('platform_detail',pk=pk)

@login_required
@require_POST
def review(request,pk):
    accessible(request.user,pk)
    form=ReviewForm(request.POST)
    if form.is_valid():
        try: engine.review(request.user,pk,**form.cleaned_data);messages.success(request,'Departmental decision recorded.')
        except ExchangeError as e: messages.error(request,str(e))
    else: messages.error(request,'A decision and a note of at most 500 characters are required.')
    return redirect('platform_detail',pk=pk)

@login_required
@require_GET
def tracker(request,pk):
    req=accessible(request.user,pk)
    return private(JsonResponse({'reference':str(req.pk),'status':req.status,'step':req.step,'due_at':req.due_at.isoformat(),'overdue':req.overdue,
        'events':list(req.events.values('sequence','kind','payload','created_at'))}))

@login_required
def notifications(request):
    items=Notification.objects.filter(user=request.user).select_related('event__request__definition').order_by('-created_at')
    return private(render(request,'platform/notifications.html',{'items':Paginator(items,30).get_page(request.GET.get('page'))}))

@login_required
@require_POST
def read_notification(request,pk):
    item=get_object_or_404(Notification,pk=pk,user=request.user)
    item.read_at=timezone.now();item.save(update_fields=['read_at'])
    return redirect('platform_notifications')

@login_required
def configure(request,pk=None):
    if not is_operator(request.user): return HttpResponseForbidden('Integration operator access required.')
    original=get_object_or_404(ServiceDefinition,pk=pk) if pk else None
    initial={}
    if original:
        initial={field:getattr(original,field) for field in ['code','title','description','department','sla_hours','workflow']}
        initial['version']=ServiceDefinition.objects.filter(code=original.code).order_by('-version').first().version+1
    form=ServiceForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            service=form.save()
            append(request.user,'workflow.publish' if service.published else 'workflow.draft',detail=str(service))
        messages.success(request,'New workflow version saved. Existing applications retain their original steps.')
        return redirect('platform_configure')
    return private(render(request,'platform/configure.html',{'form':form,'definitions':ServiceDefinition.objects.all(),'adapters':REGISTRY.values()}))

@login_required
def identities(request):
    citizen=get_object_or_404(Citizen,user=request.user)
    form=ClaimForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                item=IdentityClaim.objects.create(citizen=citizen,**form.cleaned_data)
                append(request.user,'identity.claim',detail=f'{item.department} / claim {item.pk}')
            messages.success(request, 'Link request sent. A CivicBridge operator will review it.')
            return redirect('platform_identities')
        except IntegrityError: form.add_error(None, 'A request for this department is pending. Withdraw it below to enter a different ID.')
    return private(render(request,'platform/identities.html',{'form':form,'links':citizen.identitylink_set.all(),'claims':citizen.identityclaim_set.order_by('-created_at'),'citizen':citizen}))


@login_required
@require_POST
def withdraw_claim(request, pk):
    owned_claims = IdentityClaim.objects.filter(citizen__user=request.user)
    claim = get_object_or_404(owned_claims, pk=pk)
    with transaction.atomic():
        changed = owned_claims.filter(pk=claim.pk, status='pending').update(status='withdrawn')
        if changed:
            append(request.user, 'identity.withdraw', detail=f'{claim.department} / claim {claim.pk}')
    if changed:
        messages.success(request, 'Link request withdrawn. You can now submit the correct department ID.')
    else:
        messages.info(request, 'Only pending link requests can be withdrawn.')
    return redirect('platform_identities')


@login_required
def claims(request,pk=None):
    if not is_operator(request.user): return HttpResponseForbidden('Integration operator access required.')
    item=get_object_or_404(IdentityClaim,pk=pk) if pk else None
    form=ClaimReviewForm(request.POST or None)
    if item and request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                Citizen.objects.select_for_update(no_key=True).get(pk=item.citizen_id)
                item=IdentityClaim.objects.select_for_update().get(pk=item.pk)
                if item.status!='pending': raise ExchangeError('This request is no longer pending.')
                if form.cleaned_data['decision']=='approved':
                    if IdentityLink.objects.filter(department=item.department,external_id=item.external_id).exclude(citizen=item.citizen).exists():
                        raise ExchangeError('Identity conflict: this external identifier belongs to another citizen. Do not merge accounts without a separate verified process.')
                    old=IdentityLink.objects.filter(citizen=item.citizen,department=item.department).first()
                    changed=old and old.external_id!=item.external_id
                    IdentityLink.objects.update_or_create(citizen=item.citizen,department=item.department,defaults={'external_id':item.external_id})
                    if changed:
                        for req in ServiceRequest.objects.select_for_update().filter(citizen=item.citizen):
                            if any(s['kind']=='fetch' and REGISTRY[s['connector']].department==item.department for s in req.workflow):
                                engine.remove_shared(req,'Identity mapping changed; prior grants and copies removed')
                        if item.department == 'revenue':
                            invalidate_revenue_link(request.user, item.citizen)
                item.status=form.cleaned_data['decision'];item.evidence=form.cleaned_data['evidence'];item.note=form.cleaned_data['note']
                item.reviewer=request.user;item.reviewed_at=timezone.now();item.save()
                append(request.user,'identity.'+item.status,detail=f'Claim {item.pk}; evidence {item.evidence}')
            messages.success(request, f'Identity request {item.status}.')
            return redirect('platform_claims')
        except (ExchangeError,IntegrityError) as e: form.add_error(None,str(e) if isinstance(e,ExchangeError) else 'This identifier conflicts with an existing reviewed link.')
    pending = IdentityClaim.objects.filter(status='pending').select_related('citizen__user').order_by('created_at', 'pk')
    return private(render(request, 'platform/claims.html', {'item': item, 'form': form, 'claims': pending}))

@login_required
def monitor(request):
    if not is_operator(request.user): return HttpResponseForbidden('Integration operator access required.')
    stats=[]
    for definition in ServiceDefinition.objects.order_by('code','version'):
        all_requests=ServiceRequest.objects.filter(definition=definition)
        completed=list(all_requests.exclude(completed_at=None))
        stats.append({'definition':definition,'total':all_requests.count(),'completed':len(completed),
            'on_time':sum(r.completed_at<=r.due_at for r in completed),
            'mean_hours':round(sum((r.completed_at-r.created_at).total_seconds()/3600 for r in completed)/len(completed),2) if completed else None})
    measurements=ConnectorMeasurement.objects.values('connector').annotate(calls=Count('id'),mean_ms=Avg('elapsed_ms'))
    return private(render(request,'platform/monitor.html',{'stats':stats,'connectors':[a.health() for a in REGISTRY.values()],
        'pending_claims': IdentityClaim.objects.filter(status='pending').count(),
        'measurements':measurements,'failures':EventDelivery.objects.filter(status='failed').select_related('event__request')[:50],
        'overdue':ServiceRequest.objects.filter(completed_at=None,due_at__lt=timezone.now()).exclude(status='withdrawn').select_related('definition')[:50],
        'head':AuditHead.objects.filter(pk=1).first(),'audits':IntegrityAudit.objects.order_by('-sequence')[:30]}))

@login_required
@require_POST
def retry_delivery(request,pk):
    if not is_operator(request.user): return HttpResponseForbidden('Integration operator access required.')
    with transaction.atomic():
        item=get_object_or_404(EventDelivery.objects.select_for_update(),pk=pk,status='failed')
        item.status,item.attempts,item.run_after,item.lease_token,item.lease_until='queued',0,timezone.now(),None,None
        item.save()
        append(request.user,'event.retry',item.event.request,'Delivery '+str(item.pk))
    return redirect('platform_monitor')
