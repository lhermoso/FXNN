# economic_ticks_v1 — pré-registro de execução econômica

Status: implementação prospectiva, antes de dados/labels/fits novos desta etapa.
A autorização de Léo abrange #6–#9. Confirmação 2024 abre uma única vez depois
de T1–T5 verificados, mesmo com desenvolvimento negativo ou inconclusivo.
Nenhuma ordem real ou uso de preços de 2025 faz parte deste protocolo.

## 1. Objective and release bindings

New experiment: `economic_ticks_v1`, EURUSD only, HistData only. Development is UTC [2022-01-01, 2024-01-01). Mandatory one-time confirmation when T1–T5 are satisfied is UTC [2024-01-01, 2025-01-01); economic development results do not veto opening. No 2025 prices are necessary. Negative methodological closure of 7/8 is sufficient; neither technique must improve.

The frozen evidence binds final merged SHAs for 6/7/8/19; source protocol/configuration/code hashes and successful verification reports; all 24 monthly completed/ZIP/CSV/quarantine/reserved/audit fingerprints; exact canonical ledger prefix/count; runtime and timezone database versions; session rule; and exclusive output directory. Issue 19 acquisition completion does not establish adequate economic coverage.

## 2. Mechanical policy, independent of 7/8 results

Use only temporal opportunities. No ranking against CUSUM. Primary direction is the sign of `close[i-1] - close[i-61]` on prior observed bid closes within the same valid history segment; exact equality means no signal. This inherits the deterministic continuation rule proposed in 7.

Use one weighted logistic L2 model with C=1 and exactly the final registered logistic parameters from 7, seed 0. Do not adopt a bagging scheme, seed or ensemble based on 8's external scores. Simplicity is the choice made now; 8 remains a scientific comparison, not a model election.

Recompute the existing 28 oriented features on newly derived tick bid-M1. Keep the volatility formula from 6: exact 1,440-open-minute anchor, trailing 500 returns, span 100, minimum 100. Dynamic barrier distances remain 2.5v/v. Preserve the 1,941-observed-bar feature buffer. Tick bars, labels and scalers are a **new dataset**, not interchangeable with historical M1 artifacts.

Acceptance threshold is fixed at 0.5 (`p >= 0.5`). No threshold search, calibration fit or learned sizing. Calibration is the identity map; fixed decile reliability/Brier diagnostics do not change decisions. This is not a selection using external results from 7/8. A weighted constant trained on the same rows is a probability reference, not a third economic arm. An unavailable logistic model makes the filter unavailable; never replace it with a constant, accept-all rule or another population.

Two economic arms share the entire opportunity stream, capital, size and cost assumptions: primary alone, and primary plus filter. Occupancy legitimately causes different trades; do not retrospectively force identical executed subsets.

## 3. Verified source, event order and causal M1

The loader verifies every monthly artifact, including quarantine. Quote identity is `(source_month, archive_sha256, source_sequence)` because sequences restart monthly. Concatenate fixed source months and check UTC boundaries. A flagged quarantine copy retained in normalized output is the same quote ID, not a second event. Never sort out-of-order quotes or modify issue 19 artifacts.

Source timestamps use fixed EST/UTC−5. The analytical session remains Sunday 17:00 through Friday 17:00 America/New_York with DST. These are distinct rules. The weekly session is a convention, not an authenticated historical broker holiday calendar; valid off-session quotes are audited but calendar-excluded: no OHLC, features, fills, marks or reset of the valid-quote absence timer. They retain source/disclosure bookkeeping. Invalid timestamps, chronology defects and other integrity events remain disclosed even outside sessions. Weekly closures pause elapsed open time; exceptional open-session absences remain explicit.

Replay consumes source sequence. A valid timestamp has logical availability `max(previous_highwater, timestamp)`. A record with unknown timestamp is revealed at its sequence location, anchored to the current highwater. This is a file replay convention, not proof of real delivery time: the source has no receive timestamps. Disclosure key is `(logical_time, monotonically_increasing_source_batch_ordinal)`. A contiguous equal-validated-timestamp group stops at an invalid record; do not regroup all rows sharing highwater or globally sort disclosures by alleged timestamp. An untimed initial record without highwater raises a phase-start integrity event before source-driven entries, never an invented market timestamp. A confirmation defect cannot rewrite the frozen development model. Group-end lookahead may inspect next timestamp/identity only, not next-group prices.

