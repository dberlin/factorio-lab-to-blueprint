# Portable Latitude Bands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make portable three-band spherical certification the default, expose explicit single-band selection, prevent known projected failures during search, retain structured refusals, and correct addon-supply termination warnings within the approved performance gate.

**Architecture:** `BandPolicy` carries the request through CLI/web/pipeline/layouts. An immutable `AreaFrame` becomes the sole finalized-area and encoder authority. Finalization searches both physical orientations plus zero-to-four latitude-padding rows, then certifies every legal anchor in the primary and required wider bands. Freeform reuses the same projected power and coater/Splitter predicates and feeds exact static collision pairs back to CP-SAT as relative-position no-goods. SequencePair and Freeform preserve structured failures through terminal reporting.

**Tech Stack:** Python 3.14, dataclasses, OR-Tools CP-SAT, pytest, mypy, Ruff, TypeScript 5.9, React 19, Zod, Rstest, Biome, Chromium.

**Spec:** `docs/superpowers/specs/2026-08-28-portable-bands-and-flow-fetch-design.md`

## Global Constraints

- Required Python runtime remains `>=3.14`.
- Portable mode certifies the globally smallest fitting band and up to two wider bands; it never silently downgrades or promotes the primary band.
- Latitude padding is zero through four total rows, every south/north split, and no longitude padding.
- Explicit band choices are exactly `4|8|16|20|32|40|60|80|100|120|160|200`; request/JSON values are strings.
- Every required band is certified at every legal anchor with the same orientation, frame, and building coordinates.
- `AreaFrame` is the sole encoded area authority; remove obsolete stats authority without compatibility aliases.
- Preserve current SequencePair deadline semantics and `flow.external_entry_points` behavior.
- Severe performance regression means more than 1 second added p95 or more than 10% end-to-end; optimize invariant work before changing the guarantee.
- Before exported-symbol modification, run LSP references where available. TypeScript currently has no configured LSP, so use its schema/tests and narrow searches.
- Tasks 3–6 stage portable machinery behind an internal `policy=None` path that preserves current single-band production behavior; Task 7 deletes that path while atomically making Portable public/default, so no compatibility mode remains in the final tree.
- Every production change follows red-green TDD. Run focused checks per task and project-wide checks only in Task 10.

---

### Task 1: Freeze performance inputs and capture the baseline

**Files:**
- Create: `scripts/benchmark_projection.py`
- Create: `tests/fixtures/projection/small.json`
- Create: `tests/fixtures/projection/medium.json`
- Create: `tests/fixtures/projection/large.json`
- Create: `tests/scripts/test_benchmark_projection.py`
- Modify: `scripts/audit.py`

**Interfaces:**
- Consumes: current `finalize.finalize_placement(placement: Placement) -> Placement` and audit JSON serialization.
- Produces: `run_benchmark(samples: int) -> BenchmarkResult`, `benchmark_projection.main(argv: Sequence[str] | None = None) -> int`, immutable placement JSON fixtures, and audit fields used by Task 9.

- [ ] **Step 1: Write the failing benchmark contract test**

The benchmark must load three checked-in placements without solving/routing and return JSON with per-case `median_s`, `p95_s`, `frame_candidates`, `projections`, `collider_pairs`, `power_pairs`, `sorters`, and `area`. Add an audit JSON assertion for `build_wall_time_s` and finalization counters.

```python
def test_benchmark_result_has_stable_cases_and_counters() -> None:
    result = run_benchmark(samples=2)
    assert set(result["cases"]) == {"small", "medium", "large"}
    for case in result["cases"].values():
        assert case["median_s"] >= 0.0
        assert case["p95_s"] >= case["median_s"]
        assert set(case) >= {
            "frame_candidates",
            "projections",
            "collider_pairs",
            "power_pairs",
            "sorters",
            "area",
        }
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/scripts/test_benchmark_projection.py -q
```

Expected: failure because the command and fields do not exist.

- [ ] **Step 3: Implement the timing boundary**

Generate the checked-in fixtures once from corpus entries `graphene` (small), `processor` (medium), and `casimir-crystal` (large), using explicit Freeform with one worker and each corpus tier's existing budget. Serialize the successful placement after removing `area_segments`/`band_rotated` from copied stats; after Task 2, also clear `frame`. The benchmark loader therefore always receives unfinalized geometry. Time only `finalize.finalize_placement()` with `perf_counter_ns()`. Report median and inclusive p95. Normalize counters absent from the baseline finalizer to zero. Extend audit JSON records without changing solve selection.

