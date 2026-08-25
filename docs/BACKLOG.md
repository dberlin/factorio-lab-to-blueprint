# Backlog

## OPEN -- freeform's proliferator chain crosses a Spray Coater it cannot get around

CONFIRMED IN GAME, by paste.  The failing blueprint was cut down to one coater,
its tower and every belt within six tiles -- no machines, no sorters -- and the
game flagged the BELT directly over the coater.
`colliders.belt_crossing_height` for the coater's model is **1.8975**; our chain
crosses at **z = 1**, so it owes z = 2.

**Nothing caught it because two checks each assumed the other did.**
`geom.collide` skips belts and defers them to the belt probe;
`colliders.belt_collisions` excuses belt addons outright, on the `AddonPass`
reading; and `validate._stacks` takes a coater out of the crossing question
because `PrefabDesc.multiLevel` is set for it, which is right for a Splitter --
a belt one level up is on its raised port -- and wrong for a coater, whose
raised port is at `(0, -1.25, 1)`, a tile and a quarter BEHIND it.  Directly
over a coater there is no port, only 1.8975 of collider.
`validate._addon_crossings` now asks the question, with the two real excusals
kept: a belt at or below the addon's own level, and a belt on one of its area
cells **at that area's own altitude** -- the 3-D form matters, because area 0 is
the coater's own tile and a 2-D exemption excuses exactly the belt the game
flagged.

**SPINE IS FIXED.**  `_belt_floor_over` no longer excuses a belt addon, and
`_SpurField` prices the addon's whole oriented footprint while exempting only
its RAISED areas.  Spine's mid-tier corpus stays **48/48 CLEAN** and its
coater crossings go from 8 to 0.

**FREEFORM IS PART WAY.**  With the check on, freeform's tier-large corpus is
**39-42 of 60 CLEAN** (two runs of the same code gave 39 and 42, so the spread
is the solver's, not the change's), against 60/60 before -- and every one of
those 60 carried the defect.  Each refusal is a proliferated candidate whose
chain cannot be routed.

`_Canvas.belt_ban` holds the band above a coater and under its clearance.  Two
things about it were learned the expensive way and are worth keeping:

* **A band, not a floor.**  A belt at the coater's own level is BESIDE it, not
  over it, and the game's own blueprints carry sixteen such belts across eight
  coaters.  A floor walled those off and cost cells for nothing.
* **From the collider, not the footprint.**  The oriented footprint is three
  tiles and the two boxes do not fill it -- box A stops at +1.51 tiles along the
  coater's axis and box B at +0.32 -- so a footprint-wide ban closed the MARGIN
  tile the chain enters through.  Each candidate cell is asked of the real
  boxes now, which is the same question the check asks of the result.
* **Every drop cell is exempt from EVERY ban.**  Coaters two tiles apart on one
  row overlap footprints, so coater A's band covered coater B's drop -- the belt
  was already standing there and the router could no longer reach it.

The geometry is the problem, not the ban.  `_place_coaters` seats the coater at
the EAST end of an input lane and derives the drop from area 1, which at
`Facing.EAST` lands one tile WEST of it.  The chain enters from the east margin,
so every approach to that drop crosses the coater's own collider, and the drop
must be at exactly one level up -- `game.addon_supply`'s
`ADDON_AREA_RADIUS` is 1.0 world units and a level is 1.333, so z = 2 is out of
reach of the area.

**Two ways out, and each needs measuring rather than picking.**

1. **Let the chain climb.**  Level 2 over the coater and back down.  The margin
   is one tile wide and a ramp needs run, so this needs somewhere to spend
   `BELT_CLIMB_PER_TILE` that the margin does not obviously have.
2. **Seat the coater so its raised area faces the margin.**  A coater at
   `Facing.WEST` puts its drop one tile EAST, in the margin, and the banned
   tiles fall inside the lane where the chain never goes.  It is legal --
   `AddonPass` takes `Mathf.Abs`, so a reversal passes, and `game.addon_facing`
   allows it -- but the game's own eight coaters carry the flow yaw EXACTLY,
   never reversed, and **whether a reversed coater sprays is untested**.  See
   the yaw entry below.  Do not take this option to buy corpus cells until that
   is known.

## OPEN -- our belts carry two yaws out of four, and nobody has watched one run

Measured on the reported blueprint: our belts carry **yaw 0 (439) and yaw 90
(153) and nothing else**.  We cannot emit a belt flowing `-x` or `-y` at all --
the value is a hardcoded `Facing` constant rather than anything derived from the
link direction.  Checked against flow on the compass the game's own data implies
(0 = +y, 90 = +x): **194 of our belts agree with their links and 375 disagree**.
The game's own blueprints are 259/10 and 249/26, and those disagreements are
curve angles and long-range links, not a systematic inversion.

**What is known and what is not, stated at exactly this strength.**  Flipping a
coater-tile belt from 270 to 90 in a known-good hand-built blueprint PASTED
FINE, so it is not a build-legality error.  That is all it establishes.  Every
paste this project has done tests PLACEMENT, not operation: we have never had a
fully-green paste, so nobody has ever watched one of our blueprints run.  A belt
whose yaw contradicts its own links could paste cleanly and then move items the
wrong way or not at all, and a Spray Coater is directional, so which way items
pass through it is a runtime question we have not observed.

**Do not read "pasted fine" as "correct".**  The precondition for testing this
is a blueprint that pastes clean, which is what the coater-crossing entry above
is blocking.

