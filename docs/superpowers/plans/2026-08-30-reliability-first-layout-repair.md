# Reliability-First Layout Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the reported mechanical, flow-domain, band-policy, and packing failures in Freeform and SequencePair while preserving exact validators and existing work bounds.

**Architecture:** Fix each violated phase contract at its earliest boundary. Preserve spray domain through lane/net identity; plan power for every later powered-emission tile; ban prospectively illegal staged geometry before routing; constrain search by exact band capacity; consume typed routing/projection evidence in bounded retries. Area may increase by at most 10% where required for legality.

**Tech Stack:** Python 3.14, Pydantic, immutable dataclasses/enums, OR-Tools CP-SAT, existing SequencePair SA/LNS, React 19, TypeScript, Zod, pytest, Vitest, Ruff, strict MyPy, Biome.

**Spec:** `docs/superpowers/specs/2026-08-30-reliability-first-layout-repair-design.md`

## Global Constraints

- Exact `finalize_placement` and `validate` acceptance remain unchanged.
- No larger deadline, routing expansion budget, stage count, arrangement count, worker count, archive, island count, or hidden retry floor.
- No global clearance increase or blanket candidate blacklist.
- Every task starts with a focused failing behavioral test and ends with focused tests/statics.
- Preserve original structured evidence when a repair does not succeed.
- Keep each task in a separate commit range and run review before starting a dependent task.
- Do not optimize the projected power-legality cache until Task 11 passes.

---

### Task 1: Finish SequencePair projection-safe pitch feedback

**Prerequisite plan:** `docs/superpowers/plans/2026-08-30-projection-safe-strip-pitch.md`, Task 3.

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Reuse: `src/flab2bp/layout/strip_variants.py`

- [ ] Execute Task 3 from the prerequisite plan exactly.
- [ ] Extend the existing stage-boundary transform rather than adding a second callback.
- [ ] Prove primary-state selection, ordinary sibling retention, superseded-padded migration, observation evidence, and the captured Chemical Plant scenario.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_sequence_solver.py -k "pitch or projection_failure or stage_boundary"
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
```

**Acceptance:** SequencePair consumes exact same-strip pitch feedback inside its existing stage work and returns a validator-clean captured case without changing a search bound.

---

### Task 2: Integrate the authoritative band catalog prerequisite

**Completed isolated implementation:** commits `6a1aadcbad3f01d5c426beb211ef666c8ef3c402` and `bd99676b33b147438ac15355f3756b06d96cfbe4`

**Files:**
- Add: `src/flab2bp/dsp/data/latitude_bands.json`
- Modify: `src/flab2bp/dsp/planet.py`
- Modify: `src/flab2bp/layout/band_policy.py`
- Modify: `src/flab2bp/cli.py`
- Modify: `src/flab2bp/web/jobs.py`
- Modify: `web/src/api/build.ts`
- Modify: `web/src/ui/BuildPanel.tsx`
- Modify: focused Python and web tests named by the isolated commit

- [ ] Review the isolated commit for authoritative dimensions, package-data inclusion, Python/TypeScript shared import, legacy segment canonicalization, height/width orientation, and finalizer frame semantics.
- [ ] Cherry-pick only after Critical and Important review findings are closed.
- [ ] Verify all 12 ordered capacities, including `160x1000` equator capacity while retaining legal full-height snapped-index anchors.
- [ ] Verify CLI and web parsing canonicalize meaningful legacy segment inputs before pipeline/finalizer handoff.
- [ ] Keep band 120 at `25x600`; do not claim this catalog correction repairs band-aware search.
- [ ] Run the isolated focused Python and web commands from its task report.

**Acceptance:** Packaged `latitude_bands.json` is the sole dimension authority imported and validated by Python and TypeScript; selectors display explicit physical dimensions and request canonical values.

---

### Task 3: Preserve sprayed and unsprayed cargo domains

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/sequence_solver.py` only where shared lane/net identity is constructed or consumed
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_strip_variants.py`
- Modify: `tests/layout/test_sequence_solver.py` if SequencePair has a separate identity projection

- [ ] Add an immutable `CargoDomain` in the existing shared strip/lane model module. Do not place it in a router-only module.
- [ ] Add deterministic RED controls for one produced item: every internal consumer proliferated, no consumer proliferated, a mixed internal set, and a requested-output boundary plus internal proliferated consumer.
- [ ] Derive internal destination domains from consumer proliferation mode. Assign requested-output/boundary sinks explicitly to `UNSPRAYED` unless an authoritative future spec field says otherwise.
- [ ] Prove uniform proliferated demand produces only `REQUIRES_SPRAY`, uniform clean demand only `UNSPRAYED`, and boundary-plus-proliferated or mixed internal demand produces both domains; `lanes_requiring_split` records coexistence.
- [ ] Partition destinations by domain before `_shard_sinks` and `_merge_lanes`.
- [ ] Carry `(item_id, cargo_domain)` through `_LogicalStripPlan`, logical lanes, `Strip.out_lanes`, `_Port`, `_Net`, sibling/join/shortcut keys, and island balance.
- [ ] Permit direct insertion only in `UNSPRAYED`; seat coaters on every `REQUIRES_SPRAY` lane, including uniform sprayed items not present in `lanes_requiring_split`.
- [ ] Keep user-facing material names item-only; domain is internal identity, not a synthetic DSP item.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/layout/test_sequence_solver.py -k "spray_domain or requiring_split or sprayed_lane or unsprayed"
uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/strip_variants.py src/flab2bp/layout/sequence_solver.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/strip_variants.py src/flab2bp/layout/sequence_solver.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/layout/test_sequence_solver.py
```