```python
class CaseResult(TypedDict):
    median_s: float
    p95_s: float
    frame_candidates: int
    projections: int
    collider_pairs: int
    power_pairs: int
    sorters: int
    area: int


class BenchmarkResult(TypedDict):
    cases: dict[str, CaseResult]


def _time_case(placement: Placement, samples: int) -> CaseResult:
    elapsed: list[float] = []
    finalized: Placement | None = None
    for _sample in range(samples):
        started = time.perf_counter_ns()
        finalized = finalize.finalize_placement(placement)
        elapsed.append((time.perf_counter_ns() - started) / 1_000_000_000)
    assert finalized is not None
    ordered = sorted(elapsed)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return CaseResult(
        median_s=statistics.median(ordered),
        p95_s=p95,
        frame_candidates=int(finalized.stats.get("projection_frame_candidates", 0)),
        projections=int(finalized.stats.get("projection_count", 0)),
        collider_pairs=int(finalized.stats.get("projection_collider_pairs", 0)),
        power_pairs=int(finalized.stats.get("projection_power_pairs", 0)),
        sorters=int(finalized.stats.get("projection_sorters", 0)),
        area=finalized.area,
    )
```
Command contract:

```bash
uv run python scripts/benchmark_projection.py --samples 20 --output /tmp/portable-band-baseline.json
```

- [ ] **Step 4: Capture baseline evidence**

```bash
uv run pytest tests/scripts/test_benchmark_projection.py -q
uv run python scripts/benchmark_projection.py --samples 20 --output /tmp/portable-band-baseline.json
uv run python scripts/audit.py --tier small --budget 4 --strategy both --jobs 1 --json /tmp/portable-band-build-baseline.json
```

Preserve both `/tmp` baselines through Task 9.

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_projection.py scripts/audit.py tests/scripts/test_benchmark_projection.py tests/fixtures/projection
git commit -m "test: freeze projection performance baseline"
```

### Task 2: Introduce BandPolicy and AreaFrame with a clean encoder cutover

**Files:**
- Create: `src/flab2bp/layout/band_policy.py`
- Modify: `src/flab2bp/layout/base.py`
- Modify: `src/flab2bp/dsp/codec.py`
- Modify: `tests/layout/test_base.py`
- Modify: `tests/dsp/test_encode.py`
- Modify: finalized-placement fixtures currently using `stats["area_segments"]`

**Interfaces:**
- Consumes: `planet.bands()` and existing `Placement`/`PlacedBuilding` bounds.
- Produces: `BandSelection`, `BAND_SELECTIONS`, `BandPolicy.parse(value: str) -> BandPolicy`, `AreaFrame`, and `Placement.frame`.

- [ ] **Step 1: Write failing model/encoder tests**

Cover:

```python
assert BandPolicy.parse("portable") == BandPolicy("portable")
assert BandPolicy.parse("160").explicit_segments == 160
with pytest.raises(ValueError, match="latitude band"):
    BandPolicy.parse("240")

frame = AreaFrame(12, 7, 40, (40, 60, 80), False)
assert replace(placement, frame=frame).area == 84
```

Encoder tests must reject unframed placements and buildings/second anchors outside the frame, read dimensions/band only from `Placement.frame`, and ignore no stats compatibility path.

```bash
uv run pytest tests/layout/test_base.py tests/dsp/test_encode.py -q
```

Expected: failures because these types do not exist.

- [ ] **Step 2: Implement the shared policy**

In `layout/band_policy.py`:

```python
type BandSelection = Literal[
    "portable", "4", "8", "16", "20", "32", "40",
    "60", "80", "100", "120", "160", "200",
]

BAND_SELECTIONS: tuple[BandSelection, ...] = (
    "portable", "4", "8", "16", "20", "32", "40",
    "60", "80", "100", "120", "160", "200",
)

@dataclass(frozen=True, slots=True)
class BandPolicy:
    selection: BandSelection

    @classmethod
    def parse(cls, value: str) -> "BandPolicy":
        if value not in BAND_SELECTIONS:
            raise ValueError(f"unknown latitude band {value!r}")
        return cls(cast(BandSelection, value))

    @property
    def explicit_segments(self) -> int | None:
        return None if self.selection == "portable" else int(self.selection)
```

Use a strict typed cast or `TypeGuard`; no `Any`.

- [ ] **Step 3: Implement AreaFrame and Placement semantics**

In `layout/base.py`:

```python
@dataclass(frozen=True, slots=True)
class AreaFrame:
    width: int
    height: int
    primary_band: int
    certified_bands: tuple[int, ...]
    rotated: bool
