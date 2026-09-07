# Gate: hierarchical v3 on the large URLs

Branch `hierarchical-v3` at `bf081859` (the code HEAD every measurement below
is taken at). Merge base: master `1ce8a0d3`. Worktree
`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v3`.

Box: 128 cores, never idle, and its load is I/O wait. Every timed step has a
`-load.txt` beside it, taken immediately before the run. At most one layout
build ran at a time from this plan, and **no audit of this gate ever ran while
another audit was running** — checked before each of the four audit
invocations, which then WAITED (220–340 s on three of the four) rather than
racing a sibling worktree.

**The load convention changed after these runs, and the committed files were
NOT re-measured.** CPU pressure on this box is now recorded as the five-second
mean of RUNNABLE processes —
`vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`, under 64 being
fine on 128 cores — because load average here is dominated by I/O wait and so
measures the wrong thing. `run_large.sh`, `run_guard.sh` and `run_moved.sh` now
write that. **Every `-load.txt` in this directory predates the change and holds
the OLD form**: an `uptime` line plus one `vmstat 1 3 | tail -1` line. Nothing
was re-run and nothing was backdated.

The old form is not useless, because its `vmstat` line's first column is `r`,
the run queue — **a single SAMPLE, not a five-second mean**, and not the new
metric. Read across the 30 old-form files in this directory: load average
ranges **7.29–64.99** while the runnable sample ranges **3–75**, and the two
disagree in exactly the direction the new convention exists for — the highest
load average recorded here, 64.99 beside Task 6's belt3 rung probe, sat against
**19** runnable. That is the case for the change, made from this gate's own
files rather than asserted.

**A correction to the check the plan prescribes, and it runs the OTHER way
round.** The plan warned that `pgrep -f audit.py` "matches its OWN command line
and always returns a hit" and prescribed
`ps -eo args | grep -cE 'scripts/audit\.py'` instead. **That is backwards, and
this gate first got it wrong in the same direction.**

* **`pgrep` never self-matches.** It excludes its own PID — procps-ng 4.0.6
  here, and every BSD does the same. Measured on this box with **9** real audit
  processes running: `pgrep -af 'scripts/audit\.py'` returned exactly those 9
  and did **not** include the invoking shell, whose command line contained the
  pattern verbatim. The one false positive `pgrep -f` can produce is an
  *enclosing* `bash -c "… pattern …"`, which the `[s]` bracket form removes,
  because the literal text `[s]cripts/audit\.py` is not accepted by the regex
  it spells.
* **The prescribed replacement is the form that self-matches**, because
  `ps -eo args` lists the pipeline's own `grep`. It reads 2 with nothing
  running. Reading it literally cost this gate one wasted detached checkout
  (recorded in `c3fe8116`), and an earlier revision of these scripts
  "fixed" it by assembling the pattern at run time — treating the symptom on
  the strength of the plan's wrong diagnosis.

`run_guard.sh` and `run_moved.sh` now use `pgrep -af '[s]cripts/audit\.py'`
and **print the matching lines next to the count**, so every number in §4 is
auditable rather than asserted. The plan has been corrected at both sites.
Avoid `pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'` as the primary form:
it is also self-match-proof, but it matched only **2 of those 9**, missing the
forkserver children. **This is a script-text and docs correction only — nothing
was re-run for it, and the behaviour of the four audit invocations already
taken is unaffected**, because the run-time-assembled pattern they used
excluded the same processes for a worse reason.

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
| (d) corpus guard: zero regressions, 0 INVALID, 0 CRASH | no cell CLEAN on base and not CLEAN on branch | **72 = 72 CLEAN on both trees** (freeform 36→36, sequence-pair 36→36); **0** regressions, **0** the other way, **0** INVALID, **0** CRASH, 0.000 s wall overshoot both sides. 7 of 72 cells moved in area, **all 7 smaller**; five shown to move on one or both trees by a control pair (§4.1) | **PASS** |
| — (reported, not gating) belt3 / zurl2 / titanium-glass area | `area / best_known` | **not computable on any cell**: nothing was emitted, so no area exists | not demonstrated |
| — (reported, not gating) wall within budget + `RACE_COMPLETION_GRACE_S = 6.0` | ≤ 66.0 s and ≤ 21.0 s | the six 60 s cells ran **24.68–60.91 s** in process (largest: zurl2 r2 at 60.91, inside 66.0); the two 15 s cells ran **9.46–15.59 s**, inside 21.0 | PASS |

