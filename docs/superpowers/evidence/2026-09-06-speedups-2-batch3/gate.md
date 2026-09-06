# Gate: speedups round 2, third batch (L4 + L5, the freeform budget-discipline levers)

**Verdict: PASS.** Three paired 30 s corpus rounds, 72/72 cells each side, every
round: **zero regressions, INVALID 0, CRASH 0, max `wall_overshoot_s` 0.000 s on
both trees**, and the freeform arm's returned placements are no worse (pooled
-0.40 % area; 9 of 11 moved cell-pairs smaller, and both "larger" pairs are the
baseline's own round-to-round wobble). The one cell that disagrees
(`sequence-pair universe-matrix/all-products`) is a **flake**: it refuses once in
three dedicated re-runs on the **baseline** tree and never in three on the
candidate, and this batch does not touch the sequence-pair arm at all.

| | commit | tree |
|---|---|---|
| baseline | `b01f6fc` (master, the merge base) | `/tmp/speedups-2-batch3-baseline` |
| candidate | `811190a` | `.claude/worktrees/speedups-2-batch3` |

Candidate commits under gate:

* `2e1a724 perf(layout): certify only freeform candidates that would become the incumbent` (L4)
* `c53843f perf(layout): size the next freeform candidate by the median, keep the completion tail a maximum` (L5)
* `2020e86 docs(layout): state the certify gate's invariant precisely`
* `811190a fix(layout): never charge a fresh freeform candidate more than the dearest completed one` (review round 1: Ruling D3 cap, M-1 `started_at` clear, M-3 docstring)

`src/` diff against the baseline is `freeform.py` (+304/-42) and two added lines
of `base.py` — the `budget_unspent_s` and `certify_skipped` field declarations on
`PlacementStats`. `sequence_pair.py` and `sequence_solver.py` are **untouched**,
so the sequence-pair arm is a control in every table below.

## 1. Three paired rounds

Command, both trees: `uv run python scripts/audit.py --budget 30 --json <out>`.
The three baseline rounds were recorded first (22:11-22:21), the three candidate
rounds back to back afterwards (23:00-23:10); they are paired by round index, not
interleaved in time. Load was recorded before each round (`*-round<N>-load.txt`);
the box was never idle (load average 4.4 to 46.2, with the load in I/O wait),
which is this box's normal state.

| round | baseline status counts | candidate status counts | baseline wall | candidate wall | `audit.py` exit |
|---|---|---|---|---|---|
| 1 | **CLEAN 72** | **CLEAN 72** | 1428 s | 1428 s | base 0 / cand 0 |
| 2 | **CLEAN 72** | CLEAN 71, REFUSED 1 | 1427 s | 1414 s | base 0 / cand 1 |
| 3 | **CLEAN 72** | **CLEAN 72** | 1437 s | 1415 s | base 0 / cand 0 |

72 cells present on both sides in every round; no cell absent from any round.
(The wall column is the sum of `build_wall_time_s` over all 72 cells, not the
elapsed time of the run, which is ~190 s at 8 cells in flight.)

`scripts/audit_compare.py --p95-seconds 36` (the default 30 s is below the ~31-32 s
p95 that four islands plus the race completion grace produce on every run,
baseline included):

| round | compare verdict | line |
|---|---|---|
| 1 | PASS | `clean 72  refused 0  invalid 0  crashed 0  paired 72  area ratio 0.9945  p95 31.5s` |
| 2 | FAIL | `clean 71  refused 1  invalid 0  crashed 0  paired 71  area ratio 0.9991  p95 31.2s` — the single REFUSED is `sequence-pair universe-matrix/all-products` |
| 3 | PASS | `clean 72  refused 0  invalid 0  crashed 0  paired 72  area ratio 0.9958  p95 31.9s` |

`audit_compare.py` prints FAIL for any non-clean candidate row regardless of what
the baseline did, so the banner is not the gate. The gate is the three-round
regression rule below.

### Regression rule (spec §2, regression-only)