```

Validate positive dimensions, non-empty bands, and `certified_bands[0] == primary_band`. Add `frame: AreaFrame | None = None` to `Placement`. `Placement.area` uses frame area after finalization and building-bounds area before it. Remove `area_segments` and `band_rotated` from `PlacementStats`.

- [ ] **Step 4: Cut encoder authority over**

`codec._area_for()` requires `placement.frame`, validates all footprints and second anchors inside it, validates the primary band exists/can hold the frame, and emits width/height/area segments from the frame. Migrate tests/callers; no alias or fallback.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/layout/test_base.py tests/dsp/test_encode.py -q
uv run ruff check src/flab2bp/layout/base.py src/flab2bp/layout/band_policy.py src/flab2bp/dsp/codec.py tests/layout/test_base.py tests/dsp/test_encode.py
uv run mypy src/flab2bp/layout/base.py src/flab2bp/layout/band_policy.py src/flab2bp/dsp/codec.py
git add src/flab2bp/layout/base.py src/flab2bp/layout/band_policy.py src/flab2bp/dsp/codec.py tests
git commit -m "feat: make area frames explicit"
```

### Task 3: Implement portable and explicit frame certification

**Files:**
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `src/flab2bp/dsp/planet.py`
- Modify: `tests/layout/test_finalize.py`
- Modify: `tests/dsp/test_planet.py`
- Modify: `tests/dsp/test_encode.py`

**Interfaces:**
- Consumes: `BandPolicy`, `AreaFrame`, `planet.Band`, `planet.Fit`, and existing projected legality predicates.
- Produces: `ProjectionFailure`, `ProjectionRefusal.failures`, `FrameCandidate`, `target_bands()`, `_frame_candidate(placement, policy, *, rotated, south_padding, north_padding) -> FrameCandidate | None`, `frame_candidates()`, and the temporary migration signature `finalize_placement(placement, policy: BandPolicy | None = None)`.

- [ ] **Step 1: Write failing selection tests**

Assert: globally smallest `B0`; required bands `B0` plus next two greater segment counts; `160 -> (160, 200)`; `200 -> (200,)`; every south/north split for zero-to-four added rows; deterministic key `(frame area, added rows, rotation, south padding)`; same frame/coordinates checked at every legal anchor; explicit mode certifies only its requested band; portable never promotes `B0`; five-row polar bands pass unpadded or refuse; unchanged framed finalization is idempotent.

```python
def test_portable_targets_stop_at_the_equator() -> None:
    by_segments = {band.area_segments: band for band in planet.bands()}
    assert tuple(b.area_segments for b in target_bands(by_segments[160], BandPolicy(\"portable\"))) == (160, 200)
    assert tuple(b.area_segments for b in target_bands(by_segments[200], BandPolicy(\"portable\"))) == (200,)


def test_explicit_policy_certifies_only_requested_band() -> None:
    finalized = finalize_placement(_small_placement(), BandPolicy(\"40\"))
    assert finalized.frame is not None
    assert finalized.frame.primary_band == 40
    assert finalized.frame.certified_bands == (40,)
```

```bash
uv run pytest tests/layout/test_finalize.py tests/dsp/test_planet.py tests/dsp/test_encode.py -q
```

Expected: portable/padding/explicit assertions fail.

- [ ] **Step 2: Make failures structured**

Replace the tuple alias with:

```python
@dataclass(frozen=True, slots=True)
class ProjectionFailure:
    check: str
    buildings: tuple[int, ...]
    detail: str
    band: int
```

`ProjectionRefusal.failures` is ordered and deduplicated. Keep concise `checks`, but `str(exc)` includes band, indices, and detail. Every projected predicate returns this type; never parse band from prose.

- [ ] **Step 3: Enumerate frames and targets**

Add:

```python
@dataclass(frozen=True, slots=True)
class FrameCandidate:
    frame: AreaFrame
    south_padding: int
    added_rows: int


def target_bands(primary: planet.Band, policy: BandPolicy) -> tuple[planet.Band, ...]:
    if policy.explicit_segments is not None:
        return (primary,)
    ordered = tuple(sorted(planet.bands(), key=lambda band: band.area_segments))
    start = ordered.index(primary)
    return ordered[start : start + 3]


def frame_candidates(
    placement: Placement,
    policy: BandPolicy,
) -> tuple[FrameCandidate, ...]:
    candidates: list[FrameCandidate] = []
    for rotated in (False, True):
        for added_rows in range(5):
            for south_padding in range(added_rows + 1):
                candidate = _frame_candidate(
                    placement,
                    policy,
                    rotated=rotated,
                    south_padding=south_padding,
                    north_padding=added_rows - south_padding,
                )
                if candidate is not None:
                    candidates.append(candidate)
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.frame.width * candidate.frame.height,
                candidate.added_rows,
                candidate.frame.rotated,
                candidate.south_padding,
            ),
        )
    )
```

