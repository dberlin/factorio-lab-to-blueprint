# Multiple belts and Automatic Pilers above the fastest belt

Date: 2026-09-02, revision 2 on 2026-09-03, revision 3 on 2026-09-03,
revision 4 on 2026-09-04. Status: design, awaiting review. Follows
`2026-09-02-belt-and-sorter-tiers-design.md`,
whose section 11 hands this work off. Revision 2 replaced revision 1 entirely:
revision 1 modelled a piler as a device at "the head of a lane planned at
ceiling x stack", which only works when that lane is already fed by a stacked
source, and it never stated the constraint that governs where a piler may sit.
Section 2 states it.

Revision 3 (Ruling P12) amends sections 5 and 6 to the game facts pinned by
plan Task 6 on 2026-09-03 (`multibelt` commit `8c6f4b1`,
`src/flab2bp/dsp/data/stacking.json`). Four of them moved the design: only the
Pile Sorter carries a stack and only on the live `Pile Sorter Upgrade` ladder
(the `Sorter Cargo Stacking` ladder is obsolete and unreachable); a piler
DOUBLES rather than jumping to a setting, so reaching stack 4 from an unstacked
lane needs two in series; a piler has NO per-building stack parameter, its mode
coming from its wiring; and a piler's intake is at least the belt's own cargo
rate, which deletes the throughput branch. Sections 1, 2, 8, 9 and 10 carry the
consequential corrections; nothing else changed.

Revision 4 removes the live-fixture prerequisite from C. The Automatic Piler
record is derivable from shipped 0.10.34 code: its catalog row has
`multiLevel = 1`, so the blueprint generator assigns `inputToSlot = 14`,
`outputFromSlot = 15`, `inputFromSlot = 15`, and `outputToSlot = 14`; null
object references serialize as `-1`, adjacent belts carry port references 1
and 0, and the empty generic parameter path emits `int[0]`. The shipped catalog
fixes model, footprint,
centre, yaw rotation, and ordered port poses. Sections 6.3, 8, 9, and 10 and
plan Task 11 now cite that conformance evidence rather than claiming that an
uncaptured player blueprint blocks C.

## 1. Problem

After the belt-tier change a run is raised to the fastest belt the save can
build, and a run whose demand still exceeds that belt is refused by
`flow.belt_capacity`. Above the fastest belt (30 items/s for Mk.III) no belt
tier can carry a flow directly. The game offers two ways out, and the tool
implements neither:

- **Several belts in parallel.** Split the flow across lanes so that each lane
  carries at most one belt's worth. Costs belts, entry points and strip length;
  needs no research beyond the belt itself.
- **Piling.** An Automatic Piler (item 2040) merges two consecutive cargos into
  one of up to four; a stack travels as one unit, so a belt whose cargo carries
  stack 2 moves twice the items at the same belt speed. Pile Sorters with the
  Pile Sorter Upgrade research pick and place stacks. Piling is repeated to go
  further: one piler takes 1 to 2, a second takes 2 to 4 (5.1).

Three gaps in the current code, all measured:

- **Nothing bounds machines per strip by belt capacity.**
  `strip_variants.partition_strip_variant` takes a pure machine count
  (`max_machine_count`), fed by `plan_strips`'s `strip_len` (default 6), by
  `_coarsen_saturated_strip_plan`, and by the sequence solver's strip-length
  heuristics; none reads a rate. A strip of 8 particle colliders drawing 4
  items/s each puts 32 items/s on one hydrogen lane, over Mk.III's 30.
- **Boundary lanes are created singly.** `_logical_strip_plans` gives every
  strip its own entry lane per external item and its own boundary sink per
  output, so an external input is already split across strips, but only as a
  side effect of the strip count. `flow.external_entry_points` warns whenever
  one item enters at two or more lanes without saying whether the split was
  needed.
- **Stacking does not exist in runtime code.** Item 2040 is fully described in
  the asset data (footprint 1x3, model 257, two straight-through port poses)
  and no module under `src/flab2bp/` mentions it. FactorioLab's belt-stack
  setting (`ist` in the URL, `LabRequest.stack`) is parsed and unused. The
  validator's capacity arithmetic is in items per second with an implicit
  stack of 1, so a stacked belt would be refused even if one were emitted.

Concrete case: the deuteron-fuel-rod URL from the original report. With
hydrogen belted in directly (as FactorioLab does), hydrogen enters at 40
items/s, above any belt, and the build depends on the strip count happening to
keep each collider strip's lane under 30/s.

## 2. The cargo model

Everything in this design follows from three rules about belts, and the
implementation is organised so that the validator checks exactly these rules
on what was built.

1. **Belt rule.** A belt moves at most its tier speed in *cargo units* per
   second (`BELT_RATE[tier]`, 30 for Mk.III). Items per second on a belt is
   cargo per second times the cargo's stack. A belt tile has one stack for
   the purpose of this design: the minimum stack of the cargo that reaches
   it (section 5.5 says why the minimum is the honest number).
2. **Piler rule.** A piler takes at most one belt's worth of cargo per second
   in, because its input is a belt, and emits the same items per second at
   **twice** the stack that arrived, capped at 4. It never increases the items
   per second that one input belt delivers. What it buys is headroom on the
   belt *after* it, so further belts can merge in. Because a piler doubles
   rather than jumps to a setting, a lane reaches stack 4 from an unstacked
   source through TWO pilers in series (30 items/s at stack 1 is 30 cargo/s;
   after one piler 15 cargo/s at stack 2; after a second 7.5 cargo/s at stack
   4). Pilers are still never placed on a merged trunk: every piler sits on a
   tributary before its junction, and a tributary is a producer strip's own
   output lane. The two facts this rule rests on -- a piler's own throughput is
   at least belt speed, and one piler doubles -- are pinned from the game in
   section 5.1.
