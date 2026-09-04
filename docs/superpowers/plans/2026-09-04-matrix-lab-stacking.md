# Matrix Lab Vertical Stacking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pack Matrix Labs into vertically linked columns up to the save's researched lab level, while preserving exact machine counts, throughput, paste legality, and both production layout strategies.

**Architecture:** Carry the URL-derived Matrix Lab stack limit on `BuildSpec`, the existing rates-to-geometry boundary. Represent each physical strip variant as horizontal column origins plus deterministic per-column lab counts; non-labs remain one machine per column. Bound each lab column by both Vertical Construction research and the fastest legal sorter that can move that column's aggregate rate. Emit one sorter set on each ground lab and a slot-14/15 support chain above it. Teach the neutral validator that a uniform linked lab column shares the base lab's material connections while every lab remains a separately counted, powered production machine. Freeform and SequencePair consume the same stack-aware strip variants; neither gets a private stacking path.

**Tech Stack:** Python 3.14, Pydantic `BuildSpec`, existing strip-family/variant model, OR-Tools CP-SAT, DSP blueprint codec, pytest (serial), Ruff, strict MyPy, `uv run`.

**Authority:** `src/flab2bp/dsp/catalog.py::stack_pitch_z` gives Matrix Labs an exact blueprint-z pitch of 3; `vertical_construction_allowed` compares the resulting stack index to `BeltAltitudeRules.lab_level`. The game-written fixture `tests/fixtures/12-s-purple-science-from-smelted-refined-products.txt` contains 120 Matrix Labs as 10 columns of 12 at z `0, 3, ..., 33`. Only ground labs have sorters; every elevated lab names the lab immediately below through its input record, with own slot 14 and lower-lab slot 15. All 120 labs carry the same recipe and parameter block.

## Global Constraints

- **Preserve acceptance authority.** `finalize.finalize_placement`, detailed routing, power completion, and `validate.certify` remain the only path to a returned `Placement`. No task suppresses a finding, weakens collision geometry, or counts an unlinked elevated lab as productive.
- **One shared representation.** Stacking lives in `StripVariant`/`Strip`; Freeform and SequencePair must consume the same column topology. A post-layout pass that folds already-routed labs is prohibited because it would invalidate sorter rates, slot claims, power coverage, packing dimensions, and projection feedback.
- **Physical machine count stays physical.** `MachineGroup.count`, `StripFamily.total_machine_count`, `StripInstance.machine_count`, `Strip.machines`, `spec.machine_counts`, and UI machine counts continue to mean actual labs, including elevated labs. Add explicit column-height data; do not reinterpret an existing count as columns.
- **Tech is a ceiling, not a command.** A column may be shorter than `BuildSpec.lab_stack_limit` when the group count, strip partition, or sorter throughput requires it. A save at lab level 1 remains byte-for-byte unstacked at the strip/emission boundary.
- **Sorter throughput is aggregate.** One base sorter serving a column is charged the per-machine item rate multiplied by that column's lab count, including cargo-stack pick/place constraints. If the tallest tech-legal column would overload the fastest researched sorter, use more shorter columns. Never emit the fastest sorter and rely on validation to reject an avoidable overload.
- **Uniform columns only.** Every lab in a generated column has the same item, model, yaw, recipe, parameters, and owner strip. Mixed recipes or lab types are outside this feature and must not be inferred as safe from the game's ability to paste them.
- **Exact stack records.** Elevated labs sit at `level * catalog.stack_pitch_z(item_id)`, name only their immediate lower support, and use the fixture-backed slot pair 14/15. Sorters connect only to the base lab. No reciprocal or transitive support links.
- **No planar collision exception.** Existing 3D collider projection already accepts the real 12-high fixture. Do not exempt same-x/y labs from `geom.collide`; prove the exact z pitch is clean and an off-pitch overlap still fails.
- **LSP first.** Before changing `BuildSpec`, `StripVariant`, `StripInstance`, `Strip`, `_link_lane`, `validate`, or `certify`, run LSP references. If the known Python LSP cancellation defect recurs, use AST queries scoped to the named modules and record the fallback in task evidence.
- **TDD and serial tests.** Add each named behavioral test first, run it to observe the intended failure, then implement the smallest passing change. Never use `pytest-xdist`; CP-SAT already uses parallel workers internally.
- **Benchmark isolation.** Capture the matrix-heavy baseline before implementation in a dedicated worktree/branch. Use identical URL corpus, budget, strategy set, worker count, and machine load for the after run.
- **Clean cutover.** Remove the statement that the generator never stacks labs, update the rule registry's current “unconsulted” note, and migrate all constructor/copy sites. No deprecated field, compatibility alias, duplicate stack formula, or strategy-specific fallback remains.