## RESOLVED -- a machine slot holds ONE connection, and 90% of the corpus broke it

Reported from an in-game paste: "Connection target cannot be laid" beside
"Collide with other object", many sorters red. The diagnosis was right and the
scale was much larger than the report.

**THE GAME'S RULE.** `PlanetFactory` addresses a connection as
`entityConnPool[objId * 16 + slot]` -- one `int` per `(object, slot)`. Occupancy
is keyed on the slot INDEX and never on the slot's POSE, because the pose never
enters the address. Writing a second connection into an occupied cell does not
fail: `WriteObjectConn` calls `ClearObjectConn(otherObjId, otherSlot)` first and
evicts the sitting tenant. So a blueprint naming one machine slot twice pastes
with one sorter silently unwired -- and, because the paste snaps both ends onto
the same slot pose (`lpos = transformedBy.position`), with the two sorters
standing on each other: `Collide`, then `ConnWithErrorBuilding` on everything
attached. Ported as `validate.game.slot_occupancy`, stated in
`rules.CONN_SLOTS_PER_OBJECT`.

**HOW BIG IT WAS.** Measured on a pristine `ce19f5f` with the predicate applied
standalone, budget 4:

| arm | cells | clean before | cells carrying a shared slot | shared cells in total |
|---|---|---|---|---|
| freeform, tier large | 60 | 60 | **54** | **1412** |
| spine, tier mid | 48 | 43 (5 refused) | **34** | **304** |

Every one of those validated `ok=True`. The negative control is the fixture
corpus: over the 10 real game blueprints, ~10,000 connection records, no
`(object, slot)` is named twice, on either reading of the check's scope.

**THREE CAUSES, and only the first was the one reported.**

1. `freeform._link_lane` indexed columns PER LANE and clamped
   (`usable[min(column, len(usable) - 1)]`). Two stacked lanes each asked for
   column 0 and got the same slot; a lane with more items than the machine has
   columns clamped its surplus onto the last. Fixed by rationing columns across
   every lane on a face (`Strip.column_offset`), trimming each lane to the
   columns it will actually use, and claiming slots per machine in `_link_lane`.
2. `_seat_inputs` counted ROWS and not SLOTS. Mixing two items onto one lane
   saves a row and saves no slot, so the ceiling was counted in a currency the
   machine does not have -- see the OPEN entry below.
3. **Every belt-to-belt link named slot 0 of its successor.** The game never
   writes 0 there: over the corpus, belt-to-belt is slot **1** (7169 records),
   **2** (95) or **3** (38), which are the receiving belt's three INPUT slots.
   Slot 0 is where its own OUTPUT link lives, so our value both collided on
   merges and fought with the successor link. Fixed in
   `slots.assign_belt_slots`, which mirrors the game's own first-free scan and
   raises rather than dropping a fourth feeder.

**COST.** freeform tier large goes from 60/60 clean-but-invalid to **58/60
clean, 0 shared slots**. The two lost cells are `electromagnetic-matrix`
`max-proliferation`; INVALID stays 0.

## OPEN -- freeform cannot wire a six-ingredient recipe, and `universe-matrix` is one

A lane-fed machine gets its sorters from the north and south faces only, and
each face offers a lane three insert poses. Six ingredients plus one output is
seven sorters into six slots. It does not fit, and `_seat_inputs` now says so by
name instead of producing a plan that doubles up.

This is not a new limit, it is a newly VISIBLE one. Before the slot rule was
ported, `plan_strips` accepted twelve ingredients on an Assembling Machine and
the emitted blueprint put three sorters on slot 6 and three on slot 7 of every
machine. The six-ingredient case is the only DSP recipe the true bound binds.

**The way out is the EAST and WEST faces.** An Assembling Machine and a Matrix
Lab each define twelve slots, three per side, and freeform uses six of them. A
vertical lane beside a strip, or a spur off the end of one, would reach the
other six. That is a packer change, not a wiring change, and it is the same
territory as serving a machine from a lane that is not in its own strip.

## OPEN -- half of freeform's Spray Coaters stand ACROSS the belt they ride

Reported in game: every coater red. The yaw of a belt addon is what aims its
`addonAreaPoses`, and `freeform._place_coaters` writes one yaw for every coater
regardless of which way the lane it lands on runs.

**MEASURED**, on the reported blueprint's `max-proliferation` candidate, with
the flow direction taken from the `output_obj` link graph and not from any yaw
field:

| source | coaters | yaw == flow |
|---|---|---|
| the game's own blueprints | 8 | **8** |
| `spine` | 16 | **16** |
| `freeform` | 20 | **10** -- six across the flow, four reversed |

**Why it matters, and why only some of it is checked.** The paste's `AddonPass`
excusal, which is what keeps a belt running under a coater from being called a
collision, ends in `Mathf.Abs(Vector3.Dot(areaLine, beltDirection)) > 0.95f`.
A reversal dots to -1 and passes; a right angle dots to 0 and the belt under
that coater becomes `EBuildCondition.Collide`. `validate.game.addon_facing`
ports exactly that and convicts the six, not the four.

**Why `game.addon_supply` could never have caught it.** That check computes the
addon area's cell FROM the addon's own yaw and then asks whether a belt is
there -- and the placement put the belt at the same computed cell. It validates
our choice against itself.

**The fix is not a one-line yaw.** A freeform coater rides the head tile of an
input lane, and that tile's direction of flow is decided later, by whichever
route the router attaches to it. Turning the coater to match then moves its
proliferator area to a different neighbour, and the drop belt -- already placed,
and the sink of a routed net -- has to move with it. Either the coater must be
seated on a tile whose flow is already settled, or the drop must be chosen after
routing.