3. **Merge rule.** A junction may merge belts only if the cargo rates of the
   merged belts sum to at most the outgoing belt's speed. Therefore: pile the
   tributaries first, merge after, and pile again if another merge follows.

Two sources of stack need no piler at all:

- **External feeds.** FactorioLab computes its belt counts at speed x stack
  when the URL's `ist` is greater than 1, so the player's bus is stacked at
  `ist`. An entry lane arrives stacked; the tool cannot and need not pile it.
- **Machine outputs.** A Pile Sorter takes several items from the machine's
  buffer and places them as one stack, so a producer lane is stacked up to that
  sorter's place level without a piler. Only the Pile Sorter does this, and
  only to its researched place stack (1 unresearched, rising to 4 at level 5);
  Sorter Mk.I to Mk.III place 1 at every level (5.1).

A piler is therefore needed only where a lane's *actual* stack is below what
the next merge needs. Consumer sorters must be able to pick the stack their
lane carries; that is a research level, read from the game data (section 5.1).

Worked examples, at Mk.III (30 cargo/s):

- Four producer lanes at 30 items/s unstacked into one 120 items/s trunk:
  EIGHT pilers, two in series per lane (1 -> 2 -> 4, 7.5 cargo/s each), then
  merges to one belt at 30 cargo/s. Merging before piling would put 60 cargo/s
  on the first merged belt.
- A consumer strip drawing 40 items/s of one item, fed by two 20 items/s
  producer lanes: one piler each to stack 2 (10 cargo/s each), then merge (20
  cargo/s at stack 2 = 40 items/s). Merging first would put 40 cargo/s on one
  belt. Stack 2 is chosen, not 4, because it is the smallest stack that fits --
  and it also halves the piler count, since 4 would need a second piler per
  lane.
- The same strip when the player's bus is stacked at 2 (`ist=2`): one entry
  lane at 20 cargo/s, no piler, consumer sorters picking stack 2.
- Five producer lanes at 30 items/s each: at stack 4 they are 37.5 cargo/s,
  over one belt, so the lanes are grouped by strip ordinal up to 30 cargo/s
  per belt: four on one trunk and one alone (ten pilers, two per lane).
  Parallel belts are the remainder the stack cannot absorb.

Parallel belts are what remains when stacking is unavailable (the URL says
`ist=1`, the piler or the sorter stacking level is not researched) or when
stack 4 cannot absorb the rate (above `4 x BELT_RATE[ceiling]` items/s per
belt). Nothing else needs a heuristic.

## 3. Decision

Three deliverables, each shippable and gated on its own, in this order:

- **A. Parallel belts.** The strip planner caps machines per strip so that no
  lane a strip owns exceeds the *effective* lane capacity. Every flow above
  the ceiling arrives and leaves on as many lanes as it needs, through the
  machinery that already gives each strip its own lanes. No new building.
- **B. Stack-aware lanes.** The stack a lane carries becomes a planned and
  validated quantity. Entry lanes carry the URL's stack; producer lanes carry
  what the save's sorters can place; consumer lanes must be pickable. The
  validator's capacity arithmetic becomes items divided by stack against belt
  speed. No new building either: B alone already lets a stacked bus feed a
  consumer strip above 30 items/s and lets sorter-stacked outputs leave on one
  belt.
- **C. Automatic Pilers.** Where a lane's actual stack is below what a merge
  needs, the planner places a piler on the tributary before the merge, chosen
  by a per-item merge tree built bottom-up under the merge rule.

Rules that bind all three:

1. **FactorioLab is authoritative.** Stacking is used only when the URL asked
   for it (`ist > 1`); FactorioLab computed its belt counts with that same
   stack factor. A URL that says nothing about stacking gets A only, and its
   planning stack is 1 everywhere.
2. **The validator judges what was built, unchanged in kind.**
   `flow.belt_capacity` keeps comparing each run's measured demand against the
   run's own capacity; B makes that capacity `BELT_RATE[tier] x stack_of(run)`.
   Nothing is argued at planning time that the validator does not confirm.
3. **Refuse loudly at the one remaining edge.** A single machine whose single
   ingredient or product exceeds `lane_capacity x planning_stack(item)` is
   refused with a message naming the rate, the belt, and the stack that would
   carry it (for an `ist=1` URL the planning stack is 1, so the edge is the
   belt itself).

## 4. Deliverable A: capacity-aware strip sharding

### 4.1 The cap

`StripFamily` gains `machine_cap: int`, computed in
`strip_variants.generate_strip_families(spec)` from the spec alone:

```
capacity(item) = spec.lane_capacity x spec.planning_stack(item)     # section 5.3
rate(item)     = the group's inputs_per_machine[item] or outputs_per_machine[item]
machine_cap    = max(1, min over the group's items of floor(capacity(item) / rate(item)))
```

Under A alone `planning_stack` is 1 for every item, so
`capacity(item) == spec.lane_capacity`. B changes `planning_stack`, not the
cap's shape.

