"""Straddle V2: deterministic paper-only state machine; no network/order calls."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math

VERSION = "REFINED_STRADDLE_V1"
HEADERS = ["Date", "Strategy", "Run Type", "Status", "Data Quality", "Target Entry", "Entry Time", "Expiry", "DTE", "SL %", "Units", "Spot Entry", "Spot ATM", "Synthetic Forward", "Strike", "CE Symbol", "PE Symbol", "CE Entry", "PE Entry", "CE Stop", "PE Stop", "CE Exit", "PE Exit", "CE Exit Time", "PE Exit Time", "CE Exit Reason", "PE Exit Reason", "CTC Activated At", "CTC Leg", "Entry Skew", "Skew Flag", "PDR Regime", "VIX", "Prev High", "Prev Low", "Prev Close", "Day Open", "CE OI", "PE OI", "Metadata Retrieved At", "Gross P&L", "Charges", "SL Slippage", "Net P&L", "Return %", "Source Strike", "Source CE Entry", "Source PE Entry", "Source Entry Time", "Backfill Notes", "Last Update", "State JSON"]
LOG_HEADERS = ["Event ID", "Date", "Strategy", "Timestamp IST", "Event", "Leg", "Symbol", "Price", "CE Price", "PE Price", "CE Stop", "PE Stop", "Details", "Quality"]


def money(x):
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def atm(x):
    return int((Decimal(str(x)) / 50).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 50


def valid(x):
    return isinstance(x, (float, int)) and math.isfinite(x) and x > 0


class Engine:
    def __init__(self, state):
        self.state = state
        self.events = []

    @classmethod
    def enter(cls, day, expiry, when, spot, k0, synthetic, strike, symbols, prices):
        dte = (datetime.fromisoformat(expiry).date() - datetime.fromisoformat(day).date()).days
        if dte < 0 or not all(valid(v) for v in prices.values()):
            raise ValueError("Invalid expiry or entry premium")
        pct = 25 if dte == 0 else 20
        state = dict(date=day, expiry=expiry, strategy=VERSION, entry_time=when, dte=dte, sl_pct=pct,
                     target_entry="09:32:00" if dte == 0 else "09:30:00", spot=spot, spot_atm=k0,
                     synthetic=synthetic, strike=strike, status="OPEN", quality="OBSERVED PAPER",
                     metadata={}, seq=0, last_update=when, legs={})
        for side in ("CE", "PE"):
            state["legs"][side] = dict(symbol=symbols[side], entry=prices[side], stop=money(prices[side]*(1+pct/100)),
                last=prices[side], last_time=when, exit=None, exit_time="", reason="", ctc=False, ctc_time="")
        engine = cls(state)
        engine.event(when, "ENTRY", details="Synthetic ATM; independent leg stops; 65 fixed study units")
        return engine

    def event(self, when, kind, side="", price="", details=""):
        s = self.state
        s["seq"] += 1
        legs = s["legs"]
        self.events.append([f"{s['date']}:{VERSION}:{s['seq']}", s["date"], VERSION, when, kind, side,
            legs[side]["symbol"] if side else "", price, legs["CE"]["last"], legs["PE"]["last"],
            legs["CE"]["stop"], legs["PE"]["stop"], details, s["quality"]])

    def close(self, side, price, when, reason):
        leg = self.state["legs"][side]
        if leg["exit"] is not None:
            return
        leg.update(exit=price, exit_time=when, reason=reason)
        self.event(when, reason, side, price)

    def observe(self, prices, when, paired=True):
        """Chronological observed LTPs. Stops precede CTC activation/combined target.

        A fresh survivor tick may activate CTC; at first stop, an already-decayed
        survivor requires a recent paired observation. Combined targets require
        synchronized pairs. A single-leg tick may trigger its stop immediately.
        """
        s = self.state
        if s["status"] != "OPEN":
            return
        s["last_update"] = when
        for side, price in prices.items():
            if not valid(price):
                continue
            leg = s["legs"][side]
            if when < leg["last_time"]:
                continue
            leg.update(last=price, last_time=when)
            if leg["exit"] is None and price >= leg["stop"]:
                # Observed price captures gap-through losses; Rs1/SL is additional friction.
                self.close(side, price, when, "CTC STOP" if leg["ctc"] else "STOP LOSS")
        alive = [side for side in ("CE", "PE") if s["legs"][side]["exit"] is None]
        if len(alive) == 1 and (alive[0] in prices or paired):
            side = alive[0]
            leg = s["legs"][side]
            if not leg["ctc"] and leg["last"] <= .65 * leg["entry"]:
                leg.update(stop=leg["entry"], ctc=True, ctc_time=when)
                self.event(when, "CTC ACTIVATED", side, leg["last"], "35% decay observed after first leg closed; stop tightened to entry")
        if paired and len(alive) == 2:
            legs = s["legs"]
            if sum(legs[x]["last"] for x in alive) <= .25 * sum(legs[x]["entry"] for x in alive):
                for side in alive:
                    self.close(side, legs[side]["last"], when, "75% COMBINED TARGET")
        if all(x["exit"] is not None for x in s["legs"].values()):
            s["status"] = "COMPLETED" if s["quality"] == "OBSERVED PAPER" else "REVIEW REQUIRED"

    def finish(self, when, fresh=True):
        if self.state["status"] != "OPEN":
            return
        if not fresh:
            self.state["quality"] = "STALE EXIT / REVIEW REQUIRED"
        for side, leg in self.state["legs"].items():
            if leg["exit"] is None:
                self.close(side, leg["last"], when, "14:55 EXIT" if fresh else "STALE LAST OBSERVATION")
        self.state["last_update"] = when
        self.state["status"] = "COMPLETED" if fresh and self.state["quality"] == "OBSERVED PAPER" else "REVIEW REQUIRED"

    def row(self):
        import json
        s, legs = self.state, self.state["legs"]
        m = s.get("metadata", {})
        closed = all(x["exit"] is not None for x in legs.values())
        gross = money(sum((x["entry"]-x["exit"])*65 for x in legs.values())) if closed else ""
        stop_count = sum(x["reason"] in ("STOP LOSS", "CTC STOP") for x in legs.values())
        slippage = 65 * stop_count
        net = money(gross-150-slippage) if closed else ""
        ctc = next((side for side in legs if legs[side]["ctc"]), "")
        skew = money(abs(legs["CE"]["entry"]-legs["PE"]["entry"]))
        row = {"Date":s["date"], "Strategy":VERSION, "Run Type":"REFINED PAPER", "Status":s["status"],
            "Data Quality":s["quality"], "Target Entry":s["target_entry"], "Entry Time":s["entry_time"],
            "Expiry":s["expiry"], "DTE":s["dte"], "SL %":s["sl_pct"], "Units":65, "Spot Entry":s["spot"],
            "Spot ATM":s["spot_atm"], "Synthetic Forward":s["synthetic"], "Strike":s["strike"],
            "CTC Activated At":legs[ctc]["ctc_time"] if ctc else "", "CTC Leg":ctc, "Entry Skew":skew,
            "Skew Flag":"SKEW > 15" if skew > 15 else "WITHIN 15", "Gross P&L":gross,
            "Charges":150 if closed else "", "SL Slippage":slippage if closed else "", "Net P&L":net,
            "Return %":money(net/250000*100) if closed else "", "Last Update":s["last_update"],
            "State JSON":json.dumps(s, separators=(",", ":"))}
        for side in legs:
            for column, field in (("Symbol","symbol"),("Entry","entry"),("Stop","stop"),("Exit","exit"),
                                  ("Exit Time","exit_time"),("Exit Reason","reason")):
                row[f"{side} {column}"] = legs[side][field] if legs[side][field] is not None else ""
        row.update(m)
        return [row.get(h, "") for h in HEADERS]