UTC M1 buckets are half-open `[t, t+60s)`. A bar becomes available only when that minute ends. A tick at the next boundary belongs to the next bar; its price cannot be consulted to close the prior bar. Features for decision t use only completed bars ending at or before t. Empty minutes generate absence events, not synthetic OHLC. Bid and ask remain paired for execution; separate side OHLC extrema never create synthetic executable spreads.

Treat contiguous equal-timestamp quotes as a group. Preserve original rows and sequence, but identical bid/ask pairs count as one economic quote; raw counts remain separate. Distinct pairs in a group provide no execution priority. For a simple strict feature contract, any distinct-pair group makes its bar feature-ineligible when that bar closes and resets causal warmup. Do not choose open/close by source order. This uses information already observed before subsequent decisions.

## 4. Quarantine must not become a hindsight entry mask

Issue 19 identified 7,182 out-of-order rows covering at least 120 UTC minutes: 2022-10-31 00:00–00:59 and 2023-10-30 00:00–00:59. Those dates cannot become an ex-post trading avoidance calendar.

During future source integration, derive each defect's source ID, alleged timestamp and preceding highwater. Its conservative integrity interval is `[floor(min_timestamp), ceil(highwater + 1ms))`; unions may be wider than the reported 120 minutes. Do not remap prices or promise only 120 affected minutes. This is retrospective integrity evidence, not information available to earlier trading decisions.

The causal replay reveals an invalid-observation event only when its source sequence arrives. At discovery, block new features, reset the 1,941-valid-observation warmup and mark potentially affected prior history as integrity-tainted. Earlier signals, predictions and fills remain immutable. Their **certainty classification** may become inconclusive; do not rewrite them into no-trades or recompute old signals.

For each training candidate, persist the earliest actual input-bar timestamp used by features, primary and sigma, including the earliest volatility anchor. Use conservative1941-observed-history coverage or the earlier actual anchor, never only entry time. Its training-integrity span starts there and extends through last label information. At a historical fit cutoff, test this full span against defects whose disclosure event key is strictly < the cutoff pre-clock event key; exclude intersections. It must not use defects revealed later. Retain the excluded opportunities and reasons. This is training-only integrity handling, separate from operational replay. Tests must distinguish immutable decisions from certainty reports that legitimately change when a later defect is discovered.

An unknown timestamp or wrong source month makes the archive retrospectively integrity-unresolved; do not invent a narrow interval. At discovery, stop new entries and preserve any exposure. No such rows occurred in 19, but fixtures must cover them and the redaction fix. Do not use invalid prices to fill holes.

## 5. Opportunity grid and gap rules

Create a decision row for **every scheduled open minute**, including minutes with no quotes. ID is `(UTC decision minute, policy version)`. Persist primary side, history status, no-signal, model unavailable, filter rejection, occupied, pending, expired and fill outcomes. An observed-bars-only table would conceal no-quote opportunities.

Feature history retains the inherited reset at 15 missing open minutes, with no filling for shorter gaps. A missing exact anchor makes that daily return unavailable. Sigma remains available if at least100 exact pairs exist among the last500 prior observed endpoints; the most recent endpoint does not need its own anchor. Execution is stricter: **60 open seconds without a new valid quote** triggers a quote-gap event. This fixed operational limit does not prove that shorter gaps hide no barrier touches. Any economic conclusion remains conditional on the supplied quote stream representing the relevant path.

An absence timer advances with the calendar, not only when a quote returns. Inverse elapsed-open time returns the first wall instant >= origin reaching the target duration; a plateau reached Friday17:00 returns Friday17:00, never Sunday reopening. The eligible-open-instant grid is a separate operation. A P1 hazard boundary is its exact logical firing/disclosure time: an exact60second quote neither resets the fired timer nor liquidates P1; an eligible quote strictly later may liquidate. Weekly closures pause open time. A reopening price jump is handled as a gap fill, not a stop-price guarantee. An unmodelled holiday remains an uncertain open-session absence; never infer a new holiday after outcomes. Do not relax either gap rule to recover profitability or evaluability.

## 6. New labels, partitions and fit budget

The learning target remains a proxy: TP first, not net profit. For each causal primary signal at t, independently simulate a hypothetical unit trade under cost scenario S0. Entry uses the first unambiguous eligible quote in the half-open wall-time window `[t, t+30s)`; the exact expiry timestamp cannot fill. Deadline is 4,320 open minutes after decision t. Anchor barriers to actual fill, but freeze distances before the decision from source6 price-volatility convention: `v_price(t)=sigma_daily(t)*last_completed_bid_close`; SL distance `v_price(t)`, TP distance `2.5*v_price(t)`. Current fill does not rescale the distances. sigma and last close use only pre-decision history. Reject nonfinite/nonpositive volatility or nonpositive barrier prices before entry.