`partition_strip_variant(family, variant, max_machine_count=...)` takes
`min(max_machine_count, family.machine_cap)`. That is the partition seam:
`plan_strips` in freeform calls it directly (`max_machine_count=max(1,
strip_len)`), `_coarsen_saturated_strip_plan` re-enters through `plan_strips`,
and the sequence solver's `_variant_search_inputs` calls
`partition_strip_family`, which delegates to `partition_strip_variant`
unconditionally. A cap in `partition_strip_family` would miss freeform.

There is one more way a strip grows after partitioning: the sequence-pair
stage boundary merges two instances of one family with
`sequence_pair.merge_strip_instances(family, left, right)`, summing their
machine counts. That merge must refuse (return `None`, which its caller
already treats as "no merge") when the sum exceeds `family.machine_cap`;
otherwise the cap holds at partition time and is undone at the boundary. Those two sites, and nothing else, bound both
strategies and every strip-length heuristic.

`_coarsen_saturated_strip_plan` collapses a plan of more than
`_COARSE_STRIP_THRESHOLD` strips by re-planning at `strip_len =
spec.machine_count`. Where the cap binds it cannot collapse anything, by
design: those are exactly the strips that had to be short. Deliverable A's
gate records how many cells the coarsening no longer rescues (section 10).

Why a per-item bound is enough, and why it is the only bound: a strip's input
lane for item X carries exactly `count x inputs_per_machine[X]`, its output
lanes for item Y carry at most `count x outputs_per_machine[Y]` in total, and
the planner's existing shared-lane and merged-lane checks
(`input_lane_fits`, `_check_shared_lane_capacity`, `_merge_lanes`) still
guard the case where several items share one lane. Today those checks are
the *only* rate checks in the planner, and they skip single-item lanes
(`_check_shared_lane_capacity` returns for lanes of fewer than two items;
`input_lane_fits` is installed only on the shared-proliferation path), so a
single-item lane has no planner bound at all: the cap is that bound. With it
in place, `_merge_lanes`'s over-capacity `ValueError` becomes unreachable
except for a single machine over the ceiling, which is the refusal rule 3
keeps. `_merge_lanes`'s other refusal, distinct cargo lanes exceeding the
sorter reach, is a geometry refusal the cap does not touch and stays.

### 4.2 Why runs stay bounded end to end

The router builds one net per source lane and destination lane, merges several
sources into one destination through junctions, and splits one source to
several destinations through splitters. A merged run into a consumer lane
carries at most that consumer strip's demand; a trunk out of a producer lane
carries at most that producer strip's output; both are bounded by 4.1. The
validator's `_run_demand` already propagates across junctions in both
directions, so what it measures is exactly what the cap bounded.

### 4.3 What changes for the player

Builds whose flows exceed the ceiling get more, shorter strips. External
inputs above the ceiling arrive at several entry lanes and the report says
why: `flow.external_entry_points` gains `detail["lanes_needed"]`
(`ceil(demand / capacity)`) and its message reads "hydrogen is belted in at 2
separate lanes; 40 items/s needs 2 lanes of 30/s" when the count matches the
need, and keeps today's wording when it exceeds it. The severity stays
WARNING; the CLI and web reports print the per-item lane counts next to the
existing "inputs to belt in" line.

Builds whose flows fit the ceiling are unchanged: the cap only binds where
today's strips would produce a lane the validator refuses.

### 4.4 Density, and the recovery if the gate shows it

Capacity-bounded strips are shorter. More strips means more nets, more
boundary lanes and more aisle pitch, which is the pressure the router phases
are fighting. A is shipped first because it is a one-seam change that is
correct by construction, and the corpus gate records area and strip count
before and after. If the gate shows growth on cells that were clean, the
recovery is **lane multiplicity inside a strip**: two parallel belts for the
same item on one side of the strip, within sorter reach, with the strip's
sorters for that item split between them by machine index. That keeps strip
count and pitch at the cost of a new lane geometry: today `_seat_inputs`
seats one lane row per input item and `LogicalLane` requires unique items per
lane and unique lane ids per family, so a second belt for the same item is not
representable, and a side holds at most `SORTER_MAX_REACH` (3) rows. It is
designed here so that A's cap can later be relaxed to
`capacity(item) x lanes(item)`, but it is not built until the gate asks for
it.

### 4.5 Refusal

When `rate(item) > capacity(item)` for some group, `generate_strip_families`
raises `NoValidLayout` with the group, the item, the rate, the ceiling belt,
and, when stacking would carry it, the stack that would (and whether the URL
asked for it). This replaces the late `flow.belt_capacity` refusal for that
case with an early, explained one.

## 5. Deliverable B: stack-aware lanes

### 5.1 Game facts, pinned before the code

**Pinned on 2026-09-03** (`multibelt` commit `8c6f4b1`, plan Task 6). Every
number below is read out of the game's own files for version 0.10.34 -- an
ilspycmd decompile of `Assembly-CSharp.dll` for the behaviour and a UnityPy
typetree dump of `resources.assets` for the per-level unlock values -- not from
a live dump and not assumed. They live in `src/flab2bp/dsp/data/stacking.json`
with the source field named for each one, `catalog` loads them, and
`tests/dsp/test_catalog.py` pins every table entry as a literal.

- `piler_unlocked`: whether `automatic-piler` is in the researched unlock set.
  In the vendored FactorioLab data `integrated-logistics-system` (tech 1607) is
  the sole `recipeUnlock` for both `automatic-piler` and `sorter-4`, so the
  Pile Sorter and the Automatic Piler unlock together.
