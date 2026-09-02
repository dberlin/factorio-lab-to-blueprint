# Belt and sorter tiers where necessary

Date: 2026-09-02. Status: design, awaiting review.

## 1. Problem

A build uses the FactorioLab URL's belt (`ibe`) for every belt tile it emits.
`rates/candidates.py::_to_build_spec` copies it into `BuildSpec.belt_item_id`
and `belt_items_per_second`, and `layout/freeform.py::_prepare_routing_problem`
and `_build_prepared` stamp that one item id on every belt. Nothing ever
considers a faster belt, and the strip planner never splits a lane merely
because it is over capacity: the validator's `flow.belt_capacity` check catches
the overload after the fact and the attempt becomes a refusal.

Reproduced on the deuteron-fuel-rod URL from the report (its `ibe` is
`conveyor-belt-3`; forcing `conveyor-belt-2` reproduces what the user saw):
every candidate under both strategies is rejected with
`flow.belt_capacity` findings such as *belt run 56 must carry 20 items/s but its
tier sustains only 12* (hydrogen, graphene plants to colliders), and the
strategies report *every packing that wired was rejected by our own validator*
or *exact validation failures: flow.belt_capacity*. With the URL's own
`conveyor-belt-3` the same build passes, because no lane happens to exceed 30/s.

Sorters are already picked per lane by rate: `freeform.py::_pick_sorter` walks
`catalog.SORTER_TIERS` (Mk.I 1.5/s, Mk.II 3/s, Mk.III 6/s, Pile 20/s at one
tile, divided by span) and takes the cheapest that carries the per-machine
rate. It does this with no technology gating, so a save that has not researched
`integrated-logistics-system` can be handed Pile Sorters it cannot build, and a
save without `high-efficiency-logistics-system` can be handed Sorter Mk.III.

## 2. Decision

Belt tier becomes a property of each belt run, chosen after routing from what
the run actually carries, bounded below by the URL's belt and above by the
fastest belt the URL's researched technologies unlock. Sorter tiers keep their
per-lane choice and gain the same technology bound. Two validator checks
enforce the bounds.

Three rules:

1. **The URL's belt is the floor.** FactorioLab's choice is authoritative. No
   belt is ever slower than `ibe`, and a run that fits the floor keeps it, so a
   build only gets faster belts where a lane needs them.
2. **The researched set is the ceiling.** Belt and sorter tiers are read from
   the dataset's technology `recipeUnlock` lists against the URL's researched
   technology ids, exactly as `lab/techs.py::belt_rules_for_url` reads the
   altitude rules. A URL with no technology set means every technology
   researched (`catalog.belt_rules_for_technologies` documents why); an explicit
   empty set means nothing beyond the floor.
3. **Choosing is a pass, not a search.** Nothing goes back to the packer or the
   router. Routing finishes with the floor belt everywhere; one pass measures
   each run's demand with the validator's own flow propagation and swaps the
   run's tiles to the cheapest allowed tier that carries it. The validator then
   judges the result as it judges everything else.

A lane whose demand exceeds the ceiling is still refused, exactly as today.
Splitting such a lane across parallel belts, and Automatic Pilers, are the
subject of the follow-on design (multiple belts and pilers), not this one.

## 3. Technology-derived tiers

### 3.1 `catalog.LogisticsTiers`

A frozen dataclass next to `BeltAltitudeRules`:

```python
@dataclass(frozen=True, slots=True)
class LogisticsTiers:
    #: Belt item ids the save can build, slowest first. Never empty: the
    #: URL's belt is always a member, researched or not.
    belt_item_ids: tuple[str, ...]
    #: Sorter item ids the save can build, slowest first. Never empty.
    sorter_item_ids: tuple[str, ...]
    from_url: bool
```

### 3.2 `lab/techs.py::logistics_tiers_for_request(request, dataset)`

Derivation, data-driven from the dataset rather than from hard-coded
technology names:

- `researched` is every technology item id in the dataset when
  `request.researched_technology_ids is None`, else that set.
- `unlocked` is the union of `item.technology.recipe_unlock` over researched
  technology items.
- Belts: every dataset item with a `belt` record whose id is in `unlocked`,
  plus the request's belt (`request.belt_id or "conveyor-belt-1"`) whether or
  not it is unlocked, sorted by `belt.speed`. Belts slower than the floor are
  dropped; they can never be chosen.
