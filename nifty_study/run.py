"""python -m nifty_study.run [--connection-check]. Read-only broker research."""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from xml.etree import ElementTree
from email.utils import parsedate_to_datetime
from .calendar import session, next_session
from .research import diagnose, research_history
from .filings import collect, timestamp
from .core import IST, RULE, TOP, RULE_SPEC, digest, daily_features, intraday_features, screen, ranked, review_outcome
from .adapters import Fyers, Sheets, Unavailable, public_get, fetch_universe

OUT=Path('nifty-study-report')
NEWS_URL='https://nsearchives.nseindia.com/content/RSS/Corporate_Announcements.xml'

def save(name,value):
    OUT.mkdir(exist_ok=True)
    (OUT/name).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')

def news_evidence(text,members,now):
    """RSS is discovery only. Never convert a title into verified factual evidence."""
    root=ElementTree.fromstring(text)
    rows=[]
    for item in root.findall('.//item'):
        title=item.findtext('title','').strip()
        link=item.findtext('link','').strip()
        try:
            published=parsedate_to_datetime(item.findtext('pubDate','')).astimezone(IST)
        except (TypeError,ValueError,AttributeError):
            continue
        if not now-timedelta(days=3)<=published<=now:
            continue
        for m in members:
            company=m.get('Company Name','').lower().removesuffix(' ltd.').removesuffix(' limited').strip()
            if company and (company in title.lower() or title.upper().startswith(m['Symbol']+' ')):
                rows.append([digest([link,m['Symbol'],str(published)])[:20],m['Symbol'],'NEWS LEAD',
                             published.isoformat(),now.isoformat(),link,title,False,'','','',''])
    return rows

def eligible_evidence(rows,now,symbol):
    result=[]
    for r in rows:
        if r.get('Symbol')!=symbol or str(r.get('Verified')).lower()!='true':
            continue
        try:
            published=datetime.fromisoformat(r['Published At'])
            observed=datetime.fromisoformat(r['Observed At'])
            if published.tzinfo is None or observed.tzinfo is None or max(published,observed)>now:
                continue
        except (KeyError,ValueError):
            continue
        if not r.get('Source URL','').startswith('https://'):
            continue
        result.append({k:r.get(k,'') for k in ['Category','Published At','Source URL','Finding','Metric','Value','Period','Basis']})
    return result

def return_ranks(rows,metric):
    return {r['symbol']:i+1 for i,r in enumerate(ranked(rows,metric))}

TECHNICAL_FIELDS = ('close', 'volume', 'rvol20', 'sma20', 'sma50', 'rsi14', 'macd',
                    'signal', 'atr14', 'adx14', 'stoch14', 'resistance', 'support', 'breakout',
                    'rs20', 'sector_rs', 'weekly', 'trend15', 'trend60', 'vwap', 'poc', 'zone')