## RETRACTED -- the Spray Coater's 1x1 footprint is CORRECT

Recorded because it was believed twice on one day and is easy to believe a
third time. The claim was that both strategies declare a coater `1x1` where the
prefab says `1x3`, that `tile_to_local_offset` therefore emits every coater a
tile off its belt, and that `geom.collide` is blinded by the same wrong size.

Both halves are false. In `factory-heretical-smelter-block` and
`tillable-blackbox-module-...`, blueprints the game wrote, all eight Spray
Coaters sit at their nearest belt's position to within `(0.000, 0.000, 0.001)`.
`tile_to_local_offset` is `x + width / 2 - 0.5`, so a `1x1` declared at the belt
tile emits its centre ON the belt tile -- which is correct, and which our twenty
coaters reproduce exactly. `geom.collide` builds its `Placed` from that same
offset, so it tests the coater's real 3.5-unit collider at the coater's real
pose. Forcing the footprint to the prefab pair is what MOVES the coater, and the
collision that then appears is manufactured by the fix.

`occupies_tiles = False` already says this: the tiles a coater's collider covers
are not tiles it reserves. `validate.geom.footprint` has two branches for that
reason, and collapsing them turns a test red on purpose.

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
  grid. ~~That is the OPEN entry *"our footprints are a tile grid; the game's
  collision is not"* at the bottom of this file, and this work sits behind it.~~

  **RE-AIMED 2026-08-25.** The footprint entry is closed and this was never
  waiting on it. What forbids the overlap is the ROUTER's occupancy policy:
  `freeform._Canvas.add` stakes a machine with `solid=True`, which writes every
  level of every footprint tile into `blocked`, so no belt may enter a machine's
  tiles at any altitude. Relaxing that for port tiles specifically is the work,
  and it needs its own measurement -- the same policy is what keeps belts from
  routing through machines generally, which is right everywhere else.

Until then the refusal stands and is honest. `_machine_config` still owns the
charge/discharge parameter block and is tested directly, so that coverage did not
go with the removed placement.

~~**Freeform is unchanged and needs the same correction.**~~ **MADE
2026-08-25.** Its `_machines_without_poses` owned the case correctly but its
docstring argued from a false premise -- *"a Ray Receiver IS fed in game, so it
either carries its slots in an array the extractor does not read or takes items
by some other mechanism"* -- and its refusal message carried the same reading,
so a reader who hit it was sent to the extractor rather than to belt-to-port
docking. It is fed nothing; it consumes no item at all, and its OUTPUT is what
needs a belt. The docstring now says so, and the message names the port count
the way spine's `_sorterless_groups` does: *"gives it no insert pose on any face
and 4 belt port(s) ... it takes a belt docked into a port, which neither
strategy emits"*. Pinned by
`test_the_refusal_names_the_belt_ports_rather_than_a_missing_array`.

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

## RESOLVED -- the keep-out around a junction is asymmetric in z, and that is the whole fix

`game.belt_collide` is a normal check now. **`validate.OPT_IN` is EMPTY again**,
which is the state this project wants it in, and the full suite is green with the
check default-on.

### The geometry, including the half the old entry did not have

An unlinked belt placed at every offset around a splitter, judged by
`colliders.belt_collisions`, is convicted at the four orthogonal neighbours AND
the tile itself -- at the splitter's own level and at the one ABOVE it, and
nowhere else:

        dz = -1           dz = 0            dz = +1           dz = +2
        .  .  .  .  .     .  .  .  .  .     .  .  .  .  .     .  .  .  .  .
        .  .  .  .  .     .  .  X  .  .     .  .  X  .  .     .  .  .  .  .
        .  .  .  .  .     .  X  X  X  .     .  X  X  X  .     .  .  .  .  .
        .  .  .  .  .     .  .  X  .  .     .  .  X  .  .     .  .  .  .  .
        .  .  .  .  .     .  .  .  .  .     .  .  .  .  .     .  .  .  .  .

The entry this replaces had only the `dz = 0` plate, which is why it read as a
lateral problem. It is not: **most of the convictions were a belt one LEVEL
above the splitter**, over it or beside it. The arms reach 1.19 world units
against a 1.2566-tile pitch, so a diagonal at 1.777 clears and two tiles out
clears; the cross stands 2.30 units against a level's 4/3, so one level up is
still inside it and two are not.

**AND IT IS ASYMMETRIC. THERE IS NOTHING BELOW.** That is spine's whole fix and
nobody had looked for it. `colliders.belt_keepout_offsets` MEASURES the set
rather than asserting it -- it probes the box at every offset in a
seven-by-seven-by-nine box -- and `junction.keepout_cells` turns it into routing
cells. Two tests pin it, one of them checking BOTH directions of the pairing
against `belt_collisions` itself, so an offset that stopped convicting would
show as an over-strict keep-out and one that started would show as an unsound
one.

The excusal is unchanged and untouched: the game lets a belt off when its own
run reaches the splitter within three hops (`colliders.belt_chain_excuses`), so
a keep-out cell is only fatal to a belt on a DIFFERENT run.

### Freeform: the router has the collider now

Freeform's junctions are ALL mid-path taps. Instrumented over
`super-magnetic-ring`, `information-matrix` and `quantum-chip`, 100% of them sit
on a sibling's routed path rather than on a lane port, because `_ends` already
withdraws a lane start that would need a junction it cannot have. Three changes,
and the ORDERING one is why the guard in the old entry failed:

