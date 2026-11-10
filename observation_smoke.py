"""Temporary branch-only dummy round trip. Real Sheets, fixture market data, cleanup."""
import json,os
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
from option_observations import Observer,ENTRY_TAB,HIGH_TAB,ENTRY_HEADERS,HIGH_HEADERS

BOOK='1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
IST=ZoneInfo('Asia/Kolkata');day=datetime.now(IST).date().isoformat()
marker='DUMMY_SMOKE_'+os.environ['GITHUB_RUN_ID']
at=day+'T09:30:00+05:30';start=int(datetime.fromisoformat(at).timestamp())
client=gspread.authorize(Credentials.from_service_account_info(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),scopes=['https://www.googleapis.com/auth/spreadsheets']))
client.set_timeout((3,12));book=client.open_by_key(BOOK)
tabs={name:book.worksheet(name) for name in (ENTRY_TAB,HIGH_TAB)}
before={name:ws.get_all_values() for name,ws in tabs.items()}
if before[ENTRY_TAB][0]!=ENTRY_HEADERS or before[HIGH_TAB][0]!=HIGH_HEADERS:raise RuntimeError('Unexpected observation headers')

def fixture(method,payload):
    if method=='optionchain':return {'s':'ok','data':{'expiryData':[{'expiry':start}], 'callOi':100000,'putOi':120000,'optionsChain':[{'symbol':s,'oi':5000,'greeks':{'delta':.5 if s=='DUMMY_CE' else -.5,'gamma':.01,'theta':-10,'vega':8,'iv':15}} for s in ('DUMMY_CE','DUMMY_PE')]}}
    if method=='depth':return {'s':'ok','d':{payload['symbol']:{'bids':[{'price':79,'volume':65,'ord':2}],'ask':[{'price':81,'volume':130,'ord':3}]}}}
    if method=='history':
        if payload['symbol']=='NSE:NIFTY50-INDEX':return {'s':'ok','candles':[[start-86400,25000,25100,24900,25020,1000],[start,25030,25150,24950,25050,2000]]}
        return {'s':'ok','candles':[[start+i*60,80,101 if payload['symbol']=='DUMMY_CE' and i==30 else 90,70,80,65] for i in range(330)]}
    raise RuntimeError('Fixture allows market data only')

observer=Observer(book,fixture,day,marker,enabled=False);observer.enabled=True;observer._request=fixture
expected_ids=set();report={'marker':marker,'market_data':'DUMMY FIXTURE; NOT LIVE PRICES','results':{}}
try:
    observer._context()
    for family in ('Fixed Entry','Time Based','Delta Based','Short Strangle'):
        for side in ('CE','PE'):
            observer.register(marker+' '+family,'Current Week',day,25,1,side,'DUMMY_'+side,at,80,100)
    for f in observer.futures:f.result()
    expected_ids=set(observer.entries)
    observer.tick('DUMMY_CE',101,day+'T10:00:00+05:30')
    observer.tick('DUMMY_PE',90,day+'T10:00:00+05:30')
    for e in list(observer.entries.values()):observer.exited(e['family'],e['choice'],e['pct'],e['cycle'],e['side'],day+'T15:00:00+05:30','DUMMY TEST EXIT')
    observer.finish()
    for name,ws in tabs.items():
        rows=[r for r in ws.get_all_values()[1:] if r and r[0] in expected_ids]
        if len(rows)!=8:raise RuntimeError('Missing/duplicate dummy rows: '+name)
        headers=ENTRY_HEADERS if name==ENTRY_TAB else HIGH_HEADERS
        values=[dict(zip(headers,r)) for r in rows]
        if name==ENTRY_TAB:
            if any(float(r['Gamma'])!=.01 or float(r['Spread'])!=2 or float(r['Chain PE OI Total'])!=120000 for r in values):raise RuntimeError('Snapshot serialization mismatch')
        else:
            for r in values:
                if int(r['Minutes Available'])!=330:raise RuntimeError('Candle coverage mismatch')
                if r['Side']=='CE' and (float(r['Full Window High'])!=101 or float(r['Paper SL Loss INR'])!=-1300):raise RuntimeError('Jump-over-stop loss mismatch')
        report['results'][name]={'rows':len(rows),'readback':'PASS'}
    # Exercise the actual EvidenceWriter update path and deduplication.
    observer.publish()
    for name,ws in tabs.items():
        rows=[r for r in ws.get_all_values()[1:] if r and r[0] in expected_ids]
        if len(rows)!=8:raise RuntimeError('Duplicate rows after repeat publish')
    report['repeat_publish']='PASS: same eight rows updated, no duplicates'
finally:
    observer.pool.shutdown(wait=True)
    deleted={}
    for name,ws in tabs.items():
        rows=ws.get_all_values();indexes=[i for i,r in enumerate(rows,1) if r and marker in r[0]]
        end='AK' if name==ENTRY_TAB else 'AG'
        if indexes:ws.batch_clear(['A'+str(i)+':'+end+str(i) for i in indexes])
        after=ws.get_all_values()
        if after!=before[name]:raise RuntimeError('Cleanup did not restore original values: '+name)
        deleted[name]=len(indexes)
    report['cleanup']={'deleted_rows':deleted,'original_values_restored':True}
    Path('observation-smoke-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

