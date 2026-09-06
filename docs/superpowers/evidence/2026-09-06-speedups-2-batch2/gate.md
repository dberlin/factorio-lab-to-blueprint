# Gate: speedups round 2, second batch (L3, the direct-insert eligibility memos)

**Verdict: PASS.** Three paired 30 s corpus rounds, 72/72 cells each side, every
round: **zero regressions, INVALID 0, CRASH 0, max `wall_overshoot_s` 0.000 s**,
both arms' areas inside the corpus's own round-to-round noise. The one cell that
disagrees (`sequence-pair universe-matrix/all-products`) is a **flake**, ruled by
six dedicated re-runs, three per tree, all CLEAN.

| | commit | tree |
|---|---|---|
| baseline | `79eed92` (master, the merge base) | `/tmp/speedups-2-batch2-baseline` |
| candidate | `ef2207a` | `.claude/worktrees/speedups-2-batch2` |

Candidate commits under gate:

* `2cf583b perf(layout): memoize direct alignment targets per candidate snapshot`
* `ef3da8f perf(layout): memoize direct net candidates per strip pair`
* `ef2207a test(layout): make the direct-candidate drift guard exercise the key builder`

`src/` diff against the baseline is `freeform.py` (+357/-…) and
`sequence_solver.py` (+37/-…) only. `sequence_pair.py` is untouched: the plan's
Task 2 (a checked copy path for `DirectInsertTarget`) was **not** implemented.
Ruling C2 required measuring first, and at `2cf583b` the constructor was 0.122 s
of a 23.3 s qc180 run against `_direct_net_candidates`' 4.327 s, so the memo went
to the larger cost instead. The `DirectInsertTarget.__post_init__` row below is
therefore a *control*, not a target.

## 1. Three paired rounds

Command, both trees: `uv run python scripts/audit.py --budget 30 --json <out>`.
The three baseline rounds were recorded first (20:45-20:55), the three candidate
rounds back to back afterwards (21:46-21:57); they are paired by round index, not
interleaved in time. Load was recorded before each round
(`*-round<N>-load.txt`); the box was never idle (load average 6.9 to 41.8, 95-97 %
idle CPU with the load in I/O wait), which is this box's normal state.

| round | baseline status counts | candidate status counts | baseline wall | candidate wall | `audit.py` exit |
|---|---|---|---|---|---|
| 1 | CLEAN 71, REFUSED 1 | **CLEAN 72** | 194 s | 197 s | base 1 / cand 0 |
| 2 | **CLEAN 72** | CLEAN 71, REFUSED 1 | 196 s | 196 s | base 0 / cand 1 |
| 3 | CLEAN 71, REFUSED 1 | **CLEAN 72** | 197 s | 198 s | base 1 / cand 0 |

72 cells present on both sides in every round; no cell absent from any round.

`scripts/audit_compare.py --p95-seconds 36` (the default 30 s is below the ~31-33 s
p95 that four islands plus the race completion grace produce on every run,
baseline included):

| round | compare verdict | line |
|---|---|---|
| 1 | PASS | `clean 72  refused 0  invalid 0  crashed 0  paired 71  area ratio 1.0001  p95 33.0s` |
| 2 | FAIL | `clean 71  refused 1  invalid 0  crashed 0  paired 71  area ratio 0.9985  p95 31.5s` — the single REFUSED is `sequence-pair universe-matrix/all-products` |
| 3 | PASS | `clean 72  refused 0  invalid 0  crashed 0  paired 71  area ratio 0.9951  p95 32.0s` |

`audit_compare.py` prints FAIL for any non-clean candidate row regardless of what
the baseline did, and master itself is not 72/72 here, so the banner is not the
gate. The gate is the three-round regression rule below.

### Regression rule (spec §2, regression-only)

A regression is a cell CLEAN in **all three** baseline rounds and non-CLEAN in
**all three** candidate rounds.

```
REGRESSIONS  ............................. 0
IMPROVEMENTS (non-clean x3 -> clean x3) .. 0
PARTIAL DISAGREEMENTS .................... 1
INVALID / CRASH, candidate rounds ........ 0
INVALID / CRASH, baseline rounds ......... 0
max wall_overshoot_s, baseline ........... 0.000 s (0 cells > 0)
max wall_overshoot_s, candidate .......... 0.000 s (0 cells > 0)
```

`wall_overshoot_s` has each cell's own allowance already subtracted by
`audit.py`, so 0.000 s across 216 baseline and 216 candidate cell-rounds means no
cell ran over its allowance on either tree.

## 2. The one differing cell, and its ruling

| cell | baseline r1/r2/r3 | candidate r1/r2/r3 |
|---|---|---|
| `sequence-pair universe-matrix/all-products` (spec_index 1) | REFUSED, CLEAN, REFUSED | CLEAN, REFUSED, CLEAN |