1. **Taps are chosen after every belt is staked.** `_commit_paths` is two loops
   now: stake and self-link every net, then walk them again to attach sources
   and sinks. A site test in the old one-loop order was asked a question whose
   answer had not been decided yet -- that is the whole of why adding the
   linkage test to `junction.site_is_clear` refused 1147 of 1619 sites and the
   convictions survived anyway.
2. **`_merge_frontier` withdraws a merge cell whose tap would stand beside a
   foreign belt.** The site is decided during routing, where refusing costs one
   of several offered cells rather than the whole pack. Withdrawal rate on the
   two hardest URLs: 10-62% of the cells a frontier offers, median about 38%.
   It asks for the free neighbours first and the keep-out only for a cell that
   has some -- this is a routing inner loop and most cells of a settled path are
   walled in by their own.
3. **A junction guards its collider's room afterwards.** It is belt-integrated
   and `_Canvas.add` marks nothing, so external input runs, coater spurs and the
   power lattice all used to route straight through it; `_Canvas.guard` is the
   set they now ask about.

The third named direction -- re-check and refuse the pack -- is what taking the
check out of `OPT_IN` does by itself, since both strategies run
`validate.certify` on every candidate and discard a failing one. It was the
floor, and it stayed the floor.

### Spine: the bridge goes under the trunk, not over it

Spine's junctions are its trunk taps. A trunk is a column in the east margin; a
lane reaches its trunk along its own row, crossing the trunk columns west of it.
Every spine conviction measured was the same shape: a bridge at
`(x, y +/- 1, z = 1)` against a junction at `(x, y, z = 0)` -- a foreign lane's
bridge passing one row from somebody's tap, at exactly the level the cross
reaches.

`_TRUNK_Z` inverts it. **The trunks ride a level up and the bridges stay on the
ground**, with the single ramp tile moved from both ends of a bridge to the
trunk end only. It costs no column, no area and no altitude the old arrangement
did not already spend -- `BELT_CROSSING_CLEARANCE` between bridge and trunk
either way round -- and because the keep-out has nothing below a junction, the
clash cannot happen rather than being searched away.

**A COLUMN-ORDERING PASS WAS BUILT FIRST AND IS DELETED.** A bridge only ever
crosses columns WEST of its own trunk, so ordering the colours to put the
junction-heavy trunks east removes every clash the greedy colouring caused --
measured, eight of the ten URLs spine could build went to zero convictions and
`information-matrix` went from 2-3 a cell to none. It could not reach zero on
`super-magnetic-ring`: `iron-ingot` taps rows 7/10/19 and `magnet` taps rows
8/11/37, two items on ADJACENT lane rows of the same corridors, so each trunk's
bridges fall a tile from the other's junctions whichever way round they go, and
over every permutation of the four columns the count bottoms out at one. Height
was the answer and ordering was not, so the ordering pass came out again rather
than being kept as a second mechanism against a rule that no longer binds.

**RAISING THE BRIDGE INSTEAD DOES NOT FIT, and that is why the inversion is the
one that works.** A bridge clears a junction at `z > 1.7475`, so `z = 2`.
`_trunk_x` spaces trunks two columns apart with one free ramp column each and a
belt climbs half a level per tile, so leaving the lane at `z = 0` a bridge can
be at `1/2` on the ramp column and at most `1` on the FIRST trunk column it
crosses, and arriving at its own trunk at `z = 0` it can be at most `1` on the
LAST one. The first and last trunk column a bridge crosses can never be cleared
at this pitch whatever the middle does; clearing them needs four free columns
west of trunk 0 and three before the target trunk, which more than doubles the
margin. Dropping the crossing costs none of that.

Two other escapes were considered and are dead: **jogging the bridge to a clear
row** (the margin's ramp columns are occupied at every row by the other bridges,
and a detour under one of them is a belt-over-belt clearance violation), and
**moving the junction off the trunk column** (every column in the margin is
crossed by bridges, so it relocates the clash rather than removing it).

### What it measures

Paired and interleaved against a pristine `9dffc5d` clone with its own
`uv sync` and its import path asserted, four arms a round, three rounds, sixteen
cells at a time under a 300s cap per arm. `-ON` names `game.belt_collide`
explicitly so a conviction shows as INVALID rather than as a refusal; in the fix
arm the check is default-on, so its two arms are the same configuration measured
twice.

    arm                spine clean/72     freeform clean/72    convicted cells
    base, check off      41  41  40         65  64  65               --
    base, check ON       28  28  28         52  52  54          25  25  23
    fix  (default-on)    40  41  41         63  65  64           0   0   0
                         40  40  40         64  64  64           0   0   0

**Twenty-five convicted corpus cells to zero, three rounds running.** The base's
convictions are stable to the cell -- `casimir-crystal`, `information-matrix`,
`quantum-chip` and `super-magnetic-ring` on spine, the same three minus
`casimir-crystal` on freeform -- and the fix arm carries none in any round. The
clean rate is inside the base's own spread on both strategies WITH the check on,
which is what "no coverage lost" means here. INVALID 0 in every arm that is not
deliberately naming the check.

Area, on the cells clean in both arms of a round: **+0.93%, +0.90%, +1.71%**
mean over 103-104 cells, spread -14% to +52%. The spread is freeform's height
sweep, which is stochastic and moves cells by tens of percent either way between
runs of the SAME arm; the mean is consistently positive by about a point, which
is small but is not nothing, and it is the price of the merge cells the frontier
withdraws.