---

### Task 0: Instrument the audit and capture the unstacked baseline

This task precedes every production change. The same committed measurement
schema must produce both artifacts; do not compare old-schema baseline rows
with new-schema stacked rows.

**Files:**
- Modify: `scripts/audit.py`
- Modify: `tests/scripts/test_audit.py`
- Create: `docs/superpowers/evidence/2026-09-04-matrix-lab-stacking/baseline.jsonl`
- Create: `docs/superpowers/evidence/2026-09-04-matrix-lab-stacking/comparison.md`

**Interfaces:**

Extend `Result` and its JSON row with independently measured:

```python
belt_tiles: int
physical_machine_count: int
matrix_lab_count: int
ground_matrix_lab_columns: int
max_lab_stack_height: int
lab_stack_limit: int
```

Use `bench.metrics.measure(placement)` for belt tiles and physical machines.
Derive the Matrix Lab fields from emitted item IDs and `(x, y, z)` geometry,
not strategy stats. `lab_stack_limit` comes directly from
`_belt_rules_for(job.url).lab_level`; it is evidence about the save even before
`BuildSpec` gains the field. Refused/crashed rows use zero for emitted-geometry
counts but still carry the URL limit.

- [ ] **Step 1: Add failing audit serialization tests**

In `tests/scripts/test_audit.py`, add one clean synthetic placement containing
two ground labs and one pitch-3 elevated lab. Assert the JSON row reports three
physical Matrix Labs, two ground columns, maximum height two, the independent
belt count, total physical machine count, and the URL-derived limit. Add a
placement-free refusal assertion proving geometry counts are zero rather than
missing.

Run:

```bash
uv run pytest -q tests/scripts/test_audit.py
```

Expected before implementation: the six evidence keys are absent.

- [ ] **Step 2: Implement strategy-independent measurements**

Add the six typed `Result` fields and populate them at the single successful
placement boundary before CLEAN/INVALID branching. Reuse the same helper for a
projection-refused placement. Do not read `Placement.stats["belt_tiles"]` or a
strategy's machine count. Extend the JSON writer and comparison reader tests so
missing keys are rejected for new evidence rows rather than silently read as
zero.

- [ ] **Step 3: Verify the instrumented baseline**

```bash
uv run pytest -q tests/scripts/test_audit.py
uv run ruff check scripts/audit.py tests/scripts/test_audit.py
uv run mypy
```

- [ ] **Step 4: Capture and commit the unstacked baseline**

Use one non-lab control plus both matrix-heavy URLs:

```bash
D=docs/superpowers/evidence/2026-09-04-matrix-lab-stacking
mkdir -p "$D"
rm -f "$D/baseline.jsonl"
uptime
vmstat 1 3
uv run python scripts/audit.py --budget 30 --jobs 3 --max-seconds 180 \
  --only graphene,information-matrix,universe-matrix --json "$D/baseline.jsonl"
```

Record the exact commit, CPU affinity, backend provenance, command, and load in
`comparison.md`. Confirm every JSONL row contains the six evidence keys before
starting Task 1.

```bash
git add scripts/audit.py tests/scripts/test_audit.py \
  docs/superpowers/evidence/2026-09-04-matrix-lab-stacking
git commit -m "bench: capture matrix lab stacking baseline"
```

