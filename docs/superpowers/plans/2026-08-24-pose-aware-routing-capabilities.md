# Pose-Aware Routing Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make machine orientation, exact slot-anchor lane reach, and elevated Spray Coater supply first-class sequence-pair search and routing capabilities.

**Architecture:** Merge the finalized game-extracted pose/slot/altitude interfaces, then represent each physical strip as one pose-homogeneous variant with exact lane and attachment plans. Sequence-pair SA searches variants and feedback-driven split/merge LNS; global and detailed routers terminate proliferator nets at elevated coater addon ports. Detailed routing plus validation remains the only acceptance authority.

**Tech Stack:** Python 3.12, authoritative game-extracted JSON/catalog pose data, deterministic sequence-pair SA/LNS, existing relaxed and detailed routers, pytest, Ruff, strict mypy.

**Spec:** `docs/superpowers/specs/2026-08-24-pose-aware-routing-capabilities-design.md`

## Global Constraints

- Work only in `/home/dannyb/sources/factorio-lab-to-blueprint-sequence-pair-solver` on branch `sequence-pair-solver`.
- Preserve current committed state; every task is one reviewable follow-up commit.
- Merge only a clean committed final `game-rules` branch. Never copy uncommitted code from another worktree.
- `slot_poses.json` and finalized game-rule helpers are authoritative. No building-name or footprint-ring exceptions.
- Pose, oriented footprint, lane seating, attachment plan, and strip dimensions change atomically as one variant.
- Every physical strip is pose-homogeneous. Per-machine flexibility is expressed through bounded split/merge into pose-homogeneous strips.
- Lane feasibility and sorter span come from exact slot attachments, not `lane_count <= SORTER_MAX_REACH` or footprint-edge distance.
- Spray Coater supply is a directly routed elevated belt at the authoritative addon supply pose. No sorter targets a coater.
- Both routers consume the same prepared pose/elevation geometry. Global routing remains a proxy; only detailed routing plus validation accepts.
- Current game-rules serializer/altitude code is externally owned; integrate it, do not duplicate it.
- Fix the three final-review correctness findings before capability changes.
- Keep Numba/JAX, Pareto speed claims, and production `FreeformLayout` cutover deferred.
- Use integer/Fraction geometry for decisions; floating pose asset values are normalized only through authoritative helper functions.
- Run focused tests per task. Run full Ruff lint, mypy, pytest, broad audit, and the supplied URL only at the final task.

---

## File Structure

**Create**

- `src/flab2bp/layout/strip_variants.py` — pose-homogeneous strip families, variants, exact lane seating, attachment plans, and split/merge domain operations.
- `tests/layout/test_strip_variants.py`

**Modify**

- `src/flab2bp/layout/sequence_pair.py` — variant indices, variant moves, variable strip dimensions, and split/merge state.
- `src/flab2bp/layout/route_feedback.py` — candidate-dependent history/direct scoring and feedback mapping across split instances.
- `src/flab2bp/layout/sequence_solver.py` — family planning, variant-aware preparation, and closed-loop state transitions.
- `src/flab2bp/layout/freeform.py` — authoritative family generation/emission seams and elevated coater preparation.
- `src/flab2bp/layout/global_router.py` — elevated addon goals through existing shared movement.
- `src/flab2bp/dsp/catalog.py` and game-rule data only when the merged game-rules branch lacks addon supply pose data.
- `src/flab2bp/bench/ab.py`, `src/flab2bp/bench/promotion.py` — strict persisted metrics and cross-validation promotion evidence.
- Corresponding focused tests under `tests/layout`, `tests/dsp`, and `tests/bench`.

---

### Task 1: Close Final Whole-Branch Review Findings

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `src/flab2bp/layout/route_feedback.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/bench/ab.py`
- Modify: `src/flab2bp/bench/promotion.py`
- Modify: focused tests for those modules

**Interfaces:**
- Consumes: current `FeedbackState`, `PlacementCostContext`, direct targets, persisted A/B documents.
- Produces: candidate-dependent cost evaluation, strict integer parsing, and cross-validation-aware promotion input.

- [ ] **Step 1: Write failing candidate-dependent scoring tests**

```python
def test_history_cost_changes_when_candidate_moves_across_hot_region() -> None:
    problem, near, far, feedback = history_scoring_scene()
    assert feedback_cost(problem, near, feedback) > feedback_cost(problem, far, feedback)


def test_missed_direct_insert_penalty_depends_on_candidate_geometry() -> None:
    problem, aligned, separated, targets = direct_scoring_scene()
    assert missed_direct_inserts(problem, aligned, targets) < missed_direct_inserts(
        problem, separated, targets
    )
```

