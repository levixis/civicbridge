"""Allowlisted provider contracts. New adapters implement this same interface."""
import csv
import io
import json
import time
from dataclasses import dataclass
from urllib.parse import quote
from django.conf import settings
from django.core import signing
from portal.models import IdentityLink
from portal.connectors import ExchangeError
from common.http import origin, bounded_request, TransportError
from .contracts import validate_record


@dataclass(frozen=True)
class ContractAdapter:
    code: str
    department: str
    url_setting: str
    token_setting: str
    scopes: dict
    format: str = 'json'

    def base(self):
        return origin(getattr(settings, self.url_setting), settings.ALLOW_LOCAL_HTTP)

    def fetch(self, request, consent, task):
        link = IdentityLink.objects.filter(citizen=request.citizen, department=self.department).first()
        if not link:
            raise ExchangeError(f'A reviewed {self.department} identity link is required.')
        grant = {'resident': link.external_id, 'application': str(request.pk),
                 'revision': str(consent.revision), 'scope': consent.scope,
                 'purpose': consent.purpose, 'audience': self.department,
                 'expires': consent.expires_at.isoformat()}
        headers = {'Authorization': 'Bearer ' + getattr(settings, self.token_setting),
                   'X-Consent-Grant': signing.dumps(grant, key=settings.GRANT_SIGNING_KEY, salt='civicbridge.exchange.v1'),
                   'X-Request-ID': str(task.pk)}
        path = self.scopes[consent.scope]['path'].format(subject=quote(link.external_id, safe=''))
        try:
            body, content_type = bounded_request('GET', self.base() + path, headers=headers)
            if self.format == 'csv':
                if content_type != 'text/csv':
                    raise ExchangeError('Expected the registered legacy CSV contract.')
                rows = list(csv.DictReader(io.StringIO(body.decode('utf-8'))))
                if len(rows) != 1:
                    raise ExchangeError('Legacy CSV must contain exactly one record.')
                raw = rows[0]
            else:
                if content_type != 'application/json':
                    raise ExchangeError('Expected the registered JSON contract.')
                raw = json.loads(body)
            record = self.map_record(raw, consent.scope)
            return validate_record(record, consent.scope, link.external_id)
        except TransportError as e:
            raise ExchangeError(str(e), e.retryable) from e
        except (ValueError, TypeError, KeyError, UnicodeError) as e:
            raise ExchangeError('Source data does not match the registered contract.') from e

    def map_record(self, raw, scope):
        if not isinstance(raw, dict):
            raise ExchangeError('Expected a source record object.')
        mapping = self.scopes[scope]['map']
        value = {k: raw[v] for k, v in mapping.items()}
        attrs = {}
        for canonical, source in self.scopes[scope]['attributes'].items():
            data = raw[source]
            if canonical in ['annual_income', 'members'] and self.format == 'csv':
                data = int(data)
            attrs[canonical] = data
        if self.format == 'csv':
            if value['verified'] not in ['true', 'false']:
                raise ExchangeError('Invalid legacy verification flag.')
            value['verified'] = value['verified'] == 'true'
        return {'schema_version': '1.0', 'type': scope, 'issuer': self.department,
                'attributes': attrs, **value}

    def health(self):
        started = time.monotonic()
        try:
            bounded_request('GET', self.base() + '/health/')
            return {'name': self.code, 'status': 'Available', 'elapsed_ms': int((time.monotonic()-started)*1000), 'mode': self.format.upper() + ' → common record v1.0'}
        except TransportError:
            return {'name': self.code, 'status': 'Unavailable', 'elapsed_ms': None, 'mode': self.format.upper() + ' → common record v1.0'}

    def deliver(self, event):
        try:
            bounded_request('POST', self.base() + '/api/v1/events/',
                            headers={'Authorization': 'Bearer ' + getattr(settings, self.token_setting)},
                            json={'id': str(event.pk), 'kind': event.kind, 'request': str(event.request_id), 'sequence': event.sequence,
                                  'payload': event.payload, 'created_at': event.created_at.isoformat()})
        except TransportError as e:
            raise ExchangeError(str(e), e.retryable) from e


REGISTRY = {
    'revenue': ContractAdapter('revenue', 'revenue', 'REVENUE_API_URL', 'REVENUE_API_TOKEN', {
        'income_certificate': {'path': '/api/v1/income/{subject}/',
            'map': {'subject_id':'resident_number', 'document_id':'certificate_number', 'holder':'resident_name', 'issued_on':'issue_date', 'valid_until':'expiry_date', 'verified':'verified'},
            'attributes': {'annual_income':'yearly_income', 'district':'district_name'}}}),
    'municipality': ContractAdapter('municipality', 'municipality', 'MUNICIPAL_API_URL', 'MUNICIPAL_API_TOKEN', {
        'residence_certificate': {'path': '/api/v1/residence/{subject}/',
            'map': {'subject_id':'person_key', 'document_id':'record_no', 'holder':'full_name', 'issued_on':'issued', 'valid_until':'expires', 'verified':'confirmed'},
            'attributes': {'district':'district', 'ward':'ward'}}}),
    'municipality_legacy': ContractAdapter('municipality_legacy', 'municipality', 'MUNICIPAL_API_URL', 'MUNICIPAL_API_TOKEN', {
        'household_certificate': {'path': '/api/v1/legacy/household/{subject}/',
            'map': {'subject_id':'PERSON_KEY', 'document_id':'RECORD_NO', 'holder':'FULL_NAME', 'issued_on':'ISSUED', 'valid_until':'EXPIRES', 'verified':'CONFIRMED'},
            'attributes': {'members':'MEMBERS'}}}, 'csv'),
}

def provider_targets(workflow):
    # A provider with several adapters receives each event once.
    targets = {}
    for step in workflow:
        if step['kind'] == 'fetch':
            adapter = REGISTRY[step['connector']]
            targets.setdefault(adapter.department, adapter.code)
    return list(targets.values())
