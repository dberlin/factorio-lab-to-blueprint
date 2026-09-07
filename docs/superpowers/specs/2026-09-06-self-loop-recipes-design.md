# Self-loop recipes, mixed input lanes, and coater merges — design

**Date:** 2026-09-06
**Branch:** `design-selfloop` (off master `23f6d098`)
**Evidence:** `docs/superpowers/evidence/2026-09-06-selfloop/README.md`
**Trigger:** a user URL whose blueprint "tries to reuse the hydrogen it
produces from energetic graphite as input again to itself", "tried to take 3
inputs to the mining machine producers from the same belt", and "tries to
insert them into the spray coater as if it was a splitter".

Three findings, ordered by severity. **F1 and F2 are correctness defects the
game will not run**; F3 is the reported self-loop, which is correct in steady
state and dead on paste. F1/F2 come first in the plan for that reason, but F3
is the larger design.

---

## 1. Current behaviour, with file:line

### 1.1 Rates and spec — already correct for a self-loop

`src/flab2bp/rates/solve.py:1306-1318` computes
`external_inputs[item] = consumed - produced` over the **whole block**, so a
self-loop item whose block-wide production covers its consumption never becomes
an external input. `solve.py:1325-1329` puts the difference in `surplus`.
For the reported URL's winning candidate (`output-products`, sequence-pair):

```
x-ray-cracking x4 (oil-refinery, mode=none)
  hydrogen in  149/90  = 1.6556/s      hydrogen out 149/60 = 2.4833/s
  external_inputs: no hydrogen
  surplus_outputs: {'hydrogen': '149/180'}   # 0.8278/s = 2.4833 - 1.6556
  coproduct_buffer_proofs: ()
```

The closed-form solve is covered by
`tests/rates/test_solve.py:672 test_self_consuming_recipe_solves_in_closed_form`.
`tests/rates/test_solve.py:596` records that **no corpus URL at any tier
activates a self-consuming recipe**; this URL is the first.

### 1.2 Strip plan and emission — the loop is already built

`src/flab2bp/layout/strip_variants.py:1252-1356` (`_logical_strip_plans`) emits,
for a group that both produces and consumes an item, an out-lane sink to its own
group key **and** a boundary sink (`strip_variants.py:1314-1356`); this is the
2026-08-28 self-consuming-flow-feedback work
(`docs/superpowers/plans/2026-08-28-self-consuming-flow-feedback.md`).
`freeform._nets_between` (`src/flab2bp/layout/freeform.py:3895-3906`) drops the
self edge from the CP-SAT distance proxy only.

Decoded from the emitted blueprint, hydrogen is **one 107-tile belt run**
(`run 25`) that collects from all four refineries at `y=21`, climbs to `z=3`,
returns west, drops to `y=14`, feeds all four refinery input sorters in series,
and exits the block at `(26,0)` carrying exactly `surplus_outputs['hydrogen']`.

**A serial belt already is the "priority splitter" the user asked for**:
consumers tap first, the remainder leaves. No splitter, no extra buildings.

### 1.3 Emission and validation — the gaps

* Run 25's head at `(3,21)` is fed by nothing and carries no icon.
  `markers.mark_external_belts` (`src/flab2bp/layout/markers.py:96-140`) marks
  only heads whose `carries_item ∈ spec.external_inputs`;
  `markers.unmarked_external_inputs` (`markers.py:146-158`) likewise.
* `flow.conservation` (`src/flab2bp/layout/validate.py:5112-5158`) checks
  steady-state arithmetic and directed max-flow feasibility. Hydrogen nets to
  zero and the produced hydrogen does reach the taps. **No clause has any
  notion of an initial fill.**
* `flow.coproduct_buffer` (`validate.py:4632-4636`) iterates
  `spec.coproduct_buffer_proofs`, which is empty. It is a certificate
  *verifier*: it can convict a wrong proof, never the absence of one.
* `flow.external_entry_points` / `flow.external_entry_reachable`
  (`validate.py:4499`, `validate.py:4439`) both go through
  `_entry_runs` (`validate.py:4345-4367`), which filters on
  `set(spec.external_inputs)`. Run 25 is invisible to both.
* `belt.acyclic` (`validate.py:3510-3562`) is an **ERROR** on any belt cycle, so
  physically closing the loop into a ring is forbidden by our own validator,
  even though DSP permits belt loops.
* `cli.py:39-50` and `web/payload.py:124,212` print `spec.external_inputs`.
  Hydrogen appears on neither surface.

### 1.4 Mixed input lanes

`freeform._seat_inputs` (`src/flab2bp/layout/freeform.py:2170-2292`) seats
ingredients into lane rows; `in_above` / `in_below` are tuples of lanes and a
**lane is a tuple of items**, so a lane holding two items IS a mixed belt. Its
ladder:

```python
# freeform.py:2243-2245
mix_sizes = (
    range(max(1, max_per_lane), 0, -1) if prefer_shared else range(1, max(1, max_per_lane) + 1)
)
```

Two mechanisms produce a mixed lane and they are different in kind:

* **M1, forced.** Without `prefer_shared`, one-item-per-lane is tried first and
  mixing happens only when the row caps (`freeform._side_lane_caps`) or the
  face's insert-pose columns cannot hold it. `freeform.py:2208-2223` documents
  the load-bearing case: **`universe-matrix` seats six ingredients into a
  Matrix Lab offering three columns per face only as "three ingredients mixed
  onto one lane above, three onto one below, and the product out east"**.
  Banning M1 turns that spec into a refusal.
