"""Prospective NIFTY 50 opening-momentum paper study."""
import json
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from statistics import mean, median

from nifty_study.adapters import Fyers, IST, Sheets, Unavailable, fetch_universe
from nifty_study.calendar import session

OUT = Path("opening-momentum-report")
RUNS = "Opening Momentum Runs"
PICKS = "Opening Momentum Picks"
RESULTS = "Opening Momentum Results"
VERSION = "v1"
COST = 0.001  # 10 basis points round trip, including slippage


class MomentumSheets(Sheets):
    def __init__(self):
        super().__init__()
        self.schema = {
            RUNS: ["Run Key", "Session", "Phase", "Recorded At", "Rule", "Details", "GitHub Run"],
            PICKS: ["Session", "Frozen At", "List", "Rank", "Symbol", "Features"],
            RESULTS: ["Session", "List", "Symbol", "Closing Rank", "Hit", "Entry Time",
                      "Entry", "Exit", "Exit Reason", "Net Return %"],
        }
        for name, headers in self.schema.items():
            if name not in self.tabs:
                self.tabs[name] = self.book.add_worksheet(name, rows=1000, cols=len(headers))
                self.tabs[name].update([headers], "A1")
            if self.tabs[name].row_values(1) != headers:
                raise Unavailable("Opening Momentum tab header mismatch: " + name)

    def has_run(self, key):
        return any(row["Run Key"] == key for row in self.records(RUNS))


def timestamp(bar):
    return datetime.fromtimestamp(bar[0], IST)


def at(day, hour, minute):
    return datetime.combine(day, time(hour, minute), IST)


def opening_features(bars, day):
    start = at(day, 9, 15)
    expected = [start + timedelta(minutes=5 * i) for i in range(6)]
    days = {}
    closing = {}
    for bar in bars:
        stamp = timestamp(bar)
        if stamp.date() < day and stamp.time() == time(15, 25):
            closing[stamp.date()] = bar[4]
        if time(9, 15) <= stamp.time() < time(9, 45):
            days.setdefault(stamp.date(), []).append(bar)
    current = days.get(day, [])
    if [timestamp(bar) for bar in current] != expected or not closing:
        raise Unavailable("Incomplete opening bars or previous close")
    history = [
        sum(bar[5] for bar in days[d])
        for d in sorted(days, reverse=True)
        if d < day and d in closing
        and [timestamp(bar).time() for bar in days[d]] == [stamp.time() for stamp in expected]
    ][:20]
    if len(history) < 15 or median(history) <= 0:
        raise Unavailable("Insufficient comparable opening volume history")
    opening, last, prior = current[0][1], current[-1][4], closing[max(closing)]
    return {
        "from_open": last / opening - 1,
        "gap": opening / prior - 1,
        "gap_held": last / max(prior, opening) - 1,
        "relative_volume": sum(bar[5] for bar in current) / median(history),
        "range_break": last / max(bar[2] for bar in current[:3]) - 1,
    }


def rank_opening(features, industries):
    grouped = {}
    for symbol, row in features.items():
        grouped.setdefault(industries[symbol], []).append(row["from_open"])
    for symbol, row in features.items():
        row["sector_strength"] = median(grouped[industries[symbol]])
    metrics = ("from_open", "gap_held", "relative_volume", "range_break", "sector_strength")
    for row in features.values():
        row["score"] = mean(
            mean((row[metric] > peer[metric]) + 0.5 * (row[metric] == peer[metric])
                 for peer in features.values())
            for metric in metrics
        )
    return sorted(features, key=lambda symbol: (-features[symbol]["score"], symbol))