**Acceptance:** Uniform sprayed, uniform clean, and mixed items retain their correct domains from planning through routing; every `REQUIRES_SPRAY` lane receives its existing coater behavior, and the reported magnetic-coil path never sends sprayed cargo to an unproliferated consumer.

---

### Task 4: Cover the full powered-emission route envelope

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_freeform.py`

- [ ] Add a lifecycle RED test beside `TestPowerClaimsItsGroundBeforeRouting`: one legal tower site covers the core endpoint, while a later Splitter at the legal route-ring tile is currently uncovered. Add an in-radius control.
- [ ] Change `_power_plan` to accept an explicit demand envelope separate from `canvas.limit`.
- [ ] Pass `_grow(core, _ROUTE_RING)` as demand from `_prepare_routing_problem`; retain `canvas.limit` as tower-standing capacity.
- [ ] Update the stale core-only comment and no other power-spacing logic.
- [ ] Assert the outer entry ring is not added to powered demand.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_freeform.py -k "PowerClaimsItsGroundBeforeRouting or route_ring_power or power_coverage"
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
```

**Acceptance:** Any tile on which routing may later emit a Splitter is covered before routing; the exact old boundary fixture validates cleanly without post-route repair.

---

### Task 5: Ban projected Spray Coater/Splitter conflicts before routing

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_freeform.py`
- Reuse unchanged: `src/flab2bp/layout/finalize.py`

- [ ] Add the deterministic RED geometry: coater `(26,15,yaw=90)`, candidate Splitter `(25,17,z=1)`, band 160. Assert the first cell is banned and y=18 remains legal.
- [ ] After coater placement and capacity fixation, enumerate reachable projection frames and use `finalize.projected_coater_splitter_failure` to derive junction bans.
- [ ] Merge the derived cells into `_prepared_junction_ban`, the existing single prospective junction contract.
- [ ] Prove `_merge_frontier` and `_tap_source` both honor the merged ban; do not add a late special case to only one caller.
- [ ] Keep finalizer checking unchanged as the backstop.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_freeform.py -k "coater_splitter or prepared_junction_ban or addon_splitter"
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
```

**Acceptance:** The router cannot stage a Splitter in any coater lateral keepout reachable under the requested projections, and the adjacent legal control is not over-banned.

---

### Task 6: Select projection-safe staged-static seats

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/finalize.py` only to expose an existing exact predicate if no suitable callable exists
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_finalize.py` only for predicate parity

