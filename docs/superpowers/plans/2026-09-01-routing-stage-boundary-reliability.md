# Routing Stage-Boundary Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Freeform and SequencePair reliably produce exactly valid layouts within each 15-second corpus cell by rejecting projection-impossible candidates before detailed routing, allocating usable source exits jointly, and feeding concrete routing ownership back into topology search.

**Architecture:** Preserve both existing packers and the existing detailed router. Strengthen the boundaries between packing, preparation, routing, projection, and finalization: deterministic replay cases expose each boundary; preparation allocates complete two-cell egress corridors; every routed candidate carries a viable projection frame; existing `NetFailure` evidence names the responsible endpoints and drives SequencePair LNS; both strategies reserve measured completion time before starting another exact route.

**Tech Stack:** Python 3.14, frozen dataclasses, OR-Tools CP-SAT already in the project, pytest, Ruff, mypy, existing DSP projection/certification rules.

**Spec:** `docs/superpowers/plans/2026-08-28-sequence-freeform-speed-quality.md`, refined by the 2026-09-01 broke4 runtime-capture diagnosis and the accepted stage-boundary design in this session.

## Global Constraints

- Keep Freeform and SequencePair as distinct complete strategies; do not replace either packer.
- Reuse `_PreparedRoutingProblem`, `StageAdapters`, `DetailedRouteResult`, `NetFailure`, `FeedbackState`, and `finalize.FrameCandidate`; do not add a parallel routing or failure model.
- Apply generic DSP rules only. No model-40, T-junction, recipe, item, corpus-cell, or blueprint-order special cases.
- Production certification uses serialization-stable belt collision rules; exact offline canonicalization remains out of scope because game copy ordering depends on live entity IDs.
- A normal corpus cell has a 15-second wall budget. No search phase may consume time reserved for compaction, projection, certification, and serialization.
- Generated `.txt` artifacts go only under `/home/dannyb/dsp-tests/<descriptive-subdirectory>/`.
- Changed behavior is complete only when focused tests, the named 15-second cells, the full 72-cell audit, Ruff, mypy, and the regenerated blueprint smoke path pass.

---

### Task 1: Deterministic Stage Replay Cases

**Files:**
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/layout/test_route_feedback.py`
- Modify only if production observability is missing: `src/flab2bp/layout/sequence_solver.py`

**Interfaces:**
- Consumes: `StageAdapters`, `_PreparedRoutingProblem.new_workspace()`, `DetailedRouteResult`, `StageObservation`.
- Produces: deterministic test factories for the universe-matrix/all-products sealed-egress case and universe-matrix/output finalization case. Each factory stops immediately after one named boundary and returns typed in-memory objects; no pickle, opaque serialized solver state, or wall-clock dependence.

- [ ] **Step 1: Write a failing Freeform preparation replay test**

Construct the smallest extracted prepared problem that retains the observed hydrogen source, adjacent port claims, and static belt. Assert that preparation returns a source corridor with both an access cell and an onward cell, rather than a selected access cell whose onward set is empty.

```python
def test_universe_all_replay_preserves_hydrogen_source_egress() -> None:
    prepared = universe_all_source_egress_replay()
    corridor = prepared.port_corridors[HYDROGEN_SOURCE_PORT]
    assert corridor.access not in prepared.blocked
    assert corridor.exit not in prepared.blocked
    assert corridor.exit in neighbours(corridor.access)
```

- [ ] **Step 2: Run the replay and verify the current preparation fails**

Run:

```bash
uv run pytest -q tests/layout/test_freeform.py::test_universe_all_replay_preserves_hydrogen_source_egress
```

Expected before Task 3: FAIL because the current post-pass cannot assign an exit after other matched access claims consume all onward cells.

- [ ] **Step 3: Write a SequencePair boundary replay test**

Use injected `StageAdapters` to run the exact candidate through `prepare`, one detailed route, and `validate` independently. Assert the replay is deterministic across two invocations: identical prepared geometry key, failure kinds, endpoint identities, walls, and projection-frame candidates.

```python
def test_universe_output_stage_replay_is_deterministic() -> None:
    first = run_universe_output_replay()
    second = run_universe_output_replay()
    assert first == second
    assert first.failures == tuple(sorted(first.failures, key=failure_key))
