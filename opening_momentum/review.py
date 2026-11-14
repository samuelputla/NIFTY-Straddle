"""After-close evidence and selection diagnostics for Opening Momentum."""
import json
from datetime import datetime, time
from statistics import median

from nifty_study.adapters import IST, Unavailable
from nifty_study.core import daily_features, intraday_features
from nifty_study.filings import collect, timestamp


METRICS = ("from_open", "gap_held", "relative_volume", "range_break", "sector_strength")
FIELDS = ("return", "gap", "intraday", "close", "rvol20", "sma20", "sma50",
          "rsi14", "macd", "signal", "atr14", "adx14", "stoch14",
          "support", "resistance", "breakout", "rs20")


def session_day(bar):
    return datetime.fromtimestamp(bar[0], IST).date()


def feature_percentile(row, peers, metric):
    return sum((row[metric] > peer[metric]) + 0.5 * (row[metric] == peer[metric])
               for peer in peers) / len(peers)


def selection_review(symbol, features, picks):
    row = features.get(symbol)
    if row is None or any(pick not in features for pick in picks):
        return {"reason": "Frozen score data unavailable"}
    ranks = sorted(features, key=lambda name: (-features[name]["score"], name))
    peers = list(features.values())
    cutoff = features[picks[-1]]
    contributions = {
        metric: {
            "value": row[metric],
            "selected_median": median(features[pick][metric] for pick in picks),
            "score_delta_vs_fifth": (feature_percentile(row, peers, metric)
                                    - feature_percentile(cutoff, peers, metric)) / len(METRICS),
        }
        for metric in METRICS
    }
    selected = symbol in picks
    score_gap = row["score"] - cutoff["score"]
    biggest_drag = min(METRICS, key=lambda metric: contributions[metric]["score_delta_vs_fifth"])
    reason = "Selected in opening top five"
    if not selected:
        reason = ("Equal score at cutoff; symbol tie-break"
                  if score_gap == 0 else f"Below opening cutoff; largest score drag: {biggest_drag}")
    return {"rank": ranks.index(symbol) + 1, "score": row["score"],
            "score_gap_vs_fifth": score_gap, "reason": reason,
            "fifth_pick": picks[-1], "contributions": contributions}


def evidence_by_cutoff(evidence, cutoff):
    result = {"by_0945": {}, "after_0945": {}, "gaps": evidence.get("gaps", [])}
    for category in ("announcements", "financial_filings"):
        for group in ("by_0945", "after_0945"):
            result[group][category] = []
        for item in evidence.get(category, []):
            published = timestamp(item.get("published_at"))
            if published is None:
                continue
            group = "by_0945" if published <= cutoff else "after_0945"
            result[group][category].append(item)
    return result


def build_review(day, cutoff, frozen, ranks, picks, bars_by_symbol, trades, fyers):
    leaders = [symbol for symbol, rank in ranks.items() if rank <= 5]
    symbols = list(dict.fromkeys([*leaders, *picks]))
    evidence = dict(collect(symbols, datetime.now(IST), str(day)))
    try:
        benchmark = fyers.history("NSE:NIFTY50-INDEX", str(day))
    except Unavailable:
        benchmark = []
    features = frozen.get("opening_features", {})
    reviews = []
    for symbol in symbols:
        known, later, gaps = {}, {}, []
        try:
            daily = fyers.history(f"NSE:{symbol}-EQ", str(day))
            if not benchmark:
                raise ValueError("NIFTY daily benchmark unavailable")
            for name, eligible, index_bars, target in (
                ("prior-session", [b for b in daily if session_day(b) < day],
                 [b for b in benchmark if session_day(b) < day], known),
                ("closing", daily, benchmark, later),
            ):
                try:
                    if not eligible or (name == "closing" and session_day(eligible[-1]) != day):
                        raise ValueError("Required daily close unavailable")
                    snapshot = daily_features(eligible, index_bars)
                    target.update({field: snapshot[field] for field in FIELDS})
                except (ValueError, KeyError) as error:
                    gaps.append(f"{name} technicals: {error}")
        except (Unavailable, ValueError) as error:
            gaps.append(f"Daily technicals: {error}")

        bars = [bar for bar in bars_by_symbol[symbol] if session_day(bar) == day]
        opening = [bar for bar in bars if datetime.fromtimestamp(bar[0], IST).time() < time(9, 45)]
        for name, window, target in (("opening", opening, known), ("full-session", bars, later)):
            try:
                target["candle_approx_vwap"] = intraday_features(window)["vwap"]
            except ValueError as error:
                gaps.append(f"{name} VWAP: {error}")
        if opening and bars:
            later["return_after_cutoff_pct"] = 100 * (bars[-1][4] / opening[-1][4] - 1)
        actual_rank = ranks[symbol]
        selected = symbol in picks
        outcome = ("Hit" if actual_rank <= 5 else "Failed pick") if selected else "Missed leader"
        diagnosis = selection_review(symbol, features, picks)
        trade = trades.get(symbol) if selected else None
        capture = {"reason": "Outside the Opening Momentum shortlist"}
        if trade is not None:
            entry, exit_price, exit_reason, net_return = trade
            capture = {"entry": entry, "exit": exit_price, "reason": exit_reason,
                       "net_return_pct": net_return}
        payload = {
            "paper_capture": capture,
            "selection": diagnosis,
            "technicals_by_0945": known,
            "observed_after_0945": later,
            "exchange_evidence": evidence_by_cutoff(evidence.get(symbol, {}), cutoff),
            "coverage_gaps": gaps,
        }
        reviews.append([str(day), symbol, outcome, actual_rank, diagnosis.get("rank"),
                        diagnosis["reason"], json.dumps(payload, sort_keys=True)])
    return reviews
