# Belt and Sorter Tiers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every belt run the cheapest researched belt tier that carries what it measures, keep sorter tiers within the researched set, and enforce both in the validator, so a Mk.II URL whose lanes need Mk.III builds instead of refusing.

**Architecture:** The FactorioLab URL's belt stays the floor and the fastest researched belt is the ceiling; both come from the dataset's technology `recipe_unlock` lists through `lab/techs.py` and travel on `BuildSpec`. The planner sizes lanes against the ceiling. After routing, one pass in `freeform._build_prepared` (shared by both strategies) measures each belt run with the validator's own flow propagation and swaps its tiles to the cheapest tier that fits. Two new validator checks refuse any belt or sorter outside the researched set.

**Tech Stack:** Python 3.12+, pydantic models in `spec.py`, frozen dataclasses elsewhere, `Fraction` for every rate, pytest, `uv run` for everything.

**Spec:** `docs/superpowers/specs/2026-09-02-belt-and-sorter-tiers-design.md`

## Global Constraints

- Code reading and editing go through Serena's symbolic tools (`get_symbols_overview`, `find_symbol`, `find_referencing_symbols`, `replace_symbol_body`, `replace_content`, `insert_after_symbol`); never grep for call sites, use `find_referencing_symbols`.
- Every rate is an exact `Fraction`; no float reaches geometry or the validator.
- The URL's belt is the floor: no emitted belt is ever slower than `spec.belt_item_id`.
- A URL with no technology set (`researched_technology_ids is None`) means every technology researched; an explicit empty set means nothing beyond the floor.
- Existing hand-built `BuildSpec`s must keep their behaviour: `belt_upgrades` defaults to `()` and `sorter_item_ids` defaults to all four sorters.
- Run tests with `uv run pytest <path> -q`; lint with `uv run ruff check <paths>` and `uv run mypy <paths>` before each commit.
- Commit messages end with the two trailer lines:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01RbwnAXJMnsp5fcmrB3TzuW`.
- Work on branch `belt-and-sorter-tiers`.

---

## File structure

| File | Responsibility |
| --- | --- |
| `src/flab2bp/dsp/catalog.py` | `LogisticsTiers` record (next to `BeltAltitudeRules`). |
| `src/flab2bp/lab/techs.py` | `logistics_tiers_for_request`: which belts and sorters a request's save can build. |
| `src/flab2bp/spec.py` | `BeltTier`, `BuildSpec.belt_upgrades`, `BuildSpec.sorter_item_ids`, `belt_tiers`, `lane_capacity`. |
| `src/flab2bp/rates/candidates.py` | `_to_build_spec` fills the new fields. |
| `src/flab2bp/layout/strip_variants.py`, `src/flab2bp/layout/freeform.py` | Planner capacity checks use `lane_capacity`; sorter picking within `sorter_tiers`; retier hook. |
| `src/flab2bp/layout/validate.py` | `belt_run_demands` (public), `belt.tier_allowed`, `sorter.tier_allowed`. |
| `src/flab2bp/layout/belt_tiers.py` | `retier_belts(placement, spec)`: the post-routing pass. |
| `src/flab2bp/layout/base.py` | `PlacementStats.belt_runs_upgraded`, `belt_upgrade_tiers`. |
| `src/flab2bp/cli.py`, `src/flab2bp/web/payload.py`, `web/src/api/build.ts`, `web/src/ui/BuildReport.tsx` | Report the floor, ceiling and upgraded runs. |
| `tests/lab/test_techs.py`, `tests/test_spec.py`, `tests/rates/test_candidates.py`, `tests/layout/test_freeform.py`, `tests/layout/test_belt_tiers.py`, `tests/layout/test_validate.py`, `tests/web/test_payload.py`, `tests/test_pipeline.py` | Tests per task. |

---

### Task 1: Technology-derived logistics tiers

**Files:**
- Modify: `src/flab2bp/dsp/catalog.py` (insert after `BeltAltitudeRules`, ends at line 494)
- Modify: `src/flab2bp/lab/techs.py`
- Test: `tests/lab/test_techs.py`

**Interfaces:**
- Produces: `catalog.LogisticsTiers(belt_item_ids: tuple[str, ...], sorter_item_ids: tuple[str, ...], from_url: bool)`, frozen dataclass.
- Produces: `techs.logistics_tiers_for_request(request: LabRequest, dataset: Dataset) -> catalog.LogisticsTiers`. Belts are FactorioLab ids sorted by `dataset.belt_speed`, slowest first, never slower than the request's belt, always containing it. Sorters are FactorioLab ids sorted by `catalog.SORTER_RATE_AT_1[catalog.get_item_id(id)]`, never empty (`("sorter-1",)` fallback).

- [ ] **Step 1: Write the failing tests**

Append to `tests/lab/test_techs.py`:

```python
from flab2bp.lab import params as P
from flab2bp.lab.data import load_vendored_hash_index


def _url_with_techs(tech_ids: list[str], belt: str = "conveyor-belt-2") -> str:
    techs_table = load_vendored_hash_index().technologies
    tre = P.ZFIELDSEP.join(P.n_to_id(techs_table.index(t)) for t in tech_ids)
    return f"https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe={belt}&tre={tre}&v=11"


def test_no_technology_set_unlocks_every_belt_and_sorter_above_the_floor() -> None:
    data = load_vendored()
    request = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe=conveyor-belt-2&v=11")
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2", "conveyor-belt-3")
    assert tiers.sorter_item_ids == ("sorter-1", "sorter-2", "sorter-3", "sorter-4")
    assert tiers.from_url is False


def test_belt_one_floor_lists_every_belt() -> None:
    data = load_vendored()
    request = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-1", "conveyor-belt-2", "conveyor-belt-3")


def test_without_planetary_logistics_there_is_no_belt_three() -> None:
    data = load_vendored()
    request = parse_url(
        _url_with_techs(
            [
                "basic-logistics-system",
                "improved-logistics-system",
                "high-efficiency-logistics-system",
            ]
        )
    )
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2",)
    assert tiers.sorter_item_ids == ("sorter-1", "sorter-2", "sorter-3")
    assert tiers.from_url is True


def test_without_integrated_logistics_there_is_no_pile_sorter() -> None:
    data = load_vendored()
    request = parse_url(
        _url_with_techs(
            [
                "basic-logistics-system",
                "improved-logistics-system",
                "high-efficiency-logistics-system",
                "planetary-logistics-system",
            ]
        )
    )
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2", "conveyor-belt-3")
    assert "sorter-4" not in tiers.sorter_item_ids


def test_the_floor_is_present_even_when_unresearched() -> None:
    """FactorioLab's belt choice is authoritative, researched or not."""
    data = load_vendored()
    request = parse_url(_url_with_techs(["basic-logistics-system"], belt="conveyor-belt-3"))
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-3",)


def test_an_empty_technology_set_falls_back_to_sorter_one() -> None:
    data = load_vendored()
    request = parse_url(_url_with_techs([]))
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2",)
    assert tiers.sorter_item_ids == ("sorter-1",)
```

Note: `_url_with_techs([])` must produce a URL whose `tre` decodes to an explicit empty set. If `parse_url` reads an empty `tre=` as `None`, build the request with `dataclasses.replace(parse_url(url), researched_technology_ids=set())` instead; `LabRequest` is a frozen dataclass.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/lab/test_techs.py -q`
Expected: FAIL with `AttributeError: module 'flab2bp.lab.techs' has no attribute 'logistics_tiers_for_request'`