A regression is a cell CLEAN in **all three** baseline rounds and non-CLEAN in
**all three** candidate rounds.

```
REGRESSIONS  ............................. 0
IMPROVEMENTS (non-clean x3 -> clean x3) .. 0
PARTIAL DISAGREEMENTS .................... 1
INVALID / CRASH, candidate rounds ........ 0
INVALID / CRASH, baseline rounds ......... 0
max wall_overshoot_s, baseline ........... 0.000 s (0 of 216 cell-rounds > 0)
max wall_overshoot_s, candidate .......... 0.000 s (0 of 216 cell-rounds > 0)
```

## 2. `wall_overshoot_s` — the check that matters for this batch

L5 relaxes what must fit before a candidate starts, so this is the constraint the
batch could plausibly break. `audit.py` has each cell's own allowance already
subtracted (the race completion grace for a cell whose islands resolve above one,
the serial grace otherwise), so **any positive value is a cell over its
allowance**, not merely a slow one.

| tree | cell-rounds | max | cells > 0 | freeform max (n) | sequence-pair max (n) |
|---|---|---|---|---|---|
| baseline `b01f6fc` | 216 | **0.000 s** | 0 | 0.000 s (108) | 0.000 s (108) |
| candidate `811190a` | 216 | **0.000 s** | 0 | 0.000 s (108) | 0.000 s (108) |

The distribution is degenerate on both trees: min = median = p95 = max = mean =
0.000 s. The candidate's max does not exceed the baseline's max, so the wall-safety
constraint holds. `judge.py` prints this as an explicit `wall-safety: ... -> OK`
line per round. The 18 dedicated flake re-runs in §3 are 0.000 s as well.

Three candidate freeform cells finish *above* their 30 s budget on the
`attempt_wall_s / budget` measure (`universe-matrix/output-products` up to
104.3 %, `universe-matrix/no-proliferator` 101.9 % mean) and so do baseline cells
(`super-magnetic-ring/output-products` 100.5 %, `universe-matrix/output-products`
103.1 %). That is the completion tail running past the search deadline, which is
exactly what the per-cell allowance exists for — and it happens on both trees.

## 3. The one differing cell, and its ruling

| cell | baseline r1/r2/r3 | candidate r1/r2/r3 |
|---|---|---|
| `sequence-pair universe-matrix/all-products` (spec_index 1) | CLEAN, CLEAN, CLEAN | CLEAN, **REFUSED**, CLEAN |

The refusal is `all 4 sequence islands refused: island 0..3: deadline exhausted
before finding an exact layout` — the honest failure, nothing emitted. It is not a
regression under the rule (it is not non-CLEAN in three candidate rounds). This is
the same borderline cell batch 1 and batch 2 both recorded.