```

- [ ] **Step 4: Add only missing observational fields**

If an existing typed result omits a value required by the assertions, add the value to `StageObservation` or `_PreparedRoutingProblem` as immutable data. Do not create a second stage framework and do not write runtime fixture files.

- [ ] **Step 5: Run focused replay tests**

```bash
uv run pytest -q tests/layout/test_freeform.py -k 'replay or source_egress'
uv run pytest -q tests/layout/test_sequence_solver.py -k 'replay or stage_boundary'
uv run pytest -q tests/layout/test_route_feedback.py
```

- [ ] **Step 6: Commit**

```bash
git add tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/layout/test_route_feedback.py src/flab2bp/layout/sequence_solver.py
git commit -m "Add deterministic routing stage replays"
```

---

### Task 2: Projection Context Before Detailed Routing

**Files:**
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Test: `tests/layout/test_finalize.py`
- Test: `tests/layout/test_freeform.py`
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `finalize.FrameCandidate`, `finalize.frame_candidates`, `finalize.materialize_frame_building`, `BandPolicySearchEnvelope`, `_PreparedRoutingProblem`, `StageAdapters.prepare_exact`.
- Produces: `ProjectionRoutingContext(frame: FrameCandidate, core_key: tuple[...])` and `projection_routing_contexts(core: Placement, policy: BandPolicy) -> tuple[ProjectionRoutingContext, ...]`. A prepared routing candidate carries a non-empty ordered tuple of contexts.

- [ ] **Step 1: Write failing projection-context tests**

Cover rotation, south padding, frame ordering, core static collision, projected coater/splitter keepout, and the exact universe-output frame that currently reaches `game.addon_supply` only after routing.

```python
def test_projection_context_rejects_core_with_no_viable_frame() -> None:
    contexts, failures = projection_routing_contexts(impossible_core(), BandPolicy("portable"))
    assert contexts == ()
    assert {failure.check for failure in failures} == {"geom.collide"}
```

- [ ] **Step 2: Verify the new API is absent or the extracted case fails**

```bash
uv run pytest -q tests/layout/test_finalize.py -k projection_context
```

- [ ] **Step 3: Implement context creation in `finalize.py`**

Enumerate existing `frame_candidates` in their current deterministic order. Materialize and run only invariants knowable from the prepared core: frame policy, static colliders, sorter seats, power-node geometry, and coater/splitter keepouts. Return failures when all frames are eliminated. Do not claim belt/addon validity before belts exist.

- [ ] **Step 4: Carry contexts through Freeform preparation**

Extend `_PreparedRoutingProblem` rather than adding a sibling prepared type. `_prepare` computes contexts after buildings, coaters, direct inserts, static reservations, and power nodes are fixed. A candidate with no context is rejected before `_build` starts detailed routing.

- [ ] **Step 5: Carry contexts through SequencePair preparation**

`prepare_candidate` and `prepare_exact` retain the contexts. `StageAdapters.prepare_exact` must use the exact selected strip variants and pose before detailed closure, so late projection retries cannot route a frame already disproved by the core.

- [ ] **Step 6: Add a projected endpoint feasibility check**

For each coater supply or boundary endpoint, retain only contexts in which at least one legal projected belt seat exists in its routing envelope. If no context survives, return typed projection failure evidence to the caller before detailed A*.

- [ ] **Step 7: Run focused tests and commit**

```bash
uv run pytest -q tests/layout/test_finalize.py -k 'projection_context or frame'
uv run pytest -q tests/layout/test_freeform.py -k 'projection or addon_supply'
uv run pytest -q tests/layout/test_sequence_solver.py -k 'projection or prepare_exact'
git add src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
git commit -m "Reject projection-impossible routing candidates early"
```

---

### Task 3: Joint Port-Egress Corridor Allocation

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/slots.py` only if the port claimant type belongs there
- Test: `tests/layout/test_freeform.py`
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: existing port claims used by `_match_access`, reserved and blocked cells from `_PreparedRoutingProblem`, and preparation cancellation callback.
- Produces: frozen `PortAccessCorridor(access: Cell, exit: Cell)` assignments. `_reserve_port_access` reserves both cells atomically and records ownership by port/net identity.

- [ ] **Step 1: Write failing corridor-allocation unit tests**

Cover: two claims competing for one access cell; two claims with distinct access cells but a shared sole exit; a feasible reassignment that the current access-only matching misses; true infeasibility; deterministic tie-breaking; and the universe-all hydrogen replay.

```python
def test_joint_matching_moves_access_claim_to_preserve_both_exits() -> None:
    corridors = _match_access_corridors(claims, blocked=frozenset())
    assert set(corridors) == set(claims)
    occupied = {cell for corridor in corridors.values() for cell in (corridor.access, corridor.exit)}
    assert len(occupied) == 2 * len(corridors)
```

- [ ] **Step 2: Verify the extracted zero-onward case fails**

```bash
uv run pytest -q tests/layout/test_freeform.py -k 'access_corridor or hydrogen_source_egress'
```

- [ ] **Step 3: Replace access-only matching with joint matching**

