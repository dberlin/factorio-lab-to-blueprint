# Hierarchical Block Decomposition v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `--strategy hierarchical`, a default-off layout backend that partitions a `BuildSpec` at cut-pressure minima into strip-bounded blocks, solves the blocks with the existing placers in parallel, composes them on one canvas, wires every inter-block cut with the existing router, and returns one validator-clean blueprint for specs the monolithic placers refuse (the 449- and 935-machine malls) at bounded area cost (belt3 within 1.25x of its dense monolith).

**Architecture:** A new package `flab2bp.layout.hierarchy` with four modules: `pressure` (recipe depths, depth pressure profile, cut pressure), `partition` (units, blocks, sub-specs, cuts, composed spec, strip-bounded escalation), `contracts` (the lane contract: an exact transportation assignment from producer output lanes to consumer entry lanes, one router net per positive flow), and `compose` (skyline packing, translation, a `_Canvas` built from the composed buildings, `_Port`s at boundary lanes, `freeform._route_all` on that canvas). `HierarchicalLayout` in `hierarchy/strategy.py` implements `LayoutStrategy` and is registered in `pipeline`, `web.jobs` and (through `STRATEGY_CHOICES`) the CLI. Two placer defects the prototype exposed are fixed first because the decomposer hands the placers many small specs and both defects bite there. The prototype under `docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/` is the reference implementation; lift its functions verbatim where this plan says so and change only what it names.

**Tech Stack:** Python 3.14, `uv run`, pydantic `BuildSpec`, OR-Tools CP-SAT (inside the existing placers), the freeform A* router (`freeform._route_all`, `_Canvas`, `_Port`, `_Net`), `concurrent.futures.ProcessPoolExecutor` (spawn/forkserver safe: every worker entry point is a module-level function), `scripts/audit.py`, `docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py`.

**Spec:** `docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md` §1 (objective: coverage and bounded time first, area within a 10-20 % band) and §4 E (the hierarchical option); the go decision and its three conditions in `docs/superpowers/evidence/2026-09-06-exp-hierarchical/README.md` ("The three things a production version must solve first", "The mall's refusal is a five-machine hole", "Other things that broke"). Where the two disagree, the evidence README is the more recent measurement and wins on mechanism; the design doc wins on objective.

## Global Constraints

- **Default behaviour is byte-identical.** `PRODUCTION_STRATEGIES` stays `("freeform", "sequence-pair")`; `best` never runs the hierarchical backend. One paired `scripts/audit.py --budget 30 --json` round on the merge base and the branch must show identical CLEAN counts and identical per-cell areas for both default arms (the sequence-pair arm is not bit-reproducible across rounds because of islands; judge it by CLEAN count and the same-arm noise band of ±0.11 % on geomean area).
- **The validator is the arbiter.** Every placement `HierarchicalLayout.lay_out` returns has passed `validate.certify(placement, spec, expect_power=True)` with `report.ok`; a composition that fails is a `NoValidLayout`, never a degraded result (`layout/base.py` `NoValidLayout` docstring).
- **No player-closed loops.** v1 wires every cut. A cut the router cannot wire is a refusal with the cut named in `NoValidLayout.reason`, not an `external_input` handed to the player. (The prototype's hand-back is the one thing this plan deliberately does not lift.)
- **Blocks are bounded by strips, not machines** (evidence README "Block size is the wrong knob"). The strip count of a block is `len(strip_variants._logical_strip_plans(sub_spec))`.
- **Cuts are read off net balances, sub-spec flags are recomputed, never inherited** (`spray_lanes`, `belt_required_edges`, `lanes_requiring_split`, `coproduct_buffer_proofs`) — the prototype's `sub_spec` already does this; keep it.
- **Composition gap is at least 2 tiles** (`geom.collide` at gap 1), packing prefers a shape whose smaller side is at most 160 rows (`game.blueprint_area`, tallest latitude band), and finalization runs on the COMPOSED placement only.
- **Exact arithmetic.** Rates are `Fraction`; lane counts are `ceil(rate / (spec.lane_capacity * spec.planning_stack(item, external=...)))`; the transportation assignment in `contracts` is exact.
- **Process discipline:** worktree on a branch off master; never `git stash`; never commit under `.superpowers/`; Serena for reading (shared server: Read/Edit for edits when another agent is active); `ruff check` 0, `ruff format --check` 0, `mypy src` 0; verify once per code change; the pytest summary line never prints here (judge by exit code); 120 s per-test timeout; record `(uptime; vmstat 1 3 | tail -1)` beside every timing; never two audits at once.
- **Known-red on master, not this branch's:** `tests/layout/test_freeform.py::test_all_products_band_160_cold_proof_reaches_a_valid_layout`, `tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`, load flake `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`.
- **Large URLs** are in `docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt` (labels `belt3`, `zurl2`, `mall`); best-known dense areas: belt3 all-products 12408, zurl2 all-products 40905, mall none.

## File Structure

| file | responsibility |
| --- | --- |
| `src/flab2bp/layout/hierarchy/__init__.py` | exports `HierarchicalLayout` |
| `src/flab2bp/layout/hierarchy/pressure.py` | `recipe_depths`, `depth_profile`, `cut_pressure`, `depth_pressure_blocks`, `lanes_for` (lifted from `proto/pressure.py`) |
| `src/flab2bp/layout/hierarchy/partition.py` | `Unit`, `Partition`, `agglomerate`, `coalesce`, `derive_cuts`, `boundary_balances`, `sub_spec`, `composed_spec`, `strip_count`, `initial_partition`, `split_block` (lifted from `proto/partition.py` plus the strip cap and the resplit move) |
| `src/flab2bp/layout/hierarchy/contracts.py` | `LaneEnd`, `LaneFlow`, `boundary_lanes`, `assign_lanes` (new) |
| `src/flab2bp/layout/hierarchy/compose.py` | `BlockPlaced`, `pack_blocks`, `translate`, `canvas_for`, `route_cuts`, `compose` (packing lifted from `proto/compose.py`; the router replaced by `freeform._route_all`) |
| `src/flab2bp/layout/hierarchy/strategy.py` | `HierarchicalLayout`, `_solve_block` (module-level, picklable), budget split constants |
| `src/flab2bp/pipeline.py` | `ExplicitStrategyName`/`StrategyName`/`STRATEGY_CHOICES` gain `"hierarchical"`; `_new_layout` branch; `resolve_sequence_islands` unchanged (returns 1 for it) |
| `src/flab2bp/web/jobs.py` | `WebStrategyName` and the `match` gain `"hierarchical"` |
| `tests/layout/hierarchy/test_pressure.py`, `test_partition.py`, `test_contracts.py`, `test_compose.py`, `test_strategy.py` | unit tests per module |
| `tests/layout/data/mall-block-stage-boundary.json` | the sub-spec that crashes `SequencePairLayout` (Task 3) |
| `docs/superpowers/evidence/2026-09-07-hierarchical-v1/` | gate evidence (Task 7) |

---

### Task 1: The five-machine hole (a one-recipe spec refuses at exactly 5 and 6 machines)

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` and/or `src/flab2bp/layout/finalize.py` (cause unknown; freeform refuses with `geom.collide (48, 56): build colliders intersect` at band 4, sequence-pair gives up in 1.0 s with "deadline exhausted"/"expansion budget exhausted" regardless of budget)
- Test: `tests/layout/test_freeform.py`, `tests/layout/test_sequence_pair.py`

**Interfaces:**
- Consumes: `flab2bp.rates.candidates._build_candidates_canonical`, `flab2bp.lab.flow.canonicalize_dataset/canonicalize_request`, `flab2bp.lab.url.parse_url`, `flab2bp.lab.data.load_vendored`, `flab2bp.lab.techs.belt_rules_for_url`, `pipeline._new_layout`.
- Produces: nothing new; both placers lay out the 5- and 6-machine negentropy-smelter spec.

Use superpowers:systematic-debugging: reproduce, isolate the predicate, fix at the cause. `proto/minimal.py` and `out/minimal-block-counts.json` in the evidence dir are the reproduction and the sweep (1-4 OK, 5-6 REFUSED, 7-8 OK on both placers; lowering `belt_stack`, locking the piler and removing the spray change nothing).

- [ ] **Step 1: Write the failing test** (both files get one; the fixture helper is shared through `tests/layout/conftest.py`)

```python
# tests/layout/conftest.py (add)
from __future__ import annotations

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, _build_candidates_canonical
from flab2bp.spec import BuildSpec

MALL_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf"
    ".NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc"
    "3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11"
)


