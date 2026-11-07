# Short Term Calls And One Share Tracking

The active workflow generates calls around 09:50 IST. The first 30-minute opening range remains part of this test version, as requested. Generation remains a new, unvalidated price/volume rule, not an established HDFC algorithm. All existing breakout, later retest, completed in-band confirmation, actual in-band paper fill, cancellation and exit rules remain.

## Research And Daily Selection

Track every qualifying Intraday and Swing setup at **exactly one share**, including unselected research calls. Rank prospectively and select up to **three Intraday and three Swing setups per issue date**, independently. No forced calls when fewer qualify. The same stock can have one Intraday and one Swing research plan; their outcomes remain separate. Pending/carried positions consume one-share cash reservations, without leverage. Previous Swing selections remain open under their original rules; the daily quota is not a three-position overall holding cap.

Paper Selection in Short Term Calls identifies the chosen six-or-fewer setups. Quantity is one for every new call. Original sealed plans and event IDs remain immutable. The existing Rs300000 capital is retained as the account denominator, rather than being allocated to larger trade quantities.

## Return And RRR

Gross rupees per share = exit minus entry. Gross return percent = 100 times (exit minus entry) divided by entry. With quantity one, gross trade P&L equals rupees per share. Report no trade return for unfilled/cancelled calls.

Target 1 is approximately **1R** and Target 2 approximately **2R**, measured from the highest permitted entry price against the original stop. Therefore risk:reward is about **1:1 at T1** and **1:2 at T2**, before costs. Rounded planning levels and a better actual fill can change the exact ratio. Planned T1 R, Planned T2 R and Realized R are logged. Realized R is (exit minus entry)/(entry minus original stop), and can exceed a planned stop loss during gaps.

The unchanged baseline is **full exit at T1**, original stop or time deadline, whichever happens first. It is a roughly 1:1 booked-target test, not a 1:2 booked-target strategy. T2 remains an observation after exit. Do not silently substitute a T2 exit or partial-exit rule.

## Gross Accounting

Fees and slippage are **not estimated or assumed zero** in the new one-share mode. Estimated costs, net P&L and net return remain unknown/blank. The former Rs40 plus turnover friction proxy is not applied to a single-share research result.

The account shows realized **gross** P&L, gross ROI, open gross P&L, deployed and reserved cash. Gross account ROI is cumulative gross P&L of selected trades divided by Rs300000 times 100. It will be small when trading only six individual shares; the primary setup-comparison measure is per-share percentage return and R, not that large-denominator account ROI. Do not add trade percentages to calculate account ROI. Ambiguous open outcomes withhold definitive account ROI.

## Workflow And Evidence

One GitHub workflow starts research from 9 November 2026. Generation normally runs around 09:50 IST, with a latest generation cutoff of 11:00. Tracking is scheduled every 15 minutes from 09:35–16:20; GitHub scheduling is best effort. Keep the current selection filters and six-session NSE daily/opening FYERS candle inputs. The Monday source history includes Sunday's Muhurat prices and excludes its short-session volume from normal-volume comparisons.

Daily stock-selection filters, support/resistance buffers, risk bands and target multipliers remain experimental. Fundamentals, news, corporate-action adjustment, volume-at-price and executable depth/spreads are not verified by this version. No measured win probability is claimed. No order interfaces are present.

The dedicated Calls, Status, Events, Runs and Portfolio tabs live in the existing Google workbook. Excluded and rejected candidates, raw data and replay results are saved in 90-day workflow artifacts. Zero qualifying calls is valid. Missing candles prevent unsupported entries; stop and target inside the same minute remain ambiguous. Completed one-minute candles reconstruct the 15-minute sequence; these are paper simulations, not broker fills.

Entries expire at 12:30. Intraday exits by 15:00; Swing exits by 15:00 on the fifth normal session including issue day. Stop cancellation begins at the first fully observable minute after issue, even before the frozen signal window. Continue observing original SL, T1 and T2 after exit, without changing booked P&L. Targets reached without a valid retest/entry remain missed moves. Post-exit and unfilled paths receive a daily full-session audit after 15:35. Observe through five normal sessions after the original time deadline.

Calendar coverage ends with 2026 and fails closed beyond it. Token/market-data failures are logged, not replaced by fabricated calls. Existing strategies and the Rs300000 starting balance remain unchanged.

## Checks

`python -m unittest discover -s short_term_calls/tests -v`

The real HTTP client also has eight contract-fixture checks in Linux CI. The local Postman 1.73.0 simulation daemon fails on this Windows host; the same fixture is served directly for the HTTP checks, without real credentials. Authenticated installation checks fetch a prior complete equity session and verify the dedicated Sheet journal without making test trades.
