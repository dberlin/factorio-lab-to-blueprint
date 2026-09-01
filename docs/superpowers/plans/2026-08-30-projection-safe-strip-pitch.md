# Projection-Safe Strip Pitch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair exact projected collisions between adjacent machines in one strip by enabling an on-demand padded physical variant in both Freeform and SequencePair.

**Architecture:** Shared strip-variant code constructs physically distinct padded variants and maps exact finalizer evidence to a typed pitch requirement. Freeform feeds the requirement into its current same-candidate projection retry; SequencePair rebuilds the affected variant table at a stage boundary and selects the padded variant through its existing variant-state machinery. Exact finalization remains authoritative.

**Tech Stack:** Python 3.14, immutable dataclasses, OR-Tools CP-SAT, existing SequencePair SA/LNS, pytest, Ruff, strict MyPy.

**Spec:** `docs/superpowers/specs/2026-08-30-projection-safe-pitch-power-cache-design.md`

## Global Constraints

- Normal collider pitch remains the only eligible default before exact failure feedback.
- Feedback changes only the implicated family, pose, and machine axis.
- Existing different-strip `ProjectionNoGood` behavior remains unchanged.
- No larger deadline, search budget, arrangement count, stage count, archive, or island count.
- Padded variant identity must include its physical pitch and machine origins.
- Exact finalization remains the sole acceptance authority.
- Retries remain inside the existing deadline and candidate schedule.
- Unmapped failures retain their original structured evidence without a repair hint.

---

### Task 1: Shared typed pitch requirements and padded variants

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `tests/layout/test_strip_variants.py`
- Modify: `tests/layout/test_freeform.py` only for the real projected-collision fixture

**Interfaces:**
- Consumes: `Placement`, `finalize.ProjectionFailure`, selected `StripInstanceId` and `StripVariant` tuples.
- Produces:
  - `StripPoseId` immutable pitch-independent identity for one family/pose.
  - `strip_pose_id(variant: StripVariant) -> StripPoseId`.
  - `ProjectionPitchRequirement` immutable record.
  - `projection_pitch_requirement(...) -> ProjectionPitchRequirement | None`.
  - `variant_with_minimum_pitch(variant: StripVariant, required_pitch_x: int) -> StripVariant`.
  - `partition_strip_variant(family, variant, *, max_machine_count) -> tuple[StripInstance, ...]`.

- [ ] **Step 1: Write the failing padded-geometry tests**

Add focused tests proving a padded variant changes only local-X pitch and physical identity:

```python
def test_variant_with_minimum_pitch_regenerates_physical_identity() -> None:
    family = chemical_plant_family(machine_count=2)
    ordinary = default_strip_variant(family)

    padded = variant_with_minimum_pitch(ordinary, ordinary.pitch_x + 1)

    assert padded.pitch_x == ordinary.pitch_x + 1
    assert padded.pitch_y == ordinary.pitch_y
    assert padded.footprint_width == ordinary.footprint_width
    assert padded.machine_origins_x == (0, padded.pitch_x)
    assert padded.box_width == 2 * padded.pitch_x
    assert padded.variant_id != ordinary.variant_id
    assert strip_pose_id(padded) == strip_pose_id(ordinary)
    assert padded.attachment_plan == ordinary.attachment_plan
    assert padded.lane_plan == ordinary.lane_plan
```

Also assert idempotence at or below current pitch and rejection of non-positive requirements.

- [ ] **Step 2: Run the padded-geometry tests to verify RED**

Run:

```bash
uv run pytest -q tests/layout/test_strip_variants.py -k "minimum_pitch"
```

Expected: import/attribute failure because `variant_with_minimum_pitch` does not exist.

- [ ] **Step 3: Implement padded physical geometry**

Add a deterministic helper on `MachinePlacementGeometry` that puts extra X clearance into the east halo:

```python
def with_minimum_pitch_x(self, required: int) -> MachinePlacementGeometry:
    if type(required) is not int or required <= 0:
        raise ValueError("required X pitch must be a positive integer")
    if required <= self.pitch_x:
        return self
    return replace(
        self,
        pitch_x=required,
        east_halo=self.east_halo + required - self.pitch_x,
    )
```