* **M2, chosen.** `strip_variants.py:1358-1360`
  `prefer_shared_inputs = prefer_shared_proliferation and group.proliferated and len(input_items) >= 3`,
  threaded from `generate_strip_families` (`strip_variants.py:1985,1996`),
  reverses the ladder to mix as hard as possible and gates only on
  `input_lane_fits` (`strip_variants.py:1363-1374`), a pure rate sum. Its
  purpose is fewer Spray Coaters. **It fires even when one-item-per-lane fits.**

A third mechanism must **not** be confused with either: `freeform._merge_lanes`
(`freeform.py:1854-1959`) and `_merge_frontier` (`freeform.py:8934`) share one
OUTPUT lane between several consumers of the **same** item. That is one item per
lane throughout, and it is the sharing measured as load-bearing for feasibility
on 12 of 36 corpus cells. It stays.

`_seat_both_fed_outermost` (`strip_variants.py:1137-1249`) is orthogonal: it
seats a lane that is fed BOTH from the boundary and from an internal producer
(`both_fed = frozenset(spec.external_inputs) & frozenset(producers)`,
`strip_variants.py:1295`) on a true outer row so it has two belt approaches.

### 1.5 Spray Coaters

A coater carries **no** connection (`catalog.py:1305-1319`,
`validate.py:2196-2200`); the game resolves it by position from
`addon_areas`: area 0 at `(0,0,0)` is the cargo belt it rides, area 1 at
`(0,-1.25,1)` is the proliferator supply, both searched within
`rules.ADDON_AREA_RADIUS = 1.0`. Its footprint is `(1,3)`, so at yaw 90 the body
covers three tiles along x.

In the emitted blueprint, **a 2-into-1 belt merge sits on a tile each coater's
body covers**: `belt#0 (53,20,0)` with `pred=[817, 1872]` under coater#768, and
`belt#19 (53,26,0)` with `pred=[830, 2037]` under coater#771. Nothing convicts
it: `game.addon_supply` (`validate.py:2188-2247`) only asks whether *a* belt is
in each area; `_coater_rides` (`validate.py:4898-4917`) maps area 0 to one belt
and says nothing about its predecessors; `validate.py:3520-3522` states plainly
that "two chains pointing at one tile is how many-to-one is built", so
`belt.acyclic` accepts it.

Separately, coater#768's area 1 has **two** belts at 0.250 inside the 1.0
radius on opposite sides — the proliferator run 59 tail at `(53,20,1)` and a
cargo lane (run 27) at `(55,20,1)`. Only the yaw convention separates them.

---

## 2. Every recipe in the vendored dataset with an item on both sides

`src/flab2bp/lab/vendored/data.json`, 493 recipes, **exactly two**:

| recipe | machine | in | out | self item | net/craft | covered by |
|---|---|---|---|---|---|---|
| `x-ray-cracking` | `oil-refinery` | hydrogen 2, refined-oil 1 | energetic-graphite 1, hydrogen 3 | hydrogen | +1 | this design |
| `reforming-refine` | `oil-refinery` | coal 1, hydrogen 1, refined-oil 2 | refined-oil 3 | refined-oil | +1 | this design |

Both are net-POSITIVE, both are `oil-refinery`, both are technology-locked.
No option below needs to distinguish them: they are the same shape.

