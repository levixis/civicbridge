"""Run the supported local verification with the active virtual-environment Python."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
ENV=os.environ.copy();ENV.pop('DJANGO_SETTINGS_MODULE',None)
ENV.update({'POSTGRES_HOST':'','REVENUE_POSTGRES_HOST':'','MUNICIPAL_POSTGRES_HOST':'',
            'DJANGO_DEBUG':'1','ALLOW_LOCAL_HTTP':'1','REVENUE_API_URL':'http://127.0.0.1:8001','MUNICIPAL_API_URL':'http://127.0.0.1:8002'})
subprocess.run([sys.executable,str(ROOT/'scripts/init_env.py')],cwd=ROOT,env=ENV,check=True)
components=[('', ['portal','integration','federation']),('revenue_service',['registry','source_bridge','federation']),('municipal_service',['municipal','source_bridge','federation']),('identity_service',['identity'])]
for folder,labels in components:
    for args in [['collectstatic','--noinput'],['check'],['makemigrations','--check','--dry-run'],['test',*labels]]:
        subprocess.run([sys.executable,'manage.py',*args],cwd=ROOT/folder,env=ENV,check=True)
for script in ['test_http_integration.py','test_platform_http.py']:
    subprocess.run([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,env=ENV,check=True)
print('All local checks passed. No government request or online deployment was performed.')
