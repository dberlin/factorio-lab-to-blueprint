# Phase C gate — three-round corpus audit at budget 30

Six 72-cell rounds, interleaved baseline/branch so that the two arms share the
same box load. Ruling R: the box is never idle and never waited for; `uptime`
and `vmstat 1 3` are recorded immediately before every round instead.

A second candidate arm was measured after the whole-branch review: three more
branch rounds at `ed7f428`, against the same committed master baseline. Its
section is at the bottom of this file.

| File | Arm | Tree |
|---|---|---|
| `baseline-master-a4501e0-budget30-round{1,2,3}.jsonl` | baseline | master `a4501e0`, Phase C absent |
| `branch-8ab701f-budget30-round{1,2,3}.jsonl` | candidate | `phase-c-alns` `8ab701f` (= master `a4501e0` merged into the Phase C branch) |
| `branch-ed7f428-budget30-round{1,2,3}.jsonl` | candidate | `phase-c-alns` `ed7f428` (the whole-branch fixes `1c522e4` + Ruling AF `ed7f428`) |

`baseline-budget30-round{1,2,3}.jsonl` (Task 1, commit `2971089`) are the older
baseline, taken at `22bf910` before master's belt-tier work landed. They are
**stale for this gate**: master changed `src/` (`belt_tiers.py` new,
`validate.py` +90, `freeform.py` +48, `strip_variants.py`, `spec.py`, catalog,
techs, cli, payload) between `22bf910` and `a4501e0`, so the gate regenerates
the baseline from `a4501e0` and compares like with like (Task 14 addendum
item 1).

## Invocation

Identical for both arms, three times each:

```
uv run python <TREE>/scripts/audit.py --budget 30 --jobs 16 --json <FILE>
```

* `<TREE>` for the branch is the worktree itself.
* `<TREE>` for the baseline is a `git archive a4501e0` extraction at
  `/home/dannyb/.claude/jobs/8e787b45/tmp/master-baseline`. `audit.py` inserts
  its own `_ROOT/src` at `sys.path[0]`, so running the extracted tree's own
  copy of the script is what selects master's `flab2bp`; `PYTHONPATH` alone
  would be overridden. `git diff a4501e0 HEAD -- scripts/` is empty, so both
  arms run byte-identical audit code.
* **Cython kernels.** `git diff a4501e0 HEAD -- src/flab2bp/layout/_sequence_kernel.pyx
  src/flab2bp/layout/_route_kernel.pyx setup.py pyproject.toml` is empty, so the
  worktree's compiled
  `_sequence_kernel.cpython-314-x86_64-linux-gnu.so` and
  `_route_kernel.cpython-314-x86_64-linux-gnu.so` were **copied** into the
  baseline tree rather than rebuilt. Stated here because it is a deviation from
  "build the kernels there".

## Machine load before each round (Ruling R)

| Round | Time (local) | `uptime` load 1/5/15 | `vmstat 1 3`: `r` / `wa` / `id` |
|---|---|---|---|
| baseline 1 | 00:50:05 | 2.16 / 3.28 / 4.46 | 4,1,2 / 0,0,0 / 93,99,96 |
| branch 1 | 00:51:21 | 13.08 / 6.70 / 5.58 | 1,1,1 / 0,0,0 / 93,98,98 |
| baseline 2 | 00:52:37 | 16.74 / 9.46 / 6.64 | 1,4,2 / 0,0,0 / 93,98,98 |
| branch 2 | 00:53:51 | 16.19 / 11.18 / 7.47 | 2,2,2 / 0,0,1 / 93,97,98 |
| baseline 3 | 00:55:06 | 17.60 / 12.92 / 8.38 | 2,0,5 / 0,0,0 / 93,98,98 |
| branch 3 | 00:56:22 | 15.97 / 13.69 / 9.01 | 1,1,0 / 0,0,0 / 93,98,98 |

I/O wait was 0 (once 1) in every sample and idle never fell below 93%; the
rising load average is this gate's own rounds. Each round took 71-72 s wall for
72/72 cells.

## Corpus table

| Round | Arm | CLEAN | REFUSED | INVALID | CRASH | p95 wall (s) | area ratio vs its baseline | `audit_compare --regressions-only` |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | baseline | 66 | 6 | 0 | 0 | 28.766 | — | — |
| 1 | branch | 66 | 6 | 0 | 0 | 28.763 | 0.9996 | PASS |
| 2 | baseline | 66 | 6 | 0 | 0 | 28.618 | — | — |
| 2 | branch | 66 | 6 | 0 | 0 | 28.393 | 0.9984 | PASS |
| 3 | baseline | 66 | 6 | 0 | 0 | 28.633 | — | — |
| 3 | branch | 66 | 6 | 0 | 0 | 28.530 | 0.9986 | PASS |

Adding the three `--require-clean` cells the plan names turns every round's
verdict to **FAIL**, on those cells alone:

```
FAIL NOT CLEAN: freeform universe-matrix/no-proliferator: ... game.blueprint_area ...
FAIL NOT CLEAN: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
```

Zero `REGRESSION` lines in any round; the other four refusals are `CARRIED`
(REFUSED on both arms, byte-identical `detail`).

Best-of-three per cell (a cell counts CLEAN if CLEAN in at least one round;
area = the minimum over its CLEAN rounds — the plan defines no best-of-three
rule, this is the construction used): baseline 66/72, branch 66/72, area ratio
0.9992, **zero status flips in either direction**.

## Gate verdicts

| Gate | Spec sentence it is judged against | Verdict |
|---|---|---|
| 1 — continuation | "`graphene/output-products` CLEAN, and the placement stats for that cell carry `feasibility_restart_batches >= 1`" | **FAIL** on the second clause. CLEAN 3/3 at area 420 on both arms; `feasibility_restart_batches == 0` (an exact incumbent exists, so the continuation branch declines). Moot: the cell is already CLEAN at baseline. |
| 2 — window | "The gate passes when the refusal count over those four cells falls against the baseline and no cell regresses." | **FAIL.** The refusal count over the four cells is 3 on both arms; it did not fall. Nothing regressed. |
| 3 — corpus | "no cell that was CLEAN in the baseline refuses, INVALID 0, CRASH 0, wall p95 per cell at or under 30 s, and paired geometric-mean area ... no worse than `1 + 0.013`" — plus "`graphene/output-products` and `universe-matrix/no-proliferator` under both strategies CLEAN in every round" | **FAIL** on the `universe-matrix/no-proliferator` clause only. Every other clause passes in all three rounds. |

## Cells still refusing (identical on both arms, all three rounds)

| Cell | Strategy | What refuses it | Owner |
|---|---|---|---|
| universe-matrix/no-proliferator | freeform | validator `game.blueprint_area`: a 264x162 extent needs 162 latitude rows and the tallest band holds 160 (`EBuildCondition.BlueprintAreaCrossTropic`) | not a placement-search problem |
| universe-matrix/output-products | freeform | packer: no pack of 43 strips wired at any candidate height | phase D |
| universe-matrix/all-products | freeform | packer: no pack of 42 strips wired at any candidate height | phase D |
| universe-matrix/no-proliferator | sequence-pair | deadline exhausted before finding an exact layout | phase D |
| universe-matrix/output-products | sequence-pair | deadline exhausted before finding an exact layout | phase D |
| universe-matrix/all-products | sequence-pair | deadline exhausted before finding an exact layout | phase D |

## Determinism (sequence-pair)

Branch rounds 1-3, every non-timing JSONL field (everything but `seconds` and
`build_wall_time_s`), over the 66 cells CLEAN in all three rounds:

* **sequence-pair: 0 cells differ.** This is the sequence-pair determinism
  evidence the ledger asks for. The `route_bench.py` digest replay quoted
  earlier on this branch is a freeform A* replay that never enters
  `sequence_solver.py`, and does not count here.
* freeform: 6 cells differ, all on how many candidates fit the wall clock. The
  master baseline is the control and differs on **7** cells including one
  sequence-pair cell, so this is pre-existing, not Phase C's.

## The ALNS arms are not visible in this JSONL

`scripts/audit.py`'s schema carries no per-candidate column (spec risk 10), and
`NoValidLayout` carries no `PlacementStats`. The `alns_*` absolutes in the task
report were therefore taken from a separate 72-cell sweep that reproduces
`audit.py`'s cell enumeration exactly and reads `PlacementStats` on solved
cells and the solver's own `_ProductionTelemetry` / `OperatorSession` on
refusing ones. See `.superpowers/sdd/2026-09-02-phase-c-alns-window-repair/task-14-report.md`.

---

# Ruling AF re-measurement — branch `ed7f428`

After Task 14 the whole-branch review found that Task 7's `cap_scale=True` was
truncating the exact window's evidence set, and ruled that the cap be lifted for
LOCAL_EXACT_PACK on this branch (`ed7f428`) behind the hygiene commit
(`1c522e4`), followed by a fresh three-round branch measurement against the
**existing** master baseline. These are those rounds. Same invocation, same
budget, same `--jobs 16`; the baseline files are the ones already committed at
`d9aefd2` and were not re-run.

## Machine load before each round (Ruling R)

| Round | Time (UTC) | `uptime` load 1/5/15 | `vmstat 1 3`: `r` / `wa` / `id` |
|---|---|---|---|
| branch 1 | 06:10:12 | 4.35 / 5.03 / 5.17 | 3,0,3 / 0,4,0 / 93,91,98 |
| branch 2 | 06:11:27 | 14.14 / 8.07 / 6.23 | 8,2,0 / 0,2,0 / 93,95,97 |
| branch 3 | 06:12:43 | 16.22 / 10.31 / 7.18 | 8,5,1 / 0,0,0 / 93,96,97 |
| telemetry sweep | 06:15:26 | 7.63 / 11.36 / 8.27 | 3,6,5 / 0,1,0 / 93,97,97 |