def evaluate(prior,rows,day,key):
    """Never score an untrusted late/backdated record as a prospective forecast."""
    ranks=return_ranks(rows,'return');by_symbol={r['symbol']:r for r in rows}
    groups={}
    for p in prior:
        if p.get('Target Session')==day:
            groups.setdefault(p['Forecast ID'],[]).append(p)
    reviews=[];changes=[];summaries=[]
    for fid,forecast in groups.items():
        if len(forecast)!=50 or len({p['Symbol'] for p in forecast})!=50:
            summaries.append('Incomplete stored forecast '+fid);continue
        if sum(p.get('Selected','').lower()=='true' for p in forecast)!=TOP:
            summaries.append('Invalid selected count '+fid);continue
        opening=datetime.fromisoformat(day+'T'+session(day)['open']+':00+05:30')
        try:
            if any(datetime.fromisoformat(p['Created At']).tzinfo is None or datetime.fromisoformat(p['Created At'])>=opening for p in forecast):
                summaries.append('Late forecast excluded '+fid);continue
        except (ValueError,KeyError):
            summaries.append('Invalid forecast timestamps '+fid);continue
        if {p['Symbol'] for p in forecast}!=set(by_symbol):
            summaries.append('Universe changed; forecast not scored '+fid);continue
        hits=0
        for p in forecast:
            symbol=p['Symbol'];r=by_symbol[symbol];selected=p['Selected'].lower()=='true'
            outcome=review_outcome(selected,ranks[symbol]);hits+=outcome=='HIT'
            diagnostic=diagnose(p,forecast,r,outcome)
            if outcome == 'MISSED LEADER':
                try:
                    frozen = json.loads(p.get('Reasons') or '{}')
                except (ValueError, TypeError):
                    frozen = {}
                if not isinstance(frozen, dict):
                    frozen = {}
                diagnostic['known_before_session']['technical_snapshot'] = frozen.get('technical_snapshot', {})
                diagnostic['observed_during_session']['technical_snapshot'] = {
                    field: r.get(field) for field in TECHNICAL_FIELDS}
                cutoff = datetime.fromisoformat(p['Created At'])
                context = r.get('exchange_research', {})
                evidence = {}
                for category in ('announcements', 'financial_filings'):
                    known, later = [], []
                    for item in context.get(category, []):
                        published = timestamp(item.get('published_at'))
                        if published:
                            (known if published <= cutoff else later).append(item)
                    evidence[category] = {'public_by_forecast_cutoff': known,
                                          'public_after_forecast_cutoff': later}
                diagnostic['exchange_research'] = evidence
                diagnostic['research_gaps'] = context.get('gaps', ['Exchange research not collected'])
                if not diagnostic['known_before_session']['technical_snapshot']:
                    diagnostic['research_gaps'] = [*diagnostic['research_gaps'], 'Older forecast has no frozen technical snapshot']
            explanation=json.dumps(diagnostic,sort_keys=True)
            reviews.append([key+':'+fid+':'+symbol,day,fid,symbol,selected,ranks[symbol],r['return'],r['gap'],r['intraday'],outcome,explanation,p['Rule Version']])
            if outcome in ('FALSE POSITIVE','MISSED LEADER'):
                changes.append([key+':'+fid+':'+symbol,day,symbol,outcome,json.dumps(diagnostic,sort_keys=True),
                                'Replicated feature/catalyst evidence across controls and future sessions','PROPOSED REVIEW',p['Rule Version']])
        baseline={}
        for label,col in [('prior winners','Baseline Prior Winner Rank'),('momentum','Baseline Momentum Rank'),('sector','Baseline Sector Rank')]:
            chosen=[p for p in forecast if int(p[col])<=TOP]
            baseline[label]=sum(ranks[p['Symbol']]<=TOP for p in chosen)/TOP
        summaries.append({'forecast':fid,'precision_at_5':hits/TOP,'random_expected_precision':TOP/50,'benchmarks':baseline,
                          'selected_mean_return':mean(by_symbol[p['Symbol']]['return'] for p in forecast if p['Selected'].lower()=='true'),
                          'sample':'one session; no profitability or predictive validation'})
    return reviews,changes,summaries