- **Two stacking ladders, and the obvious one is dead.** `Sorter Cargo
  Stacking` (techs 3301-3305; FactorioLab `sorter-cargo-stacking-1` through
  `-5`) carries `IsObsolete = 1`, which is what hides a tech from the tree, so
  none of its five levels is reachable in a game started on this build. It is
  kept in the JSON under `obsolete_ladder` only because an imported save still
  carries the value. **No code may read it.** The live ladder is `Pile Sorter
  Upgrade` (techs 3311-3316; FactorioLab `pile-sorter-1` through `-6`), six
  levels.
- **A stack is a property of the sorter TIER and the research level, never of
  the item.** The game's grade rule (`GameData.OnInserterTechChange`) pins
  Sorter Mk.I (2011), Mk.II (2012) and Mk.III (2013) at pick 1 and place 1 at
  every level -- Mk.III reads the obsolete ladder's field, whose only reachable
  value is the new-game baseline 1 -- and gives the Pile Sorter (2014):

  | research level | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
  | -------------- | - | - | - | - | - | - | - |
  | pick stack     | 2 | 2 | 3 | 3 | 4 | 4 | 4 |
  | place stack    | 1 | 2 | 2 | 3 | 3 | 4 | 4 |

  Level 0 is an unresearched Pile Sorter, which already picks 2 because the
  new-game baseline does. The accessors are
  `catalog.SORTER_STACKING_LEVELS` (`== 6`),
  `catalog.sorter_pick_stack(item_id, level)` and
  `catalog.sorter_place_stack(item_id, level)`; asking them about a
  non-sorter, or about a level outside `0..6`, raises.

  The consequence that governs the rest of this design: **only the Pile Sorter
  stacks.** A save with Mk.III as its fastest sorter can neither place a stack
  nor pick one, so for that save every stack in this design is 1 and a stacked
  bus is a refusal (5.3), not a slower build.
- `catalog.SORTER_STACK_RATE_FACTOR is True`: each pick adds the picked cargo's
  own stack byte to the load the sorter carries, and the whole load is
  delivered in one trip, so a sorter carrying a stack of `n` moves `n` items
  per trip and `flow.sorter_capacity` scales with the stack. Risk "Sorter
  throughput (B)" in section 10 is settled: the stacks enter that check's
  arithmetic.
- `catalog.PILER_MAX_STACK == 4`, `catalog.PILER_SINGLE_PASS is False`. The
  Automatic Piler caches at most TWO cargos and emits their sum capped at 4, so
  **it doubles**: fed an unstacked belt it emits stack 2, and reaching stack 4
  from an unstacked belt takes two pilers in series (1 -> 2 -> 4). It reaches 4
  in one pass only when its input is already at stack 2 or more.
  `catalog.piler_output_stack(s)` is `min(2 * s, 4)`.
- `catalog.PILER_STACK_PARAMETER is None`: **the piler has no per-building
  stack setting.** `PilerDesc` declares no fields at all,
  `PilerComponent.Export` serialises no stack, and the component's Pile / Split
  state is derived from the wiring by `CargoTraffic.RematchPilerConnection`.
  What a piler does is decided by which belts are attached to it, and to what
  stack it raises a lane is decided by how many pilers the lane passes through
  -- never by a parameter block. There is nothing for `dsp/params.py` to encode
  and nothing for the validator to decode.
- `catalog.PILER_THROUGHPUT == Fraction(6)` cargo per second **per unit of
  `PrefabDesc.beltSpeed`**, and its timed branch is a lower bound (the untimed
  branch adds picks on top). `PILER_THROUGHPUT * beltSpeed` reproduces
  `catalog.BELT_RATE` exactly at all three tiers (6, 12, 30 cargo/s), which is
  the arithmetic statement of "a piler never throttles the belt it sits on".
  The "piler throughput below lane capacity" branch this design once carried is
  therefore unreachable and is deleted rather than left as dead prose (6.2).

Task 6 pinned these on the no-game path (Ruling P11): the files on disk were
enough, so B and C proceed with no live capture outstanding.

### 5.2 The spec boundary

`BuildSpec` gains:

```python
class BuildSpec(_Frozen):
    #: FactorioLab's belt stack (`ist`), 1 when the URL says nothing. Never
    #: raised above 4. This is what the player's bus carries.
    belt_stack: int = 1
    #: Largest stack the save's sorters can pick from a belt and place onto
    #: one, per sorter TIER, slowest first, aligned with `sorter_item_ids`.
    #: The defaults are the level-0 row of 5.1's table: Mk.I-III at 1, an
    #: unresearched Pile Sorter picking 2 and placing 1.
    sorter_pick_stacks: tuple[int, ...] = (1, 1, 1, 2)
    sorter_place_stacks: tuple[int, ...] = (1, 1, 1, 1)
    piler_unlocked: bool = False

    @property
    def max_stack(self) -> int:
        """4 when the piler is unlocked, else the largest place stack."""
```

There is no per-item stack anywhere in the model: a lane's stack is decided by
the tier of sorter that touches it and by the save's `pile-sorter` level, both
of which are properties of the save, so both tuples are indexed by tier and
nothing is keyed by item id.

