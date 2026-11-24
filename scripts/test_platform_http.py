"""Five-process integration: isolated databases, real HTTP, no government calls."""
import os,secrets,socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.parse import urlparse,parse_qs,urljoin
import requests
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parent.parent

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]

def command(args,folder,env):
    result=subprocess.run([sys.executable,*args],cwd=ROOT/folder,env=env,capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr[-4000:])
    return result.stdout

def wait_ready(base,process):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Test service exited')
        try:
            if requests.get(base+'/health/',timeout=1).status_code==200:return
        except requests.RequestException:pass
        time.sleep(.2)
    raise RuntimeError('Service did not become ready')

def post(session,base,path,data,cookie='csrftoken'):
    session.get(base+path,timeout=5)
    token=session.cookies.get(cookie)
    response=session.post(base+path,data=data|{'csrfmiddlewaretoken':token},headers={'Referer':base+path},allow_redirects=False,timeout=10)
    assert response.status_code==302,(path,response.status_code,response.text[:300])
    return response

def sso_login(session,rp,idp,username,password,entry='/sso/login/'):
    response=session.get(rp+entry,timeout=10)
    page = urlparse(response.url)
    if page.netloc == urlparse(idp).netloc and page.path in ('/accounts/login/', '/authorize/'):
        path = page.path + '?' + page.query
        login_data = {'username': username, 'password': password}
        if page.path == '/accounts/login/':
            login_data['next'] = parse_qs(page.query)['next'][0]
        result=post(session,idp,path,login_data,'identity_csrftoken')
        response=session.get(urljoin(idp, result.headers['Location']),timeout=10)
    assert response.status_code==200,(response.url,response.status_code,response.text[:200])
    assert '/accounts/login/' not in response.url,response.url
    return response