**Flake re-runs** (brief's rule for a partial disagreement): three runs per tree,
`scripts/audit.py --budget 30 --only universe-matrix --strategy sequence-pair`,
alternating trees, files `flake-{baseline,candidate}-um-round{1,2,3}.*`:

| tree | all-products | output-products | no-proliferator |
|---|---|---|---|
| baseline `b01f6fc` | **REFUSED**, CLEAN, CLEAN | CLEAN x3 | CLEAN x3 |
| candidate `811190a` | CLEAN, CLEAN, CLEAN | CLEAN x3 | CLEAN x3 |

17/18 CLEAN, `wall_overshoot_s` 0.000 everywhere, walls 27-34 s. Pooling the
corpus rounds and the dedicated re-runs, the cell is **5/6 CLEAN on each tree** —
the baseline refuses it once in a dedicated run, the candidate once in a corpus
round.

**Ruling: FLAKE, load-dependent, present on both trees.** Two independent reasons:
the symmetric 5/6 count above, and the fact that this batch's `src/` diff is
`freeform.py` plus two `PlacementStats` field declarations — no sequence-pair code
path changed, so a sequence-pair status change cannot be caused by it.

## 4. Area, per arm — Ruling D2's "no worse" claim

Geometric-mean area ratio (candidate / baseline) over cells CLEAN in **both**
files of the paired round, with the count of cells that got larger and smaller:

| round | freeform | sequence-pair |
|---|---|---|
| 1 | n=36 0.99199 (-0.80 %) larger 1 smaller 3 | n=36 0.99697 (-0.30 %) larger 1 smaller 1 |
| 2 | n=36 0.99735 (-0.26 %) larger 1 smaller 3 | n=35 1.00089 (+0.09 %) larger 1 smaller 0 |
| 3 | n=36 0.99876 (-0.12 %) larger 0 smaller 3 | n=36 0.99294 (-0.71 %) larger 1 smaller 1 |
| **pooled** | **n=108 0.99603 (-0.40 %) larger 2 smaller 9** | n=107 0.99689 (-0.31 %) larger 3 smaller 2 |

**Same-tree control** — the same statistic between two rounds of the *same* tree,
where no code changed at all:

| pair | freeform | sequence-pair |
|---|---|---|
| baseline r1 vs r2 | -0.54 %, larger 1 smaller 2 | -0.41 %, larger 1 smaller 2 |
| baseline r1 vs r3 | -0.62 %, larger 3 smaller 2 | -0.25 %, larger 1 smaller 2 |
| baseline r2 vs r3 | -0.08 %, larger 3 smaller 1 | +0.16 %, larger 2 smaller 1 |
| candidate r1 vs r2 | **+0.00 %, nothing moved** | -0.05 %, larger 0 smaller 1 |
| candidate r1 vs r3 | +0.06 %, larger 1 smaller 0 | -0.65 %, larger 0 smaller 2 |
| candidate r2 vs r3 | +0.06 %, larger 1 smaller 0 | +0.00 %, nothing moved |

The candidate-vs-baseline freeform movement (-0.40 %) is inside what the baseline
tree produces against itself (-0.62 % to -0.08 %). Note the control's second
half: **the candidate's freeform arm is markedly more reproducible than the
baseline's** — 0 or 1 cell moves between candidate rounds, against 3-5 between
baseline rounds.

Freeform cells that moved at all, in any round:

| cell | round(s) | baseline -> candidate |
|---|---|---|
| `universe-matrix/no-proliferator` | r1 | 39312 -> **31898** (-18.9 %) |
| `information-matrix/all-products` | r1, r2 | 5159 -> **4760** (-7.7 %) |
| `magnetic-coil/output-products` | r3 | 294 -> **285** (-3.1 %) |
| `super-magnetic-ring/no-proliferator` | r2 | 2220 -> **2183** (-1.7 %) |
| `quantum-chip/all-products` | r1, r2, r3 | 3840 -> **3825** (-0.4 %) |
| `super-magnetic-ring/output-products` | r1, r2, r3 | 2044 / 2040 / 2072 -> 2052 / 2052 / 2052 |

**Ruling D2 (exactness) holds in the data.** Nine of the eleven moved
cell-pairs are smaller. The two larger pairs are both
`super-magnetic-ring/output-products`, where the candidate returns **2052 in all
three rounds** and the baseline returns 2044, 2040 and 2072 — the baseline's own
round-to-round spread straddles the candidate's constant, so this is the
baseline moving, not the candidate losing area. No freeform cell is larger in
the candidate in every round.

## 5. Budget discipline, per freeform cell (`judge.py`)

`certify_skipped` (L4) and `budget_unspent_s` (L5) are **new stats**: the baseline
tree carries neither, and `judge.py` prints `-` there rather than defaulting to
zero. `budget_unspent_s` is only written at a break that **declines to start**
another candidate, so 0.000 means "the sweep did not stop for lack of room" (it
ran out of packings, or converged), not "no budget was left over" — the
budget-minus-wall column is the comparable that exists on both trees.

Corpus totals, freeform arm, pooled over the three rounds (108 cell-rounds each):

| statistic | baseline `b01f6fc` | candidate `811190a` |
|---|---|---|
| `certify_skipped` | *absent* | **sum 372, mean 3.44, max 10** |
| `budget_unspent_s` | *absent* | sum 75.15 s, mean 0.696 s, max 6.97 s |
| candidates attempted (`alns_evaluations`) | sum 780, mean 7.22 | sum 776, mean 7.19 |
| `validation_time_s` | sum **129.15 s**, mean 1.196 | sum **88.16 s** (-31.7 %), mean 0.816 |
| budget - `attempt_wall_s` | sum 2063.9 s, mean 19.11 s | sum 2089.3 s, mean 19.35 s |
| budget spent (`attempt_wall_s`/budget) | mean 36.3 % | mean 35.6 % |

The corpus mean is dominated by 26 small cells that finish in 0.2-13 s and never
approach the budget; the levers can only act on the time-boxed ones. Those, as
the mean of the three rounds:

| freeform cell | budget spent, base -> cand | candidates, base -> cand | `validation_time_s`, base -> cand | `certify_skipped` | `budget_unspent_s` |
|---|---|---|---|---|---|
| `universe-matrix/all-products` | 81.1 % -> **92.3 %** | 2.0 -> **3.0** | 7.25 -> **3.26** | 1.0 | 5.92 |
| `universe-matrix/no-proliferator` | 96.0 % -> 101.9 % | 3.7 -> 4.0 | 10.17 -> 11.47 | 0.0 | 2.26 |
| `universe-matrix/output-products` | 98.2 % -> 95.3 % | 6.0 -> 6.0 | 5.54 -> 5.62 | 0.0 | 4.17 |
| `information-matrix/all-products` | 91.2 % -> **95.9 %** | 7.3 -> **9.3** | 3.17 -> **1.84** | 3.7 | 1.64 |
| `information-matrix/output-products` | 89.3 % -> 86.8 % | 9.0 -> 9.0 | 2.24 -> 1.31 | 2.0 | 1.11 |
| `quantum-chip/all-products` | 97.5 % -> 92.1 % | 10.0 -> **11.0** | 2.87 -> **1.20** | 5.0 | 2.72 |
| `quantum-chip/output-products` | 62.2 % -> 54.2 % | 10.0 -> 10.0 | 1.70 -> **0.22** | 5.0 | 0.00 |
| `super-magnetic-ring/no-proliferator` | 92.4 % -> 93.2 % | 9.0 -> 9.0 | 0.63 -> 0.39 | 3.0 | 2.17 |
| `super-magnetic-ring/all-products` | 90.7 % -> 91.1 % | 9.7 -> 10.0 | 0.70 -> 0.44 | 0.7 | 2.78 |
| `super-magnetic-ring/output-products` | 96.6 % -> 93.1 % | 9.3 -> 8.7 | 0.75 -> 0.24 | 3.0 | 2.27 |

Reading, without spin:

* **L4 fires everywhere and is the batch's measured win.** 372 certifications
  skipped over 108 freeform cell-rounds, and corpus certification time falls
  **129.15 s -> 88.16 s (-31.7 %)**. On individual large cells it is -58 %
  (`quantum-chip/all-products`) to -87 % (`quantum-chip/output-products`).
* **L5 converts that into more search on three cells and not on the rest.**
  `universe-matrix/all-products` goes 2 -> 3 candidates and 81 -> 92 % of budget
  spent; `information-matrix/all-products` 7.3 -> 9.3 candidates;
  `quantum-chip/all-products` 10 -> 11. Elsewhere the freed seconds are simply
  handed back: the corpus mean budget spent moves **36.3 % -> 35.6 %**, i.e.
  slightly *down*, and total candidates attempted is flat (780 -> 776).
* Non-zero `budget_unspent_s` (2-6 s) on the large cells says the room predicate
  is still the binding stop there, so the completion tail — which stays a
  maximum by design — is what is left on the table, not the candidate estimate.

## 6. Freeform re-profile (same grid as `profile-before.jsonl`)

`profile-before.jsonl` (baseline tree at `b01f6fc`) vs `profile-after.jsonl` (this
worktree at `811190a`); per-run JSON/log beside as `{before,after}-<label>.{json,log}`;
load in `profile-{before,after}-load.txt`. Single process, freeform, no islands;
`um60`/`gm200`/`um120`/`qc180` at budget 30, `belt3` and `mall` (`--policy
all-products`) at 60. `validate n`/`validate s` are the harness's `validate` phase
counters — the direct L4 evidence; `spent %` is `wall_s / budget`.

| label | side | verdict | area | wall s | spent % | candidates | validate n | validate s | `certify_skipped` | `budget_unspent_s` | unused s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| um60 | before | OK | 31898 | 24.19 | 80.6 % | 4 | 4 | 9.54 | — | — | 5.81 |
| um60 | **after** | OK | **31898** | 24.03 | 80.1 % | 4 | 4 | 9.31 | **0** | 5.97 | 5.97 |
| gm200 | before | OK | 48640 | 26.93 | 89.8 % | 4 | 4 | 8.46 | — | — | 3.07 |
| gm200 | **after** | OK | **48640** | 23.02 | 76.7 % | 4 | **2** | **4.23** | **2** | 6.98 | 6.98 |
| um120 | before | OK | 80496 | 25.03 | 83.4 % | 2 | 2 | 10.26 | — | — | 4.97 |
| um120 | **after** | OK | **80442** | 29.83 | **99.4 %** | **3** | 2 | 9.73 | **1** | 0.18 | 0.17 |
| qc180 | before | OK | 14896 | 23.06 | 76.9 % | 13 | 4 | 3.25 | — | — | 6.94 |
| qc180 | **after** | OK | **14896** | 22.09 | 73.6 % | 13 | **3** | **2.34** | **1** | 0.00 | 7.91 |
| belt3 | before | OK | 15207 | 49.97 | 83.3 % | 10 | 5 | 6.92 | — | — | 10.03 |
| belt3 | **after** | OK | **15207** | 43.95 | 73.3 % | 10 | **3** | **4.07** | **2** | 0.00 | 16.05 |
| mall | before | REFUSED (packer defect, 46 strips) | — | 38.49 | 64.2 % | — | 0 | 0.00 | — | — | 21.51 |
| mall | **after** | REFUSED (same reason) | — | 37.24 | 62.1 % | — | 0 | 0.00 | — | — | 22.76 |

Reading:

* **Area is identical on four of five OK cells and smaller on the fifth**
  (um120 80496 -> 80442). Ruling D2 again holds: the returned placement is no
  worse anywhere on this grid.
* **L4 lands on this grid too**: validate calls 4 -> 2 (gm200), 5 -> 3 (belt3),
  4 -> 3 (qc180); validate seconds -50 % on gm200 (8.46 -> 4.23, i.e. **14 % of a
  30 s budget returned**), -41 % on belt3, -28 % on qc180. `um60` skips nothing
  (`certify_skipped` 0, four validates before and after): on that cell every
  completed candidate was a would-be incumbent, which is the case the gate
  predicate is supposed to let through unchanged.
* **L5's predicted "~20 % more budget spent" does not appear on this grid, on
  one cell out of six.** um120 goes 83.4 % -> 99.4 % of budget and buys the extra
  candidate the design asked for (2 -> 3), and it is the cell that improves on
  area. The other five spend *less*: gm200 89.8 % -> 76.7 %, belt3 83.3 % ->
  73.3 %, qc180 76.9 % -> 73.6 %, um60 80.6 % -> 80.1 %, mall 64.2 % -> 62.1 %.
  What happens there is that L4's saved certification seconds shorten the run
  rather than being reinvested: the sweep exits for a reason other than the room
  predicate (`budget_unspent_s` is 0.00 on qc180 and belt3, i.e. those sweeps
  never declined to start — they ran out of packings), so a cheaper sweep just
  ends earlier.
* This matches what Task 2's own before/after runs found (`after-t2-gm200.json`,
  `after-t2-um60.json`, kept in this directory): L5 was already inert on gm200
  and um60 because the completion tail, not the candidate estimate, was binding.
  Those two files were measured at `c53843f`, i.e. **before** the `811190a` cap,
  and are retained as the intermediate reading; the `after-*.json` files here are
  the gate's own measurement at `811190a`.