Label 1 means TP before deadline; label 0 means SL or observable timeout. Gaps, invalid observations, ambiguous chronology and final-boundary uncertainty are censored for fitting but retained in the operational opportunity table. Their probabilities are still emitted when causal X and a model exist. Unfilled pending entries are non-labelable opportunities. These hypothetical overlapping labels are not portfolio PnL.

Use the exact inherited folds bound in ../../configs/economic_ticks_v1.json: Q2 inner starts2023-01-01, external[2023-04-01,2023-07-01); Q3 inner starts2023-04-01, external[2023-07-01,2023-10-01); Q4 inner starts2023-07-01, external[2023-10-01,2024-01-01), all UTC. Inner validation ends at external start; training uses only prior2022 onward. No legacy minimum_rows/minimum_per_class or bid-only execution is inherited. Complete logistic parameters and source config hashes are bound in that file. Fit only on past rows. Purge by the conservative information deadline, including the registered timeout liquidation allowance of 60 open seconds. Preserve the 1,941-observed-bar feature buffer; do not use realized early exits for purging. Labels whose information cannot be bounded are censored.

Training-local uniqueness uses half-open intervals from entry through the last information required by the label, including the terminal quote and timeout absence. A new sub-minute clock adapter needs an independent oracle; the current minute-only SessionClock cannot accept ticks. Use integer sub-minute coordinates, not rounded-away terminal observations. Fit the scaler only on training rows and their training-local weights.

Budget: at most 6 phase slots (3 folds × inner/refit) × 2 models = **12 development fits**. Exact full-contract cache reuse may reduce this to 8. At most **2 final pre-confirmation fits** on authorized 2022–2023, with purge/buffer before 2024. Thus issue 9 reserves **14 fits maximum**, including constant models and numerical failed attempts. No extra calibrator or retry budget.

Verified global bound:291 after stage8 + issue9 maximum14 = **305**, leaving695 under1000. Verify actual count/bytes before stage9; unused reservation is not permission for new variants. One-class/numerical/model failures retain explicit unavailability and never trigger seed, population or model substitution.

## 7. Account state and event precedence

Initial capital10,000USD; fixed position1,000EUR; at most one position across directions. Use a synthetic 100%-notional margin rule: entry notional plus entry commission must not exceed known liquidation equity. Short entry does not credit notional as profit. Cash changes only through realized PnL, commissions and funding; equity is cash plus unrealized liquidation-side PnL. No probability sizing, reinvestment or implicit leverage. Unknown equity blocks new entries.

States: FLAT, PENDING_ENTRY, OPEN, PENDING_TIMEOUT_EXIT, UNRESOLVED, ENDED. Every decision/event is immutable. Occupied signals are blocked, not queued. A pending signal expires30seconds after its decision. Never fill from an earlier quote. A distinct-pair entry group cancels that minute's pending order rather than searching later for a convenient price.

Reject a new signal if its conservative deadline plus60open-seconds liquidation allowance reaches/exceeds the known evaluation end. This rule is calendar-only, independent of realized duration or last available quote.

At each clock instant t, before source quotes at t: (1) apply rollover to positions held at t−; (2) activate deadlines, expire pending/timeout windows and fire absence timers; (3) finalize the prior M1 minute using already disclosed quotes; (4) emit the scheduled decision from that prior information and the pre-quote account state. Then (5) consume source batches at t in source order: reveal batch quality, manage an existing position, and finally fill an eligible pending entry. Clock events run once, not again for a later batch sharing highwater.

An occupied decision cannot be rewritten into a new entry because a later quote at t closes the position. No position exits at its entry timestamp, including another source batch at that time. No re-entry at an exit timestamp. Barrier equality is a touch, but a touch exactly at the position deadline is timeout, not TP success. This is one ordering policy, not a new sensitivity scenario.

Long entry=ask+adverse slippage; short entry=bid−adverse slippage. Long SL evaluates bid and exits observed bid−slippage; short SL evaluates ask and exits observed ask+slippage. Reopening stops do not fill at the old stop level. TP is an idealized resting limit: fill exactly at TP once the liquidation side touches it, with no favorable price improvement and no extra market slippage; commission still applies. Queue/liquidity sufficiency is an explicit assumption, not established by quotes.