### The clause-to-lever attribution the rule asks for

* **Clause (b) is LEVER A (funding / dispatch), and it is charged on the
  DISPATCH half.** The brief's literal A-signature — "a mall still refuses with
  blocks unattempted" — is **absent**: `blocks_unattempted = 0` on every cell in
  both rounds, so the FUNDING half of lever A did what it was built to do. What
  fails is the half Task 3 shipped: the malls attempt every block and the
  placers refuse 9 and 31 of them, with the one-arm rule measurably worse than
  racing both on `mall/no-proliferator` (§3, §5 lever 3). It is the clause Tasks
  2 and 3 exist to close, and it is not closed.
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
emitted. **One qualification, and it is the area column's only datapoint in
three gates:** `titanium-glass/all-products` at 60 s got far enough to have a
composed placement measured before it was refused — **area 11297 against a
best-known 5727, i.e. 1.97x** (`certify-titanium-glass-all-products.json`,
§2.3). That is a **REJECTED** placement, not a blueprint: it never emitted, it
carries 4 `power.coverage` errors, and it is therefore not an `area /
best_known` result in the sense §0 reports and certainly not one it gates. It
is recorded because "no area exists anywhere" would now be false, and because a
first blueprint on this cell would start from roughly that number.
**Validator errors by class are `n/a` on seven cells and NOT by omission**: `pipeline.build` raises `NoValidLayout` on all sixteen runs, so
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
`validate.certify` (`strategy.py:807`). It then refuses. Because the CLI
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
  `mall/all-products`, the line `blocks=52 blocks_unattempted=22 ...
  nogood_skips=36 recut_rounds=0` and noted that v2's harness spy had read 22
  unattempted for the same cell, so the CLI surface reproduced it. **That line
  is inherited, not committed** — it is `inherited-numbers.md` §4, taken on a
  tree before Task 2's funding fix, and it must not be read against
  `t3-fix1-mall-all-products.log`, a different tree under Ruling R4 whose line
  says `nogood_skips=40 recut_rounds=2`. The part of it this gate leans on is
  `blocks_unattempted=22`, which v2 read independently. **This gate agrees, and is
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
  both arms.** Task 2's both-arms measurement left **6** blocks never placed
  (that 6 is the implementer's own, now rescued verbatim into
  `inherited-numbers.md` §3); Task 3's one-arm dispatch leaves **31**, which is committed
  in `t3-r5-mall-no-proliferator.log` and which this gate measures twice more.
  The reviewer's explanation is confirmed by the dispatch column itself:
  `arm_dispatch_freeform = 0` on that cell, because the policy creates no spray
  lanes, so `coaters == 0` on every block and `dispatch_arms`
  (`dispatch.py:123-126`) can only return `(ARM_SEQUENCE_PAIR,)`. §5 weighs
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
  `unrouted_cuts` 28 → **126** (that whole intermediate run is inherited, not
  committed — `inherited-numbers.md` §1), then after Ruling R7's discard
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

## 4. Default-unchanged corpus guard (Step 3): **PASS**

Per controller ruling R13, and scripted as `run_guard.sh` so the procedure is
part of the record: everything committed and `git status --short` empty first,
`git checkout --detach 1ce8a0d3`, the BASELINE half run there writing to
`/tmp/v3gate/` (this evidence directory does not exist at the merge base),
`git checkout hierarchical-v3` immediately, HEAD and cleanliness re-verified,
then the CANDIDATE half, then the baseline half copied in. **No `git stash`,
no second worktree.** Baseline `1ce8a0d3`, candidate `c3fe8116` — an evidence
commit whose `src/` is identical to `bf081859`'s (`git diff bf081859..HEAD --
src tests` is empty).

Files: `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`, their
`-load.txt`, `compare-round1.txt`, `judge-round1.txt`, and `run_guard.sh`.

Condensed from `judge-round1.txt`; **every value is copied from it unedited,
and one LABEL is not**: `judge.py` prints `wall-safety: candidate max 0.000 s
vs baseline max 0.000 s -> OK`, and the line below adds the word *overshoot*,
because the quantity is `wall_overshoot_s` — already net of each cell's own
allowance — and "max 0.000 s" alone reads like a wall rather than an
exceedance. No number was changed. Read `judge-round1.txt` unabridged.

```
commits  : baseline 1ce8a0d  candidate c3fe811
status counts       baseline  candidate
  CLEAN                   72         72
  freeform          CLEAN 36->36
  sequence-pair     CLEAN 36->36
