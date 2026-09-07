# Self-Loop Recipes, Mixed Input Lanes and Coater Merges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop emitting blueprints that cannot run — a belt carrying several
different items into one machine, a Spray Coater seated over a belt merge, and
a self-consuming recipe whose loop nothing ever primes — and declare the
self-loop honestly instead of hiding it.

**Architecture:** Three independent corrections to existing machinery, no new
solver. (1) Remove the *chosen* mixed-input-lane preference and let the
validator arbitrate mixed lanes, exempting only the seatings a machine's own
geometry forces. (2) Reject a coater seat over a belt merge or an ambiguous
supply area, and convict both in the validator. (3) Derive a `SelfLoopSeed`
from the recipe in the rates layer, carry it to the blueprint icon, the
description, the CLI and the web payload, and let a new check own the
"can this ever start" question. The strip planner's loop lane, built by the
2026-08-28 self-consuming-flow-feedback work, is already correct and is not
touched.

**Tech Stack:** Python 3.14, `uv run`, pytest, pydantic v2, OR-Tools CP-SAT.

**Spec:** `docs/superpowers/specs/2026-09-06-self-loop-recipes-design.md`
**Evidence:** `docs/superpowers/evidence/2026-09-06-selfloop/README.md`

## Global Constraints

- The reported URL, referred to below as `AMM_URL`, is exactly:
  `https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFiWUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DKloJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11`
- Every production change follows red-green TDD: the failing test in the same
  task, run and seen to fail, before the implementation.
- **Belt SHARING between several consumers of the SAME item stays.**
  `freeform._merge_lanes` and `_merge_frontier` are not touched by any task
  here. Only MULTIPLE DISTINCT ITEMS on one input lane are banned.
- Rate solving's block-wide netting (`rates/solve.py:1306-1329`) is not changed.
  A self-consuming product remains an internal routing net and is never
  reclassified as an external input.
- No per-recipe special case. Every rule is stated over
  `inputs ∩ outputs` or over machine geometry, never over a recipe id.
- Two other agents run builds on this box: **at most ONE build at a time**,
  `--budget 30` for single builds, and record `uptime` beside every timing.
- Use Serena's symbolic tools to read and edit; `freeform.py` is 22k lines and
  `validate.py` is large, so read symbols, not files.
- **Mixed belts are given up, not made cleverer** (user note in spec §4 F1).
  The reported blueprint merged the three items onto one belt and still
  starved in game because interleaving is uncontrolled. No task adds
  port-filtered splitters or any other attempt to make a mixed belt work.

---

## Task 1: Convict a Spray Coater seated over a belt merge

**Files:**
- Modify: `tests/layout/test_validate.py`
- Modify: `src/flab2bp/layout/validate.py`

**Interfaces:**
- Consumes: `validate.Context`, `validate.Finding`, `validate.Severity`, `validate.check`, `validate._addon_rides`, `validate._coater_rides` (`validate.py:4898`), `catalog.SPRAY_COATER_ID`, `catalog.oriented_footprint`, `rules.ADDON_AREA_RADIUS`, `slots.addon_supply_position`.
- Produces: `@check("prolif.coater_rides_one_run", needs_spec=True)` yielding `Finding` at `Severity.ERROR`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_validate.py`:

```python
def test_coater_over_a_belt_merge_is_convicted() -> None:
    """Two belt runs merging on a tile the coater's body covers is not a lane.

    A Spray Coater is a belt addon that rides ONE belt.  Two chains pointing at
    a tile under its body is the geometry that reads in game as belts inserted
    into the coater, and it is exactly the interleaving hazard a mixed lane has.
    """
    placement = _coater_placement(merge_under_body=True)
    report = validate.validate(placement, _coater_spec(), expect_power=False)
    findings = [f for f in report.errors if f.check == "prolif.coater_rides_one_run"]
    assert findings, [f.check for f in report.errors]
    assert "merge" in findings[0].message


def test_coater_on_a_single_run_is_clean() -> None:
    placement = _coater_placement(merge_under_body=False)
    report = validate.validate(placement, _coater_spec(), expect_power=False)
    assert not [f for f in report.errors if f.check == "prolif.coater_rides_one_run"]


def test_coater_supply_area_with_two_belts_is_convicted() -> None:
    """Which belt supplies a coater must not depend on a rotation convention.

    Measured on the reported URL: coater#768's addon area 1 had the proliferator
    lane at (53,20,1) and a CARGO lane at (55,20,1), both exactly 0.250 from the
    area centre and both inside ADDON_AREA_RADIUS = 1.0.
    """
    placement = _coater_placement(merge_under_body=False, second_belt_in_supply_area=True)
    report = validate.validate(placement, _coater_spec(), expect_power=False)
    findings = [f for f in report.errors if f.check == "prolif.coater_rides_one_run"]
    assert findings
    assert "addon area 1" in findings[0].message
