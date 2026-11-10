# Option Entry Snapshots And Premium Highs

Forward collection for Fixed Entry, Time Based, Delta Based and Short Strangle.
The current three expiry choices and nine SL alternatives remain in place.
Cash-equity studies do not have CE/PE legs or option Greeks.

## Sheet Destinations

- **Option Entry Snapshots:** one row per date, strategy, expiry choice, SL,
  cycle and side. Entry premium/stop; API delta/gamma/theta/vega/IV and contract OI;
  expiry-specific call/put OI aggregates; all returned depth levels as JSON,
  best bid/ask and spread; previous available NIFTY session high/low/close and
  current session opening. Actual request/retrieval timestamps and delay are
  retained. Responses received after 30 seconds are explicitly labelled delayed.
  Greeks not supplied by FYERS are blank, never locally estimated. OI totals
  describe the API chain response (strikecount 50), not verified exchange totals.
- **Option Premium Highs:** each selected contract's observed 09:30–15:00 high,
  peak time, sample count and maximum sample gap. Subscriptions are retained
  after stops/resets. After the session, one-minute history for each distinct
  selected symbol checks all 330 bars from 09:30 through 14:59, including time
  before a later cycle selected that contract. Missing/conflicting bars are
  labelled, and the day-high quote field is never used for this window.

## Stop Interpretation

For every option family and every leg, price **greater than or equal to** its
stop means a crossing; no trade at the exact threshold is required. A stop of
100 crossed by 101 counts as a hit. Paper loss is (entry - stop) × 65, with the
strategy's existing pair/cycle charges handled separately.

The full-session high may precede entry or follow a stop, time reset or delta
reset. It is therefore separate from holding-period evidence. An observed open
leg crossing, or a high from a complete minute strictly within its holding
interval, records a holding-window hit and corresponding hypothetical leg loss.
No-crossing rows remain unresolved rather than proving no hit. Entry/exit minute
ordering cannot be established from candle highs. These additive evidence rows
do not overwrite existing paper fills or invent missing stop-hit timestamps.

## Collection And Recovery

Optional metadata uses a paced single background worker and existing bounded
request timeouts. SL alternatives with an identical symbol and entry timestamp
reuse the same snapshot. Strategy stop/accounting functions are unchanged.
Existing workflows upload raw entry/context/history responses and recoverable
sheet rows under `option_observations/` with 30-day artifact retention. No extra
workflow is created. These are entry snapshots accumulated over days/cycles,
not continuous intraday Greek or market-depth history.

No historical Greeks/depth backfill is claimed. First-session API availability
and Sheet publishing still require live observation.
