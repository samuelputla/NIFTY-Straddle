"""New, unvalidated automatic selection rule; preserves the established entry sequence."""
from datetime import datetime,timedelta,time
import json
from pathlib import Path
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from .engine import IST, session, trading_day, validate_plan, VERSION
from .providers import bhavcopy, DataUnavailable

DEFAULTS={'min_price':50,'min_turnover_cr':100,'candidate_count':0,
          'max_5session_rally_pct':12,
          'intraday_max_risk_pct':2.5,'swing_max_risk_pct':5,
          'min_risk_pct':0.3,'entry_band_pct':0.15,'trigger_buffer_pct':0.05,
          'swing_holding_sessions':5,'post_exit_sessions':5}


def tick(value,up=True):
    # Rs 0.05 is an experiment's level grid, not a claim about each instrument's current exchange tick.
    d=Decimal(str(value))
    return float((d/Decimal('0.05')).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*Decimal('0.05'))


def daily_candidates(day,output,config):
    days=[];d=day-timedelta(days=1)
    while len(days)<6:
        # Muhurat prices matter to Monday resistance; exclude this short session from normal volume means.
        if d.isoformat()=='2026-11-08' or session(d):days.append(d)
        d-=timedelta(days=1)
    histories=[(d,bhavcopy(d,output)) for d in reversed(days)]
    candidates=[];audit=[]
    latest=histories[-1][1]
    for symbol,r in latest.items():
        name=r['FinInstrmNm'].upper()
        if any(x in name for x in ('ETF','EXCHANGE TRADED','MUTUAL FUND','REIT','INVIT')) or 'BEES' in symbol:
            audit.append({'symbol':symbol,'stage':'Universe','outcome':'Excluded','reason':'Fund, ETF or trust'});continue
        observations=[(d,rs[symbol]) for d,rs in histories if symbol in rs]
        if len(observations)!=6:
            audit.append({'symbol':symbol,'stage':'Universe','outcome':'Excluded','reason':'Insufficient six-session evidence'});continue
        try:
            closes=[float(x['ClsPric']) for _,x in observations]
            normal=[x for d,x in observations if d.isoformat()!='2026-11-08']
            close=closes[-1];turnover=float(normal[-1]['TtlTrfVal'])/1e7
            volume=int(normal[-1]['TtlTradgVol'])
            average=sum(int(x['TtlTradgVol']) for x in normal[:-1])/len(normal[:-1])
            highs=[float(x['HghPric']) for _,x in observations]
            lows=[float(x['LwPric']) for _,x in observations]
            momentum=100*(close/closes[0]-1)
            if close<config['min_price'] or turnover<config['min_turnover_cr'] or average<=0:
                audit.append({'symbol':symbol,'stage':'Universe','outcome':'Excluded','reason':'Price, liquidity or volume evidence filter'});continue
            if not 0<momentum<=config['max_5session_rally_pct']:
                audit.append({'symbol':symbol,'stage':'Universe','outcome':'Excluded','reason':'Nonpositive momentum or extended beyond versioned rally limit'});continue
            location=(close-lows[-1])/max(.05,highs[-1]-lows[-1])
            rvol=volume/average
            # Ranking context, not a verified prediction probability. Avoid simply chasing the biggest gainer.
            score=2*location+min(rvol,3)*.5+min(momentum,6)*.1-max(0,momentum-6)*.15
            candidates.append({'symbol':symbol,'close':close,'high':max(highs[-3:]),
                'support':min(lows[-3:]),'turnover_cr':round(turnover,2),
                'recent_relative_volume':round(rvol,3),'momentum_pct':round(momentum,3),
                'close_location':round(location,3),'ranking_score':round(score,4),
                'data_dates':[str(d) for d,_ in observations],
                'volume_note':'Normal-session volume only; short Muhurat session excluded'})
            audit.append({'symbol':symbol,'stage':'Universe','outcome':'Candidate','reason':'Daily price/volume filters passed'})
        except (ValueError,KeyError,ZeroDivisionError):
            audit.append({'symbol':symbol,'stage':'Universe','outcome':'Excluded','reason':'Malformed numerical evidence'})
    (Path(output)/'universe_audit.json').write_text(json.dumps(audit,indent=2))
    ordered=sorted(candidates,key=lambda x:(-x['ranking_score'],x['symbol']))
    return ordered[:config['candidate_count']] if config['candidate_count'] else ordered


