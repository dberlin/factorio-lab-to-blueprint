# Backlog

## RESOLVED -- it was never the router. A port did not know its own altitude.

This entry said freeform's A* strands nets under congestion on a proliferated
`super-magnetic-ring`, and that a PathFinder-style history term was the missing
piece. Both halves were wrong, and the second was disproved expensively before
the first was understood: real negotiated congestion was built, measured at
parity-to-slightly-worse over 12 interleaved paired rounds, and is parked
unmerged on `pathfinder-router`.

**THE CLUE WAS IN THAT WORK'S OWN FAILURE TAXONOMY.** Counted over every search
that returned `None`, 422 of 600 were handed an EMPTY START OR GOAL SET -- a
search that expands zero nodes. That registers no conflict, so no history term
of any weight can price it, which is exactly why negotiation moved the
goal-set failures and could not touch the rest. A router cannot route to a cell
it is never told to look at.

**THE CAUSE IS ONE MISSING FIELD.** `_Port` carried x and y and no z. A Spray
Coater's proliferator drop belt sits one altitude LEVEL up -- its addon area is
at `(0, -1.25, 1)` -- while every lane port sits at 0, and both
`_reserve_port_access` and the router's start/goal construction looked for a
free cell beside a port at hard-coded level 0 regardless. For a drop that is the
plane BELOW it, and that plane is solid lane belt. The drop reported no free
neighbour, no access cell could be held, and the search began with nowhere to
go.

Measured on the URL it was reported against, same command both ways:

    before   no-proliferator only, 2028 tiles; both proliferated candidates
             refused with "no packing of N strips could be wired"
    after    max-proliferation, 1326 tiles

Corpus, freeform, four runs: **64, 65, 66, 63 of 72** against ~35 before.
INVALID 0 in every run.

**WHAT IS PINNED, AND WHAT IS NOT.** The same correction lands in three places:
goal cells, start cells, and the reservation pass.
`TestAPortKnowsItsOwnAltitude` kills the GOAL mutant. The start and reservation
mutants SURVIVE -- this corpus never exercises a drop as a search SOURCE,
because the chain reaches every drop as a destination. They are kept as the
identical defect in sibling paths, and they are unexercised rather than
verified.

**EVERY ROUTER-SIDE REFUSAL ON THE CORPUS IS GONE.** All six that remain are
`universe-matrix`, and all six are the zero-length `slotPoses` case -- see the
Ray Receiver / Energy Exchanger entry below. There is no "no packing could be
wired" refusal left anywhere in the corpus.

**WHERE NOT TO START, still true and now for a better reason.** `_route_all`'s
docstrings record what has been measured and rejected on this failure --
promoting last round's failures to the front is noise, and the history term
cannot see overuse because a committed path is `blocked` rather than dear. Those
findings stand. They were simply aimed at 2.5% of the problem.

## RESOLVED -- `prolif.coaters_are_supplied` is pinned on a real spec now

The guard this entry described has been replaced by the assertion it was holding
a place for. The check could not fail while the only candidate freeform built
contained zero coaters, and widening the sample did not rescue it because every
coater a wider sample offered came from a candidate of a URL that never
requested proliferation -- which this project may not assert against.

`super-magnetic-ring`, the one corpus URL that does request it, now builds its
proliferated candidates, so `test_every_candidate_supplies_its_coaters` asserts
`prolif.coaters_are_supplied` on a real proliferated build. It carries a
containment assertion on the coater count, because this test has been vacuous
twice and the second time survived a deliberate widening.

## RESOLVED -- it was ten checks, not three, and the first cause was not `group_for`

The entry below is kept as written, because two of the things it states with
confidence turned out to be wrong in ways that mattered, and the shape of that
error is worth more than a tidy summary.

**What the diagnosis got right.** `Context._group_for` really does resolve a
machine through `recipe_name(b.recipe_id)`, a mode-driven machine really does
carry `recipe_id == 0` by design, and `IdMap.recipes` really has no entry for
one. Every caller really did open with `if g is None: continue`.

**What it got wrong, first cause.** Fixing `group_for` alone would have changed
NOTHING, and the entry's own measurement contains the clue: it reports
`machine.recipe_valid` as not firing, on a placement of two machines whose
`recipe_id` is zero -- which is precisely what that check is for. The reason is
that DSP gives an Energy Exchanger a power cover radius of 7 and a Ray Receiver
one of 10.5. They are power NODES as well as machines, `_kind` tested
`cover_radius > 0` before anything else, and both fell out as `Kind.POWER`. Every
one of these checks iterates `of_kind(Kind.MACHINE)`, so the exchanger was never
handed to any of them and `group_for` was never reached for it at all.

MEASURED, at 9bc6963, on a hand-built two-exchanger placement with a spec
attached (both strategies now refuse or crash on the spec, see below):

    kinds: ['power', 'power']     <- classified as power nodes, not machines
    2 buildings, 2 Energy Exchangers, 0 sorters
    report.ok = True, errors = []
    machine.recipe_valid, machine.inputs_supplied, machine.output_removed,
    flow.lane_sourced, flow.conservation, flow.belt_capacity,
    flow.sorter_capacity, flow.headroom, flow.lane_attribution,
    prolif.belt_required_edges_not_direct_inserted
        -- all ten in checks_run, all ten with 0 findings

and the same placement on this commit:

    kinds: ['machine', 'machine']
    report.ok = False
    machine.inputs_supplied  x2   "needs 1 distinct ingredients, but only 0 sorters feed it"
    machine.output_removed   x2   "only 0 sorters drain it; it would back up"

**What it got wrong, blast radius.** The entry names three ERROR checks and
three helpers. The transitive closure of `Context.group_for` over this module's
call graph is TEN checks. Three call it directly; five -- `flow.conservation`,
`flow.sorter_capacity`, `flow.belt_capacity`, `flow.headroom`,
`flow.lane_attribution` -- arrive through `_lane_balance`, `_sorter_demand`,
`_run_demand` and `_sorter_item`; and two more, `spec.machine_counts` and
`prolif.belt_required_edges_not_direct_inserted`, resolved a machine through the
raw recipe id by a separate door. That is the third time on this branch that
counting a subsystem's consumers found roughly twice what was assumed. The count
is not maintained by hand: `test_every_check_that_consults_group_for_declares_it`
recomputes the closure from the module's own source and fails if `NEEDS_GROUPS`
drifts from it.

`spec.machine_counts` is worth naming separately, because making the exchanger
visible turned it from silent into WRONG: it keyed counts on the raw
`(recipe_id, item_id)` pair, so it reported "recipe 0 on machine 2209: spec
demands 0, placement has 2" for a spec demanding exactly 2. It is keyed by
resolved group now.

**What landed.**

* `_kind` answers MACHINE for a mode-driven building; `_tower_centres` selects
  power nodes on the catalog fact (`cover_radius > 0`) instead of on `Kind`, in
  placement order, so the tower set and `power.connectivity`'s BFS root are
  unchanged. An exchanger still powers itself: corner-to-centre is sqrt(32) =
  5.66 against a radius of 7.
* `_group_for` resolves a mode-driven machine by the pair the placement actually
  carries -- which building it is, and which mode its parameter block selects.
  The block is part of the key and not a tie-break: charge and discharge run on
  the same Energy Exchanger and their item flows are exact opposites.
* `machine.recipe_valid` accepts a mode block as configuration, and now FIRES on
  a mode-driven machine carrying neither -- which is `_machine_config`'s "exactly
  one of the two, never half of each" held at the other end.
* `machine.group_resolved`, a new ERROR check, owns the inability: one finding
  per unresolvable machine rather than ten, and a build nothing can validate
  fails instead of passing by default.
* `NEEDS_GROUPS`: those ten checks still RUN when a machine is unresolvable, and
  their findings still stand, but they are reported in `Report.skipped` rather
  than `checks_run`. `checks_run` is a claim of coverage; `skipped` already meant
  "silence proves nothing here", and now means it for partial coverage too.
  `scripts/ab_compare.py` already treats any non-power skip as a failed verdict,
  so this composes with the existing A/B gate without touching it.

**Deliberately NOT guessed.** FactorioLab's two Ray Receiver photon recipes --
with and without a Graviton Lens -- emit the SAME parameter block, because the
lens is an item the receiver consumes rather than a different setting. A placed
receiver therefore carries nothing that says which group it realises, and their
ingredient lists differ. `_mode_driven_group` returns `None` for that, and
`machine.group_resolved` reports it. Picking the first candidate is a fallback
with a wrong answer in it; it is a mutation in the battery and it is killed.

**WHAT THIS CATCHES ON THE CORPUS TODAY: NOTHING, and the reason matters.**

The first A/B run here was worthless in the way four earlier ones on this branch
were: `--tier small`, three runs before and after, spine 14/30 and freeform
22/30 with INVALID 0, identical -- over a corpus slice containing not one
mode-driven machine. It could not have failed.

Counting the shape first: across all 12 corpus entries x 4 candidates, 476
machine groups, **4 of them are mode-driven, all `critical-photon` on
`universe-matrix`** -- a stress-tier entry the small tier never reaches. So the
cell was audited directly, `--only universe-matrix --budget 4`, three runs each
arm:

    HEAD 9bc6963   spine 0/6 clean (refused 6, invalid 0, crashed 0)
                   freeform 0/6 clean (refused 0, invalid 0, crashed 6)
    this commit    identical, all three runs, both arms

Identical, because the only corpus build carrying a Ray Receiver never reaches
the validator at all: spine refuses it and freeform crashes on it, before and
after. **INVALID stays 0 everywhere measured.** The fix costs nothing; what it
catches is not yet demonstrable on the corpus, and the honest statement is that
the evidence it works is the hand-built measurement above, not the audit.

**Still open, and NOT this branch's to fix.** That is the same gap seen from the
other side. Neither strategy can produce a mode-driven placement today, which is
why the measurement above is hand-built rather than laid out: spine refuses the
two-exchanger spec by design (see the entry below, and
`test_spine_refuses_the_machine_rather_than_shipping_it_unwired`), and freeform
raises `IndexError` in `_emit_strip` on it at 9bc6963 --
`TestModeDrivenMachines::test_it_lays_out` is red on the branch as it stands, in
a file this work does not own. So the validator can now judge a mode-driven
machine, and nothing yet hands it one. Closing that from the layout end is what
would turn the audit into evidence.

One wording nit left alone: `cli.py` prints skipped checks as "could not run",
which is now sometimes "could not run over everything". Not changed, to keep out
of a file this work has no business in.

## The original entry, as written

A check that passes a build containing NO SORTERS AT ALL is not doing the job its
name claims, and `machine.inputs_supplied` does exactly that today.