I/O wait was 0 in every sample but two; idle never fell below 91%.

## Corpus table

| Round | Arm | CLEAN | REFUSED | INVALID | CRASH | p95 wall (s) | area ratio vs its baseline | `--regressions-only` | + the 3 `--require-clean` |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | baseline `a4501e0` | 66 | 6 | 0 | 0 | 28.766 | — | — | — |
| 1 | branch `ed7f428` | 66 | 6 | 0 | 0 | 28.557 | 0.9992 | **PASS** | **FAIL** |
| 2 | baseline | 66 | 6 | 0 | 0 | 28.618 | — | — | — |
| 2 | branch | 66 | 6 | 0 | 0 | 28.755 | 0.9991 | **PASS** | **FAIL** |
| 3 | baseline | 66 | 6 | 0 | 0 | 28.633 | — | — | — |
| 3 | branch | 66 | 6 | 0 | 0 | 28.727 | 1.0004 | **PASS** | **FAIL** |

Zero `REGRESSION` lines; all six refusals `CARRIED` with byte-identical
`detail`; **zero status flips in either direction in any round**. The
`--require-clean` FAIL is the same two `universe-matrix/no-proliferator` cells
as above and nothing else. Best-of-three: baseline 66/72, branch 66/72, paired
area ratio 0.9987, zero flips.

**The three gate verdicts are unchanged** — gate 1 fails only on
`feasibility_restart_batches == 0` (moot, the cell is CLEAN at baseline), gate 2
because the four-cell refusal count is 3 on both arms, gate 3 only on
`universe-matrix/no-proliferator`, refused by the validator under freeform and by
the 30 s deadline under sequence-pair. No regression.

## Determinism across the three rounds

Non-timing fields, over the 66 cells CLEAN in all three rounds of an arm:

* branch `ed7f428`: **11 cells differ** — 10 freeform and one sequence-pair,
  `information-matrix/output-products` (area 5150 / 5394 / 5150).
* master `a4501e0` control: **7 cells differ** — 6 freeform and one
  sequence-pair, `information-matrix/all-products`.

Task 14 measured 0 differing sequence-pair cells at `8ab701f`. The change is
what spec §3 predicts rather than a determinism defect: the wall clock decides
how many operator choices a cell draws, and this cell draws only two. Per-seed
determinism is untouched; the number of draws is what varies.

## The window arm after the uncapping

72-cell telemetry sweep at `ed7f428`: `alns_window_solves`,
`alns_window_accepted` and `alns_window_seconds` are **0 corpus-wide on both
arms**, including on `universe-matrix/no-proliferator` (16 choices drawn, 14
applied, 16 detailed routes, 0 window solves). Task 14 measured 4 solves /
0.001992 s / 0 installs at `8ab701f`, so the corpus goes from four sub-millisecond
solves that installed nothing to none.

A probe over the three sequence-pair `universe-matrix` cells, run against this
tree and again with the Ruling AF commit reverted in the working tree 40 seconds
later, says why: **every** LOCAL_EXACT_PACK choice on those cells was paired by
D-UCB with BAND_BOUNDARY, which returns either the empty set (the incumbent
already fits its band) or, uncapped, the whole 43-strip problem — and
`_alns_substitution` drops a whole-problem neighbourhood before the window is
asked. On `universe-matrix/output-products` the cap was what held those calls at
6 strips: capped 8 window-arm calls → 4 usable; uncapped 7 → 0 usable. The
binding constraint is the portfolio pairing, not the scale cap, and it is a
Phase D item.

## The full-suite exit code is not a merge gate here

`uv run pytest -q` on this tree hits an intermittent NATIVE abort inside
OR-Tools — `SharedTreeWorker::SyncWithLocalTrail`, reported as `Fatal Python
error: Aborted` (exit 134) or as a segfault (exit 139) — which kills the whole
process, so the run has no summary line and no failing test to read: only the
faulthandler dump names where it was, most often
`tests/layout/test_freeform.py::test_freeform_placement_stats_carry_the_operator_telemetry`
or `tests/test_pipeline.py::test_build_defaults_to_one_portable_policy`. It is a
pre-existing flake, recorded in this phase's ledger since its first task. Rates
measured deliberately at `ed7f428`, alternating so both arms share the box load
(loads 2.97–8.33, no run waited for an idle box): **branch 0 crashes in 3 runs;
master `a4501e0` control, same interpreter and the same copied kernels with
`PYTHONPATH` at its own `src`, 0 crashes in 3 runs.** Across every full-suite
run made while preparing these two commits the branch crashed **2 times in 10**;
each re-run was immediately clean, and no crash ever came with a test failure.
So a single non-zero exit code from this suite does not distinguish a broken tree
from a busy one, and it must not be read as a merge signal on its own. The policy
this evidence supports: a native crash is re-run once, a clean re-run stands, and
two crashes in a row are reported rather than re-run again.