This is the borderline cell the first batch's gate already recorded as clearing
"in two of three" rounds. It is not a regression under the rule (it is not CLEAN
in three baseline rounds), and its refusal on both trees is `all 4 sequence
islands refused: deadline exhausted before finding an exact layout` — the honest
failure, nothing emitted.

**Flake re-runs** (brief's rule for a partial disagreement): three runs per tree,
`scripts/audit.py --budget 30 --only universe-matrix --strategy sequence-pair`,
alternating trees, files `flake-{baseline,candidate}-um-round{1,2,3}.*`:

| tree | all-products | output-products | no-proliferator |
|---|---|---|---|
| baseline 79eed92 | CLEAN, CLEAN, CLEAN | CLEAN x3 | CLEAN x3 |
| candidate ef2207a | CLEAN, CLEAN, CLEAN | CLEAN x3 | CLEAN x3 |

18/18 CLEAN, `wall_overshoot_s` 0.000 everywhere, walls 28-36 s. The cell is
CLEAN on both trees whenever it is not racing 69 other cells for the box, and
refuses on both trees about a third of the time when it is.

**Ruling: FLAKE, load-dependent, present on both trees.** Not a regression, and
not evidence of an improvement either. The candidate happens to be 2/3 where the
baseline is 1/3; with n = 3 that is not a signal.

## 3. Area, per arm

Geometric-mean area ratio (candidate / baseline) over cells CLEAN in **both**
files of the paired round:

| round | freeform | sequence-pair |
|---|---|---|
| 1 | n=36 1.00060 (+0.06 %) moved 2 | n=35 0.99958 (-0.04 %) moved 2 |
| 2 | n=36 0.99704 (-0.30 %) moved 3 | n=35 1.00000 (+0.00 %) moved 0 |
| 3 | n=36 0.99413 (-0.59 %) moved 3 | n=35 0.99602 (-0.40 %) moved 3 |
| **pooled** | **n=108 0.99726 (-0.27 %)** | **n=105 0.99853 (-0.15 %)** |
| pooled, all cells | n=213 0.99789 (-0.21 %) | |

**Same-arm control** — the same statistic between two rounds of the *same* tree,
where no code changed at all:

| pair | freeform | sequence-pair |
|---|---|---|
| baseline r1 vs r2 | +0.27 %, moved 3 | +0.05 %, moved 1 |
| baseline r1 vs r3 | +0.65 %, moved 3 | +0.42 %, moved 2 |
| baseline r2 vs r3 | +0.38 %, moved 4 | +0.36 %, moved 3 |
| candidate r1 vs r2 | -0.09 %, moved 2 | +0.10 %, moved 1 |
| candidate r1 vs r3 | -0.00 %, moved 2 | +0.25 %, moved 3 |
| candidate r2 vs r3 | +0.08 %, moved 3 | -0.04 %, moved 3 |

The candidate-vs-baseline movement (-0.27 % / -0.15 %) is smaller than what the
baseline tree produces against itself (up to +0.65 %). **Both arms are unchanged
within noise.** Note that freeform is *not* bit-identical here the way it was in
batch 1: the compact-seed and island work from batch 1 leaves several freeform
cells time-boxed and load-sensitive, and the baseline moves the same 2-4 cells
per round-pair on its own. The cells that moved at all, in any round, were
`super-magnetic-ring`, `information-matrix/all-products`,
`magnetic-coil/output-products`, `universe-matrix/no-proliferator` (freeform) and
`quantum-chip/all-products`, `universe-matrix/{no-proliferator,output-products}`
(sequence-pair) — the time-boxed ones.

## 4. Function-level before/after (single process, no `--islands`)

`--cprofile` with `--islands 4` profiles only the coordinator process, so the
pre-pass is invisible there. These are single-process runs of
`docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py`
(`quantum-chip --rate 180 --budget 30`, and the `mall` URL
`--policy all-products --budget 60`), which is where `_variant_direct_eligibility`
appears. Both cells REFUSE at these budgets without islands, before and after,
unchanged — they are profiling probes, not verdicts.

Sources: `79eed92 -> 2cf583b` from the Task 1 implementer
(`/home/dannyb/.claude/jobs/02fee873/tmp/{before,after}-qc180-solo.pstats`);
`2cf583b -> ef3da8f` from the Task 2 implementer
(`.../tmp/t2/{head,after}-{qc180,mall}.pstats`); `ef2207a` measured fresh for this
gate from this worktree (`head-solo-qc180.pstats`, `head-solo-mall.pstats`,
load in `head-solo-load.txt`).

### qc180 (`quantum-chip` rate 180, sequence-pair, budget 30, single process)

| symbol | 79eed92 | 2cf583b (T1) | ef3da8f (T2) | **ef2207a (HEAD)** |
|---|---|---|---|---|
| `_variant_direct_eligibility` cum | 2.589 s | 2.538 s | 2.506 s | **2.522 s** |
| `_selected_direct_targets` ncalls | 481 | 553 | 1609 | **1513** |
| `_selected_direct_targets` per call | 5.37 ms | 4.58 ms | 1.55 ms | **1.66 ms** |
| `_direct_alignment_targets` ncalls / cum | 1051 / **0.758 s** | 1123 / **0.209 s** | 2179 / 0.186 s | **2083 / 0.190 s** |
| `_direct_net_candidates` ncalls / cum | 1053 / 4.665 s | 1125 / 4.773 s | 2181 / **2.487 s** | **2085 / 2.526 s** |
| `_direct_net_candidates` per call | 4.43 ms | 4.24 ms | 1.14 ms | **1.21 ms** |
| `_adapt` (`freeform.py:2013`) ncalls / cum | 1059 / 1.481 s | 1131 / 1.529 s | 13 / **0.015 s** | **13 / 0.016 s** |
| `DirectInsertTarget.__post_init__` (`sequence_pair.py:216`) ncalls / cum | 33802 / 0.628 s | 7882 / 0.153 s | 8139 / 0.123 s | **8139 / 0.127 s** |
| run total_tt | 24.456 s | 24.005 s | 22.333 s | **22.901 s** |

### mall (all-products, sequence-pair, budget 60, single process)

| symbol | 2cf583b | ef3da8f | **ef2207a (HEAD)** |
|---|---|---|---|
| `_variant_direct_eligibility` cum | 5.171 s | 5.105 s | **5.112 s** |
| `_selected_direct_targets` ncalls / per call | 417 / 12.39 ms | 561 / 9.09 ms | **561 / 9.10 ms** |
| `_direct_alignment_targets` ncalls / cum | 697 / 0.017 s | 1145 / 0.029 s | **1145 / 0.029 s** |
| `_direct_net_candidates` ncalls / cum | 699 / **2.583 s** | 1147 / **1.705 s** | **1147 / 1.735 s** |
| `_direct_net_candidates` per call | 3.70 ms | 1.49 ms | **1.51 ms** |
| `_adapt` ncalls / cum | 704 / 1.818 s | 11 / **0.026 s** | **11 / 0.027 s** |
| `DirectInsertTarget.__post_init__` ncalls / cum | 373 / 0.009 s | 712 / 0.014 s | **712 / 0.015 s** |
| passes / rounds / A* expansions | 1 / 1 / 4.44 M | 2 / 2 / **8.63 M** | 2 / 2 / **8.63 M** |

Reading:

* **`_direct_alignment_targets` -72 %** (0.758 -> 0.209 s on qc180), Task 1's memo,
  78.5 % hit rate.
* **`_direct_net_candidates` per call -68 % / -60 %** (4.43 -> 1.21 ms on qc180,
  3.70 -> 1.51 ms on the mall), Task 2's memo, 96-98 % pair hit rate; `_adapt`
  collapses from ~1100 calls to 13 because the adapted spec is pinned in the memo.
* **`DirectInsertTarget.__post_init__` fell 33802 -> 8139 calls (-76 %) with no
  code change to it** — Task 1's memo stopped re-constructing the targets. Its
  remaining 0.127 s is 0.55 % of a qc180 run, which is why the plan's Task 2 was
  redirected.
* **`_variant_direct_eligibility` cumtime is flat** (2.589 -> 2.522 s; 5.171 ->
  5.112 s) **by construction**: the pre-pass is deadline-polled, so it spends its
  slice and the win shows up as work done inside it, not as a shorter slice. On
  qc180 it completes **3.1x** the `_selected_direct_targets` calls (481 -> 1513)
  in the same 2.5 s. On the mall the whole run converts the freed time into a
  **second pass** (1 -> 2 passes, 4.44 M -> 8.63 M A* expansions) inside the same
  60 s budget.
* HEAD (`ef2207a`) reproduces `ef3da8f` exactly on both cells — identical A*
  expansion counts (2 673 912 and 8 632 979) and identical call counts — which is
  what a test-only commit should do.
* The spec's premise that this pre-pass is 55-67 % of the sequence-pair search
  **no longer held at the merge base**: at `79eed92` it was 2.59 s of a 24.5 s
  qc180 run (~10 %), the first batch having already taken the rest.

## 5. Islands re-profile (4 islands, same grid as `profile-before.jsonl`)

`profile-before.jsonl` (from the baseline tree at 79eed92) vs `profile-after.jsonl`
(this worktree at ef2207a); pstats/JSON beside as `before-<label>.*` /
`after-<label>.*`; load in `profile-before-load.txt` / `profile-after-load.txt`.
`expansions`, `passes` and `rounds` are 0 in every islands row on both sides —
the islands are child processes and the coordinator does not aggregate them, so
those three fields carry no signal here and are read from the single-process runs
above instead.

| label | verdict | area | wall s | decoded candidates | moves | detailed routes | direct inserts | islands completed / refused | compact seed |
|---|---|---|---|---|---|---|---|---|---|
| qc180 before | OK | 11842 | 27.24 | 7 | 16000 | 3 | 0 | 4 / 2 | cancelled |
| qc180 **after** | OK | **11842** | 31.77 | 8 | 16000 | 4 | 0 | 4 / 2 | cancelled |
| um120 before | OK | 37590 | 28.75 | 0 | 4000 | 2 | 0 | 4 / 0 | feasible |
| um120 **after** | OK | **37590** | 27.46 | 0 | 4000 | 2 | 0 | 4 / 0 | feasible |
| gm200 before | OK | 21156 | 27.67 | 5 | 12000 | 3 | 0 | 4 / 2 | cancelled |
| gm200 **after** | OK | **23370** | 30.09 | 6 | 12000 | 3 | 0 | 4 / **0** | cancelled |
| mall before | REFUSED (all 4 islands, deadline) | — | 49.07 | — | — | — | — | — | — |
| mall **after** | REFUSED (all 4 islands, deadline) | — | 50.31 | — | — | — | — | — | — |
| zurl2 before | REFUSED (all 4 islands, deadline) | — | 55.20 | — | — | — | — | — | — |
| zurl2 **after** | REFUSED (all 4 islands, deadline) | — | 55.01 | — | — | — | — | — | — |

* qc180 and um120 land the **same area** before and after; qc180 explores one
  more decoded candidate and one more detailed route in the same move budget.
* gm200's area moved +10.5 % (21156 -> 23370) in a **single** run. Four islands
  are not bit-reproducible across runs — the winner changes — and this run's
  islands all completed (refused 2 -> 0), so a different island won. Per the
  brief's rule, a single-cell area difference on the islands arm is noise; the
  corpus statistic in §3, which is 105 sequence-pair cell-pairs, is the area
  evidence and it shows -0.15 %.
* `direct_inserts` is **0** on every islands cell, before and after (with
  `direct_candidates` 32 on qc180). Neither tree realizes a direct insert on
  these cells, so this grid gives no end-to-end evidence about the memoized
  values themselves; that evidence is the corpus rounds in §1-§3 plus the
  implementers' transparency and drift-guard tests.
* mall and zurl2 refuse at 60 s with 4 islands on both trees, unchanged. The
  mall's single-process win (a second pass) does not survive being split four
  ways at this budget.

## 6. Spec §2 verdict

**The second batch (L3, the direct-insert eligibility memos) PASSES its gate: three
paired 30 s rounds against master `79eed92` show zero regressions, INVALID 0,
CRASH 0, max `wall_overshoot_s` 0.000 s, sequence-pair area -0.15 % and freeform
-0.27 % — both inside the baseline tree's own +0.65 % round-to-round noise — with
the pre-pass's memoized functions 60-72 % cheaper per call and the mall completing
a second pass inside the same 60 s budget, while the one disagreeing cell
(`sequence-pair universe-matrix/all-products`) is a load flake that six dedicated
re-runs clear on both trees.**

### What this batch did not deliver

The design predicted "the largest single gain on the list (55-67 % of the
sequence-pair search on two cells)". It is **not** there: that share was measured
at `a232f0a`, and by the merge base `79eed92` the first batch had already taken
it, leaving the pre-pass at ~10 % of a qc180 run. The memos took 60-72 % of that
10 %, which is a real but small end-to-end effect and is why the corpus area is
flat. The next lever on these cells, named by the Task 2 measurement, is
`_selected_strips` (`sequence_solver.py:3730`), 9.56 s cumulative on the mall.

### Files

* `baseline-79eed92-round{1,2,3}.{jsonl,txt}`, `-load.txt`, `baseline-79eed92-commit.txt`
* `candidate-round{1,2,3}.{jsonl,txt}`, `-load.txt`
* `compare-round{1,2,3}.txt`, `judge-round{1,2,3}.txt`, `judge.py`
* `flake-{baseline,candidate}-um-round{1,2,3}.{jsonl,txt}`, `flake-load.txt`
* `profile-before.jsonl`, `profile-after.jsonl`, `profile-{before,after}-load.txt`,
  `{before,after}-{qc180,um120,gm200,mall,zurl2}.{json,log,pstats,cumulative.txt,tottime.txt}`
* `head-solo-{qc180,mall}.{json,log,pstats,cumulative.txt,tottime.txt}`, `head-solo-load.txt`
