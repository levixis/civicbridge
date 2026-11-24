"""Create/upgrade local secrets without replacing existing keys or passwords."""
import os
import secrets
from pathlib import Path
from dotenv import dotenv_values
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
ROOT=Path(__file__).resolve().parent.parent
path=ROOT/'.env'
existing=dotenv_values(path) if path.exists() else {}
defaults={
 'DJANGO_DEBUG':'1','SANDBOX_ENABLED':'1','ALLOW_LOCAL_HTTP':'1',
 'DJANGO_SECRET_KEY':secrets.token_urlsafe(48),'REVENUE_DJANGO_SECRET_KEY':secrets.token_urlsafe(48),
 'MUNICIPAL_DJANGO_SECRET_KEY':secrets.token_urlsafe(48),'IDENTITY_DJANGO_SECRET_KEY':secrets.token_urlsafe(48),
 'DOCUMENT_ENCRYPTION_KEY':Fernet.generate_key().decode(),'GRANT_SIGNING_KEY':secrets.token_urlsafe(48),
 'AUDIT_CHAIN_KEY':secrets.token_urlsafe(48),'REVENUE_API_TOKEN':secrets.token_urlsafe(48),
 'MUNICIPAL_API_TOKEN':secrets.token_urlsafe(48),'REVENUE_API_URL':'http://127.0.0.1:8001',
 'MUNICIPAL_API_URL':'http://127.0.0.1:8002','SSO_ISSUER':'http://127.0.0.1:8003',
 'DJANGO_ALLOWED_HOSTS':'localhost,127.0.0.1','REVENUE_ALLOWED_HOSTS':'localhost,127.0.0.1,revenue',
 'MUNICIPAL_ALLOWED_HOSTS':'localhost,127.0.0.1','IDENTITY_ALLOWED_HOSTS':'localhost,127.0.0.1',
 'POSTGRES_USER':'civicbridge','POSTGRES_PASSWORD':secrets.token_urlsafe(32),
 'REVENUE_POSTGRES_USER':'revenue','REVENUE_POSTGRES_PASSWORD':secrets.token_urlsafe(32),
 **{'SSO_'+c.upper()+'_SECRET':secrets.token_urlsafe(48) for c in ['portal','revenue','municipality']},
}
missing={k:v for k,v in defaults.items() if k not in existing}
if missing:
    if not path.exists():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: f.write(''.join(k+'='+v+'\n' for k,v in missing.items()))
    else:
        with path.open('a') as f: f.write('\n'+''.join(k+'='+v+'\n' for k,v in missing.items()))
        os.chmod(path,0o600)
    print('Local configuration created/upgraded; existing secrets preserved.')
else:
    print('Existing configuration preserved.')
private=ROOT/'private'
private.mkdir(exist_ok=True,mode=0o700)
key=private/'identity.pem'
if not key.exists():
    data=rsa.generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f: f.write(data)
    print('Private local identity signing key generated. Preserve it with your backups.')