Implement `variant_with_minimum_pitch` by rebuilding `machine_origins_x`, `box_width`, `StripVariantId`, and the `StripVariant` around the padded geometry. Reuse the existing lane, attachment, and port-dock plans because their cells and slots are machine-local and unchanged by inter-machine pitch. Add `StripPoseId`/`strip_pose_id` with family, yaw, footprint, pitch-independent placement geometry, lane rows, attachments, port docks, and box height; exclude machine count, X pitch, east padding, machine origins, and box width so ordinary and superseding padded variants share one bounded requirement key.

- [ ] **Step 4: Write the failing typed-mapping tests**

Use the captured Chemical Plant pair: same owner, same model/yaw, adjacent origins at pitch seven, band-160 `geom.collide`. Supply explicit owner-to-instance and owner-to-variant tuples.

```python
def test_same_strip_adjacent_machine_collision_requires_next_pitch() -> None:
    failure = ProjectionFailure("geom.collide", (left_index, right_index), "build colliders intersect", 160)
    requirement = projection_pitch_requirement(
        placement,
        instance_ids=(instance.instance_id,),
        variants=(ordinary,),
        failure=failure,
    )
    assert requirement == ProjectionPitchRequirement(
        family_id=instance.family_id,
        instance_id=instance.instance_id,
        variant_id=ordinary.variant_id,
        axis="x",
        rejected_pitch=7,
        required_pitch=8,
        failure=failure,
    )
```

Parameterize controls for different owner strips, non-adjacent machines, different item/model/yaw, belts, sorters, towers, missing owners, malformed indices, and origin separation unequal to `pitch_x`; every control returns `None`.

- [ ] **Step 5: Run mapping tests to verify RED**

Run:

```bash
uv run pytest -q tests/layout/test_strip_variants.py tests/layout/test_freeform.py -k "projection_pitch_requirement or same_strip_adjacent"
```

Expected: import/attribute failure for the new mapper.

- [ ] **Step 6: Implement the immutable requirement and mapper**

Add `ProjectionPitchRequirement` with the exact fields from the spec. The mapper must validate indices and selected owner tables before reading buildings. Determine adjacency from machine origins in the selected realized variant, not merely `abs(x1-x2)`, so unrelated same-model buildings cannot create feedback. Extract the current partition body into `partition_strip_variant`; keep `partition_strip_family` as the existing variant-ID chooser delegating to it, and verify explicit padded variants preserve family identity and machine ordinals without requiring membership in `family.variants`.

- [ ] **Step 7: Verify Task 1**

Run:

```bash
uv run pytest -q tests/layout/test_strip_variants.py tests/layout/test_freeform.py -k "pitch or variant_identity or instance_partition"
uv run ruff check src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
```

- [ ] **Step 8: Commit Task 1**

```bash
git add src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
git commit -m "Add projection-safe strip pitch variants"
```

---

### Task 2: Freeform same-candidate pitch retry

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `ProjectionPitchRequirement`, `StripPoseId`, `strip_pose_id`, `partition_strip_variant`, and `variant_with_minimum_pitch` from Task 1.
- Produces:
  - `Strip.physical_variant: StripVariant | None`, retaining the exact realized variant selected for each emitted owner strip.
  - `plan_strips(..., minimum_pitch_x: Mapping[StripPoseId, int] = _NO_PITCH_REQUIREMENTS)`.
  - `_projection_pitch_requirement(...)` adapter from Freeform owner indices to shared selected instances/variants.
  - Same-height/arrangement retry using the existing `projection_retry` candidate slot.

- [ ] **Step 1: Write the failing planner override test**

Build the `plastic/all-products` spec and assert only the Chemical Plant family changes:

```python
def test_plan_strips_applies_minimum_pitch_to_one_pose() -> None:
    ordinary = plan_strips(plastic_spec(), strip_len=6)
    chemical = next(strip for strip in ordinary if strip.item_id == 2309)
    assert chemical.physical_variant is not None
    pose_id = strip_pose_id(chemical.physical_variant)

    padded = plan_strips(
        plastic_spec(),
        strip_len=6,
        minimum_pitch_x={pose_id: chemical.pw + 1},
    )

    padded_chemical = next(strip for strip in padded if strip.family_id == chemical.family_id)
    assert padded_chemical.pw == chemical.pw + 1
    assert padded_chemical.physical_variant is not None
    assert strip_pose_id(padded_chemical.physical_variant) == pose_id
    assert all(
        after == before
        for before, after in zip(ordinary, padded, strict=True)
        if before.family_id != chemical.family_id
    )
```

