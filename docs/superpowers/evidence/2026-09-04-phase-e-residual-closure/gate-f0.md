# Gate F0 — deterministic-template emission API evidence

## Provenance and stop condition

Gate R0 is already recorded as `R0: SKIP — receiver evidence absent` in `docs/superpowers/evidence/2026-09-04-phase-e-residual-closure/gate-r0.md`. That evidence names branch-point implementation commit `891d09e` and preserves its three audit rounds in `r0-sequence-round{1,2,3}.jsonl` plus host-load evidence in `r0-load.txt`. R0 SKIP is the precondition for this gate.

The current branch head for this investigation is `1ffae6e`.

Two independent investigations traced declarations and callers read-only in `src/flab2bp/layout/freeform.py`, `route_feedback.py`, `global_router.py`, `sequence_solver.py`, `finalize.py`, and `validate.py`. They did not execute a fallback, build native code, or modify production code. The test-side investigation also confirmed that the proposed fallback test was not present and created nothing. Therefore no red fallback test, placeholder implementation module, proof script, or `fallback-proof.jsonl` survives this stop condition. This document is evidence of a missing interface, not evidence of a passing fallback or completed closure.

## Existing call chain and authority

### 1. Strip planning and prepared geometry

`src/flab2bp/layout/freeform.py:2139-2151` starts the chain with:

```python
def plan_strips(
    spec: BuildSpec,
    *,
    strip_len: int = 6,
    band_policy: BandPolicy = _DEFAULT_BAND_POLICY,
    minimum_pitch_x: Mapping[StripPoseId, int] = _NO_PITCH_REQUIREMENTS,
    families: Sequence[StripFamily] | None = None,
    minimum_staged_static_clearance: Mapping[
        StagedStaticClearanceKey,
        int,
    ] = _NO_STAGED_STATIC_CLEARANCE,
    cancelled: Callable[[], bool] | None = None,
) -> list[Strip]
```

Those strips enter `src/flab2bp/layout/freeform.py:14405-14417`:

```python
def _prepare_routing_problem(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    policy: BandPolicy,
    ramped: bool = False,
    _reserve_ports: bool = True,
    staged_static_cache: _StagedStaticCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> _PreparedRoutingProblem
```

Preparation creates the canvas and calls `src/flab2bp/layout/freeform.py:5241-5251`:

```python
def _emit_strip(
    canvas: _Canvas,
    s: Strip,
    ox: int,
    oy: int,
    belt_id: int,
    belt_model: int,
    rates: dict[str, Fraction],
    in_rates: Mapping[str, Fraction] | None = None,
    out_rates: Mapping[str, Fraction] | None = None,
    owner_strip: int | None = None,
) -> tuple[dict[str, _Port], dict[_CargoSink, _Port], int]
```

`_emit_strip` emits strip-local lanes, machines, sorters, and ports; it does not emit the complete inter-strip or boundary routes. Preparation forms `_Net` edges from those ports, assigns `LogicalNetId` and `NetId` at `freeform.py:14928-14969`, freezes `_PreparedNet` records, and creates a `_PreparedRoutingProblem` whose `new_workspace()` rebinds the prepared port indices into live nets. `route_feedback.LogicalNetId` (`route_feedback.py:33-44`) is the stable recipe-edge identity; `route_feedback.NetId` (`route_feedback.py:47-70`) adds the physical source/destination strips and ordinal. Multiple physical branches may intentionally share one `LogicalNetId`, so an exact per-branch path must be keyed by the full prepared `NetId`, not inferred from logical identity alone.

Power sites are also decided before routing by `src/flab2bp/layout/freeform.py:13329-13337`:

```python
def _power_plan(
    canvas: _Canvas,
    demand: tuple[int, int, int, int],
    *,
    policy: BandPolicy,
    additional_demand: Collection[tuple[int, int]] = (),
    staged_static_cache: _StagedStaticCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[tuple[int, int]]
```

The selected sites are held out of routing and become `prepared.power_sites`.

### 2. Prepared build dispatches to search-based routers

The reusable prepared-build boundary is `src/flab2bp/layout/freeform.py:15555-15565`:

