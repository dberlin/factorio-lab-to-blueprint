# Task 7 measurement: racing both arms for a coater-free block funded below the floor

Cell: `mall`, `--strategy hierarchical --budget 60 --band portable`, two rounds each of
`--candidate-policy all-products` and `--candidate-policy no-proliferator`, through
`docs/superpowers/evidence/2026-09-07-hierarchical-v4/probe.py` (unmodified). URL in
`mall-url.txt` in this directory (identical to `run_large.sh`'s `$MALL` in the v3 evidence
directory). One build at a time, strictly sequential. `mall/no-proliferator` got two more
rounds (r3, r4) after round 1 vs round 2 disagreed too violently to read as n=2 -- see
"Extra rounds" below.

## v3 baseline (both rounds identical; `docs/superpowers/evidence/2026-09-07-hierarchical-v3/gate.md` lines 133, 211-212, 246-247)

| cell | blocks | blocks_unattempted | dispatch ff/sp/both | blocks never placed |
| --- | --- | --- | --- | --- |
| mall/all-products | 39 | 0 | 44 / 6 / 13 | 9 |
| mall/no-proliferator | 54 | 0 | 0 / 73 / 19 | 31 |

## Task 7 measurement

| cell | round | blocks | blocks_unattempted | dispatch ff/sp/both | never placed | in-process wall | shell wall | load (runnable_5s_mean) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mall/all-products | r1 | 39 | 0 | 44 / 6 / 13 | 9 | 37.08s | 38.76s | 6.0 |
| mall/all-products | r2 | 39 | 0 | 44 / 6 / 13 | 9 | 36.67s | 38.23s | 5.4 |
| mall/no-proliferator | r1 | 83 | 0 | 0 / 0 / 125 | **6** | 21.26s | 22.91s | 2.8 |
| mall/no-proliferator | r2 | 91 | **67** | 0 / 0 / 137 | **67** | 15.65s | 17.21s | 4.0 |

All four runs' `exit` was 3 (refusal); all `blueprint.exists` is `false`. Budget was 60s plus
`RACE_COMPLETION_GRACE_S = 6.0` (66s ceiling); every run finished well under that (max 38.76s
shell wall) because each refused on "out of re-cut round(s)" or "under the Ns a block solve is
given at all" before the nominal 60s wall was ever spent.

Raw sidecars: `mall-all-products-b60-r1.json`, `mall-all-products-b60-r2.json`,
`mall-no-proliferator-b60-r1.json`, `mall-no-proliferator-b60-r2.json`, each with its
`.log`/`.stdout.txt`/`-load.txt`/`.shellwall.txt` beside it.

## Reading it

**`mall/all-products` is unchanged, exactly.** `blocks`, the dispatch triple, and the
never-placed count are identical to v3 in both rounds. Every per-block budget this build can
ever produce is below `SEQUENCE_PAIR_EXACT_FLOOR_S` regardless of policy (`BLOCK_BUDGET_MAX_S`
is a whole second under it), so Task 7's abstain branch is gated purely on `features.coaters
== 0` -- the budget comparison never changes which side of it a block lands on. The 6 blocks
this cell still dispatches to `sequence-pair` alone therefore must have `coaters > 0` (this
policy allows proliferators, hence spray lanes) *and* `strips > ARM_SMALL_STRIPS`, which is
exactly the cross-tab cell v3's rule already sent to `sequence-pair` alone -- Task 7's
coater-free gate never fires for them, so the branch is inert here, not "not predominantly
coater-free." This is the expected, uninteresting case.

**`mall/no-proliferator` is where the lever fires, and it moved the number this task exists to
move, but not cleanly.** Every dispatch went to `arm_dispatch_both` in both rounds (0
freeform-alone, 0 sequence-pair-alone) -- consistent with the candidate policy itself being
coater-free build-wide (no proliferators means no spray lanes at all), so every block hits
Task 7's new abstain branch unconditionally, exactly as `dispatch.py`'s docstring and the task
brief predicted.

* **Round 1: 31 -> 6 blocks never placed.** A real, large improvement, and it lands on the
  exact number Task 6's floor measurement and the task brief's own framing anticipated ("6
  unplaced when both arms were raced" vs 31 under one).
* **Round 2: 31 -> 67 blocks never placed, of which all 67 are `blocks_unattempted` (never
  even offered to a placer).** This is **worse than the v3 baseline**, not better, and it is
  a real regression axis, not noise to explain away: racing both arms for virtually every
  block in this policy roughly DOUBLES the job count `lay_out`'s round loop must fund
  (`waves = ceil(jobs / width)`), which roughly halves `share = remaining / rounds_left /
  waves` for the SAME wall clock. Round 2's refusal text names this exactly: `"21.1s left
  over 5 wave(s) is under the 5s a block solve is given at all"` -- the round fell below
  `BLOCK_BUDGET_MIN_S` before most blocks were ever attempted, which round 1 (same cell, same
  budget, similar load) did not hit. `blocks` itself also differs between rounds (83 vs 91),
  so the two rounds' re-cut trees genuinely diverged -- consistent with a formula that got
  materially more sensitive to incidental wall-clock timing once every job doubled, not with a
  code defect: `arm_dispatch_both` and the dispatch rule itself behaved identically both
  rounds (0/0/125 and 0/0/137 -- always "both", never freeform-alone or sequence-pair-alone).

