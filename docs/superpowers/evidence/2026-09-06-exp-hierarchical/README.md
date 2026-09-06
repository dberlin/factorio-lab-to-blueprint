# Hierarchical block decomposition on the large URLs

Spike. Throwaway code, kept only so a go decision can lift it.

**Question.** Can a spec that both placers refuse today be laid out by
DECOMPOSING it into blocks the existing placers handle comfortably, solving the
blocks independently, and composing them with a bus, at a bounded area cost?

## Answer: GO, with conditions

**Placement decomposes cleanly. ROUTING does not, and the whole cost of the idea
sits in one place: the block-to-block lane interface.**

* **Coverage.** All four cases now produce a **validator-clean, encodable
  blueprint**, including `mall/all-products` (449 machines, which refuses
  everywhere at every budget measured) and `mall/no-proliferator` (935). No case
  produced an INVALID composed placement in the blocks-only configuration, and
  none crashed.
* **Area.** `zurl2` composes at **0.78x** the best-known dense monolith.
  `belt3` composes at **1.23x** with the pressure-guided partition and
  **1.47x** with the size-cap one. The 1.5x kill line is cleared by the
  pressure-guided partition and missed by the size-cap one the brief specified.
* **Time.** Every case's critical-path block wall is **11-13 s**. Measured
  serial block wall (every block, both placer arms, one after another) is 66 s
  to 221 s; blocks are embarrassingly parallel, so the wall a real orchestrator
  pays is the critical path plus composition.
* **The catch.** Of the block-to-block belts the partition asks for, the
  prototype's corridor router wires a minority, and every corridor it *does*
  build on the two mall cases turns a CLEAN composition INVALID. Everything the
  router cannot wire is handed back to the player as "connect this belt
  yourself" — 8 to 21 such loops per case.

So the deliverable today is **"the blocks, packed, with the trunk belts left to
the player"**. That is a real, pasteable, correct blueprint and it is the thing
no current placer can produce at all for the mall. The trunk is unbuilt, and it
is the whole remaining risk.

Every number below is from `out/*.json`, produced by `proto/run.py`, and every
emitted blueprint round-trips through `flab2bp.dsp.codec.decode`.

## Kill criteria, declared before running, and what happened

| criterion | outcome |
| --- | --- |
| composed placement fails validation for a structural reason the prototype cannot fix | **NOT met** in the blocks-only configuration: 0 validator errors on all four cases. **MET for the corridor router**: on both mall cases, wiring corridors reintroduces exactly one `flow.conservation` shortfall that the prototype's boundary accounting cannot close (see "The lane contract"). |
| area more than 1.5x the best known on `belt3` | **Depends on the partition.** Size-cap arm: 1.4688 blocks-only, **1.5185 with corridors — MET**. Depth-pressure arm: 1.2292 blocks-only, 1.3133 with corridors — not met. |
| total wall over 120 s | **NOT met** on any case. Worst measured critical-path block wall 13.3 s; worst serial 221 s at `--parallel 2`, which is a two-core schedule, not a wall an orchestrator would accept. |

One criterion fired, on one arm, by 1.2 %. That is a go-with-conditions.

## Design as built

`uv run python docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/run.py <label>`

1. **Whole spec** (`proto/specs.py`). Replicates the front half of
   `pipeline.build` — `canonicalize_dataset`, `parse_url`,
   `canonicalize_request`, `_build_candidates_canonical`, `belt_rules_for_url` —
   so the prototype decomposes exactly the `BuildSpec` the production pipeline
   would hand a placer.