For an existing position, a distinct-pair timestamp group is ambiguous under strict policy, even if source sequence suggests a favorable outcome. Timeout requests the first valid quote with open elapsed milliseconds from deadline in `[0,60000)`, never a stale earlier price; exact60second quotes are excluded. While holding remains conclusive, exposure and scheduled costs continue through the pending exit, including closures; after uncertainty, funding follows the separate conditional P0/P1 rules below. No quote by that limit means UNRESOLVED. Information ends at actual exit plus1ms. Since timeout eligibility is half-open on the millisecond grid, that endpoint is at most the60open-second cap; purge/final-window guards use that same cap, with no additional millisecond beyond it.

Rollover at17:00 New York applies to the position held immediately before17:00, including an exit at that timestamp; an entry exactly17:00 occurs afterward. Missing marks retain last value and age, not a fabricated current value.

## 8. Two fixed uncertainty policies

**P0 strict, primary:** an open position encountering a quote gap, invalid chronology, unresolved tie or unfilled timeout becomes UNRESOLVED, absorbing until replay end. Preserve trade ID, units, side and costs; do not reset to flat. Block later entries. Conclusive equity, final PnL and drawdown become null where unknowable; report last known mark/age. Potential exposure remains reserved. Post-uncertainty hold-to-end funding is a separate conditional accrual, not known realized cash or loss. A later-discovered defect affecting an already closed trade taints the historical result, without deleting or changing that trade.

**P1 sensitivity:** keep the uncertain exposure and block entries until liquidation at the first eligible valid group with source timestamp strictly greater than the hazard’s exact logical firing/disclosure time. Use lowest bid for long, highest ask for short, plus adverse market slippage. If a group supports both TP and SL, use adverse stop handling. If no liquidation is available by evaluation end, remain UNRESOLVED as in P0. Resumption requires liquidation and any required feature warmup; no same-timestamp re-entry.

P1 is a counterfactual execution scenario, **not a mathematical portfolio lower bound**: changed occupancy changes later trades. Positive P1 does not rescue inconclusive P0. Both policies receive the same causal signals; neither changes models, thresholds or quantities. Two uncertainty policies × three cost bundles = six scenarios; two arms = twelve portfolio replays per evaluation window. Report every scenario, never select the attractive one.

## 9. Concrete hypothetical costs and funding

Observed paired bid/ask already charges spread through entry/exit. Never subtract spread again.

| Bundle | USD commission per100,000EUR per fill | Adverse market slippage, pips/fill | Annual funding debit, both directions |
|---|---:|---:|---:|
| S0 optimistic diagnostic |0|0|0%|
| S1 reference |3.50|0.10|5%|
| S2 stress |7.00|0.50|10%|

EURUSD pip=0.0001. Commission is units/100000 × rate, charged separately on each fill. Market slippage applies at entry, stop, timeout and forced liquidation; idealized TP limits use the rule above. Slippage is already embedded in the market fill; attribute it but never subtract it again. At1,000EUR, S1 commission is0.035USD and market slippage0.01USD per fill; S2 is0.07USD and0.05USD. No per-fill cent rounding: reference accounting uses exact rational amounts from finite Decimal inputs, including funding divided by365. Equivalent exact implementations require oracle proof. Round displayed USD summaries only, half-even, preserving exact internal amounts. Invalid prospective scenario fill/barriers block entry; invalid exit calculations preserve an existing exposure as uncertain rather than clip prices or delete it.

Funding uses fixed entry USD notional `N0=units*entry_fill`: debit `N0*annual_rate/365*day_factor` at each Monday–Friday17:00 New York; Wednesday factor3, other weekdays1, weekend0. This fixed base avoids requiring unknown future marks. It is deliberately hypothetical, not an exact OANDA account formula. For P0, freeze the last conclusively known cash ledger after uncertainty; any `funding_if_still_open` is separate and conditional. Unknown stop/limit execution can also make exit time and commission unknown. For P1, funding until its assumed adverse liquidation is scenario cash, not proof of actual borrowing costs; if no liquidation exists, final PnL remains unknown and accruals are separately conditional. If a later defect taints an earlier closed trade, the certainty boundary may move backward while every recorded transaction/decision remains immutable; do not recompute a replacement portfolio.

