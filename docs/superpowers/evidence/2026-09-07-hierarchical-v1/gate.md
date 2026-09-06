# Gate: hierarchical v1 on the large URLs

Branch `hierarchical-v1` at `8eff46d8`, merge base `d57bc7cd`. Worktree
`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v1`.
Box: 128 cores, never idle; every timed step has a `-load.txt` beside it with
`uptime` and one `vmstat 1 3` sample taken immediately before the run.

## 0. The rule, declared before running

Copied verbatim from `task-7-brief.md` step 4, and not amended afterwards:

> **PASS** if all five large cells build CLEAN with zero unrouted cuts within
> 120 s wall, belt3 all-products area at most 1.25x 12408, zurl2 at most 1.0x
> 40905, and the default guard is unchanged. **FAIL** otherwise, naming which
> clause, with the prototype's numbers beside it (belt3 1.23x blocks-only,
> zurl2 0.78x) so the router's cost is visible.

The default guard, as the controller declared it: one paired
`scripts/audit.py --budget 30 --json` round against the merge base, requiring
identical CLEAN counts, identical freeform per-cell areas, and a sequence-pair
geomean within ±0.11 %.

## 1. Verdict: **FAIL**

| clause | required | measured | |
| --- | --- | --- | --- |
| coverage | 5/5 cells CLEAN | **0/5**; all five REFUSE, in both rounds | **FAIL** |
| unrouted cuts | zero | **not reached on any gated cell**: at the shipped `STRIP_CAP_DEFAULT = 12` all five refuse before composition, so the router never runs and no cut lane is even offered to it. Vacuously not-violated, and therefore no evidence for PASS either — a cell that never composes cannot demonstrate zero unrouted cuts. The router's actual cost on these URLs is visible only off the shipped default, in the cap sweep (§3.2/§3.3, caps 4/6/8: **8-50** refused lanes) and in the failure-site reading (§4). | **FAIL** (not demonstrated) |
| wall | ≤ 120 s | 26.7-34.1 s — the strategy gives up **early**, it does not time out | PASS |
| belt3 all-products area | ≤ 1.25 × 12408 = 15510 | **no area** (no blueprint) | **FAIL** |
| zurl2 area | ≤ 1.0 × 40905 | **no area** (no blueprint) | **FAIL** |
| default guard | unchanged | fails as literally declared, on all three sub-clauses; **zero regressions**, and each sub-clause is explained in §5 | **FAIL** |

The prototype, beside it: `belt3-depth-pressure-blocks-only` **1.2292x**
(15252 tiles, CLEAN, 0 validator errors) and `zurl2-blocks-only` **0.7780x**
(31824 tiles, CLEAN) — but with **the trunk belts left to the player**, 8-21 of
them per case (`../2026-09-06-exp-hierarchical/README.md`, table at line 190).
That is the difference in what the two produce. v1 hands the same cuts to the
**real** router and demands they be wired, which is the "condition" the
prototype's GO carried — but note that **on the gated runs v1 never got that
far**: at the shipped cap every cell fails at the block solves, before
composition. The comparison with the prototype's areas is therefore a
comparison with a result v1 did not reach by any route, not a like-for-like
area regression. Where v1 *does* reach the router (the cap sweep, §3.2/§3.3)
the router refuses the cuts, which is why that is still lever 1 in §6.

## 2. The five large cells (CLI, two rounds each)

`uv run flab2bp "<url>" --strategy hierarchical --budget 60 --band portable
--candidate-policy <policy>` — `run_large.sh`. One policy per run so each cell
gets the whole budget; `--no-proliferator` is a *filter* over whatever
candidates a URL produces rather than a name, so it does not pin a cell.
Files: `large-{label}-{policy}-r{1,2}.{log,stdout.txt}` and `-load.txt`.

