# NIFTY adaptation of trader-skill

## Architecture and scope

The upstream pack is a pipeline: public facts and news become metric files; explicit rules produce shortlists; allocation and risk checks produce proposals; execution is separate. It is not a trained forecasting model. Preserve its explainable handoffs while replacing geography-specific sources and adding the existing research protocol's point-in-time validation.

This document adapts workflow instructions, not upstream executable integrations. Authentication, fetching, persistent storage and scheduling must be implemented and tested before claiming operational readiness. Do not run upstream US scripts with Indian symbols and describe that as a port.

## Module map

| Upstream module | Original function | Indian adaptation | Role in this project |
| --- | --- | --- | --- |
| trader-copycat | Reconstruct investor positions from delayed SEC 13F filings | Effective-dated exchange shareholding filings and disclosed fund portfolios, preserving publication delays and reporting scope | Optional slow ownership context; never infer yesterday's institutional buying from quarterly holdings |
| trader-pelosi | Read US congressional transaction disclosures | No assumed equivalent feed. Study separately disclosed promoter/designated-person transactions and bulk/block deals where accessible | Optional disclosure features; not an Indian politician-tracking replica |
| trader-news | Deduplicate headlines and verify SEC filings | NSE/BSE corporate announcements, issuer investor-relations releases, then reputable news for context | Core catalyst journal with actual availability timestamps |
| trader-analyst | Extract reported SEC XBRL fundamentals | Exchange/issuer quarterly results, annual reports and published guidance | Core earnings context; keep consolidated/standalone, units and exceptional items explicit |
| trader-screener | Apply thresholds, explain pass/fail, rank supplied metrics | Whole-universe equity feature table, explicit filters and frozen ranking rules | Core; extend with price/volume, Nifty and sector strength, and forward outcome scoring |
| trader-alerts | Delayed quotes, thresholds and NYSE clock | Verified FYERS equities data and official NSE calendar/circulars | Core collection clock and data-quality monitoring; alerts only if requested |
| trader-budget | Allocate dollars to target weights and cash buffer | INR whole-share paper sizing using user-specified capital, position/sector caps and modeled costs | Later trading simulation; do not assign capital weights directly from predictive scores |
| trader-risk | Validate proposed orders against limits | Research coverage checks first; later paper position, liquidity, circuit and concentration checks | Separate data eligibility, forecast quality and portfolio risk decisions |
| trader-broker | Prepare an exact approved broker ticket | Optional FYERS/Kite-specific adapter with correct exchange, segment, product, tick size and order status reconciliation | Outside research operation; never import Alpaca ticket assumptions |
| trader-tax | US lot accounting and wash-sale checks | A separately requested Indian tax/accounting module with current authoritative rules | Excluded from forecasting; do not reuse US tax logic |
| trader-rebalance | Restore portfolio target weights | Optional INR paper portfolio rebalancing with whole-share rounding and costs | Excluded from leader forecasting; forecast scoring does not require a portfolio |

## Source contracts

**Identity/universe:** canonical symbol, ISIN where available, exchange, series, FYERS symbol, effective_from/effective_to, sector and benchmark. Resolve renamed securities and corporate actions; do not hardcode today's 50 members for old tests. NIFTY50-INDEX supplies the index, not its constituent prices.

**Market data:** use verified FYERS quotes/history/depth for their documented fields. Keep retrieval time, exchange/last-trade time, trading session, official-close versus LTP status, adjustment convention and latency. Validate each required field against an actual response. Circuit/market depth fields are time-specific snapshots and generally cannot be reconstructed from daily OHLCV. Do not treat total buy/sell depth as executed institutional flow. Maintain currency INR, price rupees, volume shares and turnover rupees; convert crore only for display.

**Results:** record reporting period, filing/publication time, consolidated or standalone basis, units, original/revised version, source document and extracted values. Compare matching quarters and accounting bases. Banks/insurers need sector-appropriate metrics; a missing industrial margin is not zero. Market cap and valuation must use correctly dated prices and share counts/EPS. FYERS screen display availability does not prove API support.

**News/disclosures:** preserve issuer, security mapping, document ID, publication timestamp, first observed timestamp, event date, category, URL and hash. Deduplicate by document ID/hash and cross-listed issuer identity. Read the underlying filing; flag rumors, inaccessible sources and revisions. A post-close disclosure can enter only a forecast frozen after it became public. Same-day bulk/block disclosures cannot explain a shortlist issued before publication.

**Calendar:** timezone Asia/Kolkata. Verify current equity session timings, holidays and special sessions from NSE before determining the target session. Do not use NYSE holidays, US daylight-saving rules or a weekday-only calendar. Do not assume Monday is always the next session. Final daily collection waits for source completeness and finalization rather than relying solely on a fixed clock time.

## Research handoff

Raw snapshots and filings -> validated all-member feature rows -> versioned rules -> frozen next-session paper shortlist -> independently joined outcomes and benchmarks.

Store the input manifest, feature table, forecast and outcome records defined in protocol.md. Every output states whether it is exploratory, retrospective or prospective. Reject incomplete required inputs; do not manufacture missing volumes, news dates or fundamentals to fill the original CSV layout. Begin with a price/volume-only variant if it has adequate data; evaluate catalyst/fundamental additions as separately frozen variants on comparable dates.

## Authoritative source entry points

- NSE filings and announcement routes: https://www.sebi.gov.in/curation/corporate_filings.html
- NSE shareholding patterns: https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern
- NSE market calendar and session information: https://www.nseindia.com/resources/exchange-communication-holidays?apiversion=v2
- FYERS market data: https://fyers.in/api-docs/ai/skills/market-data

Source entry points checked 7 November 2026. Website access is not a guaranteed stable machine-readable API; verify supported access routes, provenance and availability before implementation. No source restrictions should be bypassed.
