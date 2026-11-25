import os
from pathlib import Path
from urllib.parse import urlsplit
from .demo import demo_subject

def configure(namespace, root, client, port):
    namespace['ALLOW_LOCAL_HTTP'] = os.environ.get('ALLOW_LOCAL_HTTP', '0') == '1'
    namespace['SSO_ISSUER'] = os.environ.get('SSO_ISSUER', 'http://127.0.0.1:8003')
    namespace['SSO_BACKCHANNEL_URL'] = os.environ.get('SSO_BACKCHANNEL_URL', namespace['SSO_ISSUER'])
    namespace['SSO_CLIENT_ID'] = client
    namespace['SSO_CLIENT_SECRET'] = os.environ['SSO_' + client.upper() + '_SECRET']
    namespace['SSO_REDIRECT_URI'] = os.environ.get('SSO_' + client.upper() + '_REDIRECT', f'http://127.0.0.1:{port}/sso/callback/')
    callback_path = urlsplit(namespace['SSO_REDIRECT_URI']).path
    mount_path = callback_path.removesuffix('/sso/callback/') if callback_path.endswith('/sso/callback/') else ''
    namespace['SSO_HOME'] = '/services/workspace/' if client == 'portal' else mount_path + '/'
    if client == 'portal':
        # Explicit local demo subjects identify each source's own workspace.
        namespace['SSO_DEPARTMENT_ROUTES'] = {}
        for department, source_port in [('revenue', 8001), ('municipality', 8002)]:
            callback = os.environ.get(
                'SSO_' + department.upper() + '_REDIRECT',
                f'http://127.0.0.1:{source_port}/sso/callback/',
            )
            url = urlsplit(callback)
            prefix = url.path.removesuffix('/sso/callback/') if url.path.endswith('/sso/callback/') else ''
            destination = url._replace(path=prefix + '/sso/login/', query='', fragment='').geturl()
            namespace['SSO_DEPARTMENT_ROUTES'][str(demo_subject(department))] = destination
    namespace['TEMPLATES'][0]['DIRS'].append(Path(root) / 'templates' / 'shared')