def one_recipe_spec(spec: BuildSpec, recipe: str, count: int) -> BuildSpec:
    """``count`` machines of ``recipe`` cut out of ``spec`` as a self-contained spec."""
    group = next(g for g in spec.groups if g.recipe_id == recipe)
    group = group.model_copy(update={"count": count})
    inputs = {item: rate * count for item, rate in group.inputs_per_machine.items()}
    outputs = {item: rate * count for item, rate in group.outputs_per_machine.items()}
    spray = {i: True for i in spec.spray_lanes if i in inputs} if group.is_proliferated else {}
    if spray:
        for item, rate in spec.external_inputs.items():
            if item.startswith("proliferator"):
                inputs[item] = rate / spec.machine_count * count
    data = spec.model_dump()
    data.update(
        {
            "groups": (group,),
            "external_inputs": inputs,
            "outputs": outputs,
            "surplus_outputs": {},
            "spray_lanes": spray,
            "lanes_requiring_split": frozenset(),
            "belt_required_edges": frozenset(),
            "coproduct_buffer_proofs": (),
            "label": f"one-recipe-{recipe}-{count}",
        }
    )
    return BuildSpec(**data)


@pytest.fixture(scope="session")
def mall_all_products() -> tuple[BuildSpec, bool]:
    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(MALL_URL))
    rules = belt_rules_for_url(MALL_URL, data)
    spec_set = _build_candidates_canonical(
        data, request, tier=None, candidate_policies=DEFAULT_CANDIDATE_POLICIES, flow=None
    )
    spec = next(c for c in spec_set.candidates if c.label == "all-products")
    return spec, rules.vertical_construction
```

```python
# tests/layout/test_freeform.py (add)
@pytest.mark.parametrize("count", [5, 6])
def test_one_recipe_negentropy_block_lays_out_at_five_and_six(mall_all_products, count):
    spec, vertical = mall_all_products
    sub = one_recipe_spec(spec, "copper-ingot", count)
    layout = FreeformLayout(
        belt_vertical_construction=vertical, band_policy=BandPolicy.parse("portable"), workers=8
    )
    placement = layout.lay_out(sub, time_budget_s=20.0)
    assert validate.certify(placement, sub, expect_power=True).ok
```

```python
# tests/layout/test_sequence_pair.py (add)
@pytest.mark.parametrize("count", [5, 6])
def test_one_recipe_negentropy_block_lays_out_at_five_and_six(mall_all_products, count):
    spec, vertical = mall_all_products
    sub = one_recipe_spec(spec, "copper-ingot", count)
    layout = SequencePairLayout(
        belt_vertical_construction=vertical, islands=1, band_policy=BandPolicy.parse("portable")
    )
    placement = layout.lay_out(sub, time_budget_s=20.0)
    assert validate.certify(placement, sub, expect_power=True).ok
```

- [ ] **Step 2: Run, expect failure.** `uv run pytest -q -p no:randomly tests/layout/test_freeform.py tests/layout/test_sequence_pair.py -k negentropy` exits non-zero on all four cases (count 4 and 7 may be added as passing controls while isolating).

- [ ] **Step 3: Isolate, then fix at the cause.** Freeform first: instrument the band-4 projection refusal (`finalize._certify_frame` / `_collision_placed`) on the 5-machine pack and name the two buildings at `(48, 56)`; compare with the 4- and 7-machine packs. Then sequence-pair: it exhausts in 1.0 s at any budget, so find the early exit (`sequence_solver` expansion budget) that fires on a one-strip spec. Fix each at the predicate that is wrong for this input. If the two placers share a cause (a strip variant chosen for exactly 5-6 machines, `strip_variants.variants_for_count`), fix it once there. Record the cause in the commit message.

- [ ] **Step 4: Verify.** The four new tests exit 0; `uv run pytest -q -p no:randomly tests/layout/test_strip_variants.py tests/layout/test_finalize.py` exit 0; ruff/mypy/format clean. Harness sanity, freeform and sequence-pair at 30 s: `universe-matrix --rate 60` and `quantum-chip --rate 180` areas within same-arm noise of `docs/superpowers/evidence/2026-09-06-speedups-2-batch3/after-{um60,qc180}.json`.

- [ ] **Step 5: Commit** `fix(layout): lay out one-recipe specs at five and six machines`

### Task 2: `flab2bp.layout.hierarchy.pressure` and `.partition`

**Files:**
- Create: `src/flab2bp/layout/hierarchy/__init__.py` (empty for now), `src/flab2bp/layout/hierarchy/pressure.py`, `src/flab2bp/layout/hierarchy/partition.py`
- Test: `tests/layout/hierarchy/__init__.py`, `tests/layout/hierarchy/test_pressure.py`, `tests/layout/hierarchy/test_partition.py`

**Interfaces:**
- Consumes: `flab2bp.spec.BuildSpec`, `MachineGroup`, `BuildSpec.lane_capacity`, `BuildSpec.planning_stack(item, external=...)`, `flab2bp.layout.strip_variants._logical_strip_plans(spec)`.
- Produces (exact names later tasks import):

```python
# pressure.py
def lanes_for(spec: BuildSpec, item: str, rate: Fraction, *, external: bool) -> int: ...
def recipe_depths(spec: BuildSpec) -> dict[str, int]: ...
def depth_profile(spec: BuildSpec) -> list[dict[str, object]]: ...
def cut_pressure(spec: BuildSpec, blocks: list[list[Unit]]) -> tuple[dict[str, object], list[dict[str, object]]]: ...
def depth_pressure_blocks(spec: BuildSpec) -> tuple[list[list[Unit]], list[int], list[dict[str, object]]]: ...

