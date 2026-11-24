"""Versioned common records and bounded declarative workflow contracts."""
import re
from datetime import date
from django.core.exceptions import ValidationError
from django.utils import timezone
from portal.connectors import ExchangeError

ROLES = ['Education Officers', 'Welfare Officers', 'Municipal Reviewers']


def validate_workflow(steps):
    from .adapters import REGISTRY
    if not isinstance(steps, list) or not 2 <= len(steps) <= 10:
        raise ValidationError('A workflow requires 2–10 fetch/review steps.')
    ids, scopes = set(), set()
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get('id'), str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', step['id']):
            raise ValidationError('Each step needs a short unique id.')
        if step['id'] in ids:
            raise ValidationError('Duplicate step id.')
        ids.add(step['id'])
        if step.get('kind') == 'fetch':
            if set(step) != {'id', 'kind', 'connector', 'scope'}:
                raise ValidationError('Fetch steps require id, kind, connector and scope only.')
            connector, scope = step['connector'], step['scope']
            if not isinstance(connector, str) or not isinstance(scope, str):
                raise ValidationError('Connector and scope must be text.')
            adapter = REGISTRY.get(connector)
            if not adapter or scope not in adapter.scopes:
                raise ValidationError('Unknown connector or unsupported scope.')
            key = (connector, scope)
            if key in scopes:
                raise ValidationError('Duplicate document requirement.')
            scopes.add(key)
        elif step.get('kind') == 'review':
            if set(step) != {'id', 'kind', 'role'} or step['role'] not in ROLES:
                raise ValidationError('Review steps require an approved department role.')
        else:
            raise ValidationError('Only fetch and review steps are supported.')
    if steps[0]['kind'] != 'fetch' or steps[-1]['kind'] != 'review':
        raise ValidationError('Start with a document fetch and finish with departmental review.')


def validate_record(record, scope=None, subject=None):
    if not isinstance(record, dict) or record.get('schema_version') != '1.0':
        raise ExchangeError('Unsupported common-record schema version.')
    if record.get('type') not in ['income_certificate', 'residence_certificate', 'household_certificate'] or (scope and record['type'] != scope):
        raise ExchangeError('Unexpected document type.')
    if record.get('verified') is not True:
        raise ExchangeError('The issuing department has not verified this record.')
    for key in ['document_id', 'holder', 'issuer', 'subject_id']:
        if not isinstance(record.get(key), str) or not 0 < len(record[key].strip()) <= 200:
            raise ExchangeError('Invalid document identity or text value.')
    if subject and record['subject_id'] != subject:
        raise ExchangeError('Source identity does not match the reviewed identity link.')
    try:
        issued, expiry = date.fromisoformat(record['issued_on']), date.fromisoformat(record['valid_until'])
    except (KeyError, TypeError, ValueError):
        raise ExchangeError('Invalid certificate dates.')
    if issued > timezone.localdate() or expiry < timezone.localdate() or expiry < issued:
        raise ExchangeError('Certificate expired or its dates are inconsistent.')
    attrs = record.get('attributes')
    if not isinstance(attrs, dict):
        raise ExchangeError('Missing certificate attributes.')
    if record['type'] == 'income_certificate':
        value = attrs.get('annual_income')
        if type(value) is not int or not 0 <= value <= 10**12:
            raise ExchangeError('Invalid annual income.')
    if record['type'] == 'residence_certificate':
        if not isinstance(attrs.get('district'), str) or not 0 < len(attrs['district']) <= 100:
            raise ExchangeError('Invalid residence district.')
    if record['type'] == 'household_certificate':
        if type(attrs.get('members')) is not int or not 1 <= attrs['members'] <= 100:
            raise ExchangeError('Invalid household size.')
    return record
