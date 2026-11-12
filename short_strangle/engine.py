"""Deterministic paper rules. No broker orders or network access."""
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass, field
from math import isfinite

DISTANCES = (1, 1.5, 2)
LEVELS = tuple(range(10, 51, 5))
CHOICES = ('Current Week', 'Next Week', 'Monthly')
QTY = 65
COST = 150
QUOTE_GAP = 'Open-contract quote gap >10 seconds; stop path incomplete'
HIGH_RECONCILED = 'Stop outcomes reconciled from recorded session highs'

def select_expiries(contracts, monthly, listed):
    available = sorted(set(contracts) & set(listed))
    months = sorted(set(monthly) & set(available))
    if len(available) < 2 or not months:
        raise RuntimeError('Missing cross-verified current/next/monthly expiry')
    return dict(zip(CHOICES, [available[0], available[1], months[0]]))

SUMMARY = 'Short Strangle Summary'
LOGS = 'Short Strangle Logs'
HEADERS = ['Event ID', 'Date', 'Distance %', 'Expiry Choice', 'Expiry', 'SL %',
           'Spot Capture Time', 'Spot', 'CE Strike', 'PE Strike', 'Entry Time',
           'CE Symbol', 'PE Symbol', 'CE Entry', 'PE Entry', 'CE Stop', 'PE Stop',
           'CE Exit', 'PE Exit', 'CE Exit Time', 'PE Exit Time', 'CE Exit Reason',
           'PE Exit Reason', 'Net P&L', 'Assumed Charges', 'Status', 'Coverage Notes', 'Quantity']
SUMMARY_HEADERS = ['Date', 'Distance %', 'Expiry Choice', 'Expiry', 'Status'] + [f'{p}% Net P&L' for p in LEVELS] + ['Coverage Notes']

def positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and isfinite(x) and x > 0