def wait_status(session,base,pk,wanted,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        item=session.get(base+'/services/api/requests/'+str(pk)+'/',timeout=5).json()
        if item['status']==wanted:return item
        if item['status']=='exchange_failed':raise AssertionError(item)
        time.sleep(.2)
    raise AssertionError('Status did not become '+wanted)

def main():
    processes=[]
    with tempfile.TemporaryDirectory(prefix='civicbridge-platform-') as temp:
        env=os.environ.copy();env.update({k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None})
        for key in ['POSTGRES_HOST','REVENUE_POSTGRES_HOST','MUNICIPAL_POSTGRES_HOST','DJANGO_SETTINGS_MODULE','SSO_BACKCHANNEL_URL']:
            env.pop(key,None)
        p0,p1,p2,p3=[port() for _ in range(4)]
        portal,revenue,municipal,idp=[f'http://127.0.0.1:{p}' for p in [p0,p1,p2,p3]]
        env.update({'DJANGO_DEBUG':'1','ALLOW_LOCAL_HTTP':'1','SQLITE_PATH':temp+'/portal.sqlite3','REVENUE_SQLITE_PATH':temp+'/revenue.sqlite3',
            'MUNICIPAL_SQLITE_PATH':temp+'/municipal.sqlite3','IDENTITY_SQLITE_PATH':temp+'/identity.sqlite3','REVENUE_API_URL':revenue,'MUNICIPAL_API_URL':municipal,
            'SSO_ISSUER':idp,'SSO_PORTAL_REDIRECT':portal+'/sso/callback/','SSO_REVENUE_REDIRECT':revenue+'/sso/callback/','SSO_MUNICIPALITY_REDIRECT':municipal+'/sso/callback/',
            'DJANGO_ALLOWED_HOSTS':'127.0.0.1,localhost','REVENUE_ALLOWED_HOSTS':'127.0.0.1,localhost','MUNICIPAL_ALLOWED_HOSTS':'127.0.0.1,localhost','IDENTITY_ALLOWED_HOSTS':'127.0.0.1,localhost'})
        folders=['','revenue_service','municipal_service','identity_service']
        for folder in folders:command(['manage.py','migrate','--noinput'],folder,env)
        for folder,seed in [('', 'seed_demo'),('revenue_service','seed_revenue'),('municipal_service','seed_municipal'),('identity_service','seed_identity'),('','seed_platform')]:
            command(['manage.py',seed],folder,env)
        password=secrets.token_urlsafe(20)
        command(['manage.py','shell','-c',"from django.contrib.auth.models import User\nfor u in User.objects.all():\n u.set_password("+repr(password)+"); u.save()"],'identity_service',env)
        os.environ.update(env);os.environ['DJANGO_SETTINGS_MODULE']='config.settings';sys.path.insert(0,str(ROOT))
        import django;django.setup()
        from integration.models import ServiceRequest,ServiceDefinition,EventDelivery,Notification,FetchTask
        from integration.audit import verify
        logfiles=[]
        try:
            for folder,p in zip(folders,[p0,p1,p2,p3]):
                output=open(Path(temp)/(folder or 'portal'), 'w');logfiles.append(output)
                proc=subprocess.Popen([sys.executable,'manage.py','runserver',f'127.0.0.1:{p}','--noreload'],cwd=ROOT/folder,env=env,stdout=output,stderr=output)
                processes.append(proc);wait_ready(f'http://127.0.0.1:{p}',proc)
            service=ServiceDefinition.objects.get(code='housing-assistance',version=1)
            apply_path=f'/services/new/{service.pk}/'
            citizen=requests.Session()
            catalog=citizen.get(portal+'/services/',timeout=5)
            assert catalog.status_code==200 and apply_path in catalog.text and 'Household record' in catalog.text
            login_page=citizen.get(portal+apply_path,timeout=5)
            assert 'Continue with shared sign-in' in login_page.text
            sso_entry='/sso/login/?next='+requests.utils.quote(apply_path,safe='')
            assert sso_entry in login_page.text
            application=sso_login(citizen,portal,idp,'citizen@civicbridge.test',password,entry=sso_entry)
            assert application.url==portal+apply_path and 'Submit application' in application.text
            post(citizen,portal,apply_path,{'description':'Fictional HTTP housing test'})
            pk=ServiceRequest.objects.get(definition=service).pk
            detail_path=f'/services/requests/{pk}/'
            sharing=citizen.get(portal+detail_path,timeout=5)
            assert 'Give permission to share records' in sharing.text and 'Allow sharing' in sharing.text
            post(citizen,portal,detail_path+'consent/',{'agree':'on'})
            post(citizen,portal,detail_path+'consent/',{'agree':'on'})
            assert FetchTask.objects.filter(request_id=pk,status='queued').count()==1
            workerlog=open(Path(temp)/'worker','w');logfiles.append(workerlog)
            worker=subprocess.Popen([sys.executable,'manage.py','run_exchange_worker'],cwd=ROOT,env=env,stdout=workerlog,stderr=workerlog);processes.append(worker)
            wait_status(citizen,portal,pk,'review')
            req=ServiceRequest.objects.get(pk=pk)
            assert set(req.records)=={'income','residence','household'}
            assert 'Aarav' not in req.encrypted_records
            print('PASS: durable queue; three JSON/CSV records fetched by real HTTP and encrypted.')
            welfare=requests.Session();welfare_workspace=sso_login(welfare,portal,idp,'welfare',password,entry='/staff/sign-in/welfare/')
            assert welfare_workspace.url == portal+'/staff/'
            open_application = f'href="{detail_path}">Open application</a>'
            assert open_application in welfare_workspace.text
            review=welfare.get(portal+detail_path,timeout=5)
            assert 'Record your decision' in review.text and 'from CSV to common record format 1.0' in review.text
            post(welfare,portal,detail_path+'review/',{'decision':'approved','note':'Reviewed fictional records'})
            wait_status(citizen,portal,pk,'approved')
            approval=citizen.get(portal+detail_path,timeout=5)
            assert 'Approved' in approval.text and 'Reviewed fictional records' in approval.text
            print('PASS: public catalog, shared sign-in return, consent screen and visible Welfare decision.')
            deadline=time.monotonic()+20
            while time.monotonic()<deadline and EventDelivery.objects.exclude(status='delivered').exists():time.sleep(.2)
            assert not EventDelivery.objects.exclude(status='delivered').exists()
            assert Notification.objects.filter(user__username='citizen').exists()
            welfare_inbox = welfare.get(portal+'/services/notifications/',timeout=5)
            assert open_application in welfare_inbox.text and str(pk)[:8] in welfare_inbox.text
            for folder in ['revenue_service','municipal_service']:
                command(['manage.py','shell','-c',"from source_bridge.models import ApplicationMirror\nm=ApplicationMirror.objects.get(request_id='"+str(pk)+"')\nassert m.status=='approved',m.status"],folder,env)
            print('PASS: durable notifications and authenticated events; both independent department trackers show approved.')
            revenue_staff=requests.Session();sso_login(revenue_staff,revenue,idp,'revenue',password)
            assert revenue_staff.get(revenue+'/tracker/',timeout=5).status_code==200
            routed = revenue_staff.get(portal+'/sso/login/',timeout=10)
            assert routed.status_code == 200 and routed.url == revenue+'/'
            assert revenue_staff.get(revenue+'/sso/login/',timeout=10).status_code==200
            from django.contrib.auth.models import User
            before = User.objects.count()
            for department, registry in [('revenue', revenue), ('municipality', municipal)]:
                staff = requests.Session()
                page = sso_login(staff, portal, idp, department, password, entry='/staff/sign-in/' + department + '/')
                assert page.url == registry+'/', page.url
                assert staff.get(registry+'/tracker/', timeout=5).status_code == 200
            assert User.objects.count() == before
            print('PASS: departmental identities entering through the portal reach their own registry without creating citizen accounts.')
            # Same identity session signs into another RP with no second credential prompt.
            assert citizen.get(municipal+'/sso/login/',timeout=10).status_code==400
            assert citizen.get(portal+'/services/requests/'+str(pk)+'/',timeout=5).status_code==200
            outsider=requests.Session();assert outsider.get(portal+'/services/api/requests/'+str(pk)+'/',allow_redirects=False,timeout=5).status_code==302
            print('PASS: real authorization-code/PKCE sign-in; unprovisioned identity cannot become departmental staff.')
            post(citizen,portal,f'/services/requests/{pk}/revoke/',{})
            req.refresh_from_db();assert req.status=='approved' and req.encrypted_records==''
            assert verify()[0]
            print('PASS: revocation removes shared records, retains the decision, and audit-chain verification passes.')
            post(citizen,portal,'/accounts/logout/',{})
            sign_in = citizen.get(portal+'/sso/login/',timeout=10)
            assert 'Email or username' in sign_in.text
            switched = sso_login(citizen,portal,idp,'welfare@civicbridge.test',password)
            assert 'Review workspace' in switched.text and '>welfare</span>' in switched.text
            assert citizen.get(portal+detail_path,timeout=5).status_code == 200
            switched = sso_login(citizen,portal,idp,'citizen',password,entry='/sso/login/?prompt=login')
            assert 'My applications' in switched.text and '>citizen</span>' in switched.text
            print('PASS: sign in by email, switch from citizen to welfare by email, then switch back by username.')
        except Exception:
            for file in logfiles:file.flush()
            for folder in ['portal','revenue_service','municipal_service','identity_service','worker']:
                path=Path(temp)/folder
                if path.exists():print('Test diagnostics '+folder+':\n'+path.read_text()[-2500:])
            raise
        finally:
            for proc in processes:
                if proc.poll() is None:proc.terminate()
            for proc in processes:
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            for file in logfiles:file.close()
if __name__=='__main__':main()
