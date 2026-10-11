# Weekly NIFTY Strangle paper monitor

## Safety and separation

- This strategy is paper-only. It uses FYERS quotes, option-chain data, and a data WebSocket; it has no order-placement API calls.
- It writes cycle snapshots and resumable state to `Nifty Weekly Strangle`, with position entries, buybacks, and square-off metadata in `Nifty Weekly Strangle Logs`. The daily short-straddle script writes to `Nifty Daily straddle` and `Nifty Daily Straddle Logs`; its 15:00 exit is unchanged.
- It uses the same FYERS access-token secret and Google service-account secret. It runs as a second monitor with its own data socket. During Tuesday entry preparation it subscribes to at most 32 near-₹25 candidates, the current weekly legs, and NIFTY spot (at most 35 symbols, below FYERS Standard's 50-symbol socket limit).

## Cycle contract

1. The workflow is scheduled for 08:55 IST. It connects to the data stream after 09:15 and aims to capture entry prices at/just after 09:30. On Tuesday it prepares a bounded candidate list, uses post-09:30 WebSocket ticks if available, then falls back to live quotes. Transient quote errors are retried without writing a failed-capture row; the actual capture time and method are saved.
2. Start a new cycle on Tuesday only, choosing the first listed expiry strictly after that Tuesday. Select the CE and PE independently by the closest option-chain premium to ₹25. Use one 65-unit leg each.
3. Restore active legs or a queued next-cycle entry from the latest `State JSON` cell on each weekday run and continue monitoring them until the selected expiry, a cycle exit, or 15:30 IST.
4. If either leg premium is at least 50% below the other, buy back only the lower-premium leg and paper-sell a replacement of the same option type, same expiry, and nearest premium to 85% of the higher leg's current premium. Leave the higher-premium leg unchanged.
5. At/after 15:25 IST, a premium gap of at least 80% invokes that same replacement rule, whether or not the 50% rule was used earlier that day.
6. On the first replacement, mark the cycle as a straddle and freeze its combined premium reference. If combined active premiums rise 10% above that reference, close both strategy legs and wait until Tuesday to begin the next cycle.
7. Calculate cycle P&L from every sell credit and buyback premium, including replacement legs. When net premium P&L reaches 80% of the original cycle credit, close both active legs and immediately start a cycle using an expiry strictly after the one just closed.
8. If the cycle remains active through expiry, close it at the 09:30 Tuesday rollover and begin the next expiry cycle.

## Logging and dashboard data contract

`Nifty Weekly Strangle` is an append-only cycle snapshot log. It stores cycle identity, snapshot time, expiry, active CE/PE symbols and premiums, high/low premiums, initial credit, realized/open/net premium points, estimated rupee P&L, target, divergence, adjustment count, last event, exit reason, and serialized state used to resume after Actions runs. `Nifty Weekly Strangle Logs` records one row per simulated position open or buyback, including side, symbol, simulated fill premium, quantity, reason, and cycle P&L.

The sync API accepts only the known spreadsheet ID and the snapshot tabs `Nifty Daily straddle` or `Nifty Weekly Strangle`. It validates each tab's headers and stores independent R2 snapshots. `GET /api/weekly-data` returns the weekly snapshot to the dashboard. The logs tab is retained for spreadsheet study and is not used as the dashboard data source. No broker access token or service-account key is sent to the Site.

## Measurement limits

- Simulated fills use the selected option-chain/quote LTP. Actual fills can differ.
- Rupee P&L uses the existing 65-unit project assumption. It includes premium cashflows from rolling legs, but does not estimate brokerage, taxes, or other transaction charges.
- A 10% straddle-stop exit waits for Tuesday; an 80% profit-target exit starts the next-expiry cycle immediately. The Tuesday-only restart after a stop is the conservative behavior because an immediate restart after a stop was not specified.