# partition.py
@dataclass
class Unit: uid: int; group: MachineGroup; count: int   # .recipe, .produces(item), .consumes(item)
@dataclass(frozen=True)
class Cut: item: str; src: int; dst: int; rate: Fraction
@dataclass
class Partition: blocks: list[list[Unit]]; cuts: list[Cut]; notes: list[str]
def agglomerate(units: list[Unit], cap: int) -> list[list[Unit]]: ...
def coalesce(blocks: list[list[Unit]]) -> list[list[Unit]]: ...
def derive_cuts(blocks: list[list[Unit]]) -> tuple[list[int], list[Cut]]: ...
def boundary_balances(blocks) -> tuple[dict[str, dict[int, Fraction]], dict[str, dict[int, Fraction]]]: ...
def sub_spec(spec: BuildSpec, block: list[Unit], index: int) -> BuildSpec: ...
def composed_spec(spec: BuildSpec, blocks: list[list[Unit]]) -> BuildSpec: ...
def strip_count(spec: BuildSpec, block: list[Unit]) -> int: ...
def initial_partition(spec: BuildSpec, *, strip_cap: int) -> Partition: ...
def split_block(block: list[Unit], *, attempt: int) -> list[list[Unit]]: ...
```

`STRIP_CAP_DEFAULT = 12` (evidence: a 24-strip block refused, a 5-recipe 145-machine block placed in 9.6 s; 12 is the midpoint and is re-tuned by Task 7's gate, not here).

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout/hierarchy/test_pressure.py
from fractions import Fraction

from flab2bp.layout.hierarchy import pressure
from flab2bp.layout.hierarchy.partition import Unit
from flab2bp.spec import BuildSpec, MachineGroup


def _chain() -> BuildSpec:
    """ore -> ingot -> gear, one machine each; ingot also feeds a second consumer."""
    g = [
        MachineGroup(recipe_id="ingot", machine_item_id="arc-smelter", count=2,
                     inputs_per_machine={"ore": Fraction(1)}, outputs_per_machine={"ingot": Fraction(1)}),
        MachineGroup(recipe_id="gear", machine_item_id="assembling-machine-1", count=1,
                     inputs_per_machine={"ingot": Fraction(1)}, outputs_per_machine={"gear": Fraction(1)}),
        MachineGroup(recipe_id="plate", machine_item_id="assembling-machine-1", count=1,
                     inputs_per_machine={"ingot": Fraction(1)}, outputs_per_machine={"plate": Fraction(1)}),
    ]
    return BuildSpec(groups=tuple(g), external_inputs={"ore": Fraction(2)},
                     outputs={"gear": Fraction(1), "plate": Fraction(1)}, surplus_outputs={},
                     belt_item_id="conveyor-belt-1", belt_items_per_second=Fraction(6),
                     belt_upgrades=(), sorter_item_ids=("sorter-1",), belt_stack=1,
                     sorter_pick_stacks=(1,), sorter_place_stacks=(1,), piler_unlocked=False,
                     label="chain")


def test_recipe_depths_are_longest_paths_from_the_inputs():
    assert pressure.recipe_depths(_chain()) == {"ingot": 0, "gear": 1, "plate": 1}


def test_depth_profile_counts_items_and_lanes_crossing_each_cut():
    rows = pressure.depth_profile(_chain())
    assert [r["cut_after_depth"] for r in rows] == [0]
    assert rows[0]["item_pressure"] == 1          # ingot is the only crossing item
    assert rows[0]["lane_pressure"] == 1          # 2/s on a 6/s belt is one lane


def test_lanes_for_prices_a_lane_at_capacity_times_stack():
    spec = _chain()
    assert pressure.lanes_for(spec, "ingot", Fraction(6), external=False) == 1
    assert pressure.lanes_for(spec, "ingot", Fraction(7), external=False) == 2
    assert pressure.lanes_for(spec, "ingot", Fraction(0), external=False) == 0


def test_depth_pressure_blocks_cut_at_local_minima_and_keep_regions_whole():
    blocks, cut_after, profile = pressure.depth_pressure_blocks(_chain())
    assert cut_after == [0]
    assert sorted(len(b) for b in blocks) == [1, 2]
    assert all(isinstance(u, Unit) for b in blocks for u in b)
```

```python
# tests/layout/hierarchy/test_partition.py
from fractions import Fraction

import pytest

from flab2bp.layout.hierarchy import partition
from tests.layout.hierarchy.test_pressure import _chain


def test_initial_partition_covers_every_machine_exactly_once():
    part = partition.initial_partition(_chain(), strip_cap=12)
    counted = {}
    for block in part.blocks:
        for u in block:
            counted[u.recipe] = counted.get(u.recipe, 0) + u.count
    assert counted == {"ingot": 2, "gear": 1, "plate": 1}


def test_cuts_are_read_off_net_balances_and_are_topological():
    part = partition.initial_partition(_chain(), strip_cap=12)
    assert {c.item for c in part.cuts} == {"ingot"}
    for c in part.cuts:
        assert c.src < c.dst          # producer block precedes consumer block
        assert c.rate == Fraction(1)  # each consumer wants 1/s of the 2/s made


def test_sub_spec_declares_boundary_items_and_recomputes_flags():
    spec = _chain()
    part = partition.initial_partition(spec, strip_cap=12)
    consumer = next(b for b in part.blocks if any(u.recipe == "gear" for u in b))
    sub = partition.sub_spec(spec, consumer, 1)
    assert sub.external_inputs["ingot"] == sum(u.consumes("ingot") for u in consumer)
    assert "ore" not in sub.external_inputs
    assert sub.spray_lanes == {}
    assert sub.belt_required_edges == frozenset()


def test_composed_spec_matches_the_original_machine_counts():
    spec = _chain()
    part = partition.initial_partition(spec, strip_cap=12)
    built = partition.composed_spec(spec, part.blocks)
    assert built.machine_count == spec.machine_count
    assert built.external_inputs == spec.external_inputs


def test_a_block_over_the_strip_cap_is_split_by_agglomeration():
    spec = _chain()
    whole = [partition.Unit(i, g, g.count) for i, g in enumerate(spec.groups)]
    assert partition.strip_count(spec, whole) >= 3
    part = partition.initial_partition(spec, strip_cap=2)
    assert all(partition.strip_count(spec, b) <= 2 for b in part.blocks)


def test_split_block_varies_the_cut_between_attempts():
    spec = _chain()
    block = [partition.Unit(i, g, g.count) for i, g in enumerate(spec.groups)]
    first = partition.split_block(block, attempt=0)
    second = partition.split_block(block, attempt=1)
    assert len(first) >= 2 and len(second) >= 2
    assert [sorted(u.recipe for u in b) for b in first] != [sorted(u.recipe for u in b) for b in second]


def test_split_block_of_one_unit_splits_the_count():
    spec = _chain()
    ingot = next(g for g in spec.groups if g.recipe_id == "ingot")
    children = partition.split_block([partition.Unit(0, ingot, 6)], attempt=0)
    assert sorted(sum(u.count for u in b) for b in children) == [3, 3]
    children = partition.split_block([partition.Unit(0, ingot, 6)], attempt=1)
    assert sorted(sum(u.count for u in b) for b in children) == [2, 4]
```