- Sorters: every dataset item whose catalog id is in `catalog.SORTER_IDS` and
  whose id is in `unlocked`, sorted by `catalog.SORTER_RATE_AT_1`. If that is
  empty (an explicit technology set that unlocks no sorter at all), fall back
  to `("sorter-1",)` and say so in the docstring: a save that cannot build a
  Mk.I sorter cannot build the belts either, and refusing every build over it
  would help nobody.

The function sits in `lab/techs.py` for the reason that module's docstring
gives: it needs the URL parser and the dataset, and `lab` already depends on
`dsp`. `rates/candidates.py` already imports `lab.url`, so calling
`lab.techs` from `_to_build_spec` adds no new dependency direction.

The vendored dataset's unlocks, for the record: `conveyor-belt-2` and
`sorter-3` come from `high-efficiency-logistics-system`; `conveyor-belt-3` from
`planetary-logistics-system`; `sorter-4` (Pile Sorter) and `automatic-piler`
from `integrated-logistics-system`; `sorter-2` from
`improved-logistics-system`; `conveyor-belt-1` and `sorter-1` from
`basic-logistics-system`.

## 4. The spec boundary

`BuildSpec` gains two fields and one property. Existing fields keep their
meaning, so every hand-built spec in the tests behaves exactly as before.

```python
class BeltTier(_Frozen):
    item_id: str
    items_per_second: Fraction = Field(gt=0)

class BuildSpec(_Frozen):
    belt_item_id: str = "conveyor-belt-1"          # the floor, unchanged
    belt_items_per_second: Fraction = Fraction(6)  # the floor's speed, unchanged
    #: Faster belts the save can build, slowest first. Empty means the floor
    #: is also the ceiling, which is what every existing test and every
    #: hand-built spec gets.
    belt_upgrades: tuple[BeltTier, ...] = ()
    #: Sorter tiers the save can build, slowest first. Defaults to every tier
    #: so a spec built without a request keeps today's behaviour.
    sorter_item_ids: tuple[str, ...] = ("sorter-1", "sorter-2", "sorter-3", "sorter-4")

    @property
    def belt_tiers(self) -> tuple[BeltTier, ...]:
        """Floor first, then the upgrades."""

    @property
    def lane_capacity(self) -> Fraction:
        """Items/second the fastest allowed belt sustains: the planner's bound."""
```

Validators on the model: every upgrade is strictly faster than the floor and
than the upgrade before it; `sorter_item_ids` is non-empty.

`_to_build_spec` fills `belt_upgrades` and `sorter_item_ids` from
`logistics_tiers_for_request`, looking each belt's speed up with
`data.belt_speed`. Both candidate paths (derived and flow-pinned) construct
their specs through `_to_build_spec`, so both get it.

## 5. Planner: size lanes against the ceiling

Four sites compare a lane's demand against `spec.belt_items_per_second`. All
four switch to `spec.lane_capacity`, and nothing else in the planner changes:

- `layout/strip_variants.py` in `_logical_strip_plans`: the surplus-sharing
  test (`surplus + _sink_demand(...) <= ...`), the `input_lane_fits` closure,
  and the capacity handed to `_merge_lanes`.
- `layout/freeform.py::_check_shared_lane_capacity`.

The effect is that a shared or merged lane is allowed up to the best belt the
save can build instead of being refused at the floor. Single-item lanes are not
bounded by the planner today and stay that way in this design; the retier pass
carries them up to the ceiling, and beyond the ceiling the validator refuses as
it does now.

## 6. Sorter picking within the researched set

`_Canvas` gains `sorter_tiers: tuple[int, ...] = catalog.SORTER_TIERS`, set by
the two constructors (`freeform.py:6757` and `_prepare_routing_problem`) from
`spec.sorter_item_ids` through `catalog.get_item_id`. `_pick_sorter` takes the
tiers as an argument and its three callers (`_flank_lane`, `_link_lane`,
`_bridge`) pass `canvas.sorter_tiers`. The fallback when no tier carries the
rate stays the last (fastest) allowed tier: the validator's
`flow.sorter_capacity` then refuses, as it does today.

## 7. The retier pass

### 7.1 `validate.belt_run_demands(placement, spec)`

A public function in `layout/validate.py` returning
`tuple[tuple[BeltRun, ...], dict[int, dict[str | None, Fraction]]]`: the belt
runs as `_build_runs` chains them and the per-run demand `_run_demand` computes.
It builds a `Context` the way `validate()` does (`id_map(spec)`, default soft
width and altitude rules; neither affects flow) and runs no checks. Exposed
rather than duplicated so the pass and the judge can never disagree about what
a run carries.

### 7.2 `layout/belt_tiers.py::retier_belts(placement, spec) -> Placement`

