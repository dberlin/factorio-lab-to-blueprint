# Gate: hierarchical v2 on the large URLs

Branch `hierarchical-v2` at `bf8b1f40` (the code HEAD every measurement below
was taken at; this file and its evidence were committed after, so the evidence
commits `a7118ee2` / `e256c45b` carry no source change — `git diff bf8b1f40..HEAD -- src/`
is empty). Merge base: master `826c9e3e`. Worktree
`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v2`.

Box: 128 cores, never idle, load is I/O wait. Every timed step has a
`-load.txt` beside it with `uptime` and one `vmstat 1 3` sample taken
immediately before the run. At most one layout build ran at a time from this
plan, and no two audits ever ran at once (`ps -eo args | grep -cE 'scripts/audit\.py'`
checked before each of the four audit invocations; note that a plain
`pgrep -f audit.py` matches its OWN command line here and always returns a hit).

This is the successor to `../2026-09-07-hierarchical-v1/gate.md`. It gates five
changes: Task 1 `contracts.allocate_cuts` (`20aeb7a3`), Task 2
`partition.strip_count` (`4d1e8e92`), Task 3 funding and the pool (`ee04224e`,
`b5901cc4`, `bc8b9884`), Task 4 `compose.pack_with_access` (`e4e0ea8d`,
`4d655a41`), Task 5 `_ShapeNoGood` (`894557ce`, `bf8b1f40`).

## 0. The rule, declared before the results

Copied verbatim from `task-6-brief.md` step 4 and the controller's brief, and
not amended afterwards:

> **PASS** if: belt3 all-products, zurl2 and titanium-glass build CLEAN at 60 s
> within budget plus race grace with zero unrouted cuts; belt3 ≤ 1.25 x 12408;
> zurl2 ≤ 1.0 x 40905; titanium-glass ≤ 1.25 x 5727; titanium-glass builds at
> 15 s; both malls either build or refuse with every block placed and the
> refusal naming the composition stage; and the default guard is unchanged.
> **FAIL** otherwise, naming the clause.

The default guard, as the plan's Global Constraints declare it: one paired
`scripts/audit.py --budget 30 --json` round against the merge base, requiring
identical CLEAN counts, identical freeform per-cell areas, and a sequence-pair
geomean within ±0.11 % (that arm is not bit-reproducible across rounds because
of islands). `audit.py` prints `NOT CLEAN` on any refusal, so the counts and the
differing cells are read, not the banner.

Best-known dense areas for the `area / best_known` column, as the controller
supplied them: belt3 all-products **12408**, zurl2 all-products **40905**,
titanium-glass all-products **5727** (sequence-pair, `best` at 30 s). The mall
has no best-known area.

## 1. Verdict: **FAIL**, on the coverage clause

| clause | required | measured | |
| --- | --- | --- | --- |
| belt3 all-products CLEAN at 60 s | CLEAN, 0 unrouted cuts | **REFUSED both rounds**, `unrouted cut(s)` x **28** (`COMMIT_LINK` 10, `DYNAMIC_ACCESS` 10, `SEALED_POCKET` 8), identical in r1 and r2 | **FAIL** |
| zurl2 CLEAN at 60 s | CLEAN, 0 unrouted cuts | **REFUSED**, 18 unrouted (r1) / 15 (r2) | **FAIL** |
| titanium-glass CLEAN at 60 s | CLEAN, 0 unrouted cuts | **REFUSED**, 1 unrouted (r1) / 3 (r2), all `BUDGET` | **FAIL** |
| titanium-glass builds at 15 s | a blueprint | **REFUSED**, 4 unrouted (`SEALED_POCKET` 3, `COMMIT_LINK` 1), both rounds | **FAIL** |
| belt3 area ≤ 1.25 x 12408 = 15510 | an area | **no area** (no blueprint) | **FAIL** (not demonstrated) |
| zurl2 area ≤ 1.0 x 40905 | an area | **no area** | **FAIL** (not demonstrated) |
| titanium-glass area ≤ 1.25 x 5727 = 7159 | an area | **no area** | **FAIL** (not demonstrated) |
| both malls build, or refuse with every block placed and the refusal naming composition | every block placed | **neither**: `mall/all-products` refuses with **22 blocks never placed**, `mall/no-proliferator` with **45**, both naming the FUNDING rule, not composition | **FAIL** |
| wall within budget + race grace | ≤ 60 + 6.0 s | 22.8-63.2 s in-process; the largest, zurl2 at 63.2 s, is inside 66.0 s | PASS |
| default guard unchanged | identical CLEAN counts, identical freeform areas, seq-pair geomean ±0.11 % | CLEAN counts **72 = 72, identical**; 3 freeform cells and 3 sequence-pair cells moved, **every one of them demonstrably run-to-run noise present on BOTH trees** (§5), and no line of code either audited arm executes differs between the trees | **FAIL as literally declared**, PASS in substance — see §5 |

**The clause the gate fails on is coverage: 0 of 8 cells build.** No cell
emitted a blueprint, so no area exists to compare: the three area clauses are
*not demonstrated* rather than violated — the same distinction v1's gate had to
draw, and it cuts both ways, because a cell that never composes cannot
demonstrate zero unrouted cuts either.

### What did change, and it is not nothing

