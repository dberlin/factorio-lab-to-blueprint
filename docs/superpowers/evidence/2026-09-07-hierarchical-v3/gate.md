# Gate: hierarchical v3 on the large URLs

Branch `hierarchical-v3` at `bf081859` (the code HEAD every measurement below
is taken at). Merge base: master `1ce8a0d3`. Worktree
`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v3`.

Box: 128 cores, never idle, load is I/O wait. Every timed step has a
`-load.txt` beside it with `uptime` and one `vmstat 1 3` sample taken
immediately before the run. At most one layout build ran at a time from this
plan, and no two audits ever ran at once (`ps -eo args | grep -cE 'scripts/audit\.py'`
checked before each audit invocation; note that a plain `pgrep -f audit.py`
matches its OWN command line here and always returns a hit).

This is the successor to `../2026-09-07-hierarchical-v2/gate.md`, which it
supersedes. It gates seven tasks: Task 1 the stats carried into every refusal
and printed by the CLI (`d89b78e3`), Task 2 bounded and funded re-cut rounds
(`0bf58d3d`, `d5f2b4ad`), Task 3 one-arm dispatch from a routing-difficulty
feature key (`94c4edaf`, `69031212`, `f18502e7`), Task 4 the per-demand
reachability goal (`900afa1e`, `97ea65c5`, `ea65ab15`, `8362b22d`), Task 5 the
trunk-partner doorstep (`e91886fb`, `b9473715`, `a2ecd5b2`), Task 6 the
rung-by-rung oracle measurement (`6457e215`, `3067adfa`), Task 7 the corridor
spike killed at Step 0 (`bf081859`).

## 0. The rule, declared before the results

Written and committed before a single cell was run, and not amended
afterwards. Copied verbatim from `task-8-brief.md` Step 1:

> **PASS** if all four hold: (a) every cell that COMPOSES emits a blueprint
> whose `validate.certify` report has zero errors; (b) both malls compose —
> every block placed, the build reaching `compose`; (c) titanium-glass builds
> at `--budget 15`, emitting a blueprint; (d) the default-unchanged corpus
> guard has zero regressions — no cell CLEAN on the merge base and not CLEAN on
> the branch, 0 INVALID, 0 CRASH.
> **FAIL** otherwise, naming the clause AND the lever that failed (A
> funding/dispatch, B the oracle, C the corridor), and ranking the next three
> levers with the file:line and the number behind each, as v2's §6 did.

**The area clauses v2 carried are reported but NOT gating this time.** v2's
rule required belt3 ≤ 1.25 x 12408, zurl2 ≤ 1.0 x 40905 and titanium-glass
≤ 1.25 x 5727, and demonstrated none of them, because no cell emitted a
blueprint: all three came back "not demonstrated" rather than passed or
violated. A coverage gate that also fails on area cannot say which of the two
it failed on. So this gate gates coverage and time, and **reports
`area / best_known` for every cell that emits**, with no threshold attached.

Best-known dense areas for that column, as the controller supplied them
(`constraints.md`): belt3 all-products **12408**, zurl2 all-products **40905**,
titanium-glass all-products **5727** (sequence-pair, `best` at 30 s). The mall
has no best-known area.

The eight cells, the same as v2's, one candidate policy per run so each cell
gets the whole budget, `--band portable`, `-o`, and **no `--workers`** so the
strategy sees the `None` the CLI passes by default:

| cell | policy | budget |
| --- | --- | --- |
| belt3 | all-products | 60 |
| belt3 | no-proliferator | 60 |
| zurl2 | all-products | 60 |
| mall | all-products | 60 |
| mall | no-proliferator | 60 |
| titanium-glass | all-products | 60 |
| titanium-glass | all-products | 15 |
| belt3 | all-products | 15 |

Each is run TWICE. The corpus guard is one paired
`scripts/audit.py --budget 30 --json` round: the BASELINE half on the detached
merge base, the CANDIDATE half on this branch, compared with
`scripts/audit_compare.py`. **`audit.py` prints `NOT CLEAN` on any refusal, so
what is read is the CLEAN COUNTS and the NAMED DIFFERING CELLS, never the
banner.**

## 1. Verdict: **FAIL**, on clauses (a), (b) and (c) — levers A and B both

**0 of 8 cells emit a blueprint.** Exit 3 on all sixteen runs; no crash, no
handback, no invalid blueprint, and no `*.blueprint.txt` exists in this
directory.