```python
def _build_prepared(
    spec: BuildSpec,
    strips: list[Strip],
    prepared: _PreparedRoutingProblem,
    *,
    power: bool,
    route: bool,
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    prioritize_source_families: bool = False,
) -> _BuildResult
```

With `route=True`, `_build_prepared` dispatches early and late external outputs to `_route_external_outputs`, external inputs to `_route_external_inputs`, and internal nets to `_route_all` (`freeform.py:15600-15683`). With `route=False`, it skips routing; it does not accept or emit caller-supplied routes.

The internal router is `src/flab2bp/layout/freeform.py:7823`:

```python
def _route_all(
    canvas: _Canvas,
    nets: list[_Net],
    belt_id: int,
    belt_model: int,
    bounds: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    planned_power_sites: Sequence[tuple[int, int]] | None = None,
    junction_frame_bans: Sequence[frozenset[Cell]] = (),
    *,
    prioritize_source_families: bool = False,
) -> DetailedRouteResult
```

Its principal and repair passes call `_astar` (`freeform.py:8908, 9043, 9173, 9690-9735, 9770, 9841, 10027`). The search signature at `freeform.py:6909-6924` accepts starts, goals, congestion/history, bounds, budgets, and negative constraints, but no required track, level, waypoint set, or prescribed path:

```python
def _astar(
    canvas: _Canvas,
    starts: list[tuple[int, int, int]],
    goals: set[tuple[int, int, int]],
    history: dict[tuple[int, int, int], float],
    pressure: float,
    bounds: tuple[int, int, int, int],
    budget: dict[str, int] | None = None,
    deadline: float | None = None,
    blame: dict[tuple[int, int, int], float] | None = None,
    grid: _Grid | None = None,
    owned_starts: Collection[Cell] = (),
    released_starts: Collection[Cell] = (),
    forbidden: Collection[Cell] = (),
    blocking_owners: Mapping[Cell, int] | None = None,
) -> _PathSearchResult
```

### 3. Boundary emission is coupled to route search

The two boundary entry points are `src/flab2bp/layout/freeform.py:11874-11915`:

```python
def _route_external_inputs(
    canvas: _Canvas,
    nets: Sequence[_Net],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> DetailedRouteResult


def _route_external_outputs(
    canvas: _Canvas,
    nets: Sequence[_Net],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> DetailedRouteResult
```

Both are thin wrappers around `src/flab2bp/layout/freeform.py:11639-11649`:

```python
def _route_boundary_nets(
    canvas: _Canvas,
    nets: Sequence[_Net],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    *,
    outward: bool,
) -> DetailedRouteResult
```

`_route_boundary_nets` may take its ground-only `_straight_to_edge` shortcut; otherwise it calls `_astar` and immediately emits the returned path as belt `PlacedBuilding` records (`freeform.py:11719-11848`). Search and boundary belt/link emission are therefore in the same routine, with no supplied-path mode. Even a no-search internal-net caller cannot cover all external input/output nets through an existing emission boundary.

### 4. The internal exact-path commit helper is necessary but insufficient

Internal `_route_all._finish` commits searched paths through `src/flab2bp/layout/freeform.py:10467-10481`:

```python
def _commit_paths(
    canvas: _Canvas,
    nets: list[_Net],
    paths: Mapping[int, Sequence[Cell]],
    belt_id: int,
    belt_model: int,
    src_group: Mapping[int, tuple[int, ...]] | None = None,
    dst_group: Mapping[int, tuple[int, ...]] | None = None,
    *,
    source_hints: Mapping[int, Cell] | None = None,
    sink_hints: Mapping[int, Cell] | None = None,
    failure_details: dict[int, _CommitFailure] | None = None,
) -> tuple[int, ...]
```

This helper consumes a complete ordered `Sequence[Cell]` for each transient integer net index. It derives the legal real-altitude profile, emits a belt at each exact cell/level, links consecutive belt entities, and attaches source and sink lanes (`freeform.py:10545-10780`). It neither accepts stable `NetId` keys nor expands a `(track, level)` choice into endpoints, local approaches, turns, crossings, and every occupied lattice cell. Its source-linking assumptions also do not cover external-input nets, whose `_Net.source` is unavailable; those roles remain owned by `_route_boundary_nets`.