| cell | r1 wall / exit | r2 wall / exit | verdict | how far it got | validator errors |
| --- | --- | --- | --- | --- | --- |
| belt3 / all-products | 32.0 s / 3 | 31.9 s / 3 | REFUSED | 3 blocks unplaced, 5.7 s left over 2 waves | n/a (no placement) |
| belt3 / no-proliferator | 31.2 s / 3 | 31.5 s / 3 | REFUSED | 6 blocks unplaced, 6.2 / 6.1 s over 3 waves | n/a |
| zurl2 / all-products | 33.3 s / 3 | 34.1 s / 3 | REFUSED | r1: 3 blocks unplaced, 4.8 s over 2 waves. **r2: every block placed**, then `lane contract: hydrogen: block 0 supply exhausted; block 7 entry lane 1042 short by 4319/1875 items/s` | n/a |
| mall / all-products | 30.6 s / 3 | 29.9 s / 3 | REFUSED | 11 blocks unplaced, 6.8 / 7.8 s over 6 waves | n/a |
| mall / no-proliferator | 26.7 s / 3 | 27.3 s / 3 | REFUSED | 12 blocks unplaced, 11.1 / 10.7 s over 6 waves | n/a |

`area / best_known`: **not computable on any cell** — nothing was emitted.
`blocks` / `resplits` / `cut_lanes` are `PlacementStats` keys that exist only on
a returned `Placement`, so they are also absent; what stands in for them is the
block count and wave count the refusal text carries, quoted above. Exit 3 is the
CLI's "no layout exists" code, so every run is an honest refusal: no crash, no
handback, no invalid blueprint.

Two things worth stating plainly:

* **The wall is not the problem.** Every cell gives up at roughly half the
  budget, because a round whose per-block share falls under
  `BLOCK_BUDGET_MIN_S = 5.0` is not started at all. Doubling the budget does
  not change the failure class either (§3, the 120 s column).
* **zurl2 r2 is a different, new failure** from r1 on identical inputs: the
  blocks all placed and `contracts.assign_lanes` refused, on a `hydrogen`
  shortfall of 4319 against 1875 items/s. That is a lane-contract accounting
  gap on a byproduct, not a budget outcome, and it is the only appearance of
  `ContractError` in the whole gate.

## 3. Strip-cap sweep (the lever), belt3 and mall

`sweep_strip_cap.py`. The spec is built exactly as `tests/layout/conftest.py`'s
`mall_all_products` fixture builds its own — `canonicalize_dataset`,
`parse_url`, `canonicalize_request`, `_build_candidates_canonical`,
`belt_rules_for_url` — against the named URL, then handed to
`HierarchicalLayout(belt_vertical_construction=…, band_policy=parse("portable"),
workers=16, strip_cap=cap).lay_out(spec, time_budget_s=…)`.

### 3.1 What the cap does to the seed partition (probe, milliseconds)

`probe-belt3-{all-products,no-proliferator}.json`.

| cap | all-products (280 m): blocks / cuts / strips_max / machines_max | no-proliferator (537 m) |
| --- | --- | --- |
| 2 | 11 / 15 / 2 / 61 | 15 / 26 / 2 / 126 |
| 3 | 9 / 12 / 3 / 61 | 11 / 18 / 3 / 126 |
| **4** | 9 / 12 / 3 / 61 | 9 / 12 / 4 / 126 |
| **6** | 5 / 12 / 5 / 145 | 5 / 7 / 5 / 261 |
| **8** | 3 / 7 / 7 / 145 | 5 / 7 / 5 / 261 |
| **12** (shipped) | 3 / 7 / 7 / 145 | **2 / 3 / 12 / 531** |
| 16 | 3 / 7 / 7 / 145 | 2 / 3 / 12 / 531 |

Cap 4 already yields 9 blocks on both policies, so the controller's
"add cap 3 if 4 still leaves a single-block seed" condition never fired and
cap 3 was not built. The cap-12 row confirms Task 6's observation from the other
end: on `no-proliferator` the cap is met exactly at 12, so it never fires and
the seed is one 531-machine block.

### 3.2 What the cap does to a real build (60 s, workers 16, two rounds)

`sweep-{belt3,mall}-{policy}[-r2].json` / `.log`. "Stage" is how far the build
got: **unplaced** = a round could not be funded and blocks were never attempted;
**composed** = every block placed, composed and ported, and the real router then
refused N cut lanes.