MEASURED, on the code before the per-side tap charge, with the two-exchanger spec
from `TestModeDrivenMachines`:

    49 buildings, 2 Energy Exchangers, 0 sorters in the entire placement
    report.ok = True, errors = []
    machine.inputs_supplied  ran (it is in checks_run, not skipped) and did NOT fire
    machine.output_removed   likewise

The cause is one line, and it is not in the check. `Context._group_for` resolves
a placed machine to its `MachineGroup` through `recipe_name(b.recipe_id)`. A
mode-driven machine carries `recipe_id == 0` **by design** -- that is the whole
point of `_machine_config`, the mode lives in the parameter block instead -- and
`IdMap.recipes` has no entry for such a recipe at all, so there is not even a
real id to resolve. `group_for` returns `None`, and every caller opens with
`if g is None: continue`.

So the machine is not judged leniently; it is not judged. Everything that routes
through `group_for` skips it:

    machine.inputs_supplied     ERROR check
    machine.output_removed      ERROR check
    flow.lane_sourced           ERROR check
    _lane_balance, _sorter_demand, _sorter_item     helpers under other checks

`catalog.MODE_DRIVEN_MACHINE` names the affected recipes -- an Energy Exchanger's
charge/discharge, a Ray Receiver's photon/power -- so the blast radius is a
CLASS of machine, not a fluke of this one spec. Any build containing one has
three of its error checks quietly not applied to it.

Not fixed here, and deliberately: the fix belongs in `validate.py`, which this
branch does not own. Two shapes to weigh when it is picked up. `group_for` could
fall back to matching a placed machine to a group by `item_id` plus parameter
block when the recipe id is zero; or `_group_for` returning `None` for a building
that IS a machine could itself be a finding, on the ground that "this check could
not be evaluated here" is information the `skipped` field already exists to
carry, and silence is the one answer that must not be available.

Related but separate: the machines in the measurement above have no sorters
because the game gives them no sorter slots -- see the entry below.

## RESOLVED -- the extraction is complete; these buildings take belts, not sorters

The open question was whether `scripts/extract_dsp_slot_poses.py` was missing an
array. **It is not. There is no array to miss.** Settled from the game's own
prefabs and its own IL, not inferred.

**The prefabs.** Reading `resources.assets` directly: `ray-receiver` and
`energy-exchanger` each carry exactly ONE `SlotConfig`, on the prefab root --
which is what `GetComponentInChildren<SlotConfig>(true)` picks -- with

    ray-receiver       slotPoses(ports) 2   insertPoses 0   addonAreaCenter 0
    energy-exchanger   slotPoses(ports) 4   insertPoses 0   addonAreaCenter 0
    chemical-plant     slotPoses(ports) 0   insertPoses 8   addonAreaCenter 0
    assembler-mk-1     slotPoses(ports) 0   insertPoses 12  addonAreaCenter 0
    spray-coater       slotPoses(ports) 0   insertPoses 0   addonAreaCenter 2

and their only pose children are named `slot-0`, `slot-1` and `slot(0)`..`slot(3)`
-- the BELT PORTS. There are no `insert-*` children and no third array. The
extractor already reads every field the component has.

**The IL.** `BuildTool_Inserter` (`Assembly-CSharp.dll`, decompiled with
`ilspycmd`) drops any cast target that has no insert pose:

```csharp
if (prefabDesc != null && (prefabDesc.slotPoses == null
        || prefabDesc.slotPoses.Length == 0) && !prefabDesc.isBelt)
{ castObject = false; castObjectId = 0; castObjectPos = Vector3.zero; }
```

and `PrefabDesc.slotPoses` is `SlotConfig.insertPoses` (`PrefabDesc.ReadPrefab`,
lines 1208-1221). **So no sorter can ever attach to either building, on any
face, at any distance.** `BuildTool_Path` is the mirror image and shows what does
attach:

```csharp
if (prefabDesc2 != null && (prefabDesc2.portPoses == null || prefabDesc2.portPoses.Length == 0)
        && (prefabDesc2.addonAreaColPoses == null || prefabDesc2.addonAreaColPoses.Length == 0)
        && !prefabDesc2.isBelt)
{ castObject = false; ... }
```

A BELT may target a building with `portPoses` -- and the belt is what carries the
connection, not the building.

**The corpus agrees, and it is not a small sample.** 45 Energy Exchangers across
three fixtures, 90 peers naming them, and **every single peer is a belt. Zero
sorters.** The exchangers themselves carry `input_obj = output_obj = -1`. The
belts sit at 2.27 or 3.00 tiles from the exchanger centre -- inside its 11.7-wide
box, i.e. running UNDER it -- and carry `in_obj=<exchanger> in_from=2` (drawing
out of port 2) or `out_obj=<exchanger> out_to=0` (feeding into port 0). The
`falk` fixture uses the ±x ports, 1 and 3, the same way. There is no Ray Receiver
anywhere in the 13,690-building fixture corpus, so the exchanger is the whole of
the direct evidence -- but it is the same mechanism and the same two IL lines.

So the class is not "two odd prefabs". Nine buildings reachable as a spec group
have zero insert poses -- fractionator, energy-exchanger, ray-receiver,
ray-receiver-pro, orbital-collector, both mining machines, water-pump,
oil-extractor -- and every one of them is a belt-port building. The Spray Coater
is the fourth kind again: zero insert poses, zero ports, and fed through
`addonAreaPoses`.

**Spine's refusal was correct, and it was blaming the wrong thing.** It arrived
as `FALLBACK_SEED_UNWIRABLE`: *"row 1 (critical-photon#4) taps 1 lanes that no
ordering of its two corridors puts in reach; machine heights differ by up to 6
tiles and the face looking up costs up to 3."* Corridor ordering and a height
difference are real causes of a real refusal and neither is what is wrong here,
so the message sent a reader to the packer. It is now
`FALLBACK_SORTERLESS_MACHINE`, raised by `_sorterless_groups` before a single row
is packed, and it names the prefab: *"ray-receiver (critical-photon#4) has 0
insert poses and 2 belt port(s), but must wire critical-photon."*

Measured: exactly **3 of 36 corpus specs** contain such a machine, all three
`universe-matrix`, all three the same Ray Receiver -- so the check's blast radius
is the six cells that already refused, decided without running one CP-SAT solve.
The six now refuse in 0.0s instead of 0.5-9.6s, because the answer never needed
the solver.

**The "stop demanding lanes for it" fix does not apply, and it is worth saying
why.** The Ray Receiver in the corpus spec has `inputs_per_machine == {}` -- it
is a pure source, given photons by a Dyson sphere, not fed anything. The single
lane spine wants for it is the critical-photon OUTPUT, and that demand is
correct: a Ray Receiver that reaches no belt is an idle Ray Receiver, which is
exactly the two-idle-exchangers placement this entry was opened over.

### What is left OPEN: belt-to-port docking, and it is blocked

To build `universe-matrix` we need a belt that ends at a port pose and carries
`input_obj = <machine>, input_from_slot = <port index>`. Two things stand in the
way and only the first is small:

* **The emitter has no such connection.** Every machine-to-lane join in both
  strategies is a sorter. A belt tile that docks into a port is a new kind of
  edge for the router, the lane model, `flow.conservation` and the writer.
* **The port is INSIDE the footprint, and our collision model is a tile grid.**
  Ray Receiver ports are at model `(0, 0, ±1.41)` on a 5-tile axis whose half
  extent is 2.7; the Energy Exchanger's are at `±2.85` inside a half extent of
  5.85, and the real fixtures put their belts at 2.27 and 3.00 -- under the
  building. A belt overlapping a machine is legal in game and illegal in our
  grid. That is the OPEN entry *"our footprints are a tile grid; the game's
  collision is not"* at the bottom of this file, and this work sits behind it.

Until then the refusal stands and is honest. `_machine_config` still owns the
charge/discharge parameter block and is tested directly, so that coverage did not
go with the removed placement.

**Freeform is unchanged and needs the same correction.** Its
`_machines_without_poses` owns the case there and refuses correctly, but its
docstring argues from a false premise: *"a Ray Receiver IS fed in game, so it
either carries its slots in an array the extractor does not read or takes items
by some other mechanism"*. It is fed nothing -- it consumes no item at all, and
its OUTPUT is what needs a belt. That file was being edited on master while this
was written, so the correction was reported rather than made.

The other half of what the original measurement showed -- that `validate` called
that unwired placement clean -- is its own entry above, and is unrelated to the
extraction: it would skip these machines just as silently if the slot table were
complete.

## RESOLVED -- the tap-capacity model is per side, and two errors cancelling hid it

Fixed and measured; "WHAT LANDED" at the end of this entry has the numbers. The
diagnosis and the map are kept as they were written, because they are the durable
part and because the map is what corrected the diagnosis.

DIAGNOSED, then fixed. This was the whole of the remaining spine
`machine.inputs_supplied` failure -- ten tests, and every one of them a machine
one ingredient short.

`_allocate_lanes` already carries the right concept for the corridor BELOW a
row. Its docstring states the failure exactly: "the lane is allocated below,
`_find_tap` correctly refuses to wire something out of reach, and the machine
simply gets no sorter for that item at all". A short machine in a tall row stops
above the row's floor, so every lane below it is that gap further away, and
`above_gap` / `_fits_below` order and cap the band to match.

The same thing happens on the corridor ABOVE, for a different reason, and the
model says that side "costs it nothing". A Chemical Plant's poses on that face
sit a row INSIDE its five-deep footprint, so a sorter reaching one is a tile
longer than the gap suggests. Measured, usable lane depths per corridor:

    Chemical Plant, Quantum Chemical Plant    above 2    below 3
    Assembler, Oil Refinery, Matrix Lab       above 3    below 3

The model assumes 3 and 3 for everything. Every rejected tap in the failing
specs was on the `above` side at a gap of 3 or more -- the third depth a plant
cannot reach -- and `_find_taps` correctly refused each one after the allocator
had already put the item there.

Note the asymmetry, because it is why the first attempt missed. `_Group.tap_height`
folds the inset into the gap model as if it applied to both sides, and it changed
none of the ten failures: the gap thresholds are not the per-corridor DEPTH cap,
and taking the worse side for both is not what the geometry says.

THE ALLOCATOR-ONLY FIX WAS BUILT AND IT MADE THINGS WORSE. Mirroring `above_gap`
exactly -- a `below_inset`, the same `_fits_below` greedy with the inset in place
of the gap, the band ordered worst-inset-first, and then the mirror of
`gap_first` so an inset item prefers the side without one -- took spine from 10
failures to 12. `graphene` regressed: a Chemical Plant running sulfuric-acid
still ends one ingredient short, now because the allocator correctly refuses to
seat a third item upward and cannot find room downward either.