- [ ] **Step 3: Add `LogisticsTiers` to the catalog**

Use `insert_after_symbol` on `BeltAltitudeRules` in `src/flab2bp/dsp/catalog.py`:

```python


@dataclass(frozen=True, slots=True)
class LogisticsTiers:
    """Which belts and sorters a particular SAVE can build.

    Both come from the player's researched technologies, read from the
    dataset's ``recipeUnlock`` lists, so they are derived from the FactorioLab
    URL rather than defaulted or asked for on the command line -- the same
    rule as :class:`BeltAltitudeRules`.
    """

    #: FactorioLab belt item ids, slowest first.  Never empty and never
    #: slower than the URL's own belt, which is always a member: FactorioLab's
    #: choice is authoritative whether or not the technology set unlocks it.
    belt_item_ids: tuple[str, ...]
    #: FactorioLab sorter item ids, slowest first.  Never empty.
    sorter_item_ids: tuple[str, ...]
    #: False when the URL carried no technology set at all, in which case
    #: every technology is taken as researched -- FactorioLab's own default.
    from_url: bool
```

- [ ] **Step 4: Add the derivation to `lab/techs.py`**

Use `insert_after_symbol` on `belt_rules_for_url` in `src/flab2bp/lab/techs.py`, and add `from flab2bp.lab.url import LabRequest, parse_url` to the imports (replace the existing `from flab2bp.lab.url import parse_url` line) and extend `__all__` to `["belt_rules_for_url", "logistics_tiers_for_request"]`:

```python


def logistics_tiers_for_request(
    request: LabRequest, dataset: Dataset
) -> catalog.LogisticsTiers:
    """The belts and sorters this request's save can build.

    Data-driven: a belt or sorter is buildable when some researched
    technology item lists it in ``recipe_unlock``.  ``None`` for the
    researched set means every technology, as :func:`belt_rules_for_url`
    documents.  The request's own belt is always included, researched or not,
    because FactorioLab chose it and FactorioLab's choice is authoritative.

    A save whose explicit technology set unlocks no sorter at all gets
    ``("sorter-1",)``: it cannot build belts either, and refusing every build
    over it would help nobody.
    """
    technology_items = [item for item in dataset.items if item.technology is not None]
    researched = request.researched_technology_ids
    unlocked: set[str] = set()
    for item in technology_items:
        assert item.technology is not None
        if researched is None or item.id in researched:
            unlocked.update(item.technology.recipe_unlock)

    floor_id = request.belt_id or "conveyor-belt-1"
    floor_speed = dataset.belt_speed(floor_id)
    belts = {
        item.id
        for item in dataset.items
        if item.belt is not None
        and item.id in unlocked
        and item.belt.speed >= floor_speed
    }
    belts.add(floor_id)
    belt_item_ids = tuple(sorted(belts, key=lambda item_id: (dataset.belt_speed(item_id), item_id)))

    sorter_rates: dict[str, Fraction] = {}
    for item in dataset.items:
        numeric = catalog.get_item_id(item.id)
        if numeric in catalog.SORTER_RATE_AT_1 and item.id in unlocked:
            sorter_rates[item.id] = catalog.SORTER_RATE_AT_1[numeric]
    sorter_item_ids = tuple(sorted(sorter_rates, key=lambda item_id: (sorter_rates[item_id], item_id)))
    if not sorter_item_ids:
        sorter_item_ids = ("sorter-1",)

    return catalog.LogisticsTiers(
        belt_item_ids=belt_item_ids,
        sorter_item_ids=sorter_item_ids,
        from_url=researched is not None,
    )
```

Add `from fractions import Fraction` to the module imports.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/lab/test_techs.py -q`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/flab2bp/dsp/catalog.py src/flab2bp/lab/techs.py tests/lab/test_techs.py
uv run mypy src/flab2bp/dsp/catalog.py src/flab2bp/lab/techs.py
git add src/flab2bp/dsp/catalog.py src/flab2bp/lab/techs.py tests/lab/test_techs.py
git commit -m "feat(lab): derive buildable belt and sorter tiers from the URL's technologies"
```

---

### Task 2: `BuildSpec` carries the tiers

**Files:**
- Modify: `src/flab2bp/spec.py` (`BuildSpec` fields at lines 114-115; validators near line 142)
- Create: `tests/test_spec.py`

**Interfaces:**
- Produces: `spec.BeltTier(item_id: str, items_per_second: Fraction)` pydantic frozen model.
- Produces: `BuildSpec.belt_upgrades: tuple[BeltTier, ...] = ()`, `BuildSpec.sorter_item_ids: tuple[str, ...] = ("sorter-1", "sorter-2", "sorter-3", "sorter-4")`, property `BuildSpec.belt_tiers -> tuple[BeltTier, ...]` (floor first), property `BuildSpec.lane_capacity -> Fraction`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_spec.py`:

```python
"""The rates/geometry boundary's own invariants."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.spec import BeltTier, BuildSpec, MachineGroup


def _group() -> MachineGroup:
    return MachineGroup(
        recipe_id="magnetic-coil",
        machine_item_id="assembling-machine-2",
        count=1,
        inputs_per_machine={"copper-ingot": Fraction(1)},
        outputs_per_machine={"magnetic-coil": Fraction(1)},
    )


def test_no_upgrades_means_the_floor_is_the_ceiling() -> None:
    spec = BuildSpec(groups=(_group(),), belt_item_id="conveyor-belt-2", belt_items_per_second=Fraction(12))
    assert spec.belt_tiers == (BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),)
    assert spec.lane_capacity == Fraction(12)
    assert spec.sorter_item_ids == ("sorter-1", "sorter-2", "sorter-3", "sorter-4")


def test_upgrades_follow_the_floor_and_raise_the_capacity() -> None:
    spec = BuildSpec(
        groups=(_group(),),
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(
            BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),
            BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),
        ),
    )
    assert [tier.item_id for tier in spec.belt_tiers] == [
        "conveyor-belt-1",
        "conveyor-belt-2",
        "conveyor-belt-3",
    ]
    assert spec.lane_capacity == Fraction(30)


def test_an_upgrade_no_faster_than_the_floor_is_refused() -> None:
    with pytest.raises(ValueError, match="faster"):
        BuildSpec(
            groups=(_group(),),
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=Fraction(12),
            belt_upgrades=(BeltTier(item_id="conveyor-belt-1", items_per_second=Fraction(6)),),
        )


def test_upgrades_out_of_order_are_refused() -> None:
    with pytest.raises(ValueError, match="faster"):
        BuildSpec(
            groups=(_group(),),
            belt_upgrades=(
                BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),
                BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),
            ),
        )


def test_sorter_tiers_may_not_be_empty() -> None:
    with pytest.raises(ValueError, match="sorter"):
        BuildSpec(groups=(_group(),), sorter_item_ids=())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_spec.py -q`
Expected: FAIL with `ImportError: cannot import name 'BeltTier'`

- [ ] **Step 3: Add `BeltTier` and the fields**

Use `insert_before_symbol` on `MachineGroup` in `src/flab2bp/spec.py`:

```python
class BeltTier(_Frozen):
    """One belt the build may use, by FactorioLab id and throughput."""

    item_id: str
    items_per_second: Fraction = Field(gt=0)


```

Then with `replace_content` (literal) replace

```python
    belt_item_id: str = "conveyor-belt-1"
    belt_items_per_second: Fraction = Field(default=Fraction(6), gt=0)
```

with

```python
    #: The belt FactorioLab chose (``ibe``).  The FLOOR: no emitted belt is
    #: ever slower, and a run that fits it keeps it.
    belt_item_id: str = "conveyor-belt-1"
    belt_items_per_second: Fraction = Field(default=Fraction(6), gt=0)
    #: Faster belts the save can build, slowest first.  Empty means the floor
    #: is also the ceiling -- what every hand-built spec gets.  The layout
    #: sizes lanes against the fastest of these and raises a run to the
    #: cheapest one that carries its measured demand; see
    #: ``layout/belt_tiers.py``.
    belt_upgrades: tuple[BeltTier, ...] = ()
    #: Sorter tiers the save can build, slowest first.  Every tier by default
    #: so a spec built without a request keeps today's behaviour.
    sorter_item_ids: tuple[str, ...] = ("sorter-1", "sorter-2", "sorter-3", "sorter-4")
```

Then use `insert_before_symbol` on `BuildSpec/_no_dangling_demand` to add the validator:

```python
    @model_validator(mode="after")
    def _tiers_are_ordered(self) -> BuildSpec:
        previous = self.belt_items_per_second
        for tier in self.belt_upgrades:
            if tier.items_per_second <= previous:
                raise ValueError(
                    f"{self.label or 'spec'}: belt upgrade {tier.item_id!r} at "
                    f"{tier.items_per_second}/s is not faster than the tier before it "
                    f"({previous}/s); upgrades must be strictly faster than the floor "
                    "and listed slowest first"
                )
            previous = tier.items_per_second
        if not self.sorter_item_ids:
            raise ValueError(
                f"{self.label or 'spec'}: no sorter tier is allowed; a build with no "
                "sorter at all cannot feed a machine"
            )
        return self

```

And use `insert_after_symbol` on `BuildSpec/is_proliferated` to add the properties:

```python

    @property
    def belt_tiers(self) -> tuple[BeltTier, ...]:
        """Every belt the build may use, floor first."""
        floor = BeltTier(item_id=self.belt_item_id, items_per_second=self.belt_items_per_second)
        return (floor, *self.belt_upgrades)

    @property
    def lane_capacity(self) -> Fraction:
        """Items/second the fastest allowed belt sustains: the planner's bound."""
        return self.belt_tiers[-1].items_per_second
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_spec.py tests/rates -q`
Expected: PASS (the rates tests prove the defaults changed nothing)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/spec.py tests/test_spec.py
uv run mypy src/flab2bp/spec.py
git add src/flab2bp/spec.py tests/test_spec.py
git commit -m "feat(spec): carry the buildable belt and sorter tiers on BuildSpec"
```