Portable establishes `B0` once from unpadded bounds, discards orientations not fitting it, and selects `B0` plus up to two wider bands. Explicit mode selects exactly the named terrestrial band. Enumerate added rows `0..4` and all south/north splits, reject frames exceeding primary capacity, add no longitude padding, sort by the approved key.

- [ ] **Step 4: Certify every anchor efficiently**

Normalize buildings into frame-local coordinates and add south padding. For each frame, evaluate every `band.anchors(frame.height)` in every required band. Extract power nodes, seated sorters, static `Placed` records, coaters, and splitters once per frame; cache candidate pairs per band. Count frame candidates, projections, collider pairs, power pairs, and sorters in numeric stats.

Until Task 7, `policy=None` must execute the current smallest-single-band selection while attaching a one-band `AreaFrame`; this keeps each intermediate commit deployable without exposing Portable before search is projection-aware. With a policy, use the new portable/explicit search. A framed placement returns unchanged only after frame-content validation and only when its certification satisfies the requested policy. Modified membership/coordinates clear `frame`; `finalize._remove_buildings()` and boundary compaction do so before recertification. Task 7 removes `None` and makes `BandPolicy("portable")` the only default.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/layout/test_finalize.py tests/dsp/test_planet.py tests/dsp/test_encode.py -q
uv run ruff check src/flab2bp/layout/finalize.py src/flab2bp/dsp/planet.py tests/layout/test_finalize.py tests/dsp/test_planet.py tests/dsp/test_encode.py
uv run mypy src/flab2bp/layout/finalize.py src/flab2bp/dsp/planet.py
git add src/flab2bp/layout/finalize.py src/flab2bp/dsp/planet.py tests/layout/test_finalize.py tests/dsp/test_planet.py tests/dsp/test_encode.py
git commit -m "feat: certify portable latitude frames"
```


### Task 4: Reuse projected power legality during Freeform planning

**Files:**
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_finalize.py`
- Modify: `tests/layout/test_freeform.py`


**Interfaces:**
- Consumes: `BandPolicy`, `FrameCandidate`, `ProjectionFailure`, and current `_power_plan(canvas, core)`.
- Produces: `projected_power_failure(nodes, projection) -> ProjectionFailure | None` and the staged `_power_plan(..., policy: BandPolicy | None = None)`; Task 7 makes policy required.
- [ ] **Step 1: Write RED**

Construct the flat-legal diagonal Tesla Tower pair that projects below 3.5 world units in a required projection. Assert shared predicate failure and `_power_plan()` rejection; add a legal control.

```python
def test_power_plan_rejects_pair_illegal_in_required_projection() -> None:
    projections = _required_projection_fixture(primary_band=40)
    failure = next(
        (
            projected_power_failure(_diagonal_tesla_pair(), projection)
            for projection in projections
            if projected_power_failure(_diagonal_tesla_pair(), projection) is not None
        ),
        None,
    )
    assert failure is not None
    assert failure.check == \"game.power_too_close\"
    assert failure.band in (40, 60, 80)
```

```bash
uv run pytest tests/layout/test_finalize.py tests/layout/test_freeform.py -q -k "power and projection"
```

- [ ] **Step 2: Extract and reuse one predicate**

Move pair evaluation around `rules.power_node_condition()` into one helper accepting indexed nodes plus one `planet.Projection` and returning `ProjectionFailure | None`. Finalizer and Freeform both call it.

Pass `BandPolicy` through Freeform `_build()` to `_power_plan()`. Derive a conservative projection envelope from fixed `canvas.limit` or packing extent. Reject candidate sites illegal in any required band/anchor; do not inflate a flat radius. Preserve `_Unpowerable` band/check/detail evidence rather than collapsing to `power.coverage`.

