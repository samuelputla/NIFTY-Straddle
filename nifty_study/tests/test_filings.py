import unittest

from nifty_study.filings import archive, quarterly_facts, timestamp


class FilingEvidenceTests(unittest.TestCase):
    def test_timestamp_requires_time_and_preserves_ist(self):
        self.assertIsNone(timestamp('2026-11-12'))
        self.assertEqual(timestamp('12-Nov-2026 17:13:09').isoformat(),
                         '2026-11-12T17:13:09+05:30')
        self.assertFalse(archive('https://nsearchives.nseindia.com.example.com/test.xml'))

    def test_quarter_facts_exclude_half_year_values(self):
        xml = '''
        <xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:ind="urn:test">
          <context id="quarter"><period><startDate>2026-07-01</startDate>
            <endDate>2026-09-30</endDate></period></context>
          <context id="half"><period><startDate>2026-04-01</startDate>
            <endDate>2026-09-30</endDate></period></context>
          <ind:ProfitLossForPeriod contextRef="quarter" unitRef="INR">200</ind:ProfitLossForPeriod>
          <ind:ProfitLossForPeriod contextRef="half" unitRef="INR">500</ind:ProfitLossForPeriod>
        </xbrl>'''
        self.assertEqual(quarterly_facts(xml, '2026-09-30'),
                         {'ProfitLossForPeriod': {'value': '200', 'unit_ref': 'INR'}})