Explicitly **not** self-loops: `deuterium-fractionation`
(`hydrogen 0.01 -> deuterium 0.01`; the Fractionator's hydrogen pass-through is
not modelled in the dataset), `graphene-advanced` + `deuterium` (a two-recipe
producer/consumer pair — the `CoproductBufferProof` case), and
`plasma-refining` + `reforming-refine` (DSP's only two-recipe cycle).

---

## 3. Options for the self-loop (F3)

### Option A — a specialised self-loop block producer with a priority splitter

Emit the strip with a Splitter whose priority output feeds the strip's own
input lane and whose overflow goes to the boundary; the external input lane
carries only the start-up deficit.

**Rejected.** The decode shows the priority behaviour is already achieved by
belt order at zero cost: consumers tap the loop lane in series, the remainder
runs on to the boundary. A splitter adds a building, a junction the flow
checks must model, and a real risk of tripping `belt.acyclic`
(`validate.py:3510`) if the loop is closed. It solves a problem we do not have,
and it does **not** solve the one we do (the loop still starts empty). It also
introduces a per-recipe special case, which rule "no new specialised solver
unless the general path cannot express it" forbids — and the general path
already expresses it.

### Option B — general knowledge in the rate/spec layer

Collapse `inputs_per_machine[item]` and `outputs_per_machine[item]` to the net
so the spec declares only the net flow and the layout never sees the loop.

**Rejected as stated, and half of it is already done.** The *block-wide*
netting is already exactly right (`solve.py:1306-1318`); what Option B proposes
extra is netting *per machine*, which would be actively wrong: it would tell
the strip planner that a refinery consumes no hydrogen, and the planner would
then not build the input lane the machine physically needs. The 2026-08-28
plan's standing rule says the same thing — "a self-consuming product remains an
internal routing net; never reclassify it".

What survives from Option B is the useful question it asks: *what must the
emitter still build, and what must the validator check?* Answer: the emitter
already builds the loop; what is missing is the **initial fill**.

**The game's start-up behaviour, established from the data and the record:**
DSP machines paste empty, and a DSP blueprint cannot carry inventory —
`BlueprintBuilding` (`src/flab2bp/dsp/records.py:66-119`) has no inventory
field (`content` is a text string, `parameters` a building parameter block).
An Oil Refinery running X-ray Cracking crafts only with `hydrogen: 2` **and**
`refined-oil: 1` present. With hydrogen produced nowhere else, the loop holds
zero items at t=0 and the block deadlocks permanently. **An external seed is
therefore mandatory, and it can only come from the player.**

### Option C — treat it as today, declared honestly

Mark the loop lane, say so in the blueprint description and the web UI, and
teach the validator about a self-loop item so it stops treating the lane as
either an unfed entry or a non-question.

### Chosen: **C, built on B's netting, with a seed that is derived exactly**

The rate/spec layer is already general and stays untouched in its arithmetic.
The layout is already correct and stays untouched. What is added is a
first-class, **derived** declaration of the self-loop and its priming
obligation, carried from rates through to the blueprint, the CLI, the web
payload, and a validator check that is the arbiter.

Reasons, against the four criteria in the brief:

* **Bounded area.** Zero new buildings. The seed is an instruction, not a belt.
  A permanent external hydrogen lane (the obvious alternative) would cost a
  boundary belt forever and would over-declare a rate the block does not
  consume in steady state.
* **Correctness under the game's start-up behaviour.** The only mechanism the
  game offers is a player injection, so the tool's job is to compute the exact
  amount, put the icon where it goes in, prove the tile is reachable, and
  refuse when it is not.
* **Validator arbiter.** A new check owns the property; nothing ships on a
  planner's promise.
* **No new specialised solver.** The rule is
  `item ∈ inputs_per_machine ∩ outputs_per_machine` for some group — it
  covers both dataset recipes and any future one without naming either.

**Placers and hierarchy.** A self-loop is by construction *inside one group*,
so it is inside one strip and inside one hierarchical block: `partition.py`
cuts between groups and can never separate a group from itself. Both freeform
and sequence-pair share `_logical_strip_plans`, so both already emit the loop
(the 2026-08-28 tests cover both: `tests/layout/test_freeform.py:1047`,
`tests/layout/test_sequence_solver.py:9150`). Nothing strategy-specific is
needed. The one hierarchy-visible consequence is that a self-loop item's
`surplus_outputs` share can cross a cut as an ordinary output lane, which is
already how surplus travels.

---

## 4. Decisions for F1 and F2

### F1 — no mixed-item input lanes (user ruling, binding)

> "the right answer is probably to not allow multiple items on the same belt
> like this, even if it generates a little more density."
>
> "a lane whose items must be interleaved exactly to avoid one item backing up
> and starving the others is not a build we should emit, whatever it saves."

The argument the spec makes explicitly, beyond run-time risk: **a mixed lane is
probably harder to place and route, not merely riskier.** One belt carrying k
items must reach every consumer of every one of those k items. That couples
strips that would otherwise be independent, lengthens the run, and constrains
the packing. So the honest measurement of the rule is not "the area it costs"
but the net of **area, refusals, and routing time** — and a cell that starts
building because its lanes stopped being coupled is a *win* for the rule, not
a cost.

**Decision (amended 2026-09-07 — see §9 R1).** The ban is **absolute**. Remove
M2 (chosen mixing) outright, and give M1 (forced mixing) **no exemption**:
`flow.lane_single_item` convicts every input lane carrying two or more distinct
items, whatever the machine's geometry. A seating the planner "had no
alternative to" is a seating we do not ship.

`universe-matrix` is not sacrificed to this: §9 R2 frees the row it was short
of by moving the flanked output's drain lane past sorter reach, so a Matrix Lab
seats its six ingredients as six single-item lanes. That is a planner change,
not an exemption — the check stays absolute and `universe-matrix` satisfies it
on the merits.

Preserve M3 (`_merge_lanes` / `_merge_frontier` sharing one lane between
consumers of the SAME item) untouched — it is one item per lane and is
load-bearing on 12 of 36 corpus cells.

**User note, 2026-09-06 20:20 UTC (binding on the executor):** the reported
blueprint *did* merge the three items onto one belt ahead of the coater, and
it still failed in game, because nothing controls the interleaving: whichever
item the machines are not short of fills the belt and the others starve. The
only mixed belt that can work is one whose items are filtered back apart by
splitters with port filters set, *and* whose interleaving is provably
starvation-free. Neither is attempted here and neither is worth attempting;
chosen mixing is given up outright, not made cleverer. This also bears on
open question 1: a Matrix Lab's forced three-items-per-lane has the same
uncontrolled interleaving, so "keep forced mixing" keeps that failure mode.
**The user has since ruled on exactly that point — §9 R1 makes the ban
absolute, and §9 R2 removes the reason forced mixing existed.**

### F2 — a Spray Coater rides exactly one belt run

A coater is a belt addon that rides one belt. Two runs merging on a tile its
body covers is the geometry the user read as "inserting them into the coater
as if it was a splitter", and even where it is a legal DSP merge it is exactly
the interleaving hazard F1 bans. **Decision:** the emitter must not seat a
coater over a merge, and the validator must convict one. Fold F4 (two belts
inside one addon area) into the same check family.

---

## 5. The change, by layer, with exact signatures

### 5.1 `src/flab2bp/spec.py`

```python
class SelfLoopSeed(_Frozen):
    """A recipe that consumes what it produces, and the one-off prime it needs.

    DSP machines paste empty and a blueprint carries no inventory, so a loop
    whose only source is itself holds zero items at t=0 and never starts.
    ``seed_items`` is the exact whole-item injection that starts every machine
    in the group at once; the loop is self-sustaining afterwards because
    ``net_per_craft`` is positive.
    """

    item_id: str
    recipe_id: str
    machine_item_id: str
    machines: int = Field(gt=0)
    consumed_per_craft: Fraction = Field(gt=0)
    produced_per_craft: Fraction = Field(gt=0)
    net_per_craft: Fraction = Field(gt=0)
    #: ``machines * consumed_per_craft``, rounded up to whole items.
    seed_items: int = Field(gt=0)


class BuildSpec(_Frozen):
    ...
    #: Items a group both consumes and produces.  A steady-state-correct block
    #: that must be primed once by hand before it will run at all.
    self_loop_seeds: tuple[SelfLoopSeed, ...] = ()
```

A `model_validator` asserts `net_per_craft == produced_per_craft -
consumed_per_craft` and `seed_items == ceil(machines * consumed_per_craft)`, so
a hand-built spec cannot lie.

### 5.2 `src/flab2bp/rates/candidates.py`

```python
def _self_loop_seeds(data: Dataset, solution: RateSolution) -> tuple[SelfLoopSeed, ...]:
    """Every group whose recipe consumes an item it also produces."""
```

Derived per group from `data.recipe(group.recipe_id).inputs` ∩ `.outputs`, with
`net_per_craft = outputs[item] - inputs[item]`. A group whose
`net_per_craft <= 0` is **not** a seed case: the shortfall arithmetic in
`solve.py:1306-1318` already makes it an external input, which is correct.
Wired into `_to_build_spec` beside `coproduct_buffer_proofs`
(`candidates.py:216`):

```python
self_loop_seeds=_self_loop_seeds(data, solution),
```

`hierarchy/partition.py` propagates it exactly as it propagates
`coproduct_buffer_proofs` (`partition.py:349-351,419`), filtered to the groups
the sub-spec keeps.

### 5.3 Strip planner and emission — no change to lane topology

The internal loop lane and the boundary surplus lane already exist. Two
additive changes:

```python
# src/flab2bp/layout/markers.py
def self_loop_prime_heads(placement: Placement, spec: BuildSpec) -> dict[str, int]:
    """Loop-lane head belt index per self-loop item, for the prime icon."""

def mark_external_belts(placement: Placement, spec: BuildSpec) -> Placement:
    ...  # additionally marks each self_loop_prime_head with catalog.belt_marker(item)
```

The head is the head of the run that both receives the item from a group's
output sorter and delivers it to that same group's input sorters. Marking it
costs nothing and is the tile the player drops the seed on.

`src/flab2bp/pipeline.py:1171-1175` gains one clause on the blueprint
description:

```python
description=(
    f"flab2bp {sname} layout, {spec.label} candidate, "
    f"{spec.machine_count} machines, {placement.area} tiles"
    + _prime_note(spec, labelled)   # "; PRIME ONCE: 8 hydrogen onto the marked belt at (3,21)"
),
```

```python
def _prime_note(spec: BuildSpec, placement: Placement) -> str: ...
```

### 5.3a Pass-through taps are Pile Sorters — RETRACTED 2026-09-07

The user hand-fed the hydrogen loop for longer and reports it self-regulates
once started: the ordinary sorters on the loop lane keep up, exactly as the
swing arithmetic with input buffers predicts. The earlier "grabs only a few"
observation was the start-up transient, i.e. the prime this design already
provides. No Pile Sorter rule, no new tap check, and no change to
`_pick_sorter`. The mixed-belt note under §4 F1 is unaffected.

### 5.4 Validation — three new checks

```python
# src/flab2bp/layout/validate.py

@check("flow.self_loop_primed", needs_spec=True, needs_groups=True)
def _self_loop_primed(ctx: Context) -> Iterable[Finding]:
    """A loop that feeds itself must be reachable, marked, and priced.

    ERROR when the loop run's tiles are all walled in (reuse
    ``_reachable_from_outside``) -- the player cannot prime what no belt and no
    hand can reach, so the block can never start.
    ERROR when the item's producing group is not also its consuming group's
    source -- i.e. the loop lane does not physically close.
    WARNING otherwise, naming item, ``seed_items`` and the marked tile, so the
    obligation is on the report and the CLI rather than only in prose.
    """


@check("flow.lane_single_item", needs_spec=True, needs_groups=True)
def _lane_single_item(ctx: Context) -> Iterable[Finding]:
    """One input belt carries one item.  No exemption (§9 R1).

    A belt run whose sorters draw two or more DISTINCT items into machines is an
    ERROR, full stop.  There is no forced-geometry exemption: a lane whose items
    must interleave exactly to avoid starving each other is not a build we emit,
    and "the machine's faces left no alternative" describes a seating we must
    not ship rather than one we must tolerate.  When a machine family really
    cannot be seated one-item-per-lane, the answer is a planner change (§9 R2
    moved the Matrix Lab's drain row to free a lane) or a refusal, never a
    convicted-but-permitted belt.

    Belt SHARING between several consumers of the SAME item is untouched: this
    counts DISTINCT items on a run, never taps.
    """


@check("prolif.coater_rides_one_run", needs_spec=True)
def _coater_rides_one_run(ctx: Context) -> Iterable[Finding]:
    """A Spray Coater rides one belt run, with no merge under its body.

    ERROR when any belt on the coater's covered tiles
    (``catalog.oriented_footprint(SPRAY_COATER_ID, yaw)`` about its origin) has
    two or more belt predecessors, or when belts of two different runs occupy
    those tiles at the coater's own altitude.
    ERROR when belts of two or more DISTINCT RUNS lie within
    ``rules.ADDON_AREA_RADIUS`` of addon area 1: which belt supplies the coater
    must not depend on a rotation convention.  (Narrowed from "a second belt"
    on 2026-09-07 — see §9 R6.  Our own ``_place_coaters`` always puts the
    coater's approach and supply belts inside that radius, and they are one run
    carrying one item, so the convention cannot change the answer that matters.)
    """
```

### 5.5 Planner fixes

* **F1** (amended 2026-09-07 for §9 R1). Delete the
  `prefer_shared_proliferation` parameter from
  `strip_variants._logical_strip_plans` (`strip_variants.py:1255`) and
  `generate_strip_families` (`strip_variants.py:1985,1996`), and the
  `prefer_shared` branch of the ladder in `freeform._seat_inputs`
  (`freeform.py:2179,2244`). Because the ban is absolute, the ladder does not
  merely stop *preferring* mixed lanes — it stops producing them: `mix_sizes`
  collapses to one item per lane, and a seating that cannot fit that way fails
  to seat, so the strategy REFUSES rather than emitting a lane
  `flow.lane_single_item` would convict. This is the same rule the coater-seat
  predicate follows in F2 — the emitter agrees with the validator instead of
  racing it. `max_per_lane` goes with the ladder it capped.

  *Amended again 2026-09-07 — see §9 R8.* This paragraph used to end: "`input_lane_fits`
  (`strip_variants.py:1363-1374`) stays as the unconditional rate test for the
  single-item lane it now always is." **That is struck.** `input_lane_fits` is
  deleted with the preference, because its premise was false twice over. It was
  never a production check — it reached `_seat_inputs` only through
  `prefer_shared_inputs`, which required `prefer_shared_proliferation`, a flag
  no production caller ever set. And it is not a valid test for a single-item
  lane: it summed `rate * group.count`, the WHOLE group across every strip,
  against one belt, while a lane serves ONE strip. Passing it unconditionally
  refuses 28 specs in `tests/layout/test_strip_variants.py` alone, 27 of them
  quoting `1 ingredients cannot be seated` — measured, evidence at
  `docs/superpowers/evidence/2026-09-06-selfloop/task5/strip-variants-with-unconditional-lane-fits.txt`.
  The single-item rate gate is `strip_variants._machine_cap`
  (`strip_variants.py:1998`), which caps a strip at `capacity // rate` machines
  and whose own docstring names the merged lane as the one case it could not
  cover — a case §9 R1 has now abolished.
* **F2.** `freeform._coater_seat` (`freeform.py:18039`) and `_coater_seats`
  (`freeform.py:18018`) gain a predicate rejecting a seat whose covered tiles
  contain a belt with more than one belt predecessor, and rejecting a seat
  whose area-1 position has a second belt within `ADDON_AREA_RADIUS`.
  `_place_coaters` (`freeform.py:18140`) already handles an unseatable coater
  by refusing rather than skipping silently
  (`prolif.sprayed_cargo_reaches_machines`, `validate.py:5011`, is the backstop).

### 5.6 CLI and web

`cli.py:39-50` gains, after `inputs to belt in:`:

```
prime once (self-loop): hydrogen 8 items onto the marked belt at (3,21)
```

`web/payload.py:124,212` gain `"self_loop_seeds"` beside `"external_inputs"`,
shaped `{item: {"seed_items": int, "recipe": str, "machines": int}}`.

---

## 6. Tests

| # | test | file | asserts |
|---|---|---|---|
| T1 | `test_only_two_vendored_recipes_consume_what_they_produce` | `tests/lab/test_data.py` | the enumeration is exactly `{x-ray-cracking: hydrogen, reforming-refine: refined-oil}`; a dataset bump that adds a third fails loudly |
| T2 | `test_self_loop_seed_is_derived_for_x_ray_cracking` | `tests/rates/test_candidates.py` | `spec.self_loop_seeds` for the AMM-URL spec has `item_id="hydrogen"`, `machines=4`, `consumed_per_craft=2`, `produced_per_craft=3`, `net_per_craft=1`, `seed_items=8` |
| T3 | `test_self_loop_seed_absent_when_net_is_not_positive` | `tests/rates/test_candidates.py` | a synthetic group with `in 3 / out 2` yields no seed and a positive external input instead |
| T4 | `test_self_loop_lane_head_is_marked_and_described` | `tests/layout/test_markers.py` | the loop head carries `catalog.belt_marker`, and the description contains `PRIME ONCE` |
| T5 | `test_self_loop_unprimeable_lane_is_an_error` | `tests/layout/test_validate.py` | a hand-built placement whose loop run is walled in yields `flow.self_loop_primed` ERROR; the reachable version yields WARNING only |
| T6 | `test_mixed_item_input_lane_is_convicted` | `tests/layout/test_validate.py` | a placement with two filtered items drawn off one run into a machine whose faces could hold both separately yields `flow.lane_single_item` ERROR |
| T7 | `test_matrix_lab_six_ingredients_seat_as_six_single_item_lanes` | `tests/layout/test_strip_variants.py` | **replaces the old `test_forced_mixed_lane_is_exempt` (§9 R1/R2)**: the `universe-matrix` six-ingredient Matrix Lab shape seats as six lanes of one item each, so it passes `flow.lane_single_item` on the merits rather than by exemption |
| T7b | `test_forced_mixed_lane_is_still_convicted` | `tests/layout/test_validate.py` | a mixed lane on a machine whose geometry "forced" it is an ERROR anyway — the exemption is gone |
| T13 | `test_drain_row_moves_only_when_the_input_count_needs_it` | `tests/layout/test_strip_variants.py` | a `flank_outputs` spec that already fits seats byte-identically to master; the six-ingredient spec moves the drain row past sorter reach |
| T8 | `test_same_item_shared_lane_is_not_a_mixed_lane` | `tests/layout/test_validate.py` | one item, two consumers, one lane: no finding (guards M3) |
| T9 | `test_coater_over_a_belt_merge_is_convicted` | `tests/layout/test_validate.py` | a coater whose covered tile has two belt predecessors yields `prolif.coater_rides_one_run` ERROR |
| T10 | `test_coater_supply_area_with_two_belts_is_convicted` | `tests/layout/test_validate.py` | two belts inside `ADDON_AREA_RADIUS` of area 1 yields the same check as an ERROR |
| T11 | `test_amm_url_emits_one_item_per_input_lane` | `tests/test_pipeline.py` (slow) | end-to-end on the reported URL: every belt run has at most one distinct filtered item drawn into a machine |
| T12 | `test_reforming_refine_self_loop_seeds` | `tests/rates/test_candidates.py` | the second dataset recipe gets the same treatment, from the existing `flow_refined_oil_self_feedback.csv` fixture, adjusted so hydrogen is not externally supplied |

---

## 7. Risks

1. **`universe-matrix` refuses** (rewritten 2026-09-07 for §9 R1/R2). There is
   no exemption left to mis-derive; the risk moved into the planner. If the
   drain-row move (§9 R2) does not in fact free the sixth input row — because
   `_side_lane_caps` yields fewer reachable rows than measured, or because the
   drain lane cannot sit past sorter reach on that band — then `universe-matrix`
   refuses or is convicted by `flow.lane_single_item`, and the ban costs a
   corpus cell. Mitigation: the drain-row task lands BEFORE the ban task, with
   its own red-green tests and a CLI build of `universe-matrix` that must come
   back CLEAN with six single-item lanes decoded from the blueprint. The gate
   (Task 10 Step 1a) re-checks it end to end. A refusal here is reported as a
   FAIL, not argued away.
2. **Area regression from removing M2.** Fewer coaters was the whole point of
   `prefer_shared_proliferation`. Removing it costs one coater and one lane row
   per extra sprayed ingredient. On the reported URL that is +3 coaters and
   +3 lane rows on one strip. The gate measures it; the ruling stands either way.
3. **Coverage regression from the coater-seat predicate.** A stricter seat may
   leave a coater unseatable where a merge was the only geometry available,
   turning a clean cell into a refusal. This is the honest outcome, but it must
   be *counted*, not discovered.
4. **The prime instruction is prose the player may not read.** The icon on the
   head mitigates it; nothing can force it. A block that is never primed looks
   exactly like a block that is broken, which is why the CLI line is not
   optional.
5. **A future dataset adds a third self-loop recipe with `net <= 0`.** T3 pins
   that path to the external-input arithmetic rather than to a seed.
---

## 8. Open questions for the user (three) — ALL ANSWERED, see §9

**Status 2026-09-07: closed.** The user answered all three. Their answers are
recorded as binding rulings in §9 and the sections above have been amended to
match. The questions are kept verbatim below only so the rulings can be read
against what was actually asked.

1. **Forced mixing.** The ban on mixed input lanes cannot be total without
   making `universe-matrix` refuse: a Matrix Lab offers three insert columns
   per face and that recipe has six ingredients, so it seats **only** as three
   items per lane (`freeform.py:2208-2223`). This design keeps forced mixing
   and bans only chosen mixing. Is that the right line, or do you want the ban
   to be absolute and `universe-matrix` to refuse until a different seating
   (a staircase, or a second strip) is built?
2. **Priming.** The seed can only come from the player, because a DSP blueprint
   carries no inventory. This design computes the exact amount, marks the tile,
   and warns. The alternative is to declare a permanent external input lane for
   the loop item at the consumption rate and let the surplus leave at the
   production rate — always-correct on paste, at the cost of one boundary belt
   forever and a rate the block does not really consume. Prime-and-warn, or
   permanent input lane?
3. **Belt cycles.** `belt.acyclic` (`validate.py:3510`) makes a physically
   closed loop an ERROR, though DSP itself permits belt loops. Closing the loop
   would let the player prime it anywhere and would make the surplus tail
   unnecessary. Should that rule gain a narrow exemption for a declared
   self-loop lane, or stay absolute?

---

## 9. Rulings, 2026-09-07 (binding; they outrank everything above)

These are the user's answers to §8 plus one standing retraction. Where a ruling
contradicts an earlier section, the ruling wins and the section has been
amended in place with a pointer here.

### R1 — Mixed input lanes: an ABSOLUTE ban

**Answers §8 question 1.** No input lane ever carries two distinct items —
not chosen, not forced. The forced-mixing exemption is **removed**:
`flow.lane_single_item` convicts every mixed input lane, and
`_lane_seating_is_forced` is not written at all.

*Why:* the user's note under §4 F1 already established that a forced mixed lane
has exactly the same uncontrolled interleaving as a chosen one — the machines
starve the same way, and the geometry that forced it is not an argument that it
works. An exemption would have shipped, permanently and by design, the precise
build the user reported as broken.

*Cost if the ruling is wrong:* any machine family that genuinely cannot be
seated one-item-per-lane refuses instead of building. R2 removes the one such
family we know of; a future one costs a corpus cell until its own seating is
built.

*Executor's corollary (controller ruling, 2026-09-07):* an absolute check the
emitter can still violate would turn those cells INVALID rather than REFUSED
and would waste a full routing pass discovering it. So `_seat_inputs`'
mixing ladder collapses to one item per lane and a seating that will not fit
refuses, exactly as the coater-seat predicate is made to agree with
`prolif.coater_rides_one_run` in §5.5 F2. Cost if wrong: cells that would have
emitted a mixed lane now refuse a little earlier — the same cells, since a
mixed lane is an ERROR either way and `pipeline.py:1347` prefers a valid
layout; the visible difference is REFUSED instead of INVALID in the audit.

*Changes:* §4 F1 decision, §5.4 `_lane_single_item` docstring, §5.5 F1,
§7 risk 1, §6 T7/T7b. Plan: the mixed-lane conviction task drops
`_lane_seating_is_forced` and its exemption test.

### R2 — `universe-matrix` keeps building by moving the flanked output's drain row

**Makes R1 affordable.** Measured on master: a Matrix Lab is 5x5 with three
insert poses per face; `freeform._side_lane_caps` returns three reachable rows
above and three below at its band height; six ingredients fit six single-item
lanes **except** that `_seat_inputs`'s `flank_outputs` path still charges the
output's drain lane one south ROW (the gap belts between machines drain into
it), leaving five input rows for six items.

