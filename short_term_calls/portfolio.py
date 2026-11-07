"""Frozen prospective selection and cash-constrained sizing for a separate paper account."""
from datetime import datetime
from .engine import number,stamp


DEFAULT_PORTFOLIO={'initial_capital':300000,'daily_selection_count':3,
    'max_intraday_open':3,'max_swing_open':3,'risk_per_trade_pct':0.5,
    'max_trade_allocation_pct':15,'cash_reserve_pct':10,
    'cost_model':{'name':'Illustrative Total Friction V1','rate_per_side':0.0015,'fixed_round_trip':40}}


def estimated_costs(p,entry,exit_price):
    model=p.get('cost_model')
    if not model or not p.get('quantity'):return None
    return (number(entry)+number(exit_price))*p['quantity']*number(model['rate_per_side'])+number(model['fixed_round_trip'])


def select(plans,existing,results,now,settings):
    """Select before any new plan can enter; never use new calls' eventual outcomes."""
    if settings.get('quantity_mode')=='one_share':
        return select_one_share(plans,existing,results,settings)
    capital=number(settings['initial_capital'])
    reserve=number(0);realized=number(0);slots={'Intraday':0,'Swing':0}
    for p in existing:
        if not p.get('portfolio_selected'):continue
        result=results.get(p['id'],{})
        if result.get('net_pnl') not in (None,''):realized+=number(result['net_pnl'])
        inactive=result.get('status') in ('Closed','Cancelled','Expired Unfilled')
        if not inactive:
            reserve+=number(p['entry_max'])*p['quantity']
            slots[p['type']]+=1
    available=capital*(1-number(settings['cash_reserve_pct'])/100)+realized-reserve
    selected=0;used=set()
    # Rank is frozen price/volume score minus a modest risk-distance penalty; no outcome inputs.
    for p in plans:
        risk=number(p['entry_max'])-number(p['stop'])
        risk_pct=100*risk/number(p['entry_max'])
        p['portfolio_rank_score']=float(number(p['selection_evidence']['ranking_score'])-risk_pct/10)
    ordered=sorted(plans,key=lambda p:(-p['portfolio_rank_score'],p['symbol'],p['type']))
    for rank,p in enumerate(ordered,1):
        p['portfolio_rank']=rank;p['portfolio_selected']=False
        reason='Outside top-three available selections'
        if selected<settings['daily_selection_count'] and p['symbol'] not in used:
            limit=settings['max_intraday_open'] if p['type']=='Intraday' else settings['max_swing_open']
            if slots[p['type']]>=limit:reason='Paper account type slots already occupied'
            else:
                price=number(p['entry_max']);risk=price-number(p['stop'])
                allocation=min(capital*number(settings['max_trade_allocation_pct'])/100,available)
                # Reserve a conservative full-turnover friction allowance as well as purchase notional.
                model=settings['cost_model']
                friction_per_share=2*price*number(model['rate_per_side'])
                quantity=int(min((allocation-number(model['fixed_round_trip']))/(price+friction_per_share),
                    capital*number(settings['risk_per_trade_pct'])/100/(risk+friction_per_share))) if allocation>number(model['fixed_round_trip']) else 0
                if quantity>0:
                    p['quantity']=quantity;p['portfolio_selected']=True;p['cost_model']=dict(model)
                    p['portfolio_initial_capital']=float(capital)
                    selected+=1;used.add(p['symbol']);slots[p['type']]+=1
                    available-=price*quantity+(2*price*quantity*number(model['rate_per_side'])+number(model['fixed_round_trip']))
                    reason='Selected prospectively by frozen ranking, cash, risk and slot limits'
                else:reason='Insufficient paper capital for one share within limits'
        elif p['symbol'] in used:reason='Same stock already selected; other setup retained for research'
        p['portfolio_selection_reason']=reason
    return ordered