```python
def projected_power_failure(
    nodes: Sequence[tuple[int, PlacedBuilding, rules.PowerNode]],
    projection: planet.Projection,
) -> ProjectionFailure | None:
    poses = tuple(projection.position(*_building_centre(building)) for _, building, _ in nodes)
    for left, right in combinations(range(len(nodes)), 2):
        condition = _power_pair_condition(nodes[left], nodes[right], math.dist(poses[left], poses[right]) ** 2)
        if condition is not None:
            return ProjectionFailure(
                check=\"game.power_too_close\",
                buildings=(nodes[left][0], nodes[right][0]),
                detail=condition,
                band=projection.band.area_segments,
            )
    return None
```

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/layout/test_finalize.py tests/layout/test_freeform.py -q -k "power or projection"
uv run ruff check src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py tests/layout/test_finalize.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py tests/layout/test_finalize.py tests/layout/test_freeform.py
git commit -m "fix: plan power in required projections"
```

### Task 5: Reuse projected Spray Coater/Splitter keepout before routing

**Files:**
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_finalize.py`
- Modify: `tests/layout/test_freeform.py`


**Interfaces:**
- Consumes: the Task 3 projection envelope, `ProjectionFailure`, current `_place_coaters()`, and existing exact expanded OBB logic.
- Produces: `projected_coater_splitter_failure(coater, splitter, projection) -> ProjectionFailure | None` and staged `_place_coaters(..., policy: BandPolicy | None = None)`; Task 7 makes policy required.

- [ ] **Step 1: Write RED**

Use the known `broke2` coater/Splitter pair. Assert `game.addon_splitter_clearance`, rejection by `_place_coaters()` before detailed routing, and legality after the known separation.

```python
def test_coater_seat_rejects_projected_splitter_keepout() -> None:
    failure = projected_coater_splitter_failure(
        coater=_broke2_coater(),
        splitter=_broke2_splitter(),
        projection=_broke2_projection(),
    )
    assert failure is not None
    assert failure.check == \"game.addon_splitter_clearance\"
```

```bash
uv run pytest tests/layout/test_finalize.py tests/layout/test_freeform.py -q -k "coater and splitter"
```

- [ ] **Step 2: Extract and reuse exact projected OBB logic**

One helper evaluates one coater/Splitter pair under one projection. Finalizer calls it over cached pairs. `_place_coaters()` evaluates proposed coaters against existing splitters over the current policy envelope before adding coater/drop. Do not widen unrelated `_coater_keepout_hits()` or add a global margin.

```python
def projected_coater_splitter_failure(
    coater: tuple[int, colliders.Placed],
    splitter: tuple[int, colliders.Placed],
    projection: planet.Projection,
) -> ProjectionFailure | None:
    if not _projected_coater_keepout_overlaps(coater[1], splitter[1], projection):
        return None
    return ProjectionFailure(
        check=\"game.addon_splitter_clearance\",
        buildings=(coater[0], splitter[0]),
        detail=\"Splitter connection body enters the Spray Coater projected lateral keepout\",
        band=projection.band.area_segments,
    )
```

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/layout/test_finalize.py tests/layout/test_freeform.py -q -k "coater or splitter or addon"
uv run ruff check src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py tests/layout/test_finalize.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py tests/layout/test_finalize.py tests/layout/test_freeform.py
git commit -m "fix: reserve projected coater clearance"
```

### Task 6: Feed exact static collisions back to packing and retain refusal evidence

**Files:**
- Modify: `src/flab2bp/layout/base.py`
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: `tests/layout/test_freeform.py`, `tests/layout/test_sequence_solver.py`, `tests/test_pipeline.py`


**Interfaces:**
- Consumes: structured `ProjectionFailure`, `_Pack.at`, CP-SAT strip-origin variables, and `StageObservation.validation_failures`.
- Produces: non-encoded `PlacedBuilding.owner_strip`, `ProjectionNoGood`, `_pack(..., projection_no_goods)`, and structured Freeform/SequencePair/pipeline refusal output.
- [ ] **Step 1: Write RED**

Assert Freeform terminal refusal includes check/band/indices/detail; a two-strip projected collision creates a pair-specific retry and separated alternative; unrelated pairs remain unchanged; SequencePair terminal refusal includes accumulated `StageObservation.validation_failures`; pipeline preserves structured exception text.

```python
def test_projection_no_good_forbids_only_rejected_relative_displacement() -> None:
    bad = ProjectionNoGood(1, 3, -4, 7, _collision_failure())
    retry = _pack(_strips(), height=20, width_bound=40, projection_no_goods=(bad,))
    assert retry is not None
    assert (
        retry.at[1][0] - retry.at[3][0],
        retry.at[1][1] - retry.at[3][1],
    ) != (-4, 7)