- [ ] **Step 2: Run, expect failure** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement.** Copy `proto/pressure.py` into `pressure.py` verbatim except: import `Unit` from `.partition`; `lanes_for` takes `*, external: bool` and calls `spec.planning_stack(item, external=external)` directly (no `try/except`: a `NoValidLayout` from an unpickable stack is a real refusal and propagates); type the dict rows as `dict[str, object]`. Copy `proto/partition.py` into `partition.py` verbatim except: drop the repair loop and `max_repairs` entirely (README "The repair that does not work"); `Cut` is a frozen dataclass instead of a 4-tuple and `derive_cuts` returns `list[Cut]`; module-level `_NEXT_UID` becomes a `_UidCounter` instance passed explicitly so partitions are deterministic and re-entrant; add

```python
STRIP_CAP_DEFAULT = 12


def strip_count(spec: BuildSpec, block: list[Unit]) -> int:
    """How many strips the placers would build for ``block`` on its own."""
    return len(_logical_strip_plans(sub_spec(spec, block, 0)))


def initial_partition(spec: BuildSpec, *, strip_cap: int = STRIP_CAP_DEFAULT) -> Partition:
    """Cut at pressure minima, then split any block over ``strip_cap`` strips."""
    seeds, _cut_after, _profile = depth_pressure_blocks(spec)
    blocks: list[list[Unit]] = []
    todo = list(seeds)
    while todo:
        block = todo.pop()
        if strip_count(spec, block) <= strip_cap or len(block) == 1 and block[0].count == 1:
            blocks.append(block)
            continue
        children = split_block(block, attempt=0)
        if len(children) < 2:
            blocks.append(block)
            continue
        todo.extend(children)
    blocks = coalesce(blocks)
    order, cuts = derive_cuts(blocks)
    return Partition(blocks=[blocks[i] for i in order], cuts=cuts, notes=[])


def split_block(block: list[Unit], *, attempt: int) -> list[list[Unit]]:
    """Two or more children of ``block``; ``attempt`` varies WHERE it is cut.

    Block size interacts with the placers non-monotonically (six machines
    refused, three plus three placed), so a refusing block is not only shrunk
    but re-cut: attempt 0 halves by machines on the heaviest edge, attempt 1
    cuts at one third, attempt 2 splits every unit's count in two, attempt 3
    isolates each recipe.
    """
    machines = sum(u.count for u in block)
    if attempt == 0:
        cap = max(1, machines // 2)
    elif attempt == 1:
        cap = max(1, machines // 3)
    elif attempt == 2:
        halves: list[list[Unit]] = []
        for u in block:
            a, b = u.count // 2, u.count - u.count // 2
            halves.append([Unit(u.uid * 2, u.group, a)] if a else [])
            halves.append([Unit(u.uid * 2 + 1, u.group, b)] if b else [])
        return [h for h in halves if h]
    else:
        return [[u] for u in block]
    return coalesce(agglomerate(block, cap))
```

(`agglomerate` splits a unit larger than the cap first, so the one-unit case yields `[3, 3]` at attempt 0 and, with cap 2, `[2, 2, 2]` merged back to `[2, 4]` at attempt 1 — the test pins both.)

- [ ] **Step 4: Verify.** `uv run pytest -q -p no:randomly tests/layout/hierarchy` exit 0; ruff/mypy/format clean. Sanity against the prototype: `initial_partition` of belt3 all-products cuts after depth 0 and 4 (README "belt3's depth pressure profile") before the strip cap splits the 129-machine block.

- [ ] **Step 5: Commit** `feat(layout): hierarchy partition and cut pressure`

### Task 3: The sequence-pair stage-boundary crash on a decomposed block

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` (~2660 and ~2874: `ValueError("stage-boundary transform must rebuild every restart identically")`)
- Create: `tests/layout/data/mall-block-stage-boundary.json`
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: Task 2's `initial_partition`, `sub_spec`; the `mall_all_products` fixture from Task 1.
- Produces: `SequencePairLayout.lay_out` never raises `ValueError` on a legal spec; it returns or raises `NoValidLayout`.

- [ ] **Step 1: Capture the reproducer.** Run, once, in the worktree:

```python
# scratch, not committed
from flab2bp.layout.hierarchy import partition
spec, vertical = <the mall all-products spec as in tests/layout/conftest.py>
part = partition.initial_partition(spec, strip_cap=12)
for i, block in enumerate(part.blocks):
    sub = partition.sub_spec(spec, block, i)
    try:
        SequencePairLayout(belt_vertical_construction=vertical, islands=1,
                           band_policy=BandPolicy.parse("portable")).lay_out(sub, time_budget_s=12.0)
    except NoValidLayout:
        pass
    except ValueError as exc:
        Path("tests/layout/data/mall-block-stage-boundary.json").write_text(sub.model_dump_json(indent=2))
        raise SystemExit(f"captured block {i}: {exc}")
```

If no block of this partition crashes, use the prototype's: `uv run python docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/run.py mall --cap 60 --budget 12` and dump the block whose arm record reads `CRASH: ValueError: stage-boundary ...` (its sub-spec is `partition_mod.sub_spec(spec, entries[i]["units"], i)` in that script).

- [ ] **Step 2: Write the failing test**

```python
def test_a_decomposed_mall_block_never_crashes_the_stage_boundary_transform(mall_all_products):
    _spec, vertical = mall_all_products
    sub = BuildSpec.model_validate_json(
        (Path(__file__).parent / "data" / "mall-block-stage-boundary.json").read_text()
    )
    layout = SequencePairLayout(
        belt_vertical_construction=vertical, islands=1, band_policy=BandPolicy.parse("portable")
    )
    try:
        placement = layout.lay_out(sub, time_budget_s=12.0)
    except NoValidLayout:
        return
    assert validate.certify(placement, sub, expect_power=True).ok