For each run, `demand = sum(per_item.values())`. The run's tier is the first of
`spec.belt_tiers` whose `items_per_second >= demand`; a run with no recorded
demand, or one already within the floor, keeps the floor. A run above the
ceiling is set to the ceiling and left for `flow.belt_capacity` to refuse. Every
belt tile in the run gets the chosen item id and
`catalog.building(item_id).model_index` through `dataclasses.replace`; nothing
else on the building changes, so links, slots, altitude and yaw survive. The
placement's `stats` gain `belt_runs_upgraded`.

A run is uniform by construction: `_build_runs` chains forward-linked belt
tiles and breaks a chain wherever a tile has other than exactly one
predecessor, so a junction or a merge starts a new run and the trunk into it is
measured on its own.

### 7.3 Where it runs

Once, in `freeform.py::_build_prepared`, immediately after
`assign_sorter_slots` and before the `Placement` is returned. Both strategies
emit through `_build_prepared` (`sequence_solver.py:3888` imports it), so both
get it, and every later step (open-boundary compaction, latitude projection,
certification) sees the final tiers. The finalizer's compaction copies item ids
from existing belt tiles when it re-lays a boundary run, so tiers survive it;
the end-to-end tests below verify that claim rather than assume it.

Cost: one extra flow propagation per emitted placement, the same work
`_run_demand` already does inside `certify`. The evaluation gate
(`docs/superpowers/evidence/2026-09-01-evaluation-throughput/gate.md`) is
re-run after the change; the pass must not cost a cell.

## 8. Validator

Two new checks, both `needs_spec=True`, both `ERROR`:

- `belt.tier_allowed`: every belt tile's item id is in
  `{tier.item_id for tier in spec.belt_tiers}`. The finding names the run, the
  tile's tier and the allowed set.
- `sorter.tier_allowed`: every sorter's item id is in `spec.sorter_item_ids`.

`flow.belt_capacity` and `flow.sorter_capacity` are unchanged; they already
judge each run and sorter by its own tier.

## 9. Reporting

The CLI's verbose report and the web build report gain one line per selected
attempt: the floor belt, and how many runs were raised to which tier
(`belts: conveyor-belt-2; 6 runs raised to conveyor-belt-3`). When the ceiling
equals the floor because the URL's technology set unlocks nothing faster, the
line says so, so a refusal on `flow.belt_capacity` is legible next to it.

## 10. Testing

- `tests/lab/test_techs.py`: derivation against the vendored dataset with no
  technology set (all tiers), an explicit set lacking
  `planetary-logistics-system` (no `conveyor-belt-3`), an explicit set lacking
  `integrated-logistics-system` (no Pile Sorter), the floor always present, and
  the empty-sorter fallback.
- A new `tests/test_spec.py`: the tier ordering invariants and the two
  properties.
- `tests/layout/test_belt_tiers.py`: hand-built placements in the style of
  `tests/layout/test_validate.py` (`BELT2 = 2002`, `PILE = 2014`): a run under
  the floor keeps it; a run over the floor and under an upgrade takes the
  cheapest upgrade that fits; a run over the ceiling is set to the ceiling and
  `flow.belt_capacity` still fires; a trunk feeding two branches through a
  splitter is tiered on the summed demand; a spec with no upgrades leaves the
  placement byte-identical.
- `tests/layout/test_validate.py`: `belt.tier_allowed` and
  `sorter.tier_allowed` fire on a tile outside the set and stay quiet inside it.
- `tests/layout/test_freeform.py`: `_pick_sorter` never returns a tier outside
  the ones it was given.
- End to end, marked slow: the deuteron-fuel-rod URL with the request's belt
  replaced by `conveyor-belt-2` (monkeypatching `pipeline.parse_url`, as the
  reproduction did) builds under both strategies, the result validates clean,
  and some runs carry `conveyor-belt-3`; the same URL with an explicit
  technology set lacking `planetary-logistics-system` refuses with
  `flow.belt_capacity` and the report line names the ceiling.
- The corpus gate re-run, with the before and after JSONL committed under
  `docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/`.

## 11. Out of scope

- Splitting a lane above the ceiling across parallel belts, capping machines
  per strip so a single-item lane cannot exceed the ceiling, and Automatic
  Pilers. These are the follow-on design.
- Changing which belt FactorioLab's rate solver assumes for `ObjectiveUnit.BELTS`
  objectives (`rates/solve.py`); that stays the URL's belt.
- Any change to routing geometry. Belt tiers share footprint, slope and
  altitude rules, so the router has no reason to know the tier.