- [ ] **Step 2: Run scoring tests and verify current constant behavior fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/layout/test_route_feedback.py tests/layout/test_sequence_pair.py -q -k 'history_cost_changes or missed_direct_insert_penalty'`

Expected: assertions fail because the current stage context reuses one cached tuple and leaves production missed-direct count at zero.

- [ ] **Step 3: Move spatial/direct inputs into per-candidate energy evaluation**

`PlacementCostContext` carries immutable net weights, outline-scoped summed-area history, logical net pairs, and direct targets. `cheap_energy(problem, decoded, context)` queries each candidate's net bounding boxes and direct geometry. It does not cache candidate-derived values across moves.

- [ ] **Step 4: Write failing strict persisted-metric tests**

```python
@pytest.mark.parametrize("field,value", [
    ("trial", 0.9),
    ("trial", -1),
    ("area", 100.5),
    ("area", -1),
    ("belt_tiles", -1.2),
    ("buildings", 1.9),
])
def test_persisted_integer_metrics_reject_fractional_or_negative(field: str, value: object) -> None:
    payload = valid_sample_payload()
    payload[field] = value
    with pytest.raises(ValueError, match=field):
        samples_from_json(document_with(payload))
```

- [ ] **Step 5: Implement finite non-negative integral parsing**

Required integer metrics and identities accept `int` or mathematically integral finite numeric values only; reject booleans, fractions, negatives, NaN, infinity, and null except the existing non-VALID legacy `buildings: null` case.

- [ ] **Step 6: Write failing cross-validation promotion tests**

```python
@pytest.mark.parametrize("available,checked,passed,demoted", [
    (False, 0, 0, 0),
    (True, 2, 1, 0),
    (True, 2, 2, 1),
])
def test_promotion_requires_complete_successful_crossvalidation(
    available: bool, checked: int, passed: int, demoted: int
) -> None:
    report = assess_promotion(
        baseline=complete_baseline(),
        candidate=complete_candidate(),
        required=complete_manifest(),
        cross=CrossSummary(available, checked, passed, demoted, "fixture"),
    )
    assert not report.eligible
    assert any("cross-validation" in reason for reason in report.reasons)
```

- [ ] **Step 7: Thread persisted cross-validation into promotion**

Every valid blueprint in every required run must be independently checked and pass with zero demotions. Missing/disabled tooling is ineligible, never a skip that can promote.

- [ ] **Step 8: Run focused tests and static checks**

Run focused layout/bench tests, Ruff, and mypy on touched files with `VIRTUAL_ENV` unset. Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/route_feedback.py src/flab2bp/layout/sequence_solver.py src/flab2bp/bench/ab.py src/flab2bp/bench/promotion.py tests
git commit -m "Fix sequence feedback and promotion evidence"
```

---

### Task 2: Merge Finalized Authoritative Game Rules

**Files:**
- Merge committed `game-rules` branch
- Resolve overlapping catalog, freeform, base, codec, validator, and test files

**Interfaces:**
- Consumes: clean final `game-rules` branch SHA.
- Produces: one branch containing authoritative pose/slot/collider-pitch/serializer/altitude interfaces plus current sequence solver.

- [ ] **Step 1: Verify the source branch is clean and committed**

Run in the game-rules worktree: `git status --short && git log -3 --oneline`.

Expected: clean status. If dirty, stop this task and wait for its owner; do not copy files.

- [ ] **Step 2: Record merge bases and run pre-merge focused suites**

Record source SHA and sequence head in the task report. Run current slot/validator tests on game-rules and sequence/global tests on this branch.

- [ ] **Step 3: Merge game-rules into this worktree**

```bash
git merge --no-ff game-rules -m "Merge authoritative game rules"
```

- [ ] **Step 4: Resolve conflicts by interface authority**

Preserve game-rules catalog pose data, collider-derived world/grid placement pitch, slot assignment, serializer, altitude, and validation behavior. Preserve sequence solver prepared/global/detailed/feedback/budget behavior. Shared freeform preparation/emission must call authoritative helpers rather than retain parallel logic.

- [ ] **Step 5: Run merged focused tests**