- [ ] **Step 2: Run planner override test to verify RED**

Run:

```bash
uv run pytest -q tests/layout/test_freeform.py -k "minimum_pitch_to_one_pose"
```

Expected: `plan_strips()` rejects the new keyword.

- [ ] **Step 3: Thread shared padded variants through `plan_strips`**

Add the immutable mapping argument and the optional `Strip.physical_variant`. For each pose-valid family, select the ordinary default, look up its `StripPoseId`, construct the padded total-family template only when required, and partition it through `partition_strip_variant`. Build each `Strip` from the returned `StripInstance`, retaining that instance's realized variant. Compatibility families keep `physical_variant=None`; they cannot receive requirements because the mapper rejects missing variants.

Update `_coarsen_saturated_strip_plan` to preserve the mapping when it replans. Add a focused compatibility-family test so this path cannot turn a structured refusal into an attribute error.

- [ ] **Step 4: Write the failing Freeform retry regression**

Use deterministic single-worker settings and the captured `plastic/all-products` spec. Spy on `plan_strips` or the shared variant helper to record pitches. Assert the first exact candidate reports pitch seven, one retry uses pitch eight, and the result is finalizer-clean:

```python
def test_freeform_retries_same_strip_projection_failure_with_padded_pitch() -> None:
    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=1,
    ).lay_out(plastic_spec(), time_budget_s=4.0)

    report = validate.certify(placement, plastic_spec(), expect_power=True)
    assert report.ok
    assert not report.by_check("geom.collide")
    assert chemical_plant_origins(placement) == projection_safe_origins(placement)
```

Add controls showing different-strip failures still create `ProjectionNoGood`, a repeated identical requirement does not enqueue duplicate retries, and a second exact same-strip failure advances the retained pitch by one rather than accumulating old padded variants.

- [ ] **Step 5: Run the retry regression to verify RED**

Run:

```bash
uv run pytest -q tests/layout/test_freeform.py -k "padded_pitch or projection_no_good"
```

Expected: the captured same-strip failure remains unmapped and `plastic` refuses.

- [ ] **Step 6: Integrate typed pitch feedback into `_sweep`**

Maintain `minimum_pitch_x: dict[StripPoseId, int]` beside `projection_no_goods`. When `finalize_placement` raises:

1. retain every original failure;
2. attempt the existing different-strip no-good mapping;
3. reconstruct aligned `StripInstanceId` and realized `StripVariant` tuples from the emitted owner-strip order, rejecting any compatibility strip with no physical variant;
4. attempt shared pitch mapping using the emitted placement and those selected records;
5. derive the stable `StripPoseId` from the selected realized variant and update only when `required_pitch` exceeds the retained value;
6. replan strips and insert `(height, arrangement, True)` at `candidate_index` once when either feedback type learned something.

Freeform selects one deterministic pose per family, so its retained pose key is unambiguous even though every partition instance has a count-specific physical variant. The retry must reuse current deadline, `per_solve`, arrangement index, and winner key. It must not increment `self.arrangements` or append a new height.

- [ ] **Step 7: Verify Task 2**

Run:

```bash
uv run pytest -q tests/layout/test_freeform.py -k "projection or padded_pitch or sweep or arrangement"
uv run python scripts/route_profile.py plastic --strategy freeform --budget 4 --json
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
```

