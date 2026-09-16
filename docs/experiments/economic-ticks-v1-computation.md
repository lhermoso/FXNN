# economic_ticks_v1 — computational contract

This implements the [economic protocol](economic-ticks-v1-protocol.md). No
throughput measurement establishes source observability or economic validity.

## Streaming and exact source order

Verified normalized, quarantine and reserved records are merged by source
sequence. Group boundaries inspect only timestamp/identity before the next
numeric decoder runs. Logical availability is monotonic; original timestamps
remain separate. Clock timers and all-minute decisions precede the source group
at the same time. Finalized bid bars never change retrospectively. Quality
disclosures create causal resets and separate as-of integrity intervals.

The source stream feeds a disk index and bounded feature history in one pass.
Opportunities and bars are append-only JSONL files, with final content hashes;
labels are a separate later projection. No label field is accepted by the
feature interface. The feature builder retains at most1941 bars and500 return
endpoints. Authorized warmup is exported separately for the final frozen model.
Each dataset retains every scheduled open minute, including absent quotes and
unavailable features. A partial build has no completed dataset manifest.

## Disk index

Blocks contain1024 economic groups. Records use51 bytes/group and the common
int64 price representation uses32 bytes/group. Every block stores exact decimal
coefficients at a common base10 scale; exceptional values use arbitrary integer
JSON, without rounding. The technical caps are12000 coefficient/scale bits and
16MiB encoded block bytes. Unsupported precision is a technical failure before
fitting, with partial evidence preserved.

Top trees retain bid/ask minimum, maximum, ordered maximum drop/rise, executable
group counts and eligible timestamp bounds. Only decoded blocks occupy the
256MiB LRU cache; no tick-sized graph of Decimal objects is created. Hashes,
offsets, sizes, schema and source identity are checked before a read-only open.
The caller must check the full expected allocation and retain20GiB free margin.
The prospective index estimate is6.31GB; additional dataset/source/model files
must be included in the runner's preflight.

The permitted bounded-scan variant is used, without persisted microtrees:
first-hit search prunes top nodes, then scans boundary/candidate blocks. Work is
O(B+log(N/B)) per query, not a horizon scan per opportunity. Ordered mark/count
queries merge full interior nodes and scan partial boundary blocks. Original
source timestamps are eligibility predicates, never a globally sorted lookup
column. Price thresholds compare exact rationals; future block extrema can
prune traversal but cannot expose an out-of-range group.

Normal queries stop at the first full-key hazard. P1 first-return queries use
the strictly later source timestamp rule and explicitly preserve adverse group
extrema. `last_quote` supplies a real paired quote and source timestamp for mark
freshness. `range_count` counts eligible unambiguous groups, not ordinal gaps.
The small `iter_groups` audit helper has a hard cap and must not drive production
per-opportunity forward scans.

## Accounts and models

Twelve portfolios share opportunity and index artifacts. Each account jumps to
its next entry, exit, hazard, deadline, funding, decision or reporting boundary.
Held intervals use exact ordered mark summaries, excluding the exit quote.
Certified quote refresh cannot skip an actual absence timer or P1 return.
Certificates bind index identity, full event bounds and first/last source IDs;
the59999ms absence bound is a proven bound, not a measured maximum gap.
Initial cash, actual fees/funding and immediate entry spread marks remain in
the ordered equity path. Uncertainty cannot be repaired by a range summary.

Training arrays are built with bounded streaming input. Weights use only the
retained training entry-to-information-end intervals in open milliseconds.
Full-cap/1941-bar purge and strictly pre-clock integrity admission precede
training. Scalers and weighted model fits remain inside each training scope.
Only exact full training contracts may reuse an authoritative terminal export.

The canonical supervisor reserves14 slots once. Fit contexts hold its exclusive
lock; escaped exceptions or persistence faults poison future fitting across
processes. Clean checkpoints do not close the run. Scientific identity S and
fit identity F exclude later report commits. Release attestation R binds actual
exact-SHA review and meaningful CI. Private package P seals fitting before the
one confirmation opening. UTC month boundaries define bounded checkpoint
chunks; committed chunks, rather than external append operations, are the
authority for exactly-once trades and funding.

## Required verification before real execution

Synthetic tests compare dense clock, first-hit, accounting and integrity
references against production. Include arbitrary precision, non-lattice
barriers, short/long ordered drawdowns, partial blocks, future mutation,
source[100,99,100,101], same-time priorities, absence/timeout equality, quarter
carry, P0/P1 funding, filesystem corruption, process crashes and concurrent
opening attempts. A model persistence failure must never become success on
resume. Read-only replay must preserve ledger bytes and consume zero fits.