| cell | cap 4 | cap 6 | cap 8 | cap 12 (shipped) |
| --- | --- | --- | --- | --- |
| belt3 / all-products | composed, **15** lanes (r1 40.2 s, r2 44.4 s) | composed, 18 lanes (r1 43.9 s, r2 47.2 s) | unplaced, 3 blocks | unplaced, 3 blocks |
| belt3 / no-proliferator | composed, **15** lanes (40.9 / 42.2 s) | composed, 50 lanes (53.2 / 61.1 s) | composed, 50 lanes (51.6 / 61.9 s) | unplaced, 6 blocks |
| mall / all-products | **unplaced in 0.1 s**, 18 blocks, 0 solves attempted | **unplaced in 0.1 s**, 18 blocks | unplaced, 14 blocks (27.6 s) | unplaced, 11 blocks (28.3 s) |
| mall / no-proliferator | **unplaced in 0.1 s**, 21 blocks | **unplaced in 0.1 s**, 17 blocks | unplaced, 14 blocks (26.6 s) | unplaced, 14 blocks (25.3 s) |

Unrouted-lane classes (r2 run, `unrouted` field, full text in `verdict_full`):

| cell | cap | classes |
| --- | --- | --- |
| belt3 / all-products | 4 | `DYNAMIC_ACCESS` 9, `SEALED_POCKET` 3, `COMMIT_LINK` 3 |
| belt3 / all-products | 6 | `DYNAMIC_ACCESS` 10, `SEALED_POCKET` 4, `COMMIT_LINK` 4 |
| belt3 / no-proliferator | 4 | `DYNAMIC_ACCESS` 15 |
| belt3 / no-proliferator | 6 | `DYNAMIC_ACCESS` 18, `COMMIT_LINK` 14, `BUDGET` 11, `SEALED_POCKET` 7 |

### 3.3 The 120 s column, and the workers column

`sweep-belt3-{policy}-b120.json` (budget 120, caps 4 and 6) and
`sweep-w64-*.json` (budget 60, cap 6, `workers=64`, i.e. a 16-wide pool):

| cell | cap | 120 s | workers 64 at 60 s |
| --- | --- | --- | --- |
| belt3 / all-products | 4 | 57.9 s, 15 lanes: `DYNAMIC_ACCESS` 9, `SEALED_POCKET` 3, `COMMIT_LINK` 3 | — |
| belt3 / all-products | 6 | 45.3 s, **8** lanes: `DYNAMIC_ACCESS` 8 | 48.2 s, 18 lanes |
| belt3 / no-proliferator | 4 | 50.8 s, 15 lanes: `DYNAMIC_ACCESS` 15 | — |
| belt3 / no-proliferator | 6 | 74.1 s, 15 lanes: `DYNAMIC_ACCESS` 15 | 62.6 s, 20 lanes |
| mall / all-products | 6 | — | 22.7 s, 27 blocks unplaced over 4 waves |
| mall / no-proliferator | 6 | — | 24.7 s, 28 blocks unplaced over 4 waves |

**Doubling the budget does not change the failure class**: belt3 still composes
and the router still refuses the same `DYNAMIC_ACCESS`-dominated set. On the
mall, quadrupling the pool width converts the 0.1 s instant refusal into a
funded first round — every seed block placed — and then the *re-cut* round is
unfunded again, at 27-28 blocks. Both dials move the wall around; neither
reaches a blueprint.

### 3.4 The cap decision: **STRIP_CAP_DEFAULT stays at 12**

The brief's pick rule is "the cap with the smallest belt3 area that still builds
both malls". **It selects nothing, because no cap produces a belt3 area and no
cap builds either mall.** Nor is there a dominance order to fall back on:

* cap **4** is the best cap on belt3 (composes on both policies, both rounds,
  with the fewest unrouted lanes: 15 and 15) and the **worst** on the mall — it
  refuses in 0.1 s having attempted zero block solves;
* cap **12** is the only one of the four that composes on *neither* belt3
  policy, and is at best marginally ahead of cap 8 on the mall (11 vs 14
  unplaced on `all-products`, equal on `no-proliferator`).

