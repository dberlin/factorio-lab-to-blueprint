# Phase C gate — three-round corpus audit at budget 30

Six 72-cell rounds, interleaved baseline/branch so that the two arms share the
same box load. Ruling R: the box is never idle and never waited for; `uptime`
and `vmstat 1 3` are recorded immediately before every round instead.

| File | Arm | Tree |
|---|---|---|
| `baseline-master-a4501e0-budget30-round{1,2,3}.jsonl` | baseline | master `a4501e0`, Phase C absent |
| `branch-8ab701f-budget30-round{1,2,3}.jsonl` | candidate | `phase-c-alns` `8ab701f` (= master `a4501e0` merged into the Phase C branch) |

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
