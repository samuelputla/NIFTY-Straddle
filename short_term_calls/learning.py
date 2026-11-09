"""Evidence-backed loss/miss reviews; never change sealed calls or auto-fit a rule."""
import json
from datetime import datetime,time
from pathlib import Path
from .engine import IST,digest,stamp
from .providers import bhavcopy

def review(plan,result):
    evidence=plan.get('selection_evidence',{})
    stopped=result.get('exit_reason') in ('Stop','Gap Stop')
    incomplete=result.get('status') in ('Data Incomplete','Review Required')
    missed=result.get('entry_price') in (None,'') and bool(result.get('missed_targets'))
    if not (stopped or incomplete or missed):return None
    hypotheses=[]
    if stopped:
        hypotheses.append('Original technical invalidation reached; loss alone does not prove a coding or selection error')
        if result.get('exit_reason')=='Gap Stop':hypotheses.append('Opening gap exceeded planned stop; execution-risk observation')
        if evidence.get('rvol20_normal',99)<1.5:hypotheses.append('Test higher RVOL threshold against winners and losers; not an established cause')
        if evidence.get('excess20',0)<0:hypotheses.append('Recovery lagged benchmark at selection; test excluding recovery setups separately')
    if incomplete:hypotheses.append('Data/ordering gap; withhold definitive outcome and repair source evidence first')
    if missed:hypotheses.append('Target without valid entry; compare breakout-only versus retest rules prospectively, not fictitious profit')
    return {'call_id':plan['id'],'rule':plan.get('research_version','Legacy'),
            'kind':'Data Review' if incomplete else 'Stop Review' if stopped else 'Missed Entry Review',
            'original_plan_hash':digest(plan),'selection_evidence':evidence,
            'entry_at':result.get('entry_at'),'exit_at':result.get('exit_at'),
            'exit_reason':result.get('exit_reason'),'realized_r':result.get('realized_r'),
            'missing_minutes':result.get('missing_minutes'),'missed_targets':result.get('missed_targets',[]),
            'post_exit_touches':result.get('post_exit_touches',[]),'hypotheses':hypotheses,
            'cause':'Unresolved; no verified company-news cause is inferred from candle prices',
            'action':'Fix demonstrated data/code errors; keep predictive rule changes as separately versioned challengers until forward validation.'}

def save_reviews(store,plans,results,out,now):
    lookup={p['id']:p for p in plans};reviews=[]
    for r in results:
        item=review(lookup[r['call_id']],r)
        if item:
            # A new evidence version is appended when post-exit evidence changes.
            subject=r['call_id']+':'+digest(item)[:12]
            store.journal_once(subject,item['kind'],now.isoformat(),item)
            reviews.append(item)
    (Path(out)/'learning-reviews.json').write_text(json.dumps(reviews,indent=2))

def challenger_report(plans,results):
    """Descriptive filtered cohorts, NOT a counterfactual strategy backtest."""
    rows=[]
    for p in plans:
        r=results.get(p['id'],{})
        if r.get('status')!='Closed' or r.get('realized_r') in (None,''):continue
        f=p.get('selection_evidence',{})
        if 'rvol20_normal' not in f or 'excess20' not in f:continue
        rows.append((p,r,f))
    variants={'Baseline':lambda f:True,'RVOL At Least 1.5':lambda f:f['rvol20_normal']>=1.5,
              'Positive Relative Strength Only':lambda f:f['excess20']>0}
    cohorts=[]
    for name,fn in variants.items():
        chosen=[(p,r) for p,r,f in rows if fn(f)]
        cohorts.append({'hypothesis':name,'closed_calls':len(chosen),'sessions':len({p.get('target_session',p['start_at'][:10]) for p,r in chosen}),
                        'mean_observed_r':None if not chosen else sum(float(r['realized_r']) for p,r in chosen)/len(chosen),
                        'removed_calls':len(rows)-len(chosen)})
    return {'cohorts':cohorts,'promotion':'Not Promoted','reason':'No chronological holdout/forward challenger validation. Filtered existing outcomes do not model changed fills, cash, overlap or costs.',
            'next_test':'Freeze a separate challenger before new sessions; compare all selected, rejected, missed, unfilled and ambiguous cases. No automatic source-code rewrite.'}

def market_audit(store,day,plans,out,now):
    """Ex-post coverage across liquid NSE stocks; not backdated trade signals."""
    rows=bhavcopy(day,out);leaders=[]
    snapshots={}
    for r in store.cache.snapshot('Short Term Events')[1:]:
        if len(r)<6 or r[2]!='Radar Snapshot':continue
        data=json.loads(r[5])
        if data.get('target_session')==day.isoformat() and stamp(r[3])<datetime.combine(day,time(9,15),IST):
            snapshots[data['symbol']]=data
    for sym,r in rows.items():
        try:
            prev=float(r['PrvsClsgPric']);close=float(r['ClsPric']);turn=float(r['TtlTrfVal'])/1e7
            if close<50 or turn<100 or prev<=0:continue
            name=r.get('FinInstrmNm','').upper()
            if any(x in name for x in ('ETF','MUTUAL FUND','REIT','INVIT')) or 'BEES' in sym:continue
            ret=100*(close/prev-1)
            if ret>0:leaders.append((ret,sym))
        except (ValueError,KeyError):continue
    observations=[]
    for ret,sym in sorted(leaders,key=lambda x:(-x[0],x[1]))[:10]:
        issued=[p for p in plans if p['symbol']=='NSE:'+sym+'-EQ' and p['start_at'][:10]==day.isoformat()]
        original=snapshots.get(sym)
        label='Selected' if any(p.get('portfolio_selected') for p in issued) else 'Qualified Research Unselected' if issued else 'Rejected By Frozen Screen' if original else 'Outside Bounded Radar; Formation Unknown'
        record={'symbol':sym,'close_to_close_return_pct':ret,'coverage':label,
                'original_reasons':original.get('reasons',[]) if original else ['Not evaluated prospectively; do not invent formation or entry'],
                'interpretation':'Retrospective daily leader; not executable profit or a backdated call'}
        store.journal_once(day.isoformat()+':'+sym,'Market Leader Review',now.isoformat(),record)
        observations.append(record)
    store.journal_once(day.isoformat(),'Market Coverage Audit',now.isoformat(),{'leaders':len(observations),'method':'Top ten positive close-to-close liquid NSE stocks; filters use outcome-day data only for retrospective coverage, never selection'})
    (Path(out)/('market-audit-'+day.isoformat()+'.json')).write_text(json.dumps(observations,indent=2))