---

### Task 1: Lock the game-written lab stack record contract

**Files:**
- Modify: `src/flab2bp/dsp/rules.py`
- Modify: `src/flab2bp/dsp/registry.py`
- Modify: `tests/rules/test_paste_rules.py`
- Modify: `tests/rules/test_rule_registry.py`

**Interfaces:**

Add fixture-backed constants beside the existing connection-slot constants:

```python
LAB_STACK_INPUT_TO_SLOT = 14
LAB_STACK_INPUT_FROM_SLOT = 15
```

These are record slots, not sorter insert poses. Slot 14 belongs to the elevated lab's input record; slot 15 belongs to the lower support lab.

- [ ] **Step 1: Resolve rule references**

Run LSP references for the existing splitter stack slot use and `catalog.vertical_construction_allowed`. Inspect the registry entry for `vertical_construction_allowed`; do not add a second height predicate.

- [ ] **Step 2: Add a failing fixture contract test**

Add `test_game_written_matrix_lab_stacks_use_pitch_three_and_immediate_slot_14_15_links` in `tests/rules/test_paste_rules.py`. Decode `12-s-purple-science-from-smelted-refined-products.txt` and assert:

- exactly 120 item-2901 labs;
- 10 horizontal `(x, y)` columns;
- each column has rounded z levels `(0, 3, 6, ..., 33)`;
- every elevated lab's `input_obj_idx` resolves to the lab at the same `(x, y)` and z minus 3;
- `input_to_slot == 14`, `input_from_slot == 15`, and `output_obj_idx == -1` on elevated labs;
- base labs have no lab-support input;
- all lab recipes and parameter blocks are uniform;
- every sorter naming a lab names a ground lab.

Run:

```bash
uv run pytest -q tests/rules/test_paste_rules.py::test_game_written_matrix_lab_stacks_use_pitch_three_and_immediate_slot_14_15_links
```

Expected before implementation: import failure for the two named constants.

- [ ] **Step 3: Add constants and registry provenance**

Define the constants once in `dsp/rules.py`; use them in the fixture test. Update `dsp/registry.py` so the slot pair and `vertical_construction_allowed` point to the game paste/fixture evidence and no longer claim lab stacking has no layout consumer.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest -q tests/rules/test_paste_rules.py tests/rules/test_rule_registry.py
uv run ruff check src/flab2bp/dsp/rules.py src/flab2bp/dsp/registry.py \
  tests/rules/test_paste_rules.py tests/rules/test_rule_registry.py
uv run mypy
```

Commit only the four files:

```bash
git add src/flab2bp/dsp/rules.py src/flab2bp/dsp/registry.py \
  tests/rules/test_paste_rules.py tests/rules/test_rule_registry.py
git commit -m "test: lock matrix lab stack records"
```

---

### Task 2: Carry the URL-derived lab stack limit on BuildSpec

**Files:**
- Modify: `src/flab2bp/spec.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: `scripts/audit.py`
- Modify: `tests/test_spec.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/scripts/test_audit.py`

**Interfaces:**

Add one geometry/save-rule field:

```python
lab_stack_limit: int = Field(default=1, ge=1)
```

`1` preserves hand-built specs and direct layout tests. Production
`pipeline.build` replaces it on every candidate with `belt_rules.lab_level`
immediately after candidate generation and before flow/no-proliferator
filtering. The independent audit entry point must do the same in `_specs_for`
with `_belt_rules_for(url).lab_level`; otherwise the benchmark silently measures
the unstacked default. Because `_StrategyRaceRequest` already transports the
complete frozen `BuildSpec`, serial and raced strategies receive the same value
without another race protocol field.

- [ ] **Step 1: Resolve every BuildSpec construction/copy site**

Run LSP references for `BuildSpec` and `BuildSpec.model_copy`. Confirm candidate
derivation copies unknown model fields. Identify both orchestration boundaries:
the production pipeline after its shared candidate solve, and
`scripts/audit.py::_specs_for` before its candidate tuple enters the per-process
cache.