Run slot/catalog/encode/validate/freeform/sequence/global tests, Ruff, and mypy for touched files. Expected: exit 0.

- [ ] **Step 6: Commit conflict resolution if the merge did not create it automatically**

Do not rewrite source branch commits.

---

### Task 3: Pose-Aware Strip Families and Variant Generation

**Files:**
- Create: `src/flab2bp/layout/strip_variants.py`
- Create: `tests/layout/test_strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py`

**Interfaces:**
- Consumes: authoritative catalog poses, oriented footprints, collider-derived placement geometry, logical strip lanes/shards.
- Produces: `MachinePlacementGeometry`, `StripFamilyId`, `StripInstanceId`, `LogicalLane`, `LaneAttachmentPlan`, `LanePlan`, `StripVariant`, `StripFamily`, and `generate_strip_families(spec)`.

- [ ] **Step 1: Write failing refinery pose tests**

```python
def test_upright_refinery_variant_cannot_serve_required_north_lane() -> None:
    family = refinery_family(required_above=True)
    upright = variants_at_yaw(family, 0.0)
    assert not upright


def test_rotated_refinery_variant_serves_both_lane_sides() -> None:
    family = refinery_family(required_above=True, required_below=True)
    rotated = variants_at_yaw(family, 90.0)
    assert rotated
    assert all(variant.footprint_width == 7 and variant.footprint_height == 3 for variant in rotated)


def test_equal_footprints_can_require_different_machine_pitch() -> None:
    smelter = placement_geometry("arc-smelter", yaw=0.0)
    assembler = placement_geometry("assembling-machine-1", yaw=0.0)
    assert (smelter.footprint_width, assembler.footprint_width) == (3, 3)
    assert smelter.pitch_x == 3
    assert assembler.pitch_x == 4


def test_machine_row_origins_advance_by_pitch_and_reserve_edge_halo() -> None:
    variant = assembler_variant(machine_count=3)
    assert variant.machine_origins_x == (0, 4, 8)
    assert variant.box_width >= 12
    assert no_collider_envelopes_overlap(variant)
```


- [ ] **Step 2: Run and verify missing strip-variant module**

Run: `env -u VIRTUAL_ENV uv run pytest tests/layout/test_strip_variants.py -q`.

Expected: collection failure.

- [ ] **Step 3: Implement immutable family/variant identities**

Machine ranges are half-open stable ordinal intervals on `StripInstance`; the logical family owns only `total_machine_count`. Variant identity includes yaw, oriented footprint, collider pitch/halos, lane rows, attachments, and box geometry.

- [ ] **Step 4: Generate cardinal pose candidates from the slot table**

Evaluate `0, 90, 180, 270` through catalog/slot transforms. Compute authoritative oriented placement geometry, advance repeated machine origins by pitch, reserve collider halos, reject poses that cannot serve required sides, deduplicate exact physical variants, and sort deterministically.

- [ ] **Step 5: Bridge existing strip planning**

Factor existing rate/shard allocation into logical family input. Keep a compatibility function producing the selected default variant for existing Freeform callers until cutover.

- [ ] **Step 6: Run family tests/static checks and commit**

```bash
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/layout/test_strip_variants.py
git commit -m "Add pose-aware strip families"
```

---

### Task 4: Exact Pose-Derived Lane Seating and Emission

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: authoritative slot tests and freeform tests

**Interfaces:**
- Consumes: pose-valid family and authoritative attachment helpers.
- Produces: exact `LaneReachProfile`, seated `LanePlan`, and emission using the same `LaneAttachmentPlan`.

- [ ] **Step 1: Write failing Chemical Plant reach test**

```python
def test_chemical_lane_three_clear_is_past_real_slot_reach() -> None:
    machine = placed_chemical(yaw=0.0)
    lane_y = machine.y + machine.height + 2
    assert not attachable_columns(machine, lane_y)


def test_chemical_lane_closer_uses_real_inner_anchor() -> None:
    machine = placed_chemical(yaw=0.0)
    lane_y = machine.y + machine.height
    attachments = attachable_columns(machine, lane_y)
    assert attachments
    assert max(got.span for got in attachments.values()) <= SORTER_MAX_REACH
```

- [ ] **Step 2: Write failing planning/emission identity test**

Plan a lane, emit the strip, and assert every sorter machine endpoint equals the precomputed attachment cell/slot/span for that machine and lane.
Lane rows must lie outside the pose-derived collider exclusion envelope; a slot-reachable row that physically overlaps the collider is infeasible.

