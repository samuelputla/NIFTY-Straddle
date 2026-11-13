"""Bounded NSE evidence discovery for post-session equity reviews."""
from datetime import datetime, timedelta
from time import monotonic, sleep
from urllib.parse import urlsplit
from xml.etree import ElementTree

from .core import IST

METRICS = {
    'RevenueFromOperations', 'RevenueFromOperationsOtherThanFinanceCompany',
    'ProfitLossForPeriod', 'ProfitLossForThePeriod', 'ProfitBeforeTax',
    'InterestEarned', 'InterestExpended', 'NetProfitLossFromOrdinaryActivitiesAfterTax',
    'DilutedEarningsLossPerShareFromContinuingOperations',
}


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ('%d-%b-%Y %H:%M:%S', '%d-%m-%Y %H:%M:%S'):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if ' ' not in value and 'T' not in value:
        return None
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)


def archive(url):
    return isinstance(url, str) and urlsplit(url).scheme == 'https' and urlsplit(url).netloc == 'nsearchives.nseindia.com'


def quarterly_facts(xml, period_end):
    """Keep exact filed concept, value and unit; omit ambiguous contexts."""
    root = ElementTree.fromstring(xml)
    ns = '{http://www.xbrl.org/2003/instance}'
    eligible = set()
    end = datetime.strptime(period_end, '%Y-%m-%d').date()
    for ctx in root.findall(ns + 'context'):
        period = ctx.find(ns + 'period')
        if period is None or any(node.tag.endswith('}explicitMember') or node.tag.endswith('}typedMember') for node in ctx.iter()):
            continue
        if period.findtext(ns + 'endDate') != period_end:
            continue
        start = period.findtext(ns + 'startDate')
        if start and 80 <= (end - datetime.strptime(start, '%Y-%m-%d').date()).days <= 100:
            eligible.add(ctx.get('id'))
    if len(eligible) != 1:
        return {}
    return {node.tag.rsplit('}', 1)[-1]: {'value': node.text, 'unit_ref': node.get('unitRef')}
            for node in root if node.get('contextRef') in eligible and node.get('unitRef')
            and node.tag.rsplit('}', 1)[-1] in METRICS and node.text}


def collect(symbols, as_of, session_date):
    import requests

    client = requests.Session()
    client.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json, */*',
                           'Referer': 'https://www.nseindia.com/'})
    last = 0
    request_deadline = monotonic() + 65

    def get(url, **kwargs):
        nonlocal last
        sleep(max(0, 1 - (monotonic() - last)))
        if monotonic() >= request_deadline:
            raise requests.Timeout('Research time budget exhausted')
        last = monotonic()
        response = client.get(url, timeout=(3, 6), allow_redirects=False, **kwargs)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected source response')
        return response

    try:
        get('https://www.nseindia.com/')
    except (requests.RequestException, ValueError):
        pass

    target = datetime.fromisoformat(session_date)
    for symbol in sorted(symbols):
        info = {'announcements': [], 'financial_filings': [], 'gaps': []}
        try:
            data = get('https://www.nseindia.com/api/corporate-announcements', params={
                'index': 'equities', 'symbol': symbol,
                'from_date': (target-timedelta(days=7)).strftime('%d-%m-%Y'),
                'to_date': target.strftime('%d-%m-%Y')}).json()
            if not isinstance(data, list):
                raise ValueError('Invalid announcements response')
            leads = []
            for item in data:
                published = timestamp(item.get('an_dt') or item.get('sort_date'))
                url = item.get('attchmntFile')
                if item.get('symbol') == symbol and published and published <= as_of and archive(url):
                    leads.append({'published_at': published.isoformat(), 'url': url,
                                  'headline': str(item.get('desc') or item.get('attchmntText') or '')[:180],
                                  'status': 'Exchange filing indexed; contents not independently reviewed'})
            info['announcements'] = sorted(leads, key=lambda row: row['published_at'], reverse=True)[:5]
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            info['gaps'].append('NSE announcements unavailable')
        try:
            data = get('https://www.nseindia.com/api/integrated-filing-results', params={
                'index': 'equities', 'symbol': symbol, 'period_ended': 'all',
                'type': 'Integrated Filing- Financials'}).json()
            entries = data.get('data') if isinstance(data, dict) else data
            if not isinstance(entries, list):
                raise ValueError('Invalid results response')
            filings = []
            for item in entries:
                published = timestamp(item.get('broadcast_Date'))
                url = item.get('xbrl')
                if not published or published > as_of or not archive(url):
                    continue
                raw_end = str(item.get('qe_Date') or '').split(' ')[0]
                for fmt in ('%d-%b-%Y', '%d-%m-%Y', '%Y-%m-%d'):
                    try:
                        end = datetime.strptime(raw_end, fmt).date().isoformat()
                        break
                    except ValueError:
                        continue
                else:
                    continue
                basis = str(item.get('consolidated') or '').strip()
                filings.append((end, basis, published, url))
            if not filings:
                info['gaps'].append('No timestamped quarterly filing in source response')
            else:
                end, basis, published, url = max(filings, key=lambda x: (x[0], x[1].lower().startswith('con'), x[2]))
                filing = {'quarter_end': end, 'basis': basis or 'Unspecified',
                          'published_at': published.isoformat(), 'url': url, 'facts': {}}
                info['financial_filings'].append(filing)
                try:
                    filing['facts'] = quarterly_facts(get(url).content, end)
                    if not filing['facts']:
                        info['gaps'].append('No supported unambiguous quarterly XBRL facts')
                except (requests.RequestException, ValueError, ElementTree.ParseError):
                    info['gaps'].append('Quarterly XBRL unavailable')
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            info['gaps'].append('NSE financial results unavailable')
        yield symbol, info
