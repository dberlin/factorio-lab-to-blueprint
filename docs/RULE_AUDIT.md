# Rule audit: where the game's rules actually live

Audited at `a1fc8fc2`, read-only, on branch `bl-rule-audit`.
Nothing in this document was changed in code; every claim cites a line.

## Headline

**The modularization is sound in its foundations and incomplete at its edges.**

`dsp/rules.py`, `dsp/colliders.py` and the rule-bearing half of `dsp/catalog.py`
are a real single source of truth, and `layout/slots.py` and `layout/junction.py`
are model consumers: they import every constant and restate none
(`slots.py:72-84`, `junction.py:39-43`). That is most of the way there.

What is not there:

* **One game rule is documented from decompiled source and enforced by nobody.**
  `catalog.BEND_MIN_ANGLE_WHEN_SLOPED_RAD` and `catalog.SLOPE_DEADZONE`
  (`catalog.py:187-196`) carry the C# for `EBuildCondition.TooBendToLift` and
  have **zero readers in the entire repository**. I measured what we emit
  against them: **24 belts across 3 specs turn 90 degrees while sloped.**
* **The router's keep-outs are expressed in integer routing LEVELS while the
  rule is in continuous blueprint `z`**, and a ramp tile occupies a `z` that is
  not its level. That is one root cause with two instances
  (`freeform.belt_ban`, `junction.keepout_cells`), latent today.
* Four independent implementations of "how high must a belt be over a Spray
  Coater", and three of "a machine slot holds one connection".

**Disagreements found: 7 (D1–D7).** Broken down honestly, because "live" is
doing a lot of work in that sentence:

* **1 is producing output the game may reject right now** — D1, measured, 24
  belts. Whether the game rejects it is one paste away from being known.
* **1 produced wrong output when it last fired and is silent on my sample** —
  D4. `freeform` still hardcodes `Facing.EAST` for every coater
  (`freeform.py:6476`); the validator's own docstring records 10 of 20 coaters
  disagreeing with the belt flow on a reported blueprint. On the three specs I
  built (20 coaters) it convicted nothing.
* **3 are latent code-path disagreements** — D2, D3, D5. The implementations
  differ; today's inputs do not reach the gap. Each has a concrete separating
  case below.
* **2 are duplications with no measured disagreement** — D6 (three hand-rolled
  copies of one rule) and D7 (a silent geometry fallback).

**The single worst one:** `TooBendToLift` is unported, and both strategies emit
it. It is the only finding in this audit whose failure mode is an INVALID
blueprint rather than a refusal — which the project ranks as the worst possible
outcome. See D1.

Honest negatives, stated because they were suspected and measured false:

* `TESLA_COVER_RADIUS` is **not** a tile/world unit confusion. I bracketed it
  on the corpus and the tile reading is right (see N1).
* Freeform's coater ban and the validator's lateral belt rule **agree exactly**
  on the cells that matter (see N2).
* No layout module hardcodes a game constant as a bare float. I enumerated every
  float literal in the AST of all eight `layout/*.py` modules; the only
  rule-shaped values are heuristic weights and time budgets (see N3).
* `PlacedBuilding.width`/`height`, the "cache with no verification", **is** now
  verified: `geom.footprint` (`validate.py:781-861`) compares it against
  `catalog.oriented_footprint` on every building. That concern is closed.

---

## 1. The rule inventory

Legality means *the game would reject the paste*. Quality means *the factory
would be worse*. Only the first column belongs in `dsp/`.

### 1.1 Legality rules