```

- [ ] **Step 3: Run, expect `ValueError`.** Then find why the sibling restart's `problem` differs from `transformed.problem` for this spec (a transform reading unordered state, or a memo keyed on something the restart re-derives) and fix it at the cause; the invariant "every restart rebuilds identically" stays, the input that violated it is what changes.

- [ ] **Step 4: Verify.** `uv run pytest -q -p no:randomly tests/layout/test_sequence_solver.py -k "stage_boundary or restart"` exit 0; ruff/mypy/format clean; harness `quantum-chip --rate 180 --strategy sequence-pair --islands 4 --budget 30` area within same-arm noise of batch 3's after-qc180 sequence-pair row.

- [ ] **Step 5: Commit** `fix(layout): rebuild stage-boundary restarts identically on decomposed specs`

### Task 4: The lane contract (`hierarchy.contracts`)

**Files:**
- Create: `src/flab2bp/layout/hierarchy/contracts.py`
- Test: `tests/layout/hierarchy/test_contracts.py`

**Interfaces:**
- Consumes: `flab2bp.layout.markers.input_belt_heads(placement)`, `markers.output_belt_tails(placement)`, `flab2bp.dsp.catalog.is_sorter`, `PlacedBuilding.carries_item/output_obj/input_obj`, Task 2's `Cut`, `boundary_balances`.
- Produces:

```python
@dataclass(frozen=True)
class LaneEnd:
    block: int          # block index in the composed order
    building: int       # belt index INSIDE the block's own placement
    item: str
    rate: Fraction      # what this lane carries (tail) or wants (head)

@dataclass(frozen=True)
class LaneFlow:
    item: str
    src: LaneEnd        # a tail on the producing block
    dst: LaneEnd        # a head on the consuming block
    rate: Fraction

def boundary_lanes(placement: Placement, sub: BuildSpec, block: int) -> tuple[list[LaneEnd], list[LaneEnd]]:
    """(output tails, entry heads) of one solved block, rated."""

def assign_lanes(cuts: list[Cut], tails: dict[int, list[LaneEnd]], heads: dict[int, list[LaneEnd]]) -> list[LaneFlow]:
    """Exact transportation assignment; raises ContractError naming the item and blocks when demand cannot be met."""

class ContractError(ValueError): ...
```

The rule: a cut is a lane contract, not an item name (README §1). Each producer tail `i` carries `r_i` (its strip's own output rate: `placement.stats`/`owner_strip` do not expose it, so it is `sub.outputs[item] * (machines behind the lane / machines producing the item in the block)`; when `owner_strip` is `None` on every tail, split the block's `outputs[item]` evenly across its tails — exact Fractions either way and the sum is preserved). Each consumer head `j` wants `d_j` (likewise from `sub.external_inputs[item]`). `assign_lanes` sorts tails by rate descending and heads by demand descending per `(item)`, walks both lists north-west-corner style and emits one `LaneFlow` per positive `f_ij` (at most `n + m - 1` flows per item across all its cuts), stops when every head is met, and raises `ContractError` if any head is short. Fan-out from one tail to several heads and fan-in from several tails to one head are both legal here because the router treats a shared source port as one family (taps) and merges a second feed into an existing lane (`_merge_frontier`); the composer (Task 5) turns each `LaneFlow` into one `_Net`.

- [ ] **Step 1: Write the failing tests**

```python
from fractions import Fraction

import pytest

from flab2bp.layout.hierarchy.contracts import ContractError, LaneEnd, assign_lanes
from flab2bp.layout.hierarchy.partition import Cut


def _end(block, building, item, rate):
    return LaneEnd(block=block, building=building, item=item, rate=Fraction(rate))


def test_one_tail_feeds_two_heads_as_two_flows_from_the_same_tail():
    cuts = [Cut("magnet", 0, 1, Fraction(6))]
    tails = {0: [_end(0, 10, "magnet", 6)]}
    heads = {1: [_end(1, 20, "magnet", 4), _end(1, 21, "magnet", 2)]}
    flows = assign_lanes(cuts, tails, heads)
    assert [(f.src.building, f.dst.building, f.rate) for f in flows] == [(10, 20, 4), (10, 21, 2)]


def test_two_tails_fill_one_head_largest_first():
    cuts = [Cut("magnet", 0, 1, Fraction(5))]
    tails = {0: [_end(0, 10, "magnet", 2), _end(0, 11, "magnet", 3)]}
    heads = {1: [_end(1, 20, "magnet", 5)]}
    flows = assign_lanes(cuts, tails, heads)
    assert [(f.src.building, f.rate) for f in flows] == [(11, 3), (10, 2)]


def test_six_out_four_in_needs_at_most_nine_flows_and_meets_every_head():
    cuts = [Cut("magnet", 0, 1, Fraction(12))]
    tails = {0: [_end(0, i, "magnet", 2) for i in range(6)]}
    heads = {1: [_end(1, 20 + j, "magnet", 3) for j in range(4)]}
    flows = assign_lanes(cuts, tails, heads)
    assert len(flows) <= 9
    for j in range(4):
        assert sum(f.rate for f in flows if f.dst.building == 20 + j) == 3


def test_short_supply_is_a_contract_error_naming_the_item_and_blocks():
    cuts = [Cut("processor", 0, 1, Fraction(15))]
    tails = {0: [_end(0, 10, "processor", 15)]}
    heads = {1: [_end(1, 20, "processor", 28)]}
    with pytest.raises(ContractError, match=r"processor.*block 0.*block 1"):
        assign_lanes(cuts, tails, heads)


def test_flows_are_exact_fractions():
    cuts = [Cut("x", 0, 1, Fraction(1, 3))]
    tails = {0: [_end(0, 1, "x", Fraction(1, 3))]}
    heads = {1: [_end(1, 2, "x", Fraction(1, 3))]}
    (flow,) = assign_lanes(cuts, tails, heads)
    assert flow.rate == Fraction(1, 3)
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** `contracts.py`. `boundary_lanes` lifts the endpoint catalogue from `proto/compose.py` lines 315-348 (a boundary entry head is one NO sorter feeds; a boundary output tail is one NO sorter draws from) and rates them as described above. `assign_lanes`:

```python
def assign_lanes(cuts, tails, heads):
    flows: list[LaneFlow] = []
    by_item: dict[str, list[Cut]] = defaultdict(list)
    for cut in cuts:
        by_item[cut.item].append(cut)
    for item, item_cuts in sorted(by_item.items()):
        supply = sorted(
            (t for src in {c.src for c in item_cuts} for t in tails.get(src, ()) if t.item == item),
            key=lambda t: (-t.rate, t.block, t.building),
        )
        demand = sorted(
            (h for dst in {c.dst for c in item_cuts} for h in heads.get(dst, ()) if h.item == item),
            key=lambda h: (-h.rate, h.block, h.building),
        )
        left = {id(t): t.rate for t in supply}
        i = 0
        for head in demand:
            want = head.rate
            while want > 0 and i < len(supply):
                tail = supply[i]
                take = min(want, left[id(tail)])
                if take > 0:
                    flows.append(LaneFlow(item=item, src=tail, dst=head, rate=take))
                    left[id(tail)] -= take
                    want -= take
                if left[id(tail)] == 0:
                    i += 1
            if want > 0:
                raise ContractError(
                    f"{item}: block {head.block} entry lane {head.building} is short by {want} "
                    f"items/s after every producing block ({sorted({c.src for c in item_cuts})}) "
                    "is drained"
                )
    return flows
```