- [ ] **Step 3: Enumerate exact lane side profiles**

For each pose and candidate row, call authoritative attachment geometry. Shared lanes require distinct legal columns for each item. Seat inputs/outputs only in feasible rows.

- [ ] **Step 4: Replace generic reach counting**

Remove feasibility decisions based solely on lane count or footprint edge. Use actual attachment spans for sorter tier selection.

- [ ] **Step 5: Emit from the attachment plan**

Do not recompute nearest edge/column. If a planned attachment cannot be reproduced, raise/refuse rather than substitute.

- [ ] **Step 6: Run Chemical/refinery/generic 3×3/full focused tests and commit**

```bash
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
git commit -m "Seat lanes from machine slot poses"
```

---

### Task 5: Variant-Aware Sequence-Pair SA

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: focused tests

**Interfaces:**
- Consumes: `StripFamily` variant tables.
- Produces: variant indices in fixed-cardinality `PlacementProblem`/`AnnealState`/`PlacementKey`, selected-size decoding, and `MoveKind.CHANGE_VARIANT`. Direct targets are derived from the complete selected producer/consumer variant set after decoding.

- [ ] **Step 1: Write failing atomic variant test**

```python
def test_variant_move_changes_pose_dimensions_and_attachments_atomically() -> None:
    problem, state = rotatable_refinery_problem()
    moved = apply_variant_move(problem, state, strip=0, variant=1)
    decoded = decode_state(problem, moved)
    assert moved.variant_indices == (1,)
    assert decoded.width != decode_state(problem, state).width
    assert problem.variant(0, 1).attachment_plan != problem.variant(0, 0).attachment_plan
```

- [ ] **Step 2: Extend immutable search state and exact key**

Validate one variant index per strip. Keys/caches/elites include instance and variant identity.

- [ ] **Step 3: Decode selected dimensions and add deterministic move**

Variant moves choose another valid variant for one strip; no-op only when one variant exists.

- [ ] **Step 4: Thread selected variants into preparation/direct alignment**

Preparation receives one complete selected physical strip plan.

- [ ] **Step 5: Run deterministic/mutation tests and commit**

```bash
git add src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py
git commit -m "Search pose-aware strip variants"
```

---

### Task 6: Pose-Homogeneous Split and Merge LNS

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `src/flab2bp/layout/route_feedback.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: focused tests

**Interfaces:**
- Consumes: strip instances, machine ranges, detailed feedback neighbourhood.
- Produces: deterministic split/merge operations and logical-to-physical feedback mapping.

- [ ] **Step 1: Write machine-conservation property tests**

For generated family sizes 1–12, apply deterministic stage-boundary split/merge sequences and assert machine ordinal union equals the original range, intersections are empty, and lane/rate totals are unchanged.

- [ ] **Step 2: Write feedback-driven split test**

A stranded net implicating a multi-machine strip after focused variant stagnation must create two child ranges and select pose-valid variants; unrelated strips retain order/state. The next stage receives a rebuilt fixed-cardinality problem matching the child instances.

- [ ] **Step 3: Implement split state transformation**

At a stage boundary, replace the parent in both permutations, variant/gap arrays, physical net mapping, prepared adapter inputs, and feedback endpoint map; then construct the next fixed-cardinality `PlacementProblem`. Never change cardinality during `anneal_stage`. Preserve the completed stage index, restart seed, and deterministic insertion order.

- [ ] **Step 4: Implement exact inverse merge**

Only adjacent same-group ranges with compatible variants/lane plans merge.

- [ ] **Step 5: Bound growth and preserve logical feedback**

No more instances than machines. Logical edge weights persist; physical wall ownership remaps to children.

- [ ] **Step 6: Run property/LNS/static tests and commit**

```bash
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/route_feedback.py tests/layout/test_strip_variants.py tests/layout/test_sequence_pair.py tests/layout/test_route_feedback.py
git commit -m "Split strips into pose-homogeneous ranges"
```

---

### Task 7: Elevated Spray Coater Supply Ports

**Files:**
- Modify: catalog/game data only if addon poses are absent after merge
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/global_router.py`
- Modify: `src/flab2bp/layout/validate.py`
- Modify: coater/global/freeform tests

**Interfaces:**
- Consumes: authoritative `AddonSupplyPose`, coater host position/yaw/z, shared z-aware movement.
- Produces: `CoaterSupplyPort`, elevated prepared proliferator nets, direct positional connection, and addon-supply validation.

