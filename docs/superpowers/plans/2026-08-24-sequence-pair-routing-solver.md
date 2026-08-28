# Sequence-Pair Routing Solver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and promote, subject to a strict Pareto gate, a sequence-pair SA/LNS freeform backend whose relaxed DSP global router and existing detailed router form a closed feedback loop.

**Architecture:** Sequence-pair search generates legal fixed-orientation strip placements with explicit whitespace. A shared preparation layer feeds both a relaxed PathFinder-style global router and the existing detailed A* router; every temperature-stage incumbent is detailed-routed, and stranded nets plus blame walls drive the next LNS neighbourhood. Only detailed-routed, `validate.certify()`-clean placements become exact incumbents.

**Tech Stack:** Python 3.12, dataclasses, OR-Tools CP-SAT as benchmark oracle, pytest, mypy strict, Ruff; optional Numba and JAX kernels selected only by exact-parity and cold-call end-to-end benchmarks.

**Spec:** `docs/superpowers/specs/2026-08-24-sequence-pair-routing-solver-design.md`

## Global Constraints

- Work only in `/home/dannyb/sources/factorio-lab-to-blueprint-sequence-pair-solver` on branch `sequence-pair-solver`.
- Keep production `FreeformLayout` on CP-SAT until the promotion gate passes.
- Register `SequencePairLayout` only in audit/A-B tooling before promotion.
- Fixed-orientation integer placement only; preserve `_box()` and `WEST_CHANNEL` conventions.
- The relaxed router may rank candidates but can never establish validity.
- Only the existing detailed router plus `validate.certify()` may establish validity and final `(area, belt_tiles)` ordering.
- One wall deadline and one deterministic expansion budget cover every phase; no hidden retries or degraded fallback.
- Run the real detailed A* router at the end of every temperature stage.
- Python is the reference implementation. Numba and JAX require exact parity and cold-call end-to-end improvement. Rust/C++ comes only after both fail a measured hotspot.
- Preserve direct insertion, proliferation, external input access, power, refusal semantics, and every existing freeform contract.
- Use `uv` for Python commands, Ruff formatting, and strict mypy.
- Each task is one reviewable commit. Do not run project-wide formatting or the full suite until Task 14.

---

## File Structure

**Create**

- `src/flab2bp/layout/route_feedback.py` — stable net identity, detailed-route diagnostics, feedback state, and neighbourhood selection.
- `src/flab2bp/layout/sequence_pair.py` — sequence-pair state, deterministic decoder, gaps, SA moves, direct alignment, and LNS kernels.
- `src/flab2bp/layout/global_router.py` — relaxed exact-grid DSP routing and negotiated congestion.
- `src/flab2bp/layout/sequence_solver.py` — height/restart scheduling, stage loop, budgets, exact incumbents, and `SequencePairLayout`.
- `src/flab2bp/bench/promotion.py` — strict Pareto calculations and bootstrap confidence interval.
- `tests/layout/test_route_feedback.py`
- `tests/layout/test_sequence_pair.py`
- `tests/layout/test_global_router.py`
- `tests/layout/test_sequence_solver.py`
- `tests/bench/test_promotion.py`
- `scripts/benchmark_sequence_kernels.py` — isolated Python/Numba/JAX parity and cold-call benchmark.

**Modify**

- `src/flab2bp/layout/freeform.py` — shared preparation, stable net IDs, fresh routing workspaces, structured detailed results, and post-gate delegation only.
- `tests/layout/test_freeform.py` — migrated internal return contracts and detailed diagnostic regressions.
- `scripts/audit.py` — audit-only sequence-pair backend and solver statistics.
- `scripts/ab_compare.py` — configurable backend pair and promotion metrics.
- `src/flab2bp/bench/ab.py` — CPU/RSS metrics required by the gate.
- `tests/bench/test_ab.py` — new metric preservation.
- `src/flab2bp/pipeline.py`, `tests/conftest.py`, `src/flab2bp/bench/runner.py`, and solver scripts — post-gate clean cutover only.
- `pyproject.toml`, `uv.lock` — only if Numba or JAX wins Task 13.
- `docs/AB_RESULTS.md`, `docs/AB_COMPARISON.md` — measured gate evidence.

---

### Task 1: Stable Routing Identity and Diagnostic Types

**Files:**
- Create: `src/flab2bp/layout/route_feedback.py`
- Create: `tests/layout/test_route_feedback.py`

**Interfaces:**
- Consumes: `Cell = tuple[int, int, int]` coordinate convention from `freeform.py`.
- Produces: `NetId`, `NetRole`, `RouteFailureKind`, `DetailedRouteStatus`, `NetFailure`, and `DetailedRouteResult`.

- [ ] **Step 1: Write failing identity and result tests**

```python
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
)


def test_net_identity_distinguishes_roles_and_ordinals() -> None:
    internal = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    external = NetId(None, 7, "iron-ingot", NetRole.EXTERNAL, 0)
    sibling = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 1)
    assert len({internal, external, sibling}) == 3


def test_detailed_result_counts_real_failures() -> None:
    net = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    failure = NetFailure(
        net_id=net,
        kind=RouteFailureKind.SEALED_POCKET,
        wall=((4, 5, 0),),
        blocking_nets=(),
        expansions=41,
    )
    result = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(failure,),
        iterations=2,
        expansions=41,
    )
    assert result.failed_count == 1
    assert result.stranded == (net,)
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run: `uv run pytest tests/layout/test_route_feedback.py -q`

Expected: collection fails with `ModuleNotFoundError: flab2bp.layout.route_feedback`.

- [ ] **Step 3: Implement the immutable diagnostic types**

```python
from dataclasses import dataclass
from enum import StrEnum

Cell = tuple[int, int, int]


