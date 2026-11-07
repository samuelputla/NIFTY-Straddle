"""Bounded HTTP data reads and atomic append-only Sheet publication."""
import csv
import io
import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .core import validate_candles, digest

IST = ZoneInfo('Asia/Kolkata')
UNIVERSE_URL = 'https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv'
UNIVERSE_FALLBACK = 'https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv'

class Unavailable(RuntimeError):
    pass

def public_get(url):
    import requests
    try:
        r=requests.get(url,timeout=(5,25),headers={'User-Agent':'NiftyStudy/1.0 research'})
        r.raise_for_status()
        return r.text
    except (requests.RequestException,ValueError):
        raise Unavailable('Public source unavailable: '+url.split('?')[0]) from None

def universe(text):
    rows=list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    if len(rows)!=50 or len({r.get('Symbol') for r in rows})!=50:
        raise Unavailable('Official constituent file must contain 50 unique symbols')
    for r in rows:
        if not r.get('Symbol') or not r.get('Industry') or r.get('Series')!='EQ':
            raise Unavailable('Constituent metadata incomplete')
    return rows

def fetch_universe():
    for url in (UNIVERSE_URL,UNIVERSE_FALLBACK):
        try:
            text=public_get(url)
            return text,universe(text),url
        except Unavailable:
            continue
    raise Unavailable('Both official constituent sources unavailable or invalid')

class Fyers:
    def __init__(self, token, out, base=None, interval=2.1):
        import requests
        self.session=requests.Session()
        self.session.headers['Authorization']=os.getenv('FYERS_CLIENT_ID','M2DACFCYUO-100')+':'+token
        self.base=base or 'https://api-t1.fyers.in/data'
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
        self.interval=interval;self.last_request=0

    def history(self,symbol,day,resolution='D',lookback=300):
        import requests
        start=str(datetime.fromisoformat(day).date()-timedelta(days=lookback))
        params={'symbol':symbol,'resolution':resolution,'date_format':'1','range_from':start,'range_to':day,'cont_flag':'0'}
        for attempt in range(3):
            try:
                time.sleep(max(0,self.interval-(time.monotonic()-self.last_request)))
                self.last_request=time.monotonic()
                r=self.session.get(self.base+'/history',params=params,timeout=(5,25))
                if r.status_code in (401,403):
                    raise Unavailable('FYERS authentication/access unavailable')
                if r.status_code==429:
                    raise Unavailable('FYERS rate limit reached; stopped without retry to protect shared account quota')
                if r.status_code in (500,502,503,504) and attempt<2:
                    time.sleep(2**attempt);continue
                if r.status_code>=400:
                    raise Unavailable('FYERS HTTP '+str(r.status_code)+' for '+symbol)
                body=r.json()
                if body.get('code') in (-429,429,'-429','429'):
                    raise Unavailable('FYERS rate limit reached; stopped without retry to protect shared account quota')
                if body.get('s')!='ok':
                    raise Unavailable('FYERS history unavailable; code '+str(body.get('code')))
                safe=symbol.replace(':','_').replace('/','_')
                (self.out/(safe+'_'+resolution+'.json')).write_text(json.dumps({'request':params,'response':body}),encoding='utf-8')
                try:
                    candles=validate_candles(body.get('candles'))
                except ValueError as error:
                    raise Unavailable('FYERS '+str(error)+' for '+symbol) from None
                if any(str(datetime.fromtimestamp(b[0],IST).date())>day for b in candles):
                    raise Unavailable('Future candle in historical response')
                return candles
            except Unavailable:
                raise
            except (requests.Timeout,requests.ConnectionError):
                if attempt<2:
                    time.sleep(2**attempt);continue
                raise Unavailable('FYERS transport retry limit for '+symbol) from None
            except (requests.RequestException,ValueError,TypeError,KeyError):
                raise Unavailable('FYERS HTTP/response failure for '+symbol) from None
        raise Unavailable('FYERS retry limit reached')

class Sheets:
    def __init__(self):
        import gspread
        from google.oauth2.service_account import Credentials
        raw=os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
        if not raw:
            raise Unavailable('Google Sheet credentials unavailable')
        try:
            creds=Credentials.from_service_account_info(json.loads(raw),scopes=['https://www.googleapis.com/auth/spreadsheets'])
            book_id=os.getenv('NIFTY_STUDY_SHEET_ID')
            if not book_id:
                # Reuse the repository's established destination configuration.
                from eod_validation import BOOK
                book_id=BOOK
            self.book=gspread.authorize(creds).open_by_key(book_id)
        except Exception:
            raise Unavailable('Google Sheet authentication/access unavailable') from None
        self.schema=json.loads(Path(__file__).with_name('schema.json').read_text())
        self.tabs={w.title:w for w in self.book.worksheets()}
        for name,headers in self.schema.items():
            if name not in self.tabs:
                self.tabs[name]=self.book.add_worksheet(name,rows=1000,cols=len(headers))
                self.tabs[name].append_row(headers,value_input_option='RAW')
            if self.tabs[name].row_values(1)!=headers:
                raise Unavailable('Study tab header mismatch: '+name)

    def records(self,name):
        values=self.tabs[name].get_all_values()
        # Refuse unbounded growth before fetching additional daily inputs.
        if len(values)>100000:
            raise Unavailable('Study tab archival needed: '+name)
        return [dict(zip(values[0],r+['']*(len(values[0])-len(r)))) for r in values[1:]]

    def has_run(self,key):
        return any(r.get('Run Key')==key for r in self.records('Study Runs'))

    def publish(self,key,tables):
        if self.has_run(key):
            return False
        requests=[]
        for name,rows in tables.items():
            if name not in self.schema:
                raise ValueError('Write outside study tabs')
            cells=[]
            for row in rows:
                if len(row)!=len(self.schema[name]):
                    raise ValueError('Publication width mismatch for '+name)
                cells.append({'values':[{'userEnteredValue':{'boolValue':v}} if isinstance(v,bool) else
                    {'userEnteredValue':{'numberValue':v}} if isinstance(v,(float,int)) else
                    {'userEnteredValue':{'stringValue':'' if v is None else str(v)}} for v in row]})
            if cells:
                requests.append({'appendCells':{'sheetId':self.tabs[name].id,'rows':cells,'fields':'userEnteredValue'}})
        try:
            self.book.batch_update({'requests':requests})
        except Exception:
            # An ambiguous response may follow a committed atomic write. Read before any retry.
            if self.has_run(key):
                return False
            raise Unavailable('Study publication failed; no blind write retry') from None
        return True