- [ ] **Step 2: Add failing boundary tests**

Add:

- `test_lab_stack_limit_defaults_to_one_and_rejects_zero` in `tests/test_spec.py`;
- `test_pipeline_copies_url_lab_level_to_every_candidate_spec` in `tests/test_pipeline.py`;
- `test_raced_layout_receives_the_same_lab_stack_limit_as_serial_layout` in `tests/test_pipeline.py`;
- `test_audit_spec_cache_copies_url_lab_level_to_every_candidate` in
  `tests/scripts/test_audit.py`.

The pipeline and audit tests derive the expected value with the existing belt
rules helper, capture every candidate at the layout boundary, and compare the
exact integer. Do not hard-code the fully researched URL's level.

Run only the four tests. Expected before implementation: missing field or
captured default `1` instead of the URL-derived level.

- [ ] **Step 3: Implement both real entry points**

Add the field and its validation. Rebuild `BuildSpecSet` once in the pipeline
from candidates updated with
`model_copy(update={"lab_stack_limit": belt_rules.lab_level})`. In
`scripts/audit.py::_specs_for`, apply the same `model_copy` update with
`_belt_rules_for(url).lab_level` before storing candidates in `_SPECS`. Both
entry points derive the value through `belt_rules_for_url`; do not duplicate the
technology formula. Keep flow filtering, policy ordering, and audit cache keys
unchanged.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest -q tests/test_spec.py tests/test_pipeline.py tests/scripts/test_audit.py
uv run ruff check src/flab2bp/spec.py src/flab2bp/pipeline.py scripts/audit.py \
  tests/test_spec.py tests/test_pipeline.py tests/scripts/test_audit.py
uv run mypy
```

```bash
git add src/flab2bp/spec.py src/flab2bp/pipeline.py scripts/audit.py \
  tests/test_spec.py tests/test_pipeline.py tests/scripts/test_audit.py
git commit -m "feat: carry matrix lab stack limits"
```

---

### Task 3: Represent physical labs as bounded horizontal columns

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_strip_variants.py`

**Interfaces:**

Extend `StripVariant` and `StripVariantId` with:

```python
column_heights: tuple[int, ...]
max_stack_height: int
```

Invariants:

- `len(machine_origins_x) == len(column_heights)`;
- `sum(column_heights)` is the physical machine count realized by that variant;
- every height is in `1..max_stack_height`;
- non-labs have `max_stack_height == 1` and all heights equal 1;
- Matrix Lab columns are balanced deterministically: choose the minimum number of columns, then distribute `machine_count` as `base + 1` in the earliest `extra` columns and `base` in the rest;
- `StripVariantId` and `template_key` include stack capability/topology so projection feedback and no-goods cannot cross a different z arrangement.

Add a private `_safe_lab_stack_height(spec, group, variant)` that caps `spec.lab_stack_limit` by exact sorter throughput for every input/output attachment. Reuse `_sorter_tiers_for`, `_sorter_stacks_for`, `_lane_stacks_for`, `_pick_sorter`, and `catalog.sorter_rate`; do not duplicate sorter tier or cargo-stack formulas. Test heights from the requested limit down and retain the highest height whose selected legal tier actually sustains `per_machine_rate * height` for every attachment. Matrix Labs with east-flank output must include that output span in the same proof.

`partition_strip_variant(..., max_machine_count=N)` continues to expose a horizontal strip-length control: for a variant with stack height `H`, it may assign at most `N * H` physical labs before applying the existing lane `machine_cap`. `StripInstance.machine_count` and its ordinal range remain physical lab counts.

- [ ] **Step 1: Resolve variant and partition consumers**

Run LSP references for `StripVariant`, `StripVariantId`, `StripPoseId`, `_variant_for_count`, `partition_strip_variant`, `split_strip_instance`, `merge_strip_instances`, and `Strip.width`. Record every constructor before adding required fields.

- [ ] **Step 2: Add failing topology tests**

Add:

- `test_matrix_lab_variant_balances_ten_labs_into_four_level_three_columns`;
- `test_matrix_lab_variant_uses_one_column_when_tech_and_sorters_allow_it`;
- `test_non_lab_variant_keeps_one_machine_per_column_at_high_lab_level`;
- `test_matrix_lab_variant_reduces_stack_height_when_sorter_rate_would_overload`;
- `test_partition_strip_variant_caps_columns_while_preserving_physical_ordinals`;
- `test_variant_identity_distinguishes_lab_stack_topology`;
- `test_split_and_merge_preserve_every_physical_lab_exactly_once`.

Use hand-built `BuildSpec`s with explicit `lab_stack_limit`, sorter tiers, and rates. The overload test must have a middle feasible height, proving the planner chooses it rather than only “max or unstacked.”

Run the seven tests. Expected before implementation: missing fields and unstacked widths.

- [ ] **Step 3: Implement stack-aware variants**

Generate ordinary pose/attachment plans first, derive each pose's safe lab height, and rebuild its machine origins, box width, ID, and balanced `column_heights`. Update count realization, pitch widening, partition, split, merge, and family/instance invariant checks together. Keep non-lab outputs structurally identical.

Project the selected variant into `Strip` with a required `column_heights` field. Change `Strip.width` to `len(column_heights) * pw`; retain `Strip.machines == sum(column_heights)`.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest -q tests/layout/test_strip_variants.py
uv run ruff check src/flab2bp/layout/strip_variants.py \
  src/flab2bp/layout/freeform.py tests/layout/test_strip_variants.py
uv run mypy
```

```bash
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py \
  tests/layout/test_strip_variants.py
git commit -m "feat: model matrix lab stack columns"
```

---

### Task 4: Emit linked lab columns with aggregate sorter loads

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/dsp/test_codec.py`

**Interfaces:**

In `_emit_strip`, replace the flat machine loop with column emission:

1. emit the ground machine at each horizontal origin;
2. for each additional Matrix Lab level, emit an identical lab at `z = level * catalog.stack_pitch_z(item_id)`;
3. set the elevated lab's `input_obj` to the previous level, `input_to_slot=LAB_STACK_INPUT_TO_SLOT`, and `input_from_slot=LAB_STACK_INPUT_FROM_SLOT`;
4. retain every emitted lab in the placement, but pass only ground-lab indices to sorter/flank attachment helpers;
5. pass the aligned column height to `_link_lane` and `_flank_lane`, sizing each sorter's load as `per_machine_rate * column_height`;
6. keep `_Port.machines` equal to the strip's physical lab count so lane demand and inter-strip routing stay aggregate.

Non-lab columns all have height 1 and must traverse the same implementation without a parallel legacy emitter.

- [ ] **Step 1: Resolve emission helper references**

Run LSP references for `_emit_strip`, `_link_lane`, `_flank_lane`, `_dock_input_lane`, and `_dock_lane`. Any helper that iterates the machine-index list must either receive ground column bases plus heights or prove it is unreachable for Matrix Labs.

- [ ] **Step 2: Add failing emission tests**

Add:

- `test_emit_strip_builds_immediate_matrix_lab_support_chains`;
- `test_emit_strip_attaches_sorters_only_to_ground_labs`;
- `test_emit_strip_sizes_each_sorter_for_its_column_aggregate_rate`;
- `test_emit_strip_preserves_recipe_parameters_yaw_and_owner_on_every_level`;
- `test_unstacked_non_lab_emission_is_unchanged`;
- `test_matrix_lab_stack_links_survive_blueprint_encode_decode`.

For a seven-lab, level-three strip, assert balanced column heights `(3, 2, 2)`, exact z values, exact support indices/slots, seven physical lab records, and three base attachment sets. The sorter-rate test chooses rates where height 1 permits a lower tier and height 3 requires a higher tier.

Run the six tests. Expected before implementation: all seven labs are at distinct x positions and every lab owns sorters.

- [ ] **Step 3: Implement column emission**