* Single runs on a shared box: the corpus statistic in §4-§5 (108 freeform
  cell-rounds per tree) is the evidence, this grid is the mechanism.

## 7. Spec §2 verdict

**The third batch (L4 + L5, the freeform budget-discipline levers) PASSES its
gate: three paired 30 s rounds against master `b01f6fc` show zero regressions,
INVALID 0, CRASH 0 and max `wall_overshoot_s` 0.000 s on both trees (216
cell-rounds each), with freeform area -0.40 % pooled — inside the baseline tree's
own -0.62 % round-to-round noise, and no cell larger in all three rounds — while
L4 skips 372 certifications and cuts freeform certification time 31.7 %
(129.15 s -> 88.16 s), and the one disagreeing cell
(`sequence-pair universe-matrix/all-products`, an arm this batch does not touch)
refuses once on the baseline tree in dedicated re-runs and is 5/6 CLEAN on each
tree.**

### What this batch did not deliver

The design's L4 gain — "15-19 % of the freeform budget back on the largest cells,
i.e. roughly one extra candidate per run" — is **half delivered**. The seconds
come back (gm200 returns 4.2 s of 30, 14 %; the corpus returns 41 s of
certification over 108 cell-rounds), but they do not reliably become another
candidate.

The design's L5 gain — "~20 % more budget actually spent" — is **not** there as a
corpus statistic: mean budget spent moves 36.3 % -> 35.6 % over 108 freeform
cell-rounds and total candidates attempted 780 -> 776. It is real on the cells
the design named as its evidence, but only some of them: three corpus cells gain
a candidate (`universe-matrix/all-products` 2 -> 3, `information-matrix/all-products`
7.3 -> 9.3, `quantum-chip/all-products` 10 -> 11) and one re-profile cell does
(um120 2 -> 3, 83 % -> 99 % of budget). On the rest the sweep stops for a reason
the room predicate does not control — no new packing, or convergence — so making
the predicate cheaper cannot spend the budget.

