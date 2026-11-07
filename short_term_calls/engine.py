"""Conservative one-minute reconstruction of the frozen 15-minute entry rule."""
import hashlib
import json
import math
from datetime import datetime, timedelta, time, date, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    IST = ZoneInfo('Asia/Kolkata')
except ZoneInfoNotFoundError:
    IST = timezone(timedelta(hours=5,minutes=30), 'IST')
VERSION = 'short-term-paper-v2-unit-share'
HOLIDAYS = {'2026-10-20', '2026-11-10', '2026-11-24', '2026-12-25'}
FIRST, LAST = date(2026, 10, 7), date(2026, 12, 31)


def stamp(value):
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() is None:
        raise ValueError('Timezone required')
    return dt.astimezone(IST)


def session(day):
    if not FIRST <= day <= LAST:
        raise ValueError('Calendar needs renewal beyond verified November–December 2026')
    return day.weekday() < 5 and day.isoformat() not in HOLIDAYS


def trading_day(day, count):
    while count:
        day += timedelta(days=1)
        if session(day): count -= 1
    return day


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def number(value):
    n = D(str(value))
    if not n.is_finite(): raise ValueError('Nonfinite price')
    return n


def validate_plan(p):
    for k in ('id','symbol','type','issued_at','start_at','enter_by','exit_by','observe_until',
              'trigger','entry_min','entry_max','stop','target_1','target_2','source','rationale','policy'):
        if k not in p: raise ValueError('Missing plan field: '+k)
    times = [stamp(p[k]) for k in ('issued_at','start_at','enter_by','exit_by','observe_until')]
    if not times[0] < times[1] < times[2] < times[3] < times[4]:
        raise ValueError('Invalid chronology')
    if p['type'] not in ('Intraday','Swing') or not p['symbol'].startswith('NSE:') or not p['symbol'].endswith('-EQ'):
        raise ValueError('Only NSE cash long plans supported')
    if p['type']=='Intraday' and times[1].date()!=times[3].date():
        raise ValueError('Intraday holding crosses session')
    for dt in times[1:]:
        if not session(dt.date()) or not time(9,15)<=dt.time().replace(tzinfo=None)<=time(15,30):
            raise ValueError('Deadline must be a normal session timestamp')
    prices = [number(p[k]) for k in ('stop','trigger','entry_min','entry_max','target_1','target_2')]
    if not 0 < prices[0] < prices[1] <= prices[2] <= prices[3] < prices[4] < prices[5]:
        raise ValueError('Invalid long levels')
    if p['policy']!='Full Exit At T1': raise ValueError('Unimplemented exit policy')
    if p.get('quantity') is not None and (type(p['quantity']) is not int or p['quantity']<=0):
        raise ValueError('Invalid quantity')
    if p.get('total_costs') is not None and number(p['total_costs'])<0:
        raise ValueError('Negative costs')
    if (times[4]-times[1]).days>45: raise ValueError('Observation window exceeds 45 days')


def candles(raw, as_of):
    """FYERS timestamps are candle starts. Discard incomplete minutes, reject conflicts."""
    rows = {}
    for r in raw:
        if len(r)<6 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in r[:6]):
            raise ValueError('Malformed candle')
        ts,o,h,l,c,v = r[:6]
        if ts!=int(ts) or int(ts)%60 or v<0 or not 0<l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('Invalid candle')
        at=datetime.fromtimestamp(ts,IST)
        if ts in rows and rows[ts]!=r[:6]: raise ValueError('Conflicting candle revision')
        if at+timedelta(minutes=1)<=as_of and time(9,15)<=at.time().replace(tzinfo=None)<time(15,30):
            # Special sessions are not eligible for this normal-session strategy.
            if session(at.date()): rows[ts]=r[:6]
    return [rows[k] for k in sorted(rows)]


def expected_minutes(start, end):
    day=start.date()
    while day<=end.date():
        if session(day):
            at=max(start,datetime.combine(day,time(9,15),IST))
            finish=min(end,datetime.combine(day,time(15,30),IST))
            while at+timedelta(minutes=1)<=finish:
                yield int(at.timestamp())
                at+=timedelta(minutes=1)
        day+=timedelta(days=1)