**Net verdict: MIXED, not a clean win.** The lever does exactly what Task 6 predicted when it
gets the wall it needs (round 1: 31 -> 6), but spending twice the per-block pool time on every
coater-free block makes the round-funding arithmetic (`share`) meaningfully more fragile, and
in round 2 that fragility produced a cell 2x worse than the v3 baseline it replaces (67 vs 31
unplaced, all of them never even attempted). This is reported as a regression per the task's
own instruction, not re-run to chase a better number.

## Extra rounds

Two more rounds of `mall/no-proliferator` at `--budget 60`, same probe, same argv, same
policy, one build at a time -- because r1 vs r2 disagreed too violently (6 vs 67 never placed)
to read as anything with n=2. `r1`/`r2` are unchanged from above (not re-run).

| round | blocks | blocks_unattempted | dispatch ff/sp/both | never placed | recut_rounds | floor crossed? | in-proc wall | shell wall | load |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r1 | 83 | 0 | 0 / 0 / 125 | 6 | 2 | no | 21.26s | 22.91s | 2.8 |
| r2 | 91 | **67** | 0 / 0 / 137 | **67** | 2 | **yes** | 15.65s | 17.21s | 4.0 |
| r3 | 88 | 0 | 0 / 0 / 132 | 6 | 2 | no | 21.22s | 22.40s | 16.8 |
| r4 | 83 | 0 | 0 / 0 / 125 | 6 | 2 | no | 21.04s | 22.67s | 7.4 |

Raw sidecars for r3/r4: `mall-no-proliferator-b60-r3.json`, `mall-no-proliferator-b60-r4.json`,
each with its `.log`/`.stdout.txt`/`-load.txt`/`.shellwall.txt` beside it.

**As measured:**

* **1 of 4 rounds had `blocks_unattempted > 0`** (r2, 67; r1/r3/r4 all 0).
* **The range of blocks-never-placed across the four rounds is 6-67**: three rounds (r1, r3,
  r4) land at exactly 6; one round (r2) lands at 67. There is no middle value anywhere in
  {6, 67} across four runs -- the four rounds split cleanly into two outcomes, not a spread.
* **`blocks` itself varies run to run**: 83, 91, 88, 83. It does NOT track the
  never-placed/collapsed outcome one-for-one (r1 and r4 both land on 83 with the SAME
  `nogood_skips` (142) and the SAME `arm_dispatch_both` (125) -- i.e. r1 and r4 are not just
  similarly-sized, their stats lines are identical -- while r3, also a "good" round, differs
  from both at 88/150/132). So `blocks` varies among the three good rounds too, not only
  between the good and bad regime.

**Floor-crossing, quoted directly from each round's own refusal text (`recut_rounds` is 2 for
all four rounds; this is the "share fell under `BLOCK_BUDGET_MIN_S`" question, which is
distinct from `recut_rounds` itself):**

* r1: `"out of re-cut round(s) after 2 of 2 the 36.0s round wall allows"` -- the round with
  `recut_rounds=2` ran a full `_solve_round` (every block funded and attempted; `blocks_unattempted=0`); the 6 unplaced are placer-level refusals (`deadline exhausted` / `expansion budget exhausted`), not a funding cutoff.
* r2: `"21.1s left over 5 wave(s) is under the 5s a block solve is given at all"` -- this is
  the raw stats, quoted, not inferred: `remaining=21.1s`, `waves=5`, `21.1/5=4.22s` per wave,
  under `BLOCK_BUDGET_MIN_S=5.0s`. This IS the round where `share` fell under the floor, and
  it fired for the round immediately AFTER `recut_rounds` reached 2 -- before that round's
  `_solve_round` ever ran, which is why 67 blocks were never attempted at all.
* r3: `"out of re-cut round(s) after 2 of 2 the 36.0s round wall allows"` -- same shape as r1,
  no floor crossing.
* r4: `"out of re-cut round(s) after 2 of 2 the 36.0s round wall allows"` -- same shape as r1,
  no floor crossing.

So the diagnosis in the body of this document (racing both arms roughly doubles `waves`,
which roughly halves `share`, and r2 crossed under `BLOCK_BUDGET_MIN_S` where r1 did not) is
directly confirmed by r2's own refusal text, not just inferred from the difference in
outcomes -- and 3 of 4 rounds do NOT cross it at this budget.