v1 refused **5 of 5** cells and only ONE of them ever reached composition
(`zurl2/all-products` r2, which then died in `contracts.assign_lanes`). v2
refuses 8 of 8, but **5 of the 8 cells now place every block, wire every cut
and reach the router**, and the three that do not are the two malls and belt3
at 15 s. The failure has moved from "the blocks were never attempted" to "the
router cannot wire the cut lanes on the ground the composer left". That is
exactly the wall the v1 gate's §6 lever 1 named, and §6 below says why the
lever this branch shipped for it cannot move it.

## 2. The eight large cells (CLI, two rounds each)

Invocation shape, per cell — the same as v1's `run_large.sh` (one candidate
policy per run so each cell gets the whole budget; `--band portable`; `-o`; and
**no `--workers`**, so the strategy sees the `None` the CLI passes by default,
which after Task 3's `pipeline.py` fix is what finally reaches `_pool_width`):

```
uv run python run_cell.py <stem>.json -- "<url>" --strategy hierarchical \
    --budget <60|15> --band portable --candidate-policy <policy> -o <stem>.blueprint.txt
```

`run_cell.py` is this gate's own harness. It calls `flab2bp.cli.main(argv)` with
**exactly** the argv above and changes nothing about the build; it only reads
what passes through, because the CLI prints no `PlacementStats` key at all and
`PackedCanvas.gap` never reaches `PlacementStats` in the first place. What it
reads, and why, is in its module docstring. Files:
`large-{label}-{policy}-b{budget}-r{1,2}.{json,log,stdout.txt}` and `-load.txt`.

| cell | budget | r1 wall (proc / shell) | r2 wall | verdict | how far it got | area | area / best_known |
| --- | --- | --- | --- | --- | --- | --- | --- |
| belt3 / all-products | 60 | 49.4 / 50.7 s | 45.7 / 46.8 s | REFUSED (exit 3) | composed; router refused **28** cuts | — | n/a |
| belt3 / no-proliferator | 60 | 32.8 / 34.4 s | 34.2 / 35.8 s | REFUSED | composed; **7** cuts (r1), **9** (r2) | — | n/a |
| zurl2 / all-products | 60 | 63.2 / 64.7 s | 62.5 / 63.8 s | REFUSED | composed; **18** cuts (r1), **15** (r2) | — | n/a |
| mall / all-products | 60 | 28.8 / 30.3 s | 28.7 / 29.9 s | REFUSED | **22 blocks never placed**, 8.0 s over 2 waves | — | n/a |
| mall / no-proliferator | 60 | 22.9 / 24.0 s | 22.8 / 24.2 s | REFUSED | **45 blocks never placed**, 13.8 s over 3 waves | — | n/a |
| titanium-glass / all-products | 60 | 30.1 / 31.2 s | 31.8 / 33.3 s | REFUSED | composed; **1** cut (r1), **3** (r2), all `BUDGET` | — | n/a |
| titanium-glass / all-products | 15 | 15.2 / 16.8 s | 15.2 / 17.1 s | REFUSED | composed; **4** cuts | — | n/a |
| belt3 / all-products | 15 | 11.2 / 12.8 s | 11.3 / 13.0 s | REFUSED | **3 blocks never placed**, -1.5 s over 1 wave | — | n/a |

"proc" is `run_cell.py`'s own `perf_counter` around `cli.main`; "shell" is the
`date`-to-`date` wall in `run_large.sh` and includes ~1.5 s of interpreter and
dataset start-up. Exit 3 is the CLI's "no layout exists" code on every cell: no
crash, no handback, no invalid blueprint anywhere in the sixteen runs.
**`area / best_known` is not computable on any cell** — nothing was emitted, so
no `*.blueprint.txt` exists in this directory.

### 2.1 The stats the CLI does not print

Read by `run_cell.py`; every number below is from the `-r{1,2}.json` sidecars.

| cell (b60 unless noted) | seed blocks (cap 12) | cut lanes | player-fed pairs | gap chosen | port demands | reservation `missing` | rounds | nogood skips (r2) | unrouted classes (r1 / r2) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| belt3 / all-products | 9 | 89 | 0 | **2** | 102 | **0** | 2 | **2** | `CL`10 `DA`10 `SP`8 / identical |
| belt3 / no-proliferator | 14 | 130 | 0 | **2** | 168 | **0** | 1 | **4** | `DA`3 `CL`2 `SP`2 / `DA`3 `CL`4 `SP`2 |
| zurl2 / all-products | 17 | 127 | **1** (`block 16 : hydrogen`) | **2** | 144 | **0** | 1 | 0 | `BUDGET`8 `DA`7 `CL`3 / `DA`9 `CL`4 `BUDGET`2 |
| mall / all-products | 19 | — | — | — | — | — | 2 | **36** | never composed |
| mall / no-proliferator | 24 | — | — | — | — | — | 1 | **8** | never composed |
| titanium-glass / all-products | 6 | 26 | 0 | **2** | 31 | **0** | 1 | 0 | `BUDGET`1 / `BUDGET`3 |
| titanium-glass / all-products b15 | 6 | 26 | 0 | **2** | 31 | **0** | 1 | 0 | `SP`3 `CL`1 / identical |
| belt3 / all-products b15 | 9 | — | — | — | — | — | 1 | 0 | never composed |

