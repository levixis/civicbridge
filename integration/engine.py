import time
import uuid
from datetime import timedelta
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from portal.crypto import seal
from portal.connectors import ExchangeError
from .models import (ServiceRequest, ShareConsent, FetchTask, DomainEvent, EventDelivery,
                     Notification, ReviewDecision, ConnectorMeasurement, DeadlineBreach)
from .adapters import REGISTRY, provider_targets
from .contracts import validate_record
from .audit import append


def authorised(user, req):
    return user.is_active and (user.pk == req.citizen.user_id or
        (req.current_step and req.current_step['kind'] == 'review' and user.groups.filter(name=req.current_step['role']).exists()))


def active_consent(req, connector, scope):
    return req.consents.filter(connector=connector, scope=scope, revoked_at=None, expires_at__gt=timezone.now()).first()


def emit(req, kind, label):
    event = DomainEvent.objects.create(request=req, kind=kind, sequence=req.events.count()+1, payload={
        'schema_version': '1.0', 'service': req.definition.code, 'version': req.definition.version,
        'status': req.status, 'step': req.step, 'label': label[:180]})
    for target in ['notifications', *provider_targets(req.workflow)]:
        EventDelivery.objects.create(event=event, target=target)
    return event


@transaction.atomic
def submit(actor, citizen, definition, details):
    if actor.pk != citizen.user_id or not actor.is_active or not definition.published:
        raise ExchangeError('This service cannot be submitted by this account.')
    req = ServiceRequest.objects.create(citizen=citizen, definition=definition,
        workflow=definition.workflow, details=details, due_at=timezone.now()+timedelta(hours=definition.sla_hours))
    emit(req, 'request.submitted', 'Application submitted; no document upload required')
    append(actor, 'request.submit', req, f'{definition.code} v{definition.version}')
    return req


def enqueue_current(req):
    if req.terminal:
        return
    step = req.current_step
    if not step:
        req.status, req.completed_at = 'approved', timezone.now()
        req.save()
        emit(req, 'request.approved', 'All configured departmental reviews completed')
        return
    if step['kind'] == 'review':
        req.status = 'review'
        req.save()
        emit(req, 'review.ready', 'Awaiting ' + step['role'])
        return
    consent = active_consent(req, step['connector'], step['scope'])
    if not consent:
        req.status = 'awaiting_consent'
        req.save()
        return
    # Request row is held by every caller. Duplicate triggers reuse one active task.
    FetchTask.objects.get_or_create(request=req, status='queued', step=req.step,
        defaults={'consent_revision': consent.revision})
    req.status = 'processing'
    req.save()


@transaction.atomic
def grant(actor, pk):
    req = ServiceRequest.objects.select_for_update(of=('self',)).get(pk=pk, citizen__user=actor)
    if req.terminal or req.status == 'withdrawn':
        raise ExchangeError('This application has already been decided.')
    if req.consents.filter(revoked_at=None, expires_at__lte=timezone.now()).exists():
        if req.decisions.exists():
            raise ExchangeError('A prior review has expired sharing permissions. Revoke this journey and start a new application.')
        remove_shared(req, 'Expired permissions replaced; records must be fetched again')
    # Repeated grant clicks do not replace live revisions or enqueue duplicate jobs.
    granted = False
    for step in req.workflow:
        if step['kind'] == 'fetch' and not active_consent(req, step['connector'], step['scope']):
            ShareConsent.objects.update_or_create(request=req, connector=step['connector'], scope=step['scope'], defaults={
                'purpose': req.definition.title, 'revision': uuid.uuid4(), 'expires_at':timezone.now()+timedelta(days=7),
                'revoked_at':None, 'granted_at':timezone.now()})
            granted = True
    retry = req.status == 'exchange_failed'
    if req.status in ['awaiting_consent', 'exchange_failed']:
        enqueue_current(req)
    if granted:
        emit(req, 'consent.granted', 'Citizen authorised the listed records for this service for seven days')
        append(actor, 'consent.grant', req, 'Per-provider, per-scope grants; seven-day expiry')
    elif retry and req.status == 'processing':
        emit(req, 'exchange.retried', 'Citizen requested another attempt to collect the records')
        append(actor, 'exchange.retry', req, 'Record collection queued under existing sharing permissions')
    return req