Use `Fraction` z values until `codec.encode`. Fail loudly if a non-lab variant carries a height above one or a Matrix Lab lacks a catalog pitch. Preserve canonical building order: each column bottom-to-top, then the next column, then sorters. Building-index links must be computed from returned `canvas.add` indices, never by arithmetic assumptions.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest -q \
  tests/layout/test_freeform.py::test_emit_strip_builds_immediate_matrix_lab_support_chains \
  tests/layout/test_freeform.py::test_emit_strip_attaches_sorters_only_to_ground_labs \
  tests/layout/test_freeform.py::test_emit_strip_sizes_each_sorter_for_its_column_aggregate_rate \
  tests/layout/test_freeform.py::test_emit_strip_preserves_recipe_parameters_yaw_and_owner_on_every_level \
  tests/layout/test_freeform.py::test_unstacked_non_lab_emission_is_unchanged \
  tests/dsp/test_codec.py::test_matrix_lab_stack_links_survive_blueprint_encode_decode
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/dsp/test_codec.py
uv run mypy
```

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/dsp/test_codec.py
git commit -m "feat: emit linked matrix lab stacks"
```

---

### Task 5: Make neutral certification understand lab columns

**Files:**
- Modify: `src/flab2bp/layout/validate.py`
- Modify: `tests/layout/test_validate.py`

**Interfaces:**

Add cached stack topology to `Context` through private helpers:

```python
def _lab_support_index(ctx: Context, lab_index: int) -> int | None: ...
def _lab_stack_root(ctx: Context, lab_index: int) -> int: ...
def _lab_stack_members(ctx: Context, lab_index: int) -> tuple[int, ...]: ...
def _lab_stack_size(ctx: Context, lab_index: int) -> int: ...
```

A valid generated column requires exact Matrix Lab membership, x/y equality, catalog pitch, immediate lower z, slot 14/15 input link, and uniform item/model/yaw/recipe/parameters. Add checks:

- `game.lab_stack_support`: every elevated Matrix Lab has exactly the immediate valid lower support;
- `game.lab_stack_height`: every Matrix Lab satisfies `catalog.vertical_construction_allowed(..., spec.lab_stack_limit)` through a `BeltAltitudeRules` value or an equivalent call that still uses the central predicate;
- `machine.lab_stack_uniform`: a linked column has uniform operational fields.

Retain `geom.machine_ground` for non-lab machines; skip only Matrix Labs that the dedicated checks judge. Do not add a collision exception.

Make functional validation stack-aware:

- `_inputs_supplied` and `_output_removed` use the root lab's sorter/port connections for every member;
- `_islands` unions every valid support edge so all member production and consumption sit in the base lab's material-flow island;
- `_sorter_demand` multiplies the base lab's per-machine rate by `_lab_stack_size` before dividing among same-item peer sorters;
- `_sorter_peers` remains keyed by the actual root endpoint;
- `spec.machine_counts` continues counting every physical lab record;
- unresolved/invalid support never gains shared flow; its dedicated error remains visible.

Audit every `ctx.of_kind(Kind.MACHINE)` consumer. Update only checks whose question is about material connections; recipe identity, physical count, power, and collider checks remain per physical lab.

- [ ] **Step 1: Add failing geometry and support tests**

Add:

- `test_geom_machine_ground_allows_a_valid_elevated_matrix_lab`;
- `test_geom_machine_ground_still_rejects_an_elevated_non_lab_machine`;
- `test_lab_stack_support_rejects_gap_offset_wrong_slot_and_non_lab_support`;
- `test_lab_stack_height_accepts_the_last_researched_level_and_rejects_the_next`;
- `test_lab_stack_uniform_rejects_recipe_model_yaw_and_parameter_drift`;
- `test_geom_collide_accepts_exact_lab_pitch_and_rejects_an_off_pitch_stack`.

Use table-driven negative cases with one changed field each. Run only these tests and observe the old `geom.machine_ground` failure plus missing new checks.

- [ ] **Step 2: Implement topology and game-rule checks**

