# Multiple belts and Automatic Pilers above the fastest belt

Date: 2026-09-02. Status: design draft, awaiting review. Follows
`2026-09-02-belt-and-sorter-tiers-design.md`, whose section 11 hands this
work off.

## 1. Problem

After the belt-tier change, a belt run is raised to the fastest belt the save
can build, and a run whose demand still exceeds that belt is refused by
`flow.belt_capacity`. Three gaps remain, all measured in the current code:

- **Nothing bounds machines per strip by belt capacity.** `strip_variants.py::partition_strip_variant`
  takes a pure machine count (`max_machine_count`), fed by `plan_strips`'s
  `strip_len` (default 6), by `_coarsen_saturated_strip_plan` (which raises it
  to the whole machine count once a build has more than 40 strips), and by the
  sequence solver's three strip-length heuristics, all of which tune search
  cost and never read a rate. A strip of 8 particle colliders drawing 4 items/s
  each puts 32 items/s on one hydrogen lane, over Mk.III's 30.
- **Boundary lanes are created singly.** `_logical_strip_plans` gives every
  strip its own entry lane per external item and its own boundary sink per
  output, so an external input is already split across strips, but only as a
  side effect of strip count. The validator's `flow.external_entry_points`
  warns whenever one item enters at two or more lanes without saying whether
  the split was needed.
- **The Automatic Piler does not exist in runtime code.** Item 2040 is fully
  described in the asset data (`dsp/data/buildings.json`: footprint 1x3,
  model 257, `addonType 0`, `multiLevel`, `stackHeight 2.67`, two
  straight-through port poses in `dsp/data/slot_poses.json`; unlocked by
  `integrated-logistics-system` in the vendored FactorioLab data), and no
  module under `src/flab2bp/` mentions it. FactorioLab's belt-stack setting
  (`ist` in the URL, `LabRequest.stack`) is parsed and unused.

Concrete case: the deuteron-fuel-rod URL from the original report. Once the
recipe-selection fix lands (hydrogen belted in directly, as FactorioLab does),
hydrogen enters at 40 items/s, above any belt, and the build depends on the
strip count happening to keep each collider strip's lane under 30/s.

## 2. Decision

Two phases, each shippable on its own.

**Phase A, parallel belts.** A lane is one belt, and one belt carries at most
the ceiling. The strip planner caps machines per strip so that no lane a strip
owns can exceed `spec.lane_capacity`; every flow above the ceiling therefore
arrives and leaves on as many parallel lanes as it needs, through the
machinery that already gives each strip its own lanes. No new building. The
only refusal left is a single machine whose one-item rate exceeds the ceiling.

**Phase B, Automatic Pilers.** When FactorioLab's URL says the player stacks
belts (`ist` greater than 1) and the save has researched the piler and the
sorter cargo-stacking level that stack needs, a lane whose demand exceeds the
ceiling gets a piler at its head and is planned at `ceiling x stack` instead of
being split. Pilers are used only where a lane would otherwise need splitting,
never everywhere.

Rules that bind both phases:

1. **FactorioLab is authoritative.** Belt stacking is used only when the URL
   asked for it; FactorioLab computes its belt counts with that same stack
   factor, so this is what its "belts" column already assumes. A URL that
   says nothing about stacking gets Phase A only.
2. **The validator judges what was built, unchanged in kind.** `flow.belt_capacity`
   keeps comparing each run's measured demand against the run's own capacity;
   Phase B makes that capacity `tier speed x stack` for runs downstream of a
   piler. Nothing is argued at planning time that the validator does not then
   confirm.
3. **Refuse loudly at the one remaining edge.** A single machine whose single
   ingredient or product exceeds the effective ceiling is refused with a
   message that names the rate, the belt, and the stack that would fix it.

## 3. Phase A: capacity-aware strip sharding

### 3.1 The cap

`StripFamily` gains `machine_cap: int`, computed in
`strip_variants.generate_strip_families(spec)` from the spec alone:

```
max_rate    = max over the group's inputs_per_machine and outputs_per_machine values
machine_cap = max(1, floor(spec.lane_capacity / max_rate))
```