```

```bash
uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/test_pipeline.py -q -k "projection or refusal or no_good"
```

- [ ] **Step 2: Add provenance and exact no-goods**

Add non-encoded `owner_strip: int | None = None` to `PlacedBuilding`. Thread strip index through `_emit_strip()` for strip-owned static objects; global infrastructure remains unowned.

```python
@dataclass(frozen=True, slots=True)
class ProjectionNoGood:
    left_strip: int
    right_strip: int
    delta_x: int
    delta_y: int
    failure: ProjectionFailure
```

On `geom.collide` between distinct owned strips, derive current relative strip-origin displacement and deduplicate it. `_pack(..., projection_no_goods=())` creates `dx/dy` integer variables tied to strip-origin differences and uses `add_forbidden_assignments([dx, dy], [(bad_dx, bad_dy)])`. This excludes only that relative arrangement—no blanket clearance and no candidate blacklist.

```python
for index, no_good in enumerate(projection_no_goods):
    dx = model.new_int_var(-width_bound, width_bound, f\"projection_dx_{index}\")
    dy = model.new_int_var(-height, height, f\"projection_dy_{index}\")
    model.add(dx == xs[no_good.left_strip] - xs[no_good.right_strip])
    model.add(dy == ys[no_good.left_strip] - ys[no_good.right_strip])
    model.add_forbidden_assignments([dx, dy], [(no_good.delta_x, no_good.delta_y)])
```

Refactor `_sweep()` so a newly learned no-good can request another pack inside the original deadline rather than after every pack has been precomputed. Same-strip/unowned failures retain evidence but create no global cut.

- [ ] **Step 3: Preserve terminal evidence**

Replace Freeform `rejected: set[str]` with ordered structured findings. Keep concise distinct checks followed by authoritative records. SequencePair aggregates distinct validation failures from observations while keeping deadline wording/semantics. Pipeline uses structured `ProjectionRefusal` text.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/test_pipeline.py -q -k "projection or refusal or no_good"
uv run ruff check src/flab2bp/layout/base.py src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py src/flab2bp/pipeline.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/test_pipeline.py
uv run mypy src/flab2bp/layout/base.py src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py src/flab2bp/pipeline.py
git add src/flab2bp/layout/base.py src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py src/flab2bp/pipeline.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/test_pipeline.py
git commit -m "fix: feed projected collisions back to packing"
```

### Task 7: Plumb band selection through every public surface

**Files:**
- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/cli.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/web/jobs.py`
- Modify: `src/flab2bp/web/payload.py`
- Modify: `web/src/api/build.ts`
- Modify: `web/src/ui/BuildPanel.tsx`
- Modify: `web/src/ui/BuildReport.tsx`
- Modify: `tests/test_pipeline.py`, `tests/test_pipeline_cli_strategy.py`, `tests/web/test_jobs.py`, `tests/web/test_payload.py`
- Modify: `web/tests/api/build.test.ts`, `web/tests/ui/BuildPanel.test.tsx`
- Create: `web/tests/ui/BuildReport.test.tsx`


**Interfaces:**
- Consumes: `BandSelection`, `BAND_SELECTIONS`, `BandPolicy`, `Placement.frame`, and policy-aware layout constructors/finalizers.
- Produces: `pipeline.build(..., band: BandSelection = "portable")`, Python/TypeScript `band` options, CLI `--band`, and result `primary_band`/`certified_bands`.
- [ ] **Step 1: Write failing Python contract tests**

Assert pipeline default `band="portable"`, identical policy at strategy/finalizer, exact CLI choices, string-only web parsing, payload fields `primary_band`/`certified_bands`, and literal CLI reporting for one/two/three certified bands.

```python
def test_build_defaults_to_portable_band(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[BandPolicy] = []
    monkeypatch.setattr(pipeline, \"_new_layout\", _layout_spy(seen))
    pipeline.build(URL, candidates=1, time_budget_s=0.1)
    assert seen == [BandPolicy(\"portable\"), BandPolicy(\"portable\")]


def test_payload_reports_literal_certified_bands(build: Build) -> None:
    result = payload.describe(build)
    assert result[\"primary_band\"] == 160
    assert result[\"certified_bands\"] == [160, 200]
```

```bash
uv run pytest tests/test_pipeline.py tests/test_pipeline_cli_strategy.py tests/web/test_jobs.py tests/web/test_payload.py -q
```

- [ ] **Step 2: Write failing frontend tests**

Use the exact Zod enum:

```ts
z.enum(["portable", "4", "8", "16", "20", "32", "40", "60", "80", "100", "120", "160", "200"])
```

Assert default submission, changed selection, and literal result rendering.

```ts
expect(DEFAULT_OPTIONS.band).toBe(\"portable\");
await user.selectOptions(screen.getByLabelText(\"Latitude band\"), \"160\");
await user.click(screen.getByRole(\"button\", { name: \"Build\" }));
expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({
  band: \"160\",
});
```

```bash
bun --cwd web run test -- tests/api/build.test.ts tests/ui/BuildPanel.test.tsx tests/ui/BuildReport.test.tsx
```

- [ ] **Step 3: Implement plumbing**

Parse `pipeline.build(..., band: BandSelection = "portable")` once, pass policy through `_new_layout()` into both layout constructors, all internal finalizers, and pipeline defense-in-depth. In the same cutover, remove every Task 3–6 `policy=None` branch/default so no hidden single-band mode remains. Add CLI `--band` with `BAND_SELECTIONS`. Add Python/TypeScript web option default `portable`. Add selector label `Latitude band` with `Portable (smallest + two wider)` and numeric options. Successful CLI/payload/report paths must refuse unexpectedly unframed placements instead of omitting evidence.

```python
# Add to build()'s keyword-only parameters.
band: BandSelection = "portable",

policy = BandPolicy.parse(band)
layout = _new_layout(
    sname,
    power=power,
    belt_vertical_construction=belt_rules.vertical_construction,
    sequence_islands=sequence_islands,
    band_policy=policy,
)
placement = finalize.finalize_placement(placement, policy)
```

```ts
export const BandSelection = z.enum([
  'portable', '4', '8', '16', '20', '32', '40',
  '60', '80', '100', '120', '160', '200',
]);

// Add inside the existing BuildOptions object.
band: BandSelection,
```

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/test_pipeline.py tests/test_pipeline_cli_strategy.py tests/web/test_jobs.py tests/web/test_payload.py -q
bun --cwd web run test -- tests/api/build.test.ts tests/ui/BuildPanel.test.tsx tests/ui/BuildReport.test.tsx
uv run mypy src/flab2bp/pipeline.py src/flab2bp/cli.py src/flab2bp/web/jobs.py src/flab2bp/web/payload.py
bun --cwd web run typecheck
git add src/flab2bp/pipeline.py src/flab2bp/cli.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py src/flab2bp/web/jobs.py src/flab2bp/web/payload.py web tests
git commit -m "feat: expose latitude band policy"
```

### Task 8: Count positional addon-supply belts as termination taps

**Files:**
- Modify: `src/flab2bp/layout/validate.py`
- Modify: `tests/layout/test_validate.py`


**Interfaces:**
- Consumes: `_termination()`, `_belt_in_addon_area()`, catalog addon areas, and existing sorter tap indices.
- Produces: termination tap accounting that includes positional addon-supply belt indices.
- [ ] **Step 1: Write RED**

A proliferator lane containing the belt selected by `_belt_in_addon_area()` for a Spray Coater must not receive all-lane-wasted `belt.termination`. An otherwise identical lane with no sorter/addon consumer must still warn.

```python
def test_addon_supply_belt_is_a_termination_tap() -> None:
    report = _termination_report(_supplied_coater_lane())
    assert not any(
        finding.check == \"belt.termination\" and \"entire lane\" in finding.message
        for finding in report.warnings
    )


def test_unconsumed_lane_still_warns() -> None:
    report = _termination_report(_unconsumed_control_lane())
    assert any(finding.check == \"belt.termination\" for finding in report.warnings)
```

```bash
uv run pytest tests/layout/test_validate.py -q -k "termination and addon"
```

- [ ] **Step 2: Implement**

In `_termination()`, retain sorter-based taps, then add positional addon consumers with the existing helper:

```python
for addon in ctx.placement.buildings:
    try:
        areas = cat.building(addon.item_id).addon_areas
    except KeyError:
        continue
    if len(areas) < 2:
        continue
    for area in areas:
        belt_index = _belt_in_addon_area(ctx, addon, area=area.area)
        if belt_index is not None:
            touched.add(belt_index)
```

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/layout/test_validate.py -q -k "termination or addon_supply"
uv run ruff check src/flab2bp/layout/validate.py tests/layout/test_validate.py
uv run mypy src/flab2bp/layout/validate.py tests/layout/test_validate.py
git add src/flab2bp/layout/validate.py tests/layout/test_validate.py
git commit -m "fix: count addon supply as a belt tap"
```

### Task 9: Enforce the performance gate

**Files:**
- Modify: `scripts/benchmark_projection.py`
- Modify if needed: `src/flab2bp/layout/finalize.py`
- Modify: `tests/layout/test_finalize.py`
- Modify: `tests/scripts/test_benchmark_projection.py`


**Interfaces:**
- Consumes: Task 1 baseline JSON, finalization counters, and post-change frozen/audit results.
- Produces: `/tmp/portable-band-comparison.json` with per-case thresholds and any proven invariant-work caches.
- [ ] **Step 1: Compare identical frozen placements**

```bash
uv run python scripts/benchmark_projection.py --samples 20 --baseline /tmp/portable-band-baseline.json --output /tmp/portable-band-after.json
uv run python scripts/audit.py --tier small --budget 4 --strategy both --jobs 1 --json /tmp/portable-band-build-after.json
uv run python scripts/benchmark_projection.py --compare-builds /tmp/portable-band-build-baseline.json /tmp/portable-band-build-after.json --output /tmp/portable-band-comparison.json
```

Report each case's median/p95, counters, emitted area, and build-wall-time delta. Severe is >1 second added p95 or >10% end-to-end for any case; do not average it away.

- [ ] **Step 2: If severe, optimize invariant work then rerun**

Profile and cache in order: seated sorter reconstruction; power-node extraction/centers; collision `Placed` records; per-band candidate pairs; projection objects for `(band, frame height, anchor, rotation)`. Add cache-reuse counter assertions. Do not weaken bands or padding. If still severe, stop and return exact comparison JSON for explicit product decision.

- [ ] **Step 3: Commit**

```bash
git add scripts/benchmark_projection.py tests/scripts/test_benchmark_projection.py src/flab2bp/layout/finalize.py tests/layout/test_finalize.py
git commit -m "perf: bound portable projection certification"
```

### Task 10: Document and verify actual surfaces

**Files:**
- Modify: `README.md`
- Modify: `docs/WEB_UI.md`
- Modify: `docs/BACKLOG.md`


**Interfaces:**
- Consumes: completed CLI/web contracts, full verification commands, and Task 9 comparison JSON.
- Produces: durable user documentation plus actual CLI and browser behavioral evidence.
- [ ] **Step 1: Update durable docs**

Document portable default, exact `--band` values, up-to-four latitude rows/no longitude padding, explicit refusal semantics, result bands, structured evidence, and unchanged multiple external-entry warning. Remove single-band-default claims; never claim every planetary band.

- [ ] **Step 2: Run complete checks via context-mode**

```bash
uv run pytest
uv run ruff check .
uv run mypy
bun --cwd web run test
bun --cwd web run lint
bun --cwd web run typecheck
bun --cwd web run build
```

Expected: all pass with only established skips.

- [ ] **Step 3: Exercise actual CLI**

Use the smallest deterministic repository smoke URL:

```bash
uv run flab2bp "$SMOKE_URL" --strategy freeform --candidate-policy no-proliferator --budget 4 --band portable -o /tmp/freeform-portable.txt
uv run flab2bp "$SMOKE_URL" --strategy sequence-pair --sequence-islands 1 --candidate-policy no-proliferator --budget 4 --band portable -o /tmp/sequence-portable.txt
uv run flab2bp "$SMOKE_URL" --strategy freeform --candidate-policy no-proliferator --budget 4 --band 200 -o /tmp/freeform-band-200.txt
```

Reports must name exact bands and outputs must decode. Use an existing deterministic smaller fixture if a chosen URL legitimately exhausts budget; do not raise budget to hide semantics.

- [ ] **Step 4: Browser-drive actual web UI**

Start `bun run dev` through the harness process manager and wait for ports 8000/3001. Verify portable selector default, successful result bands, explicit 200 reporting only 200, and unchanged progress/result behavior. Component tests are insufficient.

- [ ] **Step 5: Report performance evidence and commit docs**

Read `/tmp/portable-band-comparison.json`; report exact figures and only claim gate success if both thresholds pass.

```bash
git add README.md docs/WEB_UI.md docs/BACKLOG.md
git commit -m "docs: explain portable latitude certification"
```

## Completion checklist

- `AreaFrame` is the sole encoder authority; obsolete stats fields are removed.
- Portable certifies `B0` plus up to two wider bands at every legal anchor.
- Explicit selection certifies only its requested band with the same padding search.
- Shared projected power and coater/Splitter predicates run before routing.
- Static collision retries use exact relative strip no-goods.
- Structured evidence reaches Freeform, SequencePair, pipeline, CLI, and web.
- Positional addon supply counts as a termination tap; external-entry warnings are unchanged.
- Python and TypeScript expose identical band strings.
- Frozen finalization and end-to-end gates pass, or measured evidence blocks completion for a product decision.
- Full checks, CLI smoke, and browser verification pass.