2. **Partition** (`proto/partition.py`, `proto/pressure.py`). Two arms:
   * `--arm size-cap` (the brief's): nodes are *units*, one per `MachineGroup`,
     pre-split so no unit exceeds `--cap`; edges are rate-weighted item flow;
     blocks come from agglomerative merging on the heaviest edge under the cap.
   * `--arm depth-pressure` (cut pressure, the register-pressure analogue):
     level the recipe DAG, compute
     the pressure of every depth boundary, cut at the **local minima** of lane
     pressure, and keep each region between two cuts together as one block
     however large it is.
3. **Sub-specs.** `partition.sub_spec` builds a real `BuildSpec` per block: every
   item the block is NET short of becomes an `external_input`, every item it has
   NET spare becomes an `output`; belt tier, sorter ladder, `belt_stack` and
   `piler_unlocked` travel verbatim; spray lanes and `belt_required_edges` are
   RECOMPUTED, never filtered.
4. **Solve.** Each block goes to both `FreeformLayout` and `SequencePairLayout`
   through the production `pipeline._new_layout`, two blocks at a time, smaller
   valid result wins. A refusing block is **escalated**: cut in half, children
   solved. That recursion is the hierarchy actually recursing, and it is what
   turns a refusal into a build.
5. **Compose** (`proto/compose.py`). Blocks normalized to their own origin,
   skyline-packed (bottom-left, tallest first, width swept, band-legal shapes
   preferred), translated onto one canvas with indices rebased. Inter-block
   belts routed one net at a time by a Dijkstra over the composed free space.
6. **Certify.** `finalize.compact_open_boundary_belts` ->
   `finalize.finalize_placement` -> `validate.validate` -> `markers` ->
   `codec.encode`, the production sequence, judged against a spec **re-derived
   from what was actually built**.

### Where this departs from the brief

* **The bus is not a shared physical trunk.** Every whole-spec external input
  arrives at each block on that block's own entry lane;
  `flow.external_entry_points` is a WARNING precisely because that is
  legitimate. The cost is entry lanes the player must feed: 10-11 on `belt3`,
  18 on `zurl2`, 19 on both malls.
* **The corridor router is not `freeform._route_all`.** That router is not
  callable standalone: its nets, grid, lane plan, merge frontier and rip-up
  state are constructed inside `lay_out` from one `BuildSpec`, and there is no
  entry point taking "a prepared canvas plus a list of nets". The closest
  existing pattern, `_plan_shared_external_inputs` /
  `_place_shared_external_input_trunks`, is likewise internal to one placement's
  grid. So the prototype wrote its own, and it is visibly worse.
* **The partition does not min-cut multi-consumer items away.** It was tried and
  it does not converge; see below.
* **Skyline packing gives up strict topological order along the bus.** The
  router searches the whole canvas, so order affects only trunk length.

## Cut pressure

`item_pressure` is how many distinct items are produced on one side of a
boundary and consumed on the other — the number of *nets* that must cross.
`lane_pressure` is `sum(ceil(rate / lane capacity))` over those items — the
number of *belts*, which is what the geometry actually pays for. Lane capacity is
`spec.lane_capacity` times `spec.planning_stack(item)`, so a stacked bus is
priced at what it really carries. Both are in `out/*.json` under `cut_pressure`
(whole partition) and `cut_pressure_boundaries` (per ordered block pair).

### belt3's depth pressure profile

| cut after depth | recipes below | machines below | item pressure | lane pressure |
| --- | --- | --- | --- | --- |
| 0 | 5 | 145 | 5 | 8 |
| 1 | 7 | 183 | 6 | 8 |
| 2 | 9 | 228 | 6 | 6 |
| 3 | 10 | 253 | 5 | 5 |
| 4 | 12 | 274 | 3 | 3 |

The profile falls monotonically, so its local minima are the first and last
boundaries: cut after depth 0 and after depth 4. That gives three blocks —
**145, 129 and 6 machines** — with a whole-partition lane pressure of **17**,
against **22** for the size-cap partition the brief specified. The minimum-
pressure partition is NOT the one the size-cap rule chose, and it is better on
every axis measured.

### Does high pressure show up as hard?

Directly measured on the unescalated three-block depth partition
(`out/belt3-depth-pressure-1round.json`):

| block | machines | recipes | boundary lanes | result |
| --- | --- | --- | --- | --- |
| 0 | **145** | 5 | 8 | **OK, 4900 tiles in 9.6 s** — 0.0296 machines/tile, the densest block anywhere in this experiment |
| 1 | 129 | 7 | 9 | **REFUSED both arms** — freeform "no completed packing of 24 strips", sequence-pair "deadline exhausted" |
| 2 | 6 | 1 | 3 | OK, 270 tiles in 0.3 s |

**Boundary pressure does not separate them: 8 lanes solved and 9 refused.**
What separates them is **strips** — 145 machines over 5 recipes is a handful of
strips and places in 9.6 s, while 129 machines over 7 recipes is 24 strips and
refuses. Machine count is not the hardness variable and neither, on this
evidence, is boundary lane pressure; **recipe count / strip count is**.

**Would "solve high-pressure regions as one integrated block, cut at pressure
minima" change the recommendation? Yes — it strengthens it, but for a different
reason than pressure predicting hardness.** Cutting at pressure minima is worth
**16 % of composed area on belt3** (1.2292 vs 1.4688 blocks-only; 1.3133 vs
1.5185 with corridors) and **40 % of serial block wall** (66 s vs 110 s), and it
is what takes belt3 from failing the 1.5x kill criterion to clearing it. The
mechanism is not that low-pressure cuts are easier to solve; it is that they
produce **fewer, larger, more recipe-homogeneous blocks**, which pack with less
gap tax and give the placers fewer strips each. So the rule to adopt is "cut at
pressure minima, and bound blocks by STRIPS rather than machines" — pressure
picks *where* to cut, strip count decides *whether* to cut again.

## Results

### Wall

Every case at `--cap 60 --budget 12 --gap 2 --max-depth 6`, two blocks solved at
a time. "Serial block wall" sums every arm of every block (what one core would
pay); "critical path" is the slowest single arm (what unlimited cores would pay).

| case | machines | blocks | block sizes | serial block wall | critical-path block wall | compose+finalize+validate | measured total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `belt3` | 280 | 8 | 15-56 (median 47) | 110.0 s | 12.0 s | 5.33 s | 6.42 s |
| `belt3-blocks-only` | 280 | 8 | 15-56 (median 47) | 110.0 s | 12.0 s | 3.22 s | 4.23 s |
| `belt3-depth-pressure` | 280 | 7 | 6-145 (median 20) | 66.0 s | 10.9 s | 5.49 s | 6.44 s |
| `belt3-depth-pressure-blocks-only` | 280 | 7 | 6-145 (median 20) | 66.0 s | 10.9 s | 3.11 s | 3.93 s |
| `zurl2` | 436 | 11 | 1-60 (median 56) | 171.7 s | 13.3 s | 9.46 s | 10.89 s |
| `zurl2-blocks-only` | 436 | 11 | 1-60 (median 56) | 171.7 s | 13.3 s | 6.85 s | 8.26 s |
| `mall` | 449 | 71 | 1-47 (median 4) | 221.4 s | 12.1 s | 11.23 s | 11.92 s |
| `mall-blocks-only` | 449 | 71 | 1-47 (median 4) | 221.4 s | 12.1 s | 5.07 s | 6.52 s |
| `mall-no-proliferator` | 935 | 79 | 2-60 (median 8) | 208.3 s | 12.2 s | 26.71 s | 27.36 s |
| `mall-no-proliferator-blocks-only` | 935 | 79 | 2-60 (median 8) | 208.3 s | 12.2 s | 6.41 s | 7.73 s |

The "measured total" excludes the block solves because they came from the
run-to-run cache (`--cache`); the per-block walls in the table and in
`out/*.json` are all COLD measurements from the run that first solved them.

### Verdict and area

| case | verdict | validator errors | area | sum of blocks | best known | ratio | machines/tile |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `belt3` | CLEAN | 0 | 18841 | 14274 | 12408 | 1.5185 | 0.01486 |
| `belt3-blocks-only` | CLEAN | 0 | 18225 | 14274 | 12408 | 1.4688 | 0.01536 |
| `belt3-depth-pressure` | CLEAN | 0 | 16296 | 13087 | 12408 | **1.3133** | 0.01718 |
| `belt3-depth-pressure-blocks-only` | CLEAN | 0 | 15252 | 13087 | 12408 | **1.2292** | 0.01836 |
| `zurl2` | CLEAN | 0 | 33480 | 26854 | 40905 | **0.8185** | 0.01302 |
| `zurl2-blocks-only` | CLEAN | 0 | 31824 | 26854 | 40905 | **0.7780** | 0.01370 |
| `mall` | INVALID | 1 `flow.conservation` | 39903 | 29681 | none | - | 0.01125 |
| `mall-blocks-only` | CLEAN | 0 | 38497 | 29681 | none | - | 0.01166 |
| `mall-no-proliferator` | INVALID | 1 `flow.conservation` | 52564 | 39691 | none | - | 0.01779 |
| `mall-no-proliferator-blocks-only` | CLEAN | 0 | 49344 | 39691 | none | - | 0.01895 |

"Sum of blocks" is the sum of the blocks' own areas — the cost of decomposition
before any packing. On belt3 that is **1.05x** the best-known monolith under the
depth-pressure partition and 1.15x under the size-cap one: **decomposition
itself costs almost nothing; composition packing costs 17-27 %.**

### Pressure and the interface

| case | item pressure | lane pressure | worst boundary lanes | cuts p2p | cuts shared | routed | unrouted | corridor tiles | player loops |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `belt3` | 21 | 22 | 1 | 4 | 12 | 2 | 4 | 543 | 8 |
| `belt3-blocks-only` | 21 | 22 | 1 | 4 | 12 | 0 | 0 | 0 | 8 |
| `belt3-depth-pressure` | 21 | 25 | 4 | 7 | 11 | 3 | 6 | 571 | 10 |
| `belt3-depth-pressure-blocks-only` | 21 | 25 | 4 | 7 | 11 | 0 | 0 | 0 | 11 |
| `zurl2` | 43 | 46 | 3 | 11 | 18 | 4 | 10 | 626 | 16 |
| `zurl2-blocks-only` | 43 | 46 | 3 | 11 | 18 | 0 | 0 | 0 | 18 |
| `mall` | 126 | 126 | 2 | 4 | 563 | 3 | 1 | 496 | 14 |
| `mall-blocks-only` | 126 | 126 | 2 | 4 | 563 | 0 | 0 | 0 | 17 |
| `mall-no-proliferator` | 157 | 162 | 2 | 7 | 769 | 4 | 6 | 1303 | 18 |
| `mall-no-proliferator-blocks-only` | 157 | 162 | 2 | 7 | 769 | 0 | 0 | 0 | 21 |

These are the pressures of the FINAL, post-escalation partitions. Escalation
raises pressure: belt3's depth partition starts at 17 lanes across 3 blocks and
ends at 25 across 7, because splitting a refusing block creates new boundaries.
That is a direct argument for fixing the placers' strip-count limit rather than
escalating around it.

### Validator output

Zero ERRORS on all four blocks-only compositions. Warnings, which are expected
and are the honest cost of the design:

* `flow.external_entry_points` 10-19 per case — one per item the player must
  belt into more than one block. Legitimate, and a WARNING by design.
* `belt.termination` 55-191 per case — the open output tails of every
  handed-back trunk.
* `geom.bounds` 1 on `zurl2`, `mall`, `mall-no-proliferator` — extent over the
  256-tile soft width.

The corridor-routed mall runs each add exactly one `flow.conservation` ERROR
(`processor` short by 28/15 items/s; `graphene` short by 9/40). Running the same
composition with `--no-route` removes it, which is what pins the cause on the
corridors rather than on the partition.

## The three things a production version must solve first

### 1. The block interface is a LANE CONTRACT, not an item name

A cut is not "block A sends `copper-ingot` to block B" — it is "block A's five
output lanes meet block B's three entry lanes". Each block sizes its lanes from
its own rates, independently, and they do not agree. On `zurl2`, **10 of 11
point-to-point cuts failed on lane-count mismatch alone**: `magnet` 6 out / 4 in,
`electric-motor` 8 out / 5 in, `graphene` 2 out / 1 in, `casimir-crystal` 1 out
/ 3 in. On belt3's depth partition, `magnet` is 11 out / 6 in.

The rate half of the same problem is what turns the malls INVALID: **wiring a
cut converts an entry lane the player could feed at any rate into a corridor-fed
lane that carries only what the producing block spares.** When the producer
spares less than the consumer needs, `flow.conservation`'s lane balance convicts
it, and declaring the shortfall as an external input cannot rescue it, because
external supply has to arrive on an entry run and every run is now fed.

Two ways out, and a production version needs one before anything else:

* **Fix the lane count and rate on both sides when the sub-specs are built** —
  make the cut rate, and therefore `ceil(rate / lane_capacity)`, identical for
  the producer's `outputs[item]` and the consumer's `external_inputs[item]`.
  Cheap; it constrains the partition instead of the emitter.
* **Emit the splitter/merge tree at the boundary** — the `_merge_frontier`
  machinery `2026-09-06-density-decomposition` named. More general, and what a
  real shared trunk needs anyway.

### 2. The router needs a standalone entry point

`freeform._route_all` cannot be driven over a prepared canvas with a list of
nets. The prototype's replacement wired 2 lane-runs on `belt3` and left 4 cuts
unrouted; on `zurl2` it wired 4 and left 10; and one of its failures is
literally "no corridor path over free
ground" on a canvas with plenty of free ground, because it refuses to cross any
occupied column and has no rip-up. **Composition cannot reuse the routing
quality the placers already have until routing can be called on a canvas
somebody else prepared.**

### 3. Finalization and projection are whole-placement operations

A block certified alone is not certified in a composition:

* moving a block DOWN re-prices its internal east-west spacings and refused at
  every latitude band on `game.power_too_close` (two poles 3.4998 world units
  apart against a 3.5 gate);
* at `--gap 1` two blocks' build colliders intersect and `finalize_placement`
  refuses with `geom.collide` — **2 tiles is the minimum legal separation**, and
  the gap tax on area is not optional;
* at 935 machines the minimum-AREA packing was 247x205 and **fit no latitude
  band at all** (`game.blueprint_area`: 205 rows needed, the tallest band holds
  160, `EBuildCondition.BlueprintAreaCrossTropic`). The packer now prefers a
  band-legal shape over a small one, which is why that case builds. **There is a
  hard ceiling on one-blueprint composition and 935 machines is close to it.**

## The mall's refusal is a five-machine hole, not a scale problem

The most useful thing the experiment found, and it was only findable because
decomposition drove the spec down to leaves small enough to name.

Before the escalation depth was raised, both mall cases still refused after being
cut to 50 and 69 blocks — and every refusing block was **6, 11 or 12 machines**.
The smallest is as simple as a spec gets:

```
6 x copper-ingot in a negentropy-smelter
external inputs: copper-ore (sprayed), proliferator-3
outputs: copper-ingot            belt_stack 4, piler unlocked
```

`proto/minimal.py` rebuilds exactly that and hands it to both placers. It refuses
**at 12 s and at 60 s, on both placers, with `belt_stack` lowered to 1, with the
piler locked, and with the spray removed** — none of those is the cause. Sweeping
the machine count (`out/minimal-block-counts.json`) finds it, and it is not size:

| negentropy-smelters | freeform | sequence-pair |
| --- | --- | --- |
| 1 | OK, 104 | OK, 104 |
| 2 | OK, 128 | OK, 128 |
| 3 | OK, 171 | OK, 171 |
| 4 | OK, 198 | OK, 198 |
| **5** | **REFUSED** `geom.collide` band 4 | **REFUSED** deadline exhausted |
| **6** | **REFUSED** `geom.collide` band 4 | **REFUSED** expansion budget exhausted |
| 7 | OK, 374 | OK, 374 |
| 8 | OK, 374 | OK, 374 |

**A hole at exactly 5 and 6, on both placers, on a one-recipe spec.** The same
hole appears for `iron-ingot` in the same machine. Freeform's own packs collide
at the polar band (`geom.collide (48, 56): build colliders intersect`);
sequence-pair gives up in 1.0 s regardless of the budget it is given.

Two consequences:

* **The mall was never evidence against hierarchical decomposition.** Its
  refusal survived being cut 75x smaller because it was never a capacity
  refusal. Both malls build once the escalation is allowed to go past 6 machines
  — `--max-depth 6` instead of 3 — which is the prototype stumbling over the
  hole rather than fixing it.
* **An escalating decomposer must vary the split, not only shrink it.** Six
  machines refuse; 3 + 3 places. Block size interacts with the placers
  **non-monotonically**, so "retry with a different cut" has to be a first-class
  move.

## The repair that does not work

The brief's "an item consumed at six positions wants its consumers in one block"
was implemented as a repair: move an item's producing units INTO each consuming
block so the item stops crossing. **It does not converge.** Each move plants the
producer's own ingredient demand in new blocks, which creates fresh
multi-consumer cuts one level UPSTREAM. Measured on `zurl2/all-products` and
`mall/no-proliferator`, **400 repairs left exactly the same 5 and 11 residual
items as 0 repairs did**, having merely churned the block contents. The code is
kept in `partition.py` behind `max_repairs=0` because the negative result is the
useful part: **a production version has to build the splitter, not dodge it.**

## Other things that broke, and why

Each of these made a composed placement invalid, and each is a property of
composition that a production version will meet.

1. **Sub-spec flags must be RECOMPUTED, not inherited.** `spray_lanes[item]` is
   `True` exactly when the lane exists anyway because the item is belted in; an
   item internal to the whole spec is EXTERNAL to a block that does not make it,
   so its flag flips. Filtering the parent's flags made **every block** refuse on
   `prolif.sprayed_cargo_reaches_machines`. Same for `belt_required_edges` (both
   endpoints must be in the block) and `lanes_requiring_split`.
2. **Cuts must be read off NET balances, not set membership.** A block that both
   makes and takes an item can still be SHORT of it after integer rounding, and
   `sub_spec` then correctly declares it external. Treating "produces it
   somewhere in the block" as "needs no lane" left that entry lane unfed:
   *"33 machine(s) consume 31464/625 items/s of magnet but only 1524384/38125
   items/s of it can reach them in flow order"*.
3. **A corridor at z = 0 walls in other blocks' entry lanes.**
   `flow.external_entry_reachable` floods **each altitude plane separately**. A
   ground-level corridor threading the gaps sealed 11 entry runs on `belt3`.
   Making altitude cheap and ground dear in the router's cost function (climb
   out, cross elevated, descend at the far end) removed all 11. Single highest-
   leverage line in the prototype.