That result is worth more than the change was. It says the constraint is real and
the allocator is not where it can be satisfied: if a row's plant can take only
two lanes upward and its ingredients want three, no seating order fixes it --
the ROW is wrong, and the row is chosen by CP-SAT. So the asymmetric per-side cap
has to reach the tap-capacity model, which is what decides that a plant may share
a row at all.

The bound I checked earlier and dismissed was the wrong one: a group's TOTAL lane
need (4) against its total reach (2 + 3 = 5) is not binding, but its need on ONE
SIDE against that side's cap is. A row of items that all prefer upward puts three
against a cap of two, and nothing downstream can undo it.

Do not attempt the allocator half again on its own; it is measured, reverted, and
recorded here precisely so the next attempt starts at the model.

### THE MAP -- every place that computes or consumes a tap-capacity bound

Enumerated before touching anything, in the form that worked for the strip's row
layout. Twenty-four sites; four of them are silently WRONG rather than merely
loose, and two of those four are in code that never says `inset`.

**The truth, and the two numbers derived from it**

| # | site | computes | side |
| --- | --- | --- | --- |
| 1 | `_anchor_span(id, yaw, h, gap, above=)` `spine.py:3128` | tiles a sorter must span from a lane `gap` clear, or `None` | PER SIDE, per gap -- the ground truth |
| 2 | `_anchor_inset(id, yaw, h)` `spine.py:3111` | `max` over the two sides of `span(gap=1) - 1` | collapses (1) to ONE number; the asymmetry dies here |
| 3 | `_Group.tap_height` `spine.py:195` | `height - _anchor_inset` | the only carrier of the inset into any model; three consumers |

Measured from (1), every machine the corpus uses:

    Chemical Plant, Quantum Chemical Plant   above 2  below 3   spans above [2,3,-,-] below [1,2,3,-]
    Assembler Mk.II/III, Arc/Plane Smelter   above 3  below 3
    Oil Refinery (yaw 90), Matrix Lab,
      Miniature Particle Collider            above 3  below 3
    Ray Receiver                             above 0  below 0   (no attachable pose either side)

**The allocator, per row, after CP-SAT has chosen it**

| # | site | computes | side |
| --- | --- | --- | --- |
| 4 | `_allocate_lanes:741-746` | `row_h = max pitch_h`; `gaps[item] = row_h - tap_height` | per item, used on ONE side only |
| 5 | `_seat._room`, `slot is below` `:783` | `sum(copies) <= reach` for the corridor **above** the row | PER SIDE -- flat 3, no gap, no inset. **WRONG: 2 for a plant** |
| 6 | `_seat._room` else -> `_fits_below` `:393,784` | `g + j + 1 <= reach` for the corridor **below** the row | PER SIDE -- charges the ABOVE-side inset. **WRONG: 2 where truth is 3** |
| 7 | `_seat._compatible` `:804` | two items may share a lane only at equal `gaps` | the one-sided gap again |
| 8 | `_seat` `gap_first` `:859` | an item with `gaps > 0` is seated UPWARD first | **pushes a plant's items at the side that cannot take them** |
| 9 | `_allocate_lanes:887` | `need > 2 * reach` | AGGREGATE -- message only |
| 10 | `_allocate_lanes:942-945` | above-the-row band sorted worst-gap-shallowest; the other band plain `sorted` | correct only while the above side costs nothing |
| 11 | `lane_order` `geometry.py:111` | `len(band) <= max_reach`, both bands | PER SIDE, flat, cannot see the inset. Last gate before emission |
| 12 | `_cover_sprayed` `:974` | proliferator-to-coater lane spacing | lane-to-lane, not machine reach -- unaffected |

**CP-SAT, `_solve_one` -- what decides a plant may share a row at all**

| # | site | computes | side |
| --- | --- | --- | --- |
| 13 | flat tap capacity `:1306-1351` | `sum(lane_copies * tapped) <= 2 * tap_reach` = 6 | AGGREGATE. Truth for a plant's row is 2 + 3 = 5 |
| 14 | `over` / `can_share` `:1321-1326` | `sum(copies) > 2 * tap_reach` picks which items may be priced at half a lane | AGGREGATE, against the same overstated 6 |
| 15 | Hall family `:1394-1457` | `lanes with gap >= t <= tap_reach + max(0, tap_reach - t)` | AGGREGATE -- the leading `tap_reach` is the upper corridor, assumed full, unconditionally |
| 16 | `heights` `:1394` + `is_h: row_h[r] == h` `:1454` | reifies a PITCH-height variable against a set of TAP heights | **two different spaces** |
| 17 | `thresholds` `:1398` | `{min(b - a, tap_reach)}` over TAP-height differences | **the real gap is `row_h(pitch) - tap_height`** |
| 18 | `corridor_h[r+1] <= reach - 1` `:1558` | direct-insert span across a corridor | machine-to-machine, no inset |

**Emission**

| # | site | computes | side |
| --- | --- | --- | --- |
| 19 | `_realizable_direct:1845` | `dy` off `groups[src].height`, `1 <= dy <= reach` | no inset -- but `_emit`'s `_pair` re-checks with `direct_anchors` and RAISES, so it refuses rather than lying |
| 20 | `_find_taps:3234` | asks (1) directly | correct |
| 21 | `_emit:2413` `if not found ... continue` | -- | **the swallow point.** A refused tap becomes no sorter and no error |
| 22 | `_pick_sorter(rate, tap.span, widest)` `:2443` | tier from `_anchor_span`'s span and `attachable_columns`' count | already inset-aware; NOT freeform's silent-tier bug |
| 23 | `_place_sorters:3294` | `attachable_columns`, places nothing when empty | correct |
| 24 | `_coater_lane_candidates:3363` | lane-to-lane proliferator reach | unaffected |

**The four that produce a WRONG value rather than an infeasible model**

* **(5)** under-charges the above side by one. This is the whole of the ten
  failures. Traced on `casimir-crystal`: three refused taps, every one a Chemical
  Plant reaching UP at a gap of 3 or more, `_anchor_span` returning `None`, and
  each one swallowed by (21).
* **(6)** over-charges the below side by one, because `tap_height` takes the
  worse of the two sides and the plant's inset is on the other one.
* **(5) and (6) cancel in the TOTAL.** The allocator believes 3 above + 2 below;
  the truth is 2 above + 3 below. Both are 5. **That is why the aggregate check
  cleared the model** -- the earlier "4 needed against 2 + 3 = 5" was not merely
  the wrong bound, it was a bound the two errors had conspired to make look right.
* **(16)/(17)** put the whole height-aware family in the wrong number space, and
  neither mentions `inset`. `row_h` takes a PITCH height; `heights` are TAP
  heights, so `is_h` is false whenever the row's tallest pitch is not also some
  group's tap height. Measured over the twelve corpus specs: **9 of 12 have a
  realizable `row_h` the reification can never match**, and against real gaps of
  `pitch_h - tap_height` the threshold set is **absent in 3 specs and incomplete
  in 6**. A row whose tallest machine is a Chemical Plant (`row_h` 5, tap heights
  {3,4}) is exactly such a row -- so on `graphene` and `plastic`, the two specs
  the reverted allocator regressed, the height-aware constraint never fires at
  all and only the flat 6 applies. This is the strip's `mh`/`ph` bug, one module
  over: right by accident for as long as clearance and footprint were the same
  number, wrong since spacing made them differ.

**Where the asymmetry has to enter, and what it costs**

At (5) and (6) as two DIFFERENT numbers -- an `above_inset` and a `below_inset`
in place of one `tap_height` -- and at (13)/(15) as a two-dimensional threshold
family. Item `i`'s reachable lanes are a prefix of the corridor above of length
`A_i = reach - above_inset(i)`, which is **row-independent** because a machine is
flush with the top of its row, plus a prefix of the corridor below of length
`B_i = reach - (row_h - height(i) + below_inset(i))`. Two nested prefix families,
so Hall's condition is exactly

    for all a, b in 0..reach:   #{lanes i : A_i <= a and B_i <= b}  <=  a + b

and today's model is the single slice `a = reach` of it. Sixteen inequalities per
row where there is now one family, most of them non-binding and skippable by the
same "cannot bind even if the row took everything" test already at `:1433`.

Note what this is NOT: no side-assignment variable, no new decision, the same
`tapped_by` literals counted. **It is a tightened bound on the same feasibility
question**, not a different question -- so it is a correctness fix, not a density
decision, though it will refuse rows that pack today and the area cost has to be
measured paired and interleaved.

Not attempted here, and deliberately: it is three coupled changes (the allocator
mirror that already regressed 10 -> 12 on its own, the height-space repair, and
the `a` dimension), and the allocator half is measured-and-reverted precisely
because doing one of the three alone is what fails.

**One thing the map found that is not about the inset at all:** both tests in
`TestTapCapacityIsHeightAware` fail on their own PREMISE, not on the model.
`test_the_allocator_refuses_the_gapped_row` asserts
`sorted({heights}) == [3, 7]` and gets `[3]`, because rotation (`69eddea`) turns
the Oil Refinery a quarter turn and its 3x7 became a 7x3. `mixed_height_spec` is
uniform-height now, so the fixture built to exercise the height-aware bound
exercises nothing, and the whole family at `:1394-1457` has had **no test
coverage since rotation landed** -- which is how (16) and (17) survived the
spacing change. Repairing the fixture needs a real height gap out of what the
catalog now offers (tap heights are 3, 4 and 5; pitches run to 8) and a mutation
check that the repaired fixture fails with the constraint removed.

### WHAT LANDED, AND WHAT IT COST

Three changes, in one commit because each alone is measured to make things worse
or nothing: the allocator mirror (10 -> 12 on its own, `35c4210`), the
height-space repair, and the second Hall dimension.

`_reach_charge(item_id, yaw, h, above=)` replaces `_anchor_inset`, and
`above_charge` / `below_inset` replace `tap_height`. One rule now covers both
corridors -- lane `j` of a band, counted from the nearest, is reachable when
`charge + j + 1 <= reach` -- so `_fits_below` became `_fits_band` and serves
both, and the corridor above is ordered worst-charge-nearest exactly as the one
below always was. The CP-SAT family became

    lanes with up >= s and down >= t   <=   (reach - s) + (reach - t)

over both thresholds instead of the `s = 0` slice, keyed on PITCH heights, with
`row_h[r]` restricted by `add_allowed_assignments` to the values it can actually
take -- so the enumeration is exhaustive rather than hopeful.

MEASURED:

* **Suite 18 -> 9. Spine 10 -> 1**, and the one left is the Spray Coater
  refusal, which is the separate entry below. Freeform's 8 are untouched and
  cannot move: it imports three constant tables from spine and nothing else.
* Newly laid out, at budget 15 on the non-proliferated candidate, validator
  clean and no fallback: `casimir-crystal` REFUSED -> **20,328** tiles,
  `information-matrix` REFUSED -> **7,031**.
* **The density cost is real and here it is**: `graphene` 576 -> **600** tiles,
  +4.2%, on a candidate that already laid out. `plastic` unchanged at 656.
* Audit, tier mid (trivial+small+mid), budget 4, both arms interleaved, 3 runs
  each: spine 20/48 and freeform 26/48 in BOTH arms, **INVALID 0, crashed 0**,
  spine area **14,139 in both arms to the tile**, deterministic across runs.
  Freeform's -0.19% is its own run-to-run noise -- one cell moves between
  repeats within each arm, in both arms.

**AND THE AUDIT COULD NOT HAVE SHOWN THIS FIX WORKING.** All 84 spine refusals
across every tier up to mid are the Spray Coater; the corpus at those tiers
contains none of the shape under test, because the candidates that carry it are
sprayed and refused earlier for an unrelated reason. Reporting "audit unchanged"
as confirmation would have been the fourth sampling error of this session. What
the audit does say is the useful half: the tightened bound cost no density and no
cell anywhere it can see.

The fixtures are `pitch_gap_spec` and `inset_face_spec`, deliberate mirror
images -- three Assembling Machines whose 4-tile clearance gaps every lane below
them, and three Chemical Plants whose poses inset every lane above them. Both are
red on the pre-fix source and green after, and three mutations discriminate:
forcing `above_charge` to 0 kills only the inset tests, dropping the row gap from
`_below_charge` kills only the clearance tests, and removing the CP-SAT family
kills only the two packer tests while the four allocator and ground-truth tests
stay green.

Two fixtures were built and thrown away before these, both green for reasons that
had nothing to do with the claim, and both worth naming: one asserted heights
through `sorted({...})` over a SET, which deduplicated the thing it measured; the
other chained its three groups producer-to-consumer, and `_solve_one` orders
producers strictly above consumers, so the packer was never free to make the
packing the test said it must refuse.

## RESOLVED -- spine grows elevated lanes, and the drop was never the hard part

Spine used to refuse EVERY proliferated spec. It now builds them, and
`super-magnetic-ring*60/free-proliferation` validates clean with
`game.addon_supply` finding nothing -- at **2050 tiles against the
unproliferated candidate's 2832**, which is the whole point of proliferating.

**THE DIAGNOSIS IN THE ORIGINAL ENTRY WAS WRONG, and in an instructive way.**
It said spine "can only run lanes at ground level", so the work looked like
teaching it a new capability. `_feed_coater` had always placed the drop at
`z = 1`. What it could not do was REACH it: it required one proliferator tile to
be the lane's TAIL *and* be orthogonally adjacent to the drop, and nothing
arranges that coincidence -- `_coater_tile` picks the mount by nearness to the
lane's MIDPOINT while this needed the column beside where the lane ENDS, and a
lane has essentially one tail because `_relink_output` gives every other tile an
`output_obj`. A conjunction of two conditions optimised for by different code.
The capability was there; the reach was missing.

The tail requirement itself is real and stays: taking a mid-lane tile's output
orphans everything downstream -- the lane stops there and its remaining sorters
draw from a belt nothing fills, reported as `flow.external_entry_reachable`
rather than as anything about coaters.

**Three things it took, each found by measuring rather than by reasoning.**

1. **A spur**, elevated, from the tail to the drop -- replacing the conjunction.
2. **A chain.** The first spur consumes the lane's only tail, so coater two
   found no source and the candidate died with coater one already supplied.
   Coaters share one supply belt, which is what the corpus's "three coaters on
   one chain" case has always shown.
3. **A search, not two guesses.** The spur was first an L tried both ways
   round. That fails the moment a later coater wants past an earlier spur, and
   it read as a geometry limit when it was a search limit. It is a BFS now,
   bounded to the placement's existing bounding box -- a spur may not enlarge
   the factory to supply a coater -- and it takes the SHORTEST route over every
   candidate source rather than the first that works. Nearest-by-manhattan
   picked a source whose actual route was 68 tiles for a straight-line 34.

## OPEN -- spine's ten-coater case is a runway problem now, not a rules one

`super-magnetic-ring*60/max-proliferation` (10 spray lanes) still refuses, and
the refusal is now bounded by **a game rule this project has deliberately not
guessed** rather than by any weakness in the search. Nine of its ten spurs
place; the tenth finds no route.

Instrumented over the whole run, what blocks a spur tile:

    499  Conveyor Belt Mk.II  (same z)
    493  Assembling Machine Mk.II  (below)
    361  Arc Smelter  (below)
    449  Sorters, Splitters, Spray Coaters  (below)

`_spur_clear` refuses to fly over anything that is not a belt. A belt over a
belt is `BELT_CROSSING_CLEARANCE` and is established; a belt over a MACHINE was
the "may a belt cross a building, and at what height" question this file
recorded as unextracted.

**THE RULE IS NOW READ, and it is permissive.** `game.belt_crossing` in
`layout/validate.py` and `colliders.belt_crossing_height` carry it. A belt
preview is not tested with its box at all: `CheckBuildConditions` line 145761
probes it with a 0.23 sphere centred 0.2 above the node, and line 145872 excuses
a machine against a belt but NOT a belt against a machine. So a belt may cross a
machine, and the price is height:

    Sorter                 z > 0.7575    (excused anyway -- see below)
    Splitter               z > 1.7475
    Spray Coater           z > 1.8975    (excused anyway)
    Arc Smelter            z > 2.7975
    Assembling Machine     z > 3.5325
    Matrix Lab             z > 2.9475
    Chemical Plant         z > 4.9725

and sorters and belt addons are excused outright, so `_spur_clear` refuses over
449 blocks the game would have allowed at any height. Of the four blocker
classes, only the 493 assemblers and 361 smelters carry a real height price:
**z = 4 clears both** on the half-level grid, which is inside `buildMaxHeight`
from `labLevel >= 2`.

**So the refusal is NOT correct-permanently.** What it costs is runway:
`BELT_CLIMB_PER_TILE` is 1/2, so z = 4 is eight tiles of ramp up and eight down,
sixteen tiles a spur must find before it may cross anything. That is the number
the next step has to measure against -- whether the tenth spur has room for it --
and it is a search question now, not a rules question.

**Loosening `_spur_clear` blindly is still the wrong move.** The permission is
conditional on the height, and the height is per-model; a spur that flies at
z = 1 over an assembler still pastes as `EBuildCondition.Collide`. Use
`colliders.belt_crossing_height`, and turn `game.belt_crossing` on in whatever
audit measures the change.

**A STALE PARAGRAPH LIVED HERE** claiming freeform's out-lanes start
immediately below the machine FOOTPRINT, inside the row a machine's collider
needs, so a junction on one is always illegal. That was true when it was
written and is not now: `Strip.row_of_output` returns `first_row_below_band`,
i.e. `machine_row + ph`, so lanes already start after the CLEARANCE band. It was
checked before this was rewritten.

What is still true is the reason a junction beside a machine fails:
`junction.site_is_clear` needs `(splitter_clearance + machine_clearance) / 2`
tiles centre to centre, about three against an Assembling Machine, and a lane
sits one tile off the band by design. That is a distance no amount of band
tuning buys cheaply -- which is why the escape is height, above, and not a wider
corridor.

## RESOLVED -- the plant was loose because a tile was being read as 1.0 unit

`geom.collide` is a normal check now: 443 assembler-on-assembler pairs became 2,
and turning it on cost no coverage. All three questions this entry opened are
answered.

**A Chemical Plant was packed too LOOSE, and the collider was not the culprit --
the divisor was.** `derive_footprint` was `2 * ceil(box / 2) - 1`: a world-unit
half-extent compared against tile centres **one unit** apart, when they are
`GRID_ARC` = 1.2566 apart. It was also reading `blueprintBoxSize`, which the game
computes from the LAST Build box and which is therefore the one box
`buildColliders` excludes. The two errors point opposite ways, and on every
footprint the corpus pins they cancel exactly -- assembler 3, Matrix Lab 5, Arc
Smelter 3, Oil Refinery 3x7, Depot 3, Tesla Tower 1, Wind Turbine 3, Solar Panel
3 -- which is why the old rule had a clean sheet and why this looked like a
collider question. On the Chemical Plant they do not cancel: 8.20 with a unit
tile is 9 tiles; 8.60 with a real tile is **7**.

The rule is now `2 * ceil(e / GRID_ARC) - 1` over the collider AABB about the
building's own centre, and it is still ALWAYS ODD, so buildings stay
integer-centred and `tile_to_local_offset`'s half-tile branch stays unreachable.

The occupancy-versus-spacing worry this entry raised was the right worry and it
is settled by measurement, not by argument: **no building's `slotPoses` fall
outside its own footprint under the new rule**, and for the assembler, Matrix
Lab, Oil Refinery and Miniature Particle Collider they land *exactly* on the
edge tile. `test_every_footprint_contains_every_slot_pose` holds that. The
Chemical Plant's poses reach 1.59 tiles, needing 5; it now has 7. There was
never occupancy to lose -- there were two tiles per plant of pure padding.

Two further consequences, each an independent confirmation that the corrected
rule is the right one rather than merely a smaller one:

* `_FOOTPRINT_OVERRIDES` is **gone**. Both its entries were corrections to the
  unit error. Sorters derive 1x1, and the Energy Exchanger derives 9x9 -- the
  value `temple-of-effectiveness` bounds it at, where the old rule derived 11x11
  and stacked 209 cells in a blueprint the game itself wrote.
* `junction.make_splitter` was forcing 1x1 by hand against a catalog that said
  3x1. A splitter's arms reach 1.19 and a tile is 1.2566, so 1x1 is what the
  corrected rule derives. The hand-forcing is now a statement of intent rather
  than a correction.

The corpus arbitrates the source field as well as the divisor, which is what
this entry asked for. `factory-quick-start-step-3-red-cube` holds twelve Oil
Refineries and all eighteen machine-side sorter endpoints in it sit **three
tiles** from a refinery centre along the building's own axis.
`blueprintBoxSize` with the corrected divisor makes that refinery 3x5, which
reaches two, so every one of those eighteen sorters would miss the machine it
serves. The colliders make it 3x7.
`test_the_corpus_puts_sorter_ends_three_tiles_from_an_oil_refinery_centre` is
that measurement.

