import unittest
from datetime import datetime
from short_term_calls.engine import IST,replay
from short_term_calls.portfolio import select,summary
from test_engine import plan,valid_rows
from test_portfolio import candidate

SETTINGS={'initial_capital':300000,'quantity_mode':'one_share','daily_intraday':3,'daily_swing':3}


class OneShareTests(unittest.TestCase):
    def test_three_each_not_three_combined(self):
        plans=[candidate(i,k) for k in ('Intraday','Swing') for i in range(6)]
        for p in plans:p['id']+=p['type']
        output=select(plans,[],{},datetime(2026,11,9,9,50,tzinfo=IST),SETTINGS)
        for kind in ('Intraday','Swing'):
            self.assertEqual(sum(p['portfolio_selected'] and p['type']==kind for p in output),3)
        self.assertEqual(len(output),12)
        self.assertTrue(all(p['quantity']==1 and p.get('cost_model') is None for p in output))

    def test_existing_daily_selection_subtracted_separately(self):
        settings=dict(SETTINGS,daily_selection_counts={'Intraday':1,'Swing':2})
        plans=[candidate(i,k) for k in ('Intraday','Swing') for i in range(4)]
        output=select(plans,[],{},datetime(2026,11,9,9,50,tzinfo=IST),settings)
        self.assertEqual(sum(p['portfolio_selected'] and p['type']=='Intraday' for p in output),1)
        self.assertEqual(sum(p['portfolio_selected'] and p['type']=='Swing' for p in output),2)

    def test_one_share_profit_and_percentage(self):
        rows=valid_rows();rows[32][2]=111
        r=replay(plan(quantity=1),rows,'2026-11-09T10:15:00+05:30')
        self.assertEqual(r['gross_pnl'],r['gross_per_share'])
        self.assertEqual(r['gross_pnl'],'9.5')
        self.assertAlmostEqual(float(r['gross_return_pct']),100*9.5/100.5)
        self.assertIsNone(r['net_pnl']);self.assertIsNone(r['estimated_costs'])
        self.assertAlmostEqual(float(r['realized_r']),9.5/5.5)

    def test_account_gross_roi_is_not_trade_percent(self):
        p=plan(quantity=1,portfolio_selected=True)
        r={'status':'Closed','gross_pnl':30}
        s=summary([p],{p['id']:r},SETTINGS,'2026-11-09T15:30:00+05:30')
        self.assertEqual(s['realized_gross'],'30');self.assertEqual(s['gross_roi_pct'],'0.01')
        self.assertIsNone(s['realized_estimated_net'])

    def test_no_forced_selection_if_fewer_qualify(self):
        output=select([candidate(1)],[],{},datetime(2026,11,9,9,50,tzinfo=IST),SETTINGS)
        self.assertEqual(sum(p['portfolio_selected'] for p in output),1)

    def test_cash_cannot_be_overallocated(self):
        p=candidate(1);p['entry_max']=400000
        output=select([p],[],{},datetime(2026,11,9,9,50,tzinfo=IST),SETTINGS)
        self.assertFalse(output[0]['portfolio_selected']);self.assertEqual(output[0]['quantity'],1)


if __name__=='__main__':unittest.main()