Enumerate each claim's legal `(access, exit)` pairs before solving. Use the existing deterministic claim priority. Solve the small bipartite/set-packing problem exactly with the existing OR-Tools dependency: one corridor per required claim, cell capacity one, optional claims only after all required claims, and lexicographic deterministic tie-breaking encoded as integer costs. Poll cancellation before and after CP-SAT.

- [ ] **Step 4: Remove the post-pass sole-egress heuristic**

Delete the branch that reserves an onward cell only when exactly one remains. Reserve both assigned cells in one commit. If required claims are infeasible, return structured preparation failure with claimant identity and conflicting owner identities; never silently retain a zero-onward access cell.

- [ ] **Step 5: Verify Freeform and SequencePair preparation**

```bash
uv run pytest -q tests/layout/test_freeform.py -k 'access or reserve_port or source_egress'
uv run pytest -q tests/layout/test_sequence_solver.py -k 'prepare or access'
```

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/slots.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
git commit -m "Allocate complete port egress corridors"
```

---

### Task 4: Ownership-Preserving Routing Conflicts

**Files:**
- Modify: `src/flab2bp/layout/route_feedback.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Test: `tests/layout/test_route_feedback.py`
- Test: `tests/layout/test_freeform.py`
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: existing `NetFailure(source, destination, blocking_nets, blocking_endpoints)`, corridor ownership from Task 3, `update_feedback`, `geometric_failure_instances`, `select_lns_neighbourhood`, `_pose_stage_boundary_update`.
- Produces: every `STATIC_ACCESS`, `DYNAMIC_ACCESS`, `SEALED_POCKET`, `CONGESTION_WALL`, and `COMMIT_LINK` failure names the blocked net plus concrete blocking owners and endpoints whenever they exist.

- [ ] **Step 1: Write failing ownership tests**

Assert that a source sealed by reserved access corridors names the owners of those corridors; a dynamic wall names committed belts; and failure ordering is deterministic.

```python
def test_sealed_source_reports_corridor_owners() -> None:
    failure = route_extracted_sealed_source()
    assert failure.kind is RouteFailureKind.SEALED_POCKET
    assert failure.blocking_nets
    assert len(failure.blocking_endpoints) == len(failure.blocking_nets)
```

- [ ] **Step 2: Preserve ownership in prepared workspaces**

Track reserved-cell owner alongside occupancy. Convert owner records to existing `NetId` values when emitting `NetFailure`; static buildings without a net remain wall evidence, not invented nets.

- [ ] **Step 3: Feed ownership through existing feedback**

Update `geometric_failure_instances` and `select_lns_neighbourhood` to prioritize source/destination strip instances and the named blocking endpoints. Keep decay and logical-net remapping unchanged.

- [ ] **Step 4: Make topology changes evidence-driven**

In `_pose_stage_boundary_update`, split, merge, or move only implicated strip families. Remove any fallback that merely rotates net order without changing the blocking topology after the same failure signature repeats.

- [ ] **Step 5: Run focused tests and commit**

```bash
uv run pytest -q tests/layout/test_route_feedback.py
uv run pytest -q tests/layout/test_freeform.py -k 'failure or feedback or sealed'
uv run pytest -q tests/layout/test_sequence_solver.py -k 'feedback or lns or topology'
git add src/flab2bp/layout/route_feedback.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_route_feedback.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
git commit -m "Feed routing ownership into topology search"
```

---

### Task 5: Completion-Time Admission Control

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/pipeline.py` only if the outer 15-second cell currently omits serialization time
- Test: `tests/layout/test_freeform.py`
- Test: `tests/layout/test_sequence_solver.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Freeform `compaction_reserve_s`, `finalize_reserve_s`, `validation_reserve_s`; Sequence `ExpansionBudget.final_reserved`; measured `StageObservation` timings.
- Produces: a shared typed `CompletionReserve` with measured upper bounds for compaction, projection, validation, and serialization. Search admission asks `reserve.can_start(remaining, estimated_candidate_cost)` before every exact route or improvement attempt.

- [ ] **Step 1: Write failing fake-clock tests**

Cover both strategies. A fully routed candidate must enter finalization before the reserved boundary; an improvement candidate must not start if it would consume the reserve; cancellation during finalization must remain a refusal, not a partial success.

```python
def test_sequence_does_not_spend_completion_reserve_on_another_route() -> None:
    result = run_with_fake_clock(route_cost=8.0, completion_cost=3.0, budget=15.0)
    assert result.termination == "exact-incumbent"
    assert result.stages[-1].validation_failures == ()
```

- [ ] **Step 2: Implement measured reserve updates**

