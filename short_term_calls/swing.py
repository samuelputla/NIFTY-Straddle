"""Versioned, prospective swing screen. Scores are not win probabilities."""
import json
import math
from datetime import datetime,timedelta,time,date
from pathlib import Path
from .engine import IST,session,trading_day,validate_plan,digest
from .providers import DataUnavailable

RULE='Swing Breakout Retest V3'
SPECIAL={'2026-11-08'}
DEFAULTS={'min_price':50,'min_turnover_cr':100,'rsi_min':50,'rsi_max':68,
          'min_rvol':1,'max_extension_pct':8,'min_excess20':-5,
          'trigger_buffer_pct':.1,'entry_band_pct':.25,'stop_buffer_pct':.1,
          'min_risk_pct':1,'max_risk_pct':5.5,'validity_calendar_days':14,
          'radar_limit':0,'benchmark':'NSE:NIFTY50-INDEX'}

def next_session(day):
    return trading_day(day,1)

def latest_session(day):
    while not session(day):day-=timedelta(days=1)
    return day

def daily_rows(raw,through):
    if not isinstance(raw,list) or not raw:raise ValueError('Daily candles missing')
    seen={}
    for r in raw:
        if len(r)<6 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in r[:6]):
            raise ValueError('Malformed daily candle')
        ts,o,h,l,c,v=r[:6];day=datetime.fromtimestamp(ts,IST).date()
        if day>through or day<through-timedelta(days=366):raise ValueError('Daily candle outside requested window')
        if not 0<l<=min(o,c)<=max(o,c)<=h or v<0:raise ValueError('Invalid daily prices')
        if day.isoformat() in seen:raise ValueError('Duplicate daily date')
        seen[day.isoformat()]=[ts,o,h,l,c,v]
    rows=[seen[d] for d in sorted(seen)]
    if datetime.fromtimestamp(rows[-1][0],IST).date()!=through:raise ValueError('Stale daily history')
    return rows

def ema(xs,n):
    if len(xs)<n:raise ValueError('EMA warm-up missing')
    out=[sum(xs[:n])/n]
    for x in xs[n:]:out.append(out[-1]+2*(x-out[-1])/(n+1))
    return out

def features(rows):
    if len(rows)<60:raise ValueError('At least 60 daily observations required')
    cs=[r[4] for r in rows]
    gains=[max(0,b-a) for a,b in zip(cs,cs[1:])]
    losses=[max(0,a-b) for a,b in zip(cs,cs[1:])]
    def smooth(xs):
        x=sum(xs[:14])/14
        for v in xs[14:]:x=(13*x+v)/14
        return x
    ag,al=smooth(gains),smooth(losses)
    rsi=100-100/(1+ag/al) if al else (100 if ag else 50)
    macd=[a-b for a,b in zip(ema(cs,12)[14:],ema(cs,26))]
    normal=[r for r in rows if datetime.fromtimestamp(r[0],IST).weekday()<5 and
            datetime.fromtimestamp(r[0],IST).date().isoformat() not in SPECIAL]
    if normal[-1][0]!=rows[-1][0] or len(normal)<21 or any(r[5]<=0 for r in normal[-21:]):
        raise ValueError('Normal-session stock volume unavailable')
    rv=normal[-1][5]/(sum(r[5] for r in normal[-21:-1])/20)
    tr=[max(rows[i][2]-rows[i][3],abs(rows[i][2]-rows[i-1][4]),abs(rows[i][3]-rows[i-1][4])) for i in range(1,len(rows))]
    start=normal[-3][0]
    return {'close':cs[-1],'sma20':sum(cs[-20:])/20,'sma50':sum(cs[-50:])/50,
            'rsi14':rsi,'macd':macd[-1],'macd_signal':ema(macd,9)[-1],
            'rvol20_normal':rv,'atr14':smooth(tr),'return20':100*(cs[-1]/cs[-21]-1),
            'extension_pct':100*(cs[-1]/(sum(cs[-20:])/20)-1),
            'resistance':max(r[2] for r in rows if r[0]>=start),'support':rows[-1][3],
            'data_through':datetime.fromtimestamp(rows[-1][0],IST).date().isoformat(),
            'input_hash':digest(rows),'indicator_conventions':'SMA means; SMA-seeded EMA; Wilder RSI14/ATR14; MACD12/26/9; 60-bar minimum; traded-session prices, normal-session RVOL20.'}