**The density it won**, paired and interleaved against master, three rounds
each, **INVALID 0 in every round of both arms**: freeform **-9.8%, -10.3%,
-9.8%** of total area over the full 72-cell corpus, on the cells clean in both
arms; spine **-1.80%**, identically in all three rounds, over the 48-cell mid
tier (32 cells clean in both, 5 of them moved). Clean counts were unmoved --
freeform A 63/66/64 against B 64/64/64, spine 32 against 32 -- so the area is
bought with packing rather than with coverage. The wins land where the Chemical
Plant does: freeform `graphene` -28%, `information-matrix` -21% to -42%,
`plastic` -19%, `quantum-chip` -28%; spine `plastic` -21%, `graphene` -18%. See
the footprint entry at the end of this file for the one real bug the change
surfaced on the way (a Spray Coater emitted a tile off its own belt).

**A Splitter one tile from a Tesla Tower collides** -- CONFIRMED from the game,
and it is the plain pitch requirement it looked like. A splitter is a CROSS of
two boxes reaching 1.19 units from its centre, a tower reaches 0.3, and
1.19 + 0.3 is more than one tile of 1.2566. Two tiles clears it;
`tests/dsp/test_colliders.py::test_a_splitter_is_not_a_belt_and_is_box_tested`
pins both sides.

**An elevated Splitter diagonally over an Assembling Machine collides** --
CONFIRMED, and the framing this entry used for it was WRONG. It is not "a belt
at level 1 passing over a machine". `PrefabDesc.ReadPrefab` line 217564 sets
`isBelt = beltSpeed > 0` from a `BeltDesc`; a Splitter takes the `SplitterDesc`
branch four lines later and sets `isSplitter`. A Splitter is therefore
box-tested like any machine, and the belt sphere rule does not reach it at all.
Box against box, an assembler's collider reaches 1.91 and a splitter's arm 1.19,
so the pair needs **three tiles** of diagonal separation, or **z = 4** -- above
the assembler's 4.68-unit collider top, exactly the height a belt would need,
but for the box reason. `geom.collide` already asks this question correctly;
what was missing was only the reading of it.

The crossing rule the second question was blocked on is read; see
"spine's ten-coater case" above and `game.belt_crossing`.

Note also that `catalog.clearance` takes an AABB over every collider box, so a
cross-shaped building like the Splitter reserves its empty corners too.
`geom.collide` tests the real boxes and knows better; the clearance is the
conservative one, and where the two disagree it is the clearance that
over-reserves.

## OPEN -- the layout obeys the slot tables now; what it cannot serve is geometry

The game's own predicates are ported (`game.inserter_data`,
`game.inserter_paste`, `game.inserter_skew`, `game.addon_supply` in
`layout/validate.py`), the real `PrefabDesc.slotPoses` and `addonAreaPoses`
tables are extracted from the game's prefabs
(`scripts/extract_dsp_slot_poses.py` -> `dsp/data/slot_poses.json`), and both
strategies now choose a sorter's machine-side anchor from those tables via
`slots.attachment`. **Every placement either serves a machine where the game
has a pose, or does not serve it: zero `game.*` findings on everything that
lays out.**

The cost is coverage, not density. Paired and interleaved over the cells both
arms lay out, constraining the anchor moved total area by **-0.28%** (6494 vs
6512); the 3x3-machine cells are identical to the tile, because for a 3x3 the
table says exactly what the old edge-row assumption said.

WHAT STILL CANNOT BE LAID OUT, AND WHY

`attachable_columns` for a lane one row clear of the machine, both sides:

| building | footprint | from above | from below |
| --- | --- | --- | --- |
| Assembling Machine, Smelter, Depot | 3x3 | 0,1,2 | 0,1,2 |
| Matrix Lab | 5x5 | 1,2,3 | 1,2,3 |
| Chemical Plant, Quantum Chemical Plant | 9x5 | 3,4,5,6 | 3,4,5,6 |
| Miniature Particle Collider | 9x5 | 1,2,3 | 1,2,3 |
| **Oil Refinery** | 3x7 | **none** | 0,1,2 |
| Ray Receiver, Energy Exchanger, Spray Coater | -- | **none** | **none** |

Three structural consequences, each a packer problem rather than a validator
one:

1. **An Oil Refinery cannot be served from the north.** Its nine poses are
   0-2 east, 3-5 west, 6-8 on the south face; there is no pose on the north
   face to be near. A layout that runs its lanes east-west can only feed a
   Refinery from below. The fix is either to rotate it a quarter turn -- at
   yaw 90 its east and west faces become north and south, and its 3x7 becomes
   a 7x3 that suits a row band better -- or to route both of its connections
   from the same side. Neither strategy can rotate a machine today.
2. **A wide machine offers fewer columns than its width**, so fewer parallel
   sorters fit. `_pick_sorter` is now sized against the attachable count rather
   than the footprint width, which buys back capacity by raising the tier, but
   a Chemical Plant still tops out at four sorters per lane.
3. **A Chemical Plant's southern anchor is a row INSIDE its footprint**, so the
   sorter is two tiles long before anything else -- and a lane three tiles clear
   of it is already past `SORTER_MAX_REACH`. Wide machines must be packed
   CLOSER to their lanes than 3x3s, not further.

**51 tests in `test_spine.py` and `test_freeform.py` fail**, all of the form
"this spec lays out and validates clean" for a spec containing an Oil Refinery,
a Chemical Plant or a Spray Coater. They are the diagnosis, not the disease; the
failure mode is `machine.inputs_supplied` / `machine.output_removed` /
`flow.sorter_capacity`, never an invalid blueprint. The audit holds **INVALID 0
and crashed 0** across three runs (tier `small`, budget 4s: 8/30 clean, 22
refused, identical all three times).

### Spray Coaters are belt-fed, and the belt goes one level UP

Both strategies used to run a sorter into a coater. That connection does not
exist: a coater ships zero insert poses, `BuildTool_Inserter` refuses to target
a building with none, and all eight coaters in the corpus carry no connection at
all -- `input_obj` and `output_obj` unset, `(15, 14)` in their four slot fields.
The game attaches an addon's belts positionally, from
`PrefabDesc.addonAreaPoses`, and for a coater area 1 -- the proliferator supply
-- is at `(0, -1.25, 1)`: a tile and a quarter behind it and **exactly one
altitude level up**. The corpus confirms it: every coater there has a belt one
level above and one tile to the side.

So proliferation needs an ELEVATED proliferator lane whose tiles land in each
coater's addon area. Neither strategy can route one, so `game.addon_supply`
reports the coater unsupplied and every proliferated candidate refuses. That is
a real capability loss and it is the right one: the sorter it replaces looked
like a feed and was not one, and nothing could see that because a coater has no
`slotPoses` for `CheckInserterDataLegal` to check.

## RESOLVED -- the game's own rules are scattered across three forms

`src/flab2bp/dsp/rules.py` now owns what the game PERMITS, and its docstring is
the index of every game rule in the project. Nothing changed value; ruff, mypy
and the full suite are green on an isolated checkout carrying only the move.

**The map, before the move.** Four forms, not three:

* **Ported predicates** in `layout/validate.py` -- `game.inserter_data`
  (`CheckInserterDataLegal`), `game.inserter_paste` (the `ErrorInserterData`
  ladder), `game.inserter_skew` (`TooSkew`), `game.addon_supply`
  (`PlanetFactory`'s addon pass), `geom.altitude_step` (`TooSteep`),
  `geom.collide`.
* **A ported predicate with its own geometry engine** -- `dsp/colliders.py` is
  the whole of `EBuildCondition.Collide`: the physics query, the exemptions,
  the spherical-to-flat argument, and `GRID_ARC` = 1.2566. It is a module and
  not a constant because the rule is an algorithm.
* **Extracted data** -- `dsp/data/slot_poses.json`, `colliders.json`,
  `buildings.json`, produced by the three `scripts/extract_dsp_*.py` and served
  by `dsp/catalog.py`.
* **Constants with the decompiled source quoted in comments** -- spread over
  `dsp/catalog.py` (belt slope, `BELT_Z_PER_WORLD_UNIT`, `belt_max_z`, the
  Tesla radii), `layout/slots.py` (`SLOT_REACH`, `SLOT_ALIGN_DEG`, the sorter
  and addon slot indices), `layout/junction.py` (the splitter slot indices,
  `MAX_PORTS`) and eight private constants in `layout/validate.py`.

**Two things were genuinely wrong, and both were name-level, not value-level.**

* `24f` -- the `TooSkew` axis limit -- was written **twice**, as
  `slots.SLOT_ALIGN_DEG` and as `validate._SKEW_AXIS_DEG`, with nothing tying
  the two literals together. One rule, two consumers, two chances to drift.
* `INPUT_TO_SLOT` and `OUTPUT_FROM_SLOT` were the **same two names** in
  `layout/slots.py` (a sorter's own ends: 1 and 0) and in `layout/junction.py`
  (a splitter's fields: 14 and 15). The splitter pair now carries a `SPLITTER_`
  prefix.

**Two unit disagreements, found by putting the rules side by side. Recorded,
not resolved, because resolving either would change behaviour.**

* `game.inserter_paste` compares a WORLD distance against `PASTE_SNAP` /
  `PASTE_RADIAL`, but the quantity the game compares is
  `num40 = zero.magnitude / num38` with `num38` one tile -- a distance in
  TILES. Read literally the port's threshold is 0.8 world units where the
  game's is 0.8 tiles = 1.005 world units -- **the game's bound is a factor of
  `GRID_ARC` = 1.2566 larger than the one we apply, so our check is tighter**.
  Tighter is the safe direction (we refuse pastes the game
  would take, never the reverse) and nothing we emit lands in the band, but it
  is not faithful. The other half of the same ladder, `num41`, is NOT divided by
  `num38` and so genuinely is in world units -- which is why one ladder can
  hold both frames. `SLOT_REACH` is unambiguous by contrast:
  `CheckInserterDataLegal` compares a bare `Vector3.magnitude` and the port
  compares world to world.
* `game.inserter_skew` compares a TILE distance against `SORTER_LENGTH` while
  the game's `magnitude` there is a world `Vector3` magnitude. Whether
  `num131`/`num132` are pre-scaled by the grid size was never recorded and the
  decompiled source is not in this repository, so it cannot be settled from
  here. It decides nothing we emit either way: our sorters span 1 to
  `SORTER_MAX_REACH` = 3 tiles, which is 1.0..3.0 read as tiles and
  1.257..3.770 read as world units, and every one of those is inside every band
  in the table.

**What did NOT move, and why.** `dsp/catalog.py` keeps the quantities that stay
with the building table and the technology set that parameterises them --
`MAX_BELT_SLOPE`, `BELT_Z_PER_WORLD_UNIT`, `belt_max_z`, `BeltAltitudeRules`,
`TESLA_*`, footprint derivation. `dsp/colliders.py` keeps `Collide`.
`dsp/data/*.json` keeps the tables. Moving the catalog constants would have
meant a large mechanical rewrite of `freeform.py` and `spine.py` while another
agent was editing `freeform.py`, and the value of that is a naming question,
not a correctness one. `rules.py`'s docstring names all of them so the index is
complete either way.

**Still open, adjacent to this:** `_ADDON_AREA_RADIUS`'s companion clause,
`Maths.DistancePointLine(...) < 0.3f`, has never been given a constant or a
port -- only the `sqrMagnitude < 1f` radius is checked. Recorded on
`rules.ADDON_AREA_RADIUS`.

## RESOLVED -- layout solver speed

*Kept as a record of what the numbers actually said, because the first diagnosis
below was wrong in an instructive way.*

Freeform went from **15.0s to 1.16s at identical density** (area 1435), and the
default test run from minutes to ~13s. None of it came from tuning budgets or
worker counts. Three real defects:

1. **A cycle in the A\* predecessor graph.** The ramp branch wrote the
   intermediate cell's state gated on a *different* cell's improvement, breaking
   the strictly-decreasing invariant that makes `prev` acyclic. Path
   reconstruction then walked the cycle forever -- 100% CPU *and* an unbounded
   list, which is where the 24-38 GB per worker came from.
2. **An inadmissible heuristic and no expansion cap.** `h` used the goals'
   *centroid*, so it never reached 0 at a goal and misled the search whenever
   goals were spread. A\* degenerated into an unguided Dijkstra over every
   reachable cell x level.
3. **An objective anti-correlated with the metric.** Height is fixed per solve,
   so `w_var` *is* area -- yet it carried weight 5 against 22 HPWL terms each up
   to `width_bound`. Wirelength dominated and the solver traded width away to
   shorten wires, which is why **more solver time produced worse layouts** (1460
   tiles at 0.1s versus 1566 at 4s). Width now outranks HPWL lexicographically.

Two bound cuts came out of it and stayed: `w_var >= ceil(total_area / height)`
(its lower bound was **1**), and `dx + dy >= min(min(w_i,w_j), min(h_i,h_j))`
for each net pair (every HPWL term relaxed to 0, so half the objective was
invisible to the bound). Bound moved 320 -> 470 immediately.

**The lesson worth keeping:** the original diagnosis here was "model
construction is too slow, cache it and warm-start". That was wrong, and profiling
first -- as this file's own step 1 advised -- would have caught it. A 71-variable
model was never the problem.

**Also measured and rejected:** weighting the A\* heuristic to break ties on the
equal-cost Manhattan plateau. Controlled at `workers=1` it cut A\* time ~15% but
produced **12% more belt tiles**, and A\* is only 0.32s of 0.85s, so the net was
~5% speed for materially more buildings to paste. Not worth it.

## RESOLVED -- direct insertion fires; the COUNTER could not see it

The item said both strategies find direct-insertion opportunities and discard
them, on the evidence of `direct_inserts = 0` across the whole bake-off. The
premise was wrong. Freeform emits **17 bridging sorters across the 24 (URL,
candidate) pairs**; `bench/metrics.py::measure` defines a direct insert as a
sorter with a MACHINE AT BOTH ENDS, and freeform's bridge spans the producer's
output-lane belt to the consumer's input-lane belt. The counter reported zero
however many were placed. `bench/runner.py` now reads what the strategy
reported. Counting belt-to-belt sorters instead would swap the error round --
spine's trunk taps are belt-to-belt too, and are not direct inserts.

It is worth what it costs. Measured on/off at `workers=1`, 8s, all 24 pairs
shipping both ways: **5210 belt tiles against 5302, and 10786 area against
10890**. Biggest single win is `processor`/`no-proliferator` at 171 belt tiles
against 275, a 38% cut. By candidate: `no-proliferator` 7 bridges,
`free-proliferation` 10, `max-proliferation` 0 -- correctly zero, since every
edge there is belt-required. One honest regression, `super-magnetic-ring`/
`no-proliferator`, which is larger with it than without.

### Machine-to-machine insertion is geometrically impossible in freeform

Not a bug, and proved rather than assumed: producer machine bottom to consumer
machine top is `out_lanes + MARGIN + in_lanes + 1 >= 4` rows against a
`SORTER_MAX_REACH` of 3. A true machine-pair insert needs the strip planner to
omit both lanes for that edge, which changes every strip height and therefore
the pack. A test pins the arithmetic so it cannot go stale silently.

## RESOLVED -- lanes are trimmed, and most of them should not have existed

The real finding was bigger than trimming. Risers made intermediate lane copies
vestigial and nothing removed them: **321 of 975 spine lanes were joined to
nothing at either end, holding 34,372 of 80,620 lane belt tiles**. A lane is also
a tile of corridor height, so they cost AREA, not just buildings. `_lane_requirements`
now gives a corridor exactly the lanes it is tapped for; extents stop at the
columns sorters actually use. Dangling tails 595 -> 151, dead lanes 321 -> ~0.

Freeform trims input lanes to their last sorter. Output lanes are deliberately
left alone -- filled at every machine column, drained at the east end, so every
tile carries flow. Building counts: processor 327 -> 248, graphene 208 -> 160,
super-magnetic-ring 1309 -> 1147.

## RESOLVED -- `tile_to_local_offset` is correct

No paste into the game was needed. A blueprint the game itself emitted is
necessarily legal, and the fixtures are therefore a real oracle -- one nobody had
pointed at this. On the three fixtures with no latitude compression, the centre
reading gives **0 footprint overlaps, 0 of 2,656 belts inside a machine, and 686
of 686 machine-side sorter endpoints inside the machine they serve**. The two
corner readings score 18 and 38 overlaps, 675 and 669 buried belts, and 248/676
and 174/666 endpoints. Locked by `tests/dsp/test_local_offset.py`.

Two things worth keeping, both of which nearly wasted the exercise:

* **The round-trip check this item originally proposed is nearly vacuous.**
  Every catalog footprint is odd, so `w/2 - 0.5` is always an integer and
  "recovered tile is an integer" reduces to "the building is on-grid" -- it would
  pass under any wrong per-footprint integer offset. Only checks that compare
  DIFFERENT footprint sizes against each other discriminate.
* **Alignment is not enough to call a fixture geometry-safe.**
  `temple-of-effectiveness` is 796/796 integer-aligned and still stacks 83
  buildings onto occupied cells, because polar longitude collapse keeps whole
  numbers while merging distinct tiles. `GEOMETRY_SAFE_FIXTURES` is wrong in
  both directions as a result: it lists `factory-quick-start-step-3-red-cube`
  (21 of 232 off-grid, 9 collapsed) and omits `12-s-purple-science`, which is
  3,008 clean buildings across a real mix of footprint sizes.

The even-footprint half-tile branch is **unreachable rather than verified** --
no catalog footprint is even, so it never fires. `test_no_catalog_footprint_is_even`
fails if that stops being true.

## RESOLVED -- `TESLA_LINK_DISTANCE` is 22.5, from the game's own code

`PowerSystem.OnNodeAdded` links two nodes when
`dx*dx + dy*dy + dz*dz <= max(a.connDistance2, b.connDistance2)`, where
`connDistance2` is `PowerDesc.connectDistance` squared, carried through
`PrefabDesc.powerConnectDistance` and `NewNodeComponent` with no scaling. It is a
centre-to-centre distance; 11.25-as-diameter is refuted, and `PowerDesc` has no
diameter field at all. Read out of `Assembly-CSharp.dll` with `ikdasm`.

Two consequences the constant's users need:

* The rule takes the **larger** of the two nodes' reaches. A Wireless Power Tower
  (`connectDistance` 45.5) links to a Tesla Tower at up to 45.5, so a solver
  treating 22.5 as a universal link budget under-reaches whenever a long-range
  node is present.
* Node positions are projected onto a sphere of radius `realRadius + 0.2` before
  the comparison, so the constant is only valid for flat, non-polar layouts.

## RESOLVED -- neither strategy could serve two destinations from one belt

Both strategies hit the same missing primitive from opposite directions, and
both used to hide it by emitting something. Closed by `layout/junction.py`,
whose convention is read off the 25 splitters in the fixture corpus and
verified through both our codec and the TypeScript viewer.

* **Freeform** now taps a different TILE of a lane for each consumer and puts a
  splitter there. Fixing it uncovered three silent failures worth remembering:
  port reservations still held at commit time (every path through its own start
  cell was dropped), A\*'s ramp reconstruction splicing a cell twice into one
  path (3 of 19 routed paths), and a strip's inner lanes being WALLED IN so that
  only the head is reachable -- which was all 40 A\* failures on magnetic-ring,
  every one at zero expansions with two thirds of the routing budget unspent.
* **Spine** joins an item's corridor copies with trunk risers in a margin east
  of the block, y-spans coloured as an interval graph, cross-column stubs
  bridged at z=1. `flow.lane_sourced` on magnetic-ring: 11 -> 0.

## MEASURED AND REJECTED -- a routing-capacity constraint in freeform's packer

This was the top item and it was the wrong diagnosis. Recorded because the
reasoning was plausible enough that somebody will propose it again.

The theory: `_pack` minimises width then wirelength and discovers only
afterwards, in `_build`, whether the result can be WIRED -- so give it a
horizontal cut, `crossings(row) <= free width on that row`. That is a genuine
necessary condition, and it is the shape spine uses for tap capacity, having
learned the same lesson: "rejecting after the fact cannot work here; routability
is a property of the packing, so the packer has to know."

It does not pay. Over the whole trivial+small+mid corpus, every candidate, three
repeats: **one** more valid pair out of 24 and one more valid sample out of 72 --
inside the noise -- for 0.5% more area and a test suite going 39s to 67s. A
single 6s sample had shown it winning decisively (0 unrouted nets against 2,
1240 tiles against 1504); that did not reproduce at any other budget.

**The packer was never the binding constraint.** Classifying every routing
failure showed empty A\* frontiers outnumbering genuine search exhaustion about
ten to one. The failures are GEOMETRY -- a lane port with no free neighbour --
not congestion. A strip's inner lanes are walled in (lane above, machines below,
lane either side), so only the head of an in-lane and the end of an out-lane are
reachable at all, and three of the five walled-in ports on the free-proliferation
chain turned out to be taps that an earlier fix had itself moved mid-lane.

If freeform's remaining refusals are to be fixed, they will be fixed by making
ports reachable, not by making packs roomier.

## RESOLVED -- riser bridges spend the ramp tiles honestly

Bridges now spend `RAMP_TILES_PER_LEVEL` per level change, which needs a free
ramp column beside each trunk, so the margin doubles. Isolated on the final
tree: **+6.1% area overall, +9.1% on the median run, 6 of 66 runs pay nothing**.
Worst case is magnetic-coil at +40%, a nine-machine spec whose block is narrower
than its margin. Against a -21.5% total, fidelity won.

## RESOLVED -- risers split into parallel lanes, and it was NOT latent

This file claimed `flow.belt_capacity` passed on every corpus spec, so the
single-belt trunk was only a future risk. Wrong: `quantum-chip` moves 48
crude-oil/s and 48 refined-oil/s against a 30/s Mk.III belt -- **8
`flow.belt_capacity` errors across the corpus**. `_lane_copies` sizes parallel
lanes from the rate, machines deal round-robin across them, and each copy gets
its own trunk. Isolated: **+2.3% area, 8 errors to 0**. Where splitting makes a
corridor unwireable it is abandoned rather than the layout -- coverage outranks
throughput.

## RESOLVED -- lane direction is derived from the taps

Also measured against this file's guess, which was that it was pervasive: it is
**3 of 656 lanes**, on magnetic-coil, plastic and processor. Real every time -- a
machine that pastes and never runs -- and invisible to the validator.
`_lane_direction` derives direction from the taps where physics leaves it free
and forces it where it does not. 3 starved drains to 0 corpus-wide.
`stats["starved_taps"]` counts the residue, because drains on BOTH sides of the
fills cannot be served by any single direction and has no cheap fix.

## RESOLVED -- `flow.conservation` reads the placement, as a reachability cut

The previous note said the junction-aware version could not be seeded soundly,
citing junction 1639 showing downstream demand 12 against upstream supply 4. That
reading was wrong on the facts: `magnetic-coil` is not an external input, so no
seeding was involved -- the fixture genuinely runs 4 magnetic-coil machines at
1/s against 12/s of demand, and the existing spec-arithmetic clause was already
reporting it. The seeding problem was solvable too; `_entry_items` divides
`external_inputs` across entry lanes in proportion to demand.

The per-junction form was then built, measured, and **rejected**: 15 lanes
reported short across `processor` and `super-magnetic-ring`, every one a false
positive. Three things in this model divide a rate evenly where DSP does not -- a
splitter feeds whichever output has room, a machine with two output sorters fills
whichever lane is not backed up, and a lane fed by two producers draws from
whichever is not empty. All three self-balance under backpressure.

What shipped instead is a **cut argument**, which backpressure cannot rescue:
union-find everything an item can physically reach (lanes, junctions, transfer
sorters, machines), and within each island production plus external supply must
cover consumption. 10 findings over 512 belt runs of the corpus, every one on a
build already refused by `machine.inputs_supplied`, none on a build that
otherwise validates clean.

### Known weakness: islands are undirected

A producer joined DOWNSTREAM of its consumer's tap reads as connected. This is
conservative on purpose -- it can hide a shortfall, never invent one -- but it is
the direction to tighten if the check ever needs to be stronger.

## RESOLVED -- `belt.termination` now measures overshoot, not tapping

The rule was wrong rather than merely noisy. It asked whether the TAIL TILE was
tapped, and both strategies end a lane a couple of tiles past its last consumer,
so correct lanes failed while wasting 2 tiles in 50. It now measures the size of
the overshoot against `SORTER_MAX_REACH`, and always reports a lane no sorter
touches anywhere.

Controlled on identical placements, old rule against new: hand-built fixtures 32
of 123 runs to 3; corpus 127 of 535 to 74. The survivors carry their own
justification -- median 8 dead tiles, tail of 44 -- and every finding names the
tile count to cut.

## RESOLVED -- transfer sorters were invisible to the flow graph

Found while doing the above, and the same theme as every other hole in this file:
a check that counted buildings instead of following connections.

A sorter with a BELT ON BOTH ENDS -- how both strategies tap a trunk onto a
branch without spending a splitter -- appeared in neither the successor/
predecessor graph nor the sorter-flow table, because `_sorter_demand` returns
`None` when neither end is a machine. So a trunk drained by a transfer sorter was
charged **zero**, and `flow.belt_capacity` could not see load leaving a lane that
way at all: a Mk.II belt carrying 20/s reported clean. Transfer sorters are now
graph edges and the rate is derived rather than guessed.

## RESOLVED -- the hand-built fixtures balance

`magnetic_ring_spec` is now the exact stoichiometric solution at 2 rings/s: 9
groups, 54 machines, supply equals demand for every item, Mk.III belt because
iron-ore at 22/s does not fit on Mk.II. Both strategies use the same numbers, so
they are compared on one spec rather than two. `two_stage_spec` was unbalanced
as well. `balanced_pair_spec` is deleted -- balancing it made it identical to
`two_stage_spec`, and dodging the imbalance was its only reason to exist.
Arithmetic tests pin both so they cannot rot back.

## RESOLVED -- freeform supplies its coaters; the numbers below are historical

**Re-measured 2026-08-23 and this no longer reproduces.** On trivial+small+mid
freeform is **48/48 clean** -- 0 refused, 0 invalid, 6s wall -- against the
14-of-24 recorded below. Across the full stress corpus it is 62-66/72 over nine
runs with **zero** `prolif.*` findings in any of them; every remaining miss is
`<refused>`, and those are concentrated in `universe-matrix` (6) and
`quantum-chip/max-proliferation` (2), neither of which is a proliferator-entry
failure.

No single commit closed this. It went out under the accumulated 2026-08-23
freeform work -- most likely `e1174f0` (stacked output lanes were walling in
their own east access cells, which is the same shape of defect as the entry lane
being walled in) and `a834293` (a ground-level toll that sends through-traffic
upstairs, so runs stop cutting the plane the entry sits on).

The diagnosis below is kept because it is a good description of a real hazard
that could recur: **the block's boundary MOVES during emission while several
passes each assume it is fixed.** If an entry lane is ever unreachable again,
start there. What is stale is only the measurement.

### The original entry, as written

The largest open defect. On the trivial+small+mid corpus freeform ships **14 of
24 (URL, candidate) pairs**, and **15 of the 22 remaining errors are
`proliferator-3` entry lanes that no belt can reach**.

The proliferator entry is a single tile placed one column west of everything --
the boundary at the moment it is placed. Then the external-input runs extend the
block west past it and it is interior, walled in on four sides. Two fixes were
tried and measured:

* Routing it to the edge in the same pass as the other external inputs made it
  **worse** (11 unreachable to 17): every run targets a boundary computed before
  any of them move it, so adding a run just moves the edge again.
* Placing it after the external runs have settled the edge helps (11 to 14 pairs
  shipping, 26 errors to 22) but introduces a refusal on `graphene`/
  `max-proliferation`, because the proliferator nets now do not exist when port
  access is first staked.

That second version is what is committed, on the measurement. The underlying
problem is that the block's boundary MOVES during emission while several passes
each assume it is fixed. The fix is probably to decide the final extent up front
-- reserve the entry ring before anything routes -- rather than to re-order the
passes again.

*The consolidation item below is the same concern seen from the other side: the
rules above now live in a data file, a catalog dataclass, four validator checks
and a layout primitive, and the argument for one module is stronger for it.*

The first in-game paste (2026-08-24) turned a pile of inferred rules into
extracted ones: the game is installed at `/home/dannyb/Dyson Sphere Program/`,
`Assembly-CSharp.dll` decompiles with `ilspycmd`, and `Locale/1033/base.txt`
(UTF-16LE, tab-separated) maps each Chinese condition key to the English text the
build cursor shows. That ended a long run of guessing -- but the rules landed
wherever each fix happened to need them, in three different FORMS:

* **Extracted data** -- `dsp/data/slot_poses.json`, 35 buildings of real
  `PrefabDesc.slotPoses`, produced by `scripts/extract_dsp_slot_poses.py`.
* **Derived constants** -- in `dsp/catalog.py`: the 3/4 world-to-blueprint z
  conversion, `BELT_CLIMB_PER_TILE`, `buildMaxHeight = labLevel*4 - 0.6`, the
  technology ids behind `beltVerticalConstruction`.
* **Ported predicates** -- in `layout/validate.py`: `CheckInserterDataLegal`
  (the 0.8 slot-pose radius and the slot-forward dot product) and the
  `TooSteep` slope rule.

Nothing is wrong with any of them individually. The problem is that a reader
asking "what does the game actually require?" has to know to look in three
places, and the C# provenance lives in whichever docstring the author was
writing at the time. That is exactly the condition under which somebody
re-derives a rule from the corpus and gets it wrong -- which is how we arrived
at a belt-height ceiling of 1.0 when the real answer, from the game, is
`3*labLevel - 0.45` and reaches 38.55 on a developed save.

The fix is a single module -- `flab2bp/dsp/gamerules.py` or similar -- holding
each rule next to the C# it came from: the function name, the condition in
`EBuildCondition`, and the decompiled snippet. Data files stay data files, but
the module should own the loading and be the one import a caller needs.
`catalog.py` keeps physical facts about buildings; `gamerules.py` owns what the
game will REFUSE.

Worth doing when the `game-rules` and `altitude-study` branches land, since both
touch `catalog.py` and `validate.py` and will conflict anyway -- the
consolidation is nearly free at merge time and expensive later.

**Rules still unextracted**, and each is a place the guessing could resume:
the LATERAL half of the belt collision rule -- what excuses a belt standing
beside, or level with, a building it overlaps. The vertical half (crossing) is
extracted and shipped as `game.belt_crossing`; the lateral half is not, because
a faithful port of it convicts blueprints the game wrote (see the belt item
under "our footprints are a tile grid" below).

Two that were on this list are now answered, and both are recorded in
`layout/validate.py`'s comments rather than as checks, because neither can be
one:

* **`NeedGround`** ("Foundation required") is not a property of a blueprint at
  all. In `BuildTool_BlueprintPaste` it is a terrain raycast per `landPoint`:
  18 m down, refused when the hit is below `-0.3 - landOffset` of the planet
  radius, or when the ground and water layers differ by more than
  `0.27 + landOffset`, or when nothing is hit. The same blueprint pastes one
  tile away. It does not offer to auto-foundation because reform is a separate
  opt-in pass (`ComputeReform`). No offline check can predict it; levelling the
  ground answers it.
* **`TooSkew`** ("Deflection too much", `偏角太大`, condition 15 -- NOT
  `TooBend`/`弯曲过度`) is ported as `game.inserter_skew`. It reads the
  blueprint's own anchors and yaws, not the snapped ones: 30 degrees between the
  two end rotations, 24 degrees between each end's forward and the line the
  sorter runs along, plus a length window that varies with how many ends are on
  a belt. On an integer grid the window cannot bind -- its loosest floor is 0.9
  and the shortest sorter is 1.0.

A third is worth recording because it was got WRONG first and the corpus caught
it: the skew ladder does **not** run on the snapped positions. Reading it that
way rejects 11 Oil Refinery sorters in `factory-quick-start-step-3-red-cube`, a
blueprint the game ships. It also means a backwards sorter yaw is not rejected
by anything ported here -- the yaw is derived from the geometry because 1250 of
1250 real sorters agree on it, not because a predicate refuses the alternative.

**And when it lands, `gamerules.py` must carry each rule's GUARD, not just its
threshold.** The belt slope rule is not `slope <= 0.8`; it is

    if (!history.beltVerticalConstruction && num25 > 0.8f)

and the guard is the whole point. `altitude-study` extracted the threshold
correctly, then applied it unconditionally, and paid 19 of 72 audit cells
against master's 2 -- every net spending two tiles per level change under a
constraint that most saves, including the user's, do not carry. Gating it on
the technology returned the audit to master's 2/0/1 exactly.

The same shape is waiting in the others: `TooSteep` has a second, tighter form
guarded by the same flag, `inserterBidirectional` and `inserterStackInput` gate
sorter behaviour, and `labLevel` gates the height ceiling. A rule recorded
without its guard reads as universal, and the cost of that mistake is not a
wrong blueprint -- it is a quietly worse one, everywhere, which is much harder
to notice.


## OPEN -- our footprints are a tile grid; the game's collision is not

The fourth and last unexplained error from the first in-game paste,
"Collide with other object" (`EBuildCondition.Collide = 34`), is ours colliding
with ourselves. It is now extracted, modelled and measured; what is NOT done is
the layout fix, which is why this entry is OPEN.

**The rule.** `BuildTool_BlueprintPaste.CheckBuildConditions` (decompiled
145712-145760) puts every preview's `PrefabDesc.buildColliders` into the live
physics world -- `ActiveColliders` -> `BuildPreviewModel.SetCollider` -- and
runs `Physics.OverlapBoxNonAlloc(collider.pos, collider.ext, ..., mask 395264)`
per preview. Mask 395264 is layers 11, 17 and **18**, and layer 18 is
"Build Preview" (confirmed from the TagManager), so previews test against each
other. An un-excused hit is `condition = EBuildCondition.Collide` at 146071.
Its guards, which narrow it a long way: a sorter is excused against anything
that is not a sorter and vice versa; a machine is excused against a belt but
**not** the reverse, because the clause tests `!A.isBelt`; belt-vs-belt is
excused only when `dotsCursor > 1`, which a single paste is not.

**Why our tile model cannot see it.** A tile is not one world unit. Rows are
`GetLatitudeRadPerGrid = 2*pi/(segment*5)` apart, and `segment` tracks the
planet radius, so the arc is `2*pi/5 = 1.2566` units on every planet. An
Assembling Machine's build collider is 3.82 units across. Three tiles is 3.770.
`catalog.derive_footprint` returned `2*ceil(box/2) - 1 = 3` for it, both
strategies duly placed assemblers three tiles apart, and the game refused every
one of those pastes. (Spacing is `catalog.clearance`'s job and has been since
`geom.collide` landed; the footprint rule itself was carrying the same unit
error, which item 1 below now records as fixed.) The corpus agrees and always
did: across every fixture, assemblers appear at a pitch of 4 or more and NEVER at 3, Matrix Labs at 5 or
more and never 4, Arc Smelters at 3. The extracted model reproduces each of
those minimum pitches exactly.

**Measured**, three runs, both strategies, every tier: 13 of 24 cells collide in
every run. 443 of ~530 pairs are assembler-on-assembler; the rest are a Tesla
Tower one tile from a Splitter.

**What landed:** `dsp/data/colliders.json` (252 models of real
`buildColliders`, from `scripts/extract_dsp_colliders.py`), `dsp/colliders.py`
holding the predicate next to the C# it came from, and `geom.collide` in
`layout/validate.py` -- an ERROR check. It was parked in `validate.OPT_IN` while
the footprints were wrong; `OPT_IN` is empty now and `geom.collide` is a normal
check that both strategies pass on the whole corpus.

**What is left, in order:**

1. ~~**Fix the footprints.**~~ **DONE, and the diagnosis in this item was
   half wrong.** The right question for *spacing* is indeed "how far apart must
   two of these be" -- and that question already had an answer,
   `catalog.clearance`, which both packers use. It is NOT the footprint's
   question. The footprint's question is occupancy, and the actual defect was a
   **unit error**: `derive_footprint` compared a world-unit half-extent against
   tile centres **one unit** apart when they are `GRID_ARC` = 1.2566 apart.

   Corrected, it is `2 * ceil(e / GRID_ARC) - 1`, which is **still always odd**.
   So `tile_to_local_offset`'s half-tile branch was NOT reached, and it must not
   be: an even footprint puts an Assembling Machine's centre on a half-tile, and
   across the geometry corpus 3,038 of 3,038 buildings are integer-centred. The
   game does not write that geometry. The branch staying unreachable is the
   result, not an omission.

2. ~~**`blueprintBoxSize` is the wrong field for this.**~~ **DONE and
   CONFIRMED**, and this half of the item was exactly right. Both errors were
   live at once and they point opposite ways, which is why the old rule scored a
   clean sheet against every footprint the corpus pins -- assembler 3, Matrix
   Lab 5, Arc Smelter 3, Oil Refinery 3x7, Depot 3, Tesla Tower 1, Wind Turbine
   3, Solar Panel 3. Fixing one without the other is worse than fixing neither:
   `blueprintBoxSize / GRID_ARC` makes an Oil Refinery 3x5, and all eighteen
   machine-side sorter endpoints in `factory-quick-start-step-3-red-cube` sit
   three tiles from a refinery centre.

   The measured effect, paired and interleaved against master, three rounds
   each, INVALID 0 in every round of both arms:

   * **freeform, full 72-cell corpus: area -9.8%, -10.3%, -9.8%** on the cells
     clean in both arms (63, 64, 63 of them). Clean counts A 63/66/64 against
     B 64/64/64 -- indistinguishable. The wins are concentrated where the
     Chemical Plant is: `graphene` -28%, `information-matrix` -21% to -42%,
     `plastic` -19%, `quantum-chip` -28%.
   * **spine, 48-cell mid tier: area -1.80%**, identical in all three rounds,
     32 cells clean in both arms and 5 of them moved -- `plastic` -21%,
     `graphene` -18%, -17%, -9%, -8%. Spine's coater-supply limitation (16
     refusals, the "ten-coater case" entry above) is unchanged and unrelated.

     That spine number was **-0.54% on a first run and the first run was
     wrong**, which is the reason it is stated with its denominator. The wrong
     figure came from the arm that carried the coater bug below: it refused ten
     cells, so only 22 cells were clean in both arms and the comparison was
     silently made on a different, smaller and easier population.

   **One real bug fell out of the growth half**, and it is worth not
   re-discovering. The Spray Coater's collider is 3.8 units long about its own
   centre, so its footprint went 1x1 -> 1x3 -- correct about the collider, and
   spine was feeding that figure straight into `PlacedBuilding.width`. A belt
   addon is anchored on the belt tile it rides (`addonAreaPoses` area 0 is "the
   cargo belt it rides"), and `tile_to_local_offset` reads the centre off the
   width, so at yaw 90 a 1x3 became 3x1 and moved the coater's emitted centre a
   tile off its belt -- into an Oil Refinery, as `geom.collide`. It cost spine
   **ten of 48 cells** before it was found, all as REFUSED rather than INVALID.
   Spine now places a coater 1x1, as freeform and `junction.make_splitter`
   already did, and `test_a_placed_coater_is_anchored_on_its_belt_tile_not_on
   _its_collider` pins it.

   Residual worth knowing for item 3: the corrected footprint is by definition
   the last tile centre the collider covers, so the **first free tile beyond it
   can be very close to the collider surface**. Across every building the
   margin is: Vertical Launching Silo 0.04, Water Pump 0.057, Splitter 0.067,
   Mining Machine 0.113 -- all under the 0.23 belt probe radius. That is not
   new and not caused by this change (the Splitter's 0.067 is exactly the
   "grazes its 1.19-unit arm by 0.16 of the 0.23 probe" already recorded in
   item 3), and no production machine is in it: the Chemical Plant's margin is
   0.73 and the tightest of the Fractionator and Storage Tank is 0.263.

3. **Belts are HALF modelled now.** They are tested as a 0.23 sphere at
   `lpos + lpos.normalized * 0.2`, and a belt hitting a machine is not excused.
   That much is shipped, as `game.belt_crossing` -- but only for a belt standing
   directly OVER a building and higher than it, which is the crossing question
   and passes the corpus.

   The LATERAL half is still not modelled, and the reason is now measured rather
   than suspected. Applied without the height restriction the same sphere flags
   **1189 belts across the fixture corpus**, in blueprints the game itself
   wrote: 675 against a building in `catalog.LOW_CONFIDENCE_FOOTPRINTS` (whose
   colliders are already recorded as untrustworthy), 382 against a building
   separated in longitude, where the flat grid is not the real spacing -- and
   the rest against Splitters and a Storage Tank at exact, uncontaminated
   spacing. A belt one tile from a Splitter grazes its 1.19-unit arm by 0.16 of
   the 0.23 probe, and *every* blueprint containing a splitter does that, so
   something excuses it. `BuildTool_Path` line 157683 excuses the first and last
   two nodes of a drag against the object they connect to, and three for a
   station -- but the paste path has no such clause and its previews carry no
   drag index. **Finding that excusal is what is left**, and until it is found
   both `geom.collide` and `game.belt_crossing` are LOWER bounds on what the
   game rejects.
4. **Sorters likewise**, and for a known reason: a sorter's box is rebuilt from
   the poses of the buildings it connects, which needs the `slotPoses` data this
   repository had wrong.

**Not a defect, and worth not re-discovering:** columns compress by `cos(lat)`
away from the paste anchor, because the longitude step is fixed at the anchor's
latitude (`RefreshBuildPreview` 179977). Two Matrix Labs five tiles apart are
clear at the equator and collide 81 rows north of it. That is why a blueprint
can paste in one place and not another, and it is a property of WHERE it lands,
not of the blueprint -- so `geom.collide` evaluates on a flat grid at
`GRID_ARC`, the loosest spacing any equatorial paste can give, and reports only
what no paste can avoid. Asking the other question is `collisions(anchor_lat=)`.
On one `information-matrix` layout the two differ by 5 pairs against 15.