Initialize from deterministic conservative floors derived from existing focused timings, then update monotonically with actual completed stage costs in the same cell. Do not use recipe/item/model thresholds. Keep the five-second atomic completion grace only for a completion already admitted before the hard boundary; never use it to start more search.

- [ ] **Step 3: Apply admission at every exact boundary**

Freeform: before detailed routing, compaction retry, and projection retry. SequencePair: before seed closure, archive detailed route, quality route, topology-beam exact closure, compaction, and `certify`.

- [ ] **Step 4: Verify exact wall behavior and commit**

```bash
uv run pytest -q tests/layout/test_freeform.py -k 'deadline or reserve or finalization'
uv run pytest -q tests/layout/test_sequence_solver.py -k 'deadline or reserve or exact'
uv run pytest -q tests/test_pipeline.py -k 'deadline or completion'
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py src/flab2bp/pipeline.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/test_pipeline.py
git commit -m "Reserve completion time before exact routing"
```

---

### Task 6: Close Named 15-Second Refusals

**Files:**
- Modify only source implicated by replay evidence from Tasks 1-5.
- Test: existing corpus/audit tests and `scripts/audit.py`.

**Interfaces:**
- Consumes: deterministic replay cases and new stage observations.
- Produces: successful, exactly certified Freeform and SequencePair results for universe-matrix/all-products and universe-matrix/output at 15 seconds without strategy-specific exceptions.

- [ ] **Step 1: Run the four named cells individually**

Run each combination at `--budget 15 --jobs 1`, capture only stage summaries, and require `status=OK`, zero stranded nets, non-empty projection contexts before detailed routing, and completed final validation.

- [ ] **Step 2: Diagnose only through the first failing boundary**

For any refusal, replay the saved typed boundary case. Change the generic boundary contract that failed; do not tune height order, net order, expansion count, recipe identity, or model-specific geometry.

- [ ] **Step 3: Repeat each cell three times**

All three runs must pass. Compare stage keys and failure-free outcomes; elapsed time may vary, but selected deterministic stage inputs and exact certification must not.

- [ ] **Step 4: Commit any evidence-driven correction**

Use one commit per boundary contract. Do not combine unrelated deadline and geometry changes.

---

### Task 7: Full Reliability Gates

**Files:**
- No source changes unless a gate exposes a generic regression.

**Interfaces:**
- Consumes: completed Tasks 1-6.
- Produces: proof that the complete branch is type-safe, lint-clean, test-clean, and reliable across the 72-cell matrix.

- [ ] **Step 1: Run focused layout suites**

```bash
uv run pytest -q tests/layout/test_route_feedback.py tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/layout/test_validate.py
```

- [ ] **Step 2: Run static gates**

```bash
uv run ruff check .
uv run mypy src
```

- [ ] **Step 3: Run the complete Python suite**

```bash
uv run pytest -q
```

- [ ] **Step 4: Run the 72-cell audit at 15 seconds**

Use the repository audit command with both strategies and all policies. Require 72/72 complete, zero invalid, zero deadline refusals, and total test-suite runtime within the repository's 150-second target where applicable.

- [ ] **Step 5: Run CLI smoke tests for both strategies**

Generate one Freeform and one SequencePair blueprint through the production CLI, decode them, and run exact certification on the emitted records.

---

### Task 8: Regenerate the In-Game SequencePair Blueprint

**Files:**
- Create outside repository: `/home/dannyb/dsp-tests/broke4-sequencepair-stage-boundary-fix/<descriptive-name>.txt`

**Interfaces:**
- Consumes: the original broke4 input/options, production SequencePair CLI path, serialization-stable exact certification.
- Produces: one complete blueprint text artifact ready for Dyson Sphere Program paste testing.

- [ ] **Step 1: Generate through the production path**

Use the same broke4 FactorioLab input, policy, proliferation mode, power setting, and output target as the failing `corrected.txt`; select SequencePair and the normal user budget. Do not patch or reorder the serialized text afterward.

- [ ] **Step 2: Verify offline before notifying the user**

Decode the exact emitted string; require all requested machines and outputs, zero missing sorters, zero validator findings including `game.addon_supply`, `game.belt_collide`, and `geom.belt_single_occupancy`, and a save-safe title.

- [ ] **Step 3: Report the exact test path**

Notify the user immediately with the full `/home/dannyb/dsp-tests/broke4-sequencepair-stage-boundary-fix/...txt` path and the expected in-game observation. The artifact is test-ready at this point; the branch need not wait for the user's manual result before preserving all automated evidence.

- [ ] **Step 4: Record the game result**

If the game accepts and completes the build, mark the in-game verification complete. If it rejects, use the reported game state as ground truth and capture only the newly exposed generic rule.