class NetRole(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    PROLIFERATOR = "proliferator"


@dataclass(frozen=True, order=True, slots=True)
class NetId:
    source_strip: int | None
    destination_strip: int | None
    item: str
    role: NetRole
    ordinal: int


class RouteFailureKind(StrEnum):
    STATIC_ACCESS = "static-access"
    DYNAMIC_ACCESS = "dynamic-access"
    SEALED_POCKET = "sealed-pocket"
    CONGESTION_WALL = "congestion-wall"
    COMMIT_LINK = "commit-link"
    BUDGET = "budget"


class DetailedRouteStatus(StrEnum):
    ROUTED = "routed"
    STRANDED = "stranded"
    UNPOWERABLE = "unpowerable"
    BUDGET = "budget"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class NetFailure:
    net_id: NetId
    kind: RouteFailureKind
    wall: tuple[Cell, ...]
    blocking_nets: tuple[NetId, ...]
    expansions: int


@dataclass(frozen=True, slots=True)
class DetailedRouteResult:
    status: DetailedRouteStatus
    routed: tuple[NetId, ...]
    failures: tuple[NetFailure, ...]
    iterations: int
    expansions: int

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def stranded(self) -> tuple[NetId, ...]:
        return tuple(failure.net_id for failure in self.failures)
```

- [ ] **Step 4: Run focused type tests**

Run: `uv run pytest tests/layout/test_route_feedback.py -q`

Expected: all tests pass.

- [ ] **Step 5: Run static checks for the new module**

Run: `uv run ruff check src/flab2bp/layout/route_feedback.py tests/layout/test_route_feedback.py && uv run mypy src/flab2bp/layout/route_feedback.py tests/layout/test_route_feedback.py`

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/layout/route_feedback.py tests/layout/test_route_feedback.py
git commit -m "Add routing diagnostic domain types"
```

---

### Task 2: Immutable Prepared Routing Problem

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` around `_Port`, `_Net`, `_build`, and route preparation
- Modify: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `NetId`, `NetRole` from Task 1; existing `Strip`, `_Pack`, `_Canvas`, `_Port`, `_Net` geometry.
- Produces: `_PreparedPort`, `_PreparedNet`, `_PreparedRoutingProblem`, `_prepare_routing_problem(...)`, and `_PreparedRoutingProblem.new_workspace()`.

- [ ] **Step 1: Use LSP references before changing `_Port`, `_Net`, and `_build`**

Run the LSP `references` operation for each symbol. If the server cannot resolve the symbol, record the failure and use a repository-scoped text search for those exact identifiers. Enumerate every caller in `freeform.py`, `tests/layout/test_freeform.py`, and scripts before editing.

- [ ] **Step 2: Write failing preparation-isolation tests**

```python
def test_prepared_problem_creates_fresh_workspaces() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(spec, strips, pack, power=False)

    first = prepared.new_workspace()
    second = prepared.new_workspace()
    first.canvas.blocked[(999, 999, 0)] = -1

    assert (999, 999, 0) not in second.canvas.blocked
    assert first.buildings is not second.buildings


def test_prepared_net_ids_are_stable() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    a = _prepare_routing_problem(spec, strips, pack, power=False)
    b = _prepare_routing_problem(spec, strips, pack, power=False)
    assert tuple(net.net_id for net in a.nets) == tuple(net.net_id for net in b.nets)
```

- [ ] **Step 3: Run the two tests and verify missing symbols**

Run: `uv run pytest tests/layout/test_freeform.py -q -k 'prepared_problem or prepared_net_ids'`

Expected: FAIL because `_prepare_routing_problem` and workspace types do not exist.

- [ ] **Step 4: Introduce prepared snapshots and index-based ports**

Add frozen preparation types near the existing routing types:

```python
@dataclass(frozen=True, slots=True)
class _PreparedPort:
    belt_index: int
    x: int
    y: int
    x0: int
    x1: int
    tiles: int
    machines: int


@dataclass(frozen=True, slots=True)
class _PreparedNet:
    net_id: NetId
    src: _PreparedPort | None
    dst: _PreparedPort
    item: str
    boundary_goals: tuple[tuple[int, int, int], ...] = ()


@dataclass(slots=True)
class _RoutingWorkspace:
    canvas: _Canvas
    buildings: list[PlacedBuilding]
    nets: list[_Net]


@dataclass(frozen=True, slots=True)
class _PreparedRoutingProblem:
    building_templates: tuple[PlacedBuilding, ...]
    blocked: tuple[tuple[tuple[int, int, int], int], ...]
    solid: frozenset[tuple[int, int, int]]
    reserved: frozenset[tuple[int, int, int]]
    keep_out: frozenset[tuple[int, int, int]]
    nets: tuple[_PreparedNet, ...]
    core: tuple[int, int, int, int]
    route_bounds: tuple[int, int, int, int]
    limit: tuple[int, int, int, int] | None
    power_sites: tuple[tuple[int, int], ...]

    def new_workspace(self) -> _RoutingWorkspace:
        buildings = deepcopy(list(self.building_templates))
        canvas = _Canvas(
            buildings=buildings,
            blocked=dict(self.blocked),
            solid=set(self.solid),
            reserved=set(self.reserved),
            routing_ports=frozenset(),
            limit=self.limit,
            keep_out=set(self.keep_out),
        )
        nets = [_bind_prepared_net(net, buildings) for net in self.nets]
        return _RoutingWorkspace(canvas=canvas, buildings=buildings, nets=nets)
```

`new_workspace()` must clone building templates and mutable maps. Ports resolve buildings by index, never by retaining a mutable `PlacedBuilding` reference from another attempt.
Implement `_bind_prepared_net(net, buildings)` in the same block: resolve each prepared port's `belt_index` against the fresh building list and return a mutable `_Net` for that workspace.

- [ ] **Step 5: Extract `_prepare_routing_problem` from `_build` without changing behavior**

```python
def _prepare_routing_problem(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
) -> _PreparedRoutingProblem:
    """Build immutable exact geometry shared by both routing engines."""
```

Move strip emission, coater/proliferator topology, stable net ID assignment, port holding, power planning, core bounds, and route bounds into this function. Keep external-input nets tagged `NetRole.EXTERNAL` and proliferator nets tagged `NetRole.PROLIFERATOR`.

- [ ] **Step 6: Rebuild `_build` from a fresh workspace**

`_build` must call preparation once, create a fresh workspace, and execute the existing detailed behavior. Do not change placement ordering, routing order, or validation in this task.

- [ ] **Step 7: Run preparation and existing geometry tests**

Run:

```bash
uv run pytest tests/layout/test_freeform.py -q -k 'prepared_problem or prepared_net_ids or no_two_blocking or every_machine or sorter_endpoints'
```

Expected: all selected tests pass.

- [ ] **Step 8: Run Ruff and mypy for touched files**

Run: `uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py && uv run mypy src/flab2bp/layout/freeform.py tests/layout/test_freeform.py`

Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "Extract immutable freeform routing preparation"
```

---

### Task 3: Structured Detailed-Router Results

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` at `_astar`, `_route_external_inputs`, `_route_all`, `_build`, and all callers
- Modify: `tests/layout/test_freeform.py`
- Modify: `src/flab2bp/layout/route_feedback.py`
- Modify: `tests/layout/test_route_feedback.py`

**Interfaces:**
- Consumes: `_PreparedRoutingProblem` from Task 2 and diagnostics from Task 1.
- Produces: `_PathSearchResult`, `_BuildResult`, and detailed results carrying stranded IDs, walls, blocking IDs, causes, and expansions.

- [ ] **Step 1: Write failing diagnostic regressions**

```python
def test_a_sealed_pocket_reports_the_failed_net_and_blocking_owner() -> None:
    canvas, bounds, net, blocker = _boxed_in_with_owned_wall()
    result = _route_all(canvas, [blocker, net], BELT_ID, BELT_MODEL, bounds)
    failure = result.failures[0]
    assert failure.net_id == net.net_id
    assert failure.kind is RouteFailureKind.SEALED_POCKET
    assert blocker.net_id in failure.blocking_nets
    assert failure.wall


def test_budget_exhaustion_is_reported_as_unknown() -> None:
    canvas, bounds, net = _simple_route_scene()
    result = _route_all(
        canvas,
        [net],
        BELT_ID,
        BELT_MODEL,
        bounds,
        budget={"left": 0},
    )
    assert result.status is DetailedRouteStatus.BUDGET
    assert result.failures[0].kind is RouteFailureKind.BUDGET
```

- [ ] **Step 2: Run the diagnostic tests and verify tuple-return failures**

Run: `uv run pytest tests/layout/test_freeform.py -q -k 'sealed_pocket_reports or budget_exhaustion_is_reported'`

Expected: FAIL because `_route_all` returns `(routed, failed, iterations)`.

- [ ] **Step 3: Add one result object per A* call, not per expanded node**

```python
@dataclass(frozen=True, slots=True)
class _PathSearchResult:
    path: tuple[Cell, ...] | None
    kind: RouteFailureKind | None
    wall: tuple[Cell, ...]
    expansions: int
```

Change `_astar` to return `_PathSearchResult`. The success path carries `kind=None`; budget/deadline, dynamic access, and exhausted-pocket exits name their cause. Preserve the existing heap arrays and predecessor representation.

- [ ] **Step 4: Map wall cells to blocking `NetId`s in `_route_all`**

Use the existing cell-to-path owner table. Convert owner indices to stable net IDs only when recording a failure. Preserve current rip-up, repair, best-round, and commit behavior.

- [ ] **Step 5: Return `DetailedRouteResult` from internal and external routing**

Migrate `_route_external_inputs` and `_route_all`. Aggregate them in `_build` without losing role-specific net IDs.

- [ ] **Step 6: Replace `_build`'s tuple with a named result and migrate every caller**

```python
@dataclass(slots=True)
class _BuildResult:
    placement: Placement
    routing: DetailedRouteResult
    towers: tuple[PlacedBuilding, ...]
```

Use LSP references for `_build`; update `FreeformLayout._sweep`, `fallback_placement`, and every direct test caller. Replace `if failed:` with `if result.routing.failed_count:`.

- [ ] **Step 7: Run the detailed-router regression slice**

Run:

```bash
uv run pytest tests/layout/test_freeform.py -q -k 'astar or route or failed or pocket or wall or time_budget or branch or merge'
```

Expected: all selected tests pass with the new result API.

- [ ] **Step 8: Run static checks**

Run: `uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py tests/layout/test_freeform.py tests/layout/test_route_feedback.py && uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py tests/layout/test_freeform.py tests/layout/test_route_feedback.py`

Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py tests/layout/test_freeform.py tests/layout/test_route_feedback.py
git commit -m "Report detailed routing failures structurally"
```

---

### Task 4: Sequence-Pair Decoder and Gap Profile

**Files:**
- Create: `src/flab2bp/layout/sequence_pair.py`
- Create: `tests/layout/test_sequence_pair.py`

**Interfaces:**
- Consumes: integer rectangle sizes, net pairs, and a fixed target height.
- Produces: `PlacementProblem`, `SequencePair`, `GapProfile`, `DecodedPlacement`, `decode_sequence_pair(...)`, and coordinate windows.

- [ ] **Step 1: Write relation, non-overlap, and gap tests**

```python
def test_sequence_pair_relations_decode_to_expected_axes() -> None:
    pair = SequencePair(positive=(0, 1, 2), negative=(0, 2, 1))
    decoded = decode_sequence_pair(
        pair, GapProfile.zero(3), ((3, 2), (4, 2), (2, 3)), outline_height=10
    )
    assert decoded.x[1] >= decoded.x[0] + 3
    assert decoded.y[1] >= decoded.y[2] + 3


def test_gap_profile_adds_explicit_channel_space() -> None:
    pair = SequencePair(positive=(0, 1), negative=(0, 1))
    plain = decode_sequence_pair(pair, GapProfile.zero(2), ((3, 2), (4, 2)), outline_height=6)
    gapped = decode_sequence_pair(
        pair,
        GapProfile(east=(2, 0), north=(0, 0)),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert gapped.x[1] == plain.x[1] + 2


def test_decoded_rectangles_never_overlap() -> None:
    sizes = ((3, 2), (4, 3), (2, 5), (1, 4))
    for positive in permutations(range(4)):
        for negative in permutations(range(4)):
            decoded = decode_sequence_pair(
                SequencePair(positive, negative),
                GapProfile.zero(4),
                sizes,
                outline_height=sum(height for _width, height in sizes),
            )
            boxes = [
                (decoded.x[i], decoded.y[i], decoded.x[i] + width, decoded.y[i] + height)
                for i, (width, height) in enumerate(sizes)
            ]
            for i, j in combinations(range(4), 2):
                ax0, ay0, ax1, ay1 = boxes[i]
                bx0, by0, bx1, by1 = boxes[j]
                assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0
```

- [ ] **Step 2: Run and verify the missing-module failure**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q`

Expected: collection fails because `sequence_pair.py` does not exist.

- [ ] **Step 3: Implement validated immutable state**

```python
@dataclass(frozen=True, slots=True)
class SequencePair:
    positive: tuple[int, ...]
    negative: tuple[int, ...]

    def validate(self, size: int) -> None:
        wanted = tuple(range(size))
        if tuple(sorted(self.positive)) != wanted or tuple(sorted(self.negative)) != wanted:
            raise ValueError(
                "both sequence-pair permutations must contain every strip exactly once"
            )


@dataclass(frozen=True, slots=True)
class GapProfile:
    east: tuple[int, ...]
    north: tuple[int, ...]

    @classmethod
    def zero(cls, size: int) -> GapProfile:
        return cls((0,) * size, (0,) * size)


@dataclass(frozen=True, slots=True)
class PlacementProblem:
    sizes: tuple[tuple[int, int], ...]
    nets: tuple[tuple[int, int], ...]
    outline_height: int
    area_lower_bound: int

    @property
    def size(self) -> int:
        return len(self.sizes)
```

Bound gap values to `0..4` in constructors/mutations.

- [ ] **Step 4: Implement deterministic constraint graphs and longest paths**

```python
def decode_sequence_pair(
    pair: SequencePair,
    gaps: GapProfile,
    sizes: tuple[tuple[int, int], ...],
    *,
    outline_height: int,
    outline_width: int | None = None,
) -> DecodedPlacement:
    """Return earliest legal coordinates and latest shifts inside the outline."""
```

Build both relation graphs, compute forward earliest coordinates and reverse latest coordinates for a supplied outline, and return width, used height, and per-strip windows. Use integers only.

- [ ] **Step 5: Run decoder tests**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q -k 'relation or gap or overlap'`

Expected: all selected tests pass.

- [ ] **Step 6: Run property coverage over generated permutations**

Add deterministic generated cases for 1–7 rectangles and run: `uv run pytest tests/layout/test_sequence_pair.py -q`

Expected: pass without randomness or time-based seeds.

- [ ] **Step 7: Run static checks and commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
uv run mypy src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
git add src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
git commit -m "Add deterministic sequence-pair decoder"
```

---

### Task 5: Deterministic SA Moves and Multi-Start Search

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `tests/layout/test_sequence_pair.py`

**Interfaces:**
- Consumes: `PlacementProblem` and decoder from Task 4.
- Produces: `AnnealConfig`, `PlacementCostContext`, `SearchEnergy`, `AnnealState`, `anneal_stage(...)`, and deterministic derived seeds.

- [ ] **Step 1: Write failing move and reproducibility tests**

```python
def test_every_move_preserves_both_permutations() -> None:
    state = AnnealState.initial(size=8, seed=41)
    for kind in MoveKind:
        moved = apply_move(state, kind, random.Random(7))
        moved.pair.validate(8)
        assert all(0 <= gap <= 4 for gap in moved.gaps.east + moved.gaps.north)


def test_fixed_seed_reproduces_stage_incumbent() -> None:
    problem = tiny_placement_problem()
    a = anneal_stage(problem, AnnealState.initial(problem.size, 17), AnnealConfig.test())
    b = anneal_stage(problem, AnnealState.initial(problem.size, 17), AnnealConfig.test())
    assert a.incumbent == b.incumbent
    assert a.accepted_moves == b.accepted_moves
```

- [ ] **Step 2: Run and verify missing search symbols**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q -k 'move or fixed_seed'`

Expected: FAIL because SA types are absent.

- [ ] **Step 3: Implement move kinds and bounded gap mutation**

Implement swap-positive, swap-negative, swap-both, insert-positive, insert-negative, and one-step east/north gap mutation. Use `random.Random` owned by the state; never module-global randomness.

- [ ] **Step 4: Implement normalized cheap energy**

```python
@dataclass(frozen=True, slots=True)
class PlacementCostContext:
    net_weights: tuple[float, ...]
    history_cost_by_net: tuple[float, ...]
    missed_direct_inserts: int = 0


@dataclass(frozen=True, order=True, slots=True)
class SearchEnergy:
    hard_outline_overflow: int
    scalar: float


def cheap_energy(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    context: PlacementCostContext,
) -> SearchEnergy:
    overflow = max(0, decoded.used_height - problem.outline_height)
    area_ratio = decoded.width * problem.outline_height / max(problem.area_lower_bound, 1)
    weighted_hpwl = sum(
        context.net_weights[index]
        * (abs(decoded.x[src] - decoded.x[dst]) + abs(decoded.y[src] - decoded.y[dst]))
        for index, (src, dst) in enumerate(problem.nets)
    )
    hpwl_ratio = weighted_hpwl / max(problem.area_lower_bound, 1)
    history_ratio = sum(context.history_cost_by_net) / max(len(problem.nets), 1)
    direct_ratio = context.missed_direct_inserts / max(len(problem.nets), 1)
    gap_ratio = decoded.gap_area / max(problem.area_lower_bound, 1)
    return SearchEnergy(
        hard_outline_overflow=overflow,
        scalar=area_ratio
        + 0.35 * hpwl_ratio
        + 0.2 * history_ratio
        + 0.1 * direct_ratio
        + 0.05 * gap_ratio,
    )
```

The scalar includes normalized area, feedback-weighted HPWL, summed-area-table congestion approximation, missed direct insert opportunities, and explicit gap area. Hard overflow sorts first.

- [ ] **Step 5: Implement one temperature stage**

`anneal_stage` runs exactly `config.moves_per_stage`, applies the configured cooling curve, and retains distinct incumbents by placement hash. It does not call either router.

- [ ] **Step 6: Run tests and a fixed throughput smoke test**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q`

Then run a direct Python smoke benchmark over the `quantum-chip` strip sizes and assert only that 8,000 moves complete and return a legal incumbent; do not encode a machine-specific timing assertion in pytest.

- [ ] **Step 7: Static checks and commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
uv run mypy src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
git add src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
git commit -m "Add deterministic sequence-pair annealing"
```

---

### Task 6: Feedback State and Targeted LNS

**Files:**
- Modify: `src/flab2bp/layout/route_feedback.py`
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `tests/layout/test_route_feedback.py`
- Modify: `tests/layout/test_sequence_pair.py`

**Interfaces:**
- Consumes: `DetailedRouteResult`, `PlacementCostContext`, `SequencePair`, and strip ownership from `NetId`.
- Produces: `FeedbackState`, `update_feedback(...)`, `feedback_cost_context(...)`, `select_lns_neighbourhood(...)`, and `repair_neighbourhood(...)`.

- [ ] **Step 1: Write failing update-semantic tests**

```python
def test_real_failure_bumps_net_and_wall_but_budget_does_not() -> None:
    state = FeedbackState.empty(outline=(80, 120))
    failed = detailed_failure(RouteFailureKind.SEALED_POCKET)
    updated = update_feedback(state, failed)
    assert updated.net_weight[failed.failures[0].net_id] == 1.0
    assert updated.cell_history[(4, 5, 0)] > 0.0

    budget = detailed_failure(RouteFailureKind.BUDGET)
    assert update_feedback(state, budget) == state


def test_cell_history_resets_and_net_weights_survive_height_change() -> None:
    net = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    state = FeedbackState(
        outline=(80, 120),
        net_weight={net: 2.0},
        cell_history={(4, 5, 0): 3.0},
    )
    changed = state.for_outline((80, 121))
    assert changed.net_weight[net] == 2.0
    assert changed.cell_history == {}
```

- [ ] **Step 2: Write failing locked-order LNS test**

```python
def test_lns_changes_only_selected_strips_and_sequence_neighbours() -> None:
    pair = SequencePair(tuple(range(8)), tuple(range(8)))
    neighbourhood = frozenset({3, 4})
    repaired = repair_neighbourhood(pair, GapProfile.zero(8), neighbourhood, seed=9)
    assert relative_order(repaired.pair, locked={0, 1, 2, 5, 6, 7}) == relative_order(
        pair, locked={0, 1, 2, 5, 6, 7}
    )
```

- [ ] **Step 3: Run and verify failures**

Run: `uv run pytest tests/layout/test_route_feedback.py tests/layout/test_sequence_pair.py -q -k 'feedback or history or lns'`

Expected: FAIL with missing feedback/LNS symbols.

- [ ] **Step 4: Implement bounded feedback, cost context, and 0.85 decay**

Net criticality increments by 1.0 and caps at 8.0. Cell history increments by the detailed blame value. At each stage boundary, multiply both by 0.85 and delete values below `1e-6`. Outline change clears cells and preserves net weights. `feedback_cost_context(state, problem, decoded)` builds the `PlacementCostContext` from Task 5 by integrating the outline-scoped congestion summed-area table over each decoded net bounding box.

- [ ] **Step 5: Implement neighbourhood selection**

Select stranded endpoint strips, blocking-net endpoint strips, immediate positive/negative permutation neighbours, and strips whose gaps intersect hot boxes. Budget failures select nothing.

- [ ] **Step 6: Implement deterministic destroy/repair and stagnation growth**

Remove only selected strips, preserve locked relative order, reinsert with weighted derived-seed ordering, and allow local gap moves. Add one neighbour ring after a configured number of non-improving focused stages.

- [ ] **Step 7: Run focused tests and static checks**

```bash
uv run pytest tests/layout/test_route_feedback.py tests/layout/test_sequence_pair.py -q
uv run ruff check src/flab2bp/layout/route_feedback.py src/flab2bp/layout/sequence_pair.py tests/layout/test_route_feedback.py tests/layout/test_sequence_pair.py
uv run mypy src/flab2bp/layout/route_feedback.py src/flab2bp/layout/sequence_pair.py tests/layout/test_route_feedback.py tests/layout/test_sequence_pair.py
```

Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add src/flab2bp/layout/route_feedback.py src/flab2bp/layout/sequence_pair.py tests/layout/test_route_feedback.py tests/layout/test_sequence_pair.py
git commit -m "Feed detailed routing failures into sequence LNS"
```

---

### Task 7: Global Router Movement and One-Pass Overflow

**Files:**
- Create: `src/flab2bp/layout/global_router.py`
- Create: `tests/layout/test_global_router.py`
- Modify: `src/flab2bp/layout/freeform.py` only to expose shared movement/preparation helpers without duplicating rules

**Interfaces:**
- Consumes: `_PreparedRoutingProblem.new_workspace()`, exact movement constants, `FeedbackState`, and deterministic expansion budget.
- Produces: `GlobalNetResult`, `GlobalRouteResult`, and `route_global_once(...)`.

- [ ] **Step 1: Write failing movement-parity tests**

```python
def test_global_router_uses_the_same_level_and_ramp_moves_as_detailed() -> None:
    problem = prepared_long_open_route(distance=12)
    result = route_global_once(problem, FeedbackState.empty(problem.outline), budget=20_000)
    path = result.paths[result.net_results[0].net_id]
    assert max(level for _x, _y, level in path) > 0
    assert every_step_is_detailed_router_legal(path)


def test_hard_solids_and_reserved_ports_remain_impassable() -> None:
    problem, hard_cells = prepared_blocked_detour()
    result = route_global_once(problem, FeedbackState.empty(problem.outline), budget=20_000)
    used = {cell for path in result.paths.values() for cell in path}
    assert used.isdisjoint(hard_cells)
```

- [ ] **Step 2: Write failing overflow test**

```python
def test_one_pass_records_capacity_overflow_instead_of_blocking() -> None:
    problem = two_nets_one_cell_corridor()
    result = route_global_once(problem, FeedbackState.empty(problem.outline), budget=20_000)
    assert result.overflow_cells == 1
    assert result.total_overflow == 1
    assert len(result.paths) == 2
```

- [ ] **Step 3: Run and verify missing-module failure**

Run: `uv run pytest tests/layout/test_global_router.py -q`

Expected: collection fails because `global_router.py` is absent.

- [ ] **Step 4: Define immutable global results**

```python
@dataclass(frozen=True, slots=True)
class GlobalNetResult:
    net_id: NetId
    length: int
    level_changes: int
    overflow: int
    expansions: int


@dataclass(frozen=True, slots=True)
class GlobalRouteResult:
    net_results: tuple[GlobalNetResult, ...]
    paths: Mapping[NetId, tuple[Cell, ...]]
    overflow_cells: int
    total_overflow: int
    max_overflow: int
    unreachable_ports: int
    rounds: int
    expansions: int
    hot_cells: tuple[Cell, ...]
```

- [ ] **Step 5: Implement a one-pass relaxed search on fresh arrays**

Reuse exact passability and move generation. Hard solids remain blocked. Provisional occupancy is an integer array; occupied route cells add present/history cost but remain searchable. Use flat indices and compact predecessor storage, matching current allocation-conscious router patterns.

- [ ] **Step 6: Implement compatible sharing keys**

Use only prepared sibling source/destination groups. A path segment shared by compatible nets consumes one logical unit for that group; same-item strangers remain separate capacity users.

- [ ] **Step 7: Run global movement tests and static checks**

```bash
uv run pytest tests/layout/test_global_router.py -q
uv run ruff check src/flab2bp/layout/global_router.py tests/layout/test_global_router.py src/flab2bp/layout/freeform.py
uv run mypy src/flab2bp/layout/global_router.py tests/layout/test_global_router.py src/flab2bp/layout/freeform.py
```

Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add src/flab2bp/layout/global_router.py tests/layout/test_global_router.py src/flab2bp/layout/freeform.py
git commit -m "Add relaxed DSP global routing pass"
```

---

### Task 8: PathFinder Negotiation and Hot Regions

**Files:**
- Modify: `src/flab2bp/layout/global_router.py`
- Modify: `tests/layout/test_global_router.py`

**Interfaces:**
- Consumes: `route_global_once(...)` from Task 7.
- Produces: `route_global(...)` with present/history congestion, deterministic rounds, hot regions, and budget status.

- [ ] **Step 1: Write failing convergence and budget tests**

```python
def test_negotiation_moves_one_net_off_an_overflow_cell() -> None:
    problem = corridor_with_one_detour()
    result = route_global(problem, FeedbackState.empty(problem.outline), budget=100_000)
    assert result.total_overflow == 0
    assert result.rounds >= 2


def test_global_budget_returns_metrics_not_validity() -> None:
    result = route_global(stress_grid(), FeedbackState.empty((100, 100)), budget=10)
    assert result.exhausted_budget
    assert result.total_overflow >= 0
```

- [ ] **Step 2: Run and verify missing negotiation behavior**

Run: `uv run pytest tests/layout/test_global_router.py -q -k 'negotiation or global_budget'`

Expected: FAIL.

- [ ] **Step 3: Implement deterministic present/history updates**

Route all nets longest-first, compute overflow, increase history on overflow cells, and reroute for at most five reference rounds or until zero overflow/budget exhaustion. Include detailed feedback's cell history in the initial history array.

- [ ] **Step 4: Build hot cells and region boxes**

Sort hot cells by `(-history, flat_index)`, retain a bounded deterministic prefix, and merge adjacent cells into compact boxes for cheap SA summed-area scoring.

- [ ] **Step 5: Verify global results never imply acceptance**

Add a test that a zero-overflow result exposes no `valid` or `placement` property and cannot be passed to `validate.certify()`.

- [ ] **Step 6: Run tests, static checks, and commit**

```bash
uv run pytest tests/layout/test_global_router.py -q
uv run ruff check src/flab2bp/layout/global_router.py tests/layout/test_global_router.py
uv run mypy src/flab2bp/layout/global_router.py tests/layout/test_global_router.py
git add src/flab2bp/layout/global_router.py tests/layout/test_global_router.py
git commit -m "Negotiate global routing congestion"
```

---

### Task 9: Direct-Insert Alignment Within Legal Windows

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `tests/layout/test_sequence_pair.py`
- Modify: `src/flab2bp/layout/freeform.py` only to expose existing direct-candidate geometry as immutable inputs

**Interfaces:**
- Consumes: `DecodedPlacement` coordinate windows and current `_DirectCandidate` fields.
- Produces: `DirectInsertTarget` and `align_direct_inserts(...)`.

- [ ] **Step 1: Write failing alignment tests**

```python
def test_alignment_realizes_candidate_without_changing_relations() -> None:
    problem, decoded, target = direct_alignment_scene()
    aligned = align_direct_inserts(problem, decoded, (target,))
    assert target.key in aligned.direct
    assert aligned.width <= decoded.width
    assert same_sequence_relations(decoded, aligned)
    assert no_overlaps(aligned, problem.sizes)


def test_alignment_leaves_candidate_when_window_is_too_small() -> None:
    problem, decoded, target = direct_alignment_scene(alignment_window=0)
    aligned = align_direct_inserts(problem, decoded, (target,))
    assert aligned == decoded
    assert target.key not in aligned.direct
```

- [ ] **Step 2: Run and verify missing alignment**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q -k alignment`

Expected: FAIL.

- [ ] **Step 3: Implement immutable targets and window-bounded shifts**

```python
@dataclass(frozen=True, slots=True)
class DirectInsertTarget:
    key: tuple[int, int]
    producer: int
    consumer: int
    producer_row: int
    consumer_row: int
    producer_span: int
    consumer_span: int
```

Try targets in stable benefit order. Shift only within each strip's earliest/latest x/y window, re-decode affected constraints, and reject shifts that enlarge the outline or overlap.

- [ ] **Step 4: Compare against CP-SAT oracle on fixture placements**

For `two_stage_spec`, assert the local aligner realizes at least the existing adjacent direct insertion. Record missed opportunities as test-visible counts; do not weaken the exact belt-count promotion gate.

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest tests/layout/test_sequence_pair.py tests/layout/test_freeform.py -q -k 'direct or alignment'
uv run ruff check src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py src/flab2bp/layout/freeform.py
uv run mypy src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py src/flab2bp/layout/freeform.py
git commit -m "Align sequence placements for direct insertion"
```

---

### Task 10: Stage Scheduler and Shared Budget Orchestrator

**Files:**
- Create: `src/flab2bp/layout/sequence_solver.py`
- Create: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: sequence search, global router, detailed router adapter, feedback, candidate heights, and `BuildSpec`.
- Produces: `SequenceSolverConfig`, `SequencePairLayout`, stage stats, and exact-incumbent ordering.

- [ ] **Step 1: Write failing scheduler tests with injected fake routers**

```python
def test_every_height_gets_one_stage_before_any_second_stage() -> None:
    trace: list[int] = []
    solver = fake_solver(heights=(40, 60, 80), stage_trace=trace)
    solver.search(max_stages=4)
    assert trace[:3] == [40, 60, 80]


def test_detailed_router_runs_at_end_of_every_stage() -> None:
    detailed_calls: list[int] = []
    solver = fake_solver(detailed_calls=detailed_calls)
    solver.search(max_stages=3)
    assert len(detailed_calls) == 3


def test_proxy_candidate_cannot_displace_exact_incumbent() -> None:
    exact = fake_exact_candidate(area=100, belt_tiles=50)
    proxy = fake_proxy_candidate(area=90, global_overflow=0)
    solver = fake_solver(stage_candidates=(exact, proxy))
    result = solver.search(max_stages=2)
    assert result.placement is exact.placement
    assert result.exact_key == (100, 50)
```

- [ ] **Step 2: Write failing budget-reserve test**

```python
def test_stage_routes_cannot_spend_final_twenty_five_percent() -> None:
    budget = ExpansionBudget(total=100)
    solver = fake_solver(expansion_budget=budget)
    solver.search(max_stages=20)
    assert budget.final_reserved >= 25
```

- [ ] **Step 3: Run and verify missing-module failure**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q`

Expected: collection fails because `sequence_solver.py` is absent.

- [ ] **Step 4: Define orchestration configuration and injectable adapters**

```python
@dataclass(frozen=True, slots=True)
class SequenceSolverConfig:
    stages: int = 6
    moves_per_stage: int = 2_000
    restarts_per_height: int = 2
    global_elites: int = 3
    global_rounds: int = 5
    final_reserve_fraction: Fraction = Fraction(1, 4)
    seed: int = 20260824


@dataclass(slots=True)
class ExpansionBudget:
    total: int
    discovery_by_height: dict[int, int]
    shared_left: int
    final_reserved: int
```

Router callables are constructor-injected in tests; production defaults bind the real implementations.

- [ ] **Step 5: Implement discovery and best-first stage scheduling**

Initialize every height/restart with a derived seed. Allocate equal discovery expansion slices. After discovery, prioritize valid exact incumbent, stranded count, global overflow, area, then spent budget.

- [ ] **Step 6: Implement one closed stage**

Run SA moves, global-route distinct elites, select the stage incumbent, detailed-route it, validate exact success, update feedback on geometric failure, and enter LNS for small stranded sets.

- [ ] **Step 7: Implement exact incumbent and termination semantics**

Compare valid candidates only by `(placement.area, belt_tiles)`. On deadline/budget exhaustion, return the best valid incumbent or raise `NoValidLayout`; never return global/partial output.

- [ ] **Step 8: Run scheduler tests and static checks**

```bash
uv run pytest tests/layout/test_sequence_solver.py -q
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "Orchestrate staged sequence routing search"
```

---

### Task 11: Real Closed-Loop Backend, Power, and Validation

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: real preparation/global/detailed implementations and `LayoutStrategy`.
- Produces: working audit-only `SequencePairLayout.lay_out(...)` with full stats.

- [ ] **Step 1: Write failing end-to-end no-power and power tests**

```python
@pytest.mark.parametrize("power", [False, True])
def test_sequence_backend_returns_only_certified_placements(power: bool) -> None:
    spec = two_stage_spec()
    placement = SequencePairLayout(power=power, config=SequenceSolverConfig.test()).lay_out(
        spec,
        time_budget_s=2.0,
    )
    assert not validate.certify(placement, spec, expect_power=power).errors
    assert placement.stats["backend"] == "sequence-pair"
    assert placement.stats["detailed_routes"] >= 1.0
```

- [ ] **Step 2: Add the powered one-net-miss regression**

Use the frozen quantum-chip strip/placement fixture derived from the spike. Assert the first detailed result strands one net, the feedback state selects its endpoint/blocker strips, and the next LNS stage either validates or returns an honest structured miss without emitting a placement.

- [ ] **Step 3: Run and verify real integration failures**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k 'certified or powered_one_net'`

Expected: FAIL until real adapters are connected.

- [ ] **Step 4: Bind production preparation, global router, detailed router, power, and validator**

`SequencePairLayout` constructor accepts `power`, `strip_len`, and optional internal `config`. Its public `lay_out(spec, *, time_budget_s)` exactly satisfies `LayoutStrategy`. It creates the same ceiling/deadline and shared expansion budget semantics as `FreeformLayout`.

- [ ] **Step 5: Populate complete observational stats**

Include backend, accelerator, heights, restarts, stages, moves, global/detailed routes, best overflow/stranded, LNS sizes, feedback counts, phase times, expansion use, direct candidates/inserts, area, belts, power, and termination cause. Stats cannot influence search.

- [ ] **Step 6: Run behavior slices against both backends**

Run:

```bash
uv run pytest tests/layout/test_sequence_solver.py tests/layout/test_freeform.py -q -k 'direct or prolifer or fan_out or shard or mixed or external or power or deterministic or validator'
```

Expected: all selected tests pass.

- [ ] **Step 7: Static checks and commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/freeform.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/freeform.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py
git add src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/freeform.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py
git commit -m "Close sequence search with detailed routing feedback"
```

---

### Task 12: Audit Backend and Strict Pareto Evaluator

**Files:**
- Create: `src/flab2bp/bench/promotion.py`
- Create: `tests/bench/test_promotion.py`
- Modify: `scripts/audit.py`
- Modify: `scripts/ab_compare.py`
- Modify: `src/flab2bp/bench/ab.py`
- Modify: `tests/bench/test_ab.py`

**Interfaces:**
- Consumes: `SequencePairLayout`, existing `Sample`, `Trial`, `Cell`, and corpus runner.
- Produces: audit strategy `sequence-pair`, configurable `--a/--b`, CPU/RSS samples, `PromotionReport`, and bootstrap upper confidence bound.

- [ ] **Step 1: Write failing promotion tests**

```python
def test_promotion_requires_strict_runtime_ci_and_nonworse_quality() -> None:
    report = assess_promotion(
        baseline=fixture_trials(
            seconds=(10.0, 10.2, 9.8), area=(100, 100, 100), belts=(50, 50, 50)
        ),
        candidate=fixture_trials(seconds=(8.0, 8.2, 7.9), area=(100, 99, 100), belts=(50, 50, 49)),
        bootstrap_seed=7,
    )
    assert report.eligible
    assert report.runtime_ratio_ci_hi < 1.0


def test_one_cell_quality_regression_blocks_promotion() -> None:
    report = assess_promotion(
        baseline=fixture_trials(
            url_id="one-cell", seconds=(10.0, 10.1, 9.9), area=(100, 100, 100), belts=(50, 50, 50)
        ),
        candidate=fixture_trials(
            url_id="one-cell", seconds=(7.0, 7.1, 6.9), area=(101, 101, 101), belts=(50, 50, 50)
        ),
        bootstrap_seed=7,
    )
    assert not report.eligible
    assert any("area" in reason for reason in report.reasons)
```

- [ ] **Step 2: Run and verify missing promotion module**

Run: `uv run pytest tests/bench/test_promotion.py -q`

Expected: collection fails.

- [ ] **Step 3: Implement deterministic bootstrap and per-cell checks**

```python
@dataclass(frozen=True, slots=True)
class PromotionReport:
    eligible: bool
    reasons: tuple[str, ...]
    runtime_ratio_geo_mean: float
    runtime_ratio_ci_hi: float
    p95_ratio: float
    cpu_ratio: float
    rss_ratio: float
```

Use a fixed-seed paired bootstrap over matched cells. Require CI high `< 1.0`, zero invalids, no additional refusals, non-worse per-cell median area/belts, and non-worse p95/CPU/RSS.

- [ ] **Step 4: Preserve CPU and peak RSS through A/B samples**

Add numeric metrics without changing existing JSON compatibility. Tests must prove older samples lacking these keys still parse but cannot pass promotion.

- [ ] **Step 5: Register the backend and persisted-report CLI only in audit tooling**

Change strategy tables to factories so CP-SAT worker arguments are not forced into `SequencePairLayout`. Add `sequence-pair` to `audit.py`. Add `--a` and `--b` choices to `ab_compare.py`, retain its existing `--json PATH` and `--power` conventions, and keep existing spine/freeform defaults until explicitly selected. Add `python -m flab2bp.bench.promotion RESULT.json [RESULT.json ...]` to combine one or more persisted runs and emit the machine-readable `PromotionReport`.

- [ ] **Step 6: Run benchmark unit tests**

Run: `uv run pytest tests/bench/test_promotion.py tests/bench/test_ab.py -q`

Expected: all pass.

- [ ] **Step 7: Run one small real A/B smoke cell**

Run:

```bash
uv run python scripts/ab_compare.py --a freeform --b sequence-pair --only magnetic-coil --budget 10 --repeat 2 --candidates 1 --json out/sequence-pair-smoke.json
```

Expected: both strategies produce recorded outcomes in `out/sequence-pair-smoke.json`; the command does not claim promotion from one cell.

- [ ] **Step 8: Static checks and commit**

```bash
uv run ruff check src/flab2bp/bench/promotion.py src/flab2bp/bench/ab.py scripts/audit.py scripts/ab_compare.py tests/bench/test_promotion.py tests/bench/test_ab.py
uv run mypy src/flab2bp/bench/promotion.py src/flab2bp/bench/ab.py scripts/audit.py scripts/ab_compare.py tests/bench/test_promotion.py tests/bench/test_ab.py
git add src/flab2bp/bench/promotion.py src/flab2bp/bench/ab.py scripts/audit.py scripts/ab_compare.py tests/bench/test_promotion.py tests/bench/test_ab.py
git commit -m "Measure sequence solver promotion criteria"
```

---

### Task 13: Python, Numba, and JAX Kernel Bake-Off

**Files:**
- Create: `scripts/benchmark_sequence_kernels.py`
- Create: `src/flab2bp/layout/sequence_kernels.py`
- Modify: `src/flab2bp/layout/sequence_pair.py` to call the selected placement kernels
- Modify: `src/flab2bp/layout/global_router.py` to expose and call its route kernel
- Modify: `tests/layout/test_sequence_pair.py`
- Modify: `tests/layout/test_global_router.py`
- Conditionally modify: `pyproject.toml`, `uv.lock` only when an accelerator qualifies
- Modify: `docs/AB_RESULTS.md`

**Interfaces:**
- Consumes: decoder and cheap-score kernels from Tasks 4–5, global routing from Tasks 7–8, and fixed mid/stress problems.
- Produces: exact parity reports, cold/warm timings, memory, one selected accelerator per kernel, or documented Python-only decisions.
- [ ] **Step 1: Write failing placement and routing kernel parity tests**

```python
def test_kernel_protocol_returns_exact_reference_integers() -> None:
    problem = generated_kernel_fixture(seed=11, strips=40)
    expected = PythonSequenceKernel().decode_batch(problem.pairs, problem.gaps, problem.sizes)
    assert len(expected) == len(problem.pairs)
    assert all(isinstance(value, int) for row in expected for value in row)


def test_global_kernel_reproduces_reference_paths_and_diagnostics() -> None:
    problem = prepared_global_kernel_fixture()
    expected = PythonGlobalRouteKernel().route(problem, budget=100_000)
    candidate = selected_global_route_kernel().route(problem, budget=100_000)
    assert candidate.paths == expected.paths
    assert candidate.net_results == expected.net_results
    assert candidate.expansions == expected.expansions
```

- [ ] **Step 2: Define the replaceable kernel protocol**

```python
IntMatrix = Sequence[Sequence[int]]
DecodedBatch = tuple[tuple[int, ...], ...]


class SequenceKernel(Protocol):
    name: str

    def decode_batch(self, pairs: IntMatrix, gaps: IntMatrix, sizes: IntMatrix) -> DecodedBatch:
        raise NotImplementedError

    def score_batch(
        self, decoded: IntMatrix, nets: IntMatrix, feedback: IntMatrix
    ) -> tuple[int, ...]:
        raise NotImplementedError
```

Define a parallel `GlobalRouteKernel` protocol in `global_router.py`; it consumes the prepared flat arrays plus an integer expansion budget and returns exact paths, per-net diagnostics, and expansion counts. Keep orchestration, random moves, error handling, feedback policy, and exact acceptance outside both kernel protocols.


- [ ] **Step 3: Implement the standalone benchmark with optional imports**

The script must:

- generate identical mid and stress placement and routing inputs;
- run Python, Numba, and JAX candidates for every compatible kernel shape;
- compare decoded coordinates, scores, paths, and diagnostics exactly before timing;
- measure import/compile plus first call, warmed calls, CPU time, and peak RSS;
- emit JSON and a concise per-kernel table;
- exit nonzero on any parity drift.

Run candidates without changing project dependencies:
```bash
uv run --with numba --with jax python scripts/benchmark_sequence_kernels.py --repeats 5
```

- [ ] **Step 4: Apply the exact adoption rule**

Adopt an accelerator only if:

1. every output has exact parity;
2. matched end-to-end `SequencePairLayout.lay_out()` cold-call wall time improves;
3. CPU time and peak RSS are non-worse;
4. the full call, not merely batch decoding, amortizes compilation.

Apply the rule independently per kernel. If neither accelerator qualifies for a kernel, retain its Python implementation. If one qualifies, add only that implementation to `sequence_kernels.py` or `global_router.py`, add its dependency through `uv`, and parameterize parity tests over Python and the winner. Numba may win the branch-heavy route kernel while JAX wins static batched decoding/scoring; this is allowed only when each end-to-end comparison independently passes. Delete rejected experimental implementations before staging.

- [ ] **Step 5: Record the measured decision**

Add the command, versions, hardware summary, exact parity result, cold/warm time, RSS, and decision to `docs/AB_RESULTS.md`. Do not write an unmeasured recommendation.

- [ ] **Step 6: Run selected-kernel tests and static checks**

Run:

```bash
uv run pytest tests/layout/test_sequence_pair.py tests/layout/test_global_router.py tests/layout/test_sequence_solver.py -q
uv run ruff check src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_kernels.py src/flab2bp/layout/global_router.py scripts/benchmark_sequence_kernels.py tests/layout/test_sequence_pair.py tests/layout/test_global_router.py
uv run mypy src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_kernels.py src/flab2bp/layout/global_router.py scripts/benchmark_sequence_kernels.py tests/layout/test_sequence_pair.py tests/layout/test_global_router.py
```

Expected: exit 0 using Python plus the selected winner, if any.

- [ ] **Step 7: Commit the measured outcome**

```bash
git add scripts/benchmark_sequence_kernels.py src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_kernels.py src/flab2bp/layout/global_router.py tests/layout/test_sequence_pair.py tests/layout/test_global_router.py docs/AB_RESULTS.md pyproject.toml uv.lock
git diff --cached --check
git commit -m "Benchmark sequence solver acceleration kernels"
```

---

### Task 14: Full Verification and Promotion Gate

**Files:**
- Modify: `docs/AB_RESULTS.md`
- Modify: `docs/AB_COMPARISON.md`
- Modify tests only if verification exposes a real uncovered contract; do not weaken assertions.

**Interfaces:**
- Consumes: complete audit-only backend and promotion evaluator.
- Produces: fresh full-corpus evidence and `PromotionReport` deciding whether Task 15 is allowed.

- [ ] **Step 1: Run focused unit and integration suites**

Run:

```bash
uv run pytest tests/layout/test_route_feedback.py tests/layout/test_sequence_pair.py tests/layout/test_global_router.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py tests/bench/test_promotion.py tests/bench/test_ab.py -q
```

Expected: zero failures.

- [ ] **Step 2: Run the full project checks**

Run:

```bash
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy
uv run pytest -q
```

Expected: every command exits 0.

- [ ] **Step 3: Run the matched full-corpus experiment**

Run every tier (the `stress` cutoff includes all lower tiers), every generated candidate, both power modes, matched core allocation, and five fixed trials per matched cell:

```bash
uv run python scripts/ab_compare.py \
  --a freeform \
  --b sequence-pair \
  --tier stress \
  --budget 10,60,120,300 \
  --repeat 5 \
  --candidates 3 \
  --json out/sequence-pair-gate-no-power.json

uv run python scripts/ab_compare.py \
  --a freeform \
  --b sequence-pair \
  --tier stress \
  --budget 10,60,120,300 \
  --repeat 5 \
  --candidates 3 \
  --power \
  --json out/sequence-pair-gate-power.json
```

- [ ] **Step 4: Confirm the strict Pareto report**

Run:

```bash
uv run python -m flab2bp.bench.promotion \
  out/sequence-pair-gate-no-power.json \
  out/sequence-pair-gate-power.json
```

Verify each reported requirement independently:

- zero invalid outputs;
- no additional refusal in any cell;
- non-worse per-cell median area;
- non-worse per-cell median belts;
- bootstrap 95% runtime-ratio upper bound below 1.0;
- non-worse p95 wall, CPU, and RSS.

Expected: `eligible=true` is required for Task 15. `eligible=false` is a valid experimental result and blocks production cutover.

- [ ] **Step 5: Update A/B documentation from generated results**

Replace stale numbers in `docs/AB_RESULTS.md` and `docs/AB_COMPARISON.md` with the exact run metadata, result table, confidence interval, per-cell regressions, and promotion verdict. State power and accelerator decisions explicitly.

- [ ] **Step 6: Commit verification evidence**

```bash
git add docs/AB_RESULTS.md docs/AB_COMPARISON.md
git commit -m "Record sequence solver corpus gate"
```

- [ ] **Step 7: Gate Task 15**

If `eligible=true`, proceed. If `eligible=false`, stop with production still on CP-SAT, retain the audit-only backend and evidence, and open no alias or fallback path. The feature is complete as an evaluated parallel backend; promotion awaits a future approved design change based on named failed metrics.

---

### Task 15: Clean Production Cutover After a Passing Gate

**Precondition:** Task 14 produced committed `eligible=true` evidence. Do not execute this task otherwise.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: `tests/conftest.py`
- Modify: `src/flab2bp/bench/runner.py`
- Modify: `scripts/audit.py`
- Modify: `scripts/ab_compare.py`
- Modify: `scripts/gap_vs_greedy.py`
- Modify: `scripts/solve_probe.py`
- Modify: `tests/layout/test_freeform.py`
- Create: `tests/test_pipeline.py`
- Create: `src/flab2bp/bench/cpsat_oracle.py`
- Create: `tests/bench/test_cpsat_oracle.py`

**Interfaces:**
- Consumes: passing `SequencePairLayout` and promotion evidence.
- Produces: `FreeformLayout` using the sequence solver by default, no audit-only alias, and CP-SAT placement reachable only through benchmark/oracle code.

- [ ] **Step 1: Write production-delegation and public-registry tests**

```python
def test_freeform_production_path_uses_promoted_sequence_solver() -> None:
    placement = FreeformLayout(power=False).lay_out(two_stage_spec(), time_budget_s=2.0)
    assert placement.stats["backend"] == "sequence-pair"
    assert "cp_sat_solves" not in placement.stats
```

```python
def test_pipeline_freeform_registry_keeps_the_public_strategy_name() -> None:
    assert _STRATEGIES["freeform"] is FreeformLayout
```

- [ ] **Step 2: Run and verify CP-SAT is still production**

Run: `uv run pytest tests/layout/test_freeform.py -q -k promoted_sequence_solver`

Expected: FAIL because current `FreeformLayout` reports the CP-SAT backend.

- [ ] **Step 3: Move CP-SAT pack oracle out of the production call graph**

Move `_pack`, its CP-SAT-only helpers, and their direct tests to `src/flab2bp/bench/cpsat_oracle.py` and `tests/bench/test_cpsat_oracle.py`. Remove production imports/calls and migrate every reference found by LSP. Do not leave a user-selectable backend flag or deprecated alias.

- [ ] **Step 4: Make `FreeformLayout` delegate to the promoted engine**

Preserve its constructor's supported power/strip/direct-insert behavior and public `lay_out()` protocol. Remove CP-SAT worker configuration from production freeform; update callers and memo keys through LSP references.

- [ ] **Step 5: Remove the audit-only `sequence-pair` strategy name**

Audit and A/B tools compare production `freeform` to explicit benchmark oracles, not two names for the same production backend.

- [ ] **Step 6: Run all affected callsite tests**

Run:

```bash
uv run pytest tests/layout/test_freeform.py tests/bench tests/test_pipeline.py -q
```

Expected: all affected callsite, oracle, and public strategy-registry tests pass.

- [ ] **Step 7: Run final project verification**

```bash
uv run ruff format --check src tests scripts
uv run ruff check src tests scripts
uv run mypy
uv run pytest -q
```

Expected: all commands exit 0.

- [ ] **Step 8: Run a production CLI smoke scenario**

Run:

```bash
uv run flab2bp \
  'https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11' \
  --strategy freeform \
  --no-power \
  --budget 10 \
  --candidates 1 \
  --verbose \
  --out out/sequence-pair-production-smoke.txt
```

Expected: exit 0, a non-empty blueprint file, a validator-clean freeform attempt, and sequence-pair backend stats. The production-delegation test proves no CP-SAT placement solve appears.

- [ ] **Step 9: Commit the clean cutover**

```bash
git add src tests scripts
git commit -m "Promote sequence solver to freeform production"
```

- [ ] **Step 10: Verify the final commit and worktree state**

Run: `git status --short && git log -3 --oneline`

Expected: clean status and the cutover commit above the gate-evidence commit.