def evaluate(symbol,rows,benchmark_return,settings,blackouts,target):
    return evaluate_features(symbol,features(rows),benchmark_return,settings,blackouts,target)

def evaluate_features(symbol,f,benchmark_return,settings,blackouts,target):
    f=dict(f);f['excess20']=f['return20']-benchmark_return
    reasons=[]
    checks=[(f['close']>=settings['min_price'],'Price Below Minimum'),
            (f['close']>f['sma20'] and f['close']>f['sma50'],'Below Trend Averages'),
            (settings['rsi_min']<=f['rsi14']<=settings['rsi_max'],'RSI Outside Research Band'),
            (f['macd']>f['macd_signal'],'MACD Below Signal'),
            (f['rvol20_normal']>=settings['min_rvol'],'Low Normal-Session Volume'),
            (f['extension_pct']<=settings['max_extension_pct'],'Extended Above SMA20'),
            (f['excess20']>=settings['min_excess20'],'Weak Relative Strength')]
    reasons.extend(reason for ok,reason in checks if not ok)
    # Only explicit, sourced event records are used. Missing event coverage remains unknown.
    events=[e for e in blackouts if e['symbol']==symbol and e['from']<=target.isoformat()<=e['through']]
    if events:reasons.append('Known Event Blackout')
    f.update(symbol=symbol,ranking_score=f['excess20'],archetype='Continuation' if f['excess20']>0 else 'Recovery',
             event_evidence=events,event_coverage='Limited configured official events; complete news/fundamentals unavailable')
    return f,reasons

def grid(v,step=.01,up=True):
    return round((math.ceil(v/step-1e-8) if up else math.floor(v/step+1e-8))*step,2)

def make_swing(f,target,issued,settings,live=False):
    # Research grid only: live exchange tick sizes are not asserted or used for orders.
    trigger=grid(f['resistance']*(1+settings['trigger_buffer_pct']/100))
    hi=grid(trigger*(1+settings['entry_band_pct']/100))
    stop=grid(f['support']*(1-settings['stop_buffer_pct']/100),up=False)
    risk=hi-stop;rp=100*risk/hi
    if not settings['min_risk_pct']<=rp<=settings['max_risk_pct']:return None
    end=latest_session(target+timedelta(days=settings['validity_calendar_days']))
    p={'id':f'ST-{target:%Y%m%d}-{f["symbol"]}-SWING-V3','symbol':'NSE:'+f['symbol']+'-EQ',
       'type':'Swing','status':'Active','issued_at':issued.isoformat(),
       'start_at':((issued.replace(second=0,microsecond=0)+timedelta(minutes=5)) if live else datetime.combine(target,time(9,15),IST)).isoformat(),
       'enter_by':datetime.combine(target,time(15,0) if live else time(12,30),IST).isoformat(),
       'exit_by':datetime.combine(end,time(15,0),IST).isoformat(),
       'observe_until':datetime.combine(trading_day(end,5),time(15,30),IST).isoformat(),
       'monitor_from_start':not live,'entry_rule':'Breakout Retest Confirmation',
       'trigger':trigger,'entry_min':trigger,'entry_max':hi,'stop':stop,
       'target_1':grid(hi+risk),'target_2':grid(hi+2*risk),'quantity':1,'quantity_mode':'one_share',
       'total_costs':None,'policy':'Full Exit At T1','source':RULE,'research_version':RULE,
       'rationale':f'{f["archetype"]}; RSI {f["rsi14"]:.2f}, RVOL {f["rvol20_normal"]:.2f}, '+
                   f'20-session excess vs NIFTY50 {f["excess20"]:.2f} points. Completed 15-minute breakout, later retest and in-band confirmation required.',
       'limitations':'Experimental technical screen; not HDFC replication. Fundamentals, complete news, corporate-action adjustments and execution costs unverified.',
       'target_session':target.isoformat(),'selection_evidence':f}
    validate_plan(p);return p