def paper_trade(bars, entry_time):
    exit_time = at(entry_time.date(), 15, 25)
    path = [bar for bar in bars if entry_time <= timestamp(bar) <= exit_time]
    expected = [entry_time + timedelta(minutes=5 * i)
                for i in range((exit_time - entry_time) // timedelta(minutes=5) + 1)]
    if [timestamp(bar) for bar in path] != expected:
        raise Unavailable("Incomplete paper trade path")
    entry = path[0][1]
    stop, target = entry * 0.99, entry * 1.02
    exit_price, reason = path[-1][1], "15:25 timed exit"
    for _, opening, high, low, _, _ in path[:-1]:
        if opening <= stop or opening >= target:
            exit_price, reason = opening, "Stop gap" if opening <= stop else "Target gap"
            break
        if low <= stop:
            exit_price, reason = stop, "Stop"
            break
        if high >= target:
            exit_price, reason = target, "Target"
            break
    return entry, exit_price, reason, 100 * (exit_price / entry - 1 - COST)


def evening_list(rows, day, symbols):
    forecasts = {}
    for row in rows:
        if row["Target Session"] != str(day):
            continue
        stamp = datetime.fromisoformat(row["Created At"])
        if stamp.tzinfo is not None and stamp < at(day, 9, 15):
            forecasts.setdefault(row["Forecast ID"], []).append(row)
    eligible = []
    for batch in forecasts.values():
        selected = [row for row in batch if row["Selected"].lower() == "true"]
        if len(batch) == 50 and {row["Symbol"] for row in batch} == symbols and len(selected) == 5:
            eligible.append((max(datetime.fromisoformat(row["Created At"]) for row in batch),
                             [row["Symbol"] for row in sorted(selected, key=lambda row: int(row["Rank"]))]))
    return min(eligible)[1] if eligible else []


def execute(phase):
    now = datetime.now(IST)
    day = now.date()
    market = session(day)
    if not market or market["kind"] != "NORMAL":
        print("Skipped outside a regular equity session")
        return
    cutoff = at(day, 9, 45)
    deadline = at(day, 9, 50)
    if phase == "freeze" and at(day, 9, 39) <= now < cutoff:
        from time import sleep

        sleep((cutoff - now).total_seconds())
        now = datetime.now(IST)
    if phase == "freeze" and not cutoff <= now < deadline:
        raise Unavailable("Opening shortlist window missed")
    if phase == "evaluate" and now < at(day, 15, 35):
        raise Unavailable("Closing candles are not ready")
    key = f"{VERSION}:{day}:{phase}"
    sheet = MomentumSheets()
    if sheet.has_run(key):
        print("Already published", key)
        return
    token = os.getenv("FYERS_ACCESS_TOKEN")
    if not token:
        raise Unavailable("FYERS access token unavailable")
    fyers = Fyers(token, OUT / "raw")
    if phase == "freeze":
        _, members, source = fetch_universe()
        industries = {member["Symbol"]: member["Industry"] for member in members}
        baseline = evening_list(sheet.records("Study Forecasts"), day, set(industries))
        features = {
            symbol: opening_features(fyers.history(f"NSE:{symbol}-EQ", str(day), "5", 40), day)
            for symbol in industries
        }
        picks = rank_opening(features, industries)[:5]
        frozen = datetime.now(IST)
        if frozen >= deadline:
            raise Unavailable("Opening shortlist was not ready before 09:50 IST")
        tables = {PICKS: [
            [str(day), frozen.isoformat(), label, rank, symbol,
             json.dumps(features[symbol], sort_keys=True) if label == "Opening" else ""]
            for label, names in (("Opening", picks), ("Evening", baseline))
            for rank, symbol in enumerate(names, 1)
        ]}
        detail = {"universe": sorted(industries), "source": source, "baseline_available": bool(baseline),
                  "frozen_at": frozen.isoformat(), "entry": deadline.isoformat(),
                  "opening_features": features}
    else:
        prior = next((row for row in sheet.records(RUNS) if row["Run Key"] == f"{VERSION}:{day}:freeze"), None)
        if prior is None:
            print("No prospective shortlist to evaluate")
            return
        frozen = json.loads(prior["Details"])
        symbols = frozen["universe"]
        entry_time = datetime.fromisoformat(frozen["entry"])
        logs = [row for row in sheet.records(PICKS)
                if row["Session"] == str(day) and row["Frozen At"] == frozen["frozen_at"]]
        selected = {row["Symbol"] for row in logs}
        if sum(row["List"] == "Opening" for row in logs) != 5:
            raise Unavailable("Incomplete frozen opening shortlist")
        returns, trades = {}, {}
        for symbol in symbols:
            bars = fyers.history(f"NSE:{symbol}-EQ", str(day), "5", 10)
            closes = [bar for bar in bars if timestamp(bar).time() == time(15, 25)]
            if len(closes) < 2 or timestamp(closes[-1]).date() != day:
                raise Unavailable("Closing rank missing data for " + symbol)
            returns[symbol] = closes[-1][4] / closes[-2][4] - 1
            if symbol in selected:
                trades[symbol] = paper_trade(bars, entry_time)
        leaders = sorted(symbols, key=lambda symbol: (-returns[symbol], symbol))
        ranks = {symbol: rank for rank, symbol in enumerate(leaders, 1)}
        results = [
            [str(day), row["List"], symbol, ranks[symbol], ranks[symbol] <= 5,
             entry_time.isoformat(), *trades[symbol]]
            for row in logs for symbol in [row["Symbol"]]
        ]
        tables = {RESULTS: results}
        detail = {"closing_top_five": leaders[:5], "closing_returns": returns,
                  "comparison_eligible": len(logs) == 10, "lists": {}}
        for label in ("Opening", "Evening"):
            scores = [row for row in results if row[1] == label]
            if scores:
                detail["lists"][label] = {
                    "hits": sum(row[4] for row in scores),
                    "mean_net_return_pct": mean(row[-1] for row in scores),
                    "missed_leaders": [symbol for symbol in leaders[:5]
                                       if symbol not in {row[2] for row in scores}],
                }
    detail_json = json.dumps(detail, sort_keys=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "summary.json").write_text(detail_json, encoding="utf-8")
    url = f"{os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
    sheet_detail = {name: value for name, value in detail.items() if name != "opening_features"}
    tables[RUNS] = [[key, str(day), phase, datetime.now(IST).isoformat(), VERSION,
                     json.dumps(sheet_detail, sort_keys=True), url]]
    if phase == "freeze" and datetime.now(IST) >= deadline:
        raise Unavailable("Opening shortlist publication window missed")
    sheet.publish(key, tables)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "evaluate"))
    execute(parser.parse_args().phase)
