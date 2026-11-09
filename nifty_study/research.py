"""Compare frozen forecasts with outcomes without inventing causal explanations."""
import json
import math
from statistics import median


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def frozen_features(row):
    try:
        data = json.loads(row.get('Reasons', '{}'))
        return data.get('features', {}) if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def diagnose(pick, forecast, actual, outcome):
    selected = [p for p in forecast if str(p.get('Selected')).lower() == 'true']
    features = frozen_features(pick)
    comparisons = {}
    for name, value in features.items():
        value = number(value)
        peers = [number(frozen_features(p).get(name)) for p in selected]
        peers = [v for v in peers if v is not None]
        if value is not None and peers:
            comparisons[name] = {'frozen_value': value, 'selected_median': median(peers),
                                 'difference': value - median(peers)}
    parts = {}
    try:
        parts = json.loads(pick.get('Reasons', '{}')).get('score_parts', {})
    except (ValueError, TypeError, AttributeError):
        pass
    score = number(pick.get('Score'))
    scores = [number(p.get('Score')) for p in selected]
    scores = [v for v in scores if v is not None]
    cutoff = min(scores) if scores else None
    return {
        'outcome': outcome,
        'known_before_session': {'rank': number(pick.get('Rank')), 'score': score,
            'selection_cutoff_score': cutoff,
            'score_gap_to_cutoff': score-cutoff if score is not None and cutoff is not None else None,
            'feature_comparison': comparisons, 'score_contributions': parts,
            'coverage': pick.get('Coverage', 'Unavailable')},
        'observed_during_session': {k: actual.get(k) for k in
            ('return', 'gap', 'intraday', 'rvol20', 'breakout', 'rsi14', 'rs20', 'evidence')},
        'finding': ('Below frozen top-five rank; inspect score contributions and feature differences'
                    if outcome == 'MISSED LEADER' else
                    'Selected setup did not achieve top-five rank; compare with missed leaders'
                    if outcome == 'FALSE POSITIVE' else
                    'Retain hit/control as comparison evidence'),
        'cause': 'Unresolved: score differences explain selection, not why the stock moved. '
                 'Session volume, gaps and new catalysts were not available at the forecast cutoff.',
        'research_action': 'Test proposed features across controls and future sessions; keep baseline rules frozen',
    }


def research_history(prior_reviews, current_reviews):
    """Count complete evaluated forecasts once; never pool different rule versions."""
    current = [dict(zip(('Review Key', 'Session', 'Forecast ID', 'Symbol', 'Selected',
        'Actual Rank', 'Return %', 'Gap %', 'Open to Close %', 'Outcome', 'Review', 'Rule Version'), r))
        for r in current_reviews]
    groups = {}
    for row in prior_reviews + current:
        key = (row.get('Rule Version'), row.get('Forecast ID'), row.get('Session'))
        symbol = row.get('Symbol')
        if symbol:
            groups.setdefault(key, {}).setdefault(symbol, row)
    versions = {}
    for (version, fid, day), by_symbol in sorted(groups.items()):
        rows = list(by_symbol.values())
        selected = [r for r in rows if str(r.get('Selected')).lower() == 'true']
        if len(rows) != 50 or len(selected) != 5:
            continue
        hits = sum(r.get('Outcome') == 'HIT' for r in selected)
        versions.setdefault(version, []).append({'session': day, 'forecast_id': fid,
            'hits': hits, 'precision_at_5': hits/5,
            'missed_leaders': [r['Symbol'] for r in rows if r.get('Outcome') == 'MISSED LEADER'],
            'failed_picks': [r['Symbol'] for r in selected if r.get('Outcome') == 'FALSE POSITIVE']})
    return {v: {'evaluated_forecasts': len(days), 'total_picks': 5*len(days),
                'hits': sum(d['hits'] for d in days),
                'precision_at_5': sum(d['hits'] for d in days)/(5*len(days)),
                'random_expected_precision': .1, 'sessions': days,
                'interpretation': 'Descriptive forward record; no validated predictive edge'}
            for v, days in versions.items()}