def replay(p, raw, as_of):
    validate_plan(p)
    now=stamp(as_of)
    start,enter_by,exit_by,observe=map(stamp,(p['start_at'],p['enter_by'],p['exit_by'],p['observe_until']))
    # Cancellation starts with the first fully observable minute after issue,
    # even when the prospective signal window opens a few minutes later.
    monitor_start=stamp(p['issued_at']).replace(second=0,microsecond=0)+timedelta(minutes=1)
    stop,trigger,lo,hi,t1,t2=map(lambda k:number(p[k]),('stop','trigger','entry_min','entry_max','target_1','target_2'))
    rows=candles(raw,now)
    data={r[0]:r for r in rows}
    expected=list(expected_minutes(monitor_start,min(now,observe)))
    missing=[t for t in expected if t not in data]
    first_gap=missing[0] if missing else None
    events=[]
    seen=set()
    def event(kind,at,price=None,detail=''):
        key=digest([p['id'],kind,at])[:24]
        if key in seen:return
        seen.add(key)
        events.append({'id':key,'call_id':p['id'],'kind':kind,'at':at,
                       'price':'' if price is None else str(price),'detail':detail})
    state='Scheduled' if now<start else 'Waiting For Breakout'
    if p.get('status','Active')!='Active': state='Needs Revalidation'
    breakout=confirm=None
    retest_seen=False
    retest_bar_seen=False
    entry=entry_at=exit_price=exit_at=None
    exit_reason=''
    ambiguous=False
    upper=lower=None
    group=[]
    previous_bucket=None
    last_price=last_at=None
    t2_first_touch=None
    missed=[]
    post=[]
    for ts,o,h,l,c,v in rows:
        at=datetime.fromtimestamp(ts,IST)
        end=at+timedelta(minutes=1)
        if at<monitor_start or at>=observe:continue
        o,h,l,c=map(number,(o,h,l,c))
        iso=at.isoformat()
        last_price,last_at=c,iso
        gap_before=first_gap is not None and ts>first_gap
        if entry is None:
            if at>enter_by and state not in ('Cancelled','Needs Revalidation'):
                state='Expired Unfilled'
            if gap_before and state not in ('Cancelled','Expired Unfilled','Needs Revalidation'):
                state='Data Incomplete'
            # A confirmation is usable only at/after its completed close.
            eligible=state=='Confirmed' and confirm is not None and at>=confirm and at<=enter_by
            if eligible and lo<=o<=hi:
                entry,entry_at,state=o,at,'Open'
                event('Paper Entry',iso,o,'Next available one-minute open inside band; reconstructed, not broker fill')
            elif state not in ('Cancelled','Expired Unfilled','Needs Revalidation','Data Incomplete') and at<=enter_by and l<=stop:
                state='Cancelled'
                event('Stop Before Entry',iso,stop,'Touch occurs within this minute')
            if entry is None:
                prior_retest=retest_seen
                touched_retest=breakout is not None and at>=breakout and l<=hi and h>=lo
                if touched_retest:retest_seen=True
                for label,level in [('T1',t1),('T2',t2)]:
                    if h>=level and label not in missed:
                        missed.append(label)
                        phase=('After Cancellation' if state=='Cancelled' else
                               'After Entry Deadline' if at>enter_by else
                               'Needs Revalidation' if state=='Needs Revalidation' else
                               'Before Breakout Confirmation' if breakout is None else
                               'Retest And Target In Same Minute; Ordering Unknown' if touched_retest and not prior_retest else
                               'Breakout Without Retest' if not retest_seen else
                               'Retest Without Valid Entry')
                        event('Missed '+label,iso,level,phase+'; no trading P&L')
        if entry is not None and h>=t2 and t2_first_touch is None:
            t2_first_touch=iso
            event('T2 Observed After Entry',iso,t2,'Reached within this minute, including possible exit minute; exact ordering relative to stop/exit may be unknown. Observation only, not extra booked profit.')
        if entry is not None and exit_at is None and not ambiguous:
            if gap_before:
                ambiguous=True;state='Review Required';exit_reason='Data Gap After Entry'
                event('Review Required',iso,detail=exit_reason)
            else:
                # Exit deadlines use the first available minute open, before its later range.
                reason=price=None
                if at>=exit_by:reason,price='Time Exit',o
                elif o<=stop:reason,price='Gap Stop',o
                elif o>=t1:reason,price='Target 1',t1
                elif l<=stop and h>=t1:
                    ambiguous=True;state='Review Required';exit_reason='Stop And Target In Same Minute'
                    event('Review Required',iso,detail=exit_reason)
                elif l<=stop:reason,price='Stop',stop
                elif h>=t1:reason,price='Target 1',t1
                upper=max(upper if upper is not None else entry,h)
                lower=min(lower if lower is not None else entry,l)
                if reason:
                    exit_price,exit_at,exit_reason,state=price,at,reason,'Closed'
                    event(reason,iso,price,'One-minute reconstruction; exit minute excluded from post-exit touches')
        elif exit_at is not None and at>exit_at:
            for label,hit,level in [('T1',h>=t1,t1),('T2',h>=t2,t2),('Stop',l<=stop,stop)]:
                if hit and label not in post:
                    post.append(label);event('Post Exit '+label,iso,level,'Observed in this minute; original P&L unchanged')
        # Build complete exchange-aligned 15-minute bars, never across a missing minute.
        bucket=(at.hour*60+at.minute-555)//15
        bucket_key=(at.date(),bucket)
        if bucket_key!=previous_bucket: group=[];previous_bucket=bucket_key
        group.append((at,o,h,l,c))
        boundary=(end.hour*60+end.minute-555)%15==0
        complete=len(group)==15 and group[0][0]+timedelta(minutes=15)==end
        if not (boundary and complete and group[0][0]>=start and entry is None and at<=enter_by):continue
        if state in ('Cancelled','Expired Unfilled','Needs Revalidation','Data Incomplete'):continue
        close=group[-1][4]
        if breakout is None:
            if close>trigger:
                breakout=end;state='Waiting For Retest'
                event('Breakout',end.isoformat(),close,'Completed 15-minute close strictly above trigger')
        elif group[0][0]>=breakout:
            if min(x[3] for x in group)<=hi and max(x[2] for x in group)>=lo:
                retest_bar_seen=True
                event('Retest',end.isoformat(),close,'A later completed 15-minute bar overlaps the entry range')
            if retest_bar_seen and trigger<close and lo<=close<=hi:
                confirm=end;state='Confirmed'
                event('Confirmation',end.isoformat(),close,'Actual reconstructed entry must still be inside band')
            else:
                confirm=None;state='Waiting For Confirmation' if retest_bar_seen else 'Waiting For Retest'
    if entry is None and now>enter_by and state not in ('Cancelled','Needs Revalidation','Data Incomplete'):
        state='Expired Unfilled'
    if first_gap is not None:
        event('Coverage Gap',datetime.fromtimestamp(first_gap,IST).isoformat(),detail=f'{len(missing)} expected normal-session minutes missing; no assumed fills across gap')
        if entry is None and state not in ('Cancelled','Needs Revalidation'):state='Data Incomplete'
    if entry is not None and exit_at is None and not ambiguous and now>exit_by:
        state='Review Required';exit_reason='Missing Deadline Exit'
    gross_per_share=None if exit_price is None else exit_price-entry
    gross=None if gross_per_share is None or p.get('quantity') is None else gross_per_share*p['quantity']
    costs=None
    if gross is not None:
        if p.get('total_costs') is not None:costs=number(p['total_costs'])
        elif p.get('cost_model'):
            from .portfolio import estimated_costs
            costs=estimated_costs(p,entry,exit_price)
    net=None if gross is None or costs is None else gross-costs
    risk=None if entry is None else entry-stop
    return {'call_id':p['id'],'status':state,'breakout':None if breakout is None else breakout.isoformat(),
            'retest_observed':retest_seen,'confirmation':None if confirm is None else confirm.isoformat(),
            'entry_at':None if entry_at is None else entry_at.isoformat(),'entry_price':None if entry is None else str(entry),
            'exit_at':None if exit_at is None else exit_at.isoformat(),'exit_price':None if exit_price is None else str(exit_price),
            'exit_reason':exit_reason,'gross_per_share':None if gross_per_share is None else str(gross_per_share),
            'gross_pnl':None if gross is None else str(gross),'net_pnl':None if net is None else str(net),
            'gross_return_pct':None if gross_per_share is None else str(100*gross_per_share/entry),
            'estimated_costs':None if costs is None else str(costs),
            'net_return_pct':None if net is None else str(100*net/(entry*p['quantity'])),
            'planned_t1_r':str((t1-hi)/(hi-stop)),'planned_t2_r':str((t2-hi)/(hi-stop)),
            'realized_r':None if gross_per_share is None else str(gross_per_share/risk),
            't2_observed_after_entry':t2_first_touch is not None,'t2_first_touch_at':t2_first_touch,
            'last_price':None if last_price is None else str(last_price),'last_at':last_at,
            'observed_mfe_through_exit_minute':None if upper is None else str(upper-entry),
            'observed_mae_through_exit_minute':None if lower is None else str(entry-lower),
            'missed_targets':missed,'post_exit_touches':post,'missing_minutes':len(missing),
            'as_of':as_of,'events':events,'evidence_hash':digest(raw),'method':'One-minute candle reconstruction, not broker fills'}