| clause | required | measured | |
| --- | --- | --- | --- |
| (a) every cell that COMPOSES emits a blueprint with zero `certify` errors | a blueprint per composing cell | **5 of 8 cells compose** (belt3 both policies, zurl2, titanium-glass at both budgets). **None emits.** Four die at the router with 18 / 8 / 70 (r2 73) / 6 (r2 2) unrouted cuts; the fifth, `titanium-glass/all-products` at 60 s, wires **every one of its 26 cut lanes** and then fails `certify` with **4 `power.coverage` findings** (§2.3) | **FAIL** |
| (b) both malls compose — every block placed, the build reaching `compose` | every block placed | **neither composes.** `mall/all-products` refuses with **9 blocks never placed**, `mall/no-proliferator` with **31**, identical in both rounds. `cut_lanes=0`, `port_demands=0`, `compose_gap=0` on both: composition is never entered | **FAIL** |
| (c) titanium-glass builds at `--budget 15`, emitting a blueprint | a blueprint | **REFUSED**, 6 unrouted cuts (r1: `COMMIT_LINK` 3, `BUDGET` 2, `DYNAMIC_ACCESS` 1) and 2 (r2: `SEALED_POCKET` 1, `BUDGET` 1), with `reservation_missing=0` and `reservation_degraded=1` on both | **FAIL** |
| (d) corpus guard: zero regressions, 0 INVALID, 0 CRASH | no cell CLEAN on base and not CLEAN on branch | *see §4* | *see §4* |
| — (reported, not gating) belt3 / zurl2 / titanium-glass area | `area / best_known` | **not computable on any cell**: nothing was emitted, so no area exists | not demonstrated |
| — (reported, not gating) wall within budget + `RACE_COMPLETION_GRACE_S = 6.0` | ≤ 66.0 s and ≤ 21.0 s | the six 60 s cells ran **24.68–60.91 s** in process (largest: zurl2 r2 at 60.91, inside 66.0); the two 15 s cells ran **9.46–15.59 s**, inside 21.0 | PASS |

### The clause-to-lever attribution the rule asks for

* **Clause (b) is LEVER A (funding / dispatch).** It is the clause Tasks 2 and
  3 exist to close, and it is not closed.
* **Clause (c) is LEVER B (the oracle).** The brief's own attribution rule is
  "B if the cells compose and the router still refuses with
  `reservation_missing == 0`", and that is exactly this cell: it composes, it
  reports `reservation_missing=0`, and the router refuses anyway.
* **Clause (a) fails on BOTH, plus a third site neither lever names.** Four of
  the five composing cells are lever B again. The fifth is new (§2.3).
* **LEVER C did not run and therefore did not fail.** Task 6 measured its two
  clauses and Task 7 recorded `LEVER C: SKIPPED` without a line of
  implementation (`corridor-spike.md`). A skipped lever is not a failed one,
  and §5 does not charge it.

### What did change, and it is not nothing

Three things moved that no previous gate could show, and all three are in the
measurement rather than in a claim:

1. **Every block is now attempted on every cell.** `blocks_unattempted = 0` on
   **all eight cells in both rounds**, and the string `not attempted` appears
   **zero times** in all sixteen refusals. v2 refused both malls with 22 and 45
   blocks that never reached a placer. Every block named in a v3 refusal
   carries a real placer verdict. That is Lever A's deliverable, delivered —
   and it is not enough to compose either mall.
2. **The failure on the malls has moved from the funding rule to the block
   placers.** v2's mall refusals named the funding arithmetic; v3's name
   per-block placer verdicts (§2.2).
3. **One cell reached `validate.certify` with every cut lane wired.** No
   hierarchical build in v1, v2 or v3 had ever got past `_route_all` on a
   composed canvas before. `titanium-glass/all-products` at 60 s now does, in
   both rounds, and dies on four power findings (§2.3). That is the shortest
   distance to a first blueprint this project has measured.

## 2. The eight large cells (CLI, two rounds each)

Invocation shape, per cell — one candidate policy per run so each cell gets the
whole budget; `--band portable`; `-o`; and **no `--workers`**, so the strategy
sees the `None` the CLI passes by default:

```
uv run python run_cell.py <stem>.json -- "<url>" --strategy hierarchical \
    --budget <60|15> --band portable --candidate-policy <policy> -o <stem>.blueprint.txt
```

`run_cell.py` **monkeypatches nothing**. Task 1 carries the strategy's whole
`PlacementStats` into every `NoValidLayout` attempt failure and `cli.main`
prints it on the refusal path as `  stats <strategy>/<candidate>: key=value ...`
on stderr; the harness tees stderr and parses that line. It therefore replaces
all four of v2's spies: `_solve_round` (which v2 wrapped for `nogood_skips`,
unreachable through `PlacementStats` because that key was written only on a
success path), `allocate_cuts` (`player_fed`), `pack_with_access` (`gap`), and
`pipeline.build` (area / buildings / validator errors, now read from the CLI's
own `_report` lines). Its module docstring says so and states the one limit it
does not paper over — **the stats line exists only on the refusal path** — so a
cell that emitted would report an area and no stats. No cell emitted.

Files: `large-{label}-{policy}-b{budget}-r{1,2}.{json,log,stdout.txt}` and
`-load.txt`.