Build stack maps once per `Context`; detect cycles and multiple upper labs claiming one support as errors rather than recursing indefinitely. Use the central catalog pitch and height predicate. Update the stale `OutOfVerticalConstructionHeight` comment that says the generator never stacks labs.

- [ ] **Step 3: Add failing throughput tests**

Add:

- `test_lab_stack_members_share_the_base_input_connections`;
- `test_lab_stack_members_share_the_base_output_connections`;
- `test_lab_stack_flow_island_counts_every_members_rate`;
- `test_lab_stack_base_sorter_is_charged_the_whole_column_rate`;
- `test_lab_stack_spec_machine_count_counts_every_level`;
- `test_unlinked_elevated_lab_never_inherits_base_flow`.

The sorter-capacity test must fail with a height-three column and a tier sufficient for one lab but insufficient for three; its positive control uses the next sufficient tier. The island test must fail if upper labs are left as isolated machine nodes.

- [ ] **Step 4: Implement stack-aware functional checks**

Route material-connection lookups through the validated stack root and scale base sorter demand once. Do not multiply both `_sorter_demand` and `_run_demand`; the latter must receive the already-aggregated sorter flow exactly once.

- [ ] **Step 5: Validate the real fixture topology**

Add `test_real_twelve_high_matrix_lab_columns_pass_stack_checks` using the decoded fixture contract from Task 1 and an explicit level-12 rule. It must run the dedicated stack checks and `geom.collide`; it need not claim full spec/flow certification for a fixture without a `BuildSpec`.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest -q tests/layout/test_validate.py
uv run ruff check src/flab2bp/layout/validate.py tests/layout/test_validate.py
uv run mypy
```

```bash
git add src/flab2bp/layout/validate.py tests/layout/test_validate.py
git commit -m "feat: certify matrix lab stack flow"
```

---

### Task 6: Prove both production strategies and the pipeline use stacking

**Files:**
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/web/test_payload.py`

**Interfaces:** No new implementation path. These are changed-contract integration tests over the shared strip representation, full finalization/certification, blueprint encoding, and user-facing counts.

- [ ] **Step 1: Add a deterministic matrix-lab integration fixture**

Create a local test `BuildSpec` with seven Matrix Labs, two ingredients, one product, `lab_stack_limit=3`, sorter capacity sufficient for three labs, and a small deterministic band. Reuse it across the Freeform and SequencePair tests without adding a production fixture module.

- [ ] **Step 2: Add strategy integration tests**

Add:

- `test_freeform_returns_a_certified_stacked_matrix_lab_placement`;
- `test_sequence_pair_returns_a_certified_stacked_matrix_lab_placement`.

Each test asserts seven lab records, three ground columns, max z 6, exact support links, clean certification, and a framed/encodable placement. Pin deterministic workers/config already used by neighboring tests; use the smallest existing time budget that passes reliably.

- [ ] **Step 3: Add pipeline and payload contract tests**

Add:

- `test_pipeline_uses_the_url_lab_level_and_returns_every_stacked_lab`;
- `test_payload_machine_count_remains_physical_when_labs_are_stacked`.

The payload test asserts `machines == spec.machine_count`, not the number of ground columns. The pipeline test also asserts the selected attempt blueprint decodes with the same lab count and legal maximum stack index.

- [ ] **Step 4: Run integration verification and commit**

```bash
uv run pytest -q \
  tests/layout/test_freeform.py::test_freeform_returns_a_certified_stacked_matrix_lab_placement \
  tests/layout/test_sequence_solver.py::test_sequence_pair_returns_a_certified_stacked_matrix_lab_placement \
  tests/test_pipeline.py::test_pipeline_uses_the_url_lab_level_and_returns_every_stacked_lab \
  tests/web/test_payload.py::test_payload_machine_count_remains_physical_when_labs_are_stacked
uv run ruff check tests/layout/test_freeform.py tests/layout/test_sequence_solver.py \
  tests/test_pipeline.py tests/web/test_payload.py
uv run mypy
```

