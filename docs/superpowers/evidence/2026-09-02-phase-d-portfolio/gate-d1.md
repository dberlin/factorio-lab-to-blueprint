# Gate D1 — wall discipline, budget 30, two explicit strategies

Verdict: **PASS** on every clause, in all three rounds.

## What was measured, and from where

- **Commit under test: `842d9a0801df47fb4a4aa126b33a16793e9a22dc`** (`842d9a0`, branch
  `phase-d-portfolio`) — Tasks 1–6 with their fix rounds; Task 5's
  `fix(layout): stop preparing archive candidates once the deadline has passed` is the tip.
- **Baseline: `9fd65121c956c5479f0f50c6522e0ef885a45a01`** (`9fd6512` = `master`, the branch point),
  file `baseline-budget30.jsonl` from Task 1.
- The three rounds were run **from a `git archive 842d9a0` extracted at
  `/home/dannyb/.claude/jobs/8e787b45/tmp/d1-gate/`**, not from the live worktree, so that
  in-flight edits by other implementers could not contaminate a round. `scripts/audit.py` inserts
  its own `_ROOT/src` at the head of `sys.path`, and this was verified before the rounds:
  `flab2bp.__init__`, `flab2bp.layout.sequence_solver` and the compiled kernel all resolved inside
  the archive.
- **Compiled kernels were copied, not rebuilt.** `git diff --stat master 842d9a0 -- '*.pyx' '*.pxd'
  setup.py pyproject.toml` is **empty**, so the worktree's
  `_route_kernel.cpython-314-x86_64-linux-gnu.so` and
  `_sequence_kernel.cpython-314-x86_64-linux-gnu.so` were copied into the archive's
  `src/flab2bp/layout/`. Every row reports `route_backend == "cython"`.