Official current OANDA documentation motivates explicit rollover/direction/holiday treatment; it does not establish historical2022–2024 rates. The numbers3.5/7/5%/10% are arbitrary frozen sensitivity assumptions, not broker quotations, historical estimates, investment advice or an upper bound on costs. Missing actual broker terms limits implementable-return claims but does not make this fully specified hypothetical experiment unexecutable or waive confirmation. Funding without an identified historical broker schedule precludes an implementable-return claim. Even a successful study can at most justify conditional paper-trading planning with later broker-term validation.

## 10. Portfolio windows, metrics and development diagnostics

Development portfolio starts FLAT on2023-04-01 and runs continuously until2024-01-01. No quarterly resets or artificial liquidation. A new fold model affects only new entries; open positions keep original barriers/management. Report cashflows, marks and exposure by quarter. Missing Q2 models/coverage remain explicit, never drop Q2 to evaluate only Q3/Q4.

Per arm/scenario/period report: realized and unrealized PnL; net equity return; commission, attributed slippage and funding; turnoverEUR/USD; entries/exits/unresolved counts; wall/open-time exposure; peak notional; liquidation-equity drawdown; mark coverage/age; blocked reasons and occupied time; integrity violations. Final PnL/DD is null when unresolved; last-known equity is not final performance. Candidate probability metrics remain separate. No naive IID inference or summed candidate returns.

Promotion quarterly PnL is `E(end−)-E(start−)` on the same continuous portfolio. Snapshot each boundary before its clock events, funding or source quotes. Cashflows belong to `[start,end)`; the identical boundary snapshot ends one quarter and starts the next. For a conclusive open position, `E(t−)=known_cash + units*side*(last_unambiguous_liquidation_side_quote_before_t-entry_fill)`; if flat, the unrealized term is zero and E equals known cash, not zero. Use bid for long and ask for short. Do not subtract hypothetical exit commission/slippage before an actual fill: entry slippage is already in entry price; commissions/funding affect cash when executed. This is liquidation-side marked equity, not a fully net hypothetical liquidation value.

Report mark age in wall and open time. Unresolved/tainted accounting, no valid required mark, or open-time mark age>=60seconds at a boundary makes E and the affected PnL/comparison null. Flat conclusive cash requires no quote mark. Never substitute realized-only PnL or artificially close/reset. Final equity uses this same snapshot metric; total PnL is final E−10000USD. Maximum dollar drawdown is over this same marked equity process; divide by initial10000USD for the registered percentage, not running-peak equity. Unknown required marks make conclusive drawdown unavailable. Quarter-carry and exact-boundary fee/funding fixtures must prove allocation without duplication.

### Development diagnostics and promotion are not opening gates

- G1: artifact/source/replay/review/CI/ledger evidence. Genuine failures feed the relevant T tests below.
- G2: availability of all historical development-fold comparisons. Preserve missing folds. This is not T3: the final authorized model may be available even when an earlier fold was unavailable.
- G3: development portfolio certainty, including unresolved exposure, tainted history and missing final marks. Correctly represented uncertainty is an economic-result limitation, not automatically a T2 processing failure.
- G4: filtered S1 net PnL>0 and filtered minus primary S1 net PnL>0 in each external quarter Q2/Q3/Q4.
- G5: filtered S2 total net PnL>0, maximum dollar drawdown<=5% initial capital and no capital breach.

G4/G5 are promotion criteria. No arbitrary30/120trade floor exists. Report all support; zero trades for an available arm gives zero realized trading PnL, unavailable comparison is not numeric zero, and unresolved exposure has unknown final PnL. No G2/G3/G4/G5 outcome alone permits skipping confirmation.

## 11. Mandatory technically executable confirmation

Opening is required once when **all T1–T5 pass**, regardless of development loss, zero trades, small support, failed promotion, missing historical-fold comparison or a correctly represented development UNRESOLVED portfolio:

| Test | Required before opening | Legacy G relationship |
|---|---|---|
| T1 | Dependencies6/7/8/19 methodologically closed, required releases/provenance verified; negative findings allowed | Evidence component of G1 |
| T2 | Verified development source processable under the frozen source/quality/causal contract; no unhandled semantics or normalization mismatch | Source component of G1; G3 uncertainty alone does not fail it |
| T3 | Planned final logistic and reference constant available/exported/verified using only authorized pre2024 information; no poisoned/unfinished fit | Final model availability, distinct from historical G2 |
| T4 | Causal/state/accounting fixtures, exact replay, independent review, meaningful exact-SHA CI, resources and atomic ledger binding all valid | Release/integrity component of G1 |
| T5 | Complete code/config/runtime/source/calendar/features/barriers/models/threshold/size/cost/uncertainty/metrics/criteria package frozen; guard UNOPENED | Freeze/provenance component of G1 |