The reason cap 4 destroys the mall is not partition quality, it is the funding
rule: a round's jobs are `blocks × arms`, run `(workers or 16) // 4 = 4` at a
time, and the round's remaining wall is divided by the resulting **wave count**.
At 60 s the reserve is `min(40, max(10, 24)) = 24 s`, so 18 blocks × 2 arms = 36
jobs = 9 waves = `35.9 / 9 = 4.0 s` per block, under the 5 s floor, and the
round is skipped entirely. **A finer partition — the thing that makes each block
easy — is what starves the round.** Until that is fixed, a cap change trades one
URL for another, so `STRIP_CAP_DEFAULT` is left at 12, no code was changed for
this gate, and the sweep should be repeated at cap 4 once the funding rule is
fixed (§6, lever 2).

## 4. Reading the refusals: where the strategy actually dies

Three distinct failure sites are now visible in the evidence, in the order a
build meets them:

1. **Unfunded round** — the round's per-block share is under
   `BLOCK_BUDGET_MIN_S`. All five CLI cells at the shipped cap, and the whole
   mall column at every cap. Cause: the wave divisor above.
2. **Lane contract** — every block placed, and `contracts.assign_lanes` finds a
   cut's supply short. Once, on `zurl2/all-products` r2, on `hydrogen`
   (4319 vs 1875 items/s).
3. **Unrouted cuts** — every block placed, composed and ported, and
   `_route_all` refuses the cut lanes. belt3 at caps 4/6/8, every round, at both
   60 s and 120 s. Dominated by `DYNAMIC_ACCESS`, with `SEALED_POCKET`,
   `COMMIT_LINK` and (only when the interface gets large) `BUDGET` behind it.

Site 3 is the one the design predicted would be the cost, and it is now the
measured cost. `BUDGET` — the class that dominated Task 6's review-round-2
measurement, which is what motivated `settlement_reserve_s` — has largely gone;
what is left is geometric. The cut lanes are being asked to reach ports on
ground that the composer packed without reserving anything for them.

## 5. Default-unchanged guard

One paired round, `scripts/audit.py --budget 30 --json`, merge base first
(throwaway worktree `.claude/worktrees/gate-base-d57bc7cd`, `uv sync`, kernel
import check reported `backend cython` on both trees; worktree removed
afterwards), then this branch. Never two audits at once.

Files: `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`, their
`-load.txt`, `compare-round1.txt` (`scripts/audit_compare.py`),
`judge-round1.txt` (`judge.py`, copied from `../2026-09-06-speedups-2-batch3/`).

```
status counts       baseline  candidate
  CLEAN                   71         72
  REFUSED                  1          0
CLEAN in baseline, not CLEAN in candidate: 0     <-- no regression
INVALID/CRASH in either: 0
gmean area ratio  all 0.99906 (-0.09 %)  freeform 0.99939 (-0.06 %)  seq-pair 0.99873 (-0.13 %)
cells whose area moved at all: 4 of 71
wall-safety: candidate max overshoot 0.000 s vs baseline 0.000 s -> OK
total build wall: baseline 1418.5 s, candidate 1415.1 s
```

`audit_compare.py` prints FAIL, on `p95 wall 31.9s exceeds 30.0s`; the baseline's
own p95 is 31.3 s, so that is the script's known default (budget with no grace),
not a candidate effect. `judge.py` is the authority here, as in batch 3.

**As literally declared, the guard fails on all three sub-clauses.** Each one was
run down rather than waved through:

**(a) CLEAN counts 71 vs 72.** The one differing cell is `sequence-pair
universe-matrix [1/all-products]`, REFUSED on the **baseline** and CLEAN on the
candidate. `../2026-09-06-speedups-2-batch3/gate.md` lines 8-9 already
characterises that exact cell as **a flake**: it "refuses once in three
dedicated re-runs on the **baseline** tree and never in three on the candidate".
That is the same side it refuses on here, so this round reproduces batch 3's
finding rather than contradicting it, and it is not a change introduced by this
branch. The clause that matters is intact: **zero cells go CLEAN → not CLEAN.**

**(b) freeform per-cell areas are not identical.** Four cells moved. Each was
re-run once more on **both** trees (`moved-{baseline,candidate}-r2.{jsonl,txt}`,
`scripts/audit.py --budget 30 --only information-matrix,super-magnetic-ring,magnetic-coil`):

