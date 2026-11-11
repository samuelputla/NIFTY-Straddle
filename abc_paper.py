"""Intraday ABC equity paper collector. FYERS is used for market data."""
import json
import math
import os
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from market_calendar import session_allowed

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
EXIT = time(15)
WATCHLIST = "RELIANCE,HDFCBANK,ICICIBANK,INFY,TCS,SBIN,AXISBANK,LT"
OUTPUT = Path("abc-paper.jsonl")


@dataclass
class Candle:
    low: Decimal
    high: Decimal
    close: Decimal


class Strategy:
    def __init__(self, emit):
        self.emit = emit
        self.bars = []
        self.a = self.b = None
        self.armed = False
        self.used = set()
        self.trade = None
        self.last_price = None
        self.last_at = None
        self.bucket = self.bar = None

    def reset_pattern(self, a=None, b=None):
        self.a, self.b = a, b
        self.armed = False

    def levels(self):
        span = self.b - self.a
        return (self.b - span * Decimal(".382"),
                self.b - span * Decimal(".50"),
                self.b - span * Decimal(".52"))

    def close(self, bar, at):
        self.bars.append(bar)
        if len(self.bars) > 3:
            self.bars.pop(0)
        if self.trade or self.armed:
            return
        if self.a is not None and self.b > self.a:
            upper, lower, stop = self.levels()
            if bar.low < stop:
                self.reset_pattern()
            elif bar.high <= self.b and lower <= bar.close <= upper:
                if (self.a, self.b) not in self.used:
                    self.armed = True
                    self.emit("armed", at, a=self.a, b=self.b, stop=stop,
                              target=self.b + 2 * (self.b - stop))
                    return
        if len(self.bars) >= 2:
            pivot, right = self.bars[-2:]
            left = self.bars[0] if len(self.bars) == 3 else None
            if (left is None or pivot.low < left.low) and pivot.low < right.low:
                # The next candle confirms the low and supplies the first
                # high whose order after A is known from 15-minute bars.
                self.reset_pattern(pivot.low, right.high)
                return
        if self.a is not None:
            self.b = max(self.b, bar.high)

    def tick(self, at, price):
        if not OPEN <= at.time() < EXIT:
            return
        bucket = at.replace(minute=at.minute // 15 * 15, second=0, microsecond=0)
        if bucket != self.bucket:
            if self.bar is not None:
                if bucket - self.bucket != timedelta(minutes=15):
                    raise RuntimeError("Missing 15-minute candle in FYERS stream")
                self.close(self.bar, bucket)
            self.bucket, self.bar = bucket, Candle(price, price, price)
        else:
            self.bar.low = min(self.bar.low, price)
            self.bar.high = max(self.bar.high, price)
            self.bar.close = price
        self.last_price, self.last_at = price, at
        if self.trade:
            if price <= self.trade["stop"]:
                self.exit(at, "stop")
            elif price >= self.trade["target"]:
                self.exit(at, "target")
        elif self.armed:
            _, _, stop = self.levels()
            if price < stop:
                self.emit("invalidated", at, b=self.b, price=price)
                self.reset_pattern()
            elif price > self.b:
                self.used.add((self.a, self.b))
                self.trade = dict(a=self.a, b=self.b, stop=stop,
                                  target=self.b + 2 * (self.b - stop),
                                  planned_entry=self.b, entry=price)
                self.emit("entry", at, **self.trade)
                if price >= self.trade["target"]:
                    self.exit(at, "target")

    def exit(self, at, reason):
        if self.trade:
            self.emit("exit", at, reason=reason, price=self.last_price,
                      quote_at=self.last_at.isoformat(),
                      pnl_per_share=self.last_price - self.trade["entry"],
                      planned_pnl_per_share=self.last_price - self.trade["planned_entry"],
                      **self.trade)
            self.trade = None
            self.reset_pattern()
            self.bars.clear()


def run():
    from fyers_apiv3.FyersWebsocket import data_ws

    now = lambda: datetime.now(IST)
    day = now().date()
    allowed, reason = session_allowed(day)
    if not allowed:
        print(reason)
        return
    if now().time() >= OPEN:
        raise RuntimeError("Start ABC before 09:15 IST to capture the full session")

    client = os.environ.get("FYERS_CLIENT_ID") or "M2DACFCYUO-100"
    token = os.environ["FYERS_ACCESS_TOKEN"].strip()
    if not token:
        raise RuntimeError("FYERS_ACCESS_TOKEN is empty")
    symbols = sorted({f"NSE:{name.strip().upper()}-EQ"
                      for name in os.environ.get("ABC_SYMBOLS", WATCHLIST).split(",")
                      if name.strip()})
    if not symbols:
        raise RuntimeError("ABC_SYMBOLS is empty")

    events = queue.Queue()
    def on_message(message):
        if not isinstance(message, dict):
            return
        symbol, price = message.get("symbol"), message.get("ltp")
        if symbol in symbols and isinstance(price, (float, int)) and math.isfinite(price) and price > 0:
            events.put((symbol, now(), Decimal(str(price))))

    def on_connect():
        socket.subscribe(symbols=symbols, data_type="SymbolUpdate")
        socket.keep_running()

    def on_failure(*_args):
        events.put((None, now(), None))

    socket = data_ws.FyersDataSocket(
        access_token=f"{client}:{token}", log_path="", litemode=True,
        write_to_file=False, reconnect=False, on_connect=on_connect,
        on_close=on_failure, on_error=on_failure, on_message=on_message,
    )
    with OUTPUT.open("w", encoding="utf-8", buffering=1) as journal:
        def logger(symbol):
            def emit(event, at, **fields):
                row = dict(symbol=symbol, event=event, at=at.isoformat(), **fields)
                journal.write(json.dumps(row, default=str) + "\n")
            return emit

        strategies = {symbol: Strategy(logger(symbol)) for symbol in symbols}
        threading.Thread(target=socket.connect, daemon=True).start()
        end = datetime.combine(day, EXIT, IST)
        seen = set()
        while now() < end or not events.empty():
            try:
                symbol, at, price = events.get(timeout=0.5)
            except queue.Empty:
                if now().time() >= time(9, 16) and seen != set(symbols):
                    missing = sorted(set(symbols) - seen)
                    raise RuntimeError(f"No session ticks received for {missing}")
                continue
            if at >= end:
                break
            if symbol is None:
                logger("SESSION")("feed_error", at)
                raise RuntimeError("FYERS feed interrupted; session results are incomplete")
            if at.time() >= OPEN:
                seen.add(symbol)
                strategies[symbol].tick(at, price)
        for strategy in strategies.values():
            strategy.exit(end, "session_last_observed_price")
        logger("SESSION")("complete", end, symbols=symbols)


if __name__ == "__main__":
    run()