No arbitrary support floor is added to T3. Mathematically undefined final fitting, such as a one-class logistic target, is explicit unavailability; no alternate seed/filter/model substitution. Known quality events can yield censored labels or unresolved portfolios while still satisfying T2 if the contract represents them correctly. Their effect on actual final training must be verified, not assumed.

If a T test fails, keep the guard UNOPENED and continue independent authorized technical work. If it cannot be resolved within the scientific/fit contract, report the precise unexecuted confirmation acceptance item and evidence. No parent-convenience waiver or silent completion exists. Any proposed nonexecution closure requires explicit issue-level acceptance resolution and independent review against user scope. No additional permission is needed for already authorized technical work.

Before the first confirmation-specific payload acquisition or numeric inspection of already-held reserved spillover, atomically persist OPENING with the frozen contract hash. Metadata-only listing/form inspection is not price evaluation. States are UNOPENED→OPENING→OPENED→COMPLETED or INCOMPLETE, never backward. Failure after opening does not restore the reserve. Bounded transport retry or deterministic replay of identical bytes/contract continues the same attempt. A post-opening code/semantic change that could alter scientific decisions invalidates confirmation; it cannot create a corrected retuned confirmation on the same year.

Run all six scenarios and both arms without stopping for an attractive/disappointing month. A P0 absorbing state still accounts for the remaining opportunity grid and potential exposure: this can be a completed evaluation with an inconclusive result. Missing required source months or incomplete event accounting prevent completion. Recoverable process crashes preserve the active guard/checkpoint; INCOMPLETE is an explicitly terminal evaluation outcome.

Confirmation uses source-month2024 plus any December2023 EST spillover into UTC2024. Source December2024 may containUTC2025: timestamp validation and reservation precede numeric parsing, enforcing UTC[2024-01-01,2025-01-01). Separate reader/protocol/output, no issue19 mutation, alternate feed, paid replacement or2025 tail to rescue a position. Freeze bounded acquisition/CRC/name/hash rules before opening.

Final models are trained/exported before opening and remain fixed for the whole year. Use authorized development warmup only; begin2024FLAT with10,000USD. No refits, calibration, threshold selection, gap/tie relaxation, clock repair based on outcomes or cost changes. Final-window entry veto is calendar-only: conservative deadline plus the half-open60open-second allowance must be strictly before evaluation end. One terminal observed quote contributes information through timestamp+1ms, already contained within that cap.

Primary confirmation is P0/S1, with the remaining five predeclared sensitivity scenarios. Confirmatory promotion requires conclusive relevant comparisons, disclosed support, positive filtered S1 PnL and improvement over primary annually and in each quarter, positive filtered S2 PnL and dollar drawdown<=5% initial capital and no capital breach. These are descriptive requirements, not statistical power or an executable-profit guarantee.

Final report separates development result, confirmation execution status, confirmation economic result and combined decision. Planning paper trading requires promotion in both development and confirmation. Determinate economic failure in either stage rejects promotion for the specific pipeline; positive confirmation does not erase negative development. If no determinate rejection applies but material uncertainty remains, keep exploration only. No real orders or implementable-return claim.

## 12. Future modules, fixtures and lifecycle

New modules: `tick_economic_source.py` (verified source/bars/quality events), `economic_opportunities.py` (all-minute decisions/features), `economic_labels.py` (hypothetical labels and training censoring), `economic_fit.py` (stage9models/partitions/replay), `economic_simulator.py` (account/event state), `economic_research.py` (freeze/confirmation/report). No historical frozen helper is changed. Existing minute-only SessionClock needs a new sub-minute adapter with an independent oracle. Existing fixed-development downloader cannot become the confirmation reader by merely changing a year argument.

Fixtures must cover sides and no double spread; stop gaps and TP caps; identical/distinct ties and opposite barrier touches; minute boundaries and future-price invariance; invalid quotes amid valid minutes; unknown timestamps/redaction; source-month IDs; highwater reveal and immutable earlier decisions; stale marks and P0 conditional funding excluded from known cash; pending30seconds and absence60open-seconds; weekly closure; deadline precedence and delayed timeout; short cash/capital; DST/Wednesday/exact-rollover ordering; unresolved exposure blocking entries; no same-time re-entry; quarter carry; end-window calendar rejection; training integrity as-of-cutoff versus later defects; full opportunity denominators; unavailable folds; ledger poisoning/cache/no retries; and one-time confirmation/2025price exclusion.

