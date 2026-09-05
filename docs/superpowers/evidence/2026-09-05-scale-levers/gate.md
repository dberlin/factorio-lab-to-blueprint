# Scale-levers corpus gate and re-profile (2026-09-05)

Branch head: `19f95a6` (`Merge master d81c4d9 into scale-levers`).
Baselines: master `d81c4d9` (`baseline-d81c4d9-commit.txt`, the master this
branch contains) and master `789625f` (`baseline-commit.txt`, the older
baseline the earlier rounds were taken on). The **verdict is judged on the
`d81c4d9` comparison**; the `789625f` table is kept for continuity with the
mall-profile README.

All six rounds are `scripts/audit.py --budget 30 --json` over the full 72-cell
matrix, interleaved candidate/baseline so the box load is comparable, never
two audits at once. Candidate rounds ran from this worktree; `d81c4d9` rounds
ran from the detached worktree `/tmp/scale-levers-baseline-d81c4d9`
(`build.log` there ends `build-exit=0`, `route_backend=cython` in every row).
Load before each round is in `*-load.txt` (below); the box is never idle and
its load is disk I/O, so `vmstat` shows ~98 % idle CPU throughout.

`audit.py` prints `NOT CLEAN` whenever any cell refuses, and
`audit_compare.py` prints `FAIL` for any non-clean candidate row regardless of
what the baseline did. Master itself is not 72/72 here, so neither banner is
the gate. What is read below is the status counts and the *set* of cells whose
status differs between the paired files (`judge.py`, output in
`judge-round{1,2,3}-{789625f,d81c4d9}.txt`).

## Commands

```
E=docs/superpowers/evidence/2026-09-05-scale-levers
(uptime; vmstat 1 3 | tail -1) > $E/candidate-round$r-load.txt
uv run python scripts/audit.py --budget 30 --json $E/candidate-round$r.jsonl > $E/candidate-round$r.txt 2>&1
uv run python scripts/audit_compare.py $E/baseline-round$r.jsonl $E/candidate-round$r.jsonl > $E/compare-round$r.txt 2>&1
uv run python $E/judge.py <baseline>.jsonl $E/candidate-round$r.jsonl
```

and, from `/tmp/scale-levers-baseline-d81c4d9`, the same `audit.py` line
writing `baseline-d81c4d9-round$r.jsonl` into this evidence directory.

## Round order and load

| # | run | started | load avg (1/5/15) | wall |
|---|---|---|---|---|
| 1 | candidate round 1 | 14:47:41 | 3.39 / 4.57 / 5.19 | 132 s |
| 2 | baseline d81c4d9 round 1 | 14:50:04 | 11.79 / 8.37 / 6.55 | 136 s |
| 3 | candidate round 2 | 14:52:37 | 13.36 / 10.99 / 7.82 | ~140 s |
| 4 | baseline d81c4d9 round 2 | 14:55:04 | 15.55 / 14.01 / 9.47 | ~140 s |
| 5 | candidate round 3 | 14:57:30 | 14.19 / 14.76 / 10.43 | ~135 s |
| 6 | baseline d81c4d9 round 3 | 14:59:52 | 14.56 / 15.26 / 11.23 | ~140 s |

## Three rounds against master `d81c4d9` (the verdict table)

| round | baseline CLEAN / REFUSED / INVALID / CRASH | candidate CLEAN / REFUSED / INVALID / CRASH | cells differing | area ratio | p95 wall base / cand |
|---|---|---|---|---|---|
| 1 | 71 / 1 / 0 / 0 | 71 / 1 / 0 / 0 | 0 | 0.9993 | 29.14 s / 29.08 s |
| 2 | 71 / 1 / 0 / 0 | 71 / 1 / 0 / 0 | 0 | 1.0012 | 29.20 s / 29.48 s |
| 3 | 71 / 1 / 0 / 0 | 71 / 1 / 0 / 0 | 0 | 0.9995 | 29.14 s / 29.43 s |

The one refusal is the same cell on both trees in all three rounds:
`sequence-pair universe-matrix / all-products` -- "deadline exhausted before
finding an exact layout". It refuses in the `d81c4d9` baseline in all three
rounds too, so it is not this branch's.

