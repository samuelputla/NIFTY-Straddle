"""One-off FYERS Nifty daily range research. No orders or Sheet writes."""
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import time
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OUT=Path('nifty-range-report')
IST=ZoneInfo('Asia/Kolkata')

def percentile(values,q):
    a=sorted(values);pos=(len(a)-1)*q;i=int(pos);f=pos-i
    return a[i]+f*(a[min(i+1,len(a)-1)]-a[i])

def summarize(rows):
    out={'sessions':len(rows),'from':rows[0]['date'],'through':rows[-1]['date']}
    for metric in ['range_points','range_pct','absolute_change_points','absolute_change_pct','absolute_gap_points','absolute_intraday_points']:
        v=[r[metric] for r in rows]
        out[metric]={'mean':round(statistics.mean(v),2),'median':round(statistics.median(v),2),
                     'p75':round(percentile(v,.75),2),'p90':round(percentile(v,.90),2),'p95':round(percentile(v,.95),2),'max':round(max(v),2)}
    out['up_days']=sum(r['change_points']>0 for r in rows)
    out['down_days']=sum(r['change_points']<0 for r in rows)
    return out

def calculate(candles):
    rows=[];previous=None
    for c in sorted(candles):
        if len(c)<6 or not all(isinstance(x,(float,int)) and math.isfinite(x) for x in c[:6]):
            raise ValueError('Malformed candle')
        stamp,o,h,l,close,vol=c[:6]
        if not 0<l<=min(o,close)<=max(o,close)<=h:
            raise ValueError('Invalid provider OHLC')
        day=str(datetime.fromtimestamp(stamp,IST).date())
        if previous is not None:
            change=close-previous
            rows.append({'date':day,'open':o,'high':h,'low':l,'close':close,'previous_close':previous,
                         'range_points':h-l,'range_pct':100*(h-l)/previous,
                         'change_points':change,'change_pct':100*change/previous,
                         'absolute_change_points':abs(change),'absolute_change_pct':100*abs(change)/previous,
                         'gap_points':o-previous,'absolute_gap_points':abs(o-previous),
                         'intraday_points':close-o,'absolute_intraday_points':abs(close-o)})
        previous=close
    if not rows:raise ValueError('Insufficient history')
    return rows

def main():
    import requests
    OUT.mkdir(exist_ok=True)
    token=os.getenv('FYERS_ACCESS_TOKEN','').strip()
    if not token:raise ValueError('FYERS workflow access unavailable')
    client=os.getenv('FYERS_CLIENT_ID','M2DACFCYUO-100')
    session=requests.Session();session.headers.update({'Authorization':token if token.startswith(client+':') else client+':'+token,'Content-Type':'application/json','version':'3'})
    # Only success flags leave the runner; profile data and credential values never do.
    for label,url,params in [
        ('profile','https://api-t1.fyers.in/api/v3/profile',None),
        ('index_quote','https://api-t1.fyers.in/data/quotes',{'symbols':'NSE:NIFTY50-INDEX'})]:
        check=session.get(url,params=params,timeout=(5,25))
        if check.status_code==429:raise ValueError('FYERS rate limit active during '+label+'; stopped without retry')
        try:payload=check.json()
        except ValueError:raise ValueError('FYERS non-JSON response during '+label)
        ok=check.status_code==200 and payload.get('s')=='ok'
        if label=='index_quote':
            ok=ok and bool(payload.get('d')) and all(x.get('s')=='ok' for x in payload['d'])
        print('CONNECTION_CHECK '+json.dumps({'check':label,'ok':ok,'http_status':check.status_code,'code':payload.get('code')}))
        if not ok:raise ValueError('FYERS '+label+' check failed; code '+str(payload.get('code')))
        time.sleep(2.1)
    from fyers_apiv3 import fyersModel
    sdk_token=token[len(client)+1:] if token.startswith(client+':') else token
    sdk=fyersModel.FyersModel(client_id=client,token=sdk_token,is_async=False,log_path='')
    candles={};requests_made=0
    def fetch(start,end):
        nonlocal requests_made
        if requests_made:time.sleep(2.1)
        requests_made+=1
        body=sdk.history(data={'symbol':'NSE:NIFTY50-INDEX','resolution':'D',
                              'date_format':'1','range_from':str(start),'range_to':str(end),'cont_flag':'1'})
        if body.get('code') in (-429,429,'-429','429'):raise ValueError('FYERS rate-limit code; stopped without retry')
        if body.get('s')!='ok' or not body.get('candles'):
            for test_symbol,test_resolution in [('NSE:SBIN-EQ','D'),('NSE:NIFTY50-INDEX','D'),('NSE:NIFTY50-INDEX','1')]:
                time.sleep(2.1)
                probe=sdk.history(data={'symbol':test_symbol,'resolution':test_resolution,'date_format':'1',
                                        'range_from':str(end),'range_to':str(end),'cont_flag':'1'})
                print('HISTORY_PROBE '+json.dumps({'symbol':test_symbol,'resolution':test_resolution,'date':str(end),
                     'ok':probe.get('s')=='ok','code':probe.get('code'),'candles':len(probe.get('candles') or [])}))
                if probe.get('code') in (-429,429,'-429','429'):break
            raise ValueError('FYERS history unavailable; code '+str(body.get('code')))
        (OUT/(str(start)+'_'+str(end)+'.json')).write_text(json.dumps(body),encoding='utf-8')
        for c in body['candles']:
            at=str(datetime.fromtimestamp(c[0],IST).date())
            if not str(start)<=at<=str(end):raise ValueError('Provider returned date outside requested window')
            if c[0] in candles and candles[c[0]]!=c:raise ValueError('Overlapping provider candles disagree')
            candles[c[0]]=c
    # One bounded request establishes whether today's earlier rate restriction persists.
    end=date(2026,11,6)
    fetch(date(2026,9,1),end)
    start=date(2021,1,1)
    while start<=end:
        stop=min(start+timedelta(days=299),end)
        fetch(start,stop);start=stop+timedelta(days=1)
    rows=calculate(list(candles.values()))
    with (OUT/'daily_movements.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    yearly={}
    for year in sorted({r['date'][:4] for r in rows}):yearly[year]=summarize([r for r in rows if r['date'].startswith(year)])
    result={'source':'FYERS daily NIFTY50 index history','as_of':datetime.now(IST).isoformat(),
            'requests':requests_made,'raw_candle_count':len(candles),'coverage':'Provider-returned sessions; holidays/special-session completeness not independently reconciled. First available candle excluded where prior close is unavailable. 2026 is partial.',
            'input_sha256':hashlib.sha256(json.dumps(sorted(candles.values())).encode()).hexdigest(),
            'overall':summarize(rows),'yearly':yearly,
            'largest_ranges':sorted(rows,key=lambda r:r['range_points'],reverse=True)[:5],
            'largest_net_moves':sorted(rows,key=lambda r:r['absolute_change_points'],reverse=True)[:5]}
    (OUT/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RANGE_RESULT '+json.dumps(result,separators=(',',':')))

if __name__=='__main__':
    try:main()
    except Exception as e:
        # Only known safe diagnostics; never print response headers, token or raw exception.
        message=str(e) if isinstance(e,ValueError) and str(e).startswith(('FYERS','Provider','Overlapping','Malformed','Invalid','Insufficient')) else 'Data retrieval failed; no statistical conclusion'
        OUT.mkdir(exist_ok=True);(OUT/'status.json').write_text(json.dumps({'status':'UNAVAILABLE','reason':message}))
        print('RANGE_STATUS '+json.dumps({'status':'UNAVAILABLE','reason':message}));sys.exit(1)

