import unittest
from datetime import datetime
from short_term_calls.engine import IST
from short_term_calls.portfolio import DEFAULT_PORTFOLIO,select,summary,estimated_costs
from test_engine import plan


def candidate(i,kind='Intraday'):
    return plan(id='P'+str(i),symbol='NSE:T'+str(i)+'-EQ',type=kind,
        selection_evidence={'ranking_score':10-i/10})


class PortfolioTests(unittest.TestCase):
    def test_only_top_three_unique_symbols_funded(self):
        p=[candidate(i) for i in range(10)]
        selected=select(p,[],{},datetime(2026,11,9,9,50,tzinfo=IST),DEFAULT_PORTFOLIO)
        funded=[x for x in selected if x['portfolio_selected']]
        self.assertEqual([x['id'] for x in funded],['P0','P1','P2'])
        self.assertEqual(len(selected),10)
        self.assertLessEqual(sum(x['quantity']*x['entry_max'] for x in funded),135000)

    def test_same_symbol_not_funded_twice(self):
        a=candidate(0);b=candidate(0);b['id']='OTHER';b['type']='Swing'
        selected=select([a,b],[],{},datetime(2026,11,9,9,50,tzinfo=IST),DEFAULT_PORTFOLIO)
        self.assertEqual(sum(p['portfolio_selected'] for p in selected),1)

    def test_open_positions_reserve_cash(self):
        existing=[]
        for i in range(6):
            p=candidate(i,'Swing' if i>=3 else 'Intraday')
            p.update(portfolio_selected=True,quantity=400)
            existing.append(p)
        selected=select([candidate(10)],existing,{},datetime(2026,11,9,9,50,tzinfo=IST),DEFAULT_PORTFOLIO)
        self.assertFalse(selected[0]['portfolio_selected'])

    def test_roi_denominator_is_starting_account_capital(self):
        p=candidate(0);p.update(portfolio_selected=True,quantity=10)
        s=summary([p],{'P0':{'status':'Closed','net_pnl':'3000'}},DEFAULT_PORTFOLIO,'2026-11-09T15:30:00+05:30')
        self.assertEqual(s['realized_roi_pct'],'1')

    def test_uncertain_trade_withholds_portfolio_roi(self):
        p=candidate(0);p.update(portfolio_selected=True,quantity=10)
        s=summary([p],{'P0':{'status':'Review Required','entry_price':100,'last_price':105}},DEFAULT_PORTFOLIO,'2026-11-09T15:30:00+05:30')
        self.assertIsNone(s['realized_roi_pct']);self.assertEqual(s['unrealized_gross'],'50')

    def test_costs_explicit_proxy_not_broker_invoice(self):
        p=candidate(0);p.update(quantity=100,cost_model=DEFAULT_PORTFOLIO['cost_model'])
        self.assertEqual(str(estimated_costs(p,100,105)),'70.7500')


if __name__=='__main__':unittest.main()