def remove_shared(req, reason):
    req.consents.filter(revoked_at=None).update(revoked_at=timezone.now())
    req.tasks.filter(status__in=['queued', 'running']).update(status='cancelled', lease_until=None, error=reason)
    req.encrypted_records = ''
    if not req.terminal:
        req.status, req.step = 'awaiting_consent', 0
        # Past reviewer decisions remain recorded; a refreshed workflow needs fresh decisions.
        # Restart is blocked after any review: withdraw this request and create another instead.
        if req.decisions.exists():
            req.status = 'withdrawn'
    req.save()
    emit(req, 'consent.revoked', reason)


@transaction.atomic
def revoke(actor, pk):
    req = ServiceRequest.objects.select_for_update(of=('self',)).get(pk=pk, citizen__user=actor)
    remove_shared(req, 'Access revoked; shared records removed')
    append(actor, 'consent.revoke', req, 'Queued work cancelled; decisions retained')


def valid_records(req):
    records = req.records
    for index, step in enumerate(req.workflow[:req.step]):
        if step['kind'] != 'fetch':
            continue
        if not active_consent(req, step['connector'], step['scope']):
            raise ExchangeError('Required sharing consent is no longer active.')
        validate_record(records.get(step['id']), step['scope'])
    return records


@transaction.atomic
def review(actor, pk, decision, note):
    req = ServiceRequest.objects.select_for_update(of=('self',)).select_related('citizen__user', 'definition').get(pk=pk)
    if req.status != 'review' or not req.current_step or not authorised(actor, req) or actor.pk == req.citizen.user_id:
        raise ExchangeError('The current departmental reviewer is required.')
    if decision not in ['approved', 'rejected'] or not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
        raise ExchangeError('Choose an approval/rejection and provide a note.')
    valid_records(req)
    ReviewDecision.objects.create(request=req, step=req.step, actor=actor, decision=decision, note=note)
    append(actor, 'review.'+decision, req, f"Step {req.current_step['id']}")
    if decision == 'rejected':
        req.status, req.completed_at = 'rejected', timezone.now()
        req.save()
        emit(req, 'request.rejected', 'Department rejected the application')
    else:
        emit(req, 'review.approved', 'Department approved this workflow step')
        req.step += 1
        enqueue_current(req)
    return req


def claim(model):
    now, token = timezone.now(), uuid.uuid4()
    eligible = Q(status='queued', run_after__lte=now) | Q(status='running', lease_until__lt=now)
    item = model.objects.filter(eligible).order_by('run_after', 'pk').first()
    if item and model.objects.filter(pk=item.pk).filter(eligible).update(status='running', lease_until=now+timedelta(seconds=60), lease_token=token, attempts=F('attempts')+1):
        item.refresh_from_db()
        return item


def process_fetch(task):
    token = task.lease_token
    with transaction.atomic():
        req = ServiceRequest.objects.select_for_update(of=('self',)).select_related('citizen__user', 'definition').get(pk=task.request_id)
        live = FetchTask.objects.select_for_update().filter(pk=task.pk, status='running', lease_token=token).first()
        if not live:
            return
        step = req.current_step
        consent = active_consent(req, step['connector'], step['scope']) if step and step['kind']=='fetch' else None
        if req.status != 'processing' or req.step != task.step or not consent or consent.revision != task.consent_revision or not req.citizen.user.is_active:
            FetchTask.objects.filter(pk=task.pk).update(status='cancelled', lease_until=None, error='Consent or request changed')
            if req.status == 'processing':
                remove_shared(req, 'Sharing permissions or account changed')
            return
    started, error, record = time.monotonic(), None, None
    try:
        if task.attempts > 4:
            raise ExchangeError('Maximum exchange attempts exceeded.')
        record = validate_record(REGISTRY[step['connector']].fetch(req, consent, task), step['scope'])
    except ExchangeError as e:
        error = e
    except Exception:
        error = ExchangeError('Unexpected connector failure.', True)
    with transaction.atomic():
        req = ServiceRequest.objects.select_for_update(of=('self',)).select_related('citizen__user', 'definition').get(pk=task.request_id)
        live = FetchTask.objects.select_for_update().filter(pk=task.pk, status='running', lease_token=token).first()
        if not live:
            return
        consent = active_consent(req, step['connector'], step['scope'])
        if req.status != 'processing' or req.step != task.step or not consent or consent.revision != task.consent_revision or not req.citizen.user.is_active:
            live.status, live.lease_until, live.error = 'cancelled', None, 'Consent changed during exchange'
            live.save()
            if req.status == 'processing':
                remove_shared(req, 'Sharing permissions changed during exchange')
            return
        ConnectorMeasurement.objects.create(connector=step['connector'], scope=step['scope'], success=error is None,
            elapsed_ms=min(int((time.monotonic()-started)*1000), 2**31-1), error=str(error)[:200] if error else '')
        live.lease_until = None
        if error:
            live.error = str(error)[:200]
            if error.retryable and live.attempts < 4:
                live.status, live.run_after = 'queued', timezone.now()+timedelta(seconds=5*2**live.attempts)
                live.save()
            else:
                live.status = 'failed'
                live.save()
                req.status = 'exchange_failed'
                req.save()
                emit(req, 'exchange.failed', live.error)
            append(None, 'exchange.failed', req, str(error), 'failed')
            return
        records = req.records
        records[step['id']] = record
        req.encrypted_records = seal(records)
        live.status, live.error = 'succeeded', ''
        live.save()
        emit(req, 'exchange.received', 'Validated '+step['scope']+' from '+step['connector'])
        append(None, 'exchange.received', req, step['connector']+' / common schema 1.0')
        req.step += 1
        enqueue_current(req)