| cell | budget | r1 wall (proc / shell) | r2 wall (proc / shell) | verdict | how far it got | area | area / best_known |
| --- | --- | --- | --- | --- | --- | --- | --- |
| belt3 / all-products | 60 | 55.92 / 57.6 s | 55.74 / 57.3 s | REFUSED (exit 3) | composed; router refused **18** cuts | — | n/a |
| belt3 / no-proliferator | 60 | 35.23 / 36.9 s | 36.78 / 38.3 s | REFUSED | composed; **8** cuts | — | n/a |
| zurl2 / all-products | 60 | 60.71 / 62.3 s | 60.91 / 62.2 s | REFUSED | composed; **70** cuts (r2 **73**), 69 of them (r2 71) `BUDGET` | — | n/a |
| mall / all-products | 60 | 37.00 / 38.7 s | 36.83 / 38.1 s | REFUSED | **9 blocks never placed**, all 9 with a placer verdict; never composed | — | n/a |
| mall / no-proliferator | 60 | 28.91 / 30.1 s | 29.24 / 30.8 s | REFUSED | **31 blocks never placed**, all 31 `deadline exhausted`; never composed | — | n/a |
| titanium-glass / all-products | 60 | 24.68 / 25.9 s | 25.08 / 26.7 s | REFUSED | composed; **0** unrouted cuts; **`certify` refused: 4 `power.coverage`** | — | n/a |
| titanium-glass / all-products | 15 | 15.59 / 17.4 s | 15.26 / 16.9 s | REFUSED | composed; **6** cuts (r2 **2**) | — | n/a |
| belt3 / all-products | 15 | 11.09 / 12.7 s | 9.46 / 10.6 s | REFUSED | **2 blocks never placed**, both `deadline exhausted`; never composed | — | n/a |

"proc" is `run_cell.py`'s own `perf_counter` around `cli.main`; "shell" is the
`date`-to-`date` wall in `run_large.sh` and includes interpreter and dataset
start-up. Round 1 is quoted with round 2 in parentheses wherever the two
differ. **`area / best_known` is not computable on any cell** — nothing was
emitted. **Validator errors by class are `n/a` on seven cells and NOT by
omission**: `pipeline.build` raises `NoValidLayout` on all sixteen runs, so
there is no returned `Build` to convict. The eighth, `titanium-glass` at 60 s,
did reach `certify`, and §2.3 reports its class breakdown in full.

### 2.1 The stats the CLI now prints

Every number below is parsed from the `  stats ` line in the `-r{1,2}.log`
files and stored in the `-r{1,2}.json` sidecars. **Round 1 is quoted with round
2 in parentheses wherever they differ**; where nothing is in parentheses, the
two rounds are identical.

| cell (b60 unless noted) | blocks | unattempted | recut rounds | arm dispatch f / sp / both | cut lanes | player-fed | gap | port demands | reservation `degraded` | reservation `missing` | nogood skips | unrouted cuts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| belt3 / all-products | 11 | **0** | 2 | 7 / 5 / 2 | 89 | 0 | **2** | 102 | **1** | **0** | 3 (2) | **18** |
| belt3 / no-proliferator | 14 | **0** | 0 | 0 / 14 / 0 | 147 | 0 | **2** | 183 | **1** | **0** | 2 | **8** |
| zurl2 / all-products | 17 | **0** | 0 | 11 / 6 / 0 | 127 | **1** | **2** | 144 | **1** | **0** | 0 | **70 (73)** |
| mall / all-products | 39 | **0** | 2 | 44 / 6 / 13 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 |
| mall / no-proliferator | 54 | **0** | 2 | 0 / 73 / 19 | 0 | 0 | 0 | 0 | 0 | 0 | 48 | 0 |
| titanium-glass / all-products | 6 | **0** | 0 | 5 / 1 / 0 | 26 | 0 | **2** | 31 | **1** | **0** | 0 | **0** |
| titanium-glass / all-products b15 | 6 | **0** | 0 | 5 / 1 / 0 | 26 | 0 | **2** | 31 | **1** | **0** | 0 | **6 (2)** |
| belt3 / all-products b15 | 9 | **0** | 0 | 4 / 5 / 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Unrouted classes, r1 / r2 (`CL` = `COMMIT_LINK`, `DA` = `DYNAMIC_ACCESS`,
`SP` = `SEALED_POCKET`), counted from the refusal text and agreeing with
`unrouted_cuts` on every cell:

| cell | r1 | r2 |
| --- | --- | --- |
| belt3 / all-products | `DA` 8, `SP` 5, `CL` 5 | identical |
| belt3 / no-proliferator | `DA` 5, `CL` 2, `SP` 1 | identical |
| zurl2 / all-products | **`BUDGET` 69**, `DA` 1 | **`BUDGET` 71**, `DA` 2 |
| titanium-glass b15 | `CL` 3, `BUDGET` 2, `DA` 1 | `SP` 1, `BUDGET` 1 |

Five provenance notes, because a gate that does not say where a number is
weakest is not a gate:

* **`blocks` is the GROWN count, not the seed partition.** On the five cells
  with `recut_rounds = 0` the two coincide, so belt3/no-proliferator's 14,
  zurl2's 17, titanium-glass's 6 and belt3-at-15's 9 ARE seed counts measured
  here. On the three with `recut_rounds = 2` (belt3/all-products 11, and both
  malls at 39 and 54) they are not, and **this gate ran no partition probe**,
  so it does not state a v3 seed count for them. v2 measured those seeds at 9,
  19 and 24 by probe (`../2026-09-07-hierarchical-v2/gate.md` §2.1); those are
  v2's numbers, cited as v2's, and `partition` is unchanged on this branch.
* **`compose_gap = 0` and `port_demands = 0` are a SENTINEL, not a measurement**
  — they are what the refusal path reports when composition was never entered.
  The three cells carrying them are exactly the three that never composed.
  (Task 5's review recorded this as an undocumented sentinel and deferred it.)
* **`reservation_degraded = 1` on all five composing cells, in both rounds.**
  Ten runs out of ten. It is a ladder TOTAL and can only over-count, so the
  honest reading of the pair `degraded = 1, missing = 0` is the one
  `base.py`'s own docstring gives: "some rung was degraded and the committed
  one may or may not have been" — NOT "every port is satisfiable". §3 and §5
  take this apart; it is the single most load-bearing number in this gate.
* **`arm_dispatch_*` counts blocks per ROUND**, at the funding site, so on a
  multi-round cell the columns sum to more than `blocks` (mall/no-proliferator:
  0 + 73 + 19 = 92 over three rounds against 54 blocks). On the five
  single-round cells they sum exactly to `blocks`.
* **`nogood_skips` and `player_fed` are now shipped `PlacementStats` keys read
  off the CLI**, not harness spies. v2 had to report both from monkeypatches
  and label them as such. zurl2's single player-fed pair persists from v2.

### 2.2 What the refusals say, verbatim

The three shapes, quoted from the `-r1.log` files:

```
mall / all-products r1:
  hierarchical/all-products: 9 block(s) never placed, out of re-cut round(s)
  after 2 of 2 the 36.0s round wall allows: block 20 (steel, titanium-alloy):
  REFUSED: no packing of 3 strips could be wired at any candidate height; every
  pack the sweep produced left nets unrouted. That is a PACKER defect -- it is
  producing packs its own router cannot wire -- and it is reported rather than
  papered over with a looser packing; ...

belt3 / all-products r1:
  hierarchical/all-products: unrouted cut(s): electric-motor: block 8 -> block 7:
  DYNAMIC_ACCESS; gear: block 5 -> block 8: DYNAMIC_ACCESS; gear: block 5 ->
  block 8: SEALED_POCKET; iron-ingot: block 1 -> block 8: SEALED_POCKET; ...

titanium-glass / all-products b60 r1 AND r2, bit-identical:
  hierarchical/all-products: composed placement failed validation:
  power.coverage: building 5952 has tile (63,3) outside every tower's supply
  radius; it would sit unpowered; power.coverage: building 5953 has tile (63,3)
  outside every tower's supply radius; it would sit unpowered; power.coverage:
  building 5959 has tile (62,1) outside every tower's supply radius; it would
  sit unpowered.
```

**Neither mall's refusal names the funding rule any more.** The clause it now
fails is that the placers refuse the blocks, not that the rounds were unfunded:

* `mall/all-products`, both rounds: 9 blocks, of which **7 carry the
  `no packing of N strips could be wired at any candidate height ... That is a
  PACKER defect` message** (`freeform.py:20015`), one carries
  `no pack was ever routed: 1 lane head could not obtain the belt approach`
  (`freeform.py:19519`), and one a per-block deadline (`the 9.70933s deadline
  passed with no completed packing of 5 strips`, r2).
* `mall/no-proliferator`, both rounds: **31 blocks, all 31 `REFUSED: deadline
  exhausted before finding an exact layout`**, with `exact validation failures:
  geom.collide` and no band accepting the final placement.
* `belt3/all-products` at 15 s: 2 blocks, both `deadline exhausted`. Note the
  round accounting is `after 0 of 0 the 9.0s round wall allows` — that is Task
  2's `allowed_recut_rounds(9.0) == 0` firing exactly as designed, giving the
  seed round the whole wall on the web-UI path.

### 2.3 The one cell that wired every cut, and what convicted it

`titanium-glass / all-products` at 60 s is the first hierarchical build in
three gates to compose, route **all 26 of its cut lanes** and reach
`validate.certify` (`strategy.py:787`). It then refuses. Because the CLI
truncates to `report.errors[:3]` and names buildings by index, one extra build
was run through `certify_probe.py` — a read-only wrapper on `validate.certify`,
same argv, `certify-titanium-glass-all-products.{json,log}` and its
`-load.txt`. It reproduces the gate cell's refusal exactly (the same indices
5952 / 5953 / 5959 at the same tiles), and reports:

| what | measured |
| --- | --- |
| `errors_by_check` | **`power.coverage` alone** — no geometry, flow, belt or band finding at all |
| findings | **4**, not the 3 the CLI printed |
| what they are | all four are **DSP item 2020 = `SPLITTER_ID`** (`dsp/catalog.py:219`), 1×1, at tiles **(63,3)** and **(62,1)**, each at **z = 0 and z = 2** — two vertical splitter pairs |
| the canvas | 5993 buildings, area **11297**, **80 splitters**, **61 Tesla towers** (item 2201) |
| coverage | **76 of 80 splitters are covered; 4 are not** |

So the composed canvas is not unpowered — it is 95 % powered, and four
cut-lane splitters stand on ground that none of the 61 towers each block
brought for its own footprint reaches. §5 lever 2 is this.

## 3. Where the strategy dies, and where this gate agrees or disagrees with each implementer

Failure sites, in the order a build meets them, over sixteen runs:

1. **Block placer refuses** — both malls (9 and 31 blocks) and
   `belt3/all-products` at 15 s (2 blocks). **3 of 8 cells.** In v2 this site
   was "the round was never funded"; it is now real placer verdicts.
2. **Unfunded round** — **zero occurrences.** `blocks_unattempted = 0`
   everywhere; `not attempted` appears in none of the sixteen refusals.
3. **Lane contract** (`contracts.assign_lanes`) — **zero occurrences**, as in
   v2. One player-fed pair on zurl2 and no `ContractError` anywhere.
4. **Unrouted cuts** — belt3 at both policies, zurl2, titanium-glass at 15 s.
   **4 of 8 cells.** belt3's are entirely geometric; zurl2's are 69–71/70–73
   `BUDGET`, i.e. clock, not ground.
5. **Certification** — `titanium-glass/all-products` at 60 s. **1 of 8 cells,
   and new in this gate** (§2.3).

Per task, citing each implementer's own measurement as theirs:

* **Task 1 (stats into every refusal, `d89b78e3`)** measured, on
  `mall/all-products`, the line `blocks=52 blocks_unattempted=22 ... nogood_skips=36
  recut_rounds=0` and noted that v2's harness spy had read 22 unattempted for
  the same cell, so the CLI surface reproduced it. **This gate agrees, and is
  the proof the surface works**: every number in §2.1 came off that line with
  no monkeypatching, including two — `nogood_skips` and `player_fed` — that v2
  could only obtain by wrapping production functions, and one,
  `reservation_degraded`, that did not exist before Task 5. Where the gate must
  qualify it: **the line is printed on the refusal path only**, so the one
  quantity a PASSING gate would most want (the stats behind an emitted
  blueprint) is still not printed by any shipped surface.
* **Task 2 (bounded, funded re-cut rounds, `0bf58d3d`/`d5f2b4ad`)** measured
  both malls going from `blocks_unattempted` 22 and 45 to **0**, and
  titanium-glass at 15 s keeping `blocks=6 blocks_unattempted=0
  recut_rounds=0` with `allowed_recut_rounds(~8.7) == 0` firing. **This gate
  agrees on both, twice each.** `blocks_unattempted = 0` on all eight cells in
  both rounds, and belt3 at 15 s shows the same `allowed = 0` branch in its
  refusal text (`after 0 of 0 the 9.0s round wall allows`). This is the
  clearest single win on the branch. It does not close clause (b): the malls
  now attempt every block and the placers refuse 9 and 31 of them.
* **Task 3 (one-arm dispatch, `94c4edaf`…`f18502e7`)** measured, after Ruling
  R5, `mall/all-products blocks=39 blocks_unattempted=0 recut_rounds=2`,
  `mall/no-proliferator blocks=54 blocks_unattempted=0 recut_rounds=2`, and
  `titanium-glass@15 blocks=6 blocks_unattempted=0 recut_rounds=0`
  (`t3-r5-*.log`). **This gate reproduces all three exactly, in both rounds**
  — 39, 54 and 6, with the same `recut_rounds` and the same
  `arm_dispatch_freeform=0 / sequence_pair=73` split on no-proliferator. It
  also confirms the implementer's own adverse finding rather than softening
  it: **on `mall/no-proliferator` the one-arm dispatch is worse than racing
  both arms.** Task 2's both-arms measurement left **6** blocks never placed;
  Task 3's one-arm dispatch leaves **31**, and this gate measures 31 twice.
  The reviewer's explanation is confirmed by the dispatch column itself:
  `arm_dispatch_freeform = 0` on that cell, because the policy creates no spray
  lanes, so `coaters == 0` on every block and `dispatch_arms`
  (`dispatch.py:109-111`) can only return `(ARM_SEQUENCE_PAIR,)`. §5 weighs
  this; **the rule is not tuned here**, per the plan.
* **Task 4 (the per-demand reachability goal, `900afa1e`…`8362b22d`)** shipped
  a `goals` parameter and Ruling R6's `_PORT_ACCESS_PROBE_KEEP = 2` scoped to
  goal-carrying demands only. **This gate can neither confirm nor refute its
  payload in production, and says so**: on all ten composing runs the answer
  the goals produce is thrown away before it reaches a rung decision
  (`reservation_degraded = 1`), so what the composer acts on is v2's
  local-only reservation. The mechanism is proven in a test
  (`a2ecd5b2`) and by Task 6's direct probe; it is not proven on a shipped
  build here, because it never gets to speak.
