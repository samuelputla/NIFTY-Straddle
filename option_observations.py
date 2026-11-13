"""Additive FYERS evidence. Never changes entries, exits, stops or P&L."""
import copy
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from option_basket_margin import TAB as MARGIN_TAB, HEADERS as MARGIN_HEADERS, estimate_margin

IST = ZoneInfo('Asia/Kolkata')
INDEX = 'NSE:NIFTY50-INDEX'
ENTRY_TAB = 'Option Entry Snapshots'
HIGH_TAB = 'Option Premium Highs'
ENTRY_HEADERS = ['Event ID','Date','Family','Expiry Choice','Expiry','SL %','Cycle','Side','Symbol','Entry Time','Entry Premium','Stop Price','Snapshot Requested At','Snapshot Received At','Snapshot Delay Seconds','Snapshot Timing','Delta','Gamma','Theta','Vega','IV','Contract OI','Chain CE OI Total','Chain PE OI Total','OI Scope','Best Bid','Best Ask','Spread','Bid Levels JSON','Ask Levels JSON','Previous Session','Previous NIFTY High','Previous NIFTY Low','Previous NIFTY Close','NIFTY Opening','Context Retrieved At','Data Status']
HIGH_HEADERS = ['Event ID','Date','Family','Expiry Choice','Expiry','SL %','Cycle','Side','Symbol','Entry Time','Stop Price','Exit Time','Recorded Exit Reason','Window Start','Window End','Observed High','Observed High At','Observed Samples','Max Observed Gap Seconds','Minute Candle High','High Candle Start','Minutes Available','Expected Minutes','Window Coverage','Full Window High','Full Window High At Or Above Stop','Observed Crossing While Leg Open','Interpretation','Entry Premium','Holding Window Candle High','Holding Window High At Or Above Stop','Paper SL Loss INR','Holding Window Evidence']

def stamp(): return datetime.now(IST).isoformat()
def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else ''
    except (ValueError, TypeError): return ''

def candle_high(response, day):
    """Window [09:30,15:00): 330 complete minutes; never use day-high OHLC."""
    start = int(datetime.fromisoformat(day+'T09:30:00+05:30').timestamp())
    end = start + 330*60
    bars = {}
    conflict = False
    for row in response.get('candles', []) if response.get('s') == 'ok' else []:
        if len(row)<6 or num(row[0])=='' or not start<=row[0]<end or row[0]%60: continue
        if any(num(v)=='' for v in row[:6]) or not 0<row[3]<=min(row[1],row[4])<=max(row[1],row[4])<=row[2]: continue
        if row[0] in bars and bars[row[0]]!=row[:6]: conflict=True
        bars[row[0]]=row[:6]
    if not bars: return {'high':'','at':'','minutes':0,'coverage':'UNAVAILABLE'}
    best = max(bars.values(), key=lambda r:r[2])
    complete = len(bars)==330 and not conflict
    return {'high':best[2], 'at':datetime.fromtimestamp(best[0],IST).isoformat(),
            'minutes':len(bars),'coverage':'COMPLETE MINUTE BARS' if complete else 'PARTIAL / CONFLICTING MINUTE BARS'}