Expected profile verdict: `OK`, with no budget or arrangement increase.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "Retry Freeform with projection-safe pitch"
```

---

### Task 3: SequencePair on-demand padded variant tables

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `tests/layout/test_sequence_pair.py`
- Modify: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: Task 1 requirement and padded-variant constructor, plus the existing `StageBoundaryTransform` path.
- Produces:
  - `enable_variant_stage_boundary(problem, state, *, strip, variant, select_variant) -> StageBoundaryUpdate`.
  - Extended `StageBoundaryTransform` inputs for authoritative `projection_failures` and a `select_feedback_variant` primary/sibling flag.
  - `StageObservation.pitch_requirement: ProjectionPitchRequirement | None`.

- [ ] **Step 1: Write the failing immutable table-update tests**

Construct a two-strip variant-aware `PlacementProblem`. Enable a padded variant for strip zero and assert:

```python
update = enable_variant_stage_boundary(
    problem,
    state,
    strip=0,
    variant=padded,
    select_variant=True,
)
assert update.problem.variant_tables[0] == problem.variant_tables[0] + (padded,)
assert update.problem.variant_tables[1] == problem.variant_tables[1]
assert update.state.variant_indices[0] == len(problem.variant_tables[0])
assert update.state.pair == state.pair
assert update.state.gaps == state.gaps
```

Add idempotence and supersession tests keyed by `StripPoseId`: re-enabling the same variant is a no-op; a larger padded pitch replaces the older padded entry and migrates a state that selected it to the replacement index. With `select_variant=False`, an ordinary sibling keeps its selection while a sibling that selected the superseded padded entry migrates to the replacement.

- [ ] **Step 2: Run table-update tests to verify RED**

Run:

```bash
uv run pytest -q tests/layout/test_sequence_pair.py -k "enable_variant_stage_boundary"
```

Expected: import failure for the new helper.

- [ ] **Step 3: Implement immutable variant-table updates**

Rebuild `sizes`, `variant_tables`, and the selected state's index while retaining instance IDs, logical nets, pair order, gaps, stage index, and seed. Validate that the padded variant has the same family, `StripPoseId`, and realized machine count as the target table. Ordinary entries keep their order; the single padded entry for that pose is last. `select_variant=True` chooses it for the failed restart; `False` rebases sibling indices without changing an ordinary selection.

- [ ] **Step 4: Write failing SequenceSolver feedback tests**

Provide a deterministic validation adapter returning one exact same-strip Chemical Plant failure. Assert:

- the failed stage establishes no incumbent;
- the failed restart selects the padded variant next;
- sibling restarts receive the same rebuilt problem but retain their ordinary selected variant;
- stage count, archive cap, move allowance, and expansions do not increase;
- `StageObservation` retains the authoritative failure and typed requirement.

Add unmapped/different-strip controls.

- [ ] **Step 5: Run solver feedback tests to verify RED**

Run:

```bash
uv run pytest -q tests/layout/test_sequence_solver.py -k "projection_pitch or padded_variant"
```

Expected: no variant-table rebuild occurs and the ordinary pitch repeats.

- [ ] **Step 6: Extend the existing stage-boundary transform and production adapter**

Extend `StageBoundaryTransform` and its existing test adapters with two inputs: the authoritative `projection_failures` tuple and `select_feedback_variant: bool`. Invoke the existing boundary path when either the current route signature is non-empty or projection failures exist. Pass `True` for the failed restart and `False` for sibling rebases; retain the current invariant that every callback returns an identical rebuilt problem. Existing split/merge behavior ignores the flag and remains unchanged.

In the production `transform_stage`, check projection feedback before ordinary route-failure split/merge. Map failures against `problem.instance_ids`, the failed state's selected variants, and `detailed.placement`. If a requirement is newer:

1. build the padded realized variant;
2. rebuild the failed restart via `enable_variant_stage_boundary(..., select_variant=True)`;
3. rebuild sibling states through the same helper with `select_variant=False`;
4. clear stale archives whose candidate keys reference the superseded table;
5. preserve feedback weights, expansion spend, exact incumbents, and winner ordering.

Thread the learned requirement into `_record_routing_observation` and `StageObservation`. Do not route it through net-failure signatures because it is geometry, not congestion. A projection-only validation failure must therefore reach the boundary transform even when detailed routing has no failure signature.

- [ ] **Step 7: Write the real SequencePair plastic regression**

At one island and deterministic configuration, run `plastic/all-products` at four seconds. Assert finalizer-clean output and selected Chemical Plant pitch eight. Keep a control showing an ordinary valid family retains pitch seven.

- [ ] **Step 8: Verify Task 3**

Run:

```bash
uv run pytest -q tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py
uv run python scripts/route_profile.py plastic --strategy sequence-pair --budget 4 --json
uv run ruff check src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py
```

Expected profile verdict: `OK`; exact incumbent remains ordered only by `(area, belt_tiles)`.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py
git commit -m "Teach SequencePair projection-safe pitch feedback"
```