| cell | base r1 | base r2 | cand r1 | cand r2 | reading |
| --- | --- | --- | --- | --- | --- |
| freeform `information-matrix [1/all-products]` | 5159 | **4760** | 4760 | 4760 | baseline is the unstable side; candidate stable at the baseline's own r2 value |
| freeform `super-magnetic-ring [2/output-products]` | 1980 | **2120** | 2052 | 2052 | candidate sits *inside* the baseline's own spread |
| freeform `super-magnetic-ring [0/no-proliferator]` | 2183 | 2183 | 2233 | **2088** | candidate is the unstable side; baseline value lies inside its spread |
| sequence-pair `magnetic-coil [2/output-products]` | 299 | 299 | **286** | **286** | **reproducible on both sides: a real change, 4.3 % SMALLER** |

So three of the four are run-to-run noise on a time-bounded search, present on
one tree or the other, and the "identical freeform areas" clause is not
achievable on these cells at a 30 s budget regardless of the branch.

**(c) sequence-pair geomean -0.13 %, outside ±0.11 %.** It is that one cell and
nothing else: `286/299 = 0.9565`, and `0.9565 ** (1/35) = 0.99873`, which is the
printed geomean to five places. The branch's only sequence-pair change is
`caf893f3` (Task 3): at the **seed** stage-boundary site, a merge that a sibling
restart cannot follow now abandons the collapse instead of raising
`ValueError("stage-boundary transform must rebuild every restart identically")`
— the LNS site has carried that guard since merges existed. `magnetic-coil/
output-products` is a corpus cell where that site fires, and the changed search
path lands 13 tiles smaller. **The exact path inside the solver was not traced**;
what is claimed is the correlation plus the fact that this is the branch's only
sequence-pair edit, reproducible on both sides of two rounds.

Task 1 (`ee4ead43`) does change shared freeform code — the power broad phase now
narrows to the candidate's own cleanup-survivor rectangle on every build, not
only on the specs that refused — so freeform areas moving would have been an
expected finding; the measurement says the moves seen here are noise instead.

**Summary of the guard: FAILS AS DECLARED, with all three sub-clauses explained
and none of them a regression.** The substantive result is 0 of 72 cells CLEAN →
not CLEAN, 0 INVALID, 0 CRASH, whole-corpus area within 0.09 %, and one
reproducible 4.3 % improvement.

## 6. The next three levers, from the measurement

1. **Reserve the trunk before packing, not after** (design §4 E's "bus corridor
   reserved before block placement", which v1 deliberately does not do —
   task-7-brief self-review, "Not covered, deliberately"). Evidence: §3.2/§3.3 —
   belt3 composes at caps 4/6/8 every time and the router refuses 8-50 lanes,
   dominated by `DYNAMIC_ACCESS`, and **doubling the budget to 120 s does not
   change the class**. This is not the router running short of wall, it is the
   router being handed a canvas with nowhere to run. Highest value: it is the
   only lever that attacks the clause the gate actually fails on.
2. **Fund a round per block, not per wave.** Evidence: §3.4 — 18 blocks × 2 arms
   at pool width 4 is 9 waves, `35.9 / 9 = 4.0 s` is under the 5 s floor, and the
   mall refuses in **0.1 s having attempted nothing**, at the caps that are best
   for belt3. The pool width is `(workers or 16) // 4 = 4` on a 128-core box.
   Either widen the pool from the real core count, or fund a block from the
   round's wall directly and let the waves take as long as they take under the
   parent deadline. Cheap, and it unblocks the cap sweep (§3.4) that is currently
   undecidable.
3. **Close the lane contract on byproducts.** Evidence: §2 — `zurl2/all-products`
   r2, `hydrogen: block 0 supply exhausted; block 7 entry lane 1042 short by
   4319/1875 items/s`, reached only after every block placed. `contracts.py`
   matches a cut's out-lanes to in-lanes by count and rate and refuses a
   shortfall; the prototype's own backlog item asked for merge/split there and
   v1 refuses instead. It is the deepest a large cell has got, so it is the next
   wall after levers 1 and 2.

