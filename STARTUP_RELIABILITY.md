# 09:30 startup reliability

## Confirmed evidence, 21 October 2026

The core run created 7 October at 09:06:53 IST captured 09:30:00. On 14 October the run was created 09:23:11 and captured 09:45:40: this included a long in-process provider/quote delay. On 21 October GitHub created the run at 14:12:11, and premiums were captured at 14:12:38. The five-hour failure was before the application executed. That run used old commit 52907bb, predating the merged UTC scheduling and 09:35 cutoff fixes.

GitHub schedule delivery is best effort; a repository change cannot guarantee event creation or runner allocation. Do not infer that more strategies caused this delay, or that explicit UTC alone cures GitHub event-delivery delays.

## Additional hardening

- Previous-day history no longer runs on the premium-entry path. It begins after the websocket starts, is bounded, and leaves context blank/unavailable on failure.
- Gap classification handles missing previous close rather than aborting monitoring or fabricating a value.
- Core VIX/OI background requests begin after entry/socket startup; Next Expiry retains its existing staggered metadata timing.
- Core and Next Expiry monitor jobs become eligible at 09:12 instead of 09:15, while retaining the separate wait job and six-hour monitor budget.
- Shared requirements enable pip caching for both paper workflows and research; remove the unnecessary pip upgrade on every paper run.
- Log actual startup and dependency-ready times in IST and job summaries. These timestamps measure application setup, not GitHub's unobserved scheduling internals.

## Preserved behavior

08:55 paper schedules; research 09:00 schedule; 09:30 target; 09:35 latest entry; per-strategy duplicate-row protection; independent stops; survivor's original stop; 15:00 exit; separate state/tabs/concurrency. No broker order endpoints or Sheet data edits.

An independent local 09:28 startup check was already configured outside this repository. It requires awake online Codex, current tools/access and valid credentials; it is not a guaranteed cloud scheduler. Never duplicate an active run or dispatch late positions.

## Verification boundary

Python AST parsing and YAML structure review were performed. No broker session, manual workflow dispatch, live order, or completed market-session test was run for these changes. Verify first morning's event creation, monitor-ready and capture timestamps before claiming runtime reliability.