**MASTER MOVED UNDER THIS WORK.** `bl-runway` and `bl-stale` merged while it was
in progress, so the baseline above is a clone of `9dffc5d` -- the commit this
branch was cut from -- and not the main checkout, which is two merges ahead. An
earlier round measured against the moved checkout by mistake and read as a
twenty-cell regression that was entirely `bl-runway`'s spray-coater work; that
is what a baseline you did not pin looks like. The branch merges onto the new
master with one conflict, in `tests/dsp/test_colliders.py`, where both sides
appended a test.

## RESOLVED -- the ten-coater case never owed any runway, and eleven cells came with it

`super-magnetic-ring*60/max-proliferation` lays out and validates clean, at both
power settings. Mid-tier spine goes **32/48 -> 43/48**, five interleaved paired
rounds, every round identical in both arms, **INVALID 0 throughout**, and the
**total area over the cells clean in BOTH arms is unchanged to the tile**
(23795 -> 23795). Eleven cells moved REFUSED -> CLEAN and none moved the other
way:

    electromagnetic-matrix/max-proliferation  power=1
    graphene/max-proliferation                power=0,1
    magnetic-coil/max-proliferation           power=1
    plastic/max-proliferation                 power=1
    processor/free-proliferation              power=0,1
    processor/max-proliferation               power=0,1
    super-magnetic-ring/max-proliferation     power=0,1

At `--tier large` (60 cells, everything but the stress tier) the same paired
interleaved shape, three rounds: **A [40, 40, 39] -> B [55, 55, 55]**, INVALID 0
in every round, **16** cells REFUSED -> CLEAN and none the other way, adding
`casimir-crystal/max-proliferation` and `information-matrix/max-proliferation`
at both power settings. Area over the cells clean in both arms moves 101479 ->
101400, and both cells that moved are `information-matrix/no-proliferator` --
a spec with no coater in it at all, so it is CP-SAT nondeterminism and not this
change, which cannot run when `prolif is None`.

The stress tier is not paired here and the honest reason is the 300s command
cap: the master arm spends **148 seconds on `quantum-chip/max-proliferation`
alone**, refusing, and never finished a full-corpus round inside it. This arm
did the whole 72 cells in 25s wall for 59/72. A refusal that costs the retry
ceiling is exactly what stops costing it when the spur places.

**THE RUNWAY QUESTION HAD A ONE-LINE ANSWER, and it is that there is no
runway to find.** This entry asked whether the tenth spur has room for sixteen
tiles of ramp. It never needs one: `lab.techs.belt_rules_for_url` reads a URL
carrying no technology set as EVERY technology researched, so every corpus URL
including this one comes back `vertical_construction=True, lab_level=9`, and
with `beltVerticalConstruction` a level change costs no horizontal run at all --
`geom.altitude_step` returns before the slope test. Sixteen tiles of ramp is the
cost on a save that has NOT researched it, and no corpus cell is such a save.
Measuring that took one call and saved building a shape around a constraint that
was not there.

**What shipped is the rule, not a constant.** `_belt_floor_over` asks
`colliders.belt_crossing_height` per model and rounds the game's STRICT bound up
to `BELT_Z_QUANTUM`: 3.5325 over an Assembling Machine becomes `z = 4`, not 3.5.
Sorters and belt addons are excused outright by `PrefabDesc` flag, and a belt is
not a probe target at all -- so all 449 sorter/splitter/coater blocks and the
499 belt blocks this entry counted were never crossings. `_SpurField`
precomputes `(floor, taken)` per tile and `_spur_clear` delegates to it, so the
readable one-tile rule and the search cannot drift.

**The altitude is part of the search state now**, not a profile applied to a
2D route afterwards. That is what makes the ramp honest on a save without the
unlock: without `beltVerticalConstruction` a step may move the altitude by at
most `BELT_CLIMB_PER_TILE`, so a route with no room to climb simply never
reaches the goal, and the old "route shorter than the climb" post-check is gone.
With the unlock each tile takes the LOWEST altitude it allows at or above the
addon level -- byte-identical to the old behaviour wherever nothing is crossed,
which is why the area did not move.

`_MAX_SPUR_Z` is `DEFAULT_MAX_BELT_Z` (8.5 on the quantum), the ceiling on a NEW
save. The layout is not told the URL's `buildMaxHeight` -- only the validator is
-- so a spur that assumed a researched ceiling would ship geometry
`geom.altitude_range` refuses on exactly the saves that cannot paste it. Nothing
in the corpus asks for more than 4.

**`game.belt_crossing` is genuinely exercised, and the falsifier was run.**
Replacing the per-model height with a constant `0.5` makes spine's own
self-validation reject every plan it emits -- "every plan that emitted was
rejected by our own validator: game.belt_crossing" -- so the check is not
decoration here. `game.belt_collide`, the lateral half, went 4 findings over 32
placed cells to 6 over 43: the two extra are the two `max-proliferation` cells
that now exist at all, each carrying the same single pre-existing
belt-beside-splitter conviction the other three `super-magnetic-ring`
candidates already had, on a `magnet` riser bridge. **Zero of the six are on a
proliferator belt**, i.e. none is a spur -- against a sample of 267 proliferator
belts in that one placement, 19 of them flying above the addon level.

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

**THE HEIGHT WAS NOT THE ONLY THING BLOCKING A SPUR**, and what is left is a
different defect entirely -- see the next entry.