(The error message must contain `block <src>` and `block <dst>` in that order for the test's regex; format it so.)

- [ ] **Step 4: Verify.** `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_contracts.py` exit 0; ruff/mypy/format clean.

- [ ] **Step 5: Commit** `feat(layout): lane contracts for inter-block cuts`

### Task 5: Compose on one canvas and route the cuts with the real router (`hierarchy.compose`)

**Files:**
- Create: `src/flab2bp/layout/hierarchy/compose.py`
- Test: `tests/layout/hierarchy/test_compose.py`

**Interfaces:**
- Consumes: `freeform._Canvas`, `_Port`, `_Net`, `_route_all(canvas, nets, belt_id, belt_model, bounds, deadline=...)` (freeform.py ~9166; the existing standalone call sites are `tests/layout/test_freeform.py` `_two_strip_stranded_fixture` and `TestDetailedRoutingDiagnostics`, which build a `_Canvas` and `_Net`s by hand — copy their shape), `_reserve_port_access(canvas, demands, *, boundary, bounds, cancelled)` (~11890), `_sorter_tiers_for`, `_sorter_stacks_for`, `_lane_stacks_for` (~5906-5938), `catalog.get_item_id`, `catalog.building(id).model_index`, `catalog.is_belt`, `route_feedback.DetailedRouteResult`, Task 4's `LaneFlow`.
- Produces:

```python
@dataclass
class BlockPlaced: index: int; placement: Placement; base: int; offset: tuple[int, int]; width: int; height: int

@dataclass
class ComposeResult:
    placement: Placement
    blocks: list[BlockPlaced]
    routed: int
    failures: tuple[str, ...]      # one line per unrouted flow: item, src block, dst block, router failure kind

def pack_blocks(sizes: list[tuple[int, int]], gap: int) -> tuple[list[tuple[int, int]], int, int]: ...
def compose(placements: list[Placement], flows: list[LaneFlow], spec: BuildSpec, *, gap: int,
            ramped: bool, deadline: float | None) -> ComposeResult: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from fractions import Fraction

from flab2bp.layout.hierarchy import compose
from flab2bp.layout.hierarchy.contracts import LaneEnd, LaneFlow


def test_pack_blocks_keeps_a_two_tile_gap_and_prefers_a_band_legal_shape():
    sizes = [(40, 30), (40, 30), (40, 30), (40, 30)]
    offsets, width, height = compose.pack_blocks(sizes, gap=2)
    boxes = [(x, y, x + w, y + h) for (x, y), (w, h) in zip(offsets, sizes, strict=True)]
    for a in range(4):
        for b in range(a + 1, 4):
            ax0, ay0, ax1, ay1 = boxes[a]
            bx0, by0, bx1, by1 = boxes[b]
            assert ax1 + 2 <= bx0 or bx1 + 2 <= ax0 or ay1 + 2 <= by0 or by1 + 2 <= ay0
    assert min(width, height) <= 160


def test_pack_blocks_never_exceeds_160_rows_when_a_legal_shape_exists():
    sizes = [(30, 60)] * 8
    _offsets, width, height = compose.pack_blocks(sizes, gap=2)
    assert min(width, height) <= 160


def test_compose_routes_one_cut_between_two_solved_blocks(two_solved_blocks):
    # `two_solved_blocks` (conftest): the `_chain` spec of test_pressure split at its one cut,
    # both blocks laid out by FreeformLayout at 10 s, plus the flows from assign_lanes.
    left, right, flows, spec, ramped = two_solved_blocks
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)
    assert result.failures == ()
    assert result.routed == len(flows)
    heads = {f.dst.building + result.blocks[1].base for f in flows}
    fed = {b.output_obj for b in result.placement.buildings if b.output_obj is not None}
    assert heads <= fed


def test_compose_reports_an_unroutable_cut_instead_of_handing_it_back(two_solved_blocks):
    left, right, flows, spec, ramped = two_solved_blocks
    walled = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None,
                             _limit_margin=0)  # no room outside the packed boxes
    assert walled.failures or walled.routed == len(flows)
    # Either the router still finds a path inside the gap, or it names the failure; never silence.
    assert not any("external_input" in f for f in walled.failures)
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement.** Lift `_normalize`, `_shelf` (as `pack_blocks`, single-row mode dropped, `BAND_MAX_ROWS = 160`, gap floor `max(gap, 2)`), `_skyline`, `_translate` from `proto/compose.py` verbatim. Replace the proto's `_route` Dijkstra with the real router:

```python
def canvas_for(spec: BuildSpec, buildings: list[PlacedBuilding], *, ramped: bool,
               margin: int) -> _Canvas:
    canvas = _Canvas(
        ramped=ramped,
        sorter_tiers=_sorter_tiers_for(spec),
        sorter_stacks=_sorter_stacks_for(spec),
        lane_stacks=_lane_stacks_for(spec),
    )
    for b in buildings:
        # Mirror `_prepare_routing_problem`: machines and addons are solid
        # (their crossing band goes into `blocked`), belts hold their own level.
        canvas.add(b, solid=not catalog.is_belt(b.item_id))
    min_x, min_y, max_x, max_y = Placement(buildings=tuple(buildings)).bounds
    canvas.limit = (min_x - margin, min_y - margin, max_x + margin, max_y + margin)
    return canvas


def _lane(buildings: list[PlacedBuilding], index: int) -> tuple[int, ...]:
    """Every belt index of the run containing ``index``, west to east."""
    prev = {b.output_obj: i for i, b in enumerate(buildings) if b.output_obj is not None}
    head = index
    while head in prev and catalog.is_belt(buildings[prev[head]].item_id):
        head = prev[head]
    run = [head]
    while buildings[run[-1]].output_obj is not None and catalog.is_belt(buildings[buildings[run[-1]].output_obj].item_id):
        run.append(buildings[run[-1]].output_obj)
    return tuple(sorted(run, key=lambda i: buildings[i].x))


def _port(buildings: list[PlacedBuilding], index: int, machines: int) -> _Port:
    tiles = _lane(buildings, index)
    b = buildings[index]
    return _Port(
        belt=index, x=b.x, y=b.y,
        x0=buildings[tiles[0]].x, x1=buildings[tiles[-1]].x, tiles=tiles,
        machines=machines, z=int(b.z), cargo_domain=CargoDomain.UNSPRAYED,
    )
```

`compose` then: normalize + pack + translate (rebasing `output_obj`/`input_obj` by each block's `base`); build `buildings`; `canvas = canvas_for(spec, buildings, ramped=ramped, margin=_limit_margin)` with `_limit_margin` default 8; for each `LaneFlow` build `_Net(src=_port(buildings, flow.src.building + base[src]), dst=_port(buildings, flow.dst.building + base[dst]), item=flow.item)`; call `_reserve_port_access` for every port the way `_prepare_routing_problem` does (read that call with Serena and copy its `PortAccessDemand` construction); `belt_id = catalog.get_item_id(spec.belt_item_id) or 2001`, `belt_model = catalog.building(belt_id).model_index`; `result = _route_all(canvas, nets, belt_id, belt_model, canvas.limit, deadline=deadline)`; on `result.status` not OK, every `result.failures` entry becomes one `failures` line (`f"{item}: block {src} -> block {dst}: {failure.kind.name}"`); the composed placement is `Placement(buildings=tuple(canvas.buildings), description="hierarchical composition")`. Routed belts are committed into `canvas.buildings` by `_route_all` itself (it calls `_commit_paths`), so no second emission pass exists here. The `two_solved_blocks` fixture lives in `tests/layout/hierarchy/conftest.py`, lays the two `_chain` blocks out with `FreeformLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"), workers=4)` at 10 s, and builds `flows` with `contracts.boundary_lanes` + `assign_lanes`.

- [ ] **Step 4: Verify.** `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_compose.py` exit 0 (record wall; two 10 s freeform solves are expected); ruff/mypy/format clean.

- [ ] **Step 5: Commit** `feat(layout): compose solved blocks and route cuts on one canvas`

### Task 6: `HierarchicalLayout` and its registration

**Files:**
- Create: `src/flab2bp/layout/hierarchy/strategy.py`; export from `src/flab2bp/layout/hierarchy/__init__.py`
- Modify: `src/flab2bp/pipeline.py` (`ExplicitStrategyName`, `StrategyName`, `STRATEGY_CHOICES`, `_new_layout`), `src/flab2bp/web/jobs.py` (`WebStrategyName`, the `match` at ~218 and its error text)
- Test: `tests/layout/hierarchy/test_strategy.py`, `tests/test_pipeline_cli_strategy.py`, `tests/web/` (the existing options test that enumerates strategies)

**Interfaces:**
- Consumes: Tasks 2, 4, 5; `pipeline._new_layout`, `BandPolicy`, `finalize.compact_open_boundary_belts`, `finalize.finalize_placement`, `validate.certify`, `LayoutStrategy`, `NoValidLayout`, `PlacementCompletion`.
- Produces:

```python
BLOCK_BUDGET_SHARE = Fraction(1, 2)      # of the whole budget, per block, in parallel
BLOCK_BUDGET_MIN_S = 5.0
BLOCK_BUDGET_MAX_S = 20.0
MAX_RESPLIT_ATTEMPTS = 4                # Task 2's split_block attempts 0..3
DEFAULT_GAP = 2

class HierarchicalLayout:
    name = "hierarchical"
    def __init__(self, *, belt_vertical_construction: bool, band_policy: BandPolicy,
                 workers: int | None = None, strip_cap: int = STRIP_CAP_DEFAULT,
                 block_strategy: Literal["freeform", "sequence-pair", "best"] = "best") -> None: ...
    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 15.0,
                absolute_deadline: float | None = None) -> Placement: ...

def _solve_block(args: tuple[BuildSpec, str, float, bool, int, float | None]) -> tuple[dict[str, object], Placement | None]: ...
```

Behaviour of `lay_out`:
1. `deadline = absolute_deadline or time.monotonic() + time_budget_s`. Partition with `initial_partition(spec, strip_cap=self.strip_cap)`.
2. Solve every unsolved block in a `ProcessPoolExecutor(max_workers=min(len(blocks), max(1, (workers or 16) // 8)))`, each job `_solve_block((sub, strategy, block_budget, vertical, 8, deadline))` for each strategy in `("freeform", "sequence-pair")` (or the one requested), where `block_budget = min(BLOCK_BUDGET_MAX_S, max(BLOCK_BUDGET_MIN_S, time_budget_s * BLOCK_BUDGET_SHARE))` and every child passes `absolute_deadline=deadline` to `lay_out` so no block outlives the parent's wall. The smaller valid placement wins per block (lifted from `proto/run.py` `_solve_block` and the arm loop; keep the CRASH handling, a crash is a refusal for that arm).
3. A refused block is re-cut with `split_block(block, attempt=k)` for `k` in `0..MAX_RESPLIT_ATTEMPTS-1` while `time.monotonic() < deadline - 2 * BLOCK_BUDGET_MIN_S`; children go back to step 2. A block still refused when attempts or time run out is a `NoValidLayout` whose reason names the block's recipes and the last refusal.
4. `boundary_lanes` per block, `assign_lanes` (a `ContractError` is a `NoValidLayout`), `compose(...)` with `deadline`; any `failures` is a `NoValidLayout` listing them.
5. `placement = compact_open_boundary_belts(placement, built, expect_power=True)`; `finalize_placement(placement, self.band_policy, cancelled=lambda: time.monotonic() >= deadline)`; `validate.certify(placement, built, expect_power=True)` where `built = composed_spec(spec, blocks)`; not `ok` is a `NoValidLayout` with the first three error messages. Return `replace(placement, completion=PlacementCompletion.COMPACTED_AND_FINALIZED, stats={... "blocks": n, "block_wall_s": ..., "compose_wall_s": ..., "cut_lanes": len(flows), "resplits": k, "strips_max": max strip_count})` — stats keys must be added to `PlacementStats` in `layout/base.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout/hierarchy/test_strategy.py
def test_hierarchical_lays_out_the_chain_as_two_blocks_and_certifies(chain_spec):
    layout = HierarchicalLayout(belt_vertical_construction=True,
                                band_policy=BandPolicy.parse("portable"), workers=8, strip_cap=2)
    placement = layout.lay_out(chain_spec, time_budget_s=30.0)
    assert placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert placement.stats["blocks"] == 2
    assert validate.certify(placement, chain_spec, expect_power=True).ok


def test_a_block_that_refuses_is_re_cut_before_the_whole_spec_refuses(chain_spec, monkeypatch):
    calls: list[int] = []
    real = strategy._solve_block
    def refuse_first_shape(args):
        sub = args[0]
        calls.append(sub.machine_count)
        if sub.machine_count == 2 and len(sub.groups) == 1:   # the unsplit ingot block
            return ({"verdict": "REFUSED: forced", "ok": False, "strategy": args[1], "wall_s": 0.0}, None)
        return real(args)
    monkeypatch.setattr(strategy, "_solve_block", refuse_first_shape)
    layout = HierarchicalLayout(belt_vertical_construction=True,
                                band_policy=BandPolicy.parse("portable"), workers=8, strip_cap=2)
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)
    assert placement.stats["resplits"] >= 1
    assert 1 in calls   # the ingot block was split into 1 + 1


def test_an_unwired_cut_is_a_refusal_not_a_handback(chain_spec, monkeypatch):
    monkeypatch.setattr(strategy.compose_mod, "compose",
                        lambda *a, **k: compose_mod.ComposeResult(Placement(buildings=()), [], 0, ("ingot: block 0 -> block 1: BUDGET",)))
    layout = HierarchicalLayout(belt_vertical_construction=True,
                                band_policy=BandPolicy.parse("portable"), workers=8, strip_cap=2)
    with pytest.raises(NoValidLayout, match=r"ingot: block 0 -> block 1"):
        layout.lay_out(chain_spec, time_budget_s=30.0)


def test_no_block_outlives_the_parent_deadline(chain_spec, monkeypatch):
    seen: list[float | None] = []
    real = strategy._solve_block
    def spy(args):
        seen.append(args[5])
        return real(args)
    monkeypatch.setattr(strategy, "_solve_block", spy)
    HierarchicalLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"),
                       workers=8, strip_cap=2).lay_out(chain_spec, time_budget_s=30.0)
    assert seen and all(d is not None for d in seen)
```

(The monkeypatched `_solve_block` only works with an in-process executor; give `HierarchicalLayout` a private `_executor_factory` attribute defaulting to `ProcessPoolExecutor` and set it to a `ThreadPoolExecutor` in the tests that patch the worker.)

```python
# tests/test_pipeline_cli_strategy.py (add)
def test_hierarchical_is_an_explicit_strategy_but_not_part_of_best():
    assert "hierarchical" in pipeline.STRATEGY_CHOICES
    assert "hierarchical" not in pipeline.PRODUCTION_STRATEGIES
    assert pipeline._strategy_names("hierarchical") == ("hierarchical",)
    assert pipeline.resolve_sequence_islands("hierarchical", 16, None) == 1
    layout = pipeline._new_layout("hierarchical", belt_vertical_construction=True,
                                  band_policy=BandPolicy.parse("portable"), workers=8)
    assert layout.name == "hierarchical"
```

Plus one web test asserting `{"url": ..., "strategy": "hierarchical"}` parses and `"strategy": "spine"` still raises `InvalidOptions` naming the four choices.

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** `strategy.py` as specified; registration edits: `ExplicitStrategyName = Literal["freeform", "sequence-pair", "hierarchical"]`, `StrategyName` likewise, `STRATEGY_CHOICES = ("best", "freeform", "sequence-pair", "hierarchical")`, `_new_layout` gains `if strategy == "hierarchical": return HierarchicalLayout(belt_vertical_construction=..., band_policy=band_policy, workers=workers)` and its return annotation; `build`'s island validation already refuses islands for it. `web/jobs.py`: `WebStrategyName = Literal["best", "freeform", "sequence-pair", "hierarchical"]`, the `match` arm and the error string list it. The CLI picks it up from `STRATEGY_CHOICES`; update the `--strategy` help text to name it as explicit-only.

- [ ] **Step 4: Verify.** `uv run pytest -q -p no:randomly tests/layout/hierarchy tests/test_pipeline_cli_strategy.py tests/web` exit 0; ruff/mypy/format clean. `uv run flab2bp "<belt3 url>" --strategy hierarchical --budget 60` emits a blueprint and prints the validator summary clean; record wall and area.

- [ ] **Step 5: Commit** `feat(layout): hierarchical block-decomposition strategy (explicit, default off)`

### Task 7: Gate on the large URLs and the default-unchanged guard

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v1/` with `gate.md`, `large-{label}-{policy}-r{1,2}.{json,log}`, `baseline-round1.jsonl`, `candidate-round1.jsonl`, `compare-round1.txt`, `judge.py` (copy from `2026-09-06-speedups-2-batch3/judge.py`), `run_large.sh`, `-load.txt` files
- Modify: `docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md` (a status line under §4 E naming this evidence), `docs/speedup-idea-backlog.md` (move the four "From the hierarchical prototype" items to done/partly done with pointers)

- [ ] **Step 1: Large-URL runs.** `prof_harness.py` takes `--strategy`; extend its choices to accept `hierarchical` (one line) and run each twice at `--budget 60` with `(uptime; vmstat 1 3 | tail -1)` before each: belt3 all-products, belt3 no-proliferator, zurl2 all-products, mall all-products, mall no-proliferator. Record verdict, wall, area, blocks, resplits, cut lanes, validator errors by class, and `area / best_known` where a best known exists.

- [ ] **Step 2: Default-unchanged guard.** One paired `scripts/audit.py --budget 30 --json` round: merge base (throwaway worktree) then branch; `judge.py`; identical CLEAN counts and freeform per-cell areas identical, sequence-pair geomean within ±0.11 %.

- [ ] **Step 3: Strip cap sweep, belt3 only.** `strip_cap` 8, 12, 16 at 60 s via `HierarchicalLayout(strip_cap=...)` from a five-line script; pick the cap with the smallest belt3 area that still builds both malls; if it is not 12, change `STRIP_CAP_DEFAULT` in one commit with the table in its message.

- [ ] **Step 4: `gate.md`** with the verdict against this rule, decided before running: **PASS** if all five large cells build CLEAN with zero unrouted cuts within 120 s wall, belt3 all-products area at most 1.25x 12408, zurl2 at most 1.0x 40905, and the default guard is unchanged. **FAIL** otherwise, naming which clause, with the prototype's numbers beside it (belt3 1.23x blocks-only, zurl2 0.78x) so the router's cost is visible. Either way, list the next three levers from the measurement.

- [ ] **Step 5: Commit** `evidence: hierarchical v1 gate on the large URLs`

---

## Self-review

- **Spec coverage.** Design §4 E asks for blocks solved independently and composed with a bus: Tasks 2, 5, 6. Evidence README condition 1 (lane contract): Task 4. Condition 2 (router on a prepared canvas): Task 5, and it turns out `_route_all` already takes a `_Canvas` and `_Net`s, so the work is constructing them, not a new entry point. Condition 3 (compositional finalization): Task 6 step 5 finalizes only the composed placement, Task 5 keeps the band-legal packer and the 2-tile gap. The five-machine hole and the stage-boundary crash: Tasks 1 and 3. "Vary the split, not only shrink it": `split_block(attempt=...)`. "Cut at pressure minima, bound by strips": `initial_partition`. The design's objective (coverage and time first, area in a band) is the gate rule in Task 7. Not covered, deliberately: a physical shared bus reserved before placement (design §4 E's "reserved corridor") — v1 routes cuts after composition with a margin around the packing; if Task 7 shows the router's cost dominates, that is the first lever.
- **Placeholders.** Task 1 and Task 3 are debugging tasks whose fix cannot be written before the cause is known; each has a concrete failing test, a concrete reproduction, and the predicate to inspect first. Task 5 points at `_prepare_routing_problem` for the `PortAccessDemand` construction rather than restating a 1000-line function; the implementer reads it with Serena.
- **Type consistency.** `Cut(item, src, dst, rate)` is produced by Task 2 and consumed by Tasks 4 and 6; `LaneEnd`/`LaneFlow` by Task 4, consumed by Tasks 5 and 6; `ComposeResult(placement, blocks, routed, failures)` by Task 5, consumed by Task 6; `_solve_block` argument tuple `(spec, strategy, budget, vertical, workers, deadline)` is indexed as `args[5]` in Task 6's deadline test.
