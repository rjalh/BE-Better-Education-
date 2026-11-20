import base64, hashlib, hmac, os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

def hash_password(password: str) -> str:
    salt=os.urandom(16)
    derived=hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return 'scrypt$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(derived).decode()

def check_password(password: str, encoded: str) -> bool:
    try:
        _, a, b=encoded.split('$')
        salt=base64.b64decode(a)
        calculated=hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(calculated,base64.b64decode(b))
    except (ValueError,TypeError): return False

def signer(secret): return URLSafeTimedSerializer(secret, salt='be-session-v1')

def make_token(secret,user_id): return signer(secret).dumps({'id':user_id})

def read_token(secret, token):
    try: return signer(secret).loads(token,max_age=60*60*24*7)['id']
    except (BadSignature,SignatureExpired,KeyError,TypeError): return None
