import json
import time
import os
from urllib.parse import urlparse
import requests


class TransportError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def origin(value, allow_local=False, *, path=''):
    p = urlparse(value)
    if p.username or p.password or p.query or p.fragment or p.path not in (path, path + '/') or not p.hostname:
        raise TransportError('Invalid service origin.')
    trusted = ['127.0.0.1', 'localhost', '::1'] + [h for h in os.environ.get('INTERNAL_HTTP_HOSTS', '').split(',') if h]
    if p.scheme != 'https' and not (allow_local and p.scheme == 'http' and p.hostname in trusted):
        raise TransportError('HTTPS required; local HTTP is restricted to loopback.')
    return value.rstrip('/')


def identity_issuer(value, allow_local=False):
    path = '/identity' if urlparse(value).path in ('/identity', '/identity/') else ''
    return origin(value, allow_local, path=path)


def bounded_request(method, url, **kwargs):
    try:
        with requests.request(method, url, timeout=(3, 8), allow_redirects=False, stream=True, **kwargs) as response:
            body, deadline = bytearray(), time.monotonic() + 20
            for chunk in response.iter_content(4096):
                body.extend(chunk)
                if len(body) > 65536:
                    raise TransportError('Response exceeds 64 KiB.')
                if time.monotonic() > deadline:
                    raise TransportError('Response exceeded time limit.', True)
            if not 200 <= response.status_code < 300:
                raise TransportError(f'Service HTTP {response.status_code}.', response.status_code in [429, 500, 502, 503, 504])
            return bytes(body), response.headers.get('Content-Type', '').split(';')[0].lower()
    except (requests.Timeout, requests.ConnectionError):
        raise TransportError('Service temporarily unreachable.', True)
    except requests.RequestException:
        raise TransportError('Service request failed.', True)


def get_json(url, **kwargs):
    body, kind = bounded_request('GET', url, **kwargs)
    if kind != 'application/json':
        raise TransportError('Expected JSON response.')
    try:
        return json.loads(body)
    except ValueError:
        raise TransportError('Invalid JSON response.')