```bash
git add tests/layout/test_freeform.py tests/layout/test_sequence_solver.py \
  tests/test_pipeline.py tests/web/test_payload.py
git commit -m "test: cover stacked labs end to end"
```

---

### Task 7: Measure footprint gain and close documentation

**Files:**
- Create: `docs/superpowers/evidence/2026-09-04-matrix-lab-stacking/stacked.jsonl`
- Modify: `docs/superpowers/evidence/2026-09-04-matrix-lab-stacking/comparison.md`
- Modify: `docs/WEB_UI.md`
- Modify: `src/flab2bp/dsp/registry.py`

**Interfaces:** The gate compares `graphene` as a non-lab control plus the
`information-matrix` and `universe-matrix` matrix-heavy URLs under both
production strategies and all canonical candidate policies. Baseline and
stacked JSONL use the exact `Result` schema committed in Task 0.

- [ ] **Step 1: Capture the stacked run under identical conditions**

After Tasks 1-6, with compiled backends available, run the same command and
machine-load preflight used for the baseline:

```bash
D=docs/superpowers/evidence/2026-09-04-matrix-lab-stacking
rm -f "$D/stacked.jsonl"
uptime
vmstat 1 3
uv run python scripts/audit.py --budget 30 --jobs 3 --max-seconds 180 \
  --only graphene,information-matrix,universe-matrix --json "$D/stacked.jsonl"
```

Do not change budget, jobs, policy set, URL corpus, worker count, or band policy.
Reject the capture if any row lacks `belt_tiles`, `physical_machine_count`,
`matrix_lab_count`, `ground_matrix_lab_columns`, `max_lab_stack_height`, or
`lab_stack_limit`.

- [ ] **Step 2: Judge the gate**

`comparison.md` reports per cell: status, area, belt tiles, physical machine
count, Matrix Lab count, ground Matrix Lab columns, maximum stack height,
URL-derived stack limit, and elapsed seconds.

The feature passes only when:

- every previously CLEAN cell remains CLEAN;
- INVALID and CRASH counts remain zero;
- no comparable CLEAN cell has larger area;
- at least one matrix-heavy cell has strictly smaller area;
- every returned build has the exact spec physical-machine and Matrix Lab counts;
- every emitted column is within that row's `lab_stack_limit` and passes all stack/support/flow checks;
- the `graphene` control retains zero Matrix Labs, zero ground lab columns, and unchanged non-lab structural behavior.

A newly clean former refusal is a benefit but does not compensate for a
regression above. If solver search variance produces an area increase, rerun
three identical rounds and compare medians; do not relax the gate after seeing
results.

- [ ] **Step 3: Update user and rule documentation**

Document in `docs/WEB_UI.md` that Matrix Labs use the URL's Vertical
Construction level, machine counts remain physical labs, and only ground labs
need belt/sorter access. Update `dsp/registry.py` so the lab height rule names
`BuildSpec.lab_stack_limit`, stack-aware variant planning, audit enrichment, and
validator consumption.

- [ ] **Step 4: Run final verification**

```bash
uv run pytest -q
uv run ruff check
uv run mypy
bun test
bun run typecheck
```

Smoke the actual exact pipeline path on the `information-matrix` corpus URL with
`strategy="best"`, decode the returned blueprint, and print: chosen
candidate/strategy, report status, area, belt tiles, physical lab count, ground
lab columns, column heights, and maximum allowed height. This runtime
scenario—not a mocked test—is the completion proof.

- [ ] **Step 5: Request independent review and commit closeout**

Request a reviewer to inspect the entire branch for stack-record legality,
sorter aggregation, validation soundness, both-strategy parity, audit schema
parity, and benchmark gate compliance. Fix all Critical and Important findings,
rerun the affected focused tests, then rerun the final verification above.

```bash
git add docs/superpowers/evidence/2026-09-04-matrix-lab-stacking \
  docs/WEB_UI.md src/flab2bp/dsp/registry.py
git commit -m "docs: record matrix lab stacking gate"
```