Zero cells differ in status in any round, so there is nothing to attribute and
**no deadline flake needed a 3x re-run** (the brief's `--only <url_id>
--strategy <arm>` procedure was not exercised; there was no partial
disagreement to resolve).

Area: the geometric-mean ratio over the 71 cells clean in both is
0.9993 / 1.0012 / 0.9995, well inside `audit_compare`'s default noise band
(`--noise-area 0.013`, i.e. 1.013). The handful of individual cells that moved
at all are small-cell packing noise: `freeform electromagnetic-matrix /
no-proliferator` 551 -> 609 (round 2), `freeform super-magnetic-ring /
no-proliferator` 2220 -> 2109 / 2183, `freeform magnetic-coil /
output-products` 294 -> 285, `freeform quantum-chip / all-products`
3840 -> 3825. Every large cell is byte-identical in area.

Total build wall over the 72 cells fell in all three rounds: 972.1 -> 946.0,
981.7 -> 951.6, 989.8 -> 939.7 s. That is the levers buying attempts inside
the same per-cell 30 s budget, not cells finishing early -- p95 is pinned at
~29 s on both trees.

## Three rounds against master `789625f` (continuity only)

| round | baseline CLEAN / REFUSED | candidate CLEAN / REFUSED | CLEAN -> not CLEAN | not CLEAN -> CLEAN | area ratio |
|---|---|---|---|---|---|
| 1 | 70 / 2 | 71 / 1 | 1 | 2 | 0.9968 |
| 2 | 69 / 3 | 71 / 1 | 0 | 2 | 0.9986 |
| 3 | 70 / 2 | 71 / 1 | 1 | 2 | 0.9988 |

The differing cells, and their attribution:

- `freeform universe-matrix / all-products` and `freeform universe-matrix /
  output-products`: REFUSED on `789625f` in all three rounds, CLEAN on the
  candidate in all three rounds -- **and CLEAN on the `d81c4d9` baseline in all
  three rounds**. Master `d81c4d9` flipped the freeform routing-order default
  `prioritize_source_families` to `True`; both baselines and the candidate
  move in the same direction on the same cells, so this is master's change,
  not this branch's.
- `sequence-pair universe-matrix / all-products`: CLEAN on `789625f` in rounds
  1 and 3, REFUSED in round 2; REFUSED on `d81c4d9` in all three rounds and on
  the candidate in all three rounds. Same attribution, opposite sign: the
  routing-order flip costs this cell on both `d81c4d9` and the branch. It is
  master's, not this branch's, and it is the only cell keeping the corpus off
  72/72.
- `freeform universe-matrix / no-proliferator` 31898 -> 26752 (a 16 % area
  *win*) appears only against `789625f`; against `d81c4d9` the areas are
  identical, so that too is master's.

## Verdict against spec §4

**Corpus: PASS.** INVALID 0 and CRASH 0 in every candidate round; no cell is
CLEAN in the `d81c4d9` baseline in all three rounds and not CLEAN in the
candidate in all three rounds (in fact no cell differs at all, in any round);
the geometric-mean area ratio is 0.9993-1.0012, inside the default noise band.

**Crash criterion: PASS.** `universe-matrix*90` and `*120` -- the two
instances that raised `ValueError` out of
`strip_variants._logical_strip_plans` on `a1afec5` -- now lay out cleanly
under *both* strategies at the 30 s budget (`*90`: 331 machines, freeform area
54168, sequence-pair 26319; `*120`: 439 machines, freeform 80442,
sequence-pair 43676; verdict `OK` in all four rows of `profile-after.jsonl`).
Neither crashes and neither refuses.

**Phase thresholds: met per attempt, not as a per-run total -- see below.**
§4 asks for "`commit_paths` under 1.5 s and `power_plan` under 2.5 s per
freeform run". Per *call* (i.e. per candidate attempt) both thresholds are met
comfortably on all three cells. Per *run* (the whole 30 s harness invocation)
neither can be met, and that is §1's own premise rather than a miss: every
large cell runs to the budget, so a cheaper phase buys more attempts inside
the same 30 s instead of a shorter run. `commit_paths` on `um60` freeform went
from 5.48 s over 8 calls to 3.22 s over 10; the per-call cost more than halved
while the run kept spending its budget. This is recorded as a deviation, not
papered over: read strictly per run, that clause of §4 is not satisfied and
cannot be by any lever that leaves the budget loop intact.

| cell (freeform) | commit_paths per call before -> after | power_plan per call before -> after |
|---|---|---|
| universe-matrix*60 | 0.69 / 0.64 s -> **0.32 s** | 0.89 / 0.74 s -> **0.72 s** |
| quantum-chip*180 | 0.18 s -> **0.11 s** | 0.42 s -> **0.40 s** |
| gravity-matrix*200 | 0.60 / 0.65 s -> **0.27 s** | 1.11 / 1.05 s -> **0.87 s** |

`commit_paths` is 40-57 % cheaper per call; `power_plan` is 5-21 % cheaper per
call, the weakest of the levers, and `_power_plan`'s own fill and keep-out
stamping stay on the follow-up list (design §5).

## Before / after phase table

Real seconds per harness run, `phase (n calls)`. **Before** is
`docs/superpowers/evidence/2026-09-05-scale-profile/tallies.jsonl` at master
`a1afec5` -- eight runs in parallel on a box at load 5.9; where two
non-cProfile runs exist both are shown. **After** is `profile-after.jsonl` at
`19f95a6` -- **two runs in parallel at most**, on a box at load 21.0
(`profile-after-load.txt`). The two profiles therefore differ in how much they
contend with each other and with the rest of the box, and per-run totals are
not directly comparable; per-call figures are the honest comparison.

`a1afec5` predates the whole effort. Master `d81c4d9` already contains levers
1 (`_commit_paths` SCC pass, `df468bc`), 5 (altitude-profile cache, `f57e31d`)
and the §2 output-lane fix (`86691c5`); the branch adds levers 3, 4, 6 and the
mall levers 7-9. The before/after delta below spans both halves.

### universe-matrix*60 (224 machines)

| run | wall | route_all | commit_paths | power_plan | finalize | validate |
|---|---|---|---|---|---|---|
| freeform before | 23.7 / 27.3 | 12.65 (4) / 13.67 (5) | 5.48 (8) / 6.41 (10) | 3.54 (4) / 3.71 (5) | 1.68 (2) / 2.88 (3) | 1.59 (2) / 2.40 (3) |
| freeform after | 24.7 | 6.64 (5) | 3.22 (10) | 3.60 (5) | 3.49 (5) | 3.72 (5) |
| sequence-pair before | 24.5 / 25.3 | 5.63 (3) / 6.49 (4) | 3.31 (6) / 3.82 (8) | 2.94 (5) / 3.27 (6) | 0.91 (1) / 0.88 (1) | 0.64 (1) / 0.63 (1) |
| sequence-pair after | 25.3 | 4.34 (4) | 2.08 (8) | 3.21 (6) | 0.67 (1) | 0.68 (1) |

### quantum-chip*180 (252 machines)

| run | wall | route_all | commit_paths | power_plan | finalize | validate |
|---|---|---|---|---|---|---|
| freeform before | 26.0 | 9.97 (6) | 3.57 (20) | 2.53 (6) | 8.87 (5) | 1.50 (4) |
| freeform after | 23.5 | 9.37 (7) | 3.10 (29) | 2.80 (7) | 3.98 (6) | 2.45 (6) |
| sequence-pair before | 23.2 | 1.10 (1) | 0.53 (2) | 1.16 (3) | 0.56 (1) | 0.50 (1) |
| sequence-pair after | 24.1 | 1.68 (2) | 0.76 (5) | 1.68 (4) | 0.35 (1) | 0.49 (1) |

`finalize` is the clearest single win here: 1.77 s per call before, 0.66 s
after, from the Cython oriented-box overlap kernel (`ceb5eda`, lever 4). This
was the 8.9 s outlier the before-profile flagged.

### gravity-matrix*200 (349 machines)

| run | wall | route_all | commit_paths | power_plan | finalize | validate |
|---|---|---|---|---|---|---|
| freeform before | 20.9 / 27.2 | 10.08 (3) / 12.57 (4) | 4.76 (8) / 6.47 (10) | 3.32 (3) / 4.19 (4) | 2.07 (3) / 3.47 (4) | 2.58 (3) / 3.48 (4) |
| freeform after | 27.3 | 8.28 (5) | 2.93 (11) | 4.36 (5) | 3.65 (5) | 4.12 (5) |
| sequence-pair before | 22.5 / 22.3 | 1.31 (1) / 1.29 (1) | 0.92 (2) / 0.91 (2) | 2.30 (4) / 2.23 (4) | 1.19 (1) / 1.21 (1) | 0.68 (1) / 0.67 (1) |
| sequence-pair after | 26.0 | 1.78 (2) | 1.35 (6) | 2.74 (5) | 1.68 (2) | 1.41 (2) |

### universe-matrix*90 (331 machines) and *120 (439 machines)

Before: **CRASH** under both strategies --
`ValueError: recipe 'mass-energy-storage': hydrogen: destinations
['casimir-crystal#1', 'deuterium#6'] have to share one output lane carrying 44
items/s, over the 30/s the belt sustains` escaping
`strip_variants._logical_strip_plans`. There is no before row to compare.

| run | verdict | area | wall | route_all | commit_paths | power_plan | finalize | validate |
|---|---|---|---|---|---|---|---|---|
| *90 freeform after | OK | 54168 | 23.7 | 7.88 (4) | 3.62 (8) | 4.17 (4) | 1.68 (3) | 3.20 (3) |
| *90 sequence-pair after | OK | 26319 | 27.0 | 5.68 (4) | 2.26 (8) | 5.88 (6) | 0.94 (1) | 0.89 (1) |
| *120 freeform after | OK | 80442 | 25.9 | 7.24 (3) | 3.50 (6) | 4.95 (3) | 2.58 (3) | 4.62 (3) |
| *120 sequence-pair after | OK | 43676 | 24.0 | 4.33 (3) | 2.24 (6) | 5.61 (6) | 0.81 (1) | 1.26 (1) |

The corpus hard-codes `*60`, so none of this is exercised by the audit; these
four rows are the only evidence that the §2 fix holds at scale.

## Mall URL, `--policy all-products`, budget 100

Before is `mall-profile/tallies.jsonl` (branch with Tasks 1-6, master
`789625f`, 8 tally runs in parallel); after is the two rows at the end of
`profile-after.jsonl` (two runs in parallel). 449 machines, 46 strips, 33
groups.

| run | wall | verdict | prepare | reserve_port_access | make_grid | route_all |
|---|---|---|---|---|---|---|
| freeform before | 100.0 | REFUSED, deadline: 6 packs routed, best left 1 net unrouted | 90.29 (6) | 79.97 (12) | 4.74 (1087) | 7.22 (2) |
| freeform after | 30.9 | REFUSED, **packer defect named**: no packing of 46 strips could be wired at any height | **16.74 (6)** | **6.96 (12)** | **0.22 (47)** | 11.08 (2) |
| sequence-pair before | 70.9 | REFUSED, deadline exhausted | 29.92 (6) | 10.48 (12) | 4.76 (1112) | 10.52 (3) |
| sequence-pair after | 83.9 | REFUSED, deadline exhausted | 40.73 (10) | 9.59 (20) | 0.55 (111) | 18.87 (5) |

Freeform: `prepare` 90.3 s -> 16.7 s over the same 6 calls (15.05 -> 2.79 s per
call) and `reserve_port_access` 80.0 s -> 7.0 s over the same 12 calls
(6.66 -> 0.58 s per call). That is lever 7 (capping the access-corridor
matcher's solves and keeping the rank-optimal assignment on a timeout,
`ab670bf`) plus lever 8 (one shared grid per reservation, `3536ba3` -- visible
as `make_grid` 1087 builds / 4.74 s -> 47 builds / 0.22 s). The run no longer
spends its budget in the matcher: it reaches routing, exhausts the sweep in
30.9 s of the 100 s allowed, and returns a *different and better* refusal that
names a packer defect (packs its own router cannot wire) instead of a
preparation deadline.

Sequence-pair: `prepare` per call 4.99 -> 4.07 s and `reserve_port_access` per
call 0.87 -> 0.48 s; the run now fits 10 prepares and 5 route passes into the
budget where it previously managed 6 and 3, so the per-run totals rise while
the per-call costs fall. This is lever 9 (`e02fdff`, `_selected_strips` and
clearance-key memoization) plus the shared grid. It still refuses on the
deadline; the follow-ups in design §5 (`_projected_coater_junction_bans_by_frame`,
now 11.7 s over 10 calls, and `_place_coaters`) are the next cost there.

## Files

`candidate-round{1,2,3}.{jsonl,txt}`, `candidate-round{1,2,3}-load.txt`,
`baseline-d81c4d9-round{1,2,3}.{jsonl,txt}`,
`baseline-d81c4d9-round{1,2,3}-load.txt`, `baseline-d81c4d9-commit.txt`,
`compare-round{1,2,3}.txt` (vs `789625f`),
`compare-d81c4d9-round{1,2,3}.txt`,
`judge-round{1,2,3}-{789625f,d81c4d9}.txt`, `judge.py`,
`profile-after.jsonl`, `profile-after-load.txt`.