- [ ] Add RED tests for both observed ownerless-static classes: a staged coater versus an existing machine with an ordered projection-safe alternate seat, and plastic/output-products' post-pitch Chemical Plant owner strip 2 versus direct power building item 2201 owner `None` pair `(181, 255)`.
- [ ] Add shared immutable `ExactPackNoGood(height, outline, width, origins, evidence)` and the existing Freeform packer consumer before using it here. Tasks 8 and 10 extend this same mechanism.
- [ ] Expose/reuse a prospective staged-static predicate with the same collider condition, projection ordering, and reachable envelope as finalization.
- [ ] Change deterministic seat/offset selection to enumerate alternatives and choose the first projection-safe seat.
- [ ] For pack-dependent exhaustion, emit `ExactPackNoGood` so the unchanged pack cannot repeat.
- [ ] For same-strip invariant exhaustion, derive a typed staged-static clearance requirement and regenerate an on-demand physical lane/attachment variant with the next deterministic coater offset or one-tile lane extension; include this geometry in variant identity and use existing strategy feedback paths.
- [ ] If bounded physical alternatives are exhausted, emit an explicit terminal structured projection refusal preserving exact evidence.
- [ ] Prove alternate-seat advancement, invariant physical escalation, pack-dependent no-good, and terminal exhaustion separately; a test that merely raises earlier is insufficient.
- [ ] Prove exact predicate parity with finalization.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_freeform.py tests/layout/test_finalize.py -k "staged_static or prospective_projection or alternate_seat or static_clearance_requirement"
uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/finalize.py tests/layout/test_freeform.py tests/layout/test_finalize.py
uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/finalize.py tests/layout/test_freeform.py tests/layout/test_finalize.py
```

**Acceptance:** Every staged ownerless static chooses a projection-safe seat, escalates a pack-invariant relation through a physically distinct attachment variant, excludes a pack-dependent exact assignment, or terminates with explicit structured evidence.

---

### Task 7: Make candidate heights band-policy-aware and gate exact extents early

**Files:**
- Modify: `src/flab2bp/layout/finalize.py` only if extracting a shared pure frame-capacity helper
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `tests/layout/test_finalize.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`

- [ ] Add RED tests that explicit band 120 contributes legal core-height boundary 19 with the existing three-tile perimeter, for both strategies.
- [ ] Add RED tests that an empty exact frame-candidate set is infeasible before power planning or detailed routing, in both orientations.
- [ ] Extract one pure band-policy search-envelope helper from existing `BandPolicy`, `planet.Band`, perimeter, and finalizer orientation semantics.
- [ ] Preserve the pre-change schedule cardinality. For an explicit fixed band, reserve at most one boundary slot by replacing the first existing height the exact capacity predicate proves infeasible; retain all others in original order. If none is proved infeasible, do not alter the schedule.
- [ ] Preserve the `portable`/multi-band schedule exactly; apply policy only through the early exact extent gate.
- [ ] Add actual layout regressions for every dropped explicit-band height, proving the retained boundary schedule preserves its clean result; orientation-only controls are insufficient. Record ordered schedules.
- [ ] Add the exact early capacity gate before power planning/detailed routing. Treat `()` as failure, never as no constraints.
- [ ] Preserve finalization as the acceptance proof.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -k "band_policy_height or extent_gate or band_120 or schedule_cardinality or portable_schedule"
uv run ruff check src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
```

**Acceptance:** Explicit narrow bands receive one proved-needed boundary slot; portable/multi-band schedules remain unchanged; impossible extents are rejected early; actual layout controls preserve dropped-height coverage.

---

### Task 8: Consume different-strip projection feedback in both strategies

**Files:**
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `tests/layout/test_finalize.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`

- [ ] Add a Freeform RED regression where moving an unrelated third strip currently makes the rejected implicated pair selectable again.
- [ ] Add a SequencePair RED regression where an exact different-strip projection failure currently reaches no stage feedback and repeats.
- [ ] Define the smallest sound no-good context only when the exact projection predicate proves the pair relation independent of all other geometry.
- [ ] Reuse shared `ExactPackNoGood` for the full exact assignment whenever pair independence is not proved.
- [ ] Feed Freeform through its current retry/cut path and SequencePair through its existing stage-boundary transform; add no second callback.
- [ ] Add controls showing changed implicated geometry remains eligible, while unrelated strip movement cannot erase a proved pair relation.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -k "projection_no_good or unrelated_strip or different_strip_feedback"
uv run ruff check src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/finalize.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_finalize.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
```

**Acceptance:** Neither strategy can repeat unchanged exact different-strip evidence merely because unrelated geometry moved; legal changed relations remain searchable.

---

### Task 9: Retain typed pack attempts and make direct inserts truthful

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_freeform.py`