`global_router.route_global_once(...)` and `global_router.route_global(...)` can return `GlobalRouteResult.paths: Mapping[NetId, tuple[Cell, ...]]` (`global_router.py:41-55, 110-185`), but they are search/metrics passes. They do not emit buildings or mutate the production canvas, and using them would not be a predetermined no-search fallback.

### 5. Existing completion tail remains authoritative

After successful routing, `_build_prepared` clears attempt-local reservations, calls the exact power emitter

```python
def _place_power(canvas: _Canvas, sites: Sequence[tuple[int, int]]) -> int
```

at `freeform.py:13884`/`15730-15739`, derives sorter geometry with `assign_sorter_slots(canvas.buildings)` at `freeform.py:15741-15755`, constructs `Placement`, and calls `retier_belts(placement, spec)` at `freeform.py:15757-15780`.

The production validation stage then retains the separate final authorities:

```python
def finalize_placement(
    placement: Placement,
    policy: BandPolicy,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Placement
```

at `src/flab2bp/layout/finalize.py:2690-2695`, and

```python
def certify(placement: Placement, spec: BuildSpec, *, expect_power: bool) -> Report
```

at `src/flab2bp/layout/validate.py:5976`. The production adapter invokes finalization and certification at `sequence_solver.py:5174-5220`. A future no-search emitter should reuse this power, slot, retier, finalization, and certification tail rather than introducing parallel authority.

## Blocking invariant

No public or internal detailed-emission boundary accepts and enforces a complete `LogicalNetId`/`NetId` assignment to deterministic tracks and levels for every internal, external-input, and external-output net. `_build_prepared` has only search-or-skip behavior; `_route_all` searches; boundary emission is coupled to `_route_boundary_nets` search; and `_commit_paths` requires already-complete cell sequences keyed by transient indices.

Assigning `(track, level)` is not the same as providing the complete `Cell` path required by `_commit_paths`. A track and level identify a corridor choice, but do not specify the ordered source approach, exact endpoint cell, bends, crossings, level transitions, boundary direction, collision-free occupation, or source/sink links. Turning that assignment into a legal `Sequence[Cell]` is itself missing deterministic-template emission work. The existing emitter cannot consume the reviewed predetermined assignment as-is, and silently falling back to `_astar` would violate the no-search invariant.

## Smallest future interface contract

A separate reviewed interface plan must precede implementation. The smallest viable design is either one prepared-template emission facade or one mutually exclusive optional argument on `_build_prepared`, with the effective contract:

```python
template_paths: Mapping[NetId, Sequence[Cell]]
```

When supplied, the boundary must canonicalize the mapping to immutable path tuples and then:

1. Resolve and validate every prepared logical identity exactly once, expanding that identity to its complete prepared set of physical `NetId` branches. Because one `LogicalNetId` may fan out to several physical branches, require exactly one path for each full prepared `NetId`; never silently alias one logical assignment across branches.
2. Reject unknown identities, duplicate or alias-resolved identities, missing internal/input/output identities, empty or disconnected paths, out-of-bounds cells, illegal endpoints or level transitions, and conflicts with prepared buildings, reserved power sites, or other supplied paths.
3. Bypass `_route_all`, `_route_external_inputs`, `_route_external_outputs`, `_route_boundary_nets` search, `_astar`, global routing, and every negotiated route-search pass.
4. Translate validated stable `NetId` keys to workspace net indices once; commit internal cell sequences through the reusable `_commit_paths` belt/link logic; and factor a no-search boundary commit path from `_route_boundary_nets` so external inputs and outputs consume their supplied complete sequences too.
5. Fail closed through existing detailed-routing/commit refusal authority if any prescribed path cannot be emitted. Do not repair, substitute, or search for another path.
6. On successful commit, continue through existing `_place_power`, `assign_sorter_slots`, `Placement`, `retier_belts`, `finalize.finalize_placement`, and `validate.certify` authority unchanged.

This missing contract is the reviewed stop condition; implementing it or the upstream deterministic conversion from `(track, level)` to complete paths is outside this gate.

F0: TEMPLATE API GAP