`_to_build_spec` fills them from `logistics_tiers_for_request`, which gains
`piler: bool` and the two stack tuples, and from `request.stack` (`ist`),
which is parsed today and read by nothing. `logistics_tiers_for_request`
derives the research level from the `pile-sorter-{n}` ids alone -- the highest
`n` in `1..6` present in the researched set, 0 when none is, 6 when the request
carries no technology set at all -- and maps each entry of `sorter_item_ids`
through `catalog.sorter_pick_stack` / `sorter_place_stack` at that level. It
never reads `sorter-cargo-stacking-{n}`, which 5.1 shows is unreachable.
Defaults keep every hand-built spec in the tests at stack 1 with today's
behaviour. `lane_capacity` stays the un-stacked ceiling in cargo per second.

One more reader of the stack: `rates/solve.py` computes an
`ObjectiveUnit.Belts` objective as `value x belt_speed(belt_id)` with no stack
factor, so a URL with `ist=2` whose objective is "N belts" is solved for half
of what FactorioLab means. B multiplies that objective by the URL's stack,
which the belt-tier design left out of scope and rule 1 now requires.

### 5.3 Planning stacks

`spec.planning_stack(item)` is the stack the planner may assume for a lane of
that item, and it is what 4.1's cap reads:

- 1 when `belt_stack == 1` (rule 1: the URL did not stack).
- For an **external input**: `belt_stack`. The bus arrives at that stack
  whatever the consumer can do about it; if the fastest sorter tier the save
  can build cannot pick `belt_stack`, the build is refused at plan time with
  the stack, the sorter tier and the research that would pick it (rule 3).
  Nothing is capped silently, because a capped plan would still be fed a
  stacked bus and starve. With 5.1's tables this refusal has one concrete
  shape: **a save without the Pile Sorter can pick nothing above 1**, so any
  URL with `ist > 1` on a Mk.I/II/III save is refused, and the message names
  `integrated-logistics-system`. With a Pile Sorter, the pickable ceiling is
  the level's pick stack: 2 at levels 0-1, 3 at levels 2-3, 4 from level 4 up,
  so `ist=4` on a level-2 save is also a refusal.
- For an item **fed from the bus and from an internal producer** at once:
  `min(belt_stack, place_stack)`, because the lane carries both and a merge is
  judged at its minimum (5.5).
- For a **produced item**: the place stack of the fastest sorter tier the
  save can build -- that is what the producer's output sorters put on the belt,
  and it is unavoidable, so if the consumer cannot pick it the build is refused
  the same way and never lowered, since a sorter cannot be told to place less.
  Note that the place stack lags the pick stack by one level in 5.1's table, so
  a level-0 Pile Sorter places 1: without a piler such a save produces
  unstacked lanes even though its sorters could pick 2.

  When the piler is unlocked the lane may then be **raised** to the largest
  value of the doubling ladder `1, 2, 4` (6.2) that is at most
  `min(max_stack, pick_stack)`. C places the pilers that make the difference,
  and only where a merge needs them; with `PILER_SINGLE_PASS` false that may be
  two in series. Raising stops at the pickable stack because **piling is
  elective**: choosing not to pile further is not the silent lowering rule 3
  forbids, which is about a stack that arrives whether the tool wants it or
  not. Raising snaps to the ladder because a doubler cannot land on 3, so
  planning at 3 would promise a stack C could not build. Concretely, a level-0
  save with the piler plans produced lanes at 2, not at 4.
- For an **external output**: as a produced item, with no consumer to pick.

Sorter tiers are chosen per lane by `_pick_sorter` from the rate, as today,
which takes the CHEAPEST tier that carries the rate. A planned stack is
therefore a promise the sorter must keep: when `belt_stack > 1`,
`_pick_sorter` skips every tier whose place stack (for a producer lane) or
pick stack (for a consumer lane) is below the lane's planned stack, so a
low-rate lane planned at stack 4 is built with a sorter that places 4, not
with a Mk.I that places 1. The planning value is the fastest allowed tier's
stack (the ceiling of what any tier can promise), and the validator's
`flow.stack_pickable` judges the tier actually placed.

### 5.4 Lanes carry a stack

`LogicalLane` (the demand carrier; `LanePlan` is the pose binding) gains
`stack: int` (1 today) as a trailing field. `_logical_lanes` sets it from
`planning_stack` for input lanes and output lanes, and internal lanes inherit
the producing lane's stack. `input_lane_fits`, `_check_shared_lane_capacity`
and `_merge_lanes` compare `demand / stack` against `lane_capacity`. A lane
whose consumer sorter cannot pick its stack is not planned at a lower stack:
`planning_stack` has already refused the build (5.3), because the belt would
arrive stacked either way.

### 5.5 Validator

The validator does not trust the plan. It derives each run's stack from what
was built and judges the arithmetic:

- `Context.stack_of(run) -> int`: 1 for every run when `spec.belt_stack ==
  1` (rule 1: a save that does not stack its belts gets today's arithmetic
  exactly, including one seeded by a Pile Sorter), else the minimum stack
  over the run's sources, walking upstream through junctions and splitters. A
  source is an entry belt (stack `spec.belt_stack`), a sorter placing from a
  machine (that sorter tier's `sorter_place_stacks` entry), or a piler, whose
  output stack is `min(2 x stack_of(the run into it), 4)` -- derived, because
  5.1 pins that a piler carries no stack setting to read (C). A run with no
  traceable source has stack 1.
- `flow.belt_capacity` compares `demand` against
  `BELT_RATE[tier] x stack_of(run)`.
- `flow.stack_pickable` (ERROR): a sorter drawing from a run must have
  `sorter_pick_stacks[tier] >= stack_of(run)`. This is the check that makes
  a stacked bus over Mk.I sorters a refusal rather than a silently starved
  machine.
- `flow.external_entry_points` reports `lanes_needed` at the effective
  capacity, so a stacked entry lane counts as one lane.

Why the minimum: a belt can carry mixed stacks in the game, and a merge of a
stack-2 and a stack-1 belt runs at some average. The tool has no way to know
the mix at validation time, and the minimum is the only stack every cargo
unit on the run is guaranteed to have, so capacity at the minimum is never
optimistic. The planner never plans a mixed merge (5.4 and 6.2), so the
minimum equals the plan wherever the plan was followed.

### 5.6 Retier interaction

The retier pass divides a run's demand by `stack_of(run)` before choosing the
cheapest tier, through `belt_run_demands` extended with the stack map, so a
stacked Mk.II run carrying 20 items/s at stack 2 keeps Mk.II.

## 6. Deliverable C: Automatic Pilers

### 6.1 Gate

Pilers are placed only when `spec.belt_stack > 1` and `spec.piler_unlocked`.
A lane gets pilers only where its actual stack is below what the next merge
needs; a lane that already fits stays as it is. Since 5.1 pins that the piler
and the Pile Sorter unlock from the same technology, `piler_unlocked` also
means the save's fastest sorter is a Pile Sorter.

### 6.2 The merge tree

For each item that leaves a set of producer lanes for one sink (a consumer
strip's input lane, or the boundary), the planner decides, before routing:

1. The lanes are the producer strips' output lanes for the item, each with
   its demand (`machine_count x outputs_per_machine[item]`) and its planned
   stack (5.3).
2. **A piler is a doubler, so the reachable stacks are 1, 2 and 4.** 5.1 pins
   `PILER_SINGLE_PASS = False`: one piler emits `min(2 x input_stack, 4)`.
   Raising a lane from stack `s0` to a target `t` therefore costs
   `ceil(log2(t / s0))` pilers **in series** on that lane, and lands exactly on
   `t` for every `(s0, t)` this design produces: `1 -> 2` (one), `1 -> 4`
   (two), `2 -> 4` (one), `3 -> 4` (one, capped by `PILER_MAX_STACK`). The
   candidate uniform stacks are consequently the doubling ladder `1, 2, 4`, not
   every integer: a target of 3 is unreachable from an unstacked lane and
   asking for it would silently overshoot to 4, past a sink that can pick only
   3.
3. The **uniform stack** `s` is the smallest value in `(1, 2, 4)` that is at
   most `limit = min(max_stack, sink_pick_stack)` and satisfies
   `sum(demand_i) / s <= lane_capacity`. Stack 2 before 4: the smallest stack
   that fits keeps the most headroom for the sink's sorters and needs the
   fewest pilers. If one exists, every lane whose planned stack is below `s`
   gets `ceil(log2(s / lane.stack))` pilers in series at its downstream end,
   and all lanes merge onto one belt.
4. If none fits, `s` is the largest candidate at most `limit`, every lane below
   `s` is piled to `s` the same way, and the lanes are **grouped** by strip
   ordinal into belts of at most `lane_capacity` cargo per second each. Each
   group merges onto one belt; a group of one is a parallel belt. A's lane
   count already provides the geometry for that.
5. A lane whose planned stack already exceeds `s` keeps its stack and gets no
   piler (a Pile Sorter output at 4 into a stack-2 trunk is fine: the
   validator's minimum rule judges the trunk at 2). The fit test in step 3
   charges every lane at `s` even when its own stack is higher, so it is
   pessimistic against the grouping arithmetic in step 4 (`demand /
   max(stack, s)`); that can choose a larger `s` than the cargo strictly
   needs, never a smaller one, and it stays that way on purpose: an optimistic
   fit test would be the one place a belt could be overfilled.

The decision is deterministic: lanes are ordered by strip ordinal and the
first stack that fits is taken. Its output is a set of `PilerPlan(lane_id,
count, stack)` records -- `count` pilers in series on that lane, the last of
which emits `stack` -- and a grouping of lanes into belts. There is never a
piler on a merged trunk (section 2's piler rule), so every piler is on a
strip's own output lane and the strip's geometry can reserve it; a lane piled
twice reserves twice the tiles (6.3). Today's router merges tributaries with
junctions in whatever order its nets arrive; the grouping fixes which lanes may
share a belt, and a lane carrying `count` pilers is split into `count + 1` nets
(each piler's ports are a source and a sink like a splitter's), so the router
never needs to know about stacks: it routes belts between ports, and the pilers
sit where the strip put them.

There is no piler-throughput bound in this arithmetic. 5.1 pins the piler's
intake at 6 cargo/s per unit `beltSpeed`, which is exactly `BELT_RATE`, so
"the piler is slower than the belt" cannot happen and the branch that once
handled it is gone.

### 6.3 Geometry and emission

A piler is a tile-occupying inline device: 1x3 footprint along the lane
(`catalog.building(2040)` is `width=1, height=3`), port poses straight through,
ground level only in this design. Its pilers are emitted on the tiles at the
downstream end of the lane they stack, before that lane's junction into the
next belt (an output lane) or after the entry and before any sorter (an input
lane fed unstacked, which under rule 1 only happens for internal merges, never
for the player's bus). Where a lane carries two pilers in series they sit
consecutively along the lane with a belt tile between them, the second reading
the first's output. The belt before a piler names it as `output_obj`, the belt
after it names it as `input_obj`, and the piler itself names nobody, the
convention `junction.make_splitter` uses.

A new `junction.make_piler(x, y, z, *, yaw)` builds the record from the catalog
(item 2040, model 257). The unrotated footprint is 1x3; yaw 90 rotates it to
3x1, and the encoder stores the centre of that oriented footprint. The shipped
`piler` `portPoses` order is port 0 at `(dx=0, dy=+0.25)` facing north and port
1 at `(dx=0, dy=-0.25)` facing south before yaw is applied.

It takes no stack argument and writes no parameter block:
`PILER_STACK_PARAMETER = None`. `BlueprintUtils.GenerateBlueprintData`
0.10.34 lines 1181-1182 and 1222-1306 leave the piler's object references
null; its shipped catalog row has `multiLevel = 1`, so the multilevel branch
assigns `inputToSlot = 14`, `outputFromSlot = 15`, `inputFromSlot = 15`, and
`outputToSlot = 14`. `BlueprintBuilding.Export` lines 294-295 serializes the
null references as `-1`; and `BuildingParameters.ToParamsArray` lines 83-363
falls through with a zero parameter count, normalized to `int[0]` at
`BlueprintUtils.decompiled.cs:1297-1306`.

The connections live on the neighbouring belts.
`BlueprintUtils.decompiled.cs:1248-1272` makes the feeding belt name the piler
through `outputObj/outputToSlot = (piler, 1)` and the drawing belt name it
through `inputObj/inputFromSlot = (piler, 0)`.
`CargoTraffic.decompiled.cs:938-974` reads piler slots 0 and 1 and selects
`PilerState.Pile` when slot 0 is output and slot 1 input. Tests originate this
three-record shape, encode and decode it, and assert each field; they do not
fabricate or require a game-authored fixture.

The strip reserves each piler's three tiles, and the belt tile between
consecutive pilers, as a **tail extension**: `Strip` gains
`tail_extension: int` (0, or `4 x count - 1` for the largest `PilerPlan.count`
over its output lanes — `3 x count` tiles of piler plus the `count - 1`
separators, since a `PilerComponent` reads an input belt and an output belt and
two pilers cannot abut: 3 tiles for one piler, 7 for two in series) and
`pilers: tuple[PilerPlan, ...]`, `_box` includes the
extension on the side where output lanes exit, and the piled lane's belt row
runs through it with its pilers on those tiles after the last sorter.
Packing and routing therefore see the piler as part of the strip's footprint.
This is a pure width claim: only `_box` needs it, unlike `west_channel`, which
is an origin offset read wherever a strip's machines are placed. It is a new
reservation, not a reuse: the Spray Coater keep-out (`needs_coater_keepout`
in `plan_strips`) only widens the west channel from `WEST_CHANNEL` to
`_COATER_WEST_CHANNEL`, and nothing in `Strip` models an x-direction claim
for a lane. Every piler is on a producer strip's output lane (6.2); a
consumer's entry is the same belt, and rule 1 means the player's bus never
needs one, so there are no entry-side pilers. Any code that rebuilds a
`Strip` from a variant (the sequence solver does, when it realises a
reservation) must carry `tail_extension` and `pilers` through, and a test
pins that.

### 6.4 Validation

- `_kind` classifies item 2040 as `Kind.PILER` (today it falls through to
  `Kind.MACHINE` and would be handed to every machine check);
  `catalog.BELT_INTEGRATED_IDS` gains 2040 so `_context` does not put the
  piler in the `blocking` map under the belts it sits on; `_context`'s
  `junction_in` / `junction_out` collection, which today tests
  `kinds[...] is Kind.SPLITTER` explicitly, also accepts `Kind.PILER`;
  `_build_graph` crosses a piler as its fourth run boundary. `_build_runs`
  already breaks a run at any non-belt tile, so a piler needs no change
  there. `junction.colocated`'s premise (every attachment shares the
  junction's tile) does not hold for a piler, whose belts are one tile before
  and one tile after; the piler checks below replace it. `stack_of` for the run
  after a piler is `min(2 x stack_of(the run into it), 4)`: there is no stack
  parameter to read (5.1), so the doubling rule is the only source of the
  number, and two pilers in series are judged by applying it twice.
- `piler.input_rate` (ERROR): the run into a piler carries at most
  `BELT_RATE[tier]` cargo per second, i.e. the piler rule.
- `piler.ports` checks the two belts named around a piler dock on its port
  poses and run straight through it, mirroring `junction.ports`.
- `piler.tier_allowed` refuses a piler when `spec.piler_unlocked` is false or
  `spec.belt_stack == 1`.
- `flow.stack_pickable` from 5.5 covers sorters after a piler.

### 6.5 Retier interaction

As 5.6; the stack map now includes piler-fed runs.

## 7. Reporting

The CLI line and payload from the belt-tier design grow by: the stack in use
(`stack 1` or `stack 2 (URL ist=2)`), the number of pilers placed, and per
external item the number of entry lanes and why. `PlacementStats` gains
`pilers: float` and `entry_lanes_needed: float`. A refusal from 4.5 prints
the stack that would have carried the rate.

## 8. Testing

- Unit (A): `machine_cap` for a group at 4/s per machine is 7 at 30/s and 3
  at 12/s, and 15 at 30/s with planning stack 2; `partition_strip_variant`
  never exceeds it; a single machine over the ceiling refuses with the named
  rate.
- Layout (A): the deuteron URL with hydrogen belted in at 40/s builds under
  both strategies at Mk.III with two hydrogen entry lanes and validates
  clean; at Mk.II with no upgrade it builds with four.
- Unit (B): `stack_of` on hand-built placements: an entry belt at the URL
  stack; a sorter-placed run at the place stack; a merge of stack 2 and
  stack 1 reads 1; `flow.belt_capacity` passes 40 items/s on a Mk.III run at
  stack 2 and refuses it at stack 1; `flow.stack_pickable` fires for ANY
  sorter below the Pile Sorter on a stack-2 run (Mk.III is the sharpest case,
  since even the fastest non-Pile tier picks 1) and stays quiet for a Pile
  Sorter.
- Layout (B): the deuteron URL with `ist=2` and every technology researched
  builds with ONE hydrogen entry lane at 40 items/s and validates clean; the
  same URL with a technology set lacking the stacking research builds with
  two lanes (A's path) and says so in the report.
- Unit (C): the merge decision on hand-built lane sets: the 4 x 30 example
  yields four lanes at two pilers each (eight in all) to stack 4 and one
  shared trunk; two 20s yield one piler each to stack 2; five 30s yield a
  group of four and a group of one; a lane already at stack 2 needs one piler
  where an unstacked one needs two; a sink whose sorters pick only 1 forces
  parallel belts; a sink picking 3 is planned at stack 2, never at 3;
  ordering is deterministic across input permutations.
- Validator (C): each new check has a fires case and a clean case on
  hand-built placements; a piler fed above belt speed refuses.
- Codec (C): an originated piler-between-belts placement encodes and decodes
  with null piler links represented as `-1`, multilevel slot sentinels
  `(inputFrom, inputTo, outputFrom, outputTo) = (15, 14, 15, 14)`, an empty
  parameter tuple, and adjacent belt references to ordered ports 1 and 0.
  Separate yaw-0/yaw-90 assertions pin the catalog footprint and emitted centre.
- Corpus gate before and after each deliverable, evidence committed under
  `docs/superpowers/evidence/<date>-multiple-belts/`, `<date>-stacked-lanes/`
  and `<date>-pilers/`. A must not cost a clean cell; B and C must not cost a
  clean cell and must not change any cell whose URL has `ist=1`.

## 9. Sequencing and out of scope

A first; it needs no game data beyond what the repo has and fixes the reported
class of failure for every URL whose per-machine rates fit one belt. B second;
it needs the numbers in 5.1 (pinned on 2026-09-03) and no new building, and it
is what makes a stacked bus usable. C last; Task 11 derives its piler record
from the shipped 0.10.34 code and catalog, so no live fixture gate remains.
Each deliverable ends with its own gate.

Out of scope for all three: pilers on elevated lanes, unstacking devices (a
machine's sorter unstacks by picking), stacking lanes that already fit one
belt merely to shorten strips, lane multiplicity inside a strip (4.4, built
only if the gate asks), and any change to how FactorioLab's rate solver counts
belts.

## 10. Risks

- **Density (A).** Capacity-bounded strips are shorter. Mitigated by the cap
  binding only above the ceiling, by B removing most of it where the player
  stacks, and by 4.4's recovery.
- **Search heuristics (A).** The sequence solver's strip-length heuristics
  assume they set the length; with the cap underneath, a heuristic asking for
  12 may get 3. The plan adds a test that each heuristic's chosen length
  survives `min` with the cap without a crash, and the corpus gate catches the
  rest.
- **Sorter throughput (B).** SETTLED by 5.1: `SORTER_STACK_RATE_FACTOR` is
  true, so the place and pick stacks do enter `flow.sorter_capacity`'s
  arithmetic and the plan extends the check. What remains is that only the
  Pile Sorter carries a stack at all, so a save without it gains nothing here.
- **Coarsening (A).** `_coarsen_saturated_strip_plan` cannot collapse strips
  the cap keeps short, so a build over the coarse threshold whose lanes are
  above the ceiling keeps its many strips. A's gate counts those cells.
- **Unpickable bus (B).** A URL with `ist` above what the save's sorters can
  pick is refused rather than built at a lower stack; that is a new refusal
  class and the message names the research that removes it. 5.1 makes this
  broader than it looked: any `ist > 1` without the Pile Sorter is refused,
  because Mk.I to Mk.III pick 1 at every level.
- **Piler count (C).** A piler doubles rather than jumping to a setting (5.1),
  so a lane raised from unstacked to 4 costs two pilers and seven tiles of tail
  (`4 x 2 - 1`, the separator belt included), not one and three. Any estimate of area or building count made before this
  fact was pinned is low by a factor of two on those lanes.
- **Game facts (B, C).** SETTLED for the stacking ladders, sorter tables, rate
  factor, piler behaviour, and piler blueprint record. Section 5.1 pins the
  behaviour from shipped files. Section 6.3 pins record defaults and belt wiring
  from `BlueprintUtils`, `BlueprintBuilding.Export`,
  `BuildingParameters.ToParamsArray`, and `CargoTraffic.RematchPilerConnection`,
  and pins model 257's footprint and port ordering from the shipped catalog.
  No live game fixture or stack parameter remains to discover.
- **Mixed stacks (B).** The minimum rule is conservative; a build the game
  would run at a favourable average may be refused. Accepted: an optimistic
  capacity would emit builds that starve, which is worse than a refusal.
