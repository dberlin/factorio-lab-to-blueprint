# Speedups round 2, 2026-09-05: where the next major gains are

Follows `2026-09-05-scale-profile/` (the first profile) and
`2026-09-05-scale-levers/` (the levers it produced, now on master).  Master
here is `a232f0a`; the worktree is `.claude/worktrees/speedups-2` on branch
`speedups-2`.

The single sentence this round adds to the last one:

> **One build uses exactly one core for its whole budget, and a quarter of the
> sequence-pair budget is spent in a single-threaded CP-SAT solve that returns
> nothing on the two largest cells.**

## Method and load

* Harness: `../2026-09-05-scale-profile/prof_harness.py` (unchanged), which
  installs the real-seconds phase shims from `scripts/route_profile.py` and
  optionally `cProfile`.
* Instruments added here (all in this directory, all throwaway):
  * `cpu_trace.py` — samples the child's whole `/proc` tree once a second for
    CPU-seconds, threads and processes.  Answers "how many cores?".
  * `budget_ladder.py` — the same cell at 4/8/12/20/30 s, recording verdict,
    wall and area.  Answers "what does the budget buy?".
  * `startup_cost.py` — splits the pre-search span.
  * `proto_compact_share.py` — prototype 1 (compact-seed wall share).
  * `proto_islands.py` — prototype 2 (sequence-pair process islands).
* Two runs at a time at most, per the box rule.  The box is 128 cores and is
  never idle; its load is disk I/O wait.

```
$ uptime; vmstat 1 3 | tail -1; nproc
 17:03:59 up 20 days, 22:50, 12 users,  load average: 6.13, 6.62, 5.73
 2  0      0 1017214324  0 19453920  0    0     0     0 14948 29519 2 0 97  0  0  0
128
```

Per-batch load lines are at the head of every `== cell/strategy` block in
`plain-log.txt`, `cprof-log.txt` and `cpu-log.txt` (they ran between
17:04 and 17:5x at load 5.9-7.4).

Cells: `universe-matrix*60` (224 machines), `quantum-chip*180` (252),
`gravity-matrix*200` (349), `universe-matrix*120` (439) at budget 30 with
`--policy no-proliferator`; and the five-objective mall URL
(`../2026-09-05-scale-levers/mall-profile/url.txt`, 449 machines) with
`--policy all-products` at budget 100.

---

## 1. Where a 30 s budget goes, structurally

Real seconds from the phase shims (`plain-*.json`, one run per cell/strategy).
`prepare` CONTAINS `power_plan`, `place_coaters`, `coater_frame_bans`,
`junction_ban` and `static_risks`.  "candidates" is the number of `prepare`
calls, which is the number of packs/placements the run actually evaluated.

| cell / strategy | wall | mach | area | candidates | s/cand | prepare | route_all | power_plan | validate | finalize | commit | astar | budget left unused |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| um60-freeform | 22.7s | 224 | 26752 | 5 | 4.5 | 6.3/5 | 6.2/5 | 3.3/5 | 3.5/5 | 3.2/5 | 3.1/10 | 2.5/1044 | 7.3s (24%) |
| um60-sequence-pair | 24.5s | 224 | 17654 | 8 | 3.1 | 7.9/8 | 4.2/4 | 3.9/7 | 0.6/1 | 0.6/1 | 2.0/8 | 2.6/1343 | 5.5s (18%) |
| qc180-freeform | 28.2s | 252 | 15680 | 8 | 3.5 | 5.8/8 | 11.1/8 | 3.3/8 | 2.2/6 | 6.3/7 | 3.6/33 | 6.2/1400 | 1.8s (6%) |
| qc180-sequence-pair | 23.8s | 252 | 21384 | 8 | 3.0 | 4.4/8 | 2.0/2 | 1.5/4 | 0.5/1 | 0.5/1 | 1.0/5 | 1.4/1075 | 6.2s (21%) |
| gm200-freeform | 22.0s | 349 | 48640 | 4 | 5.5 | 6.8/4 | 7.3/4 | 3.7/4 | 3.5/4 | 2.5/4 | 2.4/9 | 4.5/814 | 8.0s (27%) |
| gm200-sequence-pair | 26.2s | 349 | 22140 | 5 | 5.2 | 5.5/5 | 1.9/2 | 2.6/5 | 1.5/2 | 1.7/2 | 1.4/6 | 1.3/731 | 3.8s (13%) |
| um120-freeform | 25.2s | 439 | 80442 | 3 | 8.4 | 8.3/3 | 7.0/3 | 4.6/3 | 4.7/3 | 2.6/3 | 3.5/6 | 4.0/718 | 4.8s (16%) |
| um120-sequence-pair | 19.0s | 439 | REFUSED | 5 | 3.8 | 9.9/5 | 2.9/2 | 5.0/5 | 0.0/0 | 0.0/0 | 1.4/4 | 2.8/904 | 11.0s (37%) |
| mall-freeform | 31.7s | 449 | REFUSED | 6 | 5.3 | 16.9/6 | 11.5/2 | 1.9/2 | 0.0/0 | 0.0/0 | 5.2/4 | 6.2/1475 | 68.3s (68%) |
| mall-sequence-pair | 82.1s | 449 | REFUSED | 10 | 8.2 | 39.7/10 | 18.5/5 | 9.0/10 | 0.0/0 | 0.0/0 | 11.2/11 | 9.3/2769 | 17.9s (18%) |