CLEAN in baseline, not CLEAN in candidate: 0     <-- no regression
not CLEAN in baseline, CLEAN in candidate: 0
INVALID/CRASH rows in candidate: 0
INVALID/CRASH rows in baseline:  0
wall-safety: candidate max overshoot 0.000 s vs baseline max 0.000 s -> OK
gmean area ratio  all 0.99456 (-0.54 %)  freeform 0.99259  seq-pair 0.99654
cells whose area moved at all: 7 of 72   -- larger 0, SMALLER 7
total build wall: baseline 1470.2 s, candidate 1463.2 s  (199 s / 198 s wall)
```

**A declared deviation from the brief's invocation.** The brief writes
`--json > <half>.jsonl 2> <half>.txt`; `run_guard.sh` runs
`--json <half>.jsonl > <half>.txt 2>&1`. On this master `--json` takes a PATH
and **appends** to it (`scripts/audit.py` ~741: "append one JSON record per
cell to this file"), so it is not a flag whose stdout can be redirected. The
outputs are the same two files per half and all four are committed; the script
deletes a stale target first, because appending twice would silently double it.
The plan has been corrected at that site too.

**Clause (d) as declared in §0 requires exactly three things, and all three
hold: no cell CLEAN on the merge base and not CLEAN on the branch (0), 0
INVALID, 0 CRASH.** Both trees are 72/72 CLEAN on both arms.

**Two banners that must not be read as the verdict.** `audit.py` prints
`NOT CLEAN` on any refusal — there were none here, and both halves' own
summary lines read `36/36 clean` per arm. And **`audit_compare.py` prints
`FAIL`**, on this line:

```
clean 72  refused 0  invalid 0  crashed 0  paired 72  area ratio 0.9946  p95 32.2s
  FAIL p95 wall 32.2s exceeds 30.0s