def make_plan(candidate,kind,minutes,now,config,reject=None):
    def rejected(reason):
        if reject:reject(reason)
        return None
    day=now.date()
    opening=[r for r in minutes if datetime.fromtimestamp(r[0],IST).date()==day and
             time(9,15)<=datetime.fromtimestamp(r[0],IST).time().replace(tzinfo=None)<time(9,45)]
    if len(opening)!=30:return rejected('Incomplete opening 30-minute evidence')
    opening=sorted(opening)
    if opening[-1][0]-opening[0][0]!=29*60:return rejected('Noncontiguous opening evidence')
    if datetime.fromtimestamp(minutes[-1][0],IST)+timedelta(minutes=1)<now-timedelta(minutes=2):
        return rejected('Recent minute data is stale')
    opening_high=max(r[2] for r in opening);opening_low=min(r[3] for r in opening)
    reference=max(candidate['high'],opening_high)
    trigger=tick(reference*(1+config['trigger_buffer_pct']/100))
    top=tick(trigger*(1+config['entry_band_pct']/100))
    support=opening_low if kind=='Intraday' else min(candidate['support'],opening_low)
    stop=tick(support*.9995,False)
    risk=top-stop
    risk_pct=100*risk/top
    maximum=config['intraday_max_risk_pct'] if kind=='Intraday' else config['swing_max_risk_pct']
    # Fresh price must not already have passed the proposed buy band or invalidation.
    if minutes[-1][4]>top:return rejected('Already above permitted entry band; no chasing')
    if minutes[-1][4]<=stop:return rejected('Support already invalidated')
    if not config['min_risk_pct']<=risk_pct<=maximum:return rejected('Risk distance outside versioned research limits')
    exit_day=day if kind=='Intraday' else trading_day(day,config['swing_holding_sessions']-1)
    observe_day=trading_day(exit_day,config['post_exit_sessions'])
    issued=now.replace(microsecond=0)
    start=issued.replace(second=0)+timedelta(minutes=1)
    p={'id':f'ST-{day:%Y%m%d}-{candidate["symbol"]}-{kind.upper()}-V1',
       'symbol':'NSE:'+candidate['symbol']+'-EQ','type':kind,'status':'Active',
       'issued_at':issued.isoformat(),'start_at':start.isoformat(),
       'enter_by':datetime.combine(day,time(12,30),IST).isoformat(),
       'exit_by':datetime.combine(exit_day,time(15,0),IST).isoformat(),
       'observe_until':datetime.combine(observe_day,time(15,30),IST).isoformat(),
       'trigger':trigger,'entry_min':trigger,'entry_max':top,'stop':stop,
       'target_1':tick(top+risk),'target_2':tick(top+2*risk),
       'quantity':None,'total_costs':None,'policy':'Full Exit At T1',
       'source':'Automated Price And Volume Research V1',
       'rationale':f'Recent resistance {reference:.2f}; support {support:.2f}; '+
          f'normal-session turnover Rs {candidate["turnover_cr"]:.2f} crore; '+
          f'recent relative volume {candidate["recent_relative_volume"]:.2f}. '+
          'Fresh completed 15-minute breakout, later retest and in-band confirmation required. '+
          'Targets are 1R/2R planning distances at maximum entry, not forecast prices.',
       'limitations':'Automatic price/volume experiment, not validated discretionary replication. '+
          'Fundamentals, news, volume-at-price profile and executable spread/depth not verified. '+
          'Per-share paper simulation only; no calibrated win probability.',
       'research_version':VERSION,'selection_evidence':candidate}
    validate_plan(p)
    return p