`CL` = `COMMIT_LINK`, `DA` = `DYNAMIC_ACCESS`, `SP` = `SEALED_POCKET`. Seed
block counts are from `probe-{url}-{policy}.json` (`initial_partition` only,
milliseconds, cap 12).

Three provenance notes, because R6 asks for them explicitly:

* **`nogood_skips` is reported from the harness, not from `PlacementStats`.**
  Task 5's counter is written into `stats` only on the SUCCESS path
  (`strategy.py:643`, inside the block that runs after certification). Every
  cell of this gate refused, so `PlacementStats["nogood_skips"]` was never
  written on any run and is unreachable in principle here. `run_cell.py` sums
  `HierarchicalLayout._solve_round`'s return value instead, which is the exact
  quantity `lay_out` accumulates into that key. The spy was added between the
  two rounds, so **the column is round 2 only**; round 1's sidecars carry no
  `rounds`/`nogood_skips` field at all and none is invented for them.
* **`player_fed` is not exposed by any shipped surface.** It is neither a
  `PlacementStats` key nor anything `-v` prints; `CutAllocation.player_fed`
  lives and dies inside `lay_out`. Per R6 the honest answer is "not exposed",
  and the numbers above come from `run_cell.py`'s wrapper around
  `strategy.allocate_cuts`, labelled as such. No production code was added.
* **`gap` is likewise not exposed.** `ComposeResult` does not carry it and
  `PackedCanvas.gap` never leaves `compose`. Same wrapper, same labelling.

### 2.2 What the refusals say, verbatim

The two shapes, quoted from the logs:

```
mall / all-products r1:
  hierarchical/all-products: 22 block(s) never placed, 8.0s left over 2 wave(s)
  is under the 5s a block solve is given at all: block 20 (steel): not attempted; ...

zurl2 / all-products r2:
  hierarchical/all-products: unrouted cut(s): copper-ingot: block 10 -> block 13:
  DYNAMIC_ACCESS; electric-motor: block 14 -> block 13: DYNAMIC_ACCESS; iron-ingot:
  block 3 -> block 14: DYNAMIC_ACCESS; ... titanium-ingot: block 0 -> block 7:
  DYNAMIC_ACCESS.
```

The mall's refusal names the **funding rule**, which is the clause it fails:
the gate rule allows a mall to refuse only "with every block placed and the
refusal naming the composition stage". Neither mall reaches composition.

The funding arithmetic behind it, from `strategy.py:493-511` and the messages
above: at 60 s the reserve is `min(40, max(5, 24)) = 24 s`, the pool is
`min(32, 128 // 4) = 32` wide, and a round's share is
`remaining / ceil(blocks * arms / 32)`. `mall/all-products` runs two solve
rounds and then arrives at a third with 22 blocks (44 jobs, 2 waves) and 8.0 s
left: `8.0 / 2 = 4.0 s`, under `BLOCK_BUDGET_MIN_S = 5.0`.
`mall/no-proliferator` arrives at its second round with 45 blocks (90 jobs, 3
waves) and 13.8 s: `13.8 / 3 = 4.6 s`. `belt3/all-products` at 15 s has a 6.0 s
reserve, runs one round, and reaches the re-cut round with `remaining = -1.5 s`
— that is, already 1.5 s inside the 6.0 s it held back for the settlement.

This is v1 §6 lever 2 exactly, and it is **still open on the mall** even though
Task 3 quadrupled the pool (4 -> 32) and halved the reserve floor. The pool
width is no longer the binding constraint — 32 wide, `mall/no-proliferator`'s
90 jobs are only 3 waves — the binding constraint is that the re-cut loop keeps
GROWING the block count (19 seed blocks -> 22 unattempted; 24 -> 45) and the
round's wall is still divided by waves.

## 3. Strip-cap sweep (Step 1), belt3 all-products