`partition_strip_variant(family, variant, max_machine_count=...)` takes
`min(max_machine_count, family.machine_cap)`. That is the single seam: every
caller (`plan_strips` in freeform, `_coarsen_saturated_strip_plan`, and the
sequence solver's partition at `sequence_solver.py:3045`) already passes
through it, so both strategies and every strip-length heuristic are bounded
without touching them.

Why `max_rate` over single items is enough: a strip's input lane for item X
carries exactly `count x inputs_per_machine[X]`, its output lanes for item Y
carry at most `count x outputs_per_machine[Y]` in total, and the planner's
existing shared-lane and merged-lane checks (`input_lane_fits`,
`_check_shared_lane_capacity`, `_merge_lanes`) still guard the case where
several items share one lane. With the cap in place, `_merge_lanes`'s
over-capacity `ValueError` becomes unreachable except for a single machine over
the ceiling, which is the refusal Phase A keeps.

### 3.2 Why runs stay bounded end to end

The router builds one net per source lane and destination lane, merges several
sources into one destination through junctions, and splits one source to
several destinations through splitters. A merged run into a consumer lane
carries at most that consumer strip's demand; a trunk out of a producer lane
carries at most that producer strip's output; both are bounded by 3.1. The
validator's `_run_demand` already propagates across junctions in both
directions, so what it measures is exactly what the cap bounded.

### 3.3 What changes for the player

Builds whose flows exceed the ceiling get more, shorter strips. External inputs
above the ceiling arrive at several entry lanes and the report says why:
`flow.external_entry_points` gains `detail["lanes_needed"]` (`ceil(demand /
capacity)`) and its message reads "hydrogen is belted in at 2 separate lanes;
40 items/s needs 2 lanes of 30/s" when the count matches the need, and keeps
today's wording when it exceeds it. The severity stays WARNING; the CLI and
web reports print the per-item lane counts next to the existing "inputs to
belt in" line.

Builds whose flows fit the ceiling are unchanged: the cap only binds where
today's strips would produce a lane the validator refuses.

### 3.4 Refusal

When `max_rate > spec.lane_capacity` for some group, `generate_strip_families`
raises `NoValidLayout` with the group, the item, the rate, the ceiling belt,
and (if stacking is unlocked but the URL did not ask for it) a note that
FactorioLab's belt stack setting would allow it. This replaces the late
`flow.belt_capacity` refusal for that case with an early, explained one.

## 4. Phase B: Automatic Pilers

### 4.1 Gate and stack level

`BuildSpec` gains `belt_stack: int = 1`. `_to_build_spec` sets it to
`min(request.stack, 4)` only when all of the following hold, else 1:

- `request.stack` is present and greater than 1 (FactorioLab's `ist`).
- `automatic-piler` is unlocked by the researched technologies
  (`integrated-logistics-system`), derived the same way as belt and sorter
  tiers in `lab/techs.py::logistics_tiers_for_request`, which gains a
  `piler: bool` field.
- The researched `sorter-cargo-stacking-N` level supports that stack for the
  sorters that will draw from stacked lanes. **Open item:** the mapping from
  stacking level to sorter stack size, and whether the Pile Sorter (`canStack`
  in the catalog) needs it at all, must be read from the game's technology
  table under `oracle/` before implementation; the spec records the rule as
  "stack is capped by what the save's sorters can pick" and the plan's first
  task is to pin the numbers with evidence.

`lane_capacity` stays the un-stacked ceiling. A new `stacked_lane_capacity`
property is `lane_capacity x belt_stack`.

### 4.2 Which lanes get a piler

In `generate_strip_families`, when `belt_stack > 1` and a group's
`machine_cap` under `lane_capacity` is smaller than under
`stacked_lane_capacity`, the family is planned against the stacked capacity
and every lane of that family whose demand exceeds `lane_capacity` is marked
`stacked=True` on its `LanePlan`. Lanes that fit the plain ceiling stay
un-stacked, so pilers appear only where a lane needed one. Boundary output
lanes and entry lanes are marked the same way from the same demand.

### 4.3 Geometry and emission

A piler is a tile-occupying inline device: 1x3 footprint along the lane, port
poses straight through, `multiLevel`, at ground level only in this design. It
is emitted at the head of a stacked lane, on the three tiles after the lane's
entry (for an input lane) or the three tiles after the last sorter (for an
output lane), before any sorter touches the lane. The belt before it names it
as `output_obj`, the belt after it names it as `input_obj`, and the piler
itself names nobody, exactly the convention `junction.make_splitter` uses. A
new `junction.make_piler(x, y, z, yaw)` builds the record from the catalog
(item 2040, model 257) and `dsp/codec.py` serialises it like any building;
the byte-identical re-encode guarantee needs one player-built blueprint that
contains a piler in `tests/fixtures/`. **Prerequisite:** obtain that fixture
from the game before Phase B starts; without it the piler's parameters and
port anchors are unverified.

The lane reserves the piler's three tiles in the strip's pitch the same way
the Spray Coater's keep-out is reserved today (`needs_coater_keepout` in
`plan_strips`), so packing and routing see it as part of the strip.

### 4.4 Validation

- `_kind` classifies item 2040 as `Kind.PILER`; `_context` collects piler
  attachments into `junction_in` / `junction_out` like a splitter, so
  `_build_runs` breaks runs at a piler and `_run_demand` propagates through it.
- A new `Context.stack_of(run)` walks upstream through junctions: a run fed
  (directly or through splitters and merges) by a piler has stack
  `spec.belt_stack`, else 1. Merging a stacked and an un-stacked run onto one
  belt is an error (`flow.stack_mixed`): the game would carry mixed stacks and
  the rate arithmetic would be wrong.
- `flow.belt_capacity` compares demand against `BELT_RATE[tier] x stack_of(run)`.
- `piler.ports` checks the two belts named around a piler dock on its port
  poses and run straight through it, mirroring `junction.ports` and
  `junction.port_pose`.
- `piler.tier_allowed` refuses a piler when `spec.belt_stack == 1`.
- `flow.stack_supported` refuses a sorter drawing from a stacked run when the
  spec's sorter stacking level cannot pick that stack (the open item in 4.1).

### 4.5 Retier interaction

The retier pass from the belt-tier design runs after routing and measures each
run's demand. With pilers it divides a run's demand by `stack_of(run)` before
choosing the cheapest tier, using the same `belt_run_demands` machinery
extended with the stack map, so a stacked Mk.II run carrying 20 items/s at
stack 2 keeps Mk.II.

## 5. Reporting

The CLI line and payload from the belt-tier design grow by: the stack in use
(`stack 1` or `stack 2 (URL ist=2)`), the number of pilers placed, and per
external item the number of entry lanes and why. `PlacementStats` gains
`pilers: float` and `entry_lanes_needed: float`.

## 6. Testing

- Unit: `machine_cap` for a group at 4/s per machine is 7 at 30/s and 3 at
  12/s; `partition_strip_variant` never exceeds it; a single machine over the
  ceiling refuses with the named rate.
- Layout: the deuteron URL with hydrogen belted in at 40/s (the recipe-fix
  branch's flow) builds under both strategies at Mk.III with two hydrogen entry
  lanes and validates clean; at Mk.II with no upgrade it builds with four.
- Validator: `flow.external_entry_points` reports `lanes_needed`; with Phase B,
  each new check has a fires case and a clean case on hand-built placements,
  and a stacked run over `tier x stack` still refuses.
- Codec: the piler fixture re-encodes byte-identically and its port anchors
  land on the neighbouring belts (the geometry oracle in
  `tests/dsp/test_local_offset.py`).
- Corpus gate before and after each phase, evidence committed under
  `docs/superpowers/evidence/<date>-multiple-belts/` and `<date>-pilers/`. Phase
  A must not cost a clean cell; the expected effect is more clean cells, not
  fewer, since the cap only binds where a lane would have been refused.

## 7. Sequencing and out of scope

Phase A first; it needs no game data beyond what the repo has and fixes the
reported class of failure completely for every URL whose per-machine rates fit
one belt. Phase B starts once the piler fixture exists and the stacking level
mapping is pinned; it changes the codec, the validator's run model and the
emitter, and is its own plan.

Out of scope for both: pilers on elevated lanes, unstacking devices (a machine's
sorter unstacks by picking), stacking internal lanes that already fit one belt
merely to shorten strips, and any change to how FactorioLab's rate solver
counts belts.

## 8. Risks

- **Density.** Capacity-bounded strips are shorter, which can grow the layout
  and the router's net count on high-rate builds. Mitigation: the cap only
  binds above the ceiling, and Phase B removes most of it where the player
  stacks.
- **Search heuristics.** The sequence solver's strip-length heuristics assume
  they set the length; with the cap underneath, a heuristic asking for 12 may
  get 3. The plan adds a test that each heuristic's chosen length survives
  `min` with the cap without a crash, and the corpus gate catches the rest.
- **Game facts for Phase B** (stacking level mapping, piler parameters, port
  anchors) are the largest unknown and are made prerequisites rather than
  assumptions.
