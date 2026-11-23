import unittest
from multi_strike_publish import build


def sources():
    fixed=[['Date','Expiry Choice','Expiry','SL %','ATM','CE Entry','PE Entry','CE Exit Price','PE Exit Price','Status']]
    summary=[['Date','Expiry Choice','Expiry',*[f'{sl}% Profit' for sl in range(10,51,5)]]]
    strangle=[['Date','Expiry Choice','Expiry','Distance %','SL %','CE Strike','PE Strike','CE Entry','PE Entry','CE Exit','PE Exit','Net P&L','Status']]
    for choice in ('Current Week','Next Week','Monthly'):
        summary.append(['2026-11-23',choice,'2026-12-01',*[100]*9])
        for sl in range(10,51,5):
            fixed.append(['2026-11-23',choice,'2026-12-01',sl,25000,100,100,80,110,'INCOMPLETE'])
            for distance in (1,1.5,2):
                strangle.append(['2026-11-23',choice,'2026-12-01',distance,sl,25300,24700,100,100,80,110,200,'INCOMPLETE'])
    return fixed,summary,strangle


class PublicationTests(unittest.TestCase):
    def test_p0_publishes_all_pairs_without_greeks_or_margins(self):
        grouped=build(*sources(),[])
        self.assertEqual(len(grouped['2026-11-23']),2187)
        self.assertEqual(grouped['2026-11-23'][0][14],300)
        self.assertEqual(grouped['2026-11-23'][0][-2:],['',''])

    def test_missing_leg_exit_preserves_existing_output(self):
        fixed,summary,strangle=sources();strangle[1][10]=''
        self.assertEqual(build(fixed,summary,strangle,[]),{})

    def test_missing_net_pnl_is_not_published(self):
        fixed,summary,strangle=sources();strangle[1][11]=''
        self.assertEqual(build(fixed,summary,strangle,[]),{})


if __name__=='__main__':unittest.main()