## OPEN -- five spur refusals are left and every one is a drop OUTSIDE the bounding box

The five mid-tier cells still refusing are `electromagnetic-matrix/max-`,
`magnetic-coil/free-` and `/max-`, `plastic/free-` and `/max-proliferation`, all
at `power=0`, and instrumenting `_coater_spur` says the same thing about all
five: **the coater's addon cell is at `x = -1`**, one column outside the
placement's own bounding box.

    electromagnetic-matrix  tail=(9, 0)   drop=(-1, 1)  box=(0, 15, 0, 27)
    magnetic-coil           tail=(3, 5)   drop=(-1, 6)  box=(0,  5, 0, 15)
    plastic                 tail=(20, 0)  drop=(-1, 1)  box=(0, 24, 0, 16)

`_coater_spur` is bounded to the existing footprint on purpose -- a spur may not
enlarge the factory to supply a coater -- and the bound applies to the DROP as
well as to the route. But the drop is not the spur's choice: the coater is
already placed, `addonAreaPoses` puts its proliferator area one tile behind it,
and a coater on the block's west edge therefore has an addon area the search is
forbidden from reaching. No amount of height helps; there is nothing to search.

**Two candidate fixes and they are not equivalent.** Either let the box include
the forced drop cell (one column of area, bounded, and the coater is already
committed), or stop `_coater_tile` choosing a mount column whose addon area
falls outside the block. The second keeps the area promise intact and is
probably the right one; the first is one line and needs the area measured, since
`docs/AB_COMPARISON.md` is scored on it. Neither has been measured yet.

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

## RESOLVED -- the layout obeys the slot tables, and rotation answered the geometry

**RE-CHECKED AGAINST LIVE CODE 2026-08-25. Two of the three structural
consequences below were closed eighty minutes after this entry was written and
nobody came back to say so.** The entry landed at `6c43bd8` (Mon 14:33);
`69eddea`, "Rotation: a machine is turned to face the lanes that must feed it",
landed at 15:53. Everything from "Neither strategy can rotate a machine today"
onward has been false since. The original text is kept below, struck through
where it expired, because the RULES it states are still the right description of
the game -- it is the *consequences* that moved.

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

`attachable_columns` for a lane one row clear of the machine, both sides.
**REGENERATED FROM LIVE CODE 2026-08-25**, at the yaw `slots.lane_orientation`
actually picks and against the footprints as `0df4b57` corrected them -- the
version written at `6c43bd8` was upright-only and pre-`GRID_ARC`, so three of its
six rows are wrong now:

| building | built as | from above | from below |
| --- | --- | --- | --- |
| Assembling Machine (all three), Arc/Plane/Negentropy Smelter, Depot Mk.I | 3x3 | 0,1,2 | 0,1,2 |
| Depot Mk.II | 5x3 | 1,2,3 | 1,2,3 |
| Matrix Lab, Self-evolution Lab | 5x5 | 1,2,3 | 1,2,3 |
| Chemical Plant, Quantum Chemical Plant | 7x5 | 2,3,4,5 | 2,3,4,5 |
| Miniature Particle Collider | 9x5 | 1,2,3 | 1,2,3 |
| **Oil Refinery** | **7x3, at yaw 90** | **2,3,4** | **2,3,4** |
| Ray Receiver, Energy Exchanger, Spray Coater | -- | **none** | **none** |

Three structural consequences were drawn from that table. **Two are closed and
the third was never a defect:**

1. ~~**An Oil Refinery cannot be served from the north.**~~ **CLOSED by
   `69eddea`, which is the rotation this item asked for.** The rule is read from
   the table rather than tabulated: `slots.lane_orientation` prefers an
   orientation reachable from BOTH sides, then from either, and breaks ties
   toward upright so nothing turns without cause. Only 0 and 90 are candidates,
   because mirroring cannot take a pose off a face. **The Refinery is the only
   building in the catalog that moves**, and at yaw 90 it is a 7x3 offering
   columns 2,3,4 to a lane on EITHER side. Both strategies call it --
   `spine.py:327`, `freeform.py:1093` -- and
   `tests/layout/test_sorter_slots.py` pins `lane_orientation(2308) == 90.0`
   and `0.0` for every other building, so a regression that rotated everything
   would fail as loudly as one that rotated nothing.
2. **A wide machine offers fewer columns than its width.** STILL TRUE and not a
   defect: it is what the prefabs say, and it is modelled rather than worked
   around. `_pick_sorter` is sized against the attachable count rather than the
   footprint width, which buys capacity back by raising the tier. The figure in
   the original text needs one correction -- a Chemical Plant is 7x5, not 9x5,
   since `0df4b57` -- so it offers **four of seven** columns, not four of nine,
   and four sorters per lane is its ceiling.
3. ~~**A Chemical Plant's southern anchor is a row INSIDE its footprint.**~~
   **The geometry is still exactly that; the packers now obey it, which is what
   this item asked for.** Measured on live code, as the deepest lane that still
   attaches, counted in clear rows between footprint edge and lane:

   | | above | below |
   | --- | --- | --- |
   | Assembling Machine, Matrix Lab, Oil Refinery (7x3), Particle Collider | 0,1,2 | 0,1,2 |
   | **Chemical Plant, Quantum Chemical Plant** | **0,1** | 0,1,2 |
   | Artificial Star, Vertical Launching Silo | 0,1 | 0,1 |

   Both strategies charge that per side and from the poses: spine's
   `_reach_charge`/`_anchor_span` and freeform's `_side_lane_caps` both walk
   outward from the band and stop at the first row `slots.attachable_columns`
   returns empty for. `_reach_charge`'s own docstring records the trap this
   replaced -- one worst-of-both-sides number that was wrong on BOTH sides and
   right in the total, so an aggregate check cleared it.