4. **Belt link slots and colliders do not survive naive concatenation.** The
   placers' belt chains write `(output_from_slot 0, output_to_slot 1)`; the
   dataclass defaults `(0, 0)` put two records in one `entityConnPool` cell and
   `game.slot_occupancy` convicted **every** corridor tile (284 errors). A
   Splitter's build collider reaches beyond its 2x2 footprint, so a corridor tile
   flush against one is convicted by `game.belt_collide` (33 errors); a one-tile
   halo for the router's purposes fixes it.
5. **One placer crash, unfixed.** A `mall/all-products` sub-spec crashed
   `SequencePairLayout` with `ValueError: stage-boundary transform must rebuild
   every restart identically` (`sequence_solver.py:2660`/`:2874`). The prototype
   now catches it and reports CRASH. A decomposer will hit this more often than a
   monolithic caller because it hands the placers many more, smaller, oddly
   shaped specs.

## Concerns

1. **The composed blueprints ask the player to close belt loops, and there are a
   lot of them** — 8 on `belt3`, 18 on `zurl2`, 17 and 21 on the malls. Each is a
   belt the player runs between two blocks of the same blueprint. It pastes and,
   once those belts exist, it runs, but it is not what "a blueprint" usually
   means, and **the composed area does not include the belts still to be laid.**