```

Add the two builders beside the existing coater fixtures in the same file:

```python
def _coater_spec() -> BuildSpec:
    """One proliferated group whose single ingredient rides a sprayed lane."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="gear",
                machine_item_id="assembling-machine-2",
                count=1,
                proliferator_mode=ProliferatorMode.PRODUCTS,
                inputs_per_machine={"iron-ingot": Fraction(1)},
                outputs_per_machine={"gear": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ingot": Fraction(1), "proliferator-2": Fraction(1, 10)},
        outputs={"gear": Fraction(1)},
        spray_lanes={"iron-ingot": True},
    )


def _coater_placement(
    *,
    merge_under_body: bool,
    second_belt_in_supply_area: bool = False,
) -> Placement:
    """A coater at yaw 90 riding a straight lane, optionally spoiled.

    ``merge_under_body`` adds a second belt chain whose tail points at the tile
    one step upstream of the coater origin -- a tile the 1x3 body covers.
    ``second_belt_in_supply_area`` puts a cargo belt on the mirror side of addon
    area 1, at the same distance as the proliferator belt.
    """
```

- [ ] **Step 2: Run them and see them fail**

```bash
uv run pytest tests/layout/test_validate.py -k coater_over_a_belt_merge -x -q
uv run pytest tests/layout/test_validate.py -k coater_supply_area_with_two_belts -x -q
```

Expected: both FAIL — no such check exists, so `report.errors` holds nothing
with that name. (The pytest summary line never prints in this repo; read the
exit code.)

- [ ] **Step 3: Add the check**

Insert after `_coater_rides` in `src/flab2bp/layout/validate.py` (around line
4918):

```python
def _coater_body_tiles(ctx: Context, index: int) -> set[tuple[float, float, float]]:
    """The tiles a Spray Coater's 1x3 body covers, at its own altitude."""
    b = ctx.placement.buildings[index]
    width, height = cat.oriented_footprint(cat.SPRAY_COATER_ID, b.yaw)
    return {
        (b.x + dx, b.y + dy, b.z)
        for dx in range(-(width // 2), width // 2 + 1)
        for dy in range(-(height // 2), height // 2 + 1)
    }


@check("prolif.coater_rides_one_run", needs_spec=True)
def _coater_rides_one_run(ctx: Context) -> Iterable[Finding]:
    """A Spray Coater rides one belt run, with no merge under its body.

    A coater carries no connection of its own -- the game finds its belts by
    position (``game.addon_supply``) -- so nothing in the record says which lane
    it is on beyond where the belts are.  Two chains pointing at one tile is a
    legal DSP merge in general (``belt.acyclic`` says so), but under a coater it
    is not a lane: the three flows it joins must arrive interleaved in the
    recipe's exact proportion or one of them fills the belt and starves the
    others, and nothing arranges that.

    Measured on the reporting URL: belt#0 at (53,20,0) had predecessors
    [817, 1872] and sat under coater#768's body; belt#19 at (53,26,0) had
    predecessors [830, 2037] under coater#771.  Both blueprints validated clean.

    The second clause is narrower and just as unfixable downstream: two belts
    inside ``rules.ADDON_AREA_RADIUS`` of addon area 1 means which one supplies
    the coater is decided by a rotation convention rather than by the geometry
    we emitted.
    """
```

Body: for each coater index in `_coater_rides(ctx).values()`, compute
`_coater_body_tiles`, find the belts on those tiles, and yield
`Severity.ERROR` when any of them has two or more belt predecessors
(`ctx.pred` restricted to `Kind.BELT`), or when belts of two distinct
`ctx.run_of` values sit on them. Then resolve `slots.addon_supply_position(...,
area=1)` and yield `Severity.ERROR` when more than one belt lies within
`rules.ADDON_AREA_RADIUS` of it.

- [ ] **Step 4: Re-run and see them pass, plus the whole validator suite**

```bash
uv run pytest tests/layout/test_validate.py -q
```

Expected: exit 0.

---

## Task 2: Stop the emitter seating a coater over a merge

**Files:**
- Modify: `tests/layout/test_freeform.py`
- Modify: `src/flab2bp/layout/freeform.py`

**Interfaces:**
- Consumes: `freeform._coater_seats` (`freeform.py:18018`), `freeform._coater_seat` (`freeform.py:18039`), `freeform._place_coaters` (`freeform.py:18140`), `freeform._Canvas`, `freeform._Port`.
- Produces: `freeform._coater_seat` returns `None` for a seat whose covered tiles carry a belt merge or whose area-1 position has two belts; signature unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_freeform.py`:

```python
def test_coater_seat_rejects_a_tile_with_a_belt_merge() -> None:
    """A seat whose body covers a merge is not a seat, however short the lane.

    `_coater_seat` used to answer only "is this drop cell free and is the lane
    long enough".  The reporting URL seated two coaters over 2-into-1 merges
    that way, and `prolif.coater_rides_one_run` now convicts every such
    placement -- so the seat chooser has to agree with the validator or the
    strategy refuses at the last step instead of choosing a legal seat.
    """
    canvas, port = _canvas_with_lane_merge_at(x=53, y=20, z=0)
    assert freeform._coater_seat(canvas, port) is None

    clean_canvas, clean_port = _canvas_with_straight_lane_at(x=53, y=20, z=0)
    assert freeform._coater_seat(clean_canvas, clean_port) is not None
```

- [ ] **Step 2: Run it and see it fail**

```bash
uv run pytest tests/layout/test_freeform.py -k coater_seat_rejects -x -q
```

Expected: FAIL — `_coater_seat` returns a seat for the merged canvas.

- [ ] **Step 3: Add the predicate**

In `freeform._coater_seat`, before returning a candidate `(x, y)`, reject it
when any belt on the tiles the coater body would cover has more than one belt
predecessor on the canvas, or when the area-1 position resolves to more than
one belt within `rules.ADDON_AREA_RADIUS`. Keep the existing `continue` /
`None` contract so `_place_coaters` handles it exactly as it handles a taken
drop cell today; `prolif.sprayed_cargo_reaches_machines`
(`validate.py:5011`) remains the backstop that turns a silently skipped coater
into a refusal.

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/layout/test_freeform.py -q
```

Expected: exit 0.

---

## Task 3: Convict a mixed-item input lane

**Files:**
- Modify: `tests/layout/test_validate.py`
- Modify: `src/flab2bp/layout/validate.py`

**Interfaces:**
- Consumes: `validate.Context`, `validate._sorter_items`, `validate.Kind`, `freeform._side_lane_caps`, `slots.probe_building`, `slots.attachable_columns`, `catalog.get_item_id`.
- Produces: `@check("flow.lane_single_item", needs_spec=True, needs_groups=True)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_validate.py`:

```python
def test_mixed_item_input_lane_is_convicted() -> None:
    """One input belt carries one item.

    Measured on the reporting URL: belt run 7 carried frame-material,
    optical-grating-crystal AND super-magnetic-ring into the same two
    advanced-mining-machine assemblers, and run 16 carried two more.  A native
    DSP merge is first-come, not proportional, so whichever source runs ahead
    fills the belt and the others back up.  `flow.belt_capacity` already sums
    across items and was satisfied; nothing asked whether they could interleave.
    """
    placement = _two_items_on_one_input_lane()
    report = validate.validate(placement, _two_ingredient_spec(), expect_power=False)
    findings = [f for f in report.errors if f.check == "flow.lane_single_item"]
    assert findings, [f.check for f in report.errors]
    assert findings[0].detail["items"] == ["copper-ingot", "iron-ingot"]


def test_same_item_shared_lane_is_not_a_mixed_lane() -> None:
    """Two consumers of ONE item off one lane is belt sharing, and it stays.

    `_merge_lanes` / `_merge_frontier` fold a producer's destinations onto one
    lane; that sharing is load-bearing for feasibility on 12 of 36 corpus cells.
    This check counts DISTINCT ITEMS on a run, never taps.
    """
    placement = _one_item_two_consumers_on_one_lane()
    report = validate.validate(placement, _one_ingredient_two_groups_spec(), expect_power=False)
    assert not [f for f in report.errors if f.check == "flow.lane_single_item"]


def test_forced_mixed_lane_is_exempt() -> None:
    """A machine that cannot seat one item per lane may mix, and only then.

    `universe-matrix` takes six ingredients into a Matrix Lab offering three
    insert columns per face, so `freeform._seat_inputs` seats it ONLY as three
    items per lane above and three below (freeform.py:2208-2223).  The exemption
    is re-derived here from the catalog rather than taken on the planner's word.
    """
    placement = _matrix_lab_six_ingredients_placement()
    report = validate.validate(placement, _matrix_lab_six_ingredient_spec(), expect_power=False)
    assert not [f for f in report.errors if f.check == "flow.lane_single_item"]
```

- [ ] **Step 2: Run them and see the first fail**

```bash
uv run pytest tests/layout/test_validate.py -k lane_single_item -x -q
uv run pytest tests/layout/test_validate.py -k "mixed_item_input_lane or same_item_shared_lane or forced_mixed_lane" -q
```

Expected: `test_mixed_item_input_lane_is_convicted` FAILS; the other two pass
vacuously (no such check yet) and must still pass at the end.

- [ ] **Step 3: Add the check**

Insert in `src/flab2bp/layout/validate.py` beside the other flow checks:

```python
def _lane_seating_is_forced(ctx: Context, machine: int, ingredients: int) -> bool:
    """Whether this machine's own faces make one-item-per-lane impossible.

    Re-derived from the two catalog helpers the planner uses -- the per-side row
    caps and the face's attachable insert columns -- so the exemption is proved
    from the game data rather than taken on the strip planner's word.  A machine
    with more ingredients than ``above_cap + below_cap`` lanes, or than
    ``columns`` insert poses per side, can only be seated by mixing.
    """


@check("flow.lane_single_item", needs_spec=True, needs_groups=True)
def _lane_single_item(ctx: Context) -> Iterable[Finding]:
    """One input belt carries one item.

    A run whose sorters draw two or more DISTINCT items into machines is an
    ERROR unless :func:`_lane_seating_is_forced` proves the consuming machine's
    geometry left no alternative.  Detail carries ``run``, sorted ``items`` and
    the machines, so the finding names what to un-mix.

    This counts distinct ITEMS, never taps: several consumers of ONE item off
    one lane is belt sharing, which is a different mechanism and stays.
    """
```

Body: build `items_by_run: dict[int, set[str]]` from every sorter whose
`input_obj` is a belt and whose `output_obj` is a machine, using
`_sorter_items(ctx)`; for each run with two or more items, exempt it when every
consuming machine satisfies `_lane_seating_is_forced`; otherwise yield
`Severity.ERROR`.

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/layout/test_validate.py -q
```

Expected: exit 0.

---

## Task 4: Remove the chosen mixed-lane preference

**Files:**
- Modify: `tests/layout/test_strip_variants.py`
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py`

**Interfaces:**
- Consumes: `strip_variants._logical_strip_plans(spec)`, `strip_variants.generate_strip_families(spec)`, `freeform._seat_inputs(items, n_sinks, above_cap, below_cap, max_per_lane, columns, *, flank_outputs=False, lane_fits=None, seating_fits=None)`.
- Produces: `prefer_shared_proliferation` and `prefer_shared` are gone from all three call sites; `lane_fits` is passed unconditionally.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_strip_variants.py`:

```python
def test_proliferated_group_does_not_mix_ingredients_onto_one_lane() -> None:
    """Fewer coaters is not worth a belt whose items must interleave exactly.

    `prefer_shared_proliferation` reversed `_seat_inputs`' mixing ladder for any
    proliferated group with three or more ingredients, so it mixed AS HARD AS
    POSSIBLE and gated only on the rate sum (`input_lane_fits`).  On the
    reporting URL that put three items on one lane into the two
    advanced-mining-machine assemblers, and two on another.  One item per lane
    is now the rule; mixing survives only where the machine's faces force it.
    """
    (plan,) = [p for p in _logical_strip_plans(_five_ingredient_proliferated_spec())]
    lanes = (*plan.in_above, *plan.in_below)
    assert all(len(lane) == 1 for lane in lanes), lanes
```

- [ ] **Step 2: Run it and see it fail**

```bash
uv run pytest tests/layout/test_strip_variants.py -k does_not_mix_ingredients -x -q
```

Expected: FAIL — lanes hold three and two items.

- [ ] **Step 3: Delete the preference**

- `src/flab2bp/layout/strip_variants.py:1255` — drop the
  `prefer_shared_proliferation: bool = False` parameter from
  `_logical_strip_plans`.
- `strip_variants.py:1358-1360` — delete `prefer_shared_inputs`.
- `strip_variants.py:1449-1450` and `1466-1467` — drop `prefer_shared=`, and
  pass `lane_fits=input_lane_fits` unconditionally (a forced mixed lane still
  has to fit the belt).
- `strip_variants.py:1985,1996` — drop the parameter from
  `generate_strip_families` and its forwarding.
- `src/flab2bp/layout/freeform.py:2179` — drop `prefer_shared` from
  `_seat_inputs`; at `freeform.py:2243-2245` reduce the ladder to
  `mix_sizes = range(1, max(1, max_per_lane) + 1)` and update the docstring
  paragraph at `freeform.py:2186-2189` to say that mixing is now only ever a
  fallback, citing `flow.lane_single_item`.

Then update every caller and test that passes the flag:

```bash
uv run python - <<'PY'
import subprocess
print(subprocess.run(["grep","-rn","prefer_shared","src","tests"],capture_output=True,text=True).stdout)
PY
```

Expected after the change: no hits.

- [ ] **Step 4: Re-run the layout suites**

```bash
uv run pytest tests/layout -q
```

Expected: exit 0. `universe-matrix`-shaped seatings still mix, because the
mixing ladder still escalates when one-per-lane does not fit.

---

## Task 5: Enumerate self-loop recipes and carry the seed on the spec

**Files:**
- Modify: `tests/lab/test_data.py`
- Modify: `tests/test_spec.py`
- Modify: `src/flab2bp/spec.py`

**Interfaces:**
- Consumes: `flab2bp.lab.data.load_vendored`, pydantic `Field`, `model_validator`.
- Produces: `spec.SelfLoopSeed` and `BuildSpec.self_loop_seeds: tuple[SelfLoopSeed, ...] = ()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/lab/test_data.py`:

```python
def test_only_two_vendored_recipes_consume_what_they_produce() -> None:
    """The self-loop set is exactly two recipes, and a dataset bump must say so.

    Both are net-POSITIVE oil-refinery recipes, which is what makes a one-off
    prime sufficient: after the first craft the loop sustains itself.
    """
    ds = load_vendored()
    loops = {
        r.id: sorted(set(r.inputs) & set(r.outputs))
        for r in ds.recipes
        if set(r.inputs) & set(r.outputs)
    }
    assert loops == {
        "x-ray-cracking": ["hydrogen"],
        "reforming-refine": ["refined-oil"],
    }
    assert ds.recipe("x-ray-cracking").outputs["hydrogen"] == Fraction(3)
    assert ds.recipe("x-ray-cracking").inputs["hydrogen"] == Fraction(2)
    assert ds.recipe("reforming-refine").outputs["refined-oil"] == Fraction(3)
    assert ds.recipe("reforming-refine").inputs["refined-oil"] == Fraction(2)
```

Add to `tests/test_spec.py`:

```python
def test_self_loop_seed_arithmetic_cannot_lie() -> None:
    with pytest.raises(ValidationError):
        SelfLoopSeed(
            item_id="hydrogen",
            recipe_id="x-ray-cracking",
            machine_item_id="oil-refinery",
            machines=4,
            consumed_per_craft=Fraction(2),
            produced_per_craft=Fraction(3),
            net_per_craft=Fraction(2),  # wrong: 3 - 2 = 1
            seed_items=8,
        )
    with pytest.raises(ValidationError):
        SelfLoopSeed(
            item_id="hydrogen",
            recipe_id="x-ray-cracking",
            machine_item_id="oil-refinery",
            machines=4,
            consumed_per_craft=Fraction(2),
            produced_per_craft=Fraction(3),
            net_per_craft=Fraction(1),
            seed_items=4,  # wrong: ceil(4 * 2) = 8
        )
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/lab/test_data.py -k consume_what_they_produce -x -q
uv run pytest tests/test_spec.py -k self_loop_seed_arithmetic -x -q
```

Expected: the first passes if the dataset is as measured (it is — keep it as
the guard); the second FAILS with `ImportError`/`NameError` because
`SelfLoopSeed` does not exist.

- [ ] **Step 3: Add the model**

In `src/flab2bp/spec.py`, after `CoproductBufferProof` (line 119):

```python
class SelfLoopSeed(_Frozen):
    """A recipe that consumes an item it also produces, and its one-off prime.

    DSP machines paste EMPTY and a blueprint carries no inventory --
    ``dsp.records.BlueprintBuilding`` has no inventory field -- so a loop whose
    only source is itself holds zero items at t=0 and the block never starts.
    The rates layer is right to net the loop away (``rates/solve.py:1306-1329``)
    and the strip planner is right to build the recirculating lane; what neither
    can express is that the lane must be filled once by hand.

    ``seed_items`` is one full input batch per machine, so every machine in the
    group can start its first craft at once.  It is sufficient because
    ``net_per_craft`` is positive: the loop gains items from then on.
    """

    item_id: str
    recipe_id: str
    machine_item_id: str
    machines: int = Field(gt=0)
    consumed_per_craft: Fraction = Field(gt=0)
    produced_per_craft: Fraction = Field(gt=0)
    net_per_craft: Fraction = Field(gt=0)
    seed_items: int = Field(gt=0)

    @model_validator(mode="after")
    def _arithmetic_holds(self) -> SelfLoopSeed:
        if self.net_per_craft != self.produced_per_craft - self.consumed_per_craft:
            raise ValueError(
                f"{self.recipe_id}: net_per_craft {self.net_per_craft} is not "
                f"{self.produced_per_craft} - {self.consumed_per_craft}"
            )
        need = self.machines * self.consumed_per_craft
        exact = -((-need.numerator) // need.denominator)
        if self.seed_items != exact:
            raise ValueError(
                f"{self.recipe_id}: seed_items {self.seed_items} is not the "
                f"{exact} whole items {self.machines} machine(s) need to start"
            )
        return self
```

and on `BuildSpec`, after `coproduct_buffer_proofs` (line 199):

```python
    #: Items a group both consumes and produces.  Steady-state correct and dead
    #: on paste until primed; see :class:`SelfLoopSeed`.
    self_loop_seeds: tuple[SelfLoopSeed, ...] = ()
```

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/test_spec.py tests/lab/test_data.py -q
```

Expected: exit 0.

---

## Task 6: Derive the seed in the rates layer

**Files:**
- Modify: `tests/rates/test_candidates.py`
- Modify: `src/flab2bp/rates/candidates.py`
- Modify: `src/flab2bp/layout/hierarchy/partition.py`

**Interfaces:**
- Consumes: `rates.candidates._to_build_spec(data, request, solution, label)`, `Dataset.recipe`, `RateSolution.groups`.
- Produces: `rates.candidates._self_loop_seeds(data: Dataset, solution: RateSolution) -> tuple[SelfLoopSeed, ...]`, wired at `candidates.py:216`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/rates/test_candidates.py`:

```python
AMM_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi"
    "WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK"
    "loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"
)


def test_self_loop_seed_is_derived_for_x_ray_cracking(data: Dataset) -> None:
    """The reported URL's hydrogen loop is declared, exactly and in whole items.

    Measured: the output-products candidate runs four oil refineries on
    x-ray-cracking, consuming 149/90 hydrogen/s and producing 149/60, with
    149/180 leaving as surplus.  No hydrogen is an external input, so the loop
    starts empty and the block deadlocks until someone drops eight in.
    """
    specs = build_candidates(data, parse_url(AMM_URL))
    (spec,) = [s for s in specs.candidates if s.label == "output-products"]
    (seed,) = spec.self_loop_seeds
    assert seed.item_id == "hydrogen"
    assert seed.recipe_id == "x-ray-cracking"
    assert seed.machine_item_id == "oil-refinery"
    assert seed.machines == 4
    assert seed.consumed_per_craft == Fraction(2)
    assert seed.produced_per_craft == Fraction(3)
    assert seed.net_per_craft == Fraction(1)
    assert seed.seed_items == 8
    assert "hydrogen" not in spec.external_inputs
    assert spec.surplus_outputs["hydrogen"] == Fraction(149, 180)


def test_self_loop_seed_absent_when_net_is_not_positive() -> None:
    """A loop that loses items is an external input, not a prime.

    ``rates/solve.py:1306-1318`` already turns the shortfall into an external
    input; declaring a seed there would promise a self-sustaining loop that is
    not one.
    """
    solution = _solution_with_group(
        recipe_id="lossy-loop",
        inputs_per_craft={"x": Fraction(3)},
        outputs_per_craft={"x": Fraction(2), "y": Fraction(1)},
    )
    assert _self_loop_seeds(_dataset_with_lossy_loop(), solution) == ()
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/rates/test_candidates.py -k self_loop_seed -x -q
```

Expected: FAIL — `_self_loop_seeds` does not exist.

- [ ] **Step 3: Implement**

In `src/flab2bp/rates/candidates.py`, after `_coproduct_buffer_proofs`
(line 149):

```python
def _self_loop_seeds(data: Dataset, solution: RateSolution) -> tuple[SelfLoopSeed, ...]:
    """Every group whose recipe consumes an item it also produces.

    Stated over ``inputs & outputs`` rather than over a recipe id, so the two
    recipes the vendored dataset has today (``x-ray-cracking`` for hydrogen and
    ``reforming-refine`` for refined oil) and any third one a dataset bump adds
    are covered by the same rule.  A non-positive net is deliberately skipped:
    the shortfall arithmetic in :mod:`flab2bp.rates.solve` already makes it an
    external input, which is the right answer for a loop that loses items.
    """
    seeds: list[SelfLoopSeed] = []
    for group in solution.groups:
        recipe = data.recipe(group.recipe_id)
        for item_id in sorted(set(recipe.inputs) & set(recipe.outputs)):
            consumed = recipe.inputs[item_id]
            produced = recipe.outputs[item_id]
            if produced <= consumed:
                continue
            need = group.machines * consumed
            seeds.append(
                SelfLoopSeed(
                    item_id=item_id,
                    recipe_id=group.recipe_id,
                    machine_item_id=group.machine_item_id,
                    machines=group.machines,
                    consumed_per_craft=consumed,
                    produced_per_craft=produced,
                    net_per_craft=produced - consumed,
                    seed_items=-((-need.numerator) // need.denominator),
                )
            )
    return tuple(seeds)
```

Wire it at `candidates.py:216`, beside `coproduct_buffer_proofs`:

```python
        self_loop_seeds=_self_loop_seeds(data, solution),
```

In `src/flab2bp/layout/hierarchy/partition.py`, propagate it exactly as
`coproduct_buffer_proofs` is propagated at lines 349-351 and 419, filtered to
the recipe ids the sub-spec keeps.

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/rates tests/layout/hierarchy -q
```

Expected: exit 0.

---

## Task 7: Mark, describe and report the prime

**Files:**
- Modify: `tests/layout/test_markers.py`
- Modify: `tests/test_cli.py`
- Modify: `src/flab2bp/layout/markers.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/cli.py`
- Modify: `src/flab2bp/web/payload.py`

**Interfaces:**
- Consumes: `markers.input_belt_heads(placement)`, `catalog.belt_marker(dsp_item_id)`, `catalog.get_item_id(item)`, `PlacedBuilding.carries_item`.
- Produces:
  - `markers.self_loop_prime_heads(placement: Placement, spec: BuildSpec) -> dict[str, int]`
  - `markers.mark_external_belts(placement, spec)` additionally marks those heads
  - `pipeline._prime_note(spec: BuildSpec, placement: Placement) -> str`
  - `cli` prints `prime once (self-loop): …`
  - `web/payload` gains `"self_loop_seeds"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_markers.py`:

```python
def test_self_loop_lane_head_is_marked() -> None:
    """The tile the player drops the seed on carries the item's icon.

    `mark_external_belts` marked only heads whose item is in
    `spec.external_inputs`, and a self-loop item never is -- so the reporting
    URL's 107-tile hydrogen lane began at an unlabelled belt at (3,21) that
    looked exactly like a forgotten input.
    """
    placement = _self_loop_placement()  # hydrogen loop, head at (3, 21)
    spec = _self_loop_spec()
    heads = markers.self_loop_prime_heads(placement, spec)
    assert set(heads) == {"hydrogen"}
    marked = markers.mark_external_belts(placement, spec)
    assert marked.buildings[heads["hydrogen"]].parameters == catalog.belt_marker(
        catalog.item_id("hydrogen")
    )
```

Add to `tests/test_cli.py`:

```python
def test_cli_reports_the_self_loop_prime(capsys) -> None:
    build = _build_with_self_loop_seed()
    cli._report(build, out=sys.stdout)
    out = capsys.readouterr().out
    assert "prime once (self-loop): hydrogen 8 items" in out
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/layout/test_markers.py -k self_loop_lane_head -x -q
uv run pytest tests/test_cli.py -k reports_the_self_loop_prime -x -q
```

Expected: both FAIL (`AttributeError` on `self_loop_prime_heads`, missing line).

- [ ] **Step 3: Implement**

`src/flab2bp/layout/markers.py`:

```python
def self_loop_prime_heads(placement: Placement, spec: BuildSpec) -> dict[str, int]:
    """Loop-lane head belt index per self-loop item, for the prime icon.

    The loop lane is the run that both RECEIVES the item from a group's output
    sorter and DELIVERS it to that same group's input sorters.  Its head is
    where a hand or a temporary belt puts the seed in, so that is the tile that
    gets the icon -- and unlike an external input it is not in
    ``spec.external_inputs``, which is exactly why nothing marked it before.
    """
```

Extend `mark_external_belts` (`markers.py:96-140`) to mark those heads too, and
count them in `stats["self_loop_prime_markers"]`.

`src/flab2bp/pipeline.py`, beside `_generated_title` (line 440):

```python
def _prime_note(spec: BuildSpec, placement: Placement) -> str:
    """`; PRIME ONCE: 8 hydrogen onto the marked belt at (3,21)`, or ``''``."""
```

and append it to the `description=` at `pipeline.py:1172-1175`.

`src/flab2bp/cli.py`, after the `inputs to belt in:` block (lines 42-50):

```python
    for seed in build.spec.self_loop_seeds:
        head = prime_heads.get(seed.item_id)
        where = f" at ({head.x},{head.y})" if head is not None else ""
        print(
            f"prime once (self-loop): {seed.item_id} {seed.seed_items} items"
            f" onto the marked belt{where}"
            f" -- {seed.recipe_id} consumes what it produces, so the block will"
            f" not start until the loop has items in it",
            file=out,
        )
```

`src/flab2bp/web/payload.py`, beside `"external_inputs"` at lines 124 and 212:

```python
        "self_loop_seeds": {
            s.item_id: {
                "seed_items": s.seed_items,
                "recipe": s.recipe_id,
                "machines": s.machines,
            }
            for s in spec.self_loop_seeds
        },
```

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/layout/test_markers.py tests/test_cli.py tests/web -q
```

Expected: exit 0.

---

## Task 8: Make the validator the arbiter of the prime

**Files:**
- Modify: `tests/layout/test_validate.py`
- Modify: `src/flab2bp/layout/validate.py`

**Interfaces:**
- Consumes: `validate.Context`, `validate._reachable_from_outside(ctx, z)`, `validate._internal_seeds`, `validate.Kind`, `BuildSpec.self_loop_seeds`.
- Produces: `@check("flow.self_loop_primed", needs_spec=True, needs_groups=True)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_validate.py`:

```python
def test_self_loop_lane_that_cannot_be_reached_is_an_error() -> None:
    """You cannot prime what no belt and no hand can reach.

    An unreachable loop lane is the same class of defect as
    `flow.external_entry_reachable`'s walled-in input: nothing about the
    blueprint looks wrong, and it simply never starts.
    """
    placement = _self_loop_placement(walled_in=True)
    report = validate.validate(placement, _self_loop_spec(), expect_power=False)
    assert [f for f in report.errors if f.check == "flow.self_loop_primed"]


def test_self_loop_lane_that_can_be_reached_is_a_warning_naming_the_seed() -> None:
    placement = _self_loop_placement(walled_in=False)
    report = validate.validate(placement, _self_loop_spec(), expect_power=False)
    assert not [f for f in report.errors if f.check == "flow.self_loop_primed"]
    (finding,) = [f for f in report.warnings if f.check == "flow.self_loop_primed"]
    assert finding.detail["item"] == "hydrogen"
    assert finding.detail["seed_items"] == 8


def test_self_loop_lane_that_does_not_close_is_an_error() -> None:
    """A declared loop whose output never reaches its own input is not a loop."""
    placement = _self_loop_placement(closed=False)
    report = validate.validate(placement, _self_loop_spec(), expect_power=False)
    assert [f for f in report.errors if f.check == "flow.self_loop_primed"]
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/layout/test_validate.py -k self_loop -x -q
```

Expected: all three FAIL — no such check.

- [ ] **Step 3: Add the check**

In `src/flab2bp/layout/validate.py`, beside `_coproduct_buffer`
(line 4632):

```python
@check("flow.self_loop_primed", needs_spec=True, needs_groups=True)
def _self_loop_primed(ctx: Context) -> Iterable[Finding]:
    """A loop that feeds itself must close, be reachable, and be priced.

    ``flow.conservation`` answers the steady-state question and answers it
    correctly: a self-loop item nets to zero and the produced item does reach
    the taps.  Neither of its clauses has any notion of an INITIAL FILL, and
    ``flow.coproduct_buffer`` is a certificate verifier that yields nothing when
    no certificate exists -- so a block whose only hydrogen source is itself
    passed every check and deadlocked on paste.

    ERROR when the loop lane does not physically close (the group's own output
    sorter does not reach its own input pickups), and ERROR when every tile of
    that lane is walled in, which is the same defect
    ``flow.external_entry_reachable`` catches for an ordinary input.  WARNING
    otherwise, naming item, ``seed_items`` and the marked tile, so the
    obligation reaches the report, the CLI and the web payload rather than
    living only in the blueprint description.
    """
```

- [ ] **Step 4: Re-run the whole suite**

```bash
uv run pytest -q
```

Expected: exit 0. The 120 s `pytest-timeout` backstop hard-kills a run, so if a
slow layout test is near it, run `tests/layout` on its own.

---

## Task 9: Gate — the reported URL, both self-loop recipes, and a paired corpus round

**Files:**
- Create: `docs/superpowers/evidence/2026-09-06-selfloop/gate/` (logs and JSONL)
- Modify: `docs/superpowers/evidence/2026-09-06-selfloop/README.md` (append the result)

**Interfaces:**
- Consumes: `uv run flab2bp`, `scripts/audit.py`, `scripts/audit_compare.py`, `docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_decode.py`, `probe_coater.py`.
- Produces: a PASS/FAIL verdict with area geomean, CLEAN counts and routing seconds per arm.

**ONE BUILD AT A TIME. Record `uptime` beside every timing.**

- [ ] **Step 1: The reported URL builds and no longer emits a mixed lane or a coater merge**

```bash
E=docs/superpowers/evidence/2026-09-06-selfloop/gate
mkdir -p "$E"
uptime | tee "$E/uptime-before-amm.txt"
/usr/bin/time -v uv run flab2bp "$AMM_URL" --budget 30 -v \
  -o "$E/bp-amm-after.txt" 2>&1 | tee "$E/build-amm-after.log"
uptime | tee -a "$E/uptime-before-amm.txt"
uv run python docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_decode.py \
  "$E/bp-amm-after.txt" > "$E/decode-amm-after.txt"
uv run python docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_coater.py \
  "$E/bp-amm-after.txt" > "$E/coater-amm-after.txt"
```

PASS requires all four:

1. `build-amm-after.log` reports `errors 0` for the winning cell.
2. `decode-amm-after.txt` contains **no** `SHARED-INPUT-RUN` line.
3. `coater-amm-after.txt` contains **no** `MERGE POINT` line on a tile the
   coater body covers, and each coater's addon area 1 resolves to exactly one
   belt within `ADDON_AREA_RADIUS`.
4. `build-amm-after.log` contains
   `prime once (self-loop): hydrogen 8 items`.
- [ ] **Step 2: The second self-loop recipe**

`reforming-refine` is not activated by any corpus URL (`tests/rates/test_solve.py:596`),
so drive it from the existing pinned fixture, with hydrogen NOT externally
supplied so the loop is the only source:

```bash
uv run pytest tests/rates/test_candidates.py -k reforming_refine_self_loop_seeds -q
```

with the test from spec §6 T12 added in Task 6. PASS requires
`seed_items == machines * 2` and `net_per_craft == 1` for `refined-oil`.

- [ ] **Step 3: Baseline the corpus on master**

From a clean master checkout of this worktree's parent commit:

```bash
uptime | tee "$E/uptime-baseline.txt"
/usr/bin/time -v uv run python scripts/audit.py --tier stress --budget 30 \
  --strategy both --json "$E/audit-baseline.jsonl" 2>&1 | tee "$E/audit-baseline.log"
uptime | tee -a "$E/uptime-baseline.txt"
```

- [ ] **Step 4: The candidate round**

```bash
uptime | tee "$E/uptime-candidate.txt"
/usr/bin/time -v uv run python scripts/audit.py --tier stress --budget 30 \
  --strategy both --json "$E/audit-candidate.jsonl" 2>&1 | tee "$E/audit-candidate.log"
uptime | tee -a "$E/uptime-candidate.txt"
```

- [ ] **Step 5: Compare, and report all three axes**

```bash
uv run python scripts/audit_compare.py "$E/audit-baseline.jsonl" "$E/audit-candidate.jsonl" \
  --expect-cells 72 | tee "$E/audit-compare.txt"
```

Then, from the two JSONL files, write `"$E/verdict.md"` reporting **per arm**
(`freeform`, `sequence-pair`):

| axis | why it is here |
|---|---|
| geometric mean area ratio over cells clean in BOTH files | the density cost of one item per lane |
| CLEAN / REFUSED / INVALID counts, and the named cells that moved either way | **a cell that starts building because its lanes stopped being coupled is a WIN for the rule, not a cost** |
| routing seconds and rip-up rounds per cell where the JSONL exposes them, p50 and p95 | a mixed lane couples strips that would otherwise be independent, so the rule may pay for itself here |
| the count of specs whose strip count grew | the direct structural consequence of un-mixing |

**The ruling stands whatever the area number says.** Report it plainly:

* If coverage or route time improves, say so — the rule paid for itself.
* If area costs with no coverage gain, quantify it exactly and leave the number
  in front of the user rather than arguing it away.
* `universe-matrix` is expected to keep its forced mixed lanes and stay CLEAN.
  If it refuses, that is spec §8 open question 1 and it goes back to the user
  before anything else is decided.

- [ ] **Step 6: Append the verdict to the evidence README**

Add a `## Gate result` section to
`docs/superpowers/evidence/2026-09-06-selfloop/README.md` with the four Step-1
checks, the three-axis table, the `audit_compare` verdict line, and the
`uptime` readings beside every timing.

---

## Task 10: Commit

- [ ] **Step 1: Run the full suite and the linters**

```bash
uv run pytest -q; echo "pytest exit=$?"
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "fix: one item per input lane, no coater merges, primed self-loops

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```