`sweep_strip_cap.py` (adapted from v1's; `--workers` now defaults to **None**,
because a sweep at v1's hardcoded `workers=16` would no longer measure the
shipped default after Task 3's pipeline fix). Budget 60 s, caps 8/12/16/24, one
build at a time in one process. Files `sweep-belt3-all-products.{json,log}` and
`-load.txt`; partition-only probe in `probe-belt3-all-products.json`.

### 3.1 What the cap does to the seed partition (probe, milliseconds)

| cap | blocks / cuts / strips_max / machines_max |
| --- | --- |
| 8 | 16 / 29 / 5 / 28 |
| **12** (shipped) | 9 / 12 / 11 / 61 |
| 16 | 9 / 12 / 11 / 61 |
| 24 | 7 / 7 / 24 / 129 |

Compare v1's own probe at the same URL and cap: **3 blocks / 7 cuts / 7 strips /
145 machines** at cap 12. That is Task 2's whole effect — `strip_count` now
counts what `freeform.plan_strips` packs, the 129-machine block is 24 packed
strips rather than 7 logical ones, and the cap bites where it never used to.

### 3.2 What the cap does to a real build (60 s, workers None, one build per cap)

| cap | wall | stage | gap chosen | port demands | `missing` | unrouted cut lanes |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | 22.3 s | composed | **4** | 111 | 0 | **8** (`DA` 7, `SP` 1) |
| **12** (shipped) | 44.7 s | composed | 2 | 102 | 0 | **28** (`CL` 10, `DA` 10, `SP` 8) |
| 16 | 34.5 s | composed | 2 | 91 | 0 | **11** (`DA` 5, `CL` 4, `SP` 2) |
| 24 | 36.5 s | **unplaced**, 3 blocks, 1 wave, -0.0 s left | — | — | — | — |

### 3.3 The cap decision: **`STRIP_CAP_DEFAULT` stays at 12**

The brief's pick rule is "the smallest cap that builds CLEAN with the smallest
area". **It selects nothing: no cap builds CLEAN and no cap produces an area.**
As in v1, the sweep is undecidable as a constant, and no code was changed for it.

Two honest observations that a future sweep should start from, neither of which
is a decision this gate is entitled to make:

* cap **8** produces the fewest unrouted lanes (8, against 28 at the shipped
  cap) and is the fastest to its verdict (22.3 s) — and it is **the only
  measurement in this whole directory in which the gap ladder actually fires**:
  it committed gap 4, not rung 0. §3.4 takes that apart, because it is the one
  observation that constrains lever 1. That is a 16-block partition of the same
  URL, so it is also the cap where a corridor lever would have the most ground
  to work with. It is one run, on one policy.
* cap **24** is the funding cliff again: 7 blocks x 2 arms is a single wave, and
  the round is still refused with `-0.0 s` left, because a 129-machine block
  eats the whole round before the re-cut can be funded.

### 3.4 The one time the ladder fires: cap 8, rung by rung

`sweep_strip_cap.py` and `run_cell.py` both wrap `pack_with_access` and so see
only the rung it COMMITS. A committed gap of 4 with a complete reservation can
only mean rung 0 was judged and rejected, and this gate is not entitled to
report a rejected rung it never saw. `ladder_probe.py` therefore wraps one level
lower — `compose._pack_at` for each rung's gap and `compose._reserve_port_access`
for that rung's verdict — and re-ran the cap-8 cell
(`ladder-belt3-all-products-cap8.{json,log}`, `ladder-probe-load.txt`, 22.7 s,
the same 8 unrouted cuts as the sweep row):

| rung | gap | assigned | missing | complete |
| --- | --- | --- | --- | --- |
| 0 | 2 | 110 | **1** — `energetic-graphite @ belt 6249`, kind `internal-arrival` | **no** |
| 1 | 4 | 111 | 0 | yes |

Three things follow, and they are the empirical constraint on §6 lever 1:

1. **The ladder is not dead code.** It fires, it widens, and the wider rung is
   genuinely complete. Task 4's machinery works.
2. **It fired on a demand R11 predicts it can only judge LOCALLY.** The one
   missing demand is an `internal-arrival` — `reaches_boundary == False` — so
   what rejected rung 0 was the joint matcher failing to find a cell-disjoint
   (access, exit) pair for that lane head, NOT the boundary reachability probe,
   which skips internal demands entirely. R11's mechanism is confirmed by the
   one case that could have refuted it.
3. **And it did not help.** Gap 4 satisfied every port and the router still
   refused 8 cut lanes (`DYNAMIC_ACCESS` 7, `SEALED_POCKET` 1). A canvas on
   which every port has a private doorstep is still a canvas on which the trunks
   cannot share ground.

The frequency matters as much as the mechanism: **one rejection, of one demand,
out of 111, in one run, at a cap that is not the default.** At the shipped cap
12 and at cap 16, and on all five composing CLI cells across two rounds (31 to
168 demands each), rung 0 was judged and found COMPLETE — that is the returned
rung, so it is a direct observation, not an inference.

## 4. Where the strategy dies, and where this gate agrees or disagrees with each task

Failure sites, in the order a build meets them:

1. **Unfunded round** — `mall` at both policies (22 and 45 blocks never placed)
   and `belt3/all-products` at 15 s (3 blocks). 3 of 8 cells.
2. **Lane contract** — `contracts.assign_lanes` refusing a cut's supply.
   **Zero occurrences in sixteen runs.** In v1 this was `zurl2/all-products` r2.
3. **Unrouted cuts** — every block placed, composed and ported, and `_route_all`
   refuses. 5 of 8 cells, both rounds. Dominated by `DYNAMIC_ACCESS`,
   `COMMIT_LINK` and `SEALED_POCKET`, with `BUDGET` on the two cells whose
   interface is smallest (titanium-glass) or largest (zurl2 r1).

Per-task, with each implementer's own measurement cited as theirs:

* **Task 1 (`contracts.allocate_cuts`)** measured "zurl2 no longer refuses on
  `lane contract: hydrogen ...`". **This gate agrees, and can say why.** zurl2
  reaches the router in both rounds, no `ContractError` appears anywhere in the
  gate, and the sidecars show exactly one player-fed pair on that cell:
  `block 16 : hydrogen` — the same (block, item) v1 refused on. The mechanism
  is doing precisely what Task 1 built it to do.
* **Task 2 (`partition.strip_count`)** measured belt3's seed partition going
  3 blocks -> 9 at cap 12, the 129-machine block splitting, and
  `initial_partition` costing 0.008 s -> 0.282 s. **This gate agrees** on the
  partition (§3.1: 9 blocks / 12 cuts at cap 12, against v1's 3 / 7) and on the
  cost with a caveat: a COLD `initial_partition` here is 0.27-0.87 s depending
  on the URL (`probe-*.json`), while a second call in the same process is
  0.078 s. Task 2's 0.282 s is a cold call; both numbers are real and they are
  not the same measurement.
* **Task 3 (funding and the pool)** measured titanium-glass at `--budget 15`
  going from refusing having attempted NOTHING to placing and composing all 6
  blocks for all three candidate policies in 47.2 s wall, with the refusal
  moving to the router. **This gate agrees.** Pinned to one policy,
  titanium-glass at 15 s places and composes its 6 blocks in 15.2 s in both
  rounds and refuses at the router with 4 unrouted cuts. The v1-era behaviour
  documented in `../2026-09-06-debug-url/README.md` (class C5: "the funding rule
  refuses round 1 before any solve — 15 s is the exact knife edge") is gone.
  Where this gate must *qualify* Task 3: the pool fix does NOT rescue the mall
  (§2.2), so the lever is real but partial.
* **Task 4 (`compose.pack_with_access`)** measured belt3 all-products at 60 s
  choosing gap 2 (rung 0) with `missing` 0 before and after across 102 demands —
  the lever never firing — and still refusing with 28 unrouted cuts (10
  `COMMIT_LINK`, 10 `DYNAMIC_ACCESS`, 8 `SEALED_POCKET`). **This gate reproduces
  that measurement exactly**, in the sweep at cap 12 and in both CLI rounds:
  102 demands, gap 2, `missing` 0, `COMMIT_LINK` 10 / `DYNAMIC_ACCESS` 10 /
  `SEALED_POCKET` 8. **And it generalises it**: across all five composing cells,
  spanning 31 to 168 port demands and four URLs, in both rounds, the ladder
  committed **rung 0 (gap 2) every single time with `missing` 0 and
  `reservation.complete` true.** The single exception in this entire directory
  is the cap-8 sweep row, and §3.4 takes it apart rung by rung: rung 0 missed
  exactly ONE demand of 111 and rung 1 (gap 4) was complete. So the ladder is
  not dead code — it fires, correctly, once — but at a rate of one rejected
  demand in one non-default configuration, and the rejection was a LOCAL
  matching failure on an `internal-arrival` demand, which is exactly what R11
  predicts is the only thing this oracle can ever reject. §6 lever 1 is about
  what it structurally cannot.
* **Task 5 (`_ShapeNoGood`)** shipped `stats["nogood_skips"]`. **This gate finds
  the lever live but verdict-neutral.** It fires on 4 of 8 cells in round 2 —
  `mall/all-products` **36** skips, `mall/no-proliferator` 8, belt3
  `no-proliferator` 4, belt3 `all-products` 2 — and 0 on zurl2 and both
  titanium-glass cells. It is doing real work exactly where the re-cut loop
  explodes (the mall, whose block count grows 19 -> 22 unattempted and 24 -> 45),
  and it changed no cell's verdict, no cell's failure class, and no cell's
  block count. Its own key is also unobservable through the surface it was
  added to (§2.1), because that surface is written only on a success path this
  gate never reaches.

## 5. Default-unchanged guard (Step 3)

Per controller ruling R13: everything committed first, `git status --short`
empty, `git checkout --detach 826c9e3e`, the BASELINE half run there, then
`git checkout hierarchical-v2` immediately, HEAD and cleanliness verified, then
the CANDIDATE half. No `git stash`, no second worktree. `.superpowers/` is
gitignored and survived; the baseline half was written to `/tmp/v2gate/` (the
evidence directory does not exist at the merge base) and copied in on return.
The three compiled kernels imported from `src/` on both trees — no `.pyx`
changed on this branch, so no rebuild was needed and none happened.

Files: `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`, their
`-load.txt`, `judge-round1.txt` (`judge.py`, copied from
`../2026-09-07-hierarchical-v1/`).

```
commits  : baseline 826c9e3  candidate a7118ee
status counts       baseline  candidate
  CLEAN                   72         72
CLEAN in baseline, not CLEAN in candidate: 0     <-- no regression
not CLEAN in baseline, CLEAN in candidate: 0
INVALID/CRASH in either: 0
gmean area ratio  all 0.99612 (-0.39 %)  freeform 1.00009 (+0.01 %)  seq-pair 0.99217 (-0.78 %)
cells whose area moved at all: 6 of 72
wall-safety: candidate max overshoot 0.000 s vs baseline 0.000 s -> OK
total build wall: baseline 1423.7 s, candidate 1419.8 s   (197 s / 195 s wall)
```

**As literally declared the guard fails on two of its three sub-clauses** —
freeform areas are not identical (3 cells moved) and the sequence-pair geomean
is -0.78 %, outside ±0.11 %. Both were run down, and both are noise:

**(a) CLEAN counts are identical, 72 = 72, and both sides are 72/72 CLEAN.**
Sub-clause (a) passes outright. v1 could not say this (its baseline was 71).

**(b) and (c): the six moved cells all move on BOTH trees.** Each of the three
url_ids carrying a moved cell was re-run once more on the candidate tree and,
after a second detached checkout, on the baseline tree
(`moved-{baseline,candidate}-r2.{jsonl,txt}`,
`scripts/audit.py --budget 30 --only universe-matrix,super-magnetic-ring,casimir-crystal`,
18 cells each, 71 s and 72 s wall; one load sample, `moved-cells-load.txt`,
taken immediately before the pair — the two halves ran back to back, separated
only by the checkout):

| cell | base r1 | base r2 | cand r1 | cand r2 | reading |
| --- | --- | --- | --- | --- | --- |
| freeform `casimir-crystal [2/output-products]` | 1144 | **1100** | 1100 | **1144** | an exact swap: each tree produces both values |
| freeform `super-magnetic-ring [0/no-proliferator]` | 2200 | **2291** | 2255 | **2233** | four different values, four runs |
| freeform `super-magnetic-ring [2/output-products]` | 2016 | **2072** | 2052 | 2052 | baseline is the unstable side |
| sequence-pair `universe-matrix [0/no-proliferator]` | 21420 | **18150** | 17836 | **21420** | candidate r2 lands on the baseline's r1 value exactly |
| sequence-pair `universe-matrix [1/all-products]` | 31317 | **25168** | 33748 | **25168** | both trees produce 25168 on r2 |
| sequence-pair `universe-matrix [2/output-products]` | 19458 | **18445** | 16340 | 16340 | baseline is the unstable side |

The re-run also caught a SEVENTH unstable cell that happened not to differ in
round 1: freeform `universe-matrix [0/no-proliferator]` sat at 31898 on the
candidate in both rounds and moved 31898 -> **39312** on the BASELINE. The
instability is not on the candidate's side of the comparison.

**The structural argument, which is decisive and which v1 could not make.**
`git diff --no-ext-diff 826c9e3e..bf8b1f40 -- src/` touches six files. Four are
`layout/hierarchy/{compose,contracts,partition,strategy}.py`, a package neither
audited arm imports. The other two are edits outside it, and both are inert for
`freeform` and `sequence-pair` —

* `layout/base.py`: adds the key `nogood_skips: float` to the
  `PlacementStats` TypedDict. A TypedDict key has no runtime behaviour.
* `pipeline.py`: `workers=worker_budget` becomes
  `workers=workers if sname == "hierarchical" else worker_budget`. For
  `sname` in `{"freeform", "sequence-pair"}` the expression is the old one.

**No line either audited arm executes differs between the two trees**, and
`hierarchical` is not in `PRODUCTION_STRATEGIES`, so it is in neither audit.
Combined with the table above, the finding is that these six cells are the
corpus's time-bounded-search noise floor at a 30 s budget, and that the guard's
"identical freeform areas" and "±0.11 % geomean" sub-clauses are not achievable
on `universe-matrix` and `super-magnetic-ring` at that budget regardless of
branch. Excluding `universe-matrix`, the sequence-pair geomean over the other
**33 cells is exactly 1.00000** — every one of them bit-identical. Excluding
`super-magnetic-ring` and `casimir-crystal`, the freeform geomean over **30
cells is exactly 1.00000**.

**Summary of the guard: FAILS AS DECLARED on sub-clauses (b) and (c), PASSES
(a), and is a no-op in substance** — 0 of 72 cells CLEAN -> not CLEAN, 0
INVALID, 0 CRASH, 0 wall overshoot, **66 of 72 cells bit-identical** between
the trees, and all 6 that were not shown moving on both trees by the re-run
(which turned up a 7th unstable cell that happened to agree in round 1, and
whose instability is on the BASELINE side).

## 6. The next three levers, from the measurement

### Lever 1 (headline): make the port-access oracle BOUNDARY-AWARE for internal demands. As specified, the ladder can only ever judge a doorstep.

This is the single most valuable finding in this evidence, and it is a finding
about the code, not about belt3. To state it precisely: the ladder is not inert
as code — §3.4 shows it firing — but the BOUNDARY half of its oracle is
structurally unreachable, so the only question it can ever answer "no" to is a
local one. Controller ruling R11 established the mechanism; **every file:line
below was re-verified against `bf8b1f40` before being printed here**:

> `compose` calls `_port_access_inventory(packing.nets)` with no
> `boundary_inputs` / `boundary_outputs` (`hierarchy/compose.py:696`; the
> parameters exist and default to `()` at `freeform.py:11577-11585`), so the
> inventory can only emit `INTERNAL_DEPARTURE` / `INTERNAL_ARRIVAL` demands
> (`freeform.py:11604-11609`). Both have `reaches_boundary == False`
> (`freeform.py:11545-11550`). `_reserve_port_access` gates its ENTIRE
> reachability probe on that flag — `if boundary is None or not
> demand.kind.reaches_boundary:` takes the early-continue for every demand
> (`freeform.py:11971-11974`) — and the joint matcher's
> `assignment_boundary_cut` validator skips every non-boundary demand and
> therefore always returns `None` (`freeform.py:12017-12019`). **Passing the
> outer ring as the boundary cannot move a single demand into `missing`.**

What the ladder actually tests is the LOCAL claim "does every lane head have a
cell-disjoint free (access, exit) pair after joint matching", which at gap 2
with an 8-tile margin is essentially always satisfiable — measured here: every
demand satisfied on every default-cap cell, and 110 of 111 at cap 8.

**The measurement now says the same thing across the whole gate, not just on
belt3.** Five composing cells, four URLs, 31 to 168 port demands, two rounds
each, plus the cap-12/16/24 sweep rows: the committed rung was **rung 0 (gap 2)
with `missing` 0 and `reservation.complete` true, every time**.

The one exception, and it is the exception that proves the mechanism: at strip
cap 8 the ladder DID fire (§3.4). Rung 0 missed exactly **one** demand of 111 —
`energetic-graphite @ belt 6249`, kind **`internal-arrival`**, i.e. a demand
whose `reaches_boundary` is False — so what rejected the rung was the joint
matcher failing a LOCAL cell-disjointness claim, not the boundary probe, which
never ran on it. Rung 1 (gap 4) was complete, **and the router still refused 8
cut lanes on it**. That is the sharpest possible statement of the problem: the
one time the oracle spoke, it spoke about a doorstep, the ladder paid for a
wider canvas to buy that doorstep, and the trunks still could not share ground.
`GAP_LADDER`'s four upper rungs (6, 8, 12, 16) and the `LADDER_WALL_SHARE`
budget that funds them have never been exercised by any measurement here.

Meanwhile the residual refusals are `COMMIT_LINK`, `SEALED_POCKET` and
`DYNAMIC_ACCESS` — shared-ground contention among trunks after the reservation
has already declared every port satisfiable. **The oracle is structurally blind
to the thing that is actually refusing.**

Why this outranks v1 §6's lever 1 (a pre-placed bus corridor, design §4 E):
the corridor is a new subsystem — reserve ground before block placement, then
teach placement, composition and the router to respect it. Making the oracle
boundary-aware is a change to what `compose` PASSES and what `reaches_boundary`
ADMITS: give `_port_access_inventory` the composed canvas's real boundary
lanes, or admit internal demands into the reachability probe when a boundary is
supplied. The machinery — the corridor enumeration, the joint matcher, the
`assignment_boundary_cut` A\* validator, the ladder that spends the verdict —
already exists and is already wired; it is simply never asked the question that
would make it say no. **Cheaper, and it is the prerequisite for knowing whether
the corridor is even needed**: until the oracle can reject a rung for the reason
that actually refuses the build — trunks sharing ground — a wider rung is tried
only on the rare local miss and buys nothing (§3.4), and the ladder that Task 4
built cannot pay for itself.

### Lever 2: fund the re-cut rounds, and bound the block growth

Evidence: §2.2. The pool is now 32 wide and the reserve floor is 5 s, and the
mall STILL refuses with 22 and 45 blocks never placed, because
`share = remaining / waves` is computed against a block count the re-cut loop
keeps growing (19 seed -> 22 unattempted; 24 -> 45), and `MAX_RESPLIT_ATTEMPTS`
is counted per block with no global round bound (§7). v1 ranked this second and
Task 3 moved the pool half of it; the remaining half is the wave divisor and
the unbounded growth. **Three** of the eight cells fail here — both malls and
belt3 at 15 s — and no other lever can reach them, because they never compose.

### Lever 3: give the router shared ground to work in, i.e. v1's bus corridor

Evidence: §2.1 — 28 / 15 / 9 / 4 / 3 unrouted cuts across five composing cells,
all of them `COMMIT_LINK` / `SEALED_POCKET` / `DYNAMIC_ACCESS` contention, with
the port-access oracle reporting complete satisfaction at the same moment. This
is v1 §6's lever 1, demoted one place — not because it got cheaper or less
necessary, but because lever 1 above is the measurement that tells you whether
a corridor is what the geometry is missing, and it costs a fraction as much to
build. Note that v1's lever-3 ("close the lane contract on byproducts") has
been overtaken: Task 1 shipped the player-fed escape hatch and no
`ContractError` occurs anywhere in this gate.

## 7. Backlog: the two remaining adaptive memories

v1 §7 listed three ideas the user raised. **The first — a within-build no-good
keyed on block shape — shipped as Task 5** (`_ShapeNoGood`), and §4 records
what it does: 36 skips on `mall/all-products`, 8 on `mall/no-proliferator`, 4
and 2 on the belt3 policies, 0 elsewhere, and no change to any verdict. The
other two are still open, and this gate sharpens the evidence for both.

* **A cross-build solved-block cache.** The evidence is stronger than v1's.
  Across the sixteen CLI runs in §2 and the five sweep and probe builds in §3,
  the same
  one-recipe blocks (`gear`, `electric-motor`, `iron-ingot`, `magnet`,
  `copper-ingot`, `steel`) were solved from scratch every time — the refusal
  texts name them by recipe, and `mall/no-proliferator` alone lists nine
  consecutive `magnet` blocks and seven `iron-ingot` blocks in ONE refusal. Task
  2's finer partition has made this much more valuable than it was in v1: the
  seed partitions are now 6-29 blocks instead of 2-3, most of them
  single-recipe, and a block is a self-contained `BuildSpec` with a
  deterministic sub-spec derivation, so it is cacheable on that spec's own hash.
  It is also the one lever that would make the SECOND run of a URL fast, which
  is what an interactive user sees. Related work already planned: "background
  compound block cache" (`42c9e0e`).
* **A strip cap that moves with outcomes.** §3.3 is again the direct argument,
  and it is now a sharper one than v1's: cap 8 gives belt3 the fewest unrouted
  lanes (8 vs 28) and the fastest verdict, cap 24 starves the round at a single
  wave, and the shipped cap 12 is the WORST of the three composing caps by
  unrouted count. But no cap builds, so a fixed constant cannot be chosen on
  outcomes that do not exist yet. Sequencing note, revised from v1: this is now
  worth something as soon as lever 1 lands, because a cap only becomes
  choosable once some cap produces a blueprint — and it should adapt on the
  ROUTER's verdict (unrouted lanes per cut), which is the signal §3.2 shows
  varying by 3.5x across caps, rather than on "the round was not funded".

## 8. As-shipped strategy constants (three of them changed on this branch)

Carried forward from v1 §8 and corrected. The numbers in this gate were
measured against **these**. `src/flab2bp/layout/hierarchy/strategy.py`'s module
docstring carries the same list next to the code.

| What | As shipped on `hierarchical-v2` | v1 value | Where |
| --- | --- | --- | --- |
| Settlement reserve | `min(40, max(**5**, 0.4 * budget))` | floor was **10** | `settlement_reserve_s`, `SETTLEMENT_RESERVE_{MIN,MAX}_S`, `SETTLEMENT_RESERVE_SHARE` |
| Pool width | `max(1, min(**32**, (workers or **_available_cpu_count()**) // 4))` | `max(1, (workers or **16**) // 4)` | `_pool_width`, `_POOL_CAP`, `_BLOCK_WORKERS` |
| What the CLI passes as `workers` | the caller's RAW `--workers`, or `None` | the 16-capped `worker_budget` | `pipeline.build`'s `_attempt` |
| Strip cap | `STRIP_CAP_DEFAULT = 12`, counting **packed** strips (`freeform.plan_strips`) | 12, counting **logical** strip plans | `partition.STRIP_CAP_DEFAULT`, `partition.strip_count` |
| Composition gap | a SEARCHED rung of `GAP_LADDER = (2, 4, 6, 8, 12, 16)`, funded out of `LADDER_WALL_SHARE = 0.4` after rung 0; `strategy.DEFAULT_GAP = 2` is now the ladder's FLOOR | `DEFAULT_GAP = 2` was the gap itself | `compose.pack_with_access`, `strategy.DEFAULT_GAP` |
| Block-shape no-good | `_ShapeNoGood`, per build, keyed on `(sorted (recipe, count) per Unit, arm)` with the refusing budget | absent | `strategy._ShapeNoGood`, `stats["nogood_skips"]` |
| Child search workers | 4 CP-SAT workers per block solve | same | `_BLOCK_WORKERS` |
| Per-round block budget | `clamp(remaining / waves, 5, 20)` s, `waves = ceil(blocks * arms / pool width)` | same | `lay_out`, `BLOCK_BUDGET_{MIN,MAX}_S` |
| Per-job deadline | `min(parent_deadline, job_start + block_budget)`, computed in the worker | same | `_solve_block` |
| Re-cut attempts | `MAX_RESPLIT_ATTEMPTS = 4`, **per block**; no global round bound | same | `_recut` |
| Process context | `spawn`; ONE pool for the whole build, not one per round | one pool per round | `_spawn_pool`, `lay_out` |

Which of these are load-bearing for the readings above:

* **The reserve floor and the pool width are why titanium-glass at 15 s now
  composes** (§4, Task 3). At 15 s the reserve is `max(5, 6.0) = 6.0` rather
  than `max(10, 6.0) = 10.0`, which turns the "exactly 0.0 s" knife edge
  recorded in `../2026-09-06-debug-url/README.md` into 9 s of round.
* **The pool width is no longer the mall's binding constraint** (§2.2). At 32
  wide, `mall/no-proliferator`'s 90 jobs are 3 waves; the round still refuses.
  v1 §8's reading of this row is superseded.
* **`strip_count` counting packed strips is why every partition in this gate is
  2-5x finer than v1's** (§3.1), which is what makes the funding rule and the
  cross-build cache both more pressing than they were.

Two consequences of the shipped shape, unchanged from v1 and not defects:

* A build can **overshoot `--budget`**: the settlement is entered on the
  strategy's deadline rather than bounded by it, so
  `pipeline._serial_completion_grace` gives `hierarchical` the spawn-pool grace
  (`RACE_COMPLETION_GRACE_S = 6.0`). zurl2's 63.2 s at a 60 s budget is that
  grace being used, inside its allowance.
* A defect inside wiring and composition surfaces as
  `composition crashed: <type>: <message>` rather than a traceback. That guard
  fired **zero times** in this gate.

## 9. Files

* `gate.md` (this file); `judge.py` (copied from `../2026-09-07-hierarchical-v1/`)
* `run_large.sh`, `run_cell.py`;
  `large-{belt3,zurl2,mall,titanium-glass}-{policy}-b{60,15}-r{1,2}.{json,log,stdout.txt}`
  and their `-load.txt`
* `sweep_strip_cap.py`; `sweep-belt3-all-products.{json,log}`,
  `sweep-belt3-all-products-load.txt`
* `ladder_probe.py`; `ladder-belt3-all-products-cap8.{json,log}`,
  `ladder-probe-load.txt` (§3.4, the rung-by-rung re-run of the cap-8 cell)
* `probe-belt3-all-products.json` (the cap sweep's partition probe) and
  `probe-{belt3,zurl2,mall,titanium-glass}-{all-products,no-proliferator}.json`
  (cap 12, the shipped default, for the §2.1 seed-block column)
* `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`,
  `judge-round1.txt`, their `-load.txt`
* `moved-{baseline,candidate}-r2.{jsonl,txt}`, `moved-cells-load.txt`

No blueprint file is present: every run refused, so `-o` was never written.