def execute(connection_check=False):
    from .session_date import collection_day
    now=datetime.now(IST);day=collection_day(now,scheduled=os.getenv('GITHUB_EVENT_NAME')=='schedule' and not connection_check);OUT.mkdir(exist_ok=True)
    sheet=Sheets()
    key=('connection-equities:' if connection_check else 'daily:')+day+':'+RULE
    if sheet.has_run(key):
        return {'status':'ALREADY RECORDED','key':key}
    token=os.getenv('FYERS_ACCESS_TOKEN','').strip()
    if not token:
        raise Unavailable('FYERS access token unavailable in workflow secret')
    fyers=Fyers(token,OUT/'raw')
    if connection_check:
        # Read the preceding calendar week only; this is authentication evidence, not a forecast.
        history=fyers.history('NSE:NIFTY50-INDEX',day,lookback=7)
        if not history:
            raise Unavailable('Connection check returned no index candles')
        _,members,source=fetch_universe()
        expected=str(datetime.fromtimestamp(history[-1][0],IST).date())
        index_history=fyers.history('NSE:NIFTY50-INDEX',day)
        verified_symbols=[]
        for m in members:
            bars=fyers.history('NSE:'+m['Symbol']+'-EQ',day)
            if str(datetime.fromtimestamp(bars[-1][0],IST).date())!=expected:
                raise Unavailable('Connection check: stock/index latest-session mismatch')
            daily_features(bars,index_history)
            verified_symbols.append(m['Symbol'])
        result={'status':'CONNECTION VERIFIED','session':day,'members':len(members),
                'message':'Index and all 50 equity daily histories/required features verified for latest provider session '+expected+'; no forecast created'}
        save('connection.json',dict(result,verified_symbols=verified_symbols,universe_source=source))
        sheet.publish(key,{'Study Runs':[[key,day,now.isoformat(),result['status'],50,'',RULE,digest(history),result['message'],run_url()]]})
        return result
    hours=session(day)
    if hours is None:
        return {'status':'NO EQUITY SESSION','session':day}
    if now<datetime.fromisoformat(day+'T16:15:00+05:30'):
        raise Unavailable('Post-session collection permitted only after 16:15 IST')
    target=next_session(day)
    target_open=datetime.fromisoformat(target+'T'+session(target)['open']+':00+05:30')
    member_text,members,universe_source=fetch_universe()
    (OUT/'constituents.csv').write_text(member_text,encoding='utf-8')
    index=fyers.history('NSE:NIFTY50-INDEX',day)
    index_dates=[str(datetime.fromtimestamp(b[0],IST).date()) for b in index]
    if index_dates[-1]!=day:
        raise Unavailable('Index source not finalized for requested session')
    previous=index_dates[-2]
    raw={};rows=[];issues=[];verified=sheet.records('Study Evidence')
    try:
        rss=public_get(NEWS_URL);(OUT/'announcements.xml').write_text(rss,encoding='utf-8')
        news=news_evidence(rss,members,now)
        seen={r['Evidence ID'] for r in verified};news=[r for r in news if r[0] not in seen]
    except (Unavailable,ElementTree.ParseError):
        news=[];issues.append('NSE announcement discovery unavailable; not evidence of no news')
    for m in members:
        symbol=m['Symbol'];bars=fyers.history('NSE:'+symbol+'-EQ',day)
        dates=[str(datetime.fromtimestamp(b[0],IST).date()) for b in bars]
        if dates[-2:]!=[previous,day] or dates[-100:]!=index_dates[-100:]:
            raise Unavailable('Daily session coverage mismatch for '+symbol)
        f=daily_features(bars,index);raw[symbol]=bars
        f.update(symbol=symbol,industry=m['Industry'],evidence=eligible_evidence(verified,now,symbol))
        f['coverage']='Daily FYERS provider close; adjustment status unverified; fundamentals/news only if verified evidence exists'
        f.update(trend15=None,trend60=None,vwap=None,poc=None)
        try:
            intraday=fyers.history('NSE:'+symbol+'-EQ',day,resolution='15',lookback=0)
            start=datetime.fromisoformat(day+'T'+hours['open']+':00+05:30')
            end=datetime.fromisoformat(day+'T'+hours['close']+':00+05:30')
            intraday=[b for b in intraday if start.timestamp()<=b[0]<end.timestamp()]
            # Auction periods can have no continuous candles; enforce coverage across the CTS core.
            expected_end=datetime.fromisoformat(day+'T15:15:00+05:30')
            expected={int(start.timestamp())+900*i for i in range(int((expected_end-start).total_seconds()//900))}
            if not expected.issubset({int(b[0]) for b in intraday}):
                raise ValueError('Intraday coverage incomplete')
            f.update(intraday_features(intraday))
        except (Unavailable,ValueError):
            f['coverage']+='; intraday unavailable'
        rows.append(f)
    for r in rows:
        peers=[p['momentum20'] for p in rows if p['industry']==r['industry'] and p['symbol']!=r['symbol']]
        r['sector20']=mean(peers) if peers else 0
        r['sector_rs']=r['momentum20']-r['sector20'] if peers else None
        if not peers:
            r['coverage']+='; no industry peers, sector feature neutral'
    scoring=screen(rows)
    prior_forecasts = sheet.records('Study Forecasts')
    prior_picks = {p['Symbol'] for p in prior_forecasts if p.get('Target Session') == day
                   and str(p.get('Selected')).lower() == 'true'}
    research_symbols = {r['symbol'] for r in ranked(rows,'return')[:TOP]} - prior_picks if prior_picks else set()
    research_as_of = min(datetime.now(IST), datetime.fromisoformat(day+'T23:59:59+05:30'))
    research = dict(collect(research_symbols, research_as_of, day)) if research_symbols else {}
    for r in rows:
        if r['symbol'] in research:
            r['exchange_research'] = research[r['symbol']]
    completed=datetime.now(IST)
    if completed>=target_open:
        raise Unavailable('Forecast cutoff missed; no prospective forecast published')
    universe_hash=digest(sorted(m['Symbol'] for m in members))
    input_hash=digest({'daily':raw,'index':index,'members':members,'rules':RULE_SPEC,
                       'derived_features_and_evidence':rows})
    fid=day+':'+target+':'+RULE
    actual_ranks=return_ranks(rows,'return');momentum=return_ranks(rows,'momentum20');sector=return_ranks(rows,'sector20')
    reviews,changes,evaluation=evaluate(prior_forecasts,rows,day,key)
    forecast=[];observations=[]
    for rank,r in enumerate(scoring,1):
        reasons=json.dumps({'features':{k:r[k] for k in RULE_SPEC['weights']},'score_parts':r['parts'],
                            'technical_snapshot':{field:r.get(field) for field in TECHNICAL_FIELDS}},sort_keys=True)
        forecast.append([fid,day,target,completed.isoformat(),RULE,universe_hash,input_hash,r['symbol'],rank,rank<=TOP,r['score'],reasons,r['coverage'],actual_ranks[r['symbol']],momentum[r['symbol']],sector[r['symbol']]])
        observations.append([key,day,r['symbol'],r['industry'],actual_ranks[r['symbol']],r['return'],r['gap'],r['intraday'],r['close'],r['volume'],r['rvol20'],r['sma20'],r['sma50'],r['rsi14'],r['macd'],r['signal'],r['atr14'],r['adx14'],r['stoch14'],r['resistance'],r['support'],r['breakout'],r['rs20'],r['sector_rs'],r['weekly'],r['trend15'],r['trend60'],r['vwap'],r['poc'],r['zone'],r['score'],json.dumps(r['evidence']),r['coverage']])
    leader_context=[{'symbol':r['symbol'],'return_pct':r['return'],'gap_pct':r['gap'],'open_to_close_pct':r['intraday'],
                     'prior_20_session_breakout':r['breakout'],'relative_volume':r['rvol20'],'rsi14':r['rsi14'],
                     'relative_strength_nifty_20_pp':r['rs20'],'verified_evidence_count':len(r['evidence']),
                     'interpretation':'Observed technical context; causation and pre-session predictability unestablished'}
                    for r in ranked(rows,'return')[:TOP]]
    history=research_history(sheet.records('Study Reviews'),reviews)
    focused_reviews=[{'symbol':r[3],'outcome':r[9],'actual_rank':r[5],
                      'return_pct':r[6],'analysis':json.loads(r[10])}
                     for r in reviews if r[9]!='CONTROL']
    findings={'research_history':history,'shortlist_review':focused_reviews,'leaders':[r['symbol'] for r in ranked(rows,'return')[:TOP]],'leader_context':leader_context,'next_candidates':[r['symbol'] for r in scoring[:TOP]],
              'evaluations':evaluation,'limitations':issues+['Exploratory price-volume-v1; no validated edge',
              'Industry peer basket is a proxy, not official sector index', 'Volume profile and VWAP approximated from 15-minute candles',
              'NSE filing and XBRL coverage is best effort; announcement descriptions are leads, and causation is unresolved',
              'Order-block zones are experimental; full weekly/multisession intraday study remains manual',
              'No automatic rule/skill promotion; misses create review proposals'], 'session_kind':hours['kind']}
    save('report.json',{'created_at':completed.isoformat(),'findings':findings,'observations':rows,'forecast':forecast,'reviews':reviews,'input_hash':input_hash})
    save('manifest.json',{'source':'FYERS history + official NIFTY constituent snapshot','observed_at':now.isoformat(),
                          'universe_source':universe_source,'universe_hash':universe_hash,'input_hash':input_hash,'rule_spec':RULE_SPEC,'session':day,
                          'target':target,'universe_scope':'current snapshot observed today; not a historical constituent reconstruction'})
    md=['# Nifty study',f'Session: {day}; target: {target}; frozen: {completed.isoformat()}',
        '## Actual leaders',', '.join(findings['leaders']),'## Observed leader context',json.dumps(leader_context,indent=2),'## Next-session paper candidates',', '.join(findings['next_candidates']),
        '## Forecast evaluation',json.dumps(evaluation),'## Five picks versus actual top five',json.dumps(focused_reviews,indent=2),
        '## Continuous research record',json.dumps(history,indent=2),'## Coverage and limitations',*['- '+x for x in findings['limitations']]]
    (OUT/'report.md').write_text('\n\n'.join(md),encoding='utf-8')
    sheet.publish(key,{'Study Observations':observations,'Study Forecasts':forecast,'Study Reviews':reviews,
                       'Study Evidence':news,'Study Changes':changes,'Study Runs':[[key,day,completed.isoformat(),'COMPLETED',50,target,RULE,input_hash,json.dumps({**findings, 'shortlist_review': [{**review, 'analysis': {k:v for k,v in review['analysis'].items() if k != 'exchange_research'}} for review in focused_reviews]}),run_url()]]})
    return {'status':'COMPLETED','session':day,'target':target,'leaders':findings['leaders'],'candidates':findings['next_candidates']}

def run_url():
    repo=os.getenv('GITHUB_REPOSITORY','samuelputla/NIFTY-Straddle')
    return 'https://github.com/'+repo+'/actions/runs/'+os.getenv('GITHUB_RUN_ID','local')

def record_failure(result):
    """Best-effort visibility in the existing Sheet; never fabricate a forecast."""
    now=datetime.now(IST)
    key='failure:'+os.getenv('GITHUB_RUN_ID',now.isoformat())+':'+RULE
    try:
        Sheets().publish(key,{'Study Runs':[[key,str(now.date()),now.isoformat(),'DATA UNAVAILABLE',
                          0,'',RULE,'',result['reason'],run_url()]]})
    except Exception:
        # Original failure evidence remains in the uploaded artifact even if Sheets is down.
        pass

def main():
    p=argparse.ArgumentParser();p.add_argument('--connection-check',action='store_true');args=p.parse_args()
    try:
        result=execute(args.connection_check);save('status.json',result)
        print(json.dumps(result))
        summary=os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary,'a',encoding='utf-8') as f:
                f.write((OUT/'report.md').read_text() if (OUT/'report.md').exists() else json.dumps(result))
        return 0
    except (Unavailable,ValueError,KeyError) as e:
        # Only our own sanitized error messages; never requests headers or credential objects.
        result={'status':'DATA UNAVAILABLE','reason':str(e)[:250]};save('status.json',result);record_failure(result);print(json.dumps(result));return 1
    except Exception:
        result={'status':'DATA UNAVAILABLE','reason':'Unexpected integration failure; inspect sanitized diagnostics'}
        save('status.json',result);record_failure(result)
        print('Study failed; integration requires review (secrets omitted)');return 1

if __name__=='__main__':
    sys.exit(main())