def summary(plans,results,settings,now):
    if settings.get('quantity_mode')=='one_share':
        return summary_one_share(plans,results,settings,now)
    capital=number(settings['initial_capital']);realized=number(0);unrealized=number(0)
    deployed=number(0);reserved=number(0);unknown=[];selected=0
    for p in plans:
        if not p.get('portfolio_selected'):continue
        selected+=1;r=results.get(p['id'],{})
        if r.get('status')=='Closed':
            if r.get('net_pnl') in (None,''):unknown.append(p['id'])
            else:realized+=number(r['net_pnl'])
        elif r.get('entry_price') not in (None,''):
            if r.get('status')=='Review Required':unknown.append(p['id'])
            deployed+=number(r['entry_price'])*p['quantity']
            if r.get('last_price') not in (None,''):
                unrealized+=(number(r['last_price'])-number(r['entry_price']))*p['quantity']
            else:unknown.append(p['id'])
        elif r.get('status') not in ('Cancelled','Expired Unfilled'):
            reserved+=number(p['entry_max'])*p['quantity']
    return {'initial_capital':str(capital),'realized_estimated_net':str(realized),
            'realized_roi_pct':None if unknown else str(100*realized/capital),
            'unrealized_gross':str(unrealized),'deployed':str(deployed),'reserved':str(reserved),
            'available_cash':str(capital+realized-deployed-reserved),
            'selected_calls':selected,'review_calls':','.join(sorted(set(unknown))),
            'as_of':now,'cost_note':'Estimated net uses illustrative 0.15% each side + Rs40 round trip; not a broker contract note. Unrealized excludes future exit costs.'}


def select_one_share(plans,existing,results,settings):
    limits=settings.get('daily_selection_counts',{'Intraday':settings.get('daily_intraday',3),'Swing':settings.get('daily_swing',3)})
    used={'Intraday':set(),'Swing':set()};counts={'Intraday':0,'Swing':0}
    account=summary_one_share(existing,results,settings,'')
    cash=number(account['available_cash'])
    for p in plans:
        p['quantity']=1;p['total_costs']=None;p.pop('cost_model',None)
        p['quantity_mode']='one_share'
        risk=number(p['entry_max'])-number(p['stop'])
        p['portfolio_rank_score']=float(number(p['selection_evidence']['ranking_score'])-10*risk/number(p['entry_max']))
    ordered=sorted(plans,key=lambda p:(-p['portfolio_rank_score'],p['symbol'],p['type']))
    for rank,p in enumerate(ordered,1):
        kind=p['type'];p['portfolio_rank']=rank;p['portfolio_selected']=False
        reason='Outside daily top three for '+kind
        if counts[kind]<limits[kind] and p['symbol'] not in used[kind]:
            if number(p['entry_max'])<=cash:
                p['portfolio_selected']=True;counts[kind]+=1;used[kind].add(p['symbol'])
                cash-=number(p['entry_max'])
                reason='Selected prospectively in daily top three '+kind+'; exactly one share'
            else:reason='Insufficient unleveraged paper cash for one share'
        p['portfolio_selection_reason']=reason
    return ordered


def summary_one_share(plans,results,settings,now):
    capital=number(settings['initial_capital']);realized=number(0);unrealized=number(0)
    deployed=number(0);reserved=number(0);unknown=[];selected=0
    for p in plans:
        if not p.get('portfolio_selected'):continue
        selected+=1;r=results.get(p['id'],{});qty=p.get('quantity',1)
        if r.get('status')=='Closed':
            if r.get('gross_pnl') in (None,''):unknown.append(p['id'])
            else:realized+=number(r['gross_pnl'])
        elif r.get('entry_price') not in (None,''):
            if r.get('status')=='Review Required':unknown.append(p['id'])
            deployed+=number(r['entry_price'])*qty
            if r.get('last_price') not in (None,''):unrealized+=(number(r['last_price'])-number(r['entry_price']))*qty
            else:unknown.append(p['id'])
        elif r.get('status') not in ('Cancelled','Expired Unfilled'):reserved+=number(p['entry_max'])*qty
    return {'initial_capital':str(capital),'realized_gross':str(realized),
        'gross_roi_pct':None if unknown else str(100*realized/capital),
        'realized_estimated_net':None,'realized_roi_pct':None,
        'unrealized_gross':str(unrealized),'deployed':str(deployed),'reserved':str(reserved),
        'available_cash':str(capital+realized-deployed-reserved),'selected_calls':selected,
        'review_calls':','.join(sorted(set(unknown))),'as_of':now,
        'cost_note':'Exactly one share per setup. Gross price returns; fees and slippage excluded, net left unknown. Top three Intraday and top three Swing selected daily. ROI denominator Rs300000.'}