- [ ] Add immutable `PackAttempt` carrying origins, compact width, height/outline, full `DetailedRouteResult`, typed static-access evidence, and promised/realized direct-insert IDs.
- [ ] Add RED tests proving `_sweep` currently discards those identities.
- [ ] Make `_bridge` return/report promised-versus-realized direct keys instead of silently restoring a rewarded net.
- [ ] Encode occupied-lane and sorter-collider preconditions for rewardable direct inserts. Remove the reward for any candidate whose realization is not structurally provable.
- [ ] Add a hard behavioral assertion that every rewarded direct insert is realized; an unrealized promise remains typed evidence and never disappears.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_freeform.py -k "pack_attempt or promised_direct or realized_direct"
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
```

**Acceptance:** Freeform retains every attempt's routing and direct-insert evidence, and every rewarded direct insertion is structurally realizable and actually emitted.

---

### Task 10: Apply proof-scoped routing feedback within bounded slack

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify only if a shared proof marker is missing: `src/flab2bp/layout/route_feedback.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_route_feedback.py`

- [ ] Add RED tests for each proof class: `STATIC_ACCESS`, structurally impossible promised direct insert, exhaustive non-budget detailed-route failure, non-exhaustive failure, and budget exhaustion.
- [ ] Permit a local no-good only when an exact predicate proves the relation independent of other obstacles/routes.
- [ ] For an exhaustive non-budget failure without a smaller proof, emit shared `ExactPackNoGood` for the full assignment.
- [ ] For non-exhaustive and budget failures, add no no-good; retain evidence for reporting only.
- [ ] Use stable `NetId`, endpoint relations, hot walls, blockers, and `FeedbackState` as failed-net-specific objective weights. Do not restore the global backward-edge penalty.
- [ ] Establish compact `W*`, then allow evidence-driven packs under `width <= ceil(1.10 * W*)`; add no arrangements or solver time.
- [ ] Add a fixture where the compact assignment fails proof-completely and a bounded alternative routes cleanly; assert identical rejected assignments do not recur.
- [ ] Exercise the captured 17-strip output-products case under its existing deadline.
- [ ] Run:

```bash
uv run pytest -q tests/layout/test_route_feedback.py tests/layout/test_freeform.py -k "proof_scoped or exhaustive or width_slack or static_access or route_feedback"
uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py tests/layout/test_freeform.py tests/layout/test_route_feedback.py
uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py tests/layout/test_freeform.py tests/layout/test_route_feedback.py
```

**Acceptance:** Only proof-complete failures exclude geometry; unproved/budget failures remain evidence only; the captured refusal receives an evidence-driven alternative without exceeding internal width slack or any work bound.

---

### Task 11: Run reliability, quality, and complete verification gates

**Files:**
- Modify tests only if a genuinely uncovered observable contract is found
- Record results in the existing benchmark/report artifact path; do not add ad hoc checked-in logs

- [ ] Record a before/after manifest of exact values for per-layout deadlines, Freeform arrangements and candidate-height cardinality, detailed/global expansion limits, SequencePair stage/move/archive/island limits, and search workers.
- [ ] Run the deterministic focused regression set for every reported failure.
- [ ] Run three paired frozen-baseline-then-candidate repetitions with `--jobs 1` for every supplied external `(URL, strategy, policy, requested band)` scenario at its unchanged budget; pair by repeat ordinal.
- [ ] Run three paired baseline-then-candidate repetitions of `URL_CORPUS × 2 strategies × 3 policies` at budget 15 with 16 audit jobs: exactly 216 external requests per arm.
- [ ] Require 216/216 `CLEAN`, zero `INVALID`, zero `CRASH`, no paired baseline-clean coverage loss, and no candidate identity loss.
- [ ] Require every paired clean final-frame area ratio and the paired geometric mean to be at most 1.10. Report any non-clean baseline repetition as absolute candidate area without inventing a ratio; every candidate repetition must still be `CLEAN`.
- [ ] Require the work-bound manifest values to remain identical.
- [ ] Run final static/full verification once:

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest -q
cd web && bun run test
cd web && bun run lint
cd web && bun run typecheck
cd web && bun run build
```

- [ ] Run production CLI smoke builds for both `freeform` and `sequence-pair`, decode each blueprint, and require exact validation clean.
- [ ] Request final code review across the complete reliability commit range.

**Acceptance:** The 216-request corpus, supplied-scenario matrix, per-scenario and aggregate area gates, work-bound manifest, static checks, tests, web build, and CLI smokes all satisfy the exact thresholds. Only then may the projected power-legality cache plan begin.