2. **`belt3`'s overage is a packing number, not a decomposition number.** The
   blocks' own areas sum to 13087 against a 12408 monolith — 1.05x under the
   depth-pressure partition, inside the brief's 10-20 % target. The rest is a
   2-tile gap tax and skyline waste.
3. **Escalation raises cut pressure.** belt3's depth partition starts at 17
   lanes across 3 blocks and ends at 25 across 7. Every refusal the placers hand
   back costs interface, so the placers' strip-count limit is upstream of the
   decomposer's quality.
4. **Block size is the wrong knob; strips are the right one.** At `--cap 90
   --budget 20` belt3's blocks summed to 19115 tiles against 14274 at `--cap 60
   --budget 12`; but the depth-pressure arm's **145-machine, 5-recipe** block
   summed better than either and solved in 9.6 s. Machines do not predict
   difficulty. Recipes/strips do.
5. **Single-URL, single-run numbers.** One run of one configuration per cell.
   C8's warning about single runs applies: directional, not gate-grade. `uptime`
   is recorded at both ends of every case in `out/*.json`; the box was under load
   throughout (1-minute average 2.6-16).
6. **The bus is conceptual, not physical.** The reserved shared corridor spec
   §4 E asks for was not built, and the prototype's experience says why it must
   be reserved BEFORE placement rather than routed after: a corridor laid
   afterwards walls in the lanes it was meant to serve.
7. **The depth-pressure arm was run on `belt3` only**, as asked. Its pressure
   profile is monotone there, so its local minima are the endpoints; a spec with
   a genuinely interior minimum has not been tested.

## Files

* `proto/specs.py` — URL -> whole `BuildSpec`.
* `proto/partition.py` — the rate-weighted size-cap partition, sub-spec
  construction, net-balance cut derivation, and the abandoned repair.
* `proto/pressure.py` — item/lane pressure, DAG levelling, the depth pressure
  profile, and the cut-at-minima partition.
* `proto/compose.py` — packing, translation, and the corridor router.
* `proto/run.py` — the driver.
* `proto/minimal.py` — isolates the refusing leaf block.
* `proto/table.py` — regenerates the tables above from `out/*.json`.
* `out/<label>.json` — the full record per case: per-block arms, cut pressure
  per boundary, every cut, every unrouted reason, and `uptime` at both ends.
  `-blocks-only` is the same case composed with no corridor belts at all.
* `out/belt3-depth-pressure-1round.json` — the unescalated three-block
  minimum-pressure partition, which is where the pressure-vs-hardness question
  is answered.
* `out/minimal-block.json`, `out/minimal-block-counts.json` — the five-machine
  hole.
* `out/<label>.blueprint.txt` — the pasteable blueprint, where one was emitted.