def process_delivery(delivery):
    token, error = delivery.lease_token, None
    event = delivery.event
    try:
        if delivery.attempts > 4:
            raise ExchangeError('Maximum delivery attempts exceeded.')
        if delivery.target == 'notifications':
            users = [event.request.citizen.user_id]
            original_step = event.request.workflow[event.payload['step']] if event.payload['step'] < len(event.request.workflow) else None
            if event.kind == 'review.ready' and original_step and original_step['kind']=='review':
                users += list(User.objects.filter(is_active=True, groups__name=original_step['role']).values_list('pk', flat=True))
            if event.kind == 'deadline.breached':
                users += list(User.objects.filter(is_active=True, groups__name='Integration Operators').values_list('pk', flat=True))
            for user_id in set(users):
                Notification.objects.get_or_create(user_id=user_id, event=event, defaults={'title': event.payload['label']})
        else:
            REGISTRY[delivery.target].deliver(event)
    except ExchangeError as e:
        error = e
    except Exception:
        error = ExchangeError('Unexpected event delivery failure.', True)
    with transaction.atomic():
        live = EventDelivery.objects.select_for_update().filter(pk=delivery.pk, status='running', lease_token=token).first()
        if not live:
            return
        live.lease_until, live.error = None, str(error)[:200] if error else ''
        if error and error.retryable and live.attempts < 4:
            live.status, live.run_after = 'queued', timezone.now()+timedelta(seconds=5*2**live.attempts)
        else:
            live.status = 'failed' if error else 'delivered'
        live.save()


def maintain():
    expired_ids = list(ServiceRequest.objects.filter(consents__revoked_at=None, consents__expires_at__lte=timezone.now()).values_list('pk', flat=True).distinct()[:100])
    for pk in expired_ids:
        with transaction.atomic():
            req = ServiceRequest.objects.select_for_update().get(pk=pk)
            if req.consents.filter(revoked_at=None, expires_at__lte=timezone.now()).exists():
                remove_shared(req, 'Consent expired; shared records removed')
                append(None, 'retention.purge', req)
    for pk in list(ServiceRequest.objects.filter(completed_at=None, due_at__lt=timezone.now()).exclude(status='withdrawn').exclude(deadlinebreach__isnull=False).values_list('pk', flat=True)[:100]):
        with transaction.atomic():
            req = ServiceRequest.objects.select_for_update().get(pk=pk)
            _, created = DeadlineBreach.objects.get_or_create(request=req)
            if created:
                emit(req, 'deadline.breached', 'Service deadline exceeded; operator action required')
                append(None, 'deadline.breach', req)


def tick_platform():
    maintain()
    task = claim(FetchTask)
    if task:
        process_fetch(task)
    worked = task is not None
    # Drain several deliveries each tick so status events do not starve behind fetches.
    for _ in range(10):
        delivery = claim(EventDelivery)
        if not delivery:
            break
        process_delivery(delivery)
        worked = True
    return worked
