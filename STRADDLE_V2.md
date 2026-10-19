# Straddle V2 — REFINED_STRADDLE_V1

Paper-only parallel study. No broker order placement and no writes to core strategy
worksheets. The core seven stop scenarios remain independent.

## Frozen rules

- Nearest actual NIFTY expiry from FYERS metadata; do not assume a weekday.
- Target09:30 IST, or09:32 on actual expiry date. Use first valid synchronized
  option/spot observations afterward; retain actual timestamp. No entry after14:55.
- Provisional K0 = nearest50 cash spot. Synthetic = K0+CE(K0)-PE(K0).
  Final same-strike CE+PE = synthetic rounded nearest50, half-up.
- Fixed65 study units/leg, independent initial stops20% non-expiry,25% expiry.
- Stop crossed: close just that leg at observed price (including gap-through).
- After first stop, survivor retains original stop until its observed premium is
  <=65% of entry. If already there at the first stop, tighten immediately. Tighten
  to entry once; never loosen. CTC is not guaranteed breakeven after costs/gaps.
- Both still active: close both if their synchronized combined observed premium
  <=25% combined entry. Once either leg closes, no combined target or runner cap.
-14:55 deadline closes survivors using last observation; a stale quote is explicitly
  review-only. No REST request can postpone the exit deadline.
- Rs150/session plusRs65/SL exit including a CTC stop. Observed prices capture
  gaps; the additionalRs1/unit stop allowance is an assumed extra friction charge.
  Study capitalRs250000, no compounding or historical lot-size/margin validation.
- VIX/OI/previous-dayOHLC/current daily open collected asynchronously afterentry.
  OI is the returned option-chain range aggregate, not exchange-wide OI. Retrieval
  time is retained. ENTRY_SKEW absoluteCE-PE >15 flagged, not an entry veto.
  PDR is based on a fresh09:30 spot observation if captured, including on0DTE;
  missing09:30 or previousrange leaves PDR blank, never substitutes day opening.

## Data and persistence

Sheets in the existing workbook: Straddle V2 Strategy and Straddle V2 Logs.
One strategy row/date. Stable strategy ID and date isolate state from all other
paper/manual systems. Hidden State JSON supports restart; restarted open positions
are review-only because unobserved price paths cannot be reconstructed.

Fresh socket observations trigger stops per leg. Combined target and CTC activation
require processed prices no more than2seconds apart. Stale source timestamps are
rejected. Pair observations are sampled into logs every5seconds; every state
transition has its own event. This sampled log is not a complete tick archive.
Missing feed intervals >15seconds make the session review-only. Snapshot is queued
every10seconds and on transitions, with bounded Sheet calls and a final25second
flush. A crash between checkpoints still creates a gap, not a guaranteed recovery.

Historical daily summaries and stop records cannot prove V2 outcomes. Imported
rows retain VIX/OI/OHLC/expiry and reference core premiums, labelled HISTORICAL
AUDIT / NEEDS PRICE PATH. Actual V2 strike/entry/exits/net remain blank. Exact
synthetic selection requires quotes for provisional and selected strikes; minute
candles can be ambiguous when stop, CTC and rebound occur in the same minute.
Any later historical replay must report those ambiguities rather than select a
favorable candle ordering. Existing annual downloader fetches only spotATM and
must be expanded before a complete V2 backtest.

## Workflow and dashboard

Dedicated GitHub workflow starts09:10 IST weekdays and finishes14:55 plus final
write.355minute job ceiling fits the sixhour hosted runner cap when timely. GitHub
scheduling delays can still cause a late start; actual entry is always recorded.
Requires existing FYERS_ACCESS_TOKEN and GOOGLE_SERVICE_ACCOUNT_JSON secrets.
Optional setup_only creates/verifies worksheets without calling FYERS.

Existing dashboard sync now sends core summary and V2 strategy snapshots. V2's
workflow also syncs at completion using existing STRADDLE_DASHBOARD_TOKEN.
The dashboard reload button reads both sheets, and the V2 view checks the saved
snapshot every60seconds. Internal State JSON is removed from browser snapshots.
Review-only, incomplete, nonnumeric and duplicate date rows never enter V2 metrics.

## Verification limits

No live FYERS session or simulated strategy session has been executed by this
change. Syntax/build checks do not establish market execution correctness or a
profitable edge. Freeze these rules and compare chronological forward sessions;
evaluate the individual changes as well as the combined package to limit overfit.