Below those, and cheaper than all three: `partition.strip_count` counts
**logical** strip plans, which undercounts what freeform actually packs (Task 6:
belt3's 129-machine block is 7 logical strips and 24 packed in the prototype), so
the cap is calibrated against the wrong quantity in the first place.

## 7. Backlog: adaptive memory for the block solver

Three ideas the user raised, recorded with the evidence in this gate that
motivates each. None is implemented; none was measured.

* **A within-build no-good keyed on block shape.** The re-cut loop re-derives a
  partition every round and re-offers blocks to both arms, and
  `split_block(attempt=k)` deliberately produces overlapping shapes (halve,
  third, halve every unit, isolate each recipe). Motivating evidence: the mall
  at `workers=64` (§3.3) placed every seed block and then arrived at the re-cut
  round with **27-28** blocks; the CLI cells (§2) name 3-12 blocks "not
  attempted" per refusal. A block shape that a placer already refused at a given
  budget is being re-offered, and the refusal is the cheapest thing in the build
  to remember. Keying is the open question: the recipe multiset plus per-recipe
  machine counts is the obvious key, and it must carry the budget it refused at,
  since Task 6's own note is that block size interacts with the placers
  non-monotonically (six machines refused where three plus three placed).
* **A cross-build solved-block cache.** The same blocks recur across candidate
  policies and across runs: belt3's `all-products` and `no-proliferator` seeds
  share recipes, and `output-products` partitions **identically** to
  `no-proliferator` (Task 6 fix report 2). Across the ten CLI runs in §2, and the
  ~30 sweep builds in §3, the same one-recipe blocks (`gear`, `electric-motor`,
  `iron-ingot`, `magnet`) were solved from scratch every time. A block is a
  self-contained `BuildSpec` with a deterministic sub-spec derivation, so it is
  cacheable on that spec's own hash. This is also the one lever that would make
  the *second* run of a URL fast, which is what an interactive user sees.
  Related work already planned: "background compound block cache" (`42c9e0e`).
* **A strip cap that moves with outcomes.** §3.4 is the direct argument: no fixed
  cap is right for both belt3 and the mall, cap 4 is best for one and worst for
  the other, and the sweep is undecidable as a *constant*. What the measurements
  suggest instead is a cap that starts where the funding rule can afford it
  (blocks × arms ≤ pool width × affordable waves) and tightens only on the blocks
  that actually refuse — which is what `split_block` already does per block, one
  level down. Sequencing note: this is worth nothing until lever 2 is fixed,
  because today the feedback signal it would adapt on ("the round was not
  funded") is produced by the cap being *small*, not by the blocks being hard.

## 8. Files

* `gate.md` (this file), `judge.py` (copied from `../2026-09-06-speedups-2-batch3/`)
* `run_large.sh`, `large-{belt3,zurl2,mall}-{policy}-r{1,2}.{log,stdout.txt,-load.txt}`
* `sweep_strip_cap.py`; `probe-belt3-{policy}.json`
* per-run JSON: `sweep-belt3-{policy}.json` (round 1),
  `sweep-belt3-{policy}-r2.json` (round 2, and the only rounds carrying the
  `unrouted` / `verdict_full` fields, which the script gained between rounds),
  `sweep-belt3-{policy}-b120.json`, `sweep-mall-{policy}.json`,
  `sweep-w64-{url}-{policy}.json`
* their stdout: `sweep-belt3-{policy}.log`, `sweep-belt3-r2.log`,
  `sweep-belt3-b120.log`, `sweep-mall.log`, `sweep-w64.log`; and the loads
  `sweep-belt3-{policy}-load.txt`, `sweep-belt3-b120-load.txt`,
  `sweep-belt3-r2-load.txt`, `sweep-mall-load.txt`, `sweep-workers-load.txt`
* `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`,
  `compare-round1.txt`, `judge-round1.txt`, their `-load.txt`
* `moved-{baseline,candidate}-r2.{jsonl,txt}`, `moved-cells-load.txt`

No blueprint file is present: every run refused, so `-o` was never written.
