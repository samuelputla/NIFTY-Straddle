import os,requests,json,datetime as dt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from comparison_runner import publish
from comparison_engine import compare_day,Quotes
base=os.environ['COMPARISON_SIM_URL']
key=rsa.generate_private_key(public_exponent=65537,key_size=2048);pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode();public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']=json.dumps({'private_key':pem,'private_key_id':'fixture','client_email':'fixture@example.test','token_uri':'https://oauth2.googleapis.com/token'})
requests.post(base+'/fixture/config',json={'publicKey':public}).raise_for_status()
Original=requests.Session
class Local(Original):
 def post(self,url,**kw):return super().post(url.replace('https://nifty-straddle-lab.cosmicbay1.chatgpt.site',base),**kw)
# Only redirect transport; execute the real compacting/signing/publishing implementation.
requests.Session=Local
rows=compare_day('2026-11-02','Fixed Entry','Current Week',25,[],Quotes([]),[],{})
publish(rows,[],token='fixture');state=requests.get(base+'/fixture/state').json();assert len(state['2026-11']['values'])==10;assert state['index']['eligibleDays']==0
before=state['index']['sentAt'];requests.post(base+'/fixture/config',json={'mode':'failure'})
try:publish(rows,[],token='fixture')
except RuntimeError:pass
else:raise AssertionError('Expected publisher failure')
after=requests.get(base+'/fixture/state').json();assert after['index']['sentAt']==before
print('PASS production month compression, real RSA signing and HTTP publishing; failed storage does not claim success or replace index')

