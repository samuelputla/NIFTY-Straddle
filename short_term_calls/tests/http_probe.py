"""Run explicitly against the local contract fixture, never the real provider."""
import json
import sys
import tempfile
import time
from datetime import datetime,timedelta
import requests
from short_term_calls.engine import IST
from short_term_calls.providers import History,DataUnavailable


def main(base):
    for attempt in range(30):
        try:
            requests.get(base+'/fixture/state',timeout=.5).raise_for_status()
            break
        except requests.RequestException:
            if attempt==29:raise
            time.sleep(.1)
    start=datetime(2026,11,9,9,15,tzinfo=IST)
    with tempfile.TemporaryDirectory() as out:
        client=History(out,simulation_url=base)
        results=[]
        for mode in ('ok','auth','rate','body-rate','unavailable','html','malformed','outside'):
            requests.get(base+'/fixture/mode',params={'value':mode},timeout=5).raise_for_status()
            try:
                data=client.fetch('NSE:TEST-EQ',start,start+timedelta(minutes=2))
                assert mode=='ok' and len(data)==1
            except DataUnavailable:
                assert mode!='ok'
            state=requests.get(base+'/fixture/state',timeout=5).json()
            assert state['calls']==1, 'Failed provider requests must not be retried'
            results.append({'mode':mode,'requests':state['calls'],'status':'passed'})
        print(json.dumps(results,indent=2))


if __name__=='__main__':main(sys.argv[1])