**Partition stability, before any recut:** `initial_partition(spec, strip_cap=...)` is a pure
function of the parsed spec -- no wall-clock, no process pool, no placer non-determinism
reaches it. Verified directly (not inferred) with a throwaway, uncommitted `/tmp` script that
imports the real `flab2bp.cli` and `flab2bp.layout.hierarchy.strategy` modules unmodified,
monkeypatches `strategy.initial_partition` to record `len(partition.blocks)` and abort
immediately (so it costs a few seconds, not a full 60s build), and drives it through
`cli.main` with the exact same argv as every round above. Run twice: **24 blocks, both
times, byte-for-byte reproducible.** This did not touch `src/` or `tests/` -- the monkeypatch
lives only in the throwaway script's own process and nothing was written to a tracked file.

So: **the four rounds do NOT differ in `blocks` before any recut** -- all four start from the
identical 24-block partition, deterministically. The divergence (83/91/88/83, and the 6-vs-67
never-placed split) happens entirely AFTER recutting starts, i.e. it is a real-time,
placer-outcome-dependent phenomenon (which specific blocks get stuck and need splitting, and
whether the round that follows still has wall above `BLOCK_BUDGET_MIN_S`), not a partition
that itself differs run to run. This is a different finding from "the partition is unstable"
-- the instability is entirely downstream of it, in the recut/funding interaction the body of
this document already names.

**Bimodal, plainly: this cell is bimodal at this budget.** 3 of 4 rounds cluster tightly at 6
never-placed (`blocks_unattempted=0`, no floor crossing); 1 of 4 collapses to 67 never-placed
(`blocks_unattempted=67`, a directly-quoted floor crossing). There is no value between 6 and
67 in this sample. The good regime is the majority outcome at n=4, but the bad regime is not
rare noise either -- it recurred once in four tries, with a mechanism (the floor crossing)
that is directly legible in the refusal text every time it fires, not a mystery each time.

## Fix round 1: post-fix rounds (r5-r8)

Task 7 fix round 1 (review of commit `3d5aba53`) found the round loop derived arms TWICE per
round under two different budgets -- `jobs`/the stats loop under the budget the round
*started* with, `_solve_round` under the freshly-recomputed `block_budget` -- doubling
`dispatch.block_features`'s `plan_strips` call per shape per round on the unguarded
orchestrator path. Fixed by computing `arms_by_slot` once per round and passing it straight
into `_solve_round` instead of it re-deriving under a fresher budget. Four more rounds of
`mall/no-proliferator --budget 60`, same probe/argv/policy, one build at a time, AFTER that
fix (uncommitted at measurement time, committed together with it):

| round | blocks | blocks_unattempted | dispatch ff/sp/both | never placed | recut_rounds | floor crossed? | in-proc wall | shell wall | load |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r5 | 95 | **70** | 0 / 0 / 143 | **70** | 2 | **yes** | 15.76s | 17.39s | 3.8 |
| r6 | 83 | 0 | 0 / 0 / 125 | 6 | 2 | no | 20.85s | 22.54s | 19.4 |
| r7 | 87 | 0 | 0 / 0 / 131 | 6 | 2 | no | 20.95s | 22.41s | 2.6 |
| r8 | 85 | 0 | 0 / 0 / 128 | 6 | 2 | no | 21.01s | 22.69s | 1.8 |

Raw sidecars: `mall-no-proliferator-b60-r5.json` .. `r8.json`, each with its
`.log`/`.stdout.txt`/`-load.txt`/`.shellwall.txt` beside it.

**As measured: the collapse survives the fix.** 1 of 4 post-fix rounds (r5) still has
`blocks_unattempted > 0` -- exactly the same 1-in-4 rate as the pre-fix sample (r1-r4), and
r5's refusal text is the same directly-quotable floor crossing as pre-fix r2's:
`"21.0s left over 5 wave(s) is under the 5s a block solve is given at all"`. The fix removed a
real, independently-justified defect (double `plan_strips`, mismatched stats attribution) and
is correct on its own merits, but it does not by itself prevent the funding formula from
occasionally crossing `BLOCK_BUDGET_MIN_S` once every job in this cell is doubled. Combined
across all eight rounds measured for this cell (r1-r8), the collapse rate is 2 of 8 (25%), and
every rate everywhere in this sample has been either 1-in-4 or its close neighbor -- consistent
with one underlying phenomenon, not something the fix changed the shape of.

**A related, smaller thing the fix DID resolve, found while investigating Finding 3 below:**
`tests/layout/hierarchy/test_strategy.py::test_a_budget_too_small_to_fund_a_round_still_attempts_the_seed_round`
went from 4/20 failures pre-fix (commit `3d5aba53`) to 0/20 post-fix (this branch's working
tree at measurement time) in the same 20-run sample described under Finding 3. That single
unit test's own spawned-pool timing margin benefited from cutting a redundant `plan_strips`
call out of the hot path; the full `mall/no-proliferator` build's funding-floor collapse did
not.