```

That is `audit_compare.py`'s own p95-wall clause against its 30 s default, not
a status regression and not one of §0's three sub-clauses — and the BASELINE's
p95 is **31.42 s**, also over 30, so the clause fails on the merge base too.
It is a property of the corpus at a 30 s budget, not of this branch. Read the
counts, never the banner.

### 4.1 The seven moved cells, run down on both trees

This branch cannot make v2's structural argument, and it is worth saying why
rather than borrowing it. v2's `src/` diff touched `freeform.py` **not at
all**, so its gate could say "no line either audited arm executes differs
between the trees". **This branch changes `freeform.py`**, and the changed
region is not inert to the default path: the diff has hunks in exactly two
places — the `_PORT_ACCESS_PROBE_KEEP` constant block and `_reserve_port_access`
(`freeform.py` ~375 and ~11931-12155, 54 non-comment lines) — and
`_reserve_port_access` IS reached by freeform's own default path, through
`_prepare_routing_problem`'s nested `hold_ports` with `boundary=boundary_cells`
(Task 4 fix round 2, `8362b22d`, which cites those callers by symbol precisely
because a line number went stale). Ruling R6 scopes the new probe cap to
demands carrying an explicit goal, so a boundary-probed demand still
enumerates every option, and that is pinned by a mutation-verified test — but
that is an argument, and four of the seven moved cells are freeform. So the
control was run.

`run_moved.sh`, same procedure, `--only` the five url_ids carrying the seven
cells, 30 cells per half, candidate `c3d9b70c` (again `src`-identical) then
baseline `1ce8a0d3`. Files `moved-{baseline,candidate}-r2.{jsonl,txt}`, their
`-load.txt`, `judge-moved-r2.txt`. Both halves 30/30 CLEAN, 0 regressions, 0
INVALID/CRASH.

| cell | base r1 | base r2 | cand r1 | cand r2 | reading |
| --- | --- | --- | --- | --- | --- |
| freeform `universe-matrix [0/no-proliferator]` | 39312 | 39312 | **31898** | **39312** | candidate moves, landing on the baseline's value |
| sequence-pair `plastic [0/no-proliferator]` | **722** | **684** | **663** | **684** | BOTH trees move, both land on 684 |
| freeform `super-magnetic-ring [0/no-proliferator]` | **2183** | **2220** | **2124** | **2146** | BOTH trees move, four values |
| freeform `super-magnetic-ring [2/output-products]` | **2044** | **2052** | **1989** | **2044** | BOTH trees move; candidate r2 = baseline r1 |
| sequence-pair `magnetic-coil [2/output-products]` | **304** | **299** | 299 | 299 | the BASELINE is the unstable side |
| sequence-pair `universe-matrix [2/output-products]` | 16720 | 16720 | 16340 | 16340 | **stable on both trees, and different** |
| freeform `quantum-chip [1/all-products]` | 3840 | 3840 | 3825 | 3825 | **stable on both trees, and different** |

**Five of the seven are demonstrably run-to-run noise** — four move on one or
both trees between the two rounds, and one (`magnetic-coil`) is unstable on
the BASELINE side, exactly as v2's control found for its own seventh cell.
`universe-matrix [0/no-proliferator]` is the sharpest: the candidate produces
31898 and then 39312, and 39312 is the baseline's value in both rounds. v2's
control found the same cell moving 31898 → 39312 on ITS baseline
(`../2026-09-07-hierarchical-v2/gate.md` §5b), so both trees have now produced
both values across two gates.

**Two are NOT shown to be noise, and this gate does not claim they are.**
`sequence-pair universe-matrix [2/output-products]` (16720 → 16340, -2.3 %)
and `freeform quantum-chip [1/all-products]` (3840 → 3825, -0.4 %) each
reproduced twice on each tree. Both are **smaller on the branch**; neither is
a status change, neither is INVALID or CRASH, and neither is one of §0's three
sub-clauses. Two runs per side is not enough to call a 0.4 % difference a
branch effect rather than a coarser noise floor, and no third round was run —
so what this gate reports is the measurement, not a conclusion: **clause (d)
passes on what it declares, and two cells got slightly smaller for a reason
this gate did not establish.**

Summary: **the guard PASSES** — 0 of 72 cells CLEAN → not CLEAN, 0 INVALID, 0
CRASH, 0 wall overshoot on either side, **65 of 72 cells bit-identical**, and
of the 7 that moved every one moved SMALLER, five of them demonstrably on both
trees.

## 5. The next three levers, from the measurement

The gate FAILS. Clauses (a), (b) and (c) all fail; **Lever A (funding /
dispatch) fails on clause (b)** and **Lever B (the oracle) fails on clause (c)
and on four fifths of clause (a)**; Lever C never ran. The three levers below
are ranked by the size of the measured number behind them and by how close
each stands to a first emitted blueprint.

**One qualification on "four fifths", against this gate's own interest.** Those
four are belt3 at both policies, zurl2, and titanium-glass at 15 s — but
**zurl2 is not evidence against the oracle.** 69 of its 70 unrouted cuts in r1
and 71 of 73 in r2 are `BUDGET`: the router ran out of clock, not ground, and
its geometric refusals are 1 and 2. §3 and `oracle.md` both say so, and
`oracle.md`'s own finding 3 declines to read zurl2's rung ordering as geometry
for the same reason. So lever B is properly charged on **three** cells of
demonstrated geometry — belt3 at both policies and titanium-glass at 15 s —
plus a fourth that is clock-bound before it is ground-bound and would need a
router wall it can finish on before it could testify either way.

**Where the files cited below live**, given once so a reader in a year does not
have to search: `compose.py`, `dispatch.py`, `partition.py` and `strategy.py`
are under `src/flab2bp/layout/hierarchy/`; `freeform.py`, `validate.py` and
`base.py` under `src/flab2bp/layout/`; `catalog.py` under `src/flab2bp/dsp/`;
`cli.py` and `pipeline.py` under `src/flab2bp/`. The same holds for the
citations in §2, §3 and §7.

### Lever 1 (headline): `_match_access_corridors` gives up WHOLESALE, and the trunk-goal oracle is therefore thrown away on every build

`freeform.py:11875` — `for _round in range(_ACCESS_CUT_ROUNDS):` with
`_ACCESS_CUT_ROUNDS = 8` (`freeform.py:375`) — returns `{}` at
`freeform.py:11881` when the validate/cut loop gives up, rather than returning
the partial assignment it has. `compose.py:899` then correctly refuses to act
on an empty answer (Ruling R7) and re-asks v2's local-only question, counting
`reservation_degraded`.

**The number: `reservation_degraded = 1` on all five composing cells in both
rounds — ten production compositions out of ten.** That is this gate's own
measurement, off the shipped stats line (§2.1). Tasks 4 and 5 are, on every
cell this gate composed, computed and discarded. Before Ruling R7's discard
existed, acting on the empty answer took belt3's `reservation_missing` to
**102** and its `unrouted_cuts` to **126**; after it, 18. **That whole
intermediate run was taken on a tree that no longer exists and is quoted
verbatim in `inherited-numbers.md` §1** — see the provenance note at the end of
§5 for the full list of such figures. The 28 it is measured against is v2's,
from `../2026-09-07-hierarchical-v2/gate.md` §2.1; the 18 is this gate's,
twice. Task 6's `oracle.md` shows
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
cut lanes, and fails `validate.certify` (`strategy.py:807`) with
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
lanes, `coaters == 0` on every block, and `dispatch.py:123-126` can then only
return `(ARM_SEQUENCE_PAIR,)`.

The measured cost of that rule on this cell is **6 blocks never placed under
both arms (Task 2, `inherited-numbers.md` §3) against 31 under one (Task 3, and
twice more here)** — a
5× regression on the clause the plan exists to close, on the one cell where
the feature key has no signal to work with. The rule was correctly not tuned
inside this plan. The lever is to give `dispatch_arms` an "abstain" answer for
a feature vector the evidence does not cover — `coaters == 0` with `strips`
below `UNCOVERED_STRIPS = 85` is currently indistinguishable from a genuine
sequence-pair block — and to re-measure both malls under it.

### Provenance note: every figure in this gate that no committed file carried

An earlier revision of this note said "two", and that was wrong — a
wrong exhaustiveness claim in the gate's own honesty mechanism is worse than no
claim, so here is the full list, and **all four are now committed**, quoted
verbatim with their tree's commit, in **`inherited-numbers.md`** beside this
file. Each came from an implementer's task report under `.superpowers/sdd/`,
which is gitignored and is deleted when the plan finishes.

Every other figure in this gate is either measured by it (the `large-*`, the
`certify-*`, the `*-round1` and `moved-*` artifacts beside this file) or cited
to a committed one (`oracle.md`, `corridor-spike.md`, the `t3-*` and `t3-r5-*`
logs, v2's `gate.md`). These four are neither, and **none of them decides a
gate clause**; all four sit in a RANKING or an agreement note:

| figure | where cited | tree | re-measured at HEAD? |
| --- | --- | --- | --- |
| belt3 `reservation_missing = 102` **and** `unrouted_cuts = 126`, pre-Ruling-R7 | §3 Task 5, §5 lever 1 | `e91886fb` | **No, and it cannot be** — R7 landed at `b9473715` and the behaviour is gone |
| belt3 `unrouted_cuts = 18`, post-R7 | §3 Task 5, §5 lever 1 | `b9473715` | **Yes, twice** — `large-belt3-all-products-b60-r{1,2}.json`, agreeing on every field |
| `mall/no-proliferator` **6** blocks never placed under BOTH arms | §3 Task 3, §5 lever 3 | `0bf58d3d` | **No, and it cannot be** — one-arm dispatch landed at `94c4edaf` |
| mall/all-products `nogood_skips = 36` (and that line's `recut_rounds = 0`) | §3 Task 1 | `d89b78e3` | **No** |

Two notes a sceptical reader will want, because both are traps:

* **The Task 1 line is NOT `t3-fix1-mall-all-products.log`.** That committed log
  is a different tree (Task 3 fix round 1, `69031212`, under Ruling R4's round
  accounting, which Ruling R5 then reverted) and reads
  `nogood_skips=40 recut_rounds=2` against Task 1's `36` and `0`. They agree on
  `blocks=52 blocks_unattempted=22` and disagree on the other two; neither is a
  re-run of the other, and **there are no `t1-*` evidence files** — Task 1
  committed no build artifacts. What §3's Task 1 bullet actually rests on is
  `blocks_unattempted=22`, which v2's harness spy independently read for the
  same cell (`../2026-09-07-hierarchical-v2/gate.md` §2.1); the `nogood_skips`
  figure carries nothing.
* **The `6` is the load-bearing one.** It is what makes §5 lever 3 a
  *regression* — 6 under both arms against 31 under one — rather than a
  standalone number. Its counterpart is committed and measured three times
  (`t3-r5-mall-no-proliferator.log` plus this gate's two rounds). The `6` rests
  on `inherited-numbers.md` §3 alone.

## 6. The adaptive memories still open, and one residual risk

Neither memory is planned, and each says why. Both are recorded in
`docs/speedup-idea-backlog.md` in exactly this form.

* **A cross-build solved-block cache.** Deliberately NOT planned here: related
  work is already planned as the "background compound block cache" (`42c9e0e`)
  and duplicating it would be two designs for one cache. The evidence for it
  keeps growing, and this gate can put a number on it: `mall/no-proliferator`
  names **31 refusing blocks in one refusal, 30 of them single-recipe — 9
  `magnet`, 7 `iron-ingot`, 6 `electric-motor`, and 2 each of `copper-ingot`,
  `magnetic-coil`, `electromagnetic-turbine` and `super-magnetic-ring`**; the
  one multi-recipe block is `circuit-board, sorter-1, sorter-2` (counted from
  `large-mall-no-proliferator-b60-r1.json`, identical in r2 — and 9+7+6+2+2+2+2
  = 30, +1 = 31). Nine separately
  solved `magnet` blocks in one build, sixteen times over the sixteen runs, is
  the case for the cache stated as a measurement.
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
| Per-round block budget | **`clamp(remaining / rounds_left / waves, 5, 20)`** | `clamp(remaining / waves, 5, 20)` | `lay_out` ~638-662, `BLOCK_BUDGET_{MIN,MAX}_S = 5.0/20.0` |
| `rounds_left` | **`1 + allowed_recuts - recut_rounds`**, so a round can never spend the wall the next round needs | absent | `strategy.py:638` |
| Global re-cut bound | **`MAX_RECUT_ROUNDS = 2`**, floored by **`allowed_recut_rounds(rounds_wall) = min(2, max(0, int(wall // 5) - 1))`** — **0 at the web UI's 15 s** | **no global round bound at all** | `strategy.py:205`, `:295-304` |
| Re-cut attempts | `MAX_RESPLIT_ATTEMPTS = 4`, per BLOCK | same | `_recut` |
| `rounds_wall` | computed ONCE before `initial_partition` (Ruling R3), so a slow round cannot re-argue its own budget | absent | `strategy.py:558` |
| Arm dispatch | **one arm per block from `dispatch_arms(features, arms)`**, with widen-before-cut — **which is structurally unreachable at the web UI's 15 s default**: `_recut` is the only caller of the widening branch and the round loop raises on `recut_rounds >= allowed_recuts` *before* reaching it, with `allowed_recut_rounds(~8.7) = 0`, so a 15 s build ships the one-arm rule with no escalation at all (§2.1 measures `arm_dispatch_both = 0` on both 15 s cells) | **both arms raced on every block** | `dispatch.py:102-126` |
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
* **`dispatch.py:123-126` is why `mall/no-proliferator` runs entirely on
  `sequence-pair`** and why it leaves 31 blocks unplaced where both arms left
  6 (§5 lever 3).
* **`compose.py:899` is why every `reservation_missing = 0` in §2.1 must be
  read together with `reservation_degraded = 1`** (§5 lever 1, §6).

## 8. Files

* `gate.md` (this file). §0 was written and committed at `58023a0e`, **before
  any cell ran**, and is unamended. **That claim is about §0 alone, not about
  this file.** Everything else here was written after the runs, and the
  PROLOGUE above §0 was additionally amended POST-HOC twice — the load
  convention and the `pgrep` correction, both of which say so in their own
  paragraphs. A reader skimming for "unamended" should read it as a statement
  about the pre-registered rule and nothing more.
* `run_large.sh`, `run_cell.py` (this gate's harness — no monkeypatching; see
  §2), `judge.py` (copied **byte-identical** from
  `../2026-09-07-hierarchical-v2/`, inherited lint findings and all, so both
  gates' corpus comparisons are computed by the same program)
* `large-{belt3,zurl2,mall,titanium-glass}-{policy}-b{60,15}-r{1,2}.{json,log,stdout.txt}`
  and their `-load.txt` — the sixteen cell runs of §2
* `certify_probe.py`, `certify-titanium-glass-all-products.{json,log}` and
  `certify-titanium-glass-load.txt` — the one extra build behind §2.3
* `run_guard.sh`; `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`,
  their `-load.txt`, `compare-round1.txt` and `judge-round1.txt` — the paired
  guard round of §4
* `run_moved.sh`; `moved-{baseline,candidate}-r2.{jsonl,txt}`, their
  `-load.txt` and `judge-moved-r2.txt` — the moved-cell control of §4.1. **No
  gate clause is read from the control**; clause (d) is decided by the paired
  round alone, and passes there.
* Carried in from earlier tasks of this plan and cited above as their authors':
  `oracle.md`, `rung_probe.py`, `rung-{belt3,zurl2}-all-products.{json,log}`
  and their `-load.txt` (Task 6); `corridor-spike.md` (Task 7);
  `t3-*.log` / `t3-r5-*.log` and their `-load.txt` (Task 3's three
  measurements under three round-accounting rules)

No blueprint file is present: every run refused, so `-o` was never written.

### 8.1 `src` and `tests` CHANGED AFTER THIS GATE WAS MEASURED — read this before trusting a number here

**`src` and `tests` were byte-identical from `58023a0e` — the commit that
pre-registered §0's PASS/FAIL rule — through every measurement in this file and
through `82aabc9f`.** `git diff --stat 58023a0e 82aabc9f -- src tests` is empty.
That is what made "the tree that was measured is the tree that ships" a
checkable claim rather than an assurance, and it is no longer true of HEAD.

**The final whole-branch review's fix wave changed both, at `0af741ed`**, after
the measurements. Diff it yourself: `git diff 82aabc9f 0af741ed`. What it
contains, and why none of it can move a number above:

| change | why it cannot move a measured number |
| --- | --- |
| `base.py`: `resplits`, `recut_rounds`, `compose_gap`, `port_demands`, `arm_dispatch_*` TypedDict comments | comments on a `TypedDict` field list; no field added, removed or renamed, no code |
| `strategy.py`: module-docstring paragraph on widen-before-cut, `_refuser` docstring restored, one wrong clause deleted from the arm-dispatch comment | docstrings and comments only |
| `dispatch.py`: `dispatch_arms` narrows only to an arm that is a member of `arms` | `dispatch_arms` is reached only from `strategy._arms_for`, which returns early unless `len(arms) >= 2`, and `arms` is always `HierarchicalLayout._arms()` — `("freeform", "sequence-pair")` at `block_strategy="best"`, a 1-tuple otherwise. So the new branch is taken only if `ARM_FREEFORM` or `ARM_SEQUENCE_PAIR` is not in `("freeform", "sequence-pair")`. **Unreachable at HEAD.** |
| `strategy.py`: `_block_layout` raises on an unregistered arm instead of falling through to sequence-pair | `_block_layout`'s only caller is `_solve_block`, whose arm is `_BlockJob[1]`, built in `_solve_round` from `_arms_for` — a subset of the same two names. **Unreachable at HEAD**, and it is the same two-name set that makes the old fall-through correct today |
| `tests/layout/hierarchy/{test_dispatch,test_strategy,test_compose}.py`: two new tests for those guards, one added refusal-message assertion, one write-only accumulator turned into an assertion, one pinned constant equality | tests exercise no production code path a cell run takes; no `src` behaviour is reached that was not reached before |

**Do not read this as "the measurements are still valid."** What is claimed is
narrower and checkable: **the measurements in this file were taken at
`82aabc9f` and have NOT been re-run**, and the diff to `0af741ed` consists of
comments, docstrings, tests, and two guards on branches no call at `82aabc9f`
or at `0af741ed` can reach. Whether that is enough to carry the verdict forward
is the reader's judgement, not this file's assertion.

**§7's `file:line` references were re-pointed** in the same wave, because the
`strategy.py` and `dispatch.py` docstring additions shifted them. They now name
lines in the SHIPPED tree, not in `82aabc9f`. The constants, thresholds and
expressions they point at are unchanged; only the line numbers moved. §7's
`dispatch.py` arm-dispatch row also carried a wrong span before this
(`101-111`; line 101 was blank and `def dispatch_arms` was at 102).

**§0 is untouched by all of this** and remains byte-identical to `58023a0e`.