Additional acceptance fixtures: negative/zero-trade/UNRESOLVED development with all T tests passing still opens confirmation; an unavailable historical fold with an available final model does not veto opening; final model unavailable or missing required CI leaves UNOPENED; completed absorbing P0 accounting differs from recoverable crash/checkpoint and terminal INCOMPLETE; exact0.035/0.07USD commissions and no double slippage; P1 absent liquidation remains uncertain; terminal+1ms stays within the same timeout cap across sessions; and post-opening semantic changes cannot reset the guard.

Prefix replay must show that later quotes/quarantine/labels do not change earlier X, signals, fitted states, scores, thresholds or decisions. Final certainty reports may change when a later defect is discovered; test the distinction explicitly. Model persistence requires successful authoritative fit-terminal completion (the run may remain open); failures cannot restart under a fresh output path. Read-only replay must consume no fits or ledger writes. Full unittest, compileall, diff-check and independent exact-SHA review/meaningful GitHub CI remain required; runner/billing failure is missing evidence.

## 13. Weakest assumptions and unresolved empirical facts

Before execution, the source bindings establish file integrity, not60-second economic coverage, how many contiguous economic tie groups exist or whether their bid/ask pairs differ (issue19 counted two rows equal to prior timestamp highwater, not two groups), or whether strict P0 can finish. Do not infer adequacy from24/24downloads or assume tick-M1 fixes old M1 gaps. Strong assumptions remain quote-path completeness, event-time availability, the weekly calendar, idealized unit limit fills and hypothetical funding. An unprocessable/unverifiable source or unavailable final model can prevent opening under a documented T failure; a correctly represented uncertain development portfolio cannot by itself waive confirmation.

## Persistence integrity

Use the merged BoundStageLedger equivalent to bind expected count and exact ledger byte hash atomically under the reservation lock. A separate preflight check is insufficient. Keep every inherited guard and include intervening zero-fit/one-fit completed-run fixtures. New economic-weight fitting helper must preserve the same authoritative persistence/replay lifecycle; source7weighted helper cannot be reused blindly for sub-minute information intervals.

## Consolidation provenance

The diagnosis and fix-impact reviews approved this prospective contract before implementation. Exact cutoff equality remains binding: training admits only defects disclosed strictly before the pre-clock cutoff.

## Index and equity endpoint bindings

All global time binary searches operate on monotonic logical availability with full event-key bounds, never on the original source-timestamp array. Original timestamps are a separate eligibility predicate. Any auxiliary eligible timestamp vector must have proven monotonicity and a mapping to source ordinals; never sort original groups to manufacture one. Strict price queries intersect their ordinal range with the first applicable hazard; hazard queries begin at the entry event key even when price exits at the entire entry timestamp are excluded. P1 combines disclosed availability, valid/calendar eligibility and source_timestamp > hazard.logical_time; that predicate alone is not a binary search on original timestamps.

Within each source batch, after already ordered calendar costs, process quality, manage/fill the existing position, fill a permitted pending entry, then mark the position that remains open. An open-position range summary excludes the quote that executes its exit; append post-fill cash once. A jumped TP fills at the registered limit without a fictitious pre-fill equity peak at the more favorable quote. On entry, immediately mark using the paired opposite liquidation side after entry commission and slippage, so spread and actual entry costs appear once without waiting for another quote. Held-position segments use ordinary eligible marks. Concatenate initial capital, flat cash, actual funding/fee points and held-position summaries in event order. Unknown or ambiguous paths make conclusive drawdown unavailable; later P1 liquidation cannot reconstruct unobserved intragap extrema.

Required fixtures: source timestamps [100,99,100,101] with source ordinals increasing and availability [100,100,100,101]; preserve the first fill, disclose the second-row defect later, P0 unresolved, P1 rejects99 and100 and may liquidate at eligible101. Repeat with an unknown timestamp and an off-session101 followed by an eligible return. Verify source IDs and full keys. Long/short fixtures cover immediate spread/commission/slippage with unchanged quotes, jumped TP without a fictitious peak, gap stop costs once, deadline timeout precedence, funding before same-time exit and quarterly snapshot before both. Hazard groups never contribute ordered extrema. Compare the independent dense account oracle with indexed mark summaries.

These bindings incorporate ../issue9-index-audit.md prospectively. They add no model, cost, threshold, scenario or fit; the ceiling remains14. The prior equity snapshot and strict pre-clock training-cutoff contracts remain in force.

