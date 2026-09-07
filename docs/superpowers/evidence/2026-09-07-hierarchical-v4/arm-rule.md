# Task 7 measurement: racing both arms for a coater-free block funded below the floor

Cell: `mall`, `--strategy hierarchical --budget 60 --band portable`, two rounds each of
`--candidate-policy all-products` and `--candidate-policy no-proliferator`, through
`docs/superpowers/evidence/2026-09-07-hierarchical-v4/probe.py` (unmodified). URL in
`mall-url.txt` in this directory (identical to `run_large.sh`'s `$MALL` in the v3 evidence
directory). One build at a time, strictly sequential.

## v3 baseline (both rounds identical; `docs/superpowers/evidence/2026-09-07-hierarchical-v3/gate.md` lines 133, 211-212, 246-247)

| cell | blocks | dispatch ff/sp/both | blocks never placed |
| --- | --- | --- | --- |
| mall/all-products | 39 | 44 / 6 / 13 | 9 |
| mall/no-proliferator | 54 | 0 / 73 / 19 | 31 |

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
never-placed count are identical to v3 in both rounds. This candidate policy is not
predominantly coater-free, so the arm-dispatch cache's new `(shape, budget)` key never crosses
`dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S` differently than v3's shape-only key would have for any
block this build actually solves -- Task 7's branch is inert here. This is the expected,
uninteresting case.

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
