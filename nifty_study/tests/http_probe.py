"""Run against Postman's local one-port simulation, never real FYERS."""
import json
import sys
import tempfile
import urllib.request
from nifty_study.adapters import Fyers,Unavailable

base=sys.argv[1].rstrip('/')
def mode(value):
    urllib.request.urlopen(base+'/fixture/mode?value='+value).read()
with tempfile.TemporaryDirectory() as out:
    api=Fyers('synthetic-test-token',out,base=base)
    mode('ok');assert api.history('NSE:INFY-EQ','2026-11-09')[0][4]==104
    mode('rate');assert api.history('NSE:INFY-EQ','2026-11-09')
    state=json.load(urllib.request.urlopen(base+'/fixture/state'));assert state['calls']==3
    for value in ['auth','malformed','unavailable']:
        mode(value)
        try: api.history('NSE:INFY-EQ','2026-11-09')
        except Unavailable as e:
            assert 'synthetic-test-token' not in str(e)
        else: raise AssertionError(value+' did not fail closed')
print('HTTP success, bounded rate retry, auth, malformed candles and outage checks passed')