Three structural facts fall out of this table.

1. **A 30 s budget buys 3 to 10 candidate evaluations**, at 3-8 s each.  Making
   a candidate 30 % cheaper buys one to three more evaluations; it does not
   change the shape of the run.
2. **6 % to 37 % of every budget is never spent.**  `_room_for_another`
   (`freeform.py:21268-21289`) refuses to start a candidate unless the clock
   left exceeds `dearest_candidate_s` — the *maximum* candidate this sweep has
   completed, not a median or an estimate of the next one.  On um120-freeform
   the dearest candidate is 8.4 s, so the sweep stops with 4.8 s in hand; on
   gm200-freeform it stops with 8.0 s.  It is a deliberately conservative
   measurement (`_room_for_another`'s docstring says so), and the conservatism
   costs a quarter of the budget on the largest cells.
3. **The "~7 s CP-SAT lock wait" the first profile saw on sequence-pair is
   `compact_seed`.**  See §4: it is `_COMPACT_SEED_WALL_SHARE = Fraction(1, 3)`
   (`sequence_solver.py:191`) handing one third of the whole budget to one
   CP-SAT solve pinned to `num_search_workers = 1`
   (`compact_seed.py:453-457`, `652-657`).

---

## 2. Parallelism: one build = one core

`cpu_trace.py` samples the whole process tree once a second.  Every cell, both
strategies (`cpu-*.json`):

| cell / strategy | wall | mean cores while running | peak cores | peak threads | peak procs |
|---|---|---|---|---|---|
| um60-freeform | 27.1 | 1.30 | 8.8 | 67 | 2 |
| um60-sequence-pair | 27.1 | 1.33 | 9.4 | 68 | 2 |
| qc180-freeform | 25.1 | 1.35 | 9.3 | 67 | 2 |
| qc180-sequence-pair | 27.1 | 1.32 | 9.2 | 67 | 2 |
| gm200-freeform | 25.1 | 1.35 | 9.4 | 67 | 2 |
| gm200-sequence-pair | 30.1 | 1.28 | 9.1 | 67 | 2 |
| um120-freeform | 28.1 | 1.31 | 9.2 | 67 | 2 |
| um120-sequence-pair | 27.1 | 1.32 | 9.3 | 68 | 2 |
| mall-freeform | 34.1 | 1.25 | 9.2 | 67 | 2 |
| mall-sequence-pair | 75.3 | 1.11 | 8.7 | 67 | 2 |

The per-second trace makes it unambiguous — this is um60-freeform, cores per
second, from `cpu-um60-freeform.json`:

```
8.83, 1.00, 1.00, 1.01, 1.00, 1.00, 1.00, 1.01, 1.00, 1.01, 1.01, 1.00,
1.00, 1.00, 1.01, 1.00, 1.00, 1.00, 1.00, 1.01, 1.01, 1.00, 1.00, 1.01,
1.00, 1.00
```

The 8.8 in the first second is `uv`'s own start-up.  **Every subsequent second
of every run is 1.00 cores.**  The 67 threads are ortools' pool sitting idle.
The box has 128.

Where the cores are meant to come from, and why none arrive:

* `pipeline.DEFAULT_WORKER_BUDGET_CAP = 16` (`pipeline.py:80`), so a build asks
  for 16 CP-SAT search workers.  Those workers reach exactly one solve:
  freeform's `_pack` (`freeform.py:4730-4734`, `num_search_workers = workers`).
  `_pack`'s measured cost is `pack_cp_wall_time_s` = **0.28 s (gm200), 0.28 s
  (um120), 1.44 s (um60), 1.64 s (qc180)** out of 22-28 s.  The worker budget
  is spent on 1-6 % of the run.
* Every other CP-SAT solve in the tree is pinned to one worker on purpose:
  `compact_seed.py:454` and `:653`, `freeform.py:11484` (the access-corridor
  tie-break).  `strategy_race.py:89-92` says so explicitly.
* `strategy_race` exists but `pipeline.build(race=False)` is the default
  (`pipeline.py:529-532`, "OFF by default until the flip commit").
* `sequence_islands.run_sequence_islands` exists and runs N complete solves in
  spawned processes — but `pipeline.build(sequence_islands=1)`
  (`pipeline.py:503`) and `cli.py:349-352` only raises it above 1 for an
  *explicit* `--strategy sequence-pair`, never for the default `best`.
  `scripts/audit.py:126` constructs `SequencePairLayout(...)` with no islands
  at all, so the corpus gate has never measured them.

What is serial and independent, in order of how easy it is to fan out:

| serial loop | where | independence |
|---|---|---|
| sequence-pair whole solves (seeds) | `sequence_islands.py` (already written, off) | fully independent; spawn + pickle a `BuildSpec` |
| freeform candidate heights | `freeform._sweep`, `freeform.py:19477+` | NOT independent: `exact_no_good_state`, `routed_assignments`, `minimum_pitch_x` and the ALNS `session` all accumulate across candidates. A pool would need the `strategy_race` message channel (which already exists) to exchange them. |
| the two strategies | `strategy_race` (written, off) | independent, shares incumbents/no-goods |
| compact-seed attempts | `compact_seed.solve_compact_seed`, one attempt per run | independent across `compact_seed_attempt`; each stays 1-worker, so each stays reproducible |

---

## 3. Startup and fixed costs

`startup.json`, from `startup_cost.py`:

| span | seconds |
|---|---|
| `import flab2bp` (freeform + sequence_solver + rates) | 1.202 |
| `load_vendored()` dataset | 0.020 |
| `parse_url` | 0.0002 |
| `build_candidates` (the rate MILP) | 0.191 |
| layout object construction | 0.000 |
| **pre-search total** | **1.413** |
| whole process wall | 1.76 |

So the fixed cost is 1.4 s and **85 % of it is imports**.  Per-module:
`flab2bp.layout.freeform` 0.63 s, `sequence_solver` 0.78 s,
`sequence_islands` 0.85 s, `strategy_race` 0.86 s, `flab2bp.rates` 0.67 s.

`-X importtime` attributes it to third parties, not to us:
`ortools.sat.python.cp_model` 0.347 s (which itself pulls pandas 0.267 s and
numpy 0.093 s), `sympy` 0.267 s under `flab2bp.rates.solve` (which genuinely
uses `sympy.solvers.simplex` for the exact rational LP, `rates/solve.py:36-42`).
`flab2bp.layout.freeform` does **not** import sympy or `flab2bp.rates`; the
pandas it pulls comes from ortools.

This is not a lever for a serial build (1.4 s of a 30 s budget), but it *is*
the entry price of every parallel arm: `strategy_race` hands each child the
parent's absolute deadline (`strategy_race.py:62-68`), so ~0.9-1.3 s of import
in each spawned child is search that child loses inside the wall.

---

## 4. Budget semantics: what does the budget actually buy?

`ladder.jsonl` / `budget_ladder.py`, one run per cell at each budget.  Cells
show `area @ wall (percent of the budget actually used)`.

| cell / strategy | 4 s | 8 s | 12 s | 20 s | 30 s |
|---|---|---|---|---|---|
| um60/freeform | 40920 @5.8 (145%) | 40920 @5.0 (62%) | 40635 @9.4 (78%) | 31898 @18.4 (92%) | **26752** @22.9 (76%) |
| um60/sequence-pair | REFUSED | REFUSED | REFUSED | 17654 @18.0 (90%) | **17654** @24.8 (83%) |
| qc180/freeform | 24297 @2.8 (70%) | 21645 @5.9 (74%) | **15680** @10.6 (88%) | 15680 @18.8 (94%) | 15680 @27.7 (92%) |
| qc180/sequence-pair | REFUSED | 21384 @8.1 (102%) | 21384 @9.0 (75%) | *17724* @18.5 (92%) | 21384 @27.6 (92%) |
| gm200/freeform | 51684 @4.8 (119%) | 51684 @5.2 (65%) | 51684 @9.7 (81%) | 51684 @15.8 (79%) | **48640** @23.7 (79%) |
| gm200/sequence-pair | REFUSED | REFUSED | 26606 @13.5 (113%) | 22240 @20.0 (100%) | **22140** @26.8 (89%) |
| um120/freeform | REFUSED | **80496** @8.3 (104%) | 80496 @8.2 (68%) | 80496 @16.2 (81%) | 80442 @24.9 (83%) |
| um120/sequence-pair | REFUSED | REFUSED | REFUSED | REFUSED | **43676** @24.1 (80%) |

Read this three ways.

**(a) Freeform: the budget is genuinely productive on two cells and inert on
two.**  um60 improves 40920 -> 26752 (-35 %) between 8 s and 30 s, and
qc180 improves 24297 -> 15680 (-35 %) between 4 s and 12 s.  But qc180 is
*finished at 12 s* — the last 18 s of a 30 s budget change nothing — and
**um120 reaches 80496 at 8 s and 80442 at 30 s: 22 further seconds buy 0.07 %
of area.**  gm200 buys 5.9 % over 26 s.  So "stop at the first clean layout"
would cost 35 % area on um60 and 0.07 % on um120; the honest version of this
lever is a *stagnation* stop (stop when N consecutive candidates fail to beat
the incumbent), not a first-clean stop.

**(b) Sequence-pair has a floor, and it is high.**  It refuses below 12-30 s on
three of four cells and produces nothing at all at 4 s anywhere.  §5 shows the
floor is largely self-inflicted.

**(c) Nothing is monotone.**  qc180/sequence-pair returns 17724 at 20 s and
21384 at 30 s — a *worse* answer from a *larger* budget (the extra clock
changes which restart wins).  Any "adaptive budget" work must treat quality as
noisy across budgets, and any gate for it has to be paired over rounds.

Budget utilisation is 62-104 %, mean about 86 %; the shortfall is
`_room_for_another` refusing to start a candidate it cannot certainly finish.

---

## 5. Prototype 1 (MEASURED): sequence-pair's compact-seed share is 4x too big

`proto_compact_share.py` / `proto-compact.jsonl`.  It patches
`sequence_solver._COMPACT_SEED_WALL_SHARE` (default `Fraction(1, 3)`) and runs
the same cell at budget 30.  `1/1000` is "effectively no compact seed".

| cell | share | area | compact-seed wall | its status | det. seconds | anneal moves | decoded cands | detailed routes | A\* expansions |
|---|---|---|---|---|---|---|---|---|---|
| um60 | **1/3** | 17654 | 7.43 | feasible | 2.56 | 8000 | 3 | 4 | 2.81 M |
| um60 | 1/6 | 17654 | 5.00 | feasible | 2.07 | 16000 | 6 | 3 | 2.35 M |
| um60 | **1/12** | **17654** | 2.50 | feasible | 1.48 | 12000 | 4 | 4 | 3.06 M |
| um60 | 1/1000 | 20600 (worse) | 0.05 | cancelled | 0.0 | 20000 | 11 | 3 | 3.22 M |
| qc180 | **1/3** | 21384 | 10.01 | **cancelled** | **0.0** | 12000 | 6 | 4 | 1.77 M |
| qc180 | 1/6 | 21384 | 5.01 | cancelled | 0.0 | 20000 | 9 | 7 | 2.45 M |
| qc180 | **1/12** | **21384** | 2.52 | cancelled | 0.0 | 20000 | 12 | 7 | 3.35 M |
| qc180 | 1/1000 | **18445 (better)** | 0.05 | cancelled | 0.0 | 24000 | 12 | 8 | 4.19 M |
| gm200 | **1/3** | 22140 | 10.03 | **cancelled** | **0.0** | 12000 | 3 | 2 | 1.04 M |
| gm200 | 1/6 | 22140 | 5.04 | cancelled | 0.0 | 16000 | 6 | 1 | 1.43 M |
| gm200 | **1/12** | **22140** | 2.52 | cancelled | 0.0 | 16000 | 8 | 2 | 2.24 M |
| gm200 | 1/1000 | 22140 | 0.06 | cancelled | 0.0 | 16000 | 9 | 2 | 2.24 M |
| um120 | **1/3** | 43676 | 2.65 | unknown | 2.56 | 12000 | 4 | 3 | 2.54 M |
| um120 | 1/6 | 43676 | 2.71 | unknown | 2.56 | 12000 | 4 | 3 | 2.54 M |
| um120 | **1/12** | **43676** | 2.50 | cancelled | 2.50 | 12000 | 4 | 3 | 2.54 M |
| um120 | 1/1000 | **REFUSED** | 0.00 | — | — | — | — | — | — |

**Result: 1/12 gives byte-identical areas to 1/3 on all four cells, and hands
7.5 s of a 30 s budget (25 %) back to the search.**  Measured effect of those
seconds: qc180 goes 12000 -> 20000 anneal moves, 6 -> 12 decoded candidates,
4 -> 7 detailed routes, 1.77 M -> 3.35 M A\* expansions.  gm200 goes 3 -> 8
decoded candidates and 1.04 M -> 2.24 M expansions.

Why it is safe to cut and not safe to remove:

* On **qc180 and gm200 the seed produces nothing at any share**:
  `compact_seed_status = cancelled`, `deterministic_time = 0.0`,
  `closures = 0`.  Those cells' models never reach even the first deterministic
  checkpoint inside 10 s of wall, so the 10 s is pure loss.
* On **um60 and um120 the seed does matter** — remove it and um60 loses 17 %
  area and um120 refuses outright — but 2.5 s is enough: um60 reaches
  `feasible` in 1.48 deterministic seconds, and um120 reaches the same 2.50
  deterministic seconds it reaches at 1/3.
* The real bound on useful compact-seed work is already the *deterministic*
  cap, `_COMPACT_SEED_DETERMINISTIC_SECONDS_PER_BUDGET_SECOND = 32/375`
  (`sequence_solver.py:190`), which is 2.56 deterministic seconds at a 30 s
  budget.  The 1/3 **wall** share only binds when the solve cannot reach that
  cap — and in exactly that case it returns nothing.

Caveat: one run per configuration.  The identical areas across three shares on
four cells are the strong signal; the verdicts are not stable enough to read
alone (um120/sequence-pair REFUSED at 30 s in `plain-um120-sequence-pair.json`
and returned 43676 in the 1/3 run here — the cell sits on the boundary, which
is itself an argument for giving it 7.5 s more).

---

## 6. Prototype 2 (MEASURED): sequence-pair islands are written, off, and worth 13 %

`proto_islands.py` / `proto-islands.jsonl`.  Same 30 s budget, same cells, only
`SequencePairLayout(islands=N)` changes.  N complete solves run in spawned
processes with derived seeds (`sequence_islands._sequence_island_seeds`
preserves the serial seed at island zero) and the best exact result wins.

| cell | islands | verdict | wall | area | vs 1 island | winning seed | winning `compact_seed_attempt` | winning height |
|---|---|---|---|---|---|---|---|---|
| um60 | 1 | OK | 25.3 | 17654 | — | 20260824 | 0 | 92 |
| um60 | 4 | OK | 27.7 | 17654 | 0.0 % | 20260824 | 0 | 92 |
| um60 | 8 | OK | 29.2 | 17654 | 0.0 % | 20260824 | 0 | 92 |
| qc180 | 1 | OK | 27.3 | 21384 | — | 20260824 | 0 | 127 |
| qc180 | 4 | OK | 27.6 | **12608** | **-41.0 %** | 5575882164002757925 | 1 | 59 |
| qc180 | 8 | OK | 27.6 | **12152** | **-43.2 %** | 10900564138630012552 | 6 | 57 |
| gm200 | 1 | OK | 26.0 | 22140 | — | 20260824 | 0 | 85 |
| gm200 | 4 | OK | 27.7 | 21402 | -3.3 % | 7235786599208570764 | 3 | 82 |
| gm200 | 8 | OK | 28.0 | 22140 | 0.0 % | 20260824 | 0 | 85 |
| um120 | 1 | OK | 23.9 | 43676 | — | 20260824 | 0 | 117 |
| um120 | 4 | OK | 26.9 | 39312 | -10.0 % | 3940288563501391924 | 2 | 112 |
| um120 | 8 | OK | 26.9 | **38916** | **-10.9 %** | 12742959511457777618 | 5 | 133 |

Mean area change across the four cells: **-13.6 % at 4 islands, -13.5 % at
8**.  Four islands is as good as eight here, which matters because
`strategy_race.race_worker_split(16)[1]` is 4 — that is all a raced
sequence-pair arm may claim under `pipeline._candidate_race_parallelism`
(`pipeline.py:114`).

Two things this measurement shows beyond the headline:

* **The win comes from a different height branch, not from more of the same
  search.**  On qc180 the serial run lands at height 127; the winning island
  used `compact_seed_attempt = 6` and landed at height 57 — a branch the single
  serial attempt (`_serial_compact_seed_attempt`, always attempt 0) can never
  reach.  So islands are diversification, not raw throughput; they are also
  where extra cores get spent without anyone having to make one solve
  multi-threaded.
* **The wall cost is 2-3 s** (25.3 -> 29.2 s on um60), which is exactly the
  spawn + import price §3 measured (~0.9-1.3 s per child) plus pool teardown.
  It fits inside `budget + ATOMIC_COMPLETION_GRACE_S`, but on a 30 s corpus
  gate it is close enough to the wall to need its own overshoot check.

Harness note kept deliberately: the first run of this prototype died with
`BrokenProcessPool` in 3 s on every islands>1 cell, because
`run_sequence_islands` uses a **spawn**-context pool and the generated child
script had no `if __name__ == "__main__"` guard, so each island re-ran the
whole script.  Anyone flipping islands on in a script entry point has the same
trap waiting.

---

## 7. cProfile: top functions, and which kind of waste each one is

`--cprofile` inflates every Python call, so these are RATIOS, not seconds.
Full dumps: `cprof-*.pstats`, `cprof-*.tottime.txt`, `cprof-*.cumulative.txt`.

### Freeform, by tottime

| cell | function | tot | cum | calls | kind |
|---|---|---|---|---|---|
| um60 | `_astar` (freeform.py:7759) | 1.34 | 1.95 | 413 | the search itself (Cython inner loop) |
| um60 | `dataclasses._replace` (:1782) | 1.06 | 1.97 | 122943 | **allocation churn** |
| um60 | `_power_plan` (freeform.py:14731) | 0.98 | 2.70 | 2 | per-candidate, memo/Cython |
| um120 | `_astar` | 1.51 | 2.05 | 238 | search |
| um120 | `_power_plan` | 1.33 | 3.38 | 1 | per-candidate |
| um120 | `_projected_power_peer_possible` (:13500) | 0.49 | 0.94 | 119951 | O(peers²) geometry |
| qc180 | `_power_plan` | 1.06 | 3.46 | 4 | per-candidate |
| qc180 | `_projected_power_candidates` (finalize.py:705) | 0.86 | 2.04 | 2381 | finalizer geometry |
| qc180 | `collisions_at` (planet.py:1059) | 0.61 | 3.82 | 8901 | geometry kernel candidate |
| mall | `_astar` | 6.17 | 7.93 | 1475 | search |
| mall | `dataclasses._replace` | 3.36 | 6.22 | 525223 | **allocation churn** |
| mall | `_tap_source` (freeform.py:12727) | 2.70 | 4.79 | 670 | §5 follow-up, still unfixed |
| mall | `is_belt` (catalog.py:234) | 2.59 | 2.59 | **17557761** | attribute lookup in a hot loop |
| mall | `_coater_keepout_hits` (freeform.py:4855) | 2.23 | 4.10 | 438 | §5 follow-up, still unfixed |
| mall | `_projected_coater_junction_bans_by_frame` (:14263) | 1.81 | 5.42 | **2** | §5 follow-up; its three projection caches are LOCAL dicts rebuilt per call |

By cumtime the freeform story is the finalizer: on qc180,
`finalize_placement` (finalize.py:2690) is 8.35 s cum over 4 calls, of which
`_certify_frame` (finalize.py:1968) is 7.96 and `_failure_at_projection`
(finalize.py:1855) is 7.37 over 296 calls — about 28 % of a 28 s run, and it
runs for **every** candidate.

### Sequence-pair, by cumtime — one function is the whole story

| cell | function | cum | calls | share of the search |
|---|---|---|---|---|
| qc180 | `search` (sequence_solver.py:1226) | 18.20 | 1 | 100 % |
| qc180 | **`_variant_direct_eligibility` (sequence_solver.py:4352)** | **10.08** | **1** | **55 %** |
| qc180 | ├ `_selected_direct_targets` (:3805) | 10.06 | 1561 | |
| qc180 | ├ `_direct_alignment_targets` (freeform.py:3163) | 6.83 | 2157 | |
| qc180 | └ `DirectInsertTarget.__post_init__` (sequence_pair.py:216) | 6.46 (tot 3.08) | **131840** | |
| mall | `search` | 49.58 | 1 | 100 % |
| mall | **`_variant_direct_eligibility`** | **33.35** | **1** | **67 %** |
| mall | ├ `_selected_direct_targets` | 33.31 | 3065 | |
| mall | └ `_selected_strips` (sequence_solver.py:3714) | 24.00 | 3345 | |
| um60 | `<method 'acquire' of '_thread.lock'>` | 7.18 (tot) | 5678 | = `solve_compact_seed` (compact_seed.py:568), cum 7.31 |
| um120 | `<method 'acquire' of '_thread.lock'>` | 2.04 (tot) | 1622 | = the compact seed |

Three separately actionable facts:

1. **`_variant_direct_eligibility` is a ONE-CALL pre-pass that eats half the
   sequence-pair search.**  It runs an O(variant pairs) scan, re-selecting
   strips and re-enumerating `DirectInsertTarget`s per pair.  It is already
   `cancelled`-aware and its docstring says a cancelled scan "is an outcome the
   compact seed has always handled", so the scan is *optional by construction*
   — which makes both capping it and memoizing it safe designs.
2. **`DirectInsertTarget.__post_init__` runs 131,840 times per run** and its two
   `origin_deltas` generator expressions run 9.0 M and 7.4 M times
   (`sequence_pair.py:240` and `:242`).  Most of those constructions come from
   `_direct_alignment_targets`, a pure function of the candidate mapping, and
   from `replace(...)` on already-valid targets.
3. **`_StagedStaticPreclearanceProof.__call__` (freeform.py:1673)** is called
   2,331,465 times on mall-sequence-pair for 2.75 s tot / **14.22 s cum**.  The
   underlying proof is `@cache`d (`freeform.py:1661`); what costs is the
   ContextVar set/reset facade and the genexpr around it at
   `sequence_solver.py:3789-3795` — the coater `west_channel` lift, which
   scale-levers §3b lever 9 deliberately left un-memoized.

`Fraction.__eq__` (1,869,188 calls, 1.67 s tot on mall-sequence-pair) and
`hash` (7.27 M calls, 2.16 s) are the same story one level down.

---

## Files

| file | what |
|---|---|
| `load-at-start.txt` | uptime / vmstat / nproc at 17:03 |
| `run_phase.sh`, `run_cpu.sh` | batch drivers (two runs at a time) |
| `plain-*.json`, `plain-log.txt` | phase-shim runs, real seconds (§1) |
| `cprof-*.json/.pstats/.tottime.txt/.cumulative.txt`, `cprof-log.txt` | cProfile runs (§7) |
| `cpu_trace.py`, `cpu-*.json`, `cpu-log.txt` | per-second core/thread/process traces (§2) |
| `startup_cost.py`, `startup.json` | fixed pre-search cost (§3) |
| `budget_ladder.py`, `ladder.jsonl` | area/verdict vs budget (§4) |
| `proto_compact_share.py`, `proto-compact.jsonl` | prototype 1 (§5) |
| `proto_islands.py`, `proto-islands.jsonl`, `islands-log.txt` | prototype 2 (§6) |

Load at the end of the session: `17:34:26 up 20 days, 23:20, load average:
7.85, 8.33, 7.56`; `vmstat` `2 0 0 1016041028 0 20403788 0 0 0 17248 23249
53654 4 1 95 0 0 0`.

The ranked design is `docs/superpowers/specs/2026-09-05-speedups-2-design.md`.