- [ ] **Step 1: Write failing coater topology tests**

```python
def test_coater_supply_port_is_elevated_from_host_lane() -> None:
    prepared = prepared_proliferated_fixture()
    port = prepared.coater_supply_ports[0]
    assert port.z == port.host_z + 1


def test_no_sorter_targets_a_spray_coater() -> None:
    placement = emitted_proliferated_fixture()
    coater_indices = {i for i, b in enumerate(placement.buildings) if b.item_id == SPRAY_COATER_ID}
    assert not [
        b for b in placement.buildings
        if is_sorter(b.item_id) and (b.input_obj in coater_indices or b.output_obj in coater_indices)
    ]
```

- [ ] **Step 2: Add/load addon supply pose data**

Use extracted authoritative data and cardinal transform. Do not hardcode building-name offsets in freeform.

- [ ] **Step 3: Replace ground drop/sorter preparation**

Reserve elevated target/approach cells. Create proliferator net to the elevated port. Remove coater-targeting sorter construction.

- [ ] **Step 4: Route through both routers**

Global and detailed use the same elevated goal and shared movement. Ground-only termination does not satisfy the net.

- [ ] **Step 5: Emit positional addon connection and validate**

Use merged serializer conventions. Validator requires host belt plus elevated proliferator supply.

- [ ] **Step 6: Run coater/proliferator/global/detailed tests and commit**

```bash
git add src/flab2bp/dsp/catalog.py src/flab2bp/layout/freeform.py src/flab2bp/layout/global_router.py src/flab2bp/layout/validate.py tests/dsp tests/layout
git commit -m "Route elevated Spray Coater supply lanes"
```

---

### Task 8: Game-Aware Closed-Loop Integration

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: integration tests
- Modify: audit registration only as needed

**Interfaces:**
- Consumes: families, selected variants, split LNS, elevated coater routing.
- Produces: complete audit-only game-aware `SequencePairLayout`.

- [ ] **Step 1: Add refinery/chemical/coater end-to-end fixtures**

Each fixture must fail before its capability and pass detailed routing plus `validate.certify` afterward.

- [ ] **Step 2: Thread variant families through every stage**

SA elites, global preparation, detailed preparation, feedback, and exact incumbent must refer to the same selected instance/variant state.

- [ ] **Step 3: Extend observational stats**

Record variant moves, pose counts, split/merge counts, pose-feasibility rejects, and elevated coater routes. Stats remain observational.

- [ ] **Step 4: Run focused closed-loop and existing sequence/freeform tests**

Expected: zero invalid output under merged game rules.

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "Integrate pose-aware closed-loop search"
```

---

### Task 9: Final Correctness and Supplied URL

**Files:**
- No tracked changes unless verification finds a real uncovered defect
- Write ignored SDD reports/artifacts

**Interfaces:**
- Consumes: completed game-aware audit-only backend.
- Produces: correctness evidence and a new independently checked URL result.

- [ ] **Step 1: Run focused capability suites**

Run slot/catalog/strip-variant/sequence/global/freeform/validator tests.
Include collider/pitch tests proving the 3×3 Smelter pitch 3 and 3×3 Assembler pitch 4 distinction, repeated-origin pitch, and strip/lane halo exclusion.

- [ ] **Step 2: Run full static and test verification**

Run Ruff format check on branch-new files, Ruff lint, mypy, and full pytest. Compare repository-wide formatter failures to merge-base inherited set.

- [ ] **Step 3: Run broad game-aware sequence audit**

Require zero INVALID and CRASH outcomes. Record honest refusals by cell.

- [ ] **Step 4: Solve the supplied URL across all three candidates**

Power enabled, equal fixed budget. Require:

- detailed `ROUTED`;
- `validate.certify` clean under merged rules;
- independent cross-validation pass;
- pose-valid machines;
- exact slot-anchor sorter geometry;
- elevated coater supply where proliferation is used.

Select by `(area, belt_tiles)` only among fully valid candidates. Save the blueprint and full stats. Do not compare the retracted old result as valid evidence.

- [ ] **Step 5: Run whole-branch review and fix findings**

No performance/Pareto/promotion conclusion.

---

## Deferred Work

Numba/JAX bake-off, full Pareto gate, and production `FreeformLayout` cutover remain blocked until this correctness plan and the externally owned game-model work are merged and verified.
