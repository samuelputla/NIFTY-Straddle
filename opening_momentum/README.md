# Opening Momentum

Prospective NIFTY 50 paper research. This workflow uses the same FYERS history and
Google workbook as Nifty Study, with three dedicated Opening Momentum tabs.

- **Opening cutoff:** 09:45 IST on regular sessions. Rank all 50 stocks using the
  six completed five-minute bars. Freeze five names before 09:50. Late runs or
  incomplete data cannot produce a valid opening list.
- **v1 score:** Equal-weight cross-sectional percentile ranks for return since
  open, return above the higher of the opening price and previous close,
  opening volume versus the same window on prior days, distance above the
  first 15-minute high, and median opening return of NIFTY 50 industry peers.
  Opening volume uses the median of up to 20 prior comparable sessions with
  at least 15 required. Ties sort by symbol.
- **Baseline:** Use the earliest complete prospective Nifty Study forecast for
  the same universe and session. Missing baselines make the session ineligible
  for the paired comparison.
- **Outcomes:** Compare closing top-five hits and average net paper return.
  Both lists use the 09:50 five-minute open, a 1% stop, 2% target, 15:25 timed
  exit and 10 basis points in round-trip costs including slippage. Gap exits
  use the bar open. If both levels touch in one bar, the stop takes priority.
- **Operations:** Scheduled weekday starts at 09:40 and 15:40 IST, with manual
  same-day entry points. GitHub schedules may start late. The existing verified
  equity calendar is bounded to 2026 and must be extended for 2027 sessions.
- Review at least 30 eligible paired sessions before revising the baseline.
  Raw history and session summaries are uploaded as GitHub run artifacts.