**The "51 tests fail" measurement is dead.** `uv run pytest` is **1323 tests,
0 failures**; `test_spine.py` and `test_freeform.py` are 176 and 228 of them and
all green. The corpus figure moved with it: measured 2026-08-25 over four runs,
freeform on the full stress corpus is **64-66/72 clean** (66, 65, 64, 66) and
spine on the 48-cell mid tier is **32/48**, with **INVALID 0 and crashed 0 in
every run** -- against the "8/30 clean" recorded above. The band is CP-SAT's,
not a regression: it is quoted as a band because a single number from it has
been mistaken for a movement on this project before.

**WHAT IS ACTUALLY LEFT, AND IT IS THE LAST ROW OF THE TABLE.** Freeform's
misses are six `universe-matrix` cells in every run, all the same refusal:
*"a machine in this spec has lanes to wire and no insert pose to wire them to"*
-- the Ray Receiver. The one or two `quantum-chip` cells that join them in a
tight run are load, not geometry: run alone, `--only quantum-chip` is 6/6 clean.
The Ray Receiver case is not this entry's; it is settled and owned
by **"RESOLVED -- the extraction is complete; these buildings take belts, not
sorters"** above, whose open tail is belt-to-port docking. Spine's sixteen mid-
tier misses are all the Spray Coater supply case, owned by **"OPEN -- spine's
ten-coater case is a runway problem now, not a rules one"**. Nothing refuses for
a reason this entry names.

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
coater's addon area. ~~Neither strategy can route one, so `game.addon_supply`
reports the coater unsupplied and every proliferated candidate refuses.~~