---

### Task 4: Pitch quality and regression gate

**Files:**
- Modify only if a test exposes a defect in Tasks 1-3.
- Record ignored execution evidence under `.superpowers/sdd/2026-08-30-projection-safe-strip-pitch/`.

**Interfaces:**
- Consumes: completed Freeform and SequencePair pitch feedback.
- Produces: accepted/rejected gate evidence for the power-cache plan.

- [ ] **Step 1: Run the focused `plastic` 4-second gate three times**

Clear the evidence file, then execute this command three times:

```bash
uv run python scripts/audit.py --only plastic --budget 4 --strategy both --jobs 1 --json .superpowers/sdd/2026-08-30-projection-safe-strip-pitch/plastic-4s.jsonl
```

Expected aggregate: 15/18 `CLEAN`; zero `INVALID`, `CRASH`, or `NOT RUN`. The three SequencePair/output-products cells must first rerun the mapped adjacent Chemical Plant relation at pitch eight, then retain only the separately diagnosed unmapped ownerless-static collision `(181, 255)` as structured `REFUSED` evidence. Any terminal observation that still maps to `ProjectionPitchRequirement` fails this gate.

- [ ] **Step 2: Run the default-budget gate**

```bash
uv run python scripts/audit.py --only plastic --budget 15 --strategy both --jobs 1 --json .superpowers/sdd/2026-08-30-projection-safe-strip-pitch/plastic-15s.jsonl
```

Expected: five clean cells. SequencePair/output-products may retain the same owner-strip-2 Chemical Plant versus ownerless direct power building refusal only after its padded rerun; no mapped pitch requirement may remain terminal. This blocker transfers to the reliability plan's staged-static task and does not authorize generic different-strip feedback here.

- [ ] **Step 3: Run deterministic geometry and routing regressions**

```bash
uv run pytest -q tests/layout/test_strip_variants.py tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py tests/layout/test_finalize.py tests/layout/test_global_router.py tests/layout/test_route_feedback.py
```

Expected: all pass; ordinary deterministic fixtures retain exact geometry and path digests.

- [ ] **Step 4: Run the paired corpus gate**

Use the `using-git-worktrees` skill to create a detached baseline worktree at design commit `4f4b867`. In strict baseline-then-candidate order, run the full budget-4 audit three times per arm with identical `--jobs 16`, appending each arm to its own absolute JSONL evidence path:

```bash
uv run python scripts/audit.py --budget 4 --strategy both --jobs 16 --json "$EVIDENCE/baseline.jsonl"
uv run python scripts/audit.py --budget 4 --strategy both --jobs 16 --json "$EVIDENCE/candidate.jsonl"
```

Repeat that pair three times. Add an ignored `$EVIDENCE/compare_gate.py` that assigns repeat ordinals per `(url_id, spec_index, power, strategy, budget)`, rejects missing/duplicate cells, and prints: clean trial and cell coverage by arm, lost baseline-clean cells, per-cell median-clean area ratios, geometric-mean candidate/baseline area, and median candidate/baseline `build_wall_time_s`. Repeat ordinals validate the matrix only; they are not paired observations because concurrent audit scheduling makes their completion order arbitrary.

```bash
uv run python "$EVIDENCE/compare_gate.py" "$EVIDENCE/baseline.jsonl" "$EVIDENCE/candidate.jsonl"
```

Acceptance:

- no cell that is `CLEAN` in any baseline repeat loses all clean coverage in the candidate arm;
- the geometric mean of candidate/baseline median-clean area per shared clean cell regresses by at most 1%;
- the median candidate/baseline median-clean wall time per shared clean cell regresses by at most 5%;
- the focused Task 1-3 feedback tests remain the authority that padded geometry appears only after an exact typed requirement.

- [ ] **Step 5: Run complete static and test validation**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy
```

- [ ] **Step 6: Request whole-pitch-range review**

Review every commit since the design commit for missed caller migration, variant identity drift, unbounded retries, invalid owner mapping, and weakened finalization. Fix all Critical and Important findings before starting the power-cache plan.