The drain lane **carries no sorter**. It can therefore sit on the row PAST
sorter reach — row four on that side — costing one strip row on that machine
family and freeing the third south row for an input lane.

*Decision:* seat the drain lane at `below_cap + 1` (or the equivalent row
index) **only when the input count needs the freed row**; keep today's seating
otherwise, so no other spec's area moves. This lands as its own task **before**
the mixed-lane ban task, with red-green tests (a Matrix Lab spec with six
ingredients seats as six single-item lanes; a spec that never needed the row is
byte-identical to before) and a CLI build of `universe-matrix` that must come
back CLEAN with no `flow.lane_single_item` finding.

*Why:* it is a planner change that satisfies the absolute ban on the merits,
rather than an exemption that permits the failure mode. The cost is bounded and
paid only by specs that need it.

*Cost if the ruling is wrong:* one extra strip row on every `flank_outputs`
spec that trips the condition (area regression, measured per arm by the gate);
or, if the freed row does not materialise, `universe-matrix` refuses and R1
costs a corpus cell — reported as a FAIL.

*Measured while turning this ruling into a task (2026-09-07, on master, in
tree) — two corrections to the ruling's own arithmetic, recorded rather than
quietly absorbed:*

* The reservation is written down **five** times, not once. `freeform.py:2268`
  is the one the user named; `strip_variants.py:1504-1506` (`out_capacity`)
  would then hand `_shard_sinks` a zero and raise *"no room left on the south
  side for any output lane"*; `strip_variants.py:1205`
  (`_seat_both_fed_outermost`'s `south_output_rows`) is a third copy; and
  `freeform.py:1114/1171/1187` is the row map that must actually put the drain
  outermost. `freeform.py:2602-2608` (`box_height`) needs no edit.
* The cost is **+4 rows on that family, not +1**: `universe-matrix#37` goes
  from `1 above + 5 band + 1 out + 1 below = 8` to `3 + 5 + 1 + 3 = 12`. Only
  one of those rows is the drain move; the other three are the price of six
  single-item lanes replacing two mixed ones — that is, the price of R1, which
  is what the user asked for. The gate reports them separately and nets
  nothing.

**R2's premise is INCOMPLETE — measured 2026-09-07 while implementing it, and
this is the finding the user most needs.** Freeing the row makes the *seating*
work exactly as R2 predicted: a Matrix Lab seats six single-item lanes and
`box_height` goes 8 → 12. It does not make the *emission* work for a strip with
more than one machine. `freeform._flank_lane` runs each machine's gap belt down
the belt column immediately east of **its own** machine, from that machine's
east pose south to the output lane. While the drain sat innermost that column
crossed nothing. Once the drain moves outward, that column has to cross all
three south input lanes, and `geom.belt_single_occupancy` forbids it — three
cells, one column. Only the LAST machine in a strip has a clear gap column, so
the moved drain is legal only on a one-machine strip. Mirroring the drain to the
north gives the same picture; elevating the crossing does not fit the ramp
length.

Capping a flanked strip at one machine when the drain has moved makes the
geometry valid and is what shipped (controller ruling, below), but it turns
`universe-matrix#37` into 15 strips and the block then refuses for an unrelated
reason — a producer lane cannot fan out that far:

```
antimatter: mass-energy-storage#23 lane is 10 tile(s) wide
but must tap 15 consumer lane(s)
```

*So: `universe-matrix` does NOT keep building.* R1's absolute ban costs that
cell for now. The gate reports it as a FAIL with that exact message. The next
lever is the producer-lane fan-out, which is a bus/junction problem and not
strip geometry; it is not in this plan's scope and is named here so it can be
scoped as its own piece of work.

Confirmed as measured: `_side_lane_caps(2901, 0.0, 5) == (3, 3)`;
`attachable_columns` is three columns at the first three rows on each side and
**empty at the fourth**, so the drain's new row is one no sorter could have
used; `_seat_inputs` on six items with caps `(3, 4)` and `flank_outputs=True`
returns six single-item lanes. Exactly one plan in the whole corpus is flanked
(`universe-matrix#37`), so nothing else can move.

### R3 — Priming: prime once and warn

**Answers §8 question 2.** The design as written stands: derive the exact seed,
mark the head tile, put it on the description, the CLI and the web payload, and
let `flow.self_loop_primed` be the arbiter. **No permanent external input lane
for the loop item.** Nothing in §3, §5.1, §5.2, §5.3, §5.6 changes; the plan's
seed/marker/CLI/validator tasks are unchanged.

*Cost if wrong:* a player who does not read the description pastes a block that
looks broken. The icon on the head and the CLI line are the mitigation; nothing
can force it.

### R4 — Belt cycles: `belt.acyclic` stays absolute

**Answers §8 question 3.** No narrow exemption for a declared self-loop lane.
The loop stays a serial run with a surplus tail, exactly as decoded in §1.2 —
which already gives the priority-splitter behaviour for free — and a physically
closed belt ring remains an ERROR.

*Why:* R3 already solves priming with an instruction, so the only thing a ring
would buy is "prime it anywhere", at the cost of putting a hole in a validator
rule that is currently absolute and cheap to reason about.

*Cost if wrong:* the player must prime at the marked head rather than anywhere
on the lane. Nothing to change beyond recording it.

### R6 — Coater addon area 1: two RUNS, not two belts (controller ruling, 2026-09-07)

Not a user answer — a defect in §5.4 as designed, found while implementing it,
and corrected here rather than worked around in the code.

§5.4's second coater clause said "ERROR when a second belt lies within
`ADDON_AREA_RADIUS` of addon area 1". Measured on this branch, that convicts
**every coater this tool has ever placed**: `freeform._place_coaters` feeds a
coater with two belts of its own making — a `supply` belt on
`slots.addon_supply_cell(..., area=1)` and an `approach` belt one tile further
out that feeds it — and at the Spray Coater's fixed addon pose with
`Facing.EAST` they sit `0.314` and `0.942` world units from the area-1 centre,
both inside the radius of `1.0`. Landing the literal rule took 19
`tests/layout/test_freeform.py` builds to `NoValidLayout`, on
`proliferated_spec`, `all-products`, `output-products` and the negentropy
block, with the finding naming the coater's own approach/supply pair.

*Decision:* the clause fires when the belts within the radius belong to two or
more **distinct runs**. Two belts of ONE run carry one item, so which of them
the game attaches cannot change what the coater is supplied with — there is no
ambiguity to convict. Two runs is exactly the reported defect: §1.5 measured
coater#768's area 1 holding the proliferator **run 59** tail at `(53,20,1)` and
a cargo lane, **run 27**, at `(55,20,1)`, both at `0.250`, separated only by the
yaw convention. The stated reason for the rule is preserved exactly; only the
test that implements it changes.

*Cost if wrong:* an ambiguity between two same-run belts carrying different
items would go unconvicted — impossible by the definition of a run — or a
future coater geometry that legitimately needs two runs nearby would be refused.
The gate's per-arm CLEAN/REFUSED counts are where that would show up.

### R7 — The coater seat predicate must sit on the path production uses

Also a controller ruling, same investigation. §5.5 F2 and the plan named
`freeform._coater_seat` as the seat chooser to harden. `_coater_seat` is called
by **nothing in `src/`** — only by tests; production goes through
`_coater_seats` from inside `_place_coaters`. A predicate added only to
`_coater_seat` is dead code, and the emitter would have gone on seating coaters
the validator convicts. The predicate belongs on both: `_coater_seat` (so the
tests that pin it keep meaning something) and the live `_coater_seats` path.

*Cost if wrong:* filtering the live path can refuse a seat the validator would
have accepted, costing coverage; the gate counts it per arm.

### R8 — `input_lane_fits` is deleted, not kept as a single-lane rate gate

A controller ruling, 2026-09-07, made while implementing §9 R1's executor
corollary. §5.5 F1 said: "`input_lane_fits` (`strip_variants.py:1363-1374`)
stays as the unconditional rate test for the single-item lane it now always
is." That sentence is struck; F1 is amended in place above.

**The premise was false twice over, and it was measured rather than argued.**

1. *It was never a production check.* `input_lane_fits` reached `_seat_inputs`
   only through `prefer_shared_inputs`, which was
   `prefer_shared_proliferation and group.proliferated and len(input_items) >= 3`.
   No caller in `src/` ever set `prefer_shared_proliferation`; only tests did.
   So the lane rate was never gated at seating time on any path production takes,
   and "keeping" the check would have been *adding* one.

2. *It is not a valid test for a single-item lane.* It sums
   `rate * group.count` — the whole group's throughput across EVERY strip —
   against one belt, while a lane serves ONE strip. Applying it per lane
   therefore refuses any group whose total production exceeds a belt, which is
   the ordinary case that sharding exists to handle.

**Measured:** passing it unconditionally, exactly as F1 directed, produced 28
failures in `tests/layout/test_strip_variants.py` alone. All 28 trace to the same
cause — a one-item lane rejected on the whole group's rate — but the symptom is
not uniform, and the difference is worth recording: 27 surface as a refusal
quoting `1 ingredients cannot be seated`, while
`test_a_single_machine_over_the_ceiling_is_refused_early_with_the_rate` surfaces
as a regex mismatch, because the seating refusal pre-empted the rate refusal that
test asserts. Evidence:
`docs/superpowers/evidence/2026-09-06-selfloop/task5/strip-variants-with-unconditional-lane-fits.txt`.

**What replaces it: nothing new.** `strip_variants._machine_cap`
(`strip_variants.py:1998`) is already the single-item rate gate — "Machines per
strip so no single-item lane exceeds its effective capacity" — and it caps a
strip at `capacity // rate`, refusing early and with the numbers when one
machine's rate alone exceeds the fastest belt. Its docstring named exactly one
case it could not cover: "a merged lane carrying several items at once can still
exceed capacity even when every one of those items is individually under the
cap". §9 R1 abolished that case, so `_machine_cap` now covers the whole space.

*Cost if this ruling is wrong:* a single-item lane whose rate exceeds one belt
would reach `flow.belt_capacity` at validation instead of being refused at
seating time — a later, less legible refusal, not a bad emission. That is the
same backstop `_machine_cap`'s docstring already names, and the cell is
INVALID rather than REFUSED in the audit.

*Changes:* §5.5 F1 (amended in place, with a pointer here).

### R5 — The Pile Sorter rule stays retracted

§5.3a is retracted and stays retracted: no Pile Sorter rule, no new tap check,
no change to `_pick_sorter`. The loop self-regulates once primed; the "grabs
only a few" observation was the start-up transient R3 already provides for.