## Canonical run, release identity and recovery lifecycle

One canonical economic_ticks_v1 run reserves at most14 fits once. Clean DEVELOPMENT_VERIFIED and FINAL_MODELS_VERIFIED checkpoints leave this run open; T3 requires every started fit to have a durable terminal record, not run_finished. Two final planned slots remain in the same reservation. Before confirmation, FROZEN_READY seals all fitting permanently, including unused slots. Final completion closes the run once; terminal impossibility does not authorize a replacement reservation.

Scientific identity S hashes actual scientific modules/config/protocol/calendar/runtime/tzdata/source bindings by content. Fit identity F binds S plus training IDs/intervals/weights/parameters/seed/task and its terminal/export hashes, excluding future aggregate reports and freeze. Release attestation R records the exact published SHA with meaningful CI and independent review plus development/model/replay manifests. An aggregates-only commit may change HEAD only after recomputation proves S and F unchanged. Freeze P is a durable private package created after R, binding S, F/model hashes, R, reports, T1–T5 and confirmation contracts. The guard binds hash(P); P need not be committed into its own attested SHA. Later documentation commits preserve S/F/P and have separate provenance; scientific changes after opening invalidate confirmation.

An exclusive supervisor keys ownership to global identity economic_ticks_v1, independent of output directory or namespace aliases. Resume loads the existing run_started,14-fit reservation, durable checkpoints and guard; it never calls start_run again. Verify ledger extension/checkpoints rather than demand the pre-reservation hash remain current. Durable fit cache requires matching contracts, terminal records, export JSON and hashes. A started fit without terminal or a persistence/integrity fault poisons future fitting across process restarts; an orphan model is not success and may not be refitted under another name. Known numerical failure stays terminal/unavailable, never a retry alias. Unstarted independent slots may proceed only under the already registered failure policy while the run is unpoisoned.

Persist/fsync OPENING before first confirmation payload I/O or reserved-content numeric inspection; this already consumes opening. OPENED means the first confirmation payload was durably received and its hash recorded. For already-held reserved content, first persist the pre-inspection marker, then record the first inspection event as the OPENED transition before exposing numeric content. Crash between OPENING and access cannot restore UNOPENED. Recoverable transport/evaluation crashes retain OPENING or OPENED and append failure/checkpoint records; identical-contract resume cannot duplicate trades, funding or fits. INCOMPLETE is an explicit terminal outcome, not each process crash, and cannot regress to OPENED. Later replay of terminal outputs is verification only.

Fixtures: clean pause between development and final slots retains one reservation; post-seal unused slot rejected; pending fit plus orphan export poisons restart/output alias; durable cache cannot reuse mismatched terminal/hash; aggregates-only HEAD change preserves S/F while changed scientific content fails; old-SHA CI fails R; concurrent supervisors permit one opening; fsync-before-I/O crash still consumes it; payload/held-content OPENED evidence; resumed checkpoint does not duplicate funding/trades; terminal INCOMPLETE cannot resume evaluation. These do not add fits, models, thresholds or costs.

## Current stage8 provenance checkpoint

Stage8 PR23 is merged at 04b355fe3ef8afd04ffe22b41b8ee7127497e8c9; issues6/7/8/19 are CLOSED, verified via GitHub. economic-ticks-v1-bindings.json records complete release SHAs, source/report hashes, runtime/tzfile identity and byte-verified canonical ledger:291 fit_started and291 fit_finished. Replay metadata reports verified with0 fits. Stage9 ceiling14 gives prospective305/1000. Rebind ledger atomically at reservation. Dependency provenance is complete; issue9 execution, final review, release and confirmation freeze require their own evidence.

## Implementation bindings before execution

Training cutoffs occur before clock events. A bar ending exactly at a cutoff has not yet been emitted and cannot count toward its 1941-observed-bar buffer. Diagnostic classification metrics include only conclusive labels whose information end is at or before that evaluation end; probabilities remain available for every causal signal including future censoring, unfilled entries and calendar tails. Feature variances use local centered arithmetic for the same inherited formulas, verified against a Decimal70 reference; historical cumulative floating-point cancellation is not a new feature.

The new disk index uses the prospectively permitted bounded-block scan variant, B=1024, exact base10 coefficients and explicit arbitrary-integer fallback. Ordered eligible group counts accompany price extrema; source ordinals are never interpreted as quote counts. Synthetic benchmarks must bind final source hashes before real processing.