The final synthetic benchmark must record source/module/input/output hashes,
parse/group/bar/index build time, query/mark/count/last-quote time, cache bytes,
RSS and disk allocation separately. Earlier primitive measurements do not
certify final code. Repeat only after a change affecting the measured path.
Public evidence contains aggregates and hashes; raw quotes, model arrays and
large predictions stay outside Git.

## Prospective integration benchmark

The integrated index was measured before any stage9 real-price processing or
fit. Synthetic100,000/500,000 normalized quotes (seed20260915) took
2.161670/16.954466 seconds for parse/group/bar/index construction. The nested
parse components were0.302081/2.165098 seconds. Verified index opening took
0.006070/0.055806 seconds. Each size exercised1,000 mixed first-hit queries
(745hits),100 dense first-hit oracles and40 dense mark oracles. First-hit
measurements including those oracle checks took0.647666/2.193356 seconds;
marks including1,000 last-quote checks took2.406385/3.159277 seconds.
Peak process RSS was88,096,768/294,944,768 bytes; retained decoded cache was
53,616,464/267,533,120 bytes. Index payloads were8,300,120/41,500,120 bytes.

A separate process measured1,000 range-count and1,000 last-quote queries per
size against the same verified indexes, with2,000 exact checks per size.
Count took3.050825/4.674662 seconds; last-quote took0.718329/0.565231 seconds.
The measured index module SHA256 was
`19e659873594d62768e3b02c13dfd8ec8550f8806b7ccf3f634799c9e41a48ad`.
These are synthetic component measurements, not full-source, feature, model or
12-portfolio runtime estimates. No real payload, fit or confirmation opening
was used. Private benchmark manifests bind scripts, source modules, synthetic
inputs, outputs and UTC timestamps; their compact hashes accompany release
validation. Later changes to a measured component require new measurement.

## Operational phases and recovery

`scripts/run_economic_ticks.py` exposes explicit data, reservation, model,
portfolio, report, freeze, confirmation, replay and completion phases. The
registered full SHA and the canonical config are mandatory. A single canonical
data-construction intent binds each phase to its output and scientific source.
An incomplete derived-data directory is renamed and retained before an
identical-contract rebuild; a completed artifact is authenticated and reused.
A directory without an existing intent cannot be adopted. This recovery does
not authorize another fit, reservation, acquisition contract or opening.

Model checkpoints must replay their original paths, including after a process
failure checkpoint that has no model-phase field. Missing committed model
artifacts fail closed. Final release verifies model and portfolio replay and
recomputes the development report. Completion similarly compares the final
report with both complete portfolio replays. Runtime bindings verify the actual
Python binary and New York tzfile against the registered fingerprints; HTTPS
transport uses the bound `/usr/bin/curl` binary.

### Integrated synthetic construction check

A separate continuous-calendar fixture covered16,000 minutes and32,000 ticks,
with two quotes per minute, deterministic seed900916 and fixed synthetic
spread. Actual dataset→labels→flat matrix→purge→weights code produced28features,
15,759 feature-available rows,14,460 volatility-available rows and9,972
conclusive labels (2,567TP/7,405SL). At synthetic cutoffs12,000/16,000 minutes,
4,133/8,062 rows survived full-cap/1,941-bar/strict-preclock admission. Weights
were finite, positive and normalized to mean1. A future mutation from minute
9,000 preserved9,001 earlier decisions exactly and changed later features.

Dataset construction took7.23seconds, labels10.72seconds, loading0.40seconds,
admission/weights0.10seconds and the mutated dataset7.52seconds; total26.22s.
Peak RSS was170,770,432bytes including runtime imports; private artifacts
occupied47,622,199bytes. This used no fits, actual market inputs, downloads or
scientific ledger writes. It proves this integrated synthetic path, not the
60-million-tick resource envelope or any economic result. Evidence SHA256:
`3ef2ab3f6be8547cc349bfc2c8af288531b77d8f61764191bcae8ce87e51d642`.

Confirmation prediction construction also has one canonical, exclusively
locked intent binding S/P, both model identities, source evidence and output.
A killed process after directory creation or between model-family exports
leaves a recoverable construction; the interrupted directory is preserved
under a registered archive name, then deterministic predictions are rebuilt
without fitting or changing the guard. Death after candidate publication
requires verification only. Completed artifacts must match their recorded
hash and mathematical replay; corrupt or observed-failed constructions cannot
be silently rebuilt. Alternate output paths do not create a new attempt.
Synthetic process-kill and concurrent-caller tests exercise these transitions.
Reports publish a complete fsynced directory atomically, retaining interrupted
staging directories without exposing a partial final report.