| Rule | Authoritative location | Also implemented / approximated in | Agree? | Risk |
|---|---|---|---|---|
| Build-collider overlap (`EBuildCondition.Collide`) | `colliders.collisions` + `colliders.obb_overlap`, `colliders.py:GRID_ARC` | `catalog.clearance` (`catalog.py:962-1001`, derived, conservative); `spine.py:4406`, `junction.py:143` each recompute `(mine + max(clearance))/2` by hand | Derived, conservative; the two `/2.0` copies are duplicated arithmetic | LOW–MED |
| Belt probe vs building collider, vertical (`game.belt_crossing`) | `colliders.belt_crossing_height` (`colliders.py:648-672`) | `spine._belt_floor_over` (`spine.py:3747-3788`); `freeform._Canvas.belt_ban` (`freeform.py:6510-6535`); `validate._addon_crossings` (`validate.py:2158`); `catalog.BELT_CROSSING_CLEARANCE` (`catalog.py:185`, hand-typed `1`) | Three of four agree; `BELT_CROSSING_CLEARANCE` is a blanket `1` that is WRONG for a coater (needs 2) — see D3 | MED |
| Belt probe vs building collider, lateral (`game.belt_collide`) | `colliders.belt_collisions` (`colliders.py:928-1019`), `colliders.belt_keepout_offsets` | `junction.keepout_cells` (`junction.py:65-83`, derived from the authoritative function); freeform `guard`; spine's trunk-under-bridge geometry (`spine.py:2940-2961`) | Derived, but re-keyed from blueprint `z` onto integer levels — see D2 | MED |
| Belt slope ceiling (`TooSteep`) | `catalog.MAX_BELT_SLOPE` + `catalog.BELT_Z_PER_WORLD_UNIT` (`catalog.py:145-163`) | `validate._altitude_step` (`validate.py:1076-1114`); `freeform.transition_form` / `_legal_link` / `_altitude_profile` (`freeform.py:2642-2801`) reason about it in prose and emit a fixed `BELT_CLIMB_PER_TILE` ramp instead of testing the bound | Agree in effect (2/3 < 4/5 always), but the router never evaluates the predicate | LOW |
| **Sloped belt may not turn (`TooBendToLift`)** | `catalog.BEND_MIN_ANGLE_WHEN_SLOPED_RAD`, `catalog.SLOPE_DEADZONE` (`catalog.py:187-196`) | **NOWHERE. Zero readers.** | **N/A — unported** | **HIGH** |
| Belt altitude ceiling (`buildMaxHeight`) | `catalog.belt_max_z` / `BeltAltitudeRules` (`catalog.py:202-336`) | `validate._altitude_range` via `ctx.max_belt_z`; `spine._MAX_SPUR_Z` (`spine.py:3742`, derived); `freeform.LEVELS = 3` (`freeform.py:160`, a router budget, explicitly NOT the ceiling) | Agree | LOW |
| Sorter end within reach of the slot pose it names | `rules.SLOT_REACH` + `rules.world_gap` (`rules.py:294-310`, `139-152`) | `validate._inserter_data` (`validate.py:1560-1573`); `slots.attachment` (`slots.py:356-358`) | Agree — both go through `world_gap` | LOW |
| Slot must face the sorter | `CheckInserterDataLegal`'s sign test, applied at `validate.py:1573-1587` (`dot < 0`) | `slots.attachment` (`slots.py:359-363`) uses `rules.SLOT_ALIGN_COS` = cos(24°) on a **2-D, un-normalised** projection | **Different predicates** — see D5 | LOW (latent) |
| Sorter length window | `rules.SORTER_LENGTH` (`rules.py:388-392`) | `validate._inserter_skew`. `slots.attachment` deliberately does not apply it, with a stated argument (`slots.py:315-318`) | Agree by argument | LOW |
| Sorter skew (`TooSkew`) | `rules.SKEW_PAIR_DEG`, `rules.SKEW_AXIS_DEG` (`rules.py:394-409`) | `validate._inserter_skew` (`validate.py:1827-1848`). `slots.py:311` cites `SKEW_AXIS_DEG` for a **different vector pair** | One constant, two meanings — see D5 | LOW |
| Paste snap ladder (`ErrorInserterData`) | `rules.PASTE_SNAP/LATERAL/RADIAL/LATERAL_EPS` (`rules.py:347-359`) | `validate._inserter_paste` only. No search-side counterpart | Search-blind — see section 3.2 | LOW |
| One connection per `(object, slot)` | `rules.CONN_SLOTS_PER_OBJECT` (`rules.py:210-264`) | `validate._slot_occupancy`; `freeform` `claimed` dict (`freeform.py:2487-2493`); `spine` `claimed` dict (`spine.py:3590-3600`) | Agree in intent, **three hand-rolled copies** — see D6 | MED |
| Belt auto-slot range (a belt tile takes 8 such links) | `rules.BELT_SLOT_AUTO_RANGE` (`rules.py:266-282`) | **Nothing checks it** — stated in its own docstring | Unported | LOW |
| Splitter port count | `rules.SPLITTER_MAX_PORTS` (`rules.py:285-289`) | `validate._junction_ports`; `junction.check_ports`; `freeform.py:5090` | Agree, all import | LOW |
| Splitter slot indices | `rules.SPLITTER_INPUT_TO_SLOT` / `_OUTPUT_FROM_SLOT` | `junction.py:39-43` imports | Agree | LOW |
| Sorter own-slot ordering (0=out, 1=in) | `rules.OUTPUT_FROM_SLOT` / `INPUT_TO_SLOT` | `validate._own_slots`, `validate._inserter_data`, `slots.py` imports | Agree | LOW |
| Addon attach radius | `rules.ADDON_AREA_RADIUS` (`rules.py:414-432`) | `validate._addon_supply`, `validate._coaters_supplied` | Agree | LOW |
| Addon attach line clause (`DistancePointLine < 0.3f`) | **No constant, no port** — recorded as unported in `rules.py:428-431` | — | Unported | MED |
| Addon may not lie across its belt (`AddonPass`) | **`validate._addon_facing` (`validate.py:1906-2029`) IS the authority** — `0.95` lives only in its docstring, the code is `off in (0, 180)` | `spine._feed_coater` picks the flow yaw; `freeform._place_coaters` writes one yaw for every coater | Rule lives in the validator, not in `dsp/` — see D4 | MED |
| Addon corner rule (decompiled 145812: ridden belt's own input AND output on the addon line) | **Unported.** Recorded in `docs/BACKLOG.md:100-105` | — | Unported | MED |
| Belt single occupancy | `validate._belt_single` (ours; the game's own answer turns on `dotsCursor`, per `colliders.py:944`) | freeform `world_taken` + `blocked`; spine `_SpurField.taken` | Agree | LOW |
| Power coverage radius | `catalog.building(id).cover_radius`, from extracted `data/buildings.json` | `validate._coverage` and `freeform._power_plan` (`freeform.py:5367-5369`) both read the extracted value and both use the identical doubled-integer form `floor((2*r)**2)`. **`spine` reads the hand-typed `catalog.TESLA_COVER_RADIUS` (`catalog.py:377`) via `CONSTANTS.supply_radius` (`spine.py:133`)** and linearises it through `geometry.reach_table` | Agree — I verified the hand-typed `21/2` equals the extracted value, and `reach_table`'s `floor(sqrt(r^2-d^2))` is the same disc as the validator's `d2 <= (2r)^2` for a 1x1 tower | LOW |
| Power link distance | `catalog.building(id).connect_distance`, extracted | Same split: `validate` and `freeform` read the extracted value, `spine` reads `catalog.TESLA_LINK_DISTANCE` (`catalog.py:411`) via `CONSTANTS.link_distance` (`spine.py:4508`) | Agree today; the copy is redundant | LOW |
| Declared footprint == prefab | `catalog.oriented_footprint` | `validate._footprint` guards it | Agree | LOW |
| Blueprint format caps | `validate._bounds` | — | Sole owner | LOW |

### 1.2 Rules that are ours, not the game's — must NOT migrate

Listed so a consolidation does not sweep them in. `rules.py:50-57` already names
most of them; this adds the ones it does not.

* `catalog.SORTER_MAX_REACH = 3` — a corpus measurement, already labelled.
* `catalog.BELT_CLIMB_PER_TILE`, `RAMP_TILES_PER_LEVEL` — what we EMIT.
* `catalog.BELT_Z_QUANTUM = 1/2` — a corpus habit. **`geom.altitude_range`
  enforces it as if it were a game rule** (`validate.py:1037-1045`). The game
  stores `localOffset_z` as a float and quantises nothing. This is an invented
  constraint; it is harmless because we only emit halves, but it is a check
  that would refuse a legal blueprint.
* `catalog.BELT_CROSSING_CLEARANCE = Fraction(1)` — sourced "per the user"
  (`catalog.py:181-185`), not from a collider. See D3.
* `freeform.LEVELS`, `MARGIN`, `WEST_CHANNEL`, `_GROUND_TOLL`, `RRR_MAX`,
  `_PACK_SHARE`, all `_REPAIR_*`, `_BLAME_*` — search parameters.
* `spine.UNIFORM_ROW_PITCH`, `_CORRIDOR_DEPTH_MARGIN`, every `FALLBACK_*`.
* `validate` `machine.*`, `flow.*`, `spec.*`, `prolif.*`, `belt.acyclic`,
  `belt.termination`, `sorter.filter`, `geom.machine_ground` — factory
  correctness, not paste legality. `geom.machine_ground`'s own docstring says so
  ("Machines this GENERATOR places sit on the ground").

### 1.3 Coverage statement — what this inventory does and does not cover

Method, so the gaps are known rather than assumed:

* **Complete:** all 53 registered checks in `validate.py`, enumerated by parsing
  the AST for `@check(...)` decorators, each mapped to the `cat.`/`rules.`/
  `colliders.` symbols its body touches (by a throwaway AST script, not committed).
* **Complete:** every module-level constant in `dsp/rules.py`, `dsp/catalog.py`,
  `dsp/colliders.py`, and every `layout/*.py`, by grep of
  `^_?[A-Z][A-Z_0-9]* *[:=]`.
* **Complete:** every float literal appearing in the *code* (not comments or
  docstrings) of all eight `layout/*.py` modules, by AST walk.
* **Complete:** every import of `dsp.rules` / `dsp.colliders` / `dsp.catalog`
  across `src/`, `tests/`, `scripts/`.
* **NOT covered:** rules the decompiled source contains that this repository has
  never written down anywhere. The decompiled C# is not in the tree; I could
  only audit against what `rules.py`, `colliders.py`, `catalog.py` and
  `BACKLOG.md` quote. Section 4 lists the ones they quote and do not port; there
  may be others nobody has read yet. Closing that needs the decompiled source,
  not this audit.
* **NOT covered:** `dsp/codec.py`, `dsp/params.py`, `dsp/envelope.py`,
  `lab/*`, `rates/*`. Spot-checked for rule constants (`codec.py` references
  `GRID_ARC` only in comments); not exhaustively walked.

---

## 2. Disagreements, worst first

### D1 — `TooBendToLift` is unported, and we emit it. WORST.

**The rule.** `catalog.py:187-196`, with the game's own code:

```
if (num21 < 2.5f && num25 > 0.1f)
    buildPreview2.condition = EBuildCondition.TooBendToLift;
```

`num21` is the angle at this belt between its input and output in radians;
`num25` is its slope ratio. So a belt that both bends more than ~36 degrees off
straight and has a slope over `0.1` is refused.

**Who implements it.** Nobody.
`grep -rn "BEND_MIN_ANGLE_WHEN_SLOPED_RAD\|SLOPE_DEADZONE" src/` returns only
the definitions themselves and the index line in `rules.py:44`. The validator
has no `bend` check; `geom.altitude_step` (`validate.py:1049-1114`) ports
`TooSteep` from **the same function, three lines away**, and stops there. The
router has no bend concept: `freeform._RAMPS` (`freeform.py:358-365`) offers
`+/-1` level and `_astar`'s ramp move is a straight two-cell run in one
direction (`freeform.py:3369-3378`), which keeps the *via* cell straight but
says nothing about the cell it lands on.

**Measured.** Reconstructing the game's two quantities from what we emit
(throwaway script, not committed; the reconstruction is described below), over `graphene`, `electromagnetic-matrix` and `plastic`,
both strategies, `time_budget_s=6`:

```
                              BEND / sloped belts
graphene/freeform                 2 /  8
graphene/spine                    6 / 18
electromagnetic-matrix/freeform   2 /  7
electromagnetic-matrix/spine     10 / 30
plastic/freeform                  0 /  0
plastic/spine                     4 / 12
TOTAL                            24 / 75
```

Every hit is `angle = 1.571` (a right angle) with slope `0.375` (spine, a belt
at `z = 1` whose input is a ramp tile at `z = 1/2` and whose output turns) or
`0.750` (freeform). Both are far over the `0.1` deadzone and far under the
`2.5` rad bound.

**The breaking case, concretely.** A spine spur climbs `0 -> 1/2 -> 1` and then
turns. The belt at `z = 1` has its input at `z = 1/2` one tile back and its
output one tile to the side: `num25 = (1 - 1/2)/(3/4) / (sqrt(2) * 1.2566)
= 0.375 > 0.1`, `num21 = pi/2 = 1.571 < 2.5`. `TooBendToLift`.

**Caveat, stated rather than hidden.** `TooBendToLift` is quoted from
`BuildTool_Path` — the interactive belt tool — not from
`BuildTool_BlueprintPaste`. If paste does not run it, none of these 24 matter.
But `TooSteep` comes from *the same function* and this project already treats it
as binding on a paste (`validate._altitude_step` exists and refuses layouts on
it). **Either both bind or neither does, and we currently enforce exactly one.**
That asymmetry is the defect regardless of which way it resolves.

**What would settle it:** paste one blueprint containing a turn immediately
after a ramp. That is a five-minute in-game test and it decides whether this is
a HIGH-severity invalid-blueprint bug or a dead constant to delete. Nothing in
this repository can settle it.

### D2 — Keep-outs are keyed on integer routing LEVELS; the rule is in blueprint `z`

**The rule.** `colliders.belt_keepout_offsets` and `belt_crossing_height` answer
in blueprint `z`, continuously. A Splitter's collider stands 2.30 world units =
1.725 blueprint `z`; a Spray Coater's stands 1.8975.

**The copies.** Both search-side keep-outs are dictionaries keyed on an integer
level:

* `freeform._Canvas.belt_ban: dict[(x,y), set[int]]` (`freeform.py:2049`),
  filled at `freeform.py:6519-6535` with `for level in range(1, floor(need)+1)`.
* `junction.keepout_cells(x, y, level)` (`junction.py:65-83`), returning
  `(x+dx, y+dy, level+dz)`.

**Why they disagree with the rule.** A ramp tile does not sit at its level. Per
`_altitude_profile` (`freeform.py:2734-2769`) the cell that changes level gets
`z = lvl * _LEVEL_HEIGHT ± 1/2`, and per `_Canvas.add` (`freeform.py:2068`) it
reserves the level A* verified — the level it *departs*. So a belt **descending**
from level 2 to level 1 stands at `z = 3/2` while occupying lattice level **2**.

* Over a Spray Coater: `belt_ban` holds `{1}`. Level 2 is free. The belt lands
  at `z = 1.5 < 1.8975`. `validate.game.belt_crossing` convicts it.
* Beside a Splitter: `_KEEPOUT` holds `dz in {0, +1}`. A splitter at level 1
  keeps out levels 1 and 2 — so this one is caught. A splitter at level 0 keeps
  out 0 and 1; a belt descending 2->1 through a neighbour cell holds level 2,
  is not caught, and stands at `z = 1.5 < 1.725`.
  `validate.game.belt_collide` convicts it.

**Status: LATENT.** I scanned the chosen placements of `graphene`, `plastic` and
`processor` on both strategies for a belt at a non-integer `z` inside a coater's
oriented footprint: **0 found**, and 0 ERROR findings across all attempts
including the rejected ones. The hole is in the code path, not in today's output.
The validator's own docstring records that it *used* to fire —
"our own output has six such belts in `freeform` and eight in `spine` — six at
one level, **two at one and a half**" (`validate.py:2123-2125`). The "one and a
half" belts are exactly this hole.

**Fix shape:** key both structures on blueprint `z` (`Fraction`), not on level,
and have `_Canvas.add` register the ramp tile's real `z` — `world_taken`
already does exactly that (`freeform.py:2092-2094`) for the single-occupancy
question, so the machinery exists.

### D3 — `BELT_CROSSING_CLEARANCE = 1` is hand-typed and wrong for a coater

`catalog.py:181-185`:

> Height a belt must gain to pass OVER a ground-level obstruction, **per the
> user**: a belt at `1/2` still fouls one at `0`, so a crossing tile has to be a
> full `1` above what it crosses.

That is a blanket constant where `colliders.belt_crossing_height(model_index)`
gives the exact per-model answer, measured from the prefab's build collider.
Measured values: Spray Coater **1.8975**, Arc Smelter 2.7975, Assembling Machine
Mk.II 3.5325, Chemical Plant 4.9725. **All four exceed 1.** A belt one level
above any of them is inside its collider.

It survives because of where it is used, not because it is right:

* `spine._TRUNK_Z = catalog.BELT_CROSSING_CLEARANCE` (`spine.py:2961`) — a
  belt-over-belt separation, where the per-model function returns `0.0`
  (belts have no target box) and the real constraint is single occupancy.
* `freeform.py:150` cites it only in prose, to justify `LEVELS = 3`.

So it is currently used for a question it is not the answer to. The name says
"belt crossing clearance"; the value is "belt-over-belt vertical separation".
Two different rules sharing one constant is precisely how the coater bug got in
the first time.

### D4 — `game.addon_facing` IS the rule, and it lives in `validate.py`

`validate._addon_facing` (`validate.py:1906-2029`) is the only place the
`AddonPass` direction rule exists. The threshold `0.95` appears only inside its
docstring (`validate.py:1921`); the code reduces it to `off in (0, 180)`
(`validate.py:2017-2019`) on the grounds that our yaws are quarter turns.

Consequences:

* There is no `rules.ADDON_FACING_DOT`, so a strategy that wanted to *satisfy*
  the rule cannot consult it. `spine._feed_coater` derives the flow yaw
  independently; `freeform._place_coaters` writes `Facing.EAST` for every coater
  (`freeform.py:6476`) and the validator's own docstring records that 10 of 20
  coaters on a reported blueprint disagreed with the flow, 6 of them convicted.
* The quarter-turn reduction is an assumption about our own output baked into a
  ported game predicate. It is true today and invisible if it stops being true.

### D5 — One constant, two different rules: `SKEW_AXIS_DEG`

`rules.py:398-405` says explicitly:

> This is ONE rule with two consumers. `layout.validate` checks against it and
> `layout.slots` picks slots so as to satisfy it.

It is **not** one rule. The two consumers test different vector pairs:

* `validate._inserter_skew` (`validate.py:1837-1848`): the angle between the
  **sorter's own yaw** and the **sorter's axis**. The same docstring
  (`validate.py:1770-1776`) admits this "cannot fire": the yaw is derived from
  the axis, so the angle is identically zero. Vacuous on our output.
* `slots.attachment` (`slots.py:359-363`): the angle between the **slot pose's
  forward** and the **run direction**, as a 2-D dot of a 3-D unit vector against
  a normalised 2-D run.

The game's actual test on that second pair is `CheckInserterDataLegal`'s sign
test — `dot(slot_fwd, direction) < 0` — which `validate._inserter_data`
(`validate.py:1573-1587`) ports faithfully at threshold **0**, in 3-D.

**Separating input:** a slot whose forward is perpendicular to the run. The game
gives `dot = 0`, which is not `< 0`, so it **accepts**. `slots.attachment`
computes `0 < 0.9135` and **refuses**. That is an avoidable refusal.

**Status: LATENT, measured.** I checked all 196 slot poses in the catalog: the
smallest planar magnitude of any slot forward is 0.9996 (Vertical Launching
Silo), so none is tilted enough for the 2-D-vs-3-D difference to bite, and no
axis-aligned run produces a perpendicular slot that a layout would want. The
predicates differ; today's data does not separate them.

The real problem is naming: a constant documented as "the game's `TooSkew`" is
being used as a hand-chosen tolerance on a different quantity. If someone
"corrects" `SKEW_AXIS_DEG` to match the game more closely, `slots.attachment`
changes behaviour for no reason connected to that correction.

### D6 — Three hand-rolled copies of `CONN_SLOTS_PER_OBJECT`

`rules.CONN_SLOTS_PER_OBJECT = 16` (`rules.py:210-264`) carries the C# showing
that `WriteObjectConn` *evicts* rather than refuses, so a double-booked slot
pastes silently broken.

Three implementations of "do not double-book":

* `validate._slot_occupancy` (`validate.py:1595-1668`) — checks it.
* `freeform` `claimed: dict[int, set[int]]` (`freeform.py:2373`, 2487-2493).
* `spine` `claimed: dict[int, set[int]]` (`spine.py:3590-3600`).

The two strategies' versions are the same idea written twice, both keyed on
machine index -> slot indices, both covering the **machine side only**. Neither
shares code with the other or with the validator. They agree today; there is
nothing holding them together.

### D7 — `catalog.clearance` has a silent geometry fallback

`catalog.py:992-997`:

```python
try:
    ex, ez = colliders.own_centre_extent(building(item_id).model_index, yaw)
except Exception:
    return (fw, fh)
if not (ex or ez):
    return (fw, fh)
```

A building whose collider cannot be read falls back to its **footprint**, which
is exactly the under-reservation that produced 443 `geom.collide` pairs. The
docstring defends it as "the previous behaviour, unchanged" — but the project's
standing rule is that a fallback names a bug and hides it. The packer will
happily pack such a building at footprint pitch and `geom.collide` will then
refuse the layout, so the cost is an unexplained refusal rather than a shipped
defect. It should raise, or the catalog should carry an explicit
"no collider data" set the way `LOW_CONFIDENCE_FOOTPRINTS` does.

---

## 2b. Honest negatives — suspected and measured false

### N1 — `TESLA_COVER_RADIUS` is in TILES, and the corpus proves it

The suspicion was the `SLOT_REACH` failure mode again: `PowerDesc.coverRadius` is
a game field, every other game literal compared against a `Vector3` is in world
units, and `validate._coverage` (`validate.py:2686-2700`) compares it against
**tile** distances. 10.5 world units is only 8.356 tiles, so a world reading
would make our coverage check 26% too generous — it would certify buildings that
paste unpowered. The docstring's own bracket ("94 machines farther than 5.25,
zero beyond 10.5", `catalog.py:371-377`) settles the diameter question and
**cannot** settle this one: if the true bound were 8.356 tiles, "zero beyond
10.5" would still hold.

Measured on the fixture corpus (throwaway script, not committed), counting powered consumers
in the disputed band `(8.356, 10.5]` tiles from their nearest tower:

```
fixture                                            towers  consumers  in band  beyond 10.5
factory-quick-start-step-1-minimum-blue-cube            2         18        0            0
factory-quick-start-step-3-red-cube                     6         87        3            0
12-s-purple-science-from-smelted-refined-products      54        984        0            0
factory-endgame-distribution-hub                       82        253        2            0
```

Five buildings — a Storage Tank, two Splitters, a Depot Mk.I and a Logistics
Distributor — sit inside the tile reading and outside the world reading, in
blueprints the game itself wrote and that work. **Nothing anywhere exceeds the
tile reading.** Bracketed on both sides: the tile reading is right and the check
is correct as written. No change needed.

### N2 — Freeform's coater ban agrees exactly with the game's lateral rule

Freeform builds `belt_ban` with `colliders.belt_crossings(..., directly_over_only=True)`
(`freeform.py:6532-6534`), which is the *narrowed* form; `colliders.py:748-752`
says the narrowing "is not the shipped rule any more". So the search looked like
it might be blind to belts that graze a coater from the side.

Measured (throwaway script, not committed), Spray Coater model 120, comparing the cells
freeform bans against `colliders.belt_keepout_offsets` (the full lateral form):

```
yaw=0    freeform bans (levels>=1): [(0,-1,1), (0,0,1)]
         game keeps out (levels>=1): [(0,-1,1), (0,0,1)]     missed: []  extra: []
yaw=90   freeform bans (levels>=1): [(-1,0,1), (0,0,1)]
         game keeps out (levels>=1): [(-1,0,1), (0,0,1)]     missed: []  extra: []
```

Identical at every level at or above 1. The lateral half only adds cells at
level 0, which is the "beside it, not over it" case both the validator
(`validate.py:2166`) and the game's own blueprints allow. No disagreement.

### N3 — No layout module hardcodes a game constant

AST walk over every float literal in the *code* of all eight `layout/*.py`
modules (throwaway AST scripts, not committed). Every value resolves to a
heuristic weight, a time budget, a height-sweep factor or a yaw:

```
freeform  {0.0, 0.05, 0.1, 0.25, 0.35, 0.5, 0.6, 0.8, 1.0, 1.25, 1.6, 3.0, 40.0, 60.0}
spine     {0.0, 1e-09, 0.25, 0.3, 0.5, 0.6, 0.7, 1.0, 2.0..8.0, 60.0}
slots     {0.0, 0.5, 90.0, 360.0}
junction  {0.0, 2.0}
validate  {0.0, 0.5, 1.0}
```

The `0.8` in `freeform.py:7537` is a height-sweep multiplier, not `SLOT_REACH`;
the `1.25` beside it is another sweep factor, not the coater's addon offset.
`1.8975` and `1.2566` appear only in comments. This lint starts green.

### N4 — `PlacedBuilding.width`/`height` is no longer an unverified cache

The concern was real when it was raised. `geom.footprint` (`validate.py:781-861`)
now compares the declared size against `catalog.oriented_footprint` for every
tile-occupying building and against `(1, 1)` for every belt addon, with the
measurement behind the addon branch stated in the docstring. Its own honest
negative — "this check convicts NOTHING in either strategy today" — is the right
outcome for a guard on a cache. Closed.

---

## 3. The search / validation split

The user's standing requirement: every rule the search obeys must also be
enforced by the validator, and every rule the validator enforces must be visible
to the search.

### 3.1 Enforced by the SEARCH but not by the VALIDATOR

**None found that are game rules.** Everything the search refuses that the
validator does not is a heuristic:

| Search constraint | Where | Is it a game rule? |
|---|---|---|
| Machines are `solid` at every altitude — no belt may ever cross a machine | `freeform._Canvas.add(solid=True)` (`freeform.py:2082-2086`), `_make_grid` (`freeform.py:3060-3063`) | **NO.** The game prices a machine crossing by height (`colliders.belt_crossing_height` gives 2.80–4.97), and spine implements exactly that pricing in `_belt_floor_over`. Freeform forbids what spine sells. See section 5. |
| `slots.attachment` requires cos(24°) alignment | `slots.py:362` | NO — stricter than the game's sign test (D5) |
| `slots.attachment` requires the run to be axis-aligned and `far` off the footprint | `slots.py:335-340` | NO — ours, and stated as ours |
| `freeform.LEVELS = 3` altitude budget | `freeform.py:160` | NO — explicitly not the ceiling |
| `spine._MAX_SPUR_Z` clamps to a NEW save's ceiling | `spine.py:3742` | Conservative direction; the validator uses the URL's real ceiling |

That is a clean result: the search never sneaks a legality decision past the
validator by knowing something the validator does not.

### 3.2 Enforced by the VALIDATOR but invisible to the SEARCH

These cause avoidable refusals — the search walks into a wall it cannot see.

| Validator check | Search-side counterpart | Consequence |
|---|---|---|
| `game.inserter_paste` (the `ErrorInserterData` snap ladder, `rules.PASTE_*`) | **None.** `slots.attachment` applies `SLOT_REACH` (0.8) but not the paste ladder's `PASTE_RADIAL` (1.6) / `PASTE_LATERAL_EPS` (0.1) branches | Currently harmless — `SLOT_REACH` is the tighter of the two on every input we produce — but the search is satisfying a *different* predicate from the one that will judge it |
| `game.inserter_skew` length window (`rules.SORTER_LENGTH`) | Deliberately absent (`slots.py:315-318`) with an argument that spans 1–3 tiles cannot bind | Fine, and correctly documented |
| `game.belt_collide` LATERAL half against **machines** | Freeform: covered accidentally, because machines are `solid`. Spine: covered by `_SpurField.taken` for the footprint, but the lateral probe reaches beyond the footprint for a building whose collider is wider than its tiles | `validate.py:2210-2222` records exactly this as "a ROUTER bug, not a rule bug", 15 spine tests red at the time. `junction.keepout_cells` closed the splitter case; nothing generalises it to other wide-collider buildings |
| `geom.altitude_range` `BELT_Z_QUANTUM` branch | Freeform emits halves by construction; spine likewise | Invented constraint, no cost |
| `power.coverage` / `power.connectivity` | Both strategies plan towers against the rule, and freeform (`_power_plan`, `freeform.py:5367-5369`) uses byte-identical arithmetic to the validator | **This is the best-consolidated rule in the codebase and is the pattern to copy.** The only blemish is spine reading the hand-typed `TESLA_*` copy instead of the extracted value |

### 3.3 The `OPT_IN` docstrings are stale

`OPT_IN` is `set()` (`validate.py:744`), but `_belt_collide`'s docstring still
opens "WHY THIS IS IN `OPT_IN` AND `game.belt_crossing` IS NOT"
(`validate.py:2207`) and describes turning it on as a future event that turns 15
spine tests red. `_belt_crossing` also refers to "that check is in `OPT_IN`"
(`validate.py:2066`). Documentation drift, not a behaviour bug — but this is a
codebase where the docstrings *are* the rule provenance, so a stale one is a
correctness hazard.

---

## 4. Rules known from the decompiled source and NOT ported

Everything here is quoted in this repository's own comments and enforced by
nothing.

1. **`TooBendToLift`** — `catalog.py:187-196`. See D1. **Highest.**
2. **The addon corner rule (decompiled 145812)** — `BACKLOG.md:100-105`: the
   `AddonPass` excusal requires the ridden belt's own *input* and *output* belts
   to lie within 0.3 of the addon's line, so a coater on a corner is refused.
   `game.addon_facing` tests one direction only (`validate.py:1999-2010`). Our
   coaters sit on straight runs, so this is silence rather than a pass.
3. **`Maths.DistancePointLine(...) < 0.3f`**, the companion to
   `ADDON_AREA_RADIUS` — `rules.py:428-431` records it as unported by name. It
   is what would decide whether a belt *two* tiles behind a coater counts as
   supplying it: `world_gap` for that offset is 0.94 against a radius of 1.0
   (`BACKLOG.md:96-99`).
4. **`BELT_SLOT_AUTO_RANGE`'s second consequence** — `rules.py:274-282`: a belt
   tile accepts at most `12 - 4 = 8` auto-slot connections, past which the
   connection is silently dropped. The docstring says "no check asserts it".
   The corpus worst is 6, so it has never been near.
5. **The silo branch of the paste ladder** (`isSilo`, 2.5/2.4) — deliberately
   not ported, with a stated reason (`rules.py`, paste section). Correct
   decision; listed for completeness.
6. **`CalcSegmentsAcross`** and the combined `sqrt(segments^2 + altitude^2)`
   minimum — deliberately not ported because they need the planet's grid.
   Correct decision; listed for completeness.
7. **The capsule form of the belt re-probe** (`OverlapCapsule` on corners) —
   `colliders.py:968-983` states the simplification and argues it is
   conservative. Correct; listed for completeness.

Items 5–7 are principled omissions with arguments. Items 1–4 are holes.

---

## 5. Invented constraints that are not game rules

| Constraint | Where | Cost |
|---|---|---|
| **A belt may never cross a machine** | `freeform` marks every machine `solid` at every level (`freeform.py:2082-2086`, `3060-3063`) | The game allows it at a price in height, and **spine already implements that price** (`_belt_floor_over`, `spine.py:3747-3788`). Freeform therefore refuses a class of route spine takes. `freeform.py:148-152` justifies `LEVELS = 3` *by* this restriction — "it treats machines as solid at every altitude, so headroom beyond a crossing plus one buys it nothing" — so the invented constraint is also capping the router's altitude budget. This is the single largest density item in the audit. |
| Belt `z` must be a multiple of `1/2` | `validate._altitude_range` (`validate.py:1037-1045`) | The game quantises nothing. Zero cost today. |
| `slots.attachment`'s cos(24°) slot alignment | `slots.py:362` | Zero cost today (D5), but stricter than the game. |
| `catalog.BELT_CROSSING_CLEARANCE = 1` used as a belt-over-belt separation | `spine._TRUNK_Z` | Correct number, wrong provenance (D3). |

---

## 6. The performance objection, head on

This is the real cause of every bug in this audit, so the plan has to answer it
rather than route around it.

The asymmetry: `_astar` expands ~1.25M nodes on a `quantum-chip` routing pass
(`freeform.py:3395-3405`) and asks "is this cell free" once per expansion per
direction. `certify()` asks "is this layout legal" once. `_make_grid` exists
because a Python-level `_Canvas.free` call per expansion is unaffordable — and
hand-building the flat array beside `free` is exactly how it drifted.

**The mechanism I would pick: COMPILE, don't call.**

The authoritative rule stays a pure predicate in `dsp/`. The hot path never
calls it per-query; it calls it once per *object* at setup and materialises the
answer into whatever fast structure it wants. Two properties make this safe:

1. The compiled form is produced by a function that lives **next to the rule**,
   not next to the search. `colliders.belt_keepout_offsets` (`colliders.py:674`)
   is already this: a `@cache`d, `frozenset` of `(dx, dy, dz)` offsets,
   *measured* by placing the real probe against the real boxes. `junction.py:58`
   consumes it and adds nothing. `catalog.clearance` (`catalog.py:962`) is the
   same pattern for the box rule.
2. The search's own structures are built **only** from compiled sets, never
   from an independently-derived formula. `_make_grid` should be a pure
   projection of `_Canvas`'s fields — and `_Canvas`'s fields should be pure
   projections of compiled rule sets.

This is not a new pattern for this codebase. It is the pattern that already
works twice. The failures are the places that did *not* use it.

**Per hot path:**

| Hot path | Rule involved | Mechanism |
|---|---|---|
| `_make_grid` / `_Canvas.free` (`freeform.py:3035-3113`, `2106-2121`) | collide, belt crossing, belt lateral, single occupancy | Keep the flat array. Make **every** contributing set a compiled keep-out from `dsp/`, keyed on blueprint `z`. Add an assert-mode that, after building the grid, re-derives it from `_Canvas.free` cell by cell and diffs — this is the direct regression test for the `_make_grid` class of bug, and it is O(cells), affordable once per test run |
| `_astar` step legality (`_RAMPS`, `_legal_link`, `_altitude_profile`) | `TooSteep`, `TooBendToLift` | The legal move set is small and enumerable. Build it once at import from `catalog.MAX_BELT_SLOPE` / `BELT_Z_PER_WORLD_UNIT` / the bend rule, as a table of `(dlevel, dtiles, turns_allowed)`. `_RAMPS` becomes that table's projection instead of a hand-written `(1, -1)` |
| CP-SAT pack model (`freeform.py:1833`, spine `_charged_pitch`) | collide | Already compiled: `catalog.clearance`. Keep. Remove the two hand-written `(a + b) / 2.0` copies (`spine.py:4406`, `junction.py:143`) into one `catalog.min_centre_separation(a_id, a_yaw, b_id, b_yaw)` |
| `slots.attachment` inside the seating loop | slot reach, slot facing | Already consults `rules.*` directly and is not hot enough to matter (it runs per candidate column, not per A* node). Fix the *predicate*, not the performance |
| `spine._SpurField` (`spine.py:3791-3860`) | belt crossing | Already the right pattern — precomputed per tile from `_belt_floor_over`. Change `_belt_floor_over` to be a thin call into `dsp/`, which it nearly is |

**Why not the alternatives.** "Call the shared predicate in the loop" is the
thing that is already known not to fit. "Debug-mode cross-check only" leaves the
fast path as an independent implementation that happens to be tested — better
than nothing, and it is step 0 below, but it does not remove the second
implementation. Compile-then-project removes it.

---

## 7. Recommended order of work

Cheapest and highest value first. **BP** = behaviour-preserving refactor,
**CHANGE** = will move layouts and needs paired, interleaved area measurement
against a genuinely separate pristine checkout.

### Step 0 — Settle `TooBendToLift` in game. [not code]
Paste one blueprint containing a 90-degree turn on the tile immediately after a
ramp. Cost: minutes. Value: decides whether we are shipping invalid blueprints
today. **Nothing else in this list matters as much and nothing else is this
cheap.** Everything in step 1 depends on the answer.

### Step 1 — Act on the answer. [CHANGE if it binds]
* If it binds: add `game.belt_bend` to `validate.py` reading
  `catalog.BEND_MIN_ANGLE_WHEN_SLOPED_RAD` / `SLOPE_DEADZONE`, and add
  "no turn on a cell adjacent to a level change" to the router's legal-move
  table. Expect refusals before it costs area; measure both.
* If it does not bind: **delete both constants** and delete `geom.altitude_step`
  too, or document why one `BuildTool_Path` rule binds on paste and the other
  does not. A constant nobody reads is a trap for the next reader.

### Step 2 — Re-key keep-outs on blueprint `z`. [BP, then verify]
`freeform._Canvas.belt_ban: dict[(x,y), set[Fraction]]` and
`junction.keepout_cells` returning `Fraction` altitudes; `_Canvas.add` registers
the ramp tile's real `z`. Closes D2 at the root. Behaviour-preserving on
today's corpus (measured: 0 half-level belts in a coater footprint), so this is
a refactor with a latent-bug fix riding along.

### Step 3 — One owner for "how high must a belt be over X". [BP]
```python
# dsp/rules.py  (or a new dsp/beltrules.py)
def belt_floor_over(model_index: int, base_z: Fraction) -> Fraction | None:
    """Lowest legal blueprint z for a belt tile crossing this building,
    quantised up to catalog.BELT_Z_QUANTUM.  None when the game excuses it."""
```
Callers become: `spine._belt_floor_over` -> delete, call this;
`freeform._place_coaters` -> call this instead of open-coding
`belt_crossing_height` + `floor` + a level loop;
`validate._addon_crossings` and `_belt_collide_findings` -> call this for the
`need` they report. Four call sites, one body.

### Step 4 — Retire `catalog.BELT_CROSSING_CLEARANCE`. [BP]
It is used at exactly one place that matters, `spine._TRUNK_Z`. Rename it to
what it is — `BELT_OVER_BELT_SEPARATION`, ours, corpus-derived — or replace
`_TRUNK_Z` with a derivation from the splitter's own collider and delete it.
Either way, stop a per-model rule and a blanket constant sharing a name.

### Step 5 — One owner for pairwise centre separation. [BP]
`catalog.min_centre_separation(a, a_yaw, b, b_yaw) -> Fraction`, replacing the
two `(mine + max(clearance(...)))/2.0` copies at `spine.py:4406` and
`junction.py:143`.

### Step 5b — Delete `TESLA_COVER_RADIUS` / `TESLA_LINK_DISTANCE`. [BP, trivial]
They are hand-typed copies of `catalog.building(2201).cover_radius` /
`.connect_distance`, which come from extracted game data. `validate` and
`freeform` already read the extracted values; only `spine.CONSTANTS`
(`spine.py:133-134`) reads the copies. Point it at the catalog and delete both
constants. Five minutes, and it removes a whole row from the duplicate table.

### Step 6 — Split `SKEW_AXIS_DEG`. [BP]
Give `slots.attachment` its own named constant with its own honest provenance
("ours; the game's test here is the sign test, this is tighter and here is why"),
or change it to the game's sign test and measure. Stop one constant carrying two
rules.

### Step 7 — Move the addon-facing rule into `dsp/`. [BP]
`rules.ADDON_FACING_DOT = 0.95` plus
`rules.addon_faces_belt(addon_yaw, flow_deg) -> bool`, with the quarter-turn
reduction as an implementation detail *inside* it and an assertion that both
inputs are quarter turns. `validate._addon_facing` and both strategies' coater
seating then consult one function. Closes D4 and makes the fix for the corner
rule (item 4 below) a one-line addition.

### Step 8 — Port the addon corner rule and the `DistancePointLine` clause.
[CHANGE — expect refusals]
Both are in `AddonPass`. Doing them together is cheaper than separately. Expect
this to convict coaters we currently place; that is the point.

### Step 9 — Delete freeform's "machines are solid at every level". [CHANGE, big]
Replace with `belt_floor_over` pricing, as spine already does, and raise
`LEVELS` to whatever the pricing needs. This is the only item here with a
plausible large density win and it is the riskiest: `LEVELS` was tuned by
measurement (`freeform.py:154-159`) and raising it costs A* time. Do it last,
paired and interleaved, and be prepared for it to measure negative.

### Step 10 — Remove the `catalog.clearance` fallback. [CHANGE — expect refusals]
Raise instead of returning the footprint. D7.

---

## 8. How "100%" is measured, and how it stays measured

Four mechanisms, in increasing cost. I would build 1, 2 and 3; 4 is the one that
actually keeps it honest.

**1. A lint: no game constant outside `dsp/`.**
A test that walks the AST of every module under `layout/`, `bench/`, `rates/`
and collects float/`Fraction` constants, and fails on any value that also
appears as a rule constant in `dsp/rules.py` or the rule section of
`dsp/catalog.py`. Cheap, and it is exactly the check that would have caught
`_SKEW_AXIS_DEG` and `SLOT_ALIGN_DEG` holding `24.0` in two files. I ran this by hand for this
audit: **layout code is clean today**, so the
lint starts green.

**2. A declared rule registry.**
Extend the `@check` decorator: `@check("game.belt_crossing", rule="colliders.belt_crossing_height")`.
A test asserts (a) every declared symbol resolves inside `flab2bp.dsp`, (b) the
check's own body references it, and (c) every rule constant exported from
`dsp/rules.py` is named by at least one check. (c) is the one that finds unported
rules: `BEND_MIN_ANGLE_WHEN_SLOPED_RAD` would have failed it from the day it was
written. This is the mechanism that makes "100%" a number you can print.

**3. Assert-mode grid cross-check.**
An env flag under which `_make_grid` re-derives its array from `_Canvas.free`
and diffs, and under which `certify()` runs on every intermediate placement, not
just the final one. Turn it on in the test suite and in `scripts/audit.py`.
This is the direct, permanent guard for the `_make_grid` class of bug.

**4. Constant-mutation coverage. The one that actually proves consultation.**
For each rule constant in `dsp/`, perturb it and assert that **both** a
validator test **and** a strategy test go red. A strategy that holds its own
copy will not notice the perturbation, and that is precisely what "the search
re-implements the rule" looks like from the outside. Concretely: bump
`rules.SLOT_REACH` to 0.4 and `slots.attachment` must start refusing; bump
`colliders.BELT_PROBE_RADIUS` and freeform's `belt_ban` must widen. Today,
bumping `catalog.BEND_MIN_ANGLE_WHEN_SLOPED_RAD` changes **nothing anywhere** —
which is the finding of this audit, expressed as a test.

Mutation coverage is the only one of the four that cannot be satisfied by a
module that merely *imports* the constant and then ignores it.

---

## 9. Where the line is: legality vs quality

Stated explicitly because a consolidation that gets this wrong is worse than the
status quo.

**Belongs in `dsp/`, no exceptions:** anything whose falsification is "the game
draws it red". Every `game.*` check, `geom.collide`, `geom.belt_single_occupancy`,
`geom.altitude_step`, `geom.altitude_range`'s ceiling half, `sorter.*` reach and
slot rules, `junction.ports`, `power.coverage`, `power.connectivity`.

**Must NOT migrate:** density, pitch, search order, altitude budgets, time
budgets, congestion weights, rip-up policy, candidate counts, fallback codes.
`freeform.LEVELS = 3` and `spine.UNIFORM_ROW_PITCH` are the canonical examples:
both were set by measurement, both look like rules, neither is one.

**Genuinely both, and how they split:**

* `catalog.BELT_Z_QUANTUM` — the *ceiling* (`belt_max_z`) is legality; the
  *quantum* is our emission habit. Split: keep `belt_max_z` in the rule module,
  move the quantum next to the emitters and stop `geom.altitude_range` checking
  it as a game rule.
* `catalog.SORTER_MAX_REACH` — the *length window* (`rules.SORTER_LENGTH`) is
  legality; `= 3` is a corpus measurement of what real builders do. Already
  correctly labelled at `rules.py:52-53`; leave it.
* `catalog.clearance` — the *rule* is `colliders.collisions`; `clearance` is a
  conservative tile-grid *projection* of it chosen so a packer can be linear.
  This is the model for everything in section 6: it lives in `dsp/`, it is
  derived from the rule, and its docstring proves the direction of the
  approximation. Keep it exactly as it is and copy the pattern.
* `freeform`'s "machines are solid" — currently a *quality* decision
  (simplicity, altitude budget) wearing a legality shape. Split it: price the
  crossing with the rule, and let `LEVELS` be the quality knob it was always
  meant to be.