---

### Task 3: `_to_build_spec` fills the tiers from the request

**Files:**
- Modify: `src/flab2bp/rates/candidates.py` (`_to_build_spec`, lines 143-199)
- Test: `tests/rates/test_candidates.py`

**Interfaces:**
- Consumes: `techs.logistics_tiers_for_request`, `BeltTier`, `BuildSpec.belt_upgrades`, `BuildSpec.sorter_item_ids`.
- Produces: every candidate spec (derived and flow-pinned) has `belt_upgrades` and `sorter_item_ids` set from the request.

- [ ] **Step 1: Write the failing test**

Append to `tests/rates/test_candidates.py` (the module already imports `parse_url`, `build_candidates` and `load_vendored`/`data` fixtures; reuse what it has):

```python
def test_candidates_carry_the_researched_belt_and_sorter_tiers() -> None:
    from fractions import Fraction

    data = load_vendored()
    specs = build_candidates(data, parse_url(EXAMPLE_URL)).candidates
    for spec in specs:
        assert spec.belt_item_id == "conveyor-belt-2"
        assert [tier.item_id for tier in spec.belt_upgrades] == ["conveyor-belt-3"]
        assert spec.belt_upgrades[0].items_per_second == Fraction(30)
        assert spec.lane_capacity == Fraction(30)
        assert spec.sorter_item_ids == ("sorter-1", "sorter-2", "sorter-3", "sorter-4")
```