def strikes(spot, distance):
    if not positive(spot) or distance not in DISTANCES:
        raise ValueError('Invalid spot or configured distance')
    s, d = Decimal(str(spot)), Decimal(str(distance)) / 100
    rounded = lambda x: int((x / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) * 100
    ce, pe = rounded(s * (1 + d)), rounded(s * (1 - d))
    if not pe < spot < ce:
        raise ValueError('Rounded strikes must remain OTM')
    return ce, pe

@dataclass
class Scenario:
    day: str
    distance: float
    choice: str
    expiry: str
    pct: int
    spot: float
    spot_at: str
    symbols: dict
    entry_at: str = ''
    entries: dict = field(default_factory=dict)
    exits: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    missed: bool = False

    def issue(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def enter(self, quotes, at):
        if self.entries or self.missed:
            return
        clock = at[11:19]
        if clock > '09:30:30':
            self.missed = True
            self.issue('MISSED ENTRY: 30-second capture grace exceeded')
            return
        if clock < '09:30:00' or not all(positive(quotes.get(s)) for s in self.symbols.values()):
            return
        self.entries = {side: quotes[sym] for side, sym in self.symbols.items()}
        self.entry_at = at

    def tick(self, symbol, price, at):
        if not self.entries or not positive(price) or not self.entry_at <= at or at[11:19] >= '15:00:00':
            return
        for side, sym in self.symbols.items():
            if sym == symbol and side not in self.exits:
                stop = round(self.entries[side] * (1 + self.pct / 100), 2)
                if price >= stop:
                    self.exits[side] = (stop, at, 'SL threshold paper fill')

    def finish(self, quotes, at):
        if at[11:19] < '15:00:00':
            raise ValueError('Final exit cannot precede 15:00')
        if not self.entries:
            self.missed = True
            return
        for side, sym in self.symbols.items():
            if side not in self.exits:
                if positive(quotes.get(sym)):
                    self.exits[side] = (quotes[sym], at, '15:00 EXIT observed paper mark')
                else:
                    self.issue('Missing final quote; unresolved position')

    def reconcile_session_highs(self, highs):
        """Apply the session-high paper rule using matching observation rows."""
        changed = False
        resolved = set()
        for side, entry in self.entries.items():
            evidence = highs.get(side)
            if not evidence:
                continue
            stop = round(entry * (1 + self.pct / 100), 2)
            if (evidence[8] != self.symbols[side] or evidence[9] != self.entry_at
                    or evidence[10] != stop or evidence[28] != entry):
                continue
            high = evidence[24]
            hit = positive(high) and high >= stop
            prior = self.exits.get(side)
            prior_stop = prior and prior[2].startswith('SL ')
            if hit and not prior_stop:
                at = evidence[26] or (evidence[16] if evidence[15] == high else evidence[20])
                if not at or not self.entry_at <= at < evidence[14]:
                    at = evidence[14]
                self.exits[side] = (stop, at, 'SL recorded session-high threshold paper fill; evidence timestamp')
                changed = True
            complete = (positive(high) and evidence[23] == 'COMPLETE MINUTE BARS'
                        and evidence[21] == evidence[22] == 330)
            if hit or prior_stop or complete:
                resolved.add(side)
        if resolved == {'CE', 'PE'} and (QUOTE_GAP in self.notes or changed):
            if QUOTE_GAP in self.notes:
                self.notes.remove(QUOTE_GAP)
            self.issue(HIGH_RECONCILED + ' (premium >= SL)')
            changed = True
        return changed

    @property
    def status(self):
        if self.missed: return 'MISSED ENTRY'
        # Completion describes closed paper positions; coverage remains in notes.
        if (set(self.entries) == {'CE', 'PE'} and set(self.exits) == {'CE', 'PE'}
                and all(positive(self.entries[s]) and positive(self.exits[s][0])
                        and self.exits[s][1] and self.exits[s][2] for s in ('CE', 'PE'))):
            return 'COMPLETED'
        if self.notes: return 'INCOMPLETE'
        return 'RUNNING'

    @property
    def net(self):
        if len(self.exits) != 2: return ''
        return round(sum(round(self.entries[s] - self.exits[s][0], 2) * QTY for s in ('CE', 'PE')) - COST, 2)

    def row(self):
        ce, pe = strikes(self.spot, self.distance)
        x = lambda side, i: self.exits.get(side, ('', '', ''))[i]
        return [f'strangle-v1|{self.day}|{self.distance}|{self.choice}|{self.pct}',
                self.day, self.distance, self.choice, self.expiry, self.pct, self.spot_at,
                self.spot, ce, pe, self.entry_at, self.symbols['CE'], self.symbols['PE'],
                *[self.entries.get(s, '') for s in ('CE', 'PE')],
                *[round(self.entries[s] * (1 + self.pct / 100), 2) if s in self.entries else '' for s in ('CE', 'PE')],
                *[x(s, 0) for s in ('CE', 'PE')], *[x(s, 1) for s in ('CE', 'PE')],
                *[x(s, 2) for s in ('CE', 'PE')], self.net, COST if self.entries else 0,
                self.status, '; '.join(self.notes), QTY]

def make_scenarios(day, spot, at, expiry_map, contracts):
    out = []
    for distance in DISTANCES:
        ce, pe = strikes(spot, distance)
        for choice in CHOICES:
            expiry = expiry_map[choice]
            symbols = {s: contracts[expiry][(k, s)] for s, k in [('CE', ce), ('PE', pe)]}
            for pct in LEVELS:
                out.append(Scenario(day, distance, choice, expiry, pct, spot, at, symbols))
    return out

def summary_rows(scenarios):
    rows = []
    for distance in DISTANCES:
        for choice in CHOICES:
            group = [s for s in scenarios if s.distance == distance and s.choice == choice]
            statuses = {s.status for s in group}
            status = 'COMPLETED' if statuses == {'COMPLETED'} else 'MISSED ENTRY' if statuses == {'MISSED ENTRY'} else 'INCOMPLETE' if 'INCOMPLETE' in statuses or 'MISSED ENTRY' in statuses else 'RUNNING'
            rows.append([group[0].day, distance, choice, group[0].expiry, status,
                         *[next(s.net for s in group if s.pct == p) for p in LEVELS],
                         '; '.join(sorted({n for s in group for n in s.notes}))])
    return rows
