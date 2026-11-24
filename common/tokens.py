"""Narrow RS256 ID-token codec, with explicit issuer/audience/nonce checks."""
import base64
import json
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def decode64(value):
    return base64.b64decode(value+'='*(-len(value)%4), altchars=b'-_', validate=True)

def key_id(public):
    import hashlib
    return hashlib.sha256(public.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()[:24]

def jwk(public):
    numbers=public.public_numbers()
    def encoded(n): return b64(n.to_bytes((n.bit_length()+7)//8,'big'))
    return {'kty':'RSA','use':'sig','alg':'RS256','kid':key_id(public),'n':encoded(numbers.n),'e':encoded(numbers.e)}

def encode(claims, private):
    header={'alg':'RS256','typ':'JWT','kid':key_id(private.public_key())}
    pieces=[b64(json.dumps(part,separators=(',',':')).encode()) for part in [header,claims]]
    signature=private.sign('.'.join(pieces).encode(),padding.PKCS1v15(),hashes.SHA256())
    return '.'.join([*pieces,b64(signature)])

def validate(token, keys, issuer, audience, nonce):
    if not isinstance(token,str) or len(token)>12000:
        raise ValueError('Invalid ID token size.')
    head,body,signature=token.split('.')
    header=json.loads(decode64(head))
    if header.get('alg')!='RS256' or header.get('typ')!='JWT':
        raise ValueError('Unsupported ID token algorithm.')
    matches=[key for key in keys['keys'] if key.get('kid')==header.get('kid') and key.get('kty')=='RSA' and key.get('alg')=='RS256' and key.get('use')=='sig']
    if len(matches)!=1:
        raise ValueError('Unknown signing key.')
    key=matches[0]
    public=rsa.RSAPublicNumbers(int.from_bytes(decode64(key['e']),'big'),int.from_bytes(decode64(key['n']),'big')).public_key()
    if public.key_size<2048:
        raise ValueError('Signing key too small.')
    public.verify(decode64(signature),f'{head}.{body}'.encode(),padding.PKCS1v15(),hashes.SHA256())
    claims=json.loads(decode64(body))
    now=int(time.time())
    if claims.get('iss')!=issuer or claims.get('aud')!=audience or claims.get('nonce')!=nonce:
        raise ValueError('Issuer, audience or nonce mismatch.')
    if type(claims.get('exp')) is not int or type(claims.get('iat')) is not int or claims['exp']<=now or claims['iat']>now+30 or claims['exp']-claims['iat']>300:
        raise ValueError('Expired or invalid token time.')
    if not isinstance(claims.get('sub'),str) or not 1<=len(claims['sub'])<=200:
        raise ValueError('Invalid token subject.')
    return claims