If the module has no `load_vendored` import, add `from flab2bp.lab.data import load_vendored`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/rates/test_candidates.py -q -k researched_belt`
Expected: FAIL on `[tier.item_id for tier in spec.belt_upgrades] == ["conveyor-belt-3"]` (empty list)

- [ ] **Step 3: Fill the fields**

In `src/flab2bp/rates/candidates.py`, add the imports `from flab2bp.lab.techs import logistics_tiers_for_request` and `BeltTier` to the `from flab2bp.spec import (...)` block. Then with `replace_content` (literal) replace

```python
    belt_id = request.belt_id or "conveyor-belt-1"
    spec = BuildSpec(
        groups=tuple(groups),
        external_inputs=dict(solution.external_inputs),
        outputs=dict(solution.outputs),
        surplus_outputs=surplus_outputs,
        belt_item_id=belt_id,
        belt_items_per_second=data.belt_speed(belt_id),
```

with

```python
    belt_id = request.belt_id or "conveyor-belt-1"
    tiers = logistics_tiers_for_request(request, data)
    belt_upgrades = tuple(
        BeltTier(item_id=item_id, items_per_second=data.belt_speed(item_id))
        for item_id in tiers.belt_item_ids
        if item_id != belt_id
    )
    spec = BuildSpec(
        groups=tuple(groups),
        external_inputs=dict(solution.external_inputs),
        outputs=dict(solution.outputs),
        surplus_outputs=surplus_outputs,
        belt_item_id=belt_id,
        belt_items_per_second=data.belt_speed(belt_id),
        belt_upgrades=belt_upgrades,
        sorter_item_ids=tiers.sorter_item_ids,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rates tests/lab -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/rates/candidates.py tests/rates/test_candidates.py
uv run mypy src/flab2bp/rates/candidates.py
git add src/flab2bp/rates/candidates.py tests/rates/test_candidates.py
git commit -m "feat(rates): candidates carry the researched belt and sorter tiers"
```

---

### Task 4: The planner sizes lanes against the ceiling

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py` (lines 941, 989, 991, 1095)
- Modify: `src/flab2bp/layout/freeform.py` (`_check_shared_lane_capacity`, line 1867)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `BuildSpec.lane_capacity`.

- [ ] **Step 1: Write the failing test**

Append to `tests/layout/test_freeform.py` (it imports `freeform`, `F` as `Fraction`, and the spec types; add `from flab2bp.spec import BeltTier` if not present):

```python
def test_shared_lane_capacity_is_judged_against_the_fastest_allowed_belt() -> None:
    """Two ingredients at 8/s each cannot share a 12/s floor belt, but the
    save can build a 30/s belt and the retier pass will give the lane one."""
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": F(8), "iron-ingot": F(8)},
                outputs_per_machine={"magnetic-coil": F(1)},
            ),
        ),
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-3", items_per_second=F(30)),),
    )
    group = next(iter(freeform._adapt(spec).values()))
    freeform._check_shared_lane_capacity(group, (("copper-ingot", "iron-ingot"),), 1, spec)

    floor_only = spec.model_copy(update={"belt_upgrades": ()})
    group = next(iter(freeform._adapt(floor_only).values()))
    with pytest.raises(ValueError, match="cannot share a belt"):
        freeform._check_shared_lane_capacity(group, (("copper-ingot", "iron-ingot"),), 1, floor_only)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_freeform.py -q -k fastest_allowed_belt`
Expected: FAIL with `ValueError: ... cannot share a belt at this rate` on the first call

- [ ] **Step 3: Switch the four sites**

In `src/flab2bp/layout/freeform.py::_check_shared_lane_capacity`, `replace_content` (literal): `    cap = spec.belt_items_per_second` → `    cap = spec.lane_capacity`, and in its error message replace `over the {cap}/s a {spec.belt_item_id} sustains` with `over the {cap}/s the fastest belt this save can build sustains`.

In `src/flab2bp/layout/strip_variants.py`, `replace_content` with `allow_multiple_occurrences=True` in literal mode: `spec.belt_items_per_second` → `spec.lane_capacity`. Confirm afterwards with `find_referencing_symbols` that the file has no remaining reference to `belt_items_per_second`; there should be exactly four replacements (lines 941, 989, 991, 1095).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/test_strip_variants.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): size shared and merged lanes against the fastest allowed belt"
```

---

### Task 5: Sorter picking stays within the researched tiers

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`: `_Canvas` (line 4064), `_PreparedRoutingProblem` (line 6722, `new_workspace`), `_prepare_routing_problem` (line 12843 and the `return _PreparedRoutingProblem(` at line 13563), `_pick_sorter` (line 4323) and its callers `_flank_lane` (line 5000), `_link_lane` (line 5265), `_bridge` (line 14124)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: `_pick_sorter(rate: Fraction, span: int, machines: int, tiers: tuple[int, ...] = catalog.SORTER_TIERS) -> tuple[int, int]`; `_Canvas.sorter_tiers: tuple[int, ...]`; `_PreparedRoutingProblem.sorter_tiers: tuple[int, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_freeform.py`:

```python
def test_pick_sorter_never_leaves_the_allowed_tiers() -> None:
    tier, _ = freeform._pick_sorter(F(10), 1, 1, tiers=(2011, 2012, 2013))
    assert tier == 2013, "the fastest ALLOWED tier, not the Pile Sorter"
    tier, _ = freeform._pick_sorter(F(10), 1, 1, tiers=(2011, 2012, 2013, 2014))
    assert tier == 2014
    tier, _ = freeform._pick_sorter(F(1), 1, 1, tiers=(2012, 2013))
    assert tier == 2012, "the cheapest allowed tier that carries the rate"


def test_sorter_tiers_for_spec_maps_ids_and_keeps_catalog_order() -> None:
    spec = single_recipe_spec().model_copy(update={"sorter_item_ids": ("sorter-2", "sorter-1")})
    assert freeform._sorter_tiers_for(spec) == (2011, 2012)
    assert freeform._sorter_tiers_for(single_recipe_spec()) == catalog.SORTER_TIERS


def test_prepared_problem_hands_the_spec_sorter_tiers_to_the_workspace() -> None:
    """A spec that allows only Mk.I and Mk.II sorters must be routed with only
    those, so the workspace canvas has to know."""
    # The smallest real one: every field has a default except the geometry
    # tuples, which may be empty.
    prepared = freeform._PreparedRoutingProblem(
        building_templates=(),
        blocked=(),
        solid=frozenset(),
        reserved=(),
        port_corridors=(),
        keep_out=frozenset(),
        guard=frozenset(),
        nets=(),
        core=(0, 0, 0, 0),
        route_bounds=(0, 0, 0, 0),
        limit=None,
        power_sites=(),
        sorters=0,
        coaters=0,
        direct_inserts=0,
        sorter_tiers=(2011, 2012),
    )
    assert prepared.new_workspace().canvas.sorter_tiers == (2011, 2012)
```

If `_PreparedRoutingProblem` has required fields beyond those listed (check with `find_symbol` depth 1), pass empty tuples or zeros for them too.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "pick_sorter_never or carries_the_spec_sorter"`
Expected: FAIL with `TypeError: _pick_sorter() got an unexpected keyword argument 'tiers'`

- [ ] **Step 3: Thread the tiers**

Replace the body of `_pick_sorter` (`replace_symbol_body`):

```python
def _pick_sorter(
    rate: Fraction,
    span: int,
    machines: int,
    tiers: tuple[int, ...] = catalog.SORTER_TIERS,
) -> tuple[int, int]:
    """Cheapest allowed sorter tier and count carrying ``rate`` across ``span``.

    Reach is three tiles for every tier, so tiers differ only in throughput --
    there is never a reason to pay for a higher tier than the rate needs.
    ``tiers`` is what the save can build, slowest first; when none carries the
    rate the fastest allowed one is returned and ``flow.sorter_capacity``
    refuses the placement, rather than emitting a tier the save cannot build.
    """
    per_machine = rate / machines if machines else rate
    for tier in tiers:
        if catalog.sorter_rate(tier, span) >= per_machine:
            return tier, machines
    return tiers[-1], machines
```

In `_Canvas`, `insert` after the `ramped: bool = False` field (use `replace_content`, literal, on `    ramped: bool = False\n\n    buildings: list[PlacedBuilding]` → add between them):

```python
    ramped: bool = False
    #: Sorter tiers this save can build, slowest first.  Every sorter the
    #: emitter picks comes from this tuple; see :func:`_pick_sorter`.
    sorter_tiers: tuple[int, ...] = catalog.SORTER_TIERS

    buildings: list[PlacedBuilding]
```

In `_PreparedRoutingProblem`, after `external_output_nets: tuple[_PreparedNet, ...] = ()` add `sorter_tiers: tuple[int, ...] = catalog.SORTER_TIERS`, and in `new_workspace` add `sorter_tiers=self.sorter_tiers,` after `ramped=self.ramped,`.

Add a helper with `insert_before_symbol` on `_pick_sorter`:

```python
def _sorter_tiers_for(spec: BuildSpec) -> tuple[int, ...]:
    """The spec's allowed sorter tiers as catalog ids, slowest first.

    Catalog order rather than spec order, so the picker's "cheapest first"
    walk holds whatever order the spec listed them in.  A spec naming no
    sorter the catalog knows falls back to every tier: an unknown id is a
    dataset mismatch, not a save that can build nothing.
    """
    allowed = {catalog.get_item_id(item_id) for item_id in spec.sorter_item_ids}
    return tuple(tier for tier in catalog.SORTER_TIERS if tier in allowed) or catalog.SORTER_TIERS


```

In `_prepare_routing_problem`, replace `    canvas = _Canvas(ramped=ramped)` with `    canvas = _Canvas(ramped=ramped, sorter_tiers=_sorter_tiers_for(spec))`.

and in the `return _PreparedRoutingProblem(` call add `sorter_tiers=canvas.sorter_tiers,` next to `ramped=canvas.ramped,`.

The three callers pass the canvas tiers:
- `_flank_lane`: `tier, _count = _pick_sorter(rate, got.span, 1, canvas.sorter_tiers)`
- `_link_lane`: `tier, _count = _pick_sorter(rate, planned.span, 1, canvas.sorter_tiers)`
- `_bridge`: `tier, _ = _pick_sorter(rates.get(item, Fraction(1)), span, 1, canvas.sorter_tiers)`

Check with `find_referencing_symbols` on `_pick_sorter` that those are the only callers.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): pick sorters only from the tiers the save can build"
```

---

### Task 6: The retier pass

**Files:**
- Modify: `src/flab2bp/layout/validate.py` (add `belt_run_demands` after `id_map`, line 5610)
- Modify: `src/flab2bp/layout/base.py` (`PlacementStats`, line 198)
- Create: `src/flab2bp/layout/belt_tiers.py`
- Create: `tests/layout/test_belt_tiers.py`

**Interfaces:**
- Produces: `validate.belt_run_demands(placement: Placement, spec: BuildSpec) -> tuple[tuple[BeltRun, ...], dict[int, dict[str | None, Fraction]]]`.
- Produces: `belt_tiers.retier_belts(placement: Placement, spec: BuildSpec) -> Placement`.
- Produces: `PlacementStats.belt_runs_upgraded: float`, `PlacementStats.belt_upgrade_tiers: list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/layout/test_belt_tiers.py`:

```python
"""The post-routing pass that gives each belt run the cheapest tier it needs."""

from __future__ import annotations

from fractions import Fraction

from flab2bp.layout.belt_tiers import retier_belts
from flab2bp.layout.validate import IdMap, validate
from flab2bp.spec import BeltTier, BuildSpec, MachineGroup
from tests.layout.test_validate import (
    ASSEMBLER,
    BELT2,
    PILE,
    belt,
    fired,
    machine,
    place,
    sorter,
    splitter,
)

BELT1 = 2001
BELT3 = 2003
IDS = IdMap(recipes={"magnetic-coil": 6}, items={"assembling-machine-2": ASSEMBLER})


def _spec(rate: Fraction, *upgrades: tuple[str, int]) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": rate},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        belt_upgrades=tuple(
            BeltTier(item_id=item_id, items_per_second=Fraction(speed)) for item_id, speed in upgrades
        ),
    )


def _fed_machine():
    # belt(2,0) -> belt(3,0) -> pile sorter -> assembler at (4,0)
    return place(
        belt(2, 0, out=1),
        belt(3, 0),
        machine(4, 0, recipe_id=6),
        sorter(3, 0, 4, 0, inp=1, out=2, item_id=PILE),
    )


def _tiers(placement) -> list[int]:
    return [b.item_id for b in placement.buildings if b.item_id in (BELT1, BELT2, BELT3)]


def test_a_run_within_the_floor_keeps_the_floor() -> None:
    out = retier_belts(_fed_machine(), _spec(Fraction(5), ("conveyor-belt-3", 30)))
    assert _tiers(out) == [BELT2, BELT2]
    assert out.stats["belt_runs_upgraded"] == 0.0


def test_a_run_over_the_floor_takes_the_cheapest_upgrade_that_fits() -> None:
    out = retier_belts(_fed_machine(), _spec(Fraction(14), ("conveyor-belt-3", 30)))
    assert _tiers(out) == [BELT3, BELT3]
    assert out.stats["belt_runs_upgraded"] == 1.0
    assert out.stats["belt_upgrade_tiers"] == ["conveyor-belt-3"]
    assert not fired(validate(out, _spec(Fraction(14), ("conveyor-belt-3", 30)), ids=IDS), "flow.belt_capacity")


def test_model_index_follows_the_tier() -> None:
    out = retier_belts(_fed_machine(), _spec(Fraction(14), ("conveyor-belt-3", 30)))
    assert {b.model_index for b in out.buildings if b.item_id == BELT3} == {37}


def test_a_run_over_the_ceiling_is_set_to_the_ceiling_and_still_refused() -> None:
    spec = _spec(Fraction(40), ("conveyor-belt-3", 30))
    out = retier_belts(_fed_machine(), spec)
    assert _tiers(out) == [BELT3, BELT3]
    assert fired(validate(out, spec, ids=IDS), "flow.belt_capacity")


def test_no_upgrades_leaves_the_placement_untouched() -> None:
    placement = _fed_machine()
    out = retier_belts(placement, _spec(Fraction(14)))
    assert out.buildings == placement.buildings


def test_a_trunk_feeding_two_branches_is_tiered_on_the_sum() -> None:
    """Two machines at 8/s each draw 16/s through the trunk into the splitter,
    so the trunk needs Mk.III while each branch fits Mk.II."""
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=2,
                inputs_per_machine={"copper-ingot": Fraction(8)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),),
    )
    placement = place(
        belt(0, 0, out=1),  # 0 trunk
        belt(1, 0, out=2),  # 1 trunk, feeds the splitter
        splitter(2, 0),  # 2
        belt(3, 0, inp=2, out=4),  # 3 branch north
        belt(4, 0),  # 4
        belt(2, 1, inp=2, out=6),  # 5 branch south
        belt(2, 2),  # 6
        machine(5, 0, recipe_id=6),  # 7
        machine(2, 3, recipe_id=6),  # 8
        sorter(4, 0, 5, 0, inp=4, out=7, item_id=PILE),  # 9
        sorter(2, 2, 2, 3, inp=6, out=8, item_id=PILE),  # 10
    )
    out = retier_belts(placement, spec)
    by_index = {i: b.item_id for i, b in enumerate(out.buildings)}
    assert by_index[0] == BELT3 and by_index[1] == BELT3
    assert by_index[3] == BELT2 and by_index[4] == BELT2
    assert by_index[5] == BELT2 and by_index[6] == BELT2
```

The splitter fixture geometry follows the junction convention in `tests/layout/test_validate.py` (belts feeding a splitter name it as `out`, belts drawing from it name it as `inp`). If `junction.make_splitter` needs different coordinates for the port poses to validate, copy the coordinates from an existing splitter test in `test_validate.py` (search `def test_flow_belt_capacity` and the junction-aware throughput section near line 3614); the retier assertions do not depend on the validator accepting the fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_belt_tiers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'flab2bp.layout.belt_tiers'`

- [ ] **Step 3: Expose the run demands from the validator**

Use `insert_after_symbol` on `id_map` in `src/flab2bp/layout/validate.py`:

```python


def belt_run_demands(
    placement: Placement, spec: BuildSpec
) -> tuple[tuple[BeltRun, ...], dict[int, dict[str | None, Fraction]]]:
    """Each belt run and the items/second it must carry, by item.

    The same runs ``_build_runs`` chains and the same demand ``_run_demand``
    computes for ``flow.belt_capacity`` -- exposed so the belt-tier pass in
    ``layout/belt_tiers.py`` and the judge can never disagree about what a run
    carries.  Runs no checks.  When a machine cannot be resolved to a spec
    group the demand is empty: the flow is unknowable, and
    ``machine.group_resolved`` reports the placement anyway.
    """
    ctx = _context(
        placement, spec, id_map(spec), 256, cat.DEFAULT_MAX_BELT_Z, True
    )
    if ctx.unresolved_machines():
        return ctx.runs, {}
    return ctx.runs, _run_demand(ctx)
```

- [ ] **Step 4: Add the stats keys**

In `src/flab2bp/layout/base.py::PlacementStats`, insert in alphabetical position (after `belt_tiles: float`): `belt_runs_upgraded: float` and `belt_upgrade_tiers: list[str]`. Keep the TypedDict's alphabetical order.

- [ ] **Step 5: Write the pass**

Create `src/flab2bp/layout/belt_tiers.py`:

```python
"""Give each belt run the cheapest belt tier that carries what it measures.

The URL's belt is the floor and the fastest researched belt is the ceiling
(``BuildSpec.belt_tiers``).  Routing lays every belt at the floor; this pass
runs once on the emitted placement, measures every run with the validator's
own flow propagation, and raises a run to the cheapest tier that fits.  Runs
that fit the floor keep it, so faster belts appear only where a lane needs
them.  A run above the ceiling is set to the ceiling and left for
``flow.belt_capacity`` to refuse: splitting such a lane is the subject of the
multiple-belts design, not this pass.

Nothing here touches geometry.  Belt tiers share footprint, slope and
altitude rules, so the router has no reason to know the tier and the pass has
no reason to move anything.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout.base import Placement
from flab2bp.layout.validate import belt_run_demands
from flab2bp.spec import BuildSpec

__all__ = ["retier_belts"]


def retier_belts(placement: Placement, spec: BuildSpec) -> Placement:
    """Return ``placement`` with every belt run on the cheapest tier that fits."""
    tiers = [
        (catalog.get_item_id(tier.item_id), tier.item_id, tier.items_per_second)
        for tier in spec.belt_tiers
    ]
    if len(tiers) < 2:
        return placement
    floor_numeric = tiers[0][0]
    if floor_numeric is None:
        return placement

    runs, demands = belt_run_demands(placement, spec)
    buildings = list(placement.buildings)
    upgraded = 0
    used: set[str] = set()
    for index, run in enumerate(runs):
        demand = sum(demands.get(index, {}).values(), Fraction(0))
        chosen_numeric, chosen_id = floor_numeric, tiers[0][1]
        for numeric, item_id, speed in tiers:
            if numeric is None:
                continue
            chosen_numeric, chosen_id = numeric, item_id
            if speed >= demand:
                break
        if chosen_numeric == floor_numeric:
            continue
        model_index = catalog.building(chosen_numeric).model_index
        for i in run.indices:
            buildings[i] = dataclasses.replace(
                buildings[i], item_id=chosen_numeric, model_index=model_index
            )
        upgraded += 1
        used.add(chosen_id)

    stats = dict(placement.stats)
    stats["belt_runs_upgraded"] = float(upgraded)
    stats["belt_upgrade_tiers"] = sorted(used)
    return dataclasses.replace(placement, buildings=tuple(buildings), stats=stats)  # type: ignore[arg-type]
```

If mypy rejects the `stats` assignment, build it as `PlacementStats` (`from flab2bp.layout.base import PlacementStats`; `stats: PlacementStats = {**placement.stats, "belt_runs_upgraded": float(upgraded), "belt_upgrade_tiers": sorted(used)}`) and drop the ignore.

Note: every belt in a run is at the floor when the pass runs, so the loop that reads `floor_numeric` only from the spec is right; the pass does not need to read tiles' current tiers.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_belt_tiers.py tests/layout/test_validate.py -q`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/belt_tiers.py src/flab2bp/layout/validate.py src/flab2bp/layout/base.py tests/layout/test_belt_tiers.py
uv run mypy src/flab2bp/layout/belt_tiers.py src/flab2bp/layout/validate.py src/flab2bp/layout/base.py
git add src/flab2bp/layout/belt_tiers.py src/flab2bp/layout/validate.py src/flab2bp/layout/base.py tests/layout/test_belt_tiers.py
git commit -m "feat(layout): retier each belt run to the cheapest belt that carries it"
```

---

### Task 7: Hook the pass into the shared emitter

**Files:**
- Modify: `src/flab2bp/layout/freeform.py::_build_prepared` (the `placement = Placement(` block near line 14055)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `belt_tiers.retier_belts`.

- [ ] **Step 1: Write the failing test**

Append to `tests/layout/test_freeform.py`, next to the existing end-to-end `FreeformLayout.lay_out` tests (use the same small spec helper they use, and the same `band_policy`/budget arguments):

```python
def test_lay_out_raises_a_lane_that_needs_a_faster_belt() -> None:
    """One machine drawing 14/s on a Mk.II floor: the input lane must come out
    as Mk.III, everything else may stay Mk.II, and the result validates."""
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": F(14)},
                outputs_per_machine={"magnetic-coil": F(1)},
            ),
        ),
        external_inputs={"copper-ingot": F(14)},
        outputs={"magnetic-coil": F(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-3", items_per_second=F(30)),),
    )
    layout = FreeformLayout(band_policy=BandPolicy("portable"), workers=1)
    placement = layout.lay_out(spec, time_budget_s=15.0)
    tiers = {b.item_id for b in placement.buildings if catalog.is_belt(b.item_id)}
    assert 2003 in tiers
    assert placement.stats["belt_runs_upgraded"] >= 1
    assert validate.certify(placement, spec, expect_power=True).ok
```

`FreeformLayout`, `BandPolicy`, `catalog` and `validate` are already imported at the top of `tests/layout/test_freeform.py`; `lay_out(spec, *, time_budget_s: float)` is its real signature. Spec fragments in this file (see `single_recipe_spec` at line 172) show how a complete small spec with `external_inputs` and `outputs` is written; mirror that if the one above trips `_no_dangling_demand`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_freeform.py -q -k needs_a_faster_belt`
Expected: FAIL: `NoValidLayout` mentioning `flow.belt_capacity`, or `2003 in tiers` false

- [ ] **Step 3: Call the pass**

In `_build_prepared`, `replace_content` (literal) the `    return _BuildResult(\n        placement=placement,` that follows the `placement = Placement(` block with:

```python
    placement = retier_belts(placement, spec)
    return _BuildResult(
        placement=placement,
```

and add `from flab2bp.layout.belt_tiers import retier_belts` to the module imports (freeform already imports `validate`, so there is no cycle).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): retier belt runs on every emitted placement"
```

---

### Task 8: Validator checks for the researched set

**Files:**
- Modify: `src/flab2bp/layout/validate.py` (add after `_sorter_capacity`, line 5144)
- Test: `tests/layout/test_validate.py`

**Interfaces:**
- Produces: checks `belt.tier_allowed` and `sorter.tier_allowed`, both `needs_spec=True`, `Severity.ERROR`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_validate.py` (after the throughput section):

```python
# --- researched tiers -------------------------------------------------------


def _tiered_spec(*upgrades: str) -> BuildSpec:
    from flab2bp.spec import BeltTier

    speeds = {"conveyor-belt-3": Fraction(30)}
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": Fraction(1)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        belt_upgrades=tuple(BeltTier(item_id=u, items_per_second=speeds[u]) for u in upgrades),
        sorter_item_ids=("sorter-1", "sorter-2", "sorter-3"),
    )


def test_belt_tier_allowed_fires_on_a_belt_the_save_cannot_build() -> None:
    p = place(belt(3, 0, item_id=2003), machine(4, 0, recipe_id=6), sorter(3, 0, 4, 0, inp=0, out=1))
    r = validate(p, _tiered_spec(), ids=TWO_INPUT_IDS)
    assert fired(r, "belt.tier_allowed")


def test_belt_tier_allowed_clean_inside_the_researched_set() -> None:
    p = place(belt(3, 0, item_id=2003), machine(4, 0, recipe_id=6), sorter(3, 0, 4, 0, inp=0, out=1))
    r = validate(p, _tiered_spec("conveyor-belt-3"), ids=TWO_INPUT_IDS)
    assert not fired(r, "belt.tier_allowed")


def test_belt_tier_allowed_fires_below_the_floor_too() -> None:
    p = place(belt(3, 0, item_id=2001), machine(4, 0, recipe_id=6), sorter(3, 0, 4, 0, inp=0, out=1))
    r = validate(p, _tiered_spec("conveyor-belt-3"), ids=TWO_INPUT_IDS)
    assert fired(r, "belt.tier_allowed")


def test_sorter_tier_allowed_fires_on_a_pile_sorter_the_save_cannot_build() -> None:
    p = place(belt(3, 0), machine(4, 0, recipe_id=6), sorter(3, 0, 4, 0, inp=0, out=1, item_id=PILE))
    r = validate(p, _tiered_spec(), ids=TWO_INPUT_IDS)
    assert fired(r, "sorter.tier_allowed")


def test_sorter_tier_allowed_clean_inside_the_researched_set() -> None:
    p = place(belt(3, 0), machine(4, 0, recipe_id=6), sorter(3, 0, 4, 0, inp=0, out=1, item_id=SORTER3))
    r = validate(p, _tiered_spec(), ids=TWO_INPUT_IDS)
    assert not fired(r, "sorter.tier_allowed")
```

`PILE` is defined later in the file (line 2776); place these tests after that definition or move the constant up.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_validate.py -q -k tier_allowed`
Expected: FAIL on the `fired(...)` assertions (unknown check never fires)

- [ ] **Step 3: Add the checks**

Use `insert_after_symbol` on `_sorter_capacity` in `src/flab2bp/layout/validate.py`:

```python


@check("belt.tier_allowed", needs_spec=True)
def _belt_tier_allowed(ctx: Context) -> Iterable[Finding]:
    """Every belt is one the save can build: the URL's belt or a researched upgrade.

    The floor is FactorioLab's choice and the ceiling is the technology set,
    both carried on the spec; a tile outside that set pastes in the game and
    then cannot be built by the player.  Below the floor is reported too --
    nothing emits a slower belt on purpose, so one is a defect.
    """
    assert ctx.spec is not None
    allowed = {
        numeric
        for tier in ctx.spec.belt_tiers
        if (numeric := cat.get_item_id(tier.item_id)) is not None
    }
    names = [tier.item_id for tier in ctx.spec.belt_tiers]
    for ridx, run in enumerate(ctx.runs):
        if run.tier_item_id in allowed:
            continue
        yield Finding(
            "belt.tier_allowed",
            Severity.ERROR,
            f"belt run {ridx} is tier {run.tier_item_id}, which this save cannot "
            f"build; allowed: {', '.join(names)}",
            run.indices,
            {"run": ridx, "tier": run.tier_item_id, "allowed": names},
        )


@check("sorter.tier_allowed", needs_spec=True)
def _sorter_tier_allowed(ctx: Context) -> Iterable[Finding]:
    """Every sorter is a tier the save has researched."""
    assert ctx.spec is not None
    allowed = {
        numeric
        for item_id in ctx.spec.sorter_item_ids
        if (numeric := cat.get_item_id(item_id)) is not None
    }
    for i, s in ctx.of_kind(Kind.SORTER):
        if s.item_id in allowed:
            continue
        yield Finding(
            "sorter.tier_allowed",
            Severity.ERROR,
            f"sorter {i} is tier {s.item_id}, which this save cannot build; "
            f"allowed: {', '.join(ctx.spec.sorter_item_ids)}",
            (i,),
            {"sorter": i, "tier": s.item_id, "allowed": list(ctx.spec.sorter_item_ids)},
        )
```

`_build_runs` records a run's tier from its first tile; a run whose tiles disagree is not something the emitter produces, and `belt.tier_allowed` judging the head is consistent with `flow.belt_capacity`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_validate.py -q`
Expected: PASS. If a rules ledger test enumerates check ids (`tests/rules/test_paste_rules.py` or `docs/RULE_LEDGER.md`), add the two ids where that test says to.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/validate.py tests/layout/test_validate.py
uv run mypy src/flab2bp/layout/validate.py
git add src/flab2bp/layout/validate.py tests/layout/test_validate.py docs/RULE_LEDGER.md
git commit -m "feat(validate): refuse belt and sorter tiers the save cannot build"
```

---

### Task 9: Report the tiers

**Files:**
- Modify: `src/flab2bp/cli.py` (the report function, after the `rules = build.belt_rules` block near line 72)
- Modify: `src/flab2bp/web/payload.py` (`_attempt_detail`, `describe`)
- Modify: `web/src/api/build.ts` (line 109-139), `web/src/ui/BuildReport.tsx` (the `<dl>` near line 110)
- Test: `tests/web/test_payload.py`

**Interfaces:**
- Produces: payload key `belt_tiers` on the build and on each attempt detail: `{"floor": str, "ceiling": str, "runs_upgraded": int, "upgrade_tiers": list[str]}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_payload.py`:

```python
def test_belt_tiers_travel_on_the_build_and_each_attempt(small_build: pipeline.Build) -> None:
    body = describe(small_build)
    tiers = body["belt_tiers"]
    assert isinstance(tiers, dict)
    assert set(tiers) == {"floor", "ceiling", "runs_upgraded", "upgrade_tiers"}
    assert tiers["floor"] == small_build.spec.belt_item_id
    assert tiers["ceiling"] == small_build.spec.belt_tiers[-1].item_id
    attempts = body["attempts"]
    assert isinstance(attempts, list)
    attempt = attempts[0]
    assert isinstance(attempt, dict)
    detail = attempt["detail"]
    assert isinstance(detail, dict)
    assert set(detail["belt_tiers"]) == {"floor", "ceiling", "runs_upgraded", "upgrade_tiers"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/web/test_payload.py -q -k belt_tiers_travel`
Expected: FAIL with `KeyError: 'belt_tiers'`

- [ ] **Step 3: Add the payload block**

In `src/flab2bp/web/payload.py` add a helper before `_attempt_detail` (`insert_before_symbol`):

```python
def _belt_tiers(spec: BuildSpec, placement: Placement) -> Json:
    """The floor FactorioLab chose, the ceiling the save allows, and what was raised."""
    tiers = spec.belt_tiers
    upgraded = placement.stats.get("belt_upgrade_tiers", [])
    return {
        "floor": tiers[0].item_id,
        "ceiling": tiers[-1].item_id,
        "runs_upgraded": int(placement.stats.get("belt_runs_upgraded", 0)),
        "upgrade_tiers": _array(sorted(upgraded)),
    }
```

with `from flab2bp.spec import BuildSpec` and `from flab2bp.layout.base import Placement` imported (check what the module already imports). Add `"belt_tiers": _belt_tiers(spec, attempt.placement),` to the dict `_attempt_detail` returns (after `"unmarked_inputs"`), and `"belt_tiers": _belt_tiers(build.spec, build.placement),` to `describe`'s dict after `"belt_rules": belt,`.

- [ ] **Step 4: Print it in the CLI**

In `src/flab2bp/cli.py`, after the `rules = build.belt_rules` / `if rules is not None:` block and before `if build.refused:`, insert:

```python
    tiers = build.spec.belt_tiers
    floor = tiers[0]
    if len(tiers) == 1:
        print(
            f"  belts: {floor.item_id} ({float(floor.items_per_second)}/s); the URL's "
            f"technologies unlock nothing faster, so a lane over that rate is refused",
            file=out,
        )
    else:
        ceiling = tiers[-1]
        raised = int(build.placement.stats.get("belt_runs_upgraded", 0))
        used = ", ".join(build.placement.stats.get("belt_upgrade_tiers", [])) or "none"
        print(
            f"  belts: {floor.item_id} ({float(floor.items_per_second)}/s) floor, "
            f"{ceiling.item_id} ({float(ceiling.items_per_second)}/s) ceiling; "
            f"{raised} run(s) raised to {used}",
            file=out,
        )
```

- [ ] **Step 5: Show it in the web report**

In `web/src/api/build.ts` add next to `BeltRules`:

```ts
const BeltTiers = z.object({
  floor: z.string(),
  ceiling: z.string(),
  runs_upgraded: z.number(),
  upgrade_tiers: z.array(z.string()),
});
```

add `belt_tiers: BeltTiers,` to `BuildResult` after `belt_rules` (line 135), and `belt_tiers: BeltTiers,` to `AttemptDetail` (line 83) after its `unmarked_inputs` (line 92). In `web/src/ui/BuildReport.tsx`, after the `Belt in` `<dd>` add:

```tsx
        <dt>Belts</dt>
        <dd>
          {shown.belt_tiers.floor}
          {shown.belt_tiers.ceiling !== shown.belt_tiers.floor
            ? `, ${shown.belt_tiers.runs_upgraded} run(s) raised to ${
                shown.belt_tiers.upgrade_tiers.join(', ') || 'nothing'
              } (ceiling ${shown.belt_tiers.ceiling})`
            : ' (the URL unlocks nothing faster)'}
        </dd>
```

`shown` is the attempt detail or the build result; both carry `belt_tiers` after Step 3.

- [ ] **Step 6: Run the tests and the web build**

Run: `uv run pytest tests/web tests/test_pipeline_cli_strategy.py -q`
Expected: PASS
Run: `cd web && bun run build && bun test 2>/dev/null; cd ..` (if `bun` is present; otherwise note it in the commit message)
Expected: build succeeds

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/flab2bp/cli.py src/flab2bp/web/payload.py tests/web/test_payload.py
uv run mypy src/flab2bp/cli.py src/flab2bp/web/payload.py
git add src/flab2bp/cli.py src/flab2bp/web/payload.py web/src/api/build.ts web/src/ui/BuildReport.tsx tests/web/test_payload.py
git commit -m "feat(report): say which belt tiers a build used and why"
```

---

### Task 10: End to end on the reported URL, and the corpus gate

**Files:**
- Test: `tests/test_pipeline.py`
- Create: `docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/gate.md` plus the JSONL files
- Modify: `README.md` (the "What it builds" paragraph), `docs/superpowers/specs/2026-09-02-belt-and-sorter-tiers-design.md` (status line)

- [ ] **Step 1: Write the failing end-to-end test**

Append to `tests/test_pipeline.py`:

```python
DEUTERON_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNzD0LwjAYBOB.k-GmJGKd3uWCuokVFLNaO2gthfqBOry"
    ".XSrGdHvu4K6TCOet6YQVnLWAG3weOWbP4O2.JybJOxSjqU--ZbKCnya.8pIc3n.hjeKr06GWYPr6KWtEHNHgDq7"
    "ALbgHG-UFvCIsNCwRSg0b07a9RKXOtTQPce4DLu01vA__&v=11"
)


def _with_belt(monkeypatch: pytest.MonkeyPatch, belt_id: str) -> None:
    original = pipeline.parse_url

    def patched(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return dataclasses.replace(original(url, **kwargs), belt_id=belt_id)

    monkeypatch.setattr(pipeline, "parse_url", patched)


@pytest.mark.slow
def test_a_mk2_url_whose_lanes_need_mk3_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reported failure: hydrogen lanes at 14-20/s on a 12/s belt.  With
    Mk.III researched, those runs are raised and the build validates."""
    _with_belt(monkeypatch, "conveyor-belt-2")
    build = pipeline.build(DEUTERON_URL, strategy="sequence-pair", time_budget_s=30.0)
    assert build.report.ok
    assert build.spec.belt_item_id == "conveyor-belt-2"
    tiers = {b.item_id for b in build.placement.buildings if catalog.is_belt(b.item_id)}
    assert 2003 in tiers, "some run needed Mk.III"
    assert 2002 in tiers, "runs within the floor keep the URL's belt"
    assert build.placement.stats["belt_runs_upgraded"] >= 1


@pytest.mark.slow
def test_without_planetary_logistics_the_same_url_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.lab import params as P
    from flab2bp.lab.data import load_vendored_hash_index

    techs_table = load_vendored_hash_index().technologies
    wanted = [
        "basic-logistics-system",
        "improved-logistics-system",
        "high-efficiency-logistics-system",
    ]
    original = pipeline.parse_url

    def patched(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return dataclasses.replace(
            original(url, **kwargs),
            belt_id="conveyor-belt-2",
            researched_technology_ids=set(wanted),
        )

    monkeypatch.setattr(pipeline, "parse_url", patched)
    with pytest.raises(pipeline.NoValidLayout, match="flow.belt_capacity"):
        pipeline.build(DEUTERON_URL, strategy="sequence-pair", time_budget_s=30.0)
```

Add `import dataclasses` and `from flab2bp.dsp import catalog` to the test module imports if absent. Note: a technology set that small also removes vertical construction and lowers the belt ceiling; if the refusal comes from a different check first, add `"vertical-construction-1"` through `"vertical-construction-6"` to `wanted` so only the belt tier differs. `NoValidLayout` lives in `flab2bp.layout.base`; import it from there if `pipeline` does not re-export it.

- [ ] **Step 2: Run the tests to verify the first fails and the second passes**

Run: `uv run pytest tests/test_pipeline.py -q -k "mk2_url or planetary_logistics"`
Expected before Tasks 1-9: first FAIL (NoValidLayout), second PASS. After Tasks 1-9: both PASS. Run it now to confirm both PASS.

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 4: Run the corpus gate**

Run the baseline from `master` in a separate worktree so the branch is never checked out over:

```bash
mkdir -p docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers
git worktree add /tmp/flab2bp-baseline master
(cd /tmp/flab2bp-baseline && uv sync -q && uv run python scripts/audit.py --budget 30 --jobs 16 --json /home/dannyb/sources/factorio-lab-to-blueprint/docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/baseline-budget30.jsonl | tail -4)
uv run python scripts/audit.py --budget 30 --jobs 16 --json docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/candidate-budget30.jsonl | tail -4
uv run python scripts/audit_compare.py docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/baseline-budget30.jsonl docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/candidate-budget30.jsonl
git worktree remove /tmp/flab2bp-baseline
```

Write `docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/gate.md` with the commit under test, the baseline commit, the clean/refused/invalid counts of both runs and the `audit_compare` output verbatim. The pass must not cost a cell: any cell clean in the baseline and not clean in the candidate is a defect to fix before finishing.

- [ ] **Step 5: Update the docs**

In `README.md`, in the "What it builds" paragraph, after "no belt lane carries more than its tier allows" add: "belts start at the tier the URL chose and a run that needs more is raised to the cheapest faster belt the URL's technologies unlock; sorters likewise stay within the researched tiers". In the spec, change the status line to `Status: implemented on branch belt-and-sorter-tiers; gate evidence under docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers/`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pipeline.py docs/superpowers/evidence/2026-09-02-belt-and-sorter-tiers README.md docs/superpowers/specs/2026-09-02-belt-and-sorter-tiers-design.md
git commit -m "test: the reported Mk.II URL builds with Mk.III runs; corpus gate evidence"
```