def prepare(store,history,target,now,out,config,live=False):
    key=target.isoformat()+f':Market {now.hour:02d}-{now.minute//15*15:02d}' if live else target.isoformat()
    if store.prepared(key):return []
    if live and (target!=now.date() or not time(9,50)<=now.time().replace(tzinfo=None)<=time(14,30)):
        raise DataUnavailable('Market-hours generation is restricted to 09:50–14:30 IST')
    if not live and now>=datetime.combine(target,time(9,10),IST):
        raise DataUnavailable('Premarket preparation cutoff missed; no late or backdated forecast')
    from .generate import daily_candidates,DEFAULTS as OLD
    cfg={**DEFAULTS,**config['swing']}
    prior=latest_session(target-timedelta(days=1))
    # Existing six-session, whole-NSE liquid-stock scan is a bounded prefilter, not an exhaustive indicator screen.
    pre=daily_candidates(target,out,{**OLD,**config['selection'],'candidate_count':cfg['radar_limit']})
    bench=history.daily(cfg['benchmark'],prior)
    if len(bench)<21:raise DataUnavailable('Benchmark warm-up missing')
    breturn=100*(bench[-1][4]/bench[-21][4]-1)
    blackouts=json.loads(Path('short_term_calls/event_blackouts.json').read_text())['events']
    audit=[];proposed=[];existing=store.plans();cached={}
    for row in store.cache.snapshot('Short Term Events')[1:]:
        if len(row)<6 or row[2]!='Radar Snapshot':continue
        record=json.loads(row[5])
        if record.get('target_session')==target.isoformat() and record.get('rule_hash')==digest(cfg) and record.get('features',{}).get('data_through')==prior.isoformat():
            cached.setdefault(record['symbol'],record.get('daily_features',record['features']))
    used={p['symbol'] for p in existing if stamp_day(p['start_at'])==target}
    for item in pre:
        sym=item['symbol']
        try:
            if sym in cached:
                f,reasons=evaluate_features(sym,cached[sym],breturn,cfg,blackouts,target)
            else:
                rows=history.daily('NSE:'+sym+'-EQ',prior)
                if [r[0] for r in rows[-21:]]!=[r[0] for r in bench[-21:]]:
                    raise ValueError('Stock and benchmark return sessions do not align')
                f,reasons=evaluate(sym,rows,breturn,cfg,blackouts,target)
            f['turnover_cr']=item['turnover_cr']
            daily_features=dict(f)
            if live and not reasons and 'NSE:'+sym+'-EQ' not in used:
                mins=history.fetch('NSE:'+sym+'-EQ',datetime.combine(target,time(9,15),IST),datetime.now(IST))
                opening=[r for r in mins if time(9,15)<=datetime.fromtimestamp(r[0],IST).time().replace(tzinfo=None)<time(9,45)]
                if len(opening)!=30 or any(b[0]-a[0]!=60 for a,b in zip(opening,opening[1:])):
                    raise DataUnavailable('Opening range has missing minutes')
                if not mins or datetime.fromtimestamp(mins[-1][0],IST)+timedelta(minutes=1)<datetime.now(IST)-timedelta(minutes=2):
                    raise DataUnavailable('Fresh completed minute is unavailable')
                f['resistance']=max(f['resistance'],max(r[2] for r in opening))
                f['support']=max(f['support'],min(r[3] for r in opening))
                f['opening_range_hash']=digest(opening);f['latest_completed_minute']=datetime.fromtimestamp(mins[-1][0],IST).isoformat()
                f['generation_phase']='Market Hours; daily indicators remain prior-session only'
                if mins[-1][4]>f['resistance']*(1+cfg['trigger_buffer_pct']/100)*(1+cfg['entry_band_pct']/100):
                    reasons.append('Already Above Buy Band; No Chasing')
                if mins[-1][4]<=f['support']*(1-cfg['stop_buffer_pct']/100):reasons.append('Support Already Invalidated')
            p=None if reasons or 'NSE:'+sym+'-EQ' in used else make_swing(f,target,now,cfg,live)
            if 'NSE:'+sym+'-EQ' in used:reasons.append('Existing Frozen Setup Retained; No Duplicate')
            if not reasons and p is None:reasons=['Plan Risk Outside Research Band']
            record={'symbol':sym,'target_session':target.isoformat(),'features':f,'daily_features':daily_features,'reasons':reasons,
                    'result':'Rejected' if reasons else 'Qualified','known_at':now.isoformat(),'rule_hash':digest(cfg)}
            if p and p['symbol'] not in used:proposed.append(p)
        except DataUnavailable as exc:
            if 'rate limit' in str(exc).lower() or 'authentication' in str(exc).lower():raise
            record={'symbol':sym,'target_session':target.isoformat(),'result':'Unavailable','reasons':[str(exc)],'known_at':now.isoformat()}
        except ValueError:
            record={'symbol':sym,'target_session':target.isoformat(),'result':'Unavailable','reasons':['Insufficient or invalid indicator evidence'],'known_at':now.isoformat()}
        audit.append(record)
    # Re-check the clock after all provider reads, before freezing or publishing any plan.
    frozen=datetime.now(IST).replace(microsecond=0)
    cutoff=time(14,35) if live else time(9,10)
    if frozen>=datetime.combine(target,cutoff,IST):raise DataUnavailable('Preparation crossed cutoff; no forecast published')
    for p in proposed:
        p['issued_at']=frozen.isoformat()
        if live:p['start_at']=(frozen.replace(second=0,microsecond=0)+timedelta(minutes=5)).isoformat()
    from .portfolio import select
    settings={**config['portfolio'],'daily_selection_counts':{'Intraday':0,'Swing':None}}
    generated=select(proposed,existing,store.results(),frozen,settings)
    store.register_many(generated,frozen.isoformat())
    from .engine import replay
    for p in generated:store.save_result(p,replay(p,[],frozen.isoformat()))
    for record in audit:
        record['known_at']=frozen.isoformat()
        store.journal(key+':'+record['symbol'],'Radar Snapshot',frozen.isoformat(),record)
    details={'target_session':target.isoformat(),'data_through':prior.isoformat(),'rule':RULE,
             'universe':'Whole-NSE six-session price/liquidity/momentum prefilter; '+('all matching stocks, no call quota' if not cfg['radar_limit'] else 'explicit research scan cap '+str(cfg['radar_limit'])),
             'evaluated':len(audit),'qualified':len(generated),'selected_new':sum(p['portfolio_selected'] for p in generated),
             'coverage':'See unavailable/rejected snapshots; missing data is not a failed formation',
             'rule_hash':digest(cfg),'benchmark':cfg['benchmark'],'benchmark_hash':digest(bench)}
    details['phase']='Market Hours' if live else 'Premarket'
    (Path(out)/('radar-'+key.replace(':','-').replace(' ','-')+'.json')).write_text(json.dumps({'summary':details,'audit':audit,'plans':generated},indent=2))
    store.journal_once(key,'Preparation Complete',frozen.isoformat(),details)
    return generated

def stamp_day(value):return datetime.fromisoformat(value).astimezone(IST).date()