- The archive was given a minimal read-only `.git` (a detached `HEAD` file holding the full
  `842d9a0…` sha plus an `objects/info/alternates` to the repository's object store) purely so
  `audit.py`'s `_head_commit()` could stamp the rows. It is a frozen file, immune to any commit
  another implementer makes while the rounds run.
- Interpreter: the worktree's `.venv/bin/python` (CPython 3.14) driving the archive's
  `scripts/audit.py`.

### Invocation (per round r ∈ {1,2,3}), run from the archive root

```
python scripts/audit.py --budget 30 --jobs 16 \
    --json docs/superpowers/evidence/2026-09-02-phase-d-portfolio/wall-budget30-round$r.jsonl
```

`--strategy` was left at its default, which is `both` → `("freeform", "sequence-pair")`: the two
explicit strategies, 72 cells, exactly as Task 1 generated the baseline.

### Comparison (per round)

```
python scripts/audit_compare.py \
    docs/superpowers/evidence/2026-09-02-phase-d-portfolio/baseline-budget30.jsonl \
    docs/superpowers/evidence/2026-09-02-phase-d-portfolio/wall-budget30-round$r.jsonl \
    --regressions-only --noise-area 0.013 --p95-seconds 30 --expect-cells 72
```

## Provenance of the rows (Ruling AH)

| file | `commit` | `route_backend` | rows |
| --- | --- | --- | --- |
| `wall-budget30-round1.jsonl` | `842d9a0801df47fb4a4aa126b33a16793e9a22dc` (all 72) | `cython` (all 72) | 72 |
| `wall-budget30-round2.jsonl` | `842d9a0801df47fb4a4aa126b33a16793e9a22dc` (all 72) | `cython` (all 72) | 72 |
| `wall-budget30-round3.jsonl` | `842d9a0801df47fb4a4aa126b33a16793e9a22dc` (all 72) | `cython` (all 72) | 72 |
| `baseline-budget30.jsonl` | **key absent** | **key absent** | 72 |

Per **Ruling AH** the baseline is the 9fd6512 snapshot taken before Task 1 added the provenance
stamp, and it was **not** regenerated. Its rows carry no `commit` and no `route_backend`; they are
read as `row.get("commit", "9fd6512")` and `row.get("route_backend", "cython")`.

## Load at the moment each round started (Ruling R: the box is never idle; never wait for one)

```
=== round 1 load ===
 05:05:48 up 18 days, 10:51,  8 users,  load average: 6.26, 4.03, 3.77
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 2  0      0 1037224152  0 8354492   0    0 50754 15355 23527   4  5  2 93  0  0  0
 1  0      0 1037320080  0 8354496   0    0     0 12604 24826 31701 2 1 97  0  0  0
 1  0      0 1037321096  0 8354496   0    0     0    96 14281 28286 1 1 98  0  0  0

=== round 2 load ===
 05:07:10 up 18 days, 10:53,  8 users,  load average: 14.40, 7.92, 5.20
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 2  0      0 1037601140  0 8354304   0    0 50751 15355 23527   4  5  2 93  0  0  0
 1  0      0 1037603564  0 8354304   0    0     0 15625 15598 34728 1 1 98  0  0  0
 1  0      0 1037604360  0 8354036   0    0     4   184 11960 22403 1 0 98  0  0  0

=== round 3 load ===
 05:08:30 up 18 days, 10:54,  8 users,  load average: 17.33, 10.61, 6.38
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 1  0      0 1037162288  0 8352336   0    0 50748 15354 23527   4  5  2 93  0  0  0
 4  0      0 1037166160  0 8352336   0    0     0     0 12996 23125 1 1 98  0  0  0
 6  0      0 1037167148  0 8352336   0    0     0     0 13691 25923 1 1 98  0  0  0
```

Each round took 71 s, 71 s and 72 s of wall for all 72 cells at `--jobs 16` on the 128-core box.

## The gate, clause by clause

Spec §3, Gate D1, verbatim: *"`scripts/audit.py --budget 30 --jobs 16`, both explicit strategies,
three rounds: per-cell `seconds` maximum at or under 35.0 s, `wall p95` at or under 30.0 s, no cell
that was CLEAN in the baseline becomes non-CLEAN, INVALID 0, CRASH 0, geometric-mean area over
jointly-CLEAN cells within `--noise-area 0.013`. Run before racing exists, so a failure has one
cause."*

| # | Clause (spec sentence) | round 1 | round 2 | round 3 | verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | per-cell `seconds` maximum at or under 35.0 s | 29.43 s | 29.66 s | 28.87 s | **PASS** |
| 2 | `wall p95` at or under 30.0 s | 28.35 s | 28.53 s | 28.43 s | **PASS** |
| 3 | no cell that was CLEAN in the baseline becomes non-CLEAN | none | none | none | **PASS** |
| 4 | INVALID 0 | 0 | 0 | 0 | **PASS** |
| 5 | CRASH 0 | 0 | 0 | 0 | **PASS** |
| 6 | geometric-mean area over jointly-CLEAN cells within 0.013 | 1.000055 | 0.998760 | 0.999377 | **PASS** |
| — | `audit_compare.py` overall verdict (`--regressions-only --noise-area 0.013 --p95-seconds 30 --expect-cells 72`) | PASS, exit 0 | PASS, exit 0 | PASS, exit 0 | **PASS** |

Racing does not exist on this branch yet (`strategy_race.py` is committed but nothing calls it;
`pipeline.build` has no `race` parameter until Task 14), so the spec's "run before racing exists"
precondition holds.

`audit.py` itself exits 1 in every round, and that is expected and is **not** a Gate D1 failure: it
counts the six baseline refusals (the three `universe-matrix` cells on each arm) as failures.
`audit_compare.py` classifies all six as `note CARRIED` and returns PASS.

### `audit_compare.py` summary lines, verbatim

```
== round 1
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0001  p95 28.3s
PASS
exit=0
== round 2
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9988  p95 28.5s
PASS
exit=0
== round 3
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9994  p95 28.4s
PASS
exit=0
```

Each round also printed the same six `note CARRIED:` lines — `freeform universe-matrix/{no-,out-,all-}`
and `sequence-pair universe-matrix/{no-,out-,all-}` — the identical refusals the baseline has. No
`FAIL` line and no `REGRESSED` line appeared in any round.

### The Step 4 wall block, verbatim

```
round1: clean 66/72  p95 28.35s  max 29.43s  invalid 0  crash 0  regressed []
round2: clean 66/72  p95 28.53s  max 29.66s  invalid 0  crash 0  regressed []
round3: clean 66/72  p95 28.43s  max 28.87s  invalid 0  crash 0  regressed []
```

No cell in any round exceeded 30.0 s, so the "cells over 30 s" list is empty in all three rounds.
The Phase A figures this had to beat were p95 30.53 / 30.67 / 30.37 and max 34.77 / 38.97 / 40.29.

Per strategy:

```
  round1 freeform       n=36 max 29.43s p95 26.96s median 5.16s
  round1 sequence-pair  n=36 max 28.75s p95 28.51s median 12.42s
  round2 freeform       n=36 max 29.66s p95 28.67s median 5.43s
  round2 sequence-pair  n=36 max 28.54s p95 28.53s median 12.21s
  round3 freeform       n=36 max 27.28s p95 27.17s median 5.69s
  round3 sequence-pair  n=36 max 28.87s p95 28.60s median 12.24s
```

Task 16 compares these per-strategy rows against Gate D2's.

### Wall overshoot

`audit.py`'s JSONL rows do **not** carry `wall_overshoot_s` or `attempt_wall_s`: Task 6 puts those
on `PlacementStats`, and `audit.Result` was never widened to copy them out. The two available
overshoot signals both read zero:

- **Max `seconds` is 29.66 s against a 30 s budget**, so `wall_overshoot_s`
  (`max(0, attempt_wall − budget − ATOMIC_COMPLETION_GRACE_S)`, grace = 5.0 s) is necessarily
  **0.0 s for all 216 rows** — no attempt even reached its own budget, let alone budget + grace.
- `audit.py`'s own post-deadline reporter ("N cells completed after their own requested search
  deadline") **did not print in any of the three rounds**: zero cells finished after their search
  deadline.

**Max wall overshoot across the three rounds: 0.0 s.**

### The cell the spec targeted

`quantum-chip/no-proliferator`, sequence-pair:

| run | status | seconds | area |
| --- | --- | --- | --- |
| Phase A round 1 / 2 / 3 | — | 34.77 / 38.97 / 40.29 | — |
| baseline (9fd6512) | CLEAN | 12.47 | 3621 |
| round 1 | CLEAN | 10.90 | 3621 |
| round 2 | CLEAN | 12.21 | 3621 |
| round 3 | CLEAN | 10.97 | 3621 |

As Task 1 recorded and the controller addendum states plainly: **the 35–40 s overshoot the spec
targeted was not present at the branch point.** The baseline already had wall max 29.4 s and p95
28.7 s, so Gate D1's wall clauses held before any of the wall-discipline changes landed. This gate
confirms Tasks 2–6 did not lose that, but it cannot and does not demonstrate that they recovered
anything: there was nothing left to recover on this corpus.

## Per-cell area movement against the baseline

Threshold 1.3% (`--noise-area 0.013`). Every jointly-CLEAN cell whose area moved at all is listed;
all of them happen to exceed 1.3%, and every other cell is byte-identical to the baseline.

| round | move | direction | strategy | cell | tier | area | wall (base → round) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | −4.082% | better | freeform | super-magnetic-ring/all-products | mid | 1960 → 1880 | 26.7 → 26.5 s |
| 1 | +4.000% | worse | freeform | casimir-crystal/output-products | large | 1100 → 1144 | 8.9 → 10.5 s |
| 1 | +2.315% | worse | freeform | processor/no-proliferator | mid | 864 → 884 | 5.2 → 3.9 s |
| 1 | −1.667% | better | freeform | super-magnetic-ring/no-proliferator | mid | 2220 → 2183 | 29.4 → 26.9 s |
| 2 | −4.524% | better | sequence-pair | information-matrix/output-products | large | 5394 → 5150 | 23.0 → 25.0 s |
| 2 | −4.082% | better | freeform | super-magnetic-ring/all-products | mid | 1960 → 1880 | 26.7 → 27.9 s |
| 2 | +2.315% | worse | freeform | processor/no-proliferator | mid | 864 → 884 | 5.2 → 5.4 s |
| 2 | −1.667% | better | freeform | super-magnetic-ring/no-proliferator | mid | 2220 → 2183 | 29.4 → 26.7 s |
| 3 | −4.524% | better | sequence-pair | information-matrix/output-products | large | 5394 → 5150 | 23.0 → 26.0 s |
| 3 | +2.315% | worse | freeform | processor/no-proliferator | mid | 864 → 884 | 5.2 → 4.7 s |
| 3 | −1.754% | better | freeform | super-magnetic-ring/output-products | mid | 2052 → 2016 | 27.6 → 26.0 s |

Four cells moved in round 1, four in round 2, three in round 3; 62 or 63 of the 66 jointly-CLEAN
cells are exactly equal to the baseline in every round. Net effect on the gate metric is a wash:
the geometric mean is 1.0001 / 0.9988 / 0.9994.

### Which task each movement implicates — and the answer is "none of them"

Only two files on the diff `9fd6512..842d9a0` are on the **freeform** path: `pipeline.py` (Task 6)
and `base.py` (Task 6's two new `PlacementStats` keys). Task 6 is provably inert unless
`attempt_expired` fires, and it fired **zero** times (max wall 29.66 s vs a 35 s
budget-plus-grace deadline). `sequence_solver.py` (Tasks 2, 3, 5) and `sequence_pair.py` (Task 4)
are sequence-pair-only. So no Phase D change can explain a freeform area move, and four of the five
moving cells are freeform.

Two direct A/B probes confirm the movements are pre-existing wall-clock nondeterminism in the
strategies themselves, present at the baseline commit:

- A second `git archive` of **9fd6512** (same copied kernels, same interpreter) was run on
  `processor --strategy freeform --budget 30 --jobs 16`, four times, against four runs of the
  842d9a0 archive. `processor/no-proliferator` came out **864, 864, 884, 864 at 9fd6512** and
  884 × 4 at 842d9a0; a third tree (842d9a0 with only `pipeline.py` reverted to 9fd6512) produced
  **936 and 884**. All three areas occur at commits that do **not** contain Task 6, so the ±2.3%
  band is the cell's own variance, not a code change.
- `information-matrix --strategy sequence-pair` was probed twice per arm: `output-products` came
  out **5150 at 9fd6512** in both probes and 5150 at 842d9a0 in both — while the 9fd6512 baseline
  *file* records 5394 for it. The same cell therefore moves between two runs of the **baseline**
  code. `information-matrix/all-products` likewise came out 4453 and then 3960 on two 9fd6512
  probes (−11%).

Per the addendum's rule for Task 2: every moving cell's wall (3.9 s to 27.9 s) is under the
compact share of a 30 s budget in the sense that the compaction cancel never had a deadline to
cross — no cell reached its budget — so **Task 2 is inert here**, as predicted. And because no cell
reached 30 s at all:

- **Task 4** (deadline poll inside the annealer) never cut a stage: a cut needs `deadline_reached`,
  which needs the attempt to reach 30 s. Nothing did. The "slightly-worse, wall-clock-
  nondeterministic area on deadline-crossing cells" the addendum warned about did not appear
  because there were no deadline-crossing cells.
- **Task 5** (stop preparing archive candidates after the deadline) likewise never fired.
- **Task 3** (refuse a cold SHARED/TOPOLOGY role reached with under 7.5 s of the attempt's span
  left) produced **no new REFUSED anywhere** and left every sequence-pair area except one exactly
  equal to the baseline, so it either never fired or fired without changing an outcome. The
  addendum's specific worry — new refusals on cells that reach topology late — did not materialise.

### The small tier, diffed explicitly

All 18 small-tier cells (`graphene`, `electromagnetic-matrix`, `plastic` × three specs × two
strategies) are **CLEAN in the baseline and in all three rounds, with byte-identical area in every
round (+0.000% throughout)**:

```
  freeform       electromagnetic-matrix/no-proliferator  base CLEAN area 551 wall 1.87s | r1 551 1.79s | r2 551 1.78s | r3 551 2.02s
  freeform       electromagnetic-matrix/all-products     base CLEAN area 756 wall 16.75s | r1 756 17.68s | r2 756 17.69s | r3 756 13.98s
  freeform       electromagnetic-matrix/output-products  base CLEAN area 576 wall 3.88s | r1 576 4.06s | r2 576 3.62s | r3 576 4.04s
  freeform       graphene/no-proliferator                base CLEAN area 363 wall 0.96s | r1 363 0.92s | r2 363 1.01s | r3 363 0.79s
  freeform       graphene/all-products                   base CLEAN area 504 wall 3.17s | r1 504 3.05s | r2 504 3.04s | r3 504 3.03s
  freeform       graphene/output-products                base CLEAN area 420 wall 2.13s | r1 420 2.27s | r2 420 2.10s | r3 420 1.93s
  freeform       plastic/no-proliferator                 base CLEAN area 760 wall 1.49s | r1 760 1.63s | r2 760 1.87s | r3 760 1.81s
  freeform       plastic/all-products                    base CLEAN area 850 wall 7.43s | r1 850 7.59s | r2 850 8.78s | r3 850 7.35s
  freeform       plastic/output-products                 base CLEAN area 800 wall 6.36s | r1 800 5.54s | r2 800 5.86s | r3 800 5.70s
  sequence-pair  electromagnetic-matrix/no-proliferator  base CLEAN area 627 wall 1.71s | r1 627 1.80s | r2 627 1.66s | r3 627 1.82s
  sequence-pair  electromagnetic-matrix/all-products     base CLEAN area 841 wall 26.65s | r1 841 26.61s | r2 841 26.61s | r3 841 27.90s
  sequence-pair  electromagnetic-matrix/output-products  base CLEAN area 576 wall 6.97s | r1 576 6.11s | r2 576 6.36s | r3 576 6.85s
  sequence-pair  graphene/no-proliferator                base CLEAN area 363 wall 0.71s | r1 363 0.68s | r2 363 0.83s | r3 363 0.66s
  sequence-pair  graphene/all-products                   base CLEAN area 518 wall 28.69s | r1 518 28.51s | r2 518 28.54s | r3 518 28.60s
  sequence-pair  graphene/output-products                base CLEAN area 420 wall 2.73s | r1 420 3.14s | r2 420 2.71s | r3 420 2.65s
  sequence-pair  plastic/no-proliferator                 base CLEAN area 722 wall 3.24s | r1 722 3.30s | r2 722 3.21s | r3 722 3.95s
  sequence-pair  plastic/all-products                    base CLEAN area 882 wall 27.31s | r1 882 26.75s | r2 882 27.58s | r3 882 26.82s
  sequence-pair  plastic/output-products                 base CLEAN area 936 wall 2.33s | r1 936 2.28s | r2 936 2.52s | r3 936 2.44s
```

Three small-tier cells sit at 26.6–28.7 s — within Task 3's "under 7.5 s left" window for the whole
back half of the attempt — and none of them lost a single unit of area or refused.

## Round-to-round determinism

Comparing every non-timing field (`seconds`, `build_wall_time_s`, `commit`, `route_backend`
excluded) across the three rounds, all at the same commit:

```
  sequence-pair round1 vs round2: 1/36 cells differ
  sequence-pair round1 vs round3: 1/36 cells differ
  sequence-pair round2 vs round3: 0/36 cells differ
```

**Sequence-pair is deterministic on 35 of 36 cells.** The single exception is
`information-matrix/output-products` (large tier):

```
    sequence-pair  information-matrix/output-products
        area: 5394 (r1) -> 5150 (r2 = r3)
        projection_frame_candidates: 2 -> 1
        projection_count: 76 -> 114
        projection_collider_pairs: 39819 -> 52930
        projection_power_pairs: 155 -> 195
        projection_sorters: 18924 -> 28614
        wall r1 23.04s  r2 25.00s  r3 26.02s
```

**This is not a deadline cut.** The cell's whole build finishes in 23–26 s against a 30 s budget, so
neither Task 4's anneal poll nor Task 5's archive stop can have fired — both require
`deadline_reached`. The 9fd6512 archive reproduces the same cell at 5150 twice (against 5394 in the
baseline file), so the split predates the branch. Attribution: ordinary CP-SAT / multi-worker
nondeterminism under a 16-way loaded box, unchanged by Phase D.

**Zero cells differ round-to-round because a deadline cut a stage.** Splitting the determinism
result the way the addendum asks: *deadline-cut differences: none, in any pair of rounds*;
*everything else: one sequence-pair cell (above) and five distinct freeform cells.*

Freeform is the noisy arm and always was: 5, 6 and 5 cells differ across the three round pairs
(4, 5 and 5 of those are freeform, over five distinct freeform cells),
including four cells whose area changes between rounds (`casimir-crystal/output-products`
1144↔1100, `super-magnetic-ring/all-products` 1880↔1960, `super-magnetic-ring/no-proliferator`
2183↔2220, `super-magnetic-ring/output-products` 2052↔2016) and several whose only difference is
projection telemetry (`projection_power_pairs` swings from 4 to 554 on the same cell between
rounds). No freeform code changed in Phase D, so this is the arm's baseline behaviour.

## Next levers

None are required: every Gate D1 clause passes with margin (max wall 5.3 s under the 35 s ceiling,
p95 1.5 s under the 30 s ceiling, area within 0.13% of the baseline geometric mean). Two
observations for the phase, not gate failures:

1. **This gate could not exercise Tasks 2–5.** No cell in 216 rows reached its 30 s budget, so the
   cancel, the cold-role refusal, the anneal cut and the archive stop all stayed dormant. Their
   correctness rests entirely on their unit tests. Gate D2, which puts two strategies inside one
   30 s wall with `RACE_COMPLETION_GRACE_S`, is the first run that can plausibly cross a deadline;
   Task 16 should not read "Gate D1 passed" as evidence that the wall-discipline code works, only
   that it costs nothing when idle.
2. **`wall_overshoot_s` / `attempt_wall_s` are invisible to the audit.** Task 6 records them on
   `PlacementStats` and no JSONL row carries them, so a future overshoot can only be inferred from
   `seconds`. Widening `audit.Result` to copy both would make the D2 record strictly better; it is
   out of scope here and nothing was changed for this gate.