Two levers this measurement names for whoever goes next:

1. **The completion tail is now the binding stop on the large cells.**
   `budget_unspent_s` is 2-6 s on every time-boxed freeform cell that declines to
   start, and by construction that is the tail (`compaction + finalize +
   validation` reserves) refusing to fit, not the median candidate estimate. L4
   shrinks the *observed* certify spans that feed `validation_reserve_s`, but the
   reserve is a maximum over them, so one expensive early certification prices
   the whole run.
2. **Sweeps that exit for lack of packings, not lack of time** (`qc180`, `belt3`,
   `quantum-chip/output-products` at 54-74 % of budget with
   `budget_unspent_s` 0.000). Neither L4 nor L5 can reach those; the lever there
   is the packing generator, not the budget arithmetic.

### Files

* `baseline-b01f6fc-round{1,2,3}.{jsonl,txt}`, `-load.txt`, `baseline-b01f6fc-commit.txt`
* `candidate-round{1,2,3}.{jsonl,txt}`, `-load.txt`
* `compare-round{1,2,3}.txt`, `judge-round{1,2,3}.txt`, `judge.py`
* `flake-{baseline,candidate}-um-round{1,2,3}.{jsonl,txt}`, `flake-load.txt`
* `profile-before.jsonl`, `profile-after.jsonl`, `profile-{before,after}-load.txt`,
  `{before,after}-{um60,gm200,um120,qc180,belt3,mall}.{json,log}`
* `after-t2-{gm200,um60}.json` — Task 2's own after-runs, measured at `c53843f`
  (before the `811190a` cap), kept as the intermediate reading