class Observer:
    def __init__(self, book, call, day, source, enabled=True, quantity=65):
        self.book,self.call,self.day,self.enabled=book,call,day,enabled
        self.quantity=quantity
        self.out=Path('option_observations')/source
        self.out.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.io_lock=threading.Lock()
        self.entries={};self.snapshots={};self.ticks={};self.candles={};self.context={};self.history={}
        self.futures=[];self.pool=ThreadPoolExecutor(max_workers=1)
        self.margin_entries={};self.margin_cache={};self.margin_results={}
        self.cache={};self.next_request=0;self.pending_publish=None
        if enabled:self.futures.append(self.pool.submit(self._context))

    def _request(self, method, payload):
        # Bound optional requests; failures are saved and never retried in a loop.
        time.sleep(max(0,self.next_request-time.monotonic()))
        self.next_request=time.monotonic()+1.1
        r=self.call(method,payload)
        if r.get('s')!='ok':raise RuntimeError('Optional market data unavailable')
        return r

    def _context(self):
        try:
            r=self._request('history',dict(symbol=INDEX,resolution='D',date_format='1',range_from=str(datetime.fromisoformat(self.day).date()-timedelta(days=14)),range_to=self.day,cont_flag='0'))
            rows=sorted(r.get('candles',[]),key=lambda x:x[0]);previous=[];today=[]
            for row in rows:
                if len(row)<6:continue
                date=datetime.fromtimestamp(row[0],IST).date().isoformat()
                if date<self.day:previous.append(row)
                elif date==self.day:today.append(row)
            context={'at':stamp(),'status':'Context unavailable'}
            if previous:
                p=previous[-1];context.update(date=datetime.fromtimestamp(p[0],IST).date().isoformat(),high=p[2],low=p[3],close=p[4])
            if today:context['open']=today[-1][1]
            context['status']='OK' if previous and today else 'Previous session or current opening unavailable'
            with self.lock:self.context=context
            self._raw('context.json',r)
        except Exception as e:
            with self.lock:self.context={'at':stamp(),'status':type(e).__name__+'; context unavailable'}

    def register(self, family, choice, expiry, pct, cycle, side, symbol, entry_at, premium, stop):
        if not self.enabled:return
        key='|'.join(map(str,(self.day,family,choice,pct,cycle,side)))
        with self.lock:
            if key in self.entries:return
            self.entries[key]=dict(key=key,family=family,choice=choice,expiry=expiry,pct=pct,cycle=cycle,side=side,symbol=symbol,entry_at=entry_at,premium=premium,stop=stop,exit_at='',reason='',crossing='')
            basket_key = (family, choice, expiry, pct, cycle)
            basket = self.margin_entries.setdefault(basket_key, {})
            basket[side] = (symbol, entry_at)
            if set(basket) == {'CE', 'PE'}:
                symbols = tuple(basket[leg][0] for leg in ('CE', 'PE'))
                at = max(basket[leg][1] for leg in basket)
                self.futures.append(self.pool.submit(self._margin, basket_key, symbols, at))
            self.futures.append(self.pool.submit(self._snapshot,key))
        self.tick(symbol,premium,entry_at)

    def _margin(self, basket_key, symbols, at):
        # Coalesce equivalent entry snapshots while still re-estimating on rolls.
        cache_key = (symbols, at[:19])
        if cache_key not in self.margin_cache:
            time.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + 1.1
            amount, status = estimate_margin(symbols, self.quantity)
            self.margin_cache[cache_key] = (stamp(), amount, status)
        captured, amount, status = self.margin_cache[cache_key]
        key = '|'.join(map(str, (self.day, *basket_key)))
        with self.lock:
            self.margin_results[key] = [key, self.day, *basket_key, at, *symbols,
                                        self.quantity, 'INTRADAY', captured, amount, status]

    def exited(self, family,choice,pct,cycle,side,at,reason):
        key='|'.join(map(str,(self.day,family,choice,pct,cycle,side)))
        with self.lock:
            if key in self.entries:self.entries[key].update(exit_at=at,reason=reason)

    def tick(self,symbol,price,at):
        if not self.enabled or num(price)=='' or price<=0 or at[:10]!=self.day or not '09:30:00'<=at[11:19]<'15:00:00':return
        with self.lock:
            t=self.ticks.setdefault(symbol,dict(high=price,at=at,count=0,last='',gap=0))
            if t['last']:
                t['gap']=max(t['gap'],max(0,(datetime.fromisoformat(at)-datetime.fromisoformat(t['last'])).total_seconds()))
            if price>t['high']:t.update(high=price,at=at)
            t['count']+=1;t['last']=at
            for e in self.entries.values():
                if e['symbol']==symbol and e['entry_at']<=at and (not e['exit_at'] or at<=e['exit_at']) and price>=e['stop'] and not e['crossing']:e['crossing']=at

    def _snapshot(self,key):
        with self.lock:e=dict(self.entries[key])
        # All SL alternatives sharing the same entry reuse the same observation.
        cache_key=(e['symbol'],e['entry_at'])
        if cache_key in self.cache:
            with self.lock:self.snapshots[key]=self.cache[cache_key]
            return
        requested=stamp();result={'requested':requested,'received':requested,'status':[],'chain':{},'option':{},'depth':{}}
        try:
            if 'expiries' not in self.cache:
                self.cache['expiries']=self._request('optionchain',dict(symbol=INDEX,strikecount=1,timestamp=''))['data']['expiryData']
            expiry=next(x['expiry'] for x in self.cache['expiries'] if datetime.fromtimestamp(int(x['expiry']),IST).date().isoformat()==e['expiry'])
            chain_key=('chain',e['expiry'],e['entry_at'])
            if chain_key not in self.cache:
                self.cache[chain_key]=self._request('optionchain',dict(symbol=INDEX,strikecount=50,timestamp=str(expiry),greeks='1'))
            chain=self.cache[chain_key]['data'];result['chain']=chain
            result['option']=next((x for x in chain.get('optionsChain',[]) if x.get('symbol')==e['symbol']),{})
            if not result['option']:result['status'].append('Selected contract missing from chain')
        except Exception as ex:result['status'].append('Chain '+type(ex).__name__)
        try:result['depth']=self._request('depth',dict(symbol=e['symbol'],ohlcv_flag='1')).get('d',{}).get(e['symbol'],{})
        except Exception as ex:result['status'].append('Depth '+type(ex).__name__)
        result['received']=stamp()
        self.cache[cache_key]=result
        with self.lock:self.snapshots[key]=result
        self._raw('entry-'+str(len(self.snapshots))+'.json',dict(entry=e,snapshot=result))

    def _raw(self,name,value):
        def clean(x):
            if isinstance(x,float) and not math.isfinite(x):return None
            if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
            if isinstance(x,(tuple,list)):return [clean(v) for v in x]
            return x
        (self.out/name).write_text(json.dumps(clean(value),allow_nan=False,default=str),encoding='utf-8')

    def checkpoint(self):
        if self.enabled and (self.pending_publish is None or self.pending_publish.done()):
            self.pending_publish=self.pool.submit(self.publish)

    def rows(self):
        with self.lock:entries=copy.deepcopy(self.entries);snapshots=copy.deepcopy(self.snapshots);ticks=copy.deepcopy(self.ticks);context=dict(self.context);candles=copy.deepcopy(self.candles)
        entry_rows=[];high_rows=[]
        for key,e in entries.items():
            base=[key,self.day,e['family'],e['choice'],e['expiry'],e['pct'],e['cycle'],e['side'],e['symbol'],e['entry_at']]
            s=snapshots.get(key,{});o=s.get('option',{});g=o.get('greeks') or {};d=s.get('depth',{});c=s.get('chain',{})
            bids=d.get('bids') or [];asks=d.get('ask') or []
            bid=max((num(x.get('price')) for x in bids if num(x.get('price'))!='' and num(x.get('price'))>0),default='')
            ask=min((num(x.get('price')) for x in asks if num(x.get('price'))!='' and num(x.get('price'))>0),default='')
            delay=round((datetime.fromisoformat(s['received'])-datetime.fromisoformat(e['entry_at'])).total_seconds(),3) if s else ''
            timing='NEAR ENTRY (RESPONSE WITHIN 30S)' if delay!='' and 0<=delay<=30 else 'DELAYED; NOT AN EXACT ENTRY SNAPSHOT' if s else 'PENDING / UNAVAILABLE'
            status=list(s.get('status',[]))+[context.get('status','Context pending')]
            greek=[num(g.get(n,o.get(n))) for n in ('delta','gamma','theta','vega')]
            iv=num(g.get('iv',o.get('iv',o.get('implied_volatility'))))
            if '' in greek or iv=='':status.append('Some Greeks/IV unavailable; not estimated')
            if bid=='' or ask=='':status.append('Bid/ask unavailable')
            if bid!='' and ask!='' and ask<bid:status.append('Crossed book; spread withheld')
            entry_rows.append(base+[e['premium'],e['stop'],s.get('requested',''),s.get('received',''),delay,timing,*greek,iv,num(o.get('oi')),num(c.get('callOi')),num(c.get('putOi')),'API chain aggregates; requested strikecount=50; raw units; not whole-exchange totals',bid,ask,round(ask-bid,4) if bid!='' and ask!='' and ask>=bid else '',json.dumps(bids),json.dumps(asks),context.get('date',''),context.get('high',''),context.get('low',''),context.get('close',''),context.get('open',''),context.get('at',''),'; '.join(status)])
            t=ticks.get(e['symbol'],{});h=candles.get(e['symbol'],{})
            candidates=[x for x in (t.get('high',''),h.get('high','')) if x!=''];high=max(candidates) if candidates else ''
            opened=datetime.fromisoformat(e['entry_at']).timestamp()
            closed=min(datetime.fromisoformat(e['exit_at']).timestamp() if e['exit_at'] else opened+86400,datetime.fromisoformat(self.day+'T15:00:00+05:30').timestamp())
            # Only complete minutes strictly within the holding interval can prove
            # a chart threshold crossing without assuming intraminute ordering.
            held=[b for b in self.history.get(e['symbol'],[]) if len(b)>=6 and opened<=b[0] and b[0]+60<=closed and num(b[2])!='' and b[2]>0]
            holding_high=max((b[2] for b in held),default='')
            hit=bool(e['crossing']) or (holding_high!='' and holding_high>=e['stop'])
            evidence='SL HIT: premium >= stop, including jumps over stop' if hit else 'NO CROSSING OBSERVED; boundary minutes / missing feed may be unresolved'
            high_rows.append(base+[e['stop'],e['exit_at'],e['reason'],self.day+'T09:30:00+05:30',self.day+'T15:00:00+05:30',t.get('high',''),t.get('at',''),t.get('count',0),t.get('gap',''),h.get('high',''),h.get('at',''),h.get('minutes',0),330,h.get('coverage','LIVE SAMPLED; FULL WINDOW NOT VERIFIED'),high,high>=e['stop'] if high!='' else '',e['crossing'],'Full-window crossing may precede entry or follow exit. Holding-window crossing is separate; paper threshold fills are not executable fill proof.',e['premium'],holding_high,True if hit else '',round((e['premium']-e['stop'])*65,2) if hit else '',evidence])
        return entry_rows,high_rows

    def publish(self):
        if not self.enabled:return
        from measurement_log import EvidenceWriter
        with self.io_lock:
            entries,highs=self.rows();self._raw('rows.json',{'entry_headers':ENTRY_HEADERS,'entries':entries,'high_headers':HIGH_HEADERS,'highs':highs})
            writer=EvidenceWriter(self.book)
            writer.save(ENTRY_TAB,ENTRY_HEADERS,entries,update=True)
            writer.save(HIGH_TAB,HIGH_HEADERS,highs,update=True)
            with self.lock:
                margins = list(self.margin_results.values())
            self._raw('basket_margins.json', margins)
            writer.save(MARGIN_TAB,MARGIN_HEADERS,margins,update=True)

    def finish(self):
        if not self.enabled:self.pool.shutdown(wait=False);return
        # All entry work is bounded by existing request timeouts and a single worker.
        self.pool.shutdown(wait=True)
        for symbol in sorted({e['symbol'] for e in self.entries.values()}):
            try:
                r=self._request('history',dict(symbol=symbol,resolution='1',date_format='1',range_from=self.day,range_to=self.day,cont_flag='0'))
                self.candles[symbol]=candle_high(r,self.day)
                # Keep only validated in-window bars for holding-period checks.
                start=int(datetime.fromisoformat(self.day+'T09:30:00+05:30').timestamp())
                self.history[symbol]=[b for b in r.get('candles',[]) if len(b)>=6 and num(b[0])!='' and start<=b[0]<start+330*60 and not b[0]%60 and all(num(v)!='' for v in b[:6]) and 0<b[3]<=min(b[1],b[4])<=max(b[1],b[4])<=b[2]]
                self._raw('history-'+symbol.replace(':','_')+'.json',r)
            except Exception as ex:self.candles[symbol]={'coverage':'UNAVAILABLE '+type(ex).__name__}
        self.publish()