* **Task 5 (the trunk-partner doorstep, `e91886fb`/`b9473715`/`a2ecd5b2`)**
  measured belt3/all-products@60 going `reservation_missing` 0 → 102 with
  `unrouted_cuts` 28 → **126**, then after Ruling R7's discard
  `reservation_missing=0 reservation_degraded=1 unrouted_cuts=18`, and
  **explicitly declined to claim 28 → 18 as an improvement** because the two
  runs are not a controlled pair. **This gate agrees with the implementer on
  every point, including the refusal to claim the win**, and adds the
  generalisation the implementer could not: `reservation_degraded = 1` on
  **all five composing cells across both rounds**, spanning 26 to 147 cut
  lanes and 31 to 183 port demands. The lever is not merely inert on belt3; it
  is inert on **every cell this gate composed**, and it is a wall tax on all
  of them.
* **Task 6 (`oracle.md`, `6457e215`/`3067adfa`)** walked all six `GAP_LADDER`
  rungs on belt3 and zurl2 at a 180 s MEASUREMENT budget and found
  `missing_sealed = 0` on all twelve judged rungs, `assigned = 0` of 91 on all
  six belt3 rungs and 0 of 144 on five of six zurl2 rungs, each missing demand
  reporting `reachable_options = 2`; that `missing` does not track `unrouted`
  (belt3's `missing` constant at 91 while the router goes 15, 16, 7, 9, 6, 3);
  and that production commits gap 2 with a degraded reservation. **This gate
  agrees and independently corroborates the production half of it**: `compose_gap
  = 2` and `reservation_degraded = 1` on every composing cell in both rounds,
  at the gate's own 60 s and 15 s budgets rather than at 180 s. It also
  corroborates that author's own warning that zurl2's rows are clock-bound and
  not geometry — this gate measures zurl2 refusing **69 of 70 (r1) and 71 of 73
  (r2) cuts on `BUDGET`** at 60 s, with exactly 1 and 2 geometric refusals.
  Where the gate must be careful: `oracle.md` is explicit that its cells' final
  CLI verdicts are probe artifacts, and **no gate clause is read from it** —
  it is cited for the rung-level mechanism only, which is what it measured.
* **Task 7 (`corridor-spike.md`, `bf081859`)** recorded `LEVER C: SKIPPED`,
  clause 1 failing and clause 2 holding, without implementing anything. **This
  gate agrees the verdict follows from the evidence**, notes that Task 7's
  reviewer re-extracted all twelve rungs independently and found no
  discrepancy, and adopts that document's own caveat: the SKIP is a statement
  about `_match_access_corridors` giving up, not a finding that the composed
  geometry is adequate. §5 lever 1 is the thing that must be fixed before the
  corridor can be judged at all.

## 4. Default-unchanged corpus guard (Step 3)

<!-- PLACEHOLDER: filled in after the paired audit ran; see below -->

## 5. The next three levers, from the measurement

The gate FAILS. Clauses (a), (b) and (c) all fail; **Lever A (funding /
dispatch) fails on clause (b)** and **Lever B (the oracle) fails on clause (c)
and on four fifths of clause (a)**; Lever C never ran. The three levers below
are ranked by the size of the measured number behind them and by how close
each stands to a first emitted blueprint.

### Lever 1 (headline): `_match_access_corridors` gives up WHOLESALE, and the trunk-goal oracle is therefore thrown away on every build

`freeform.py:11875` — `for _round in range(_ACCESS_CUT_ROUNDS):` with
`_ACCESS_CUT_ROUNDS = 8` (`freeform.py:375`) — returns `{}` at
`freeform.py:11881` when the validate/cut loop gives up, rather than returning
the partial assignment it has. `compose.py:899` then correctly refuses to act
on an empty answer (Ruling R7) and re-asks v2's local-only question, counting
`reservation_degraded`.

**The number: `reservation_degraded = 1` on all five composing cells in both
rounds — ten production compositions out of ten.** Tasks 4 and 5 are, on every
cell this gate composed, computed and discarded. Before Ruling R7's discard
existed, acting on the empty answer took belt3's `unrouted_cuts` from 28 to
**126** (Task 5's own measurement); after it, 18. Task 6's `oracle.md` shows
the same give-up at *every* rung of the ladder, not only rung 0 — `assigned = 0`
of 91 on all six belt3 rungs, 0 of 144 on five of six zurl2 rungs, on demands
each reporting `reachable_options = 2`, i.e. the A\* had **proved two corridors
reachable** and the matcher declined to use either.

It is a matcher-scaling problem with a worked counterexample, not a wall:
zurl2's gap-16 rung came back **complete, 144 of 144 assigned in 4.17 s,
`degraded` False** (`oracle.md`, `rung-zurl2-all-products.json`). Until this is
fixed, the ladder cannot rank a rung, `compose_gap` is pinned at 2 on every
cell, and the four upper rungs stay unreachable to production — while belt3's
router measurably prefers the widest one (15, 16, 7, 9, 6, **3** unrouted
across the ladder, all geometric, at the round count production itself uses).

### Lever 2: power the ground COMPOSITION adds — 4 splitters of 80, and it is the last thing between this branch and its first blueprint

Evidence: §2.3. `titanium-glass/all-products` at 60 s composes, wires all 26
cut lanes, and fails `validate.certify` (`strategy.py:787`) with
`errors_by_check == {power.coverage: 4}` — **one check, four findings, nothing
else wrong with the placement**. All four are splitters (`dsp/catalog.py:219`,
item 2020) at two tiles, convicted by `validate.py:3714-3720`. The canvas has
61 Tesla towers and 80 splitters; **76 splitters are covered and 4 are not**,
because each block brought towers sized for its own footprint and the ground
`compose` opens between blocks carries none.

This is design §4 E's reserved corridor arriving from the other direction: not
"the router has no ground to work in" but "the ground composition gives it is
unpowered". It is ranked second rather than first only because lever 1 blocks
four cells and this blocks one — but it is the **smallest measured gap between
the hierarchical strategy and a validator-clean blueprint in three gates**, and
it is bit-reproducible across two rounds plus the probe run.

### Lever 3: the block placers on the malls' shapes, and re-opening the one-arm rule for coater-free specs

Evidence: §2.2, both rounds. `mall/all-products` refuses with 9 blocks, **7 of
them carrying `freeform.py:20015`'s own "That is a PACKER defect -- it is
producing packs its own router cannot wire"** — the placer convicting itself,
not a budget. `mall/no-proliferator` refuses with **31 blocks, all 31
`deadline exhausted`**, and the dispatch column says why the whole cell is on
one arm: `arm_dispatch_freeform = 0`, because that policy creates no spray
lanes, `coaters == 0` on every block, and `dispatch.py:109-111` can then only
return `(ARM_SEQUENCE_PAIR,)`.

The measured cost of that rule on this cell is **6 blocks never placed under
both arms (Task 2) against 31 under one (Task 3, and twice more here)** — a
5× regression on the clause the plan exists to close, on the one cell where
the feature key has no signal to work with. The rule was correctly not tuned
inside this plan. The lever is to give `dispatch_arms` an "abstain" answer for
a feature vector the evidence does not cover — `coaters == 0` with `strips`
below `UNCOVERED_STRIPS = 85` is currently indistinguishable from a genuine
sequence-pair block — and to re-measure both malls under it.

## 6. The adaptive memories still open, and one residual risk

Neither memory is planned, and each says why. Both are recorded in
`docs/speedup-idea-backlog.md` in exactly this form.

* **A cross-build solved-block cache.** Deliberately NOT planned here: related
  work is already planned as the "background compound block cache" (`42c9e0e`)
  and duplicating it would be two designs for one cache. The evidence for it
  keeps growing — this gate solved the same one-recipe blocks from scratch in
  all sixteen runs, and `mall/no-proliferator` names 31 refusing blocks in a
  single refusal, most of them single-recipe.
* **A strip cap that moves with outcomes.** Deliberately NOT attached to the
  `_ShapeNoGood` memo v2 shipped, because it is not cheap to attach:
  `_ShapeNoGood` is consulted BEFORE a block solve and keyed on `(shape, arm)`,
  while the signal it should adapt on is the ROUTER's verdict (unrouted lanes
  per cut), which arrives once per build after every block has already been
  solved and composed. There is no second composition within a build to feed
  it, so an outcome-driven cap needs a cross-build memory — which is the
  previous bullet.
* **A residual risk, deliberately not fixed, and open.** Ruling R7's discard
  triggers only on an assignment of **exactly zero** (`compose.py:899`,
  `goal_driven.assigned or not demands`). A small PARTIAL assignment — one
  corridor staked where v2 staked ~102 — would commit and report
  `reservation_degraded = 0`, i.e. a stats line claiming a trustworthy verdict
  when the oracle had in effect been thrown away. **There is no evidence either
  way**: every assignment observed in this plan, at every rung of both probed
  cells and on all ten composing production runs, was wholesale empty. A
  narrow, obviously-correct trigger was preferred to a tuned threshold. It
  matters because `reservation_degraded` is the key a gate reads
  `reservation_missing = 0` through, and this is the one way that reading can
  be wrong.

## 7. As-shipped strategy constants (superseding v2 §8)

The numbers in this gate were measured against **these**. Rows that changed on
this branch are marked.

| What | As shipped on `hierarchical-v3` | v2 value | Where |
| --- | --- | --- | --- |
| Settlement reserve | `min(40, max(5, 0.4 * budget))` | same | `settlement_reserve_s`, `SETTLEMENT_RESERVE_{MIN,MAX}_S = 5.0/40.0`, `_SHARE = 0.4` |
| Pool width | `max(1, min(32, (workers or _available_cpu_count()) // 4))` | same | `_pool_width`, `_POOL_CAP = 32`, `_BLOCK_WORKERS = 4` |
| Per-round block budget | **`clamp(remaining / rounds_left / waves, 5, 20)`** | `clamp(remaining / waves, 5, 20)` | `lay_out` ~618-642, `BLOCK_BUDGET_{MIN,MAX}_S = 5.0/20.0` |
| `rounds_left` | **`1 + allowed_recuts - recut_rounds`**, so a round can never spend the wall the next round needs | absent | `strategy.py:618` |
| Global re-cut bound | **`MAX_RECUT_ROUNDS = 2`**, floored by **`allowed_recut_rounds(rounds_wall) = min(2, max(0, int(wall // 5) - 1))`** — **0 at the web UI's 15 s** | **no global round bound at all** | `strategy.py:195`, `:285-294` |
| Re-cut attempts | `MAX_RESPLIT_ATTEMPTS = 4`, per BLOCK | same | `_recut` |
| `rounds_wall` | computed ONCE before `initial_partition` (Ruling R3), so a slow round cannot re-argue its own budget | absent | `strategy.py:537` |
| Arm dispatch | **one arm per block from `dispatch_arms(features, arms)`**, with widen-before-cut | **both arms raced on every block** | `dispatch.py:101-111` |
| Dispatch thresholds | **`ARM_SMALL_STRIPS = 6`, `UNCOVERED_ITEMS_ABOVE_ONE_BELT = 8`, `UNCOVERED_STRIPS = 85`**; `coaters > 0 and strips <= 6` → freeform, else sequence-pair, and both arms whenever the vector is outside what the evidence covers | absent | `dispatch.py:41-43` |
| Strip cap | `STRIP_CAP_DEFAULT = 12`, counting packed strips | same | `partition.STRIP_CAP_DEFAULT` |
| Composition gap | a searched rung of `GAP_LADDER = (2, 4, 6, 8, 12, 16)` under `LADDER_WALL_SHARE = 0.4`, `MIN_GAP = 2` | same | `compose.py:68, 87, 103` |
| Rung-0 reservation wall | **`RESERVE_WALL_SHARE = 0.25`** of the rung's clock | absent | `compose.py:115` |
| Port-access oracle | **per-demand `goals` (a trunk partner's doorstep), with `_PORT_ACCESS_PROBE_KEEP = 2` applied ONLY to goal-carrying demands** (Ruling R6); a wholesale-empty assignment is discarded and re-asked local-only (Ruling R7) | boundary-only, structurally unreachable | `freeform.py:385`, `compose.py:899` |
| Matcher give-up | `_ACCESS_CUT_ROUNDS = 8`, returning `{}` wholesale | same | `freeform.py:375`, `:11875`, `:11881` |
| Block-shape no-good | `_ShapeNoGood`, per build, `(shape, arm)` | same | `strategy._ShapeNoGood` |
| Process context | `spawn`; ONE pool for the whole build | same | `_spawn_pool`, `lay_out` |

Which of these are load-bearing for the readings above:

* **`rounds_left` and `allowed_recut_rounds` are why `blocks_unattempted = 0`
  on all eight cells** (§3, Task 2). They are the whole of Lever A's delivered
  effect, and they are not enough for clause (b).
* **`dispatch.py:109-111` is why `mall/no-proliferator` runs entirely on
  `sequence-pair`** and why it leaves 31 blocks unplaced where both arms left
  6 (§5 lever 3).
* **`compose.py:899` is why every `reservation_missing = 0` in §2.1 must be
  read together with `reservation_degraded = 1`** (§5 lever 1, §6).

## 8. Files

* `gate.md` (this file). §0 was written and committed at `58023a0e`, **before
  any cell ran**, and is unamended.
* `run_large.sh`, `run_cell.py` (this gate's harness — no monkeypatching; see
  §2), `judge.py` (copied **byte-identical** from
  `../2026-09-07-hierarchical-v2/`, inherited lint findings and all, so both
  gates' corpus comparisons are computed by the same program)
* `large-{belt3,zurl2,mall,titanium-glass}-{policy}-b{60,15}-r{1,2}.{json,log,stdout.txt}`
  and their `-load.txt` — the sixteen cell runs of §2
* `certify_probe.py`, `certify-titanium-glass-all-products.{json,log}` and
  `certify-titanium-glass-load.txt` — the one extra build behind §2.3
* `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`, their
  `-load.txt`, `compare-round1.txt` and `judge-round1.txt` — the guard of §4
* Carried in from earlier tasks of this plan and cited above as their authors':
  `oracle.md`, `rung_probe.py`, `rung-{belt3,zurl2}-all-products.{json,log}`
  and their `-load.txt` (Task 6); `corridor-spike.md` (Task 7);
  `t3-*.log` / `t3-r5-*.log` and their `-load.txt` (Task 3's three
  measurements under three round-accounting rules)

No blueprint file is present: every run refused, so `-o` was never written.