**BOTH ROUTE ONE NOW; only the diagnosis above survives.** Spine grows an
elevated spur from a lane's tail to the drop and chains coaters onto one supply
belt (`795fc03`, and the entry "RESOLVED -- spine grows elevated lanes, and the
drop was never the hard part"); freeform's coater supply came out clean on the
re-measurement of 2026-08-23 with **zero `prolif.*` findings over nine corpus
runs**. What remains is spine's runway, which is its own OPEN entry and is a
question of where the spur can go, not of whether the connection exists.

The rule itself is unchanged and still the point: the sorter this replaced
looked like a feed and was not one, and nothing could see that because a coater
has no `slotPoses` for `CheckInserterDataLegal` to check.

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

**Rules still unextracted** -- none of the belt ones. The LATERAL half of the
belt collision rule is extracted now too: the excusal is `CheckBuildConditions`
147257, and it ships as `colliders.belt_collisions` and `game.belt_collide`.
That check is in `validate.OPT_IN` because it convicts OUR output, not the
game's -- see the belt item under "our footprints are a tile grid" below.

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


## RESOLVED -- the footprint fix landed; the one live defect left has its own entry

The fourth and last unexplained error from the first in-game paste,
"Collide with other object" (`EBuildCondition.Collide = 34`), is ours colliding
with ourselves. ~~It is now extracted, modelled and measured; what is NOT done
is the layout fix, which is why this entry is OPEN.~~

**RE-CHECKED AGAINST LIVE CODE 2026-08-25. The layout fix landed.** `geom.collide`
is a normal ERROR check that both strategies pass on the whole corpus,
`validate.OPT_IN` is down to the single entry `game.belt_collide`, and the audit
measured today is **INVALID 0 in every run** -- freeform 64-66/72 over four runs
of the full stress corpus, spine 32/48 on the 48-cell mid tier, crashed 0 in
both. Items 1
and 2 below are already marked DONE by the commits that did them, and item 3's
excusal was found and merged at `bce0c31`/`9f174dc`.

**What is left of this entry, item by item:**

* Item 3 names a REAL live defect -- our belts sit beside splitters the game
  would refuse, which is why `game.belt_collide` is still opt-in. That defect
  has its own entry, **"OPEN -- we place belts beside splitters the game would
  refuse, and the obvious guard does not fix it"**, with the geometry settled,
  the obvious guard measured and rejected, and three candidate fixes to choose
  between. Go there; do not re-derive it here.
* Item 4, sorter-on-sorter, is genuinely NOT done, and **the reason it gives is
  stale.** See its own text below: the blocker is no longer the slot data.
* Nothing else in this entry names a layout defect that still reproduces.

**One pointer into this entry needs correcting, and it is why closing this
mattered.** The entry *"the extraction is complete; these buildings take belts,
not sorters"* says belt-to-port docking "sits behind" this one, because "a belt
overlapping a machine is legal in game and illegal in our grid". The footprint
half of that is fixed. What actually forbids it now is the ROUTER's occupancy
policy, not the footprint rule: `freeform._Canvas.add` stakes a machine with
`solid=True`, which writes every level of every footprint tile into `blocked`,
so no belt may enter a machine's tiles at any altitude. That is a routing policy
to be revisited on its own terms, with its own measurement -- it is not waiting
on anything here.

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

3. **Belts are fully modelled now, and the model refuses us.** They are tested
   as a 0.23 sphere at `lpos + lpos.normalized * 0.2`, and a belt hitting a
   machine is not excused. The vertical half ships as `game.belt_crossing`.

   **The lateral excusal is found.** It is not `BuildTool_Path`'s drag index,
   which is what the previous reading looked for and rightly did not find. It
   is a THIRD pass over the belts inside `CheckBuildConditions` itself, at
   147257. The main loop sets a belt to `Collide` at 146072 *without* calling
   `AddErrorMessage` -- the only branch in the method that stays silent --
   because 147384 re-probes every belt already marked and can put it back to
   `Ok`. A belt is excused:

   * against a building its own run reaches within **three belt hops in either
     direction** (147451), and against a Splitter's own linked previews within
     two;
   * against any sorter preview (the `isInserter` asymmetry, 147437) and any
     belt addon (147454, `AddonPass`'s twin);
   * and, failing all of that, whenever the run ends in a buildable non-belt
     building (147492).

   Measured: the raw probe convicts **1189** belts across the fixture corpus;
   with the excusals, **0** on every fixture whose geometry the model can place
   -- all five single-area ones, and both of the others that decode cleanly.
   The falsifier is the same run with the upstream clauses dead: 25 convictions,
   4 of them against a Splitter at exact spacing, each the second or third node
   of a run leaving one -- which is exactly what those clauses describe.

   One detail is **read but not settled**: `ArrangeOverlapBP` materialises the
   reverse belt links at 144472 and clears them again at 144554, which taken at
   face value would make the three `input` clauses of 147451 dead on a paste.
   The corpus says they are live. Either the clearing does not survive to
   147384 or something restores it; settling that needs a runtime trace or a
   second decompile, and the rule is measured either way.

   `colliders.belt_collisions` holds it with the C#; `game.belt_collide` is it
   against a `Placement`. **That check is in `validate.OPT_IN`**, and the reason
   is step 1 above: a Splitter's `catalog.footprint` is 1x1 against a 2.38-unit
   collider, so both strategies route belts one tile from a Splitter -- at
   ground level and, on ramps, one level up, where the probe still catches the
   1.19-unit arm by 0.16 of its 0.23 radius. Turning it on turns 15 `spine`
   tests red -- `magnetic-ring`, plus `quantum-chip/no-proliferator` and
   `free-proliferation` -- because the strategy's own self-check then refuses
   every plan it emits. ~~That is a ROUTER bug the footprint fix resolves,
   exactly as spacing took `geom.collide` out of `OPT_IN`.~~ **That prediction
   was made here and then falsified.** The footprint fix landed (item 1) and the
   check is still opt-in: with it on the corpus drops to 59/72 against 64-66
   with it off, every loss a refusal rather than an invalid. The router bug is
   real and it is separate -- it is the belt-beside-splitter entry, where the
   ordering argument for why the obvious guard fails is written out. With it
   opt-in the full
   audit is unmoved: 144/144 cells at budget 4s, **INVALID 0**, and not one of
   the 38 refusals names either belt check -- they are the Spray Coater supply
   rule (spine, 32) and the missing insert poses (freeform, 6). Until then `game.belt_crossing` remains a
   LOWER bound on what the game rejects, and `game.belt_collide` is the upper
   one, available by name.
4. **Sorters likewise** -- still not done, and ~~for a known reason: a sorter's
   box is rebuilt from the poses of the buildings it connects, which needs the
   `slotPoses` data this repository had wrong.~~ **THAT REASON EXPIRED.** The
   `slotPoses` are extracted from the prefabs and correct; an Assembling Machine
   has its twelve. The live blocker is the REBUILD, and it is measured:

   * a sorter's `buildColliders` is one box, half-extents `(0.26, 0.15, 0.115)`
     -- 0.52 by 0.23 in plan -- and the game re-seats it onto the connected
     buildings' poses at `RefreshBuildPreview` 180039-180096;
   * testing that box where the blueprint RECORD puts it is refuted by the
     game's own output: **53 pairs closer than 0.52 units among the 1132 sorters
     in the five single-area fixtures**, in blueprints that paste. Shipping the
     raw test would convict the corpus, which is the same shape the belt rule
     had at 1189 raw findings;
   * so porting 180039-180096 is the work, not porting the box.

   **One measurement worth having before anyone starts.** Read through the same
   writer, in the same coordinates as the fixtures: across 16 corpus cells both
   strategies emit **702 sorters with 172 anchor points shared by two or more of
   them**, and **216 pairs under 0.52 units**. The game's 1132 share **zero**
   anchor points. That divergence may be nothing -- our machine-side anchor is a
   tile centre where the game writes a sub-tile pose, and the paste re-seats it
   from the slot index either way -- but it is the first thing the rebuild will
   have an opinion about, and it is not currently reported by anything.
   `test_a_raw_sorter_box_test_convicts_blueprints_the_game_wrote` in
   `tests/dsp/test_colliders.py` pins the fixture half so this reason cannot
   quietly expire the way the last one did.

**Not a defect, and worth not re-discovering:** columns compress by `cos(lat)`
away from the paste anchor, because the longitude step is fixed at the anchor's
latitude (`RefreshBuildPreview` 179977). Two Matrix Labs five tiles apart are
clear at the equator and collide 81 rows north of it. That is why a blueprint
can paste in one place and not another, and it is a property of WHERE it lands,
not of the blueprint -- so `geom.collide` evaluates on a flat grid at
`GRID_ARC`, the loosest spacing any equatorial paste can give, and reports only
what no paste can avoid. Asking the other question is `collisions(anchor_lat=)`.
On one `information-matrix` layout the two differ by 5 pairs against 15.
