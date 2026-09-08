# Buildings index: measurement disposition

## Revised acceptance, not a fabricated benchmark

The user's later buildings-index/indexed-scans ruling supersedes any marginal
+/-3% timing keep/revert criterion: retain the cleaner indexing. Correctness
and real deadline checks remain; wall/area-only variation from bounded search
is not a microbenchmark veto. Independent jobs may run concurrently, with
failing scenarios rerun serially. The original plan's global serialization
instructions no longer apply.

No three-cell before/after cProfile set or eight-largest Rule-W measurement
set is present in the supplied final evidence. Those original Task 11
measurement steps were **not executed here and are not claimed PASS**. They
are not prerequisites to retain the indexing under revised acceptance. There
is no per-function cumulative-time table, CPU-pressure-normalized speedup, or
attributed performance win to report. No library is added speculatively to
compensate for missing measurements.

The branch's source-reviewed algorithmic changes include cached placement
bounds, immutable and incrementally maintained query indexes, incident-link
lookups, and indexed graph/spatial narrowing. These are source-review claims,
not measured timing attribution. Existing backend-choice evidence remains
historical evidence for the approved dict-backed design; it is not a final
whole-branch profile. The survey's 155 sites / 44 WORTH / 111 HYGIENE
classification does not imply all 155 sites were converted or measured.

## Available wall evidence and its limits

`parallel-correctness-AWM9wmPE/before/corpus.log` records 1472s wall for 72/72
cells at source `2e861af02b6a5062792f8d21fca009b64aee5ab6`.
`parallel-correctness-AWM9wmPE/after/corpus.log` records 1491s wall for 72/72
cells at source `12dd4f3f15861666ff679b392093d4cca1cddbc0`.
Both use 30s per-cell budget, two strategies, power enabled, and banners of
one cell at a time / 128 CP-SAT workers / 7200s run cap. These were concurrent
correctness jobs, not an isolated Rule-W or cProfile experiment. Do not turn
these totals into a speedup claim or a retain/revert decision.

The saved JSONL records do contain two **real grace-overrun** differences,
which are not waived as microbenchmark noise. See `corpus-guard.md` for exact
cells and numbers: universe-matrix freeform/output-products and sequence-pair/
all-products. Their deadline subgate is FAIL in the saved parallel evidence,
with both focused serial adjudications now PASS: CLEAN and zero overshoot.
All 72 emitted-correctness statuses remain CLEAN -> CLEAN, and Main's twelve
fixed-timestamp controls match in full bytes. Combined integration is separate.

No validation, benchmark, profile, or gate command was run by this report
writer. Measured production source is `12dd4f3f`; Main's subsequent TEST-ONLY
fixes are committed at `4605c7c8`. This report makes no integrated-ready or merged claim.
