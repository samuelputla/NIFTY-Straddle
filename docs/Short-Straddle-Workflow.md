# Short Straddle Workflow

The Fixed Entry Straddles GitHub workflow performs paper research on NIFTY ATM short straddles across Current Week, Next Week, and Monthly expiries. It places no orders. The expiry collectors retain independent state and run in parallel.

## Schedule And Trading Assumptions

- Weekdays: GitHub requests a start at 08:55 IST, waits until 09:12, and prepares contracts for 09:30. GitHub schedule delivery is best effort.
- Initial premium capture targets 09:30 IST. Starts after the 09:35 cutoff do not open a position; a collector that reaches its cutoff records a missed entry.
- Nine separate stop-loss scenarios: 10%, 15%, 20%, 25%, 30%, 35%, 40%, 45%, and 50% above each leg's entry premium.
- Each leg stops independently. The surviving leg retains its original stop and exits at the scheduled 15:00 close. These fixed-entry studies do not roll or re-enter.
- Paper stop fills use the stop threshold. The observed triggering price is saved separately as execution evidence. These are not broker fills.
- Current study assumptions are 65 units per contract, ₹150 round-trip charges per scenario, and no additional slippage. These are research constants, not an assertion about current exchange lot sizes or real costs.

## Two Active Fixed-Entry Tabs

**Straddle Fixed Summary** has one row per date and expiry choice. All original 83 columns remain in their original order, followed by Expiry Choice (column CF). It captures:

- Date, weekday, calendar DTE, expiry, ATM strike, and entry VIX.
- Prior-session high/low/close, day opening, gap direction and percentage.
- CE/PE open interest, put/call ratio, the existing custom bias label, explicit OI contract conversion, lot-size assumption, unit basis, and strike scope.
- Entry premiums, observed intraday premium highs/lows, and final option premiums.
- Rupee net results for each of the nine scenarios, individual CE/PE point results, and stop-level/hit descriptions.
- Entry request/retrieval times, option last-trade timestamps when available, OI/VIX retrieval times, source/status notes, and run status.

**Straddle Fixed Logs** has one row per date, expiry choice, and stop percentage (normally 27 rows per full day). The original 31 columns remain in order, followed by Expiry Choice (column AF). It captures date/time, NIFTY spot, VIX, ATM, expiry, SL percentage, CE/PE symbols, entry/stop/exit prices, stop-hit indicators and times, exit reasons, leg and combined point P&L, status, last update, run type, weekday, and DTE.

Log P&L fields are premium points. Summary `% Profit` fields are the combined point result multiplied by 65, less ₹150. The historical column labels are retained to preserve the requested layout.

## Preservation And Shared Writes

The 2026-11-09 migration copied all 69 existing summary rows and 635 existing log rows; cell-by-cell value comparison found zero differences in the original columns. A complete workbook copy and a local source snapshot were saved before consolidation. The six original tabs remain hidden as recovery copies and are no longer collector destinations. Other strategy tabs were not consolidated.

New tabs duplicate the original Current Week layout, retaining header colors, Arial 10 font, column widths, row heights, and frozen panes. Appended historical blocks retain their original cell formatting. Expiry Choice is appended so no existing column shifts. Filters allow each expiry to be viewed separately.

Shared writes use Google's atomic append and its returned physical row range, rather than calculating the next row from a prior read. Each collector may update only rows allocated to it. Duplicate checks are scoped to date plus expiry choice. Unknown append outcomes fail closed rather than retrying an append that may already have succeeded.

The workflow's existing concurrency locks prevent duplicate instances of each expiry collector. Do not sort or rearrange physical rows while collectors are running; use filter views for inspection.

## Downstream Readers And Dashboard

Daily research reads Current Week rows from the consolidated logs. End-of-day validation and isolated comparisons split both shared tabs by Expiry Choice. Automated start checks read the shared summary. Execution measurement and comparison-capture artifacts remain enabled.

The retiring dashboard is disconnected: its scheduled sync workflow, fixed-entry sync step, rolling publisher, comparison publisher, and workflow token references were removed. Collectors, comparisons, and evidence continue saving to Sheets/artifacts. No new dashboard was created and the old hosted website was not deleted. Historical GitHub runs/commits can still contain the retired URLs.

## Data Quality Limits

Migration preservation does not certify historical completeness. Existing missing cells, reconstructions, and quality warnings remain unchanged. Market-feed interruptions, stale ticks, late GitHub starts, authentication failures, and quota failures can still cause missing observations. Never relabel an incomplete session as complete or fabricate data to fill a gap. Setup-only verification checks schemas without FYERS requests or paper entries; live next-session capture requires separate observation.
