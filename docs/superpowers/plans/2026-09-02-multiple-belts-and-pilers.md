# Multiple Belts and Automatic Pilers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a build carry a flow above the fastest belt, first by splitting it across parallel lanes (Deliverable A), then by planning and validating stacked cargo where FactorioLab's URL stacks belts (Deliverable B), and finally by placing Automatic Pilers where a merge would otherwise overflow a belt (Deliverable C), so that the deuteron-fuel-rod URL with hydrogen belted in at 40 items/s builds and validates clean.

**Architecture:** Three deliverables, each ending in its own corpus gate. A adds one number to `StripFamily` (`machine_cap`) and applies it at the single partition seam `partition_strip_variant`, so both strategies and every strip-length heuristic are bounded without knowing it. B makes the stack a planned and validated quantity: `BuildSpec` learns the URL's stack and the save's Pile Sorter Upgrade level (pinned from the game files in Task 6), `LogicalLane` carries a stack, the planner's capacity checks divide by it, and the validator derives `stack_of(run)` from what was built and judges items ÷ stack against belt speed. C adds a pure merge-tree planner (`layout/piling.py`) that decides, per item and bottom-up under the merge rule, how many pilers each tributary needs before a junction — a piler DOUBLES, so reaching stack 4 from an unstacked lane takes two in series; the strip reserves a tail extension of three tiles per piler, `junction.make_piler` emits each one (no parameters: a piler carries no stack setting), and the validator gains the piler kind and checks, deriving the stack after a piler rather than reading it.

**Tech Stack:** Python 3.14, pydantic models in `spec.py`, frozen dataclasses in `layout/`, the validator's `Context`/`check` registry in `layout/validate.py`, exact `Fraction` rates everywhere, pytest (serial), Ruff, strict MyPy, `uv run`; the BepInEx oracle plugin under `tools/dsp-oracle/` (C#) for game facts.

**Spec:** `docs/superpowers/specs/2026-09-02-multiple-belts-and-pilers-design.md` (revision 3). Section numbers below refer to it.

## Status (2026-09-03)

- **Deliverable A is merged** at `3a10f21` on 2026-09-03. Tasks 1 to 5 are executed; do not re-plan them.
- **Task 6 is executed** on the no-game path (**Ruling P11**): the stacking facts were read out of the shipped game files (an ilspycmd decompile of `Assembly-CSharp.dll` plus a UnityPy typetree dump of `resources.assets`, game version 0.10.34) instead of a live BepInEx capture, and landed at `8c6f4b1` on branch `multibelt` as `src/flab2bp/dsp/data/stacking.json`, the `catalog` loaders, and the pins in `tests/dsp/test_catalog.py`. Task 6's steps below are kept as the record of what was asked for; the shipped shape is the JSON in the repo, not the sample in Step 2.
- **Tasks 7 to 15 were amended on 2026-09-03 (Ruling P12)** to the facts Task 6 pinned, together with spec revision 3. Four facts changed the work rather than merely confirming it, and each amended task names the one it follows:
  1. `Sorter Cargo Stacking` (techs 3301-3305, `sorter-cargo-stacking-{n}`) is obsolete and unreachable. The live ladder is `Pile Sorter Upgrade` (3311-3316, `pile-sorter-{n}`, six levels), and only the Pile Sorter (2014) carries a stack: Mk.I/II/III pick and place 1 at every level.
  2. `SORTER_STACK_RATE_FACTOR` is true: a carried stack of `n` moves `n` items per trip.
  3. The Automatic Piler has NO per-building stack setting (`PILER_STACK_PARAMETER is None`) and is NOT single pass (`PILER_SINGLE_PASS is False`): it doubles, capped at `PILER_MAX_STACK == 4`, so an unstacked lane needs two pilers in series to reach 4.
  4. `PILER_THROUGHPUT * beltSpeed == BELT_RATE`, so a piler never throttles its belt and the throughput bound is deleted, not merely defaulted.

## Global Constraints

- **Base: master `60ab5f8`** (2026-09-03; Phases B, C and D of the reliability program, the belt-and-sorter-tier work and the rates commit `98dfa5d` are all merged). Phase C and D edited `freeform.py` extensively (`FreeformLayout.lay_out`, `_sweep`, `_pack`) and `sequence_solver.py`; this plan's hunks in those files are small and elsewhere (`plan_strips`, `_box`, `Strip`). Every gate baseline is generated fresh at this base. Phase E (`docs/superpowers/specs/2026-09-03-phase-e-universe-matrix-closure-design.md`) runs concurrently in another worktree and edits `strip_variants._logical_strip_plans` (the `input_items` order and `_seat_inputs`), `NoValidLayout` (an additive `stats` keyword) and `audit.Result` (an additive `stats` field); Task 8's hunks in `_logical_strip_plans` are the one likely merge conflict and are merged by hand, never blind.
- **The cap has two seams** (§4.1): `partition_strip_variant` and `sequence_pair.merge_strip_instances` (the stage-boundary merge that sums two instances' machine counts after partitioning). Task 2 covers both.
- **Deliverables are gates, not milestones.** A ships alone if B's game facts cannot be pinned (Task 6 says how to stop). C does not start until Task 11's fixture exists. Each deliverable's last task runs the three-round corpus audit against the previous deliverable's rounds.
- **The partition cap lives in `partition_strip_variant`** (§4.1). The sequence solver reaches it through `partition_strip_family` (`sequence_solver.py::_variant_search_inputs`), freeform through `plan_strips`; a cap in either caller misses the other.
- **mypy covers `tests/` too** (`pyproject.toml` `files = ["src", "tests"]`): every test function and helper in this plan is annotated (`-> None`, typed parameters, no bare lambdas assigned to names).
- **No behaviour change for a URL with `ist=1`** beyond A's cap, and A's cap binds only where a lane would already have been refused (§4.3). The gate's `--regressions-only` compare is the proof; a `CLEAN -> REFUSED` flip is a defect, not noise.
- **The validator judges, the planner plans.** Every planned stack is re-derived by `Context.stack_of` from the built placement (§5.5). Nothing reads a `LogicalLane.stack` inside `validate.py`.
- **Stacks are the minimum over a run's contributors** (§5.5). No `flow.stack_mixed` error; mixing is judged conservatively, not refused.
- Every `file:line` below was read at master `54614e8` and is a hint only; re-validated at `60ab5f8` on 2026-09-03: exact in `validate.py`, `spec.py`, `strip_variants.py`, `url.py`, `solve.py`, `catalog.py` (±1); drifted by +21..+361 in `freeform.py`, +475..+500 in `sequence_solver.py`, +330 in `tests/test_pipeline.py`, +693 in `tests/layout/test_freeform.py`. Deliverable A's merge moved `strip_variants.py` by +4..+45 (`LogicalLane` `:183 -> :187`, `input_lane_fits` `:978 -> :986`, the `_merge_lanes` call `:1095 -> :1099`, `generate_strip_families` `:1423 -> :1464`, `partition_strip_variant` `:1589 -> :1634`) and `spec.py` by +6 (`planning_stack` now at `:247`); `freeform.py` and `validate.py` are unchanged. The mypy baseline at `60ab5f8` is 184 errors in 16 files. Resolve each target by symbol name with Serena `find_symbol` before editing, and enumerate call sites with Serena `find_referencing_symbols`, never with grep alone; grep only for strings, data files, and the QUOTED name of any function whose signature you change (string-named `monkeypatch.setattr` sites are invisible to Serena and LSP).
- **Symbol-tool activation (every implementer and reviewer, first thing):** `ToolSearch("select:mcp__serena__activate_project,mcp__serena__initial_instructions,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,LSP")`, then `mcp__serena__activate_project` with the absolute path of the worktree being edited, then `mcp__serena__initial_instructions`. If Serena errors, use the `LSP` tool; if both fail, stop and report NEEDS_CONTEXT; never grep for symbols.
- `PlacementStats` (`src/flab2bp/layout/base.py:198`) is a `TypedDict(total=False)` with alphabetically ordered keys; the task that first writes a stat declares it and lists `base.py` in its Files.
- Magic-constant lint R1 (`tests/rules/test_rule_registry.py`) applies to new numeric literals under `src/`; name constants at module level with a comment; add a `LintException` in `src/flab2bp/dsp/registry.py` only for a genuine coincidence.
- Each task is a separate commit that leaves the tree green: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` (no new diagnostic against the locked baseline; record the count at the worktree's base in the first task's report and hold it). Never `-n auto`.
- `git diff` needs `--no-ext-diff`. Commit messages: imperative, sentence case, no trailing period. Every `git add` below names explicit paths (never `git add -A` on its own), and every commit message body ends with the two trailer lines, which the one-line `-m` forms in each task stand in for:

```
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv
```
- The dev box is never idle and its load is disk I/O, not CPU; timing steps run without waiting and record `uptime` plus `vmstat 1 3`.
- Evidence under `docs/superpowers/evidence/<date>-multiple-belts/`, `<date>-stacked-lanes/`, `<date>-pilers/`. The `.superpowers/sdd/` workspace holds briefs and reports.
- Corpus gate (A, B, C): `uv run python scripts/audit.py --budget 30 --jobs 16 --json <round-file>`, both strategies, three rounds, compared with `scripts/audit_compare.py --regressions-only --expect-cells 72 --p95-seconds 31` against the previous rounds. A must not cost a clean cell; B and C must not cost a clean cell and must not change any cell whose URL has `ist=1` (compare in default mode on those cells: area ratio within noise).
- Known test facts: `tests/test_pipeline.py::test_without_planetary_logistics_the_same_url_is_refused` pins the refusal A REMOVES (Task 4 rewrites it); `tests/layout/test_strip_variants.py:1343 test_repeated_stage_boundary_splits_conserve_every_machine_and_lane` merges instances past the default cap of 6 (Task 2 uncaps its family); `tests/layout/test_freeform.py:361 test_lay_out_threads_one_strip_families_tuple_through_every_planner_call` pins that `generate_strip_families` is called once, so no task may add a second call; `tests/dsp/test_catalog.py:861` pins `BELT_RATE` against the dataset and must not change; the two slow deuteron tests carry pytest-timeout budget comments and any new slow test budgets the same way.
- A step whose measurement misses its stated goal is not committed as if it passed: record the numbers and report.

---

## Deliverable A: parallel belts

### Task 1: `machine_cap` and `planning_stack`

**Files:**
- Modify: `src/flab2bp/spec.py` — `BuildSpec` gains `planning_stack(item)` after `lane_capacity` (`:241`)
- Modify: `src/flab2bp/layout/strip_variants.py` — `StripFamily` (`:441`) gains `machine_cap`; new `_machine_cap`; `generate_strip_families` (`:1423`) computes it
- Test: `tests/test_spec.py`, `tests/layout/test_strip_variants.py`

**Interfaces:**
- Consumes: `freeform._adapt(spec) -> dict[str, _Group]` (imported lazily inside `strip_variants._logical_strip_plans` at `:898-907`; `_Group.inputs` / `.outputs` are per-machine `Fraction` rates), `BuildSpec.lane_capacity` (`spec.py:241`), `base.NoValidLayout` (`base.py:421`; resolve its constructor signature with Serena before use).
- Produces: `BuildSpec.planning_stack(item: str) -> int` (returns 1 until Task 8); `StripFamily.machine_cap: int = 0` (0 means uncapped, the value every hand-built family in the tests gets); `strip_variants._machine_cap(group, spec) -> int`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_spec.py`:

```python
def test_planning_stack_is_one_for_every_item_until_stacked_lanes_land() -> None:
    spec = BuildSpec(groups=(), belt_item_id="conveyor-belt-3", belt_items_per_second=Fraction(30))
    assert spec.planning_stack("hydrogen") == 1
```

Add to `tests/layout/test_strip_variants.py` (reuse the module's `_single_machine_spec` helper; find it with Serena and check how it sets `inputs_per_machine`):

```python
def _rated_spec(rate: Fraction, *, count: int = 8, capacity: Fraction = Fraction(30)) -> BuildSpec:
    """One collider-like group drawing ``rate`` of hydrogen per machine."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=count,
                inputs_per_machine={"hydrogen": rate},
                outputs_per_machine={"deuterium": Fraction(1, 2)},
            ),
        ),
        external_inputs={"hydrogen": rate * count},
        outputs={"deuterium": Fraction(count, 2)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=capacity,
    )


def test_machine_cap_is_the_floor_of_capacity_over_the_largest_single_item_rate() -> None:
    (family,) = generate_strip_families(_rated_spec(Fraction(4)))
    assert family.machine_cap == 7  # floor(30 / 4)


def test_machine_cap_uses_the_fastest_allowed_belt() -> None:
    (family,) = generate_strip_families(_rated_spec(Fraction(4), capacity=Fraction(12)))
    assert family.machine_cap == 3  # floor(12 / 4)


def test_machine_cap_is_at_least_one_and_a_literal_family_defaults_to_uncapped() -> None:
    (family,) = generate_strip_families(_rated_spec(Fraction(29)))
    assert family.machine_cap == 1
    # `_family(...)` goes through `generate_strip_families`, so it is always
    # capped (the module's default spec gives 6 at 6/s and 1 per machine);
    # only a literal `StripFamily(...)` keeps the 0 default.
    generated = _family(_single_machine_spec("assembling-machine-1", count=3))
    assert generated.machine_cap == 6
    assert replace(generated, machine_cap=0).machine_cap == 0


def test_a_single_machine_over_the_ceiling_is_refused_early_with_the_rate() -> None:
    with pytest.raises(NoValidLayout, match=r"31.*hydrogen.*30"):
        generate_strip_families(_rated_spec(Fraction(31)))
```

`miniature-particle-collider` is the catalog id (`particle-collider` is not one; re-validated 2026-09-03). Add `MachineGroup` to the module's `from flab2bp.spec import ...` line (`:44`) if it is not already there, or build the group through the module's `_group` helper. Import `NoValidLayout` from `flab2bp.layout.base`; its constructor is `NoValidLayout(reason, *, spec_label, budget_s, attempt_reasons, attempt_failures, projection_failures)` (`base.py:440-451`), and it prepends its own preamble to `reason`, so the regex above matches the numbers in the order the message emits them.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_spec.py tests/layout/test_strip_variants.py -q -k "planning_stack or machine_cap or refused_early"`
Expected: FAIL — `AttributeError: 'BuildSpec' object has no attribute 'planning_stack'`; `AttributeError: 'StripFamily' object has no attribute 'machine_cap'`; the refusal test passes without raising (DID NOT RAISE).

- [ ] **Step 3: Add `planning_stack` to `BuildSpec`**

After `lane_capacity` in `src/flab2bp/spec.py`:

```python
    def planning_stack(self, item: str) -> int:
        """The cargo stack the planner may assume for a lane of ``item``.

        Always 1 until stack-aware lanes land (the multiple-belts design,
        section 5.3): a lane is planned at one item per cargo unit, so the
        effective lane capacity is ``lane_capacity`` itself.
        """
        del item
        return 1
```

- [ ] **Step 4: Add `machine_cap` to `StripFamily` and compute it**

In `src/flab2bp/layout/strip_variants.py`, on `StripFamily` after `flank_outputs: bool = False`:

```python
    #: Machines per strip so that no lane this family owns exceeds the
    #: effective lane capacity (multiple-belts design, section 4.1).  0 means
    #: uncapped, which is what every hand-built family gets; the planner's
    #: `generate_strip_families` always sets a positive value.
    machine_cap: int = 0
```

Add the helper before `generate_strip_families` (the `_Group` import goes under `TYPE_CHECKING` from `flab2bp.layout.freeform`, matching how the module already avoids the circular import at runtime):

```python
def _machine_cap(group: _Group, spec: BuildSpec) -> int:
    """Machines per strip so no single-item lane exceeds its effective capacity.

    A strip's input lane for item X carries ``count * inputs[X]`` and its
    output lanes for item Y carry at most ``count * outputs[Y]``, so the cap
    is the floor of capacity over the largest per-machine single-item rate.
    A machine whose one rate exceeds the capacity cannot be served by any
    strip length; that is refused here, early and with the numbers, instead
    of late by ``flow.belt_capacity``.
    """
    cap: int | None = None
    for item, rate in (*group.inputs.items(), *group.outputs.items()):
        capacity = spec.lane_capacity * spec.planning_stack(item)
        if rate > capacity:
            raise NoValidLayout(
                f"recipe {group.recipe_id!r}: one machine moves {rate} items/s of "
                f"{item!r}, over the {capacity}/s the fastest belt this save can build "
                f"sustains ({spec.belt_tiers[-1].item_id}); no strip length can carry it",
                spec_label=spec.label,
                budget_s=0.0,
                attempt_reasons=(),
                attempt_failures=(),
                projection_failures=(),
            )
        fits = int(capacity // rate)
        cap = fits if cap is None else min(cap, fits)
    return max(1, cap) if cap is not None else 0
```

In `generate_strip_families`, before the loop, `groups = _adapt(spec)` (the same lazy `from flab2bp.layout.freeform import ...` that `_logical_strip_plans` does at `:898-907`, so the circular import stays runtime-only), and inside the loop compute `machine_cap=_machine_cap(groups[plan.group_key], spec)` and pass it to the `StripFamily(...)` constructor. Check the keyword names of `NoValidLayout`'s constructor with Serena before committing to the call above; if `lay_out`'s other refusals build the exception through a helper, use it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_spec.py tests/layout/test_strip_variants.py -q`
Expected: PASS, including every pre-existing test (the new field has a default).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/spec.py src/flab2bp/layout/strip_variants.py tests/test_spec.py tests/layout/test_strip_variants.py
uv run mypy src/flab2bp/spec.py src/flab2bp/layout/strip_variants.py
uv run pytest tests/rules -q
git add src/flab2bp/spec.py src/flab2bp/layout/strip_variants.py tests/test_spec.py tests/layout/test_strip_variants.py
git commit -m "feat(layout): cap machines per strip by the effective lane capacity"
```

### Task 2: Apply the cap at the partition seam

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py` — `partition_strip_variant` (`:1589`)
- Modify: `src/flab2bp/layout/strip_variants.py` — `merge_strip_instances` (`:1712-1737`, exported at `:1783`; called lazily from `sequence_pair.merge_stage_boundary` at `sequence_pair.py:1869`)
- Modify: `src/flab2bp/layout/freeform.py` — the no-variant fallback in `plan_strips` (`:2157-2160`)
- Test: `tests/layout/test_strip_variants.py`, `tests/layout/test_sequence_pair.py`, `tests/layout/test_freeform.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `StripFamily.machine_cap` (Task 1); `partition_strip_family` (`:1628`) delegates unchanged; the sequence solver's three heuristics `_dense_spray_initial_strip_len` (`sequence_solver.py:269`), `_moderate_routed_initial_strip_len` (`:284`), `_mid_unsprayed_initial_strip_len` (`:306`).
- Produces: `partition_strip_variant` honours `min(max_machine_count, family.machine_cap)` when the cap is positive; `plan_strips`' fallback branch does the same.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_strip_variants.py`:

```python
def test_partition_never_exceeds_the_family_machine_cap() -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=7)), machine_cap=2)
    instances = partition_strip_family(family, max_machine_count=6)
    assert [instance.machine_count for instance in instances] == [2, 2, 2, 1]
    validate_instance_partition(family, instances)


def test_a_zero_cap_leaves_the_requested_length_alone() -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=7)), machine_cap=0)
    instances = partition_strip_family(family, max_machine_count=6)
    assert [instance.machine_count for instance in instances] == [4, 3]


def test_a_stage_boundary_merge_refuses_to_exceed_the_cap() -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=6)), machine_cap=4)
    left, right = partition_strip_family(family, max_machine_count=3)
    assert merge_strip_instances(family, left, right) is None  # 3 + 3 > 4
    uncapped = replace(family, machine_cap=0)
    left, right = partition_strip_family(uncapped, max_machine_count=3)
    assert merge_strip_instances(uncapped, left, right) is not None


@pytest.mark.parametrize("requested", [1, 3, 12, 40])
def test_every_strip_length_heuristic_survives_the_cap(requested: int) -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=9)), machine_cap=3)
    instances = partition_strip_family(family, max_machine_count=requested)
    assert max(instance.machine_count for instance in instances) <= 3
    assert sum(instance.machine_count for instance in instances) == 9
```

Add to `tests/layout/test_freeform.py`, beside `test_shared_lane_capacity_is_judged_against_the_fastest_allowed_belt` (`:16629`), using Task 1's `_rated_spec` shape (copy the helper; the two test modules do not share helpers):

```python
def test_plan_strips_shortens_strips_to_the_capacity_cap() -> None:
    spec = _rated_spec(Fraction(4), count=8)
    strips = plan_strips(spec, strip_len=8)
    assert max(strip.machines for strip in strips) <= 7
    assert sum(strip.machines for strip in strips) == 8
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_strip_variants.py tests/layout/test_freeform.py -q -k "machine_cap or heuristic_survives or shortens_strips"`
Expected: FAIL — partitions of `[4, 3]` / one 8-machine strip where the cap demands shorter ones.

- [ ] **Step 3: Apply the cap at both seams**

In `partition_strip_variant`, immediately after the `max_machine_count <= 0` check:

```python
    if family.machine_cap > 0:
        max_machine_count = min(max_machine_count, family.machine_cap)
```

In `strip_variants.merge_strip_instances(family, left, right) -> StripInstance | None` (`:1712-1737`; `merge_stage_boundary` treats `None` as "no merge"): before building the merged instance, `return None` when `family.machine_cap > 0 and left.machine_count + right.machine_count > family.machine_cap`. `merge_strip_instances` is already imported in `tests/layout/test_strip_variants.py:33`.

KNOWN BREAKAGE TO FIX IN THIS STEP: `tests/layout/test_strip_variants.py:1343 test_repeated_stage_boundary_splits_conserve_every_machine_and_lane` is parametrised over `machine_count in range(1, 13)` and merges instances back to the full count asserting `merged is not None`; its family comes from `_family(_single_machine_spec(...))`, whose default spec caps at 6 (`belt_items_per_second=Fraction(6)`, 1 item/s per machine), so parameters 7-12 would now refuse. Rebuild that test's family with `replace(family, machine_cap=0)` (the test is about conservation, not capacity) and add a one-line comment saying so.

In `plan_strips`' fallback branch (`freeform.py:2157-2160`), replace `max(1, strip_len)` with:

```python
            capped_len = max(1, strip_len)
            if family.machine_cap > 0:
                capped_len = min(capped_len, family.machine_cap)
            instance_count = max(1, math.ceil(family.total_machine_count / capped_len))
```

- [ ] **Step 4: Run the tests to verify they pass, then the planner suites**

Run: `uv run pytest tests/layout/test_strip_variants.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/layout/test_sequence_pair.py -q`
Expected: PASS. `test_lay_out_threads_one_strip_families_tuple_through_every_planner_call` (`test_freeform.py:361`) must still pass: no second `generate_strip_families` call was added.

- [ ] **Step 5: Both Phase B route digests still match**

The router is untouched; confirm:

```bash
d=docs/superpowers/evidence/2026-09-02-phase-b-last-mile
uv run python scripts/route_bench.py --cases $d/route-cases-universe-matrix-output-products.pkl --check --rounds 1
uv run python scripts/route_bench.py --cases $d/route-cases-quantum-chip-all-products.pkl --check --rounds 1
```

Expected: both `MATCH`. (These replay captured low-level searches; they prove the router is unchanged, nothing about strips.)

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
git commit -m "feat(layout): bound every strip partition by the family machine cap"
```

### Task 3: Report how many entry lanes an item needs

**Files:**
- Modify: `src/flab2bp/layout/validate.py` — `_external_entry_points` (`:4237`)
- Modify: `src/flab2bp/cli.py` — after the `belts:` line (`:94-115`)
- Modify: `src/flab2bp/web/payload.py` — `_belt_tiers` (`:76`)
- Test: `tests/layout/test_validate.py`, `tests/web/test_payload.py` (find the `_belt_tiers` test with Serena)
- Create: `tests/test_cli.py` — there is no CLI test module today and nothing pins the `belts:` report block (`tests/test_pipeline_cli_strategy.py` covers strategy selection only); this task creates the module with the `entry lanes:` test in the style of the strategy tests' fake-build fixtures

**Interfaces:**
- Consumes: `_entry_runs(ctx)` (`validate.py:4084`), `ctx.spec.external_inputs`, `ctx.spec.lane_capacity`, `ctx.spec.planning_stack`.
- Produces: `flow.external_entry_points` detail gains `"lanes_needed": int` and `"capacity": str`; the CLI prints `  entry lanes: hydrogen 2 (needs 2 at 30/s)` per multi-lane item; the web payload's belt-tier block gains `"entry_lanes": [{"item", "lanes", "lanes_needed"}]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_validate.py` beside `test_flow_external_entry_points_warns_on_several_lanes_for_one_item` (`:4023`); read that test's placement builder and reuse it with a spec whose `external_inputs` for the item is 40 and `belt_item_id="conveyor-belt-3"`:

```python
def test_flow_external_entry_points_says_how_many_lanes_the_rate_needs() -> None:
    p, spec = _two_entry_lanes(external=Fraction(40), capacity=Fraction(30))
    (finding,) = validate(p, spec, ids=TWO_INPUT_IDS).by_check("flow.external_entry_points")
    assert finding.detail["entry_lanes"] == 2
    assert finding.detail["lanes_needed"] == 2
    assert "needs 2 lanes of 30/s" in finding.message


def test_flow_external_entry_points_keeps_the_old_wording_when_lanes_exceed_the_need() -> None:
    p, spec = _two_entry_lanes(external=Fraction(10), capacity=Fraction(30))
    (finding,) = validate(p, spec, ids=TWO_INPUT_IDS).by_check("flow.external_entry_points")
    assert finding.detail["lanes_needed"] == 1
    assert "the player must connect a supply to every one of them" in finding.message
```

`_two_entry_lanes` is a small helper you write from the existing test's placement, returning `(placement, spec)`. The CLI and payload tests assert the new line / key on a fake build carrying such a finding, in the same style as the existing `belts:` tests.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_validate.py -q -k external_entry_points`
Expected: FAIL — `KeyError: 'lanes_needed'`.

- [ ] **Step 3: Implement**

In `_external_entry_points`, before the loop, compute the per-item need; inside, choose the message:

```python
    spec = ctx.spec
    for item, runs in sorted(_entry_runs(ctx).items()):
        if len(runs) < 2:
            continue
        capacity = spec.lane_capacity * spec.planning_stack(item)
        demand = spec.external_inputs.get(item, Fraction(0))
        lanes_needed = max(1, -(-demand // capacity)) if demand > 0 else 1
        heads = [bs[ctx.runs[r].head] for r in runs]
        where = ", ".join(f"({b.x},{b.y})" for b in heads[:6])
        if len(runs) == lanes_needed:
            message = (
                f"{item!r} is belted in at {len(runs)} separate lanes ({where}); "
                f"{demand} items/s needs {lanes_needed} lanes of {capacity}/s"
            )
        else:
            message = (
                f"{item!r} is belted in at {len(runs)} separate lanes ({where}); the "
                f"player must connect a supply to every one of them"
            )
        yield Finding(
            "flow.external_entry_points",
            Severity.WARNING,
            message,
            tuple(ctx.runs[r].head for r in runs),
            {
                "item": item,
                "entry_lanes": len(runs),
                "lanes_needed": int(lanes_needed),
                "capacity": str(capacity),
                "runs": sorted(runs),
            },
        )
```

(`-(-a // b)` is ceiling division on `Fraction`s; keep it exact, no float.) In `cli.py`, after the `belts:` block, iterate `build.report.by_check("flow.external_entry_points")` and print one `  entry lanes: {item} {entry_lanes} (needs {lanes_needed} at {capacity}/s)` line per finding. In `payload.py::_belt_tiers`, add `"entry_lanes": _array(sorted({...} per finding))` from the same findings (the function has the placement; take the report as a parameter and update its two callers: `payload.py:111` inside the per-attempt block, where `attempt.report` is in scope, and `payload.py:202`, where `build.report` is in scope).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_validate.py tests/test_cli.py tests/web -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/validate.py src/flab2bp/cli.py src/flab2bp/web/payload.py
uv run mypy src/flab2bp/layout/validate.py src/flab2bp/cli.py src/flab2bp/web/payload.py
git add src/flab2bp/layout/validate.py src/flab2bp/cli.py src/flab2bp/web/payload.py tests/layout/test_validate.py tests/test_cli.py tests/web
git commit -m "feat(validate): say how many entry lanes an external item needs"
```

### Task 4: The deuteron URL builds above the ceiling

**Files:**
- Modify: `tests/test_pipeline.py` — `test_without_planetary_logistics_the_same_url_is_refused` (`:717`) becomes a build; new test at Mk.III

**Interfaces:**
- Consumes: `DEUTERON_URL` (`test_pipeline.py:673`), `_with_belt` (`:680`), `pipeline.build`, `CandidatePolicy.NO_PROLIFERATOR`.

- [ ] **Step 1: Rewrite the refusal test and add the Mk.III test**

Replace `test_without_planetary_logistics_the_same_url_is_refused` with:

```python
@pytest.mark.slow
def test_without_planetary_logistics_hydrogen_arrives_on_four_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mk.II is the ceiling (12/s) and hydrogen enters at 40/s, so the cap
    shortens the collider strips until four entry lanes carry it.  Before the
    multiple-belts work this URL was refused with ``flow.belt_capacity``.

    Budget: 45 s on a sequence-pair build at ~30 s plus preparation keeps this
    under pytest-timeout's 120 s backstop even on a loaded box.
    """
    _with_belt(monkeypatch, "conveyor-belt-2", researched={
        "basic-logistics-system", "improved-logistics-system",
        "high-efficiency-logistics-system",
    })
    build = pipeline.build(DEUTERON_URL, strategy="sequence-pair", time_budget_s=45.0,
                           candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,))
    assert build.report.ok
    findings = build.report.by_check("flow.external_entry_points")
    # super-magnetic-ring is also belted in on two lanes (two assembler strips,
    # each wanting its own feed); only hydrogen is this test's subject.
    (finding,) = [f for f in findings if f.detail["item"] == "hydrogen"]
    assert finding.detail["entry_lanes"] == finding.detail["lanes_needed"] == 4


def test_at_mk3_hydrogen_above_the_ceiling_arrives_on_two_lanes() -> None:
    """Mk.III already fits 40/s hydrogen on two lanes through the ordinary
    ``strip_len`` heuristic (10 colliders split 5 + 5, 20/s each, and the cap
    of 7 is inert); this pins that the new ``lanes_needed`` detail agrees with
    the lanes actually built.  Fast (about 2 s at the default budget): not
    slow, no budget bump."""
    build = pipeline.build(DEUTERON_URL, strategy="sequence-pair",
                           candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,))
    assert build.report.ok
    findings = build.report.by_check("flow.external_entry_points")
    (finding,) = [f for f in findings if f.detail["item"] == "hydrogen"]
    assert finding.detail["entry_lanes"] == finding.detail["lanes_needed"] == 2
```

Extend `_with_belt` with an optional `researched` keyword that also patches `researched_technology_ids` (the old test shows how). If `DEUTERON_URL` does not belt hydrogen in at 40/s on this master (the recipe-pricing change should make it so), print `build.spec.external_inputs` and stop: the test premise is the spec's concrete case.

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_pipeline.py -q -k "four_lanes or two_lanes"`
Expected: PASS twice. If the Mk.II build refuses, read the refusal's check list. `flow.belt_capacity` means the cap did not bind: report the strip counts. `flow.sorter_capacity` means the cap cannot help: hydrogen at 4/s per collider needs a span-1 `sorter-3` (6/s; span 2 is only 3/s) and the Pile Sorter is not allowed in this scenario (today's Mk.II refusal at `60ab5f8` names both checks, measured 2026-09-03). That is a sorter-seating problem, not a belt problem: record it in the report with the placement's sorter spans and stop with DONE_WITH_CONCERNS; do not lower the assertions.

- [ ] **Step 3: Single-cell measurement**

```bash
uptime; vmstat 1 3
uv run python scripts/audit.py --budget 30 --jobs 4 --only universe-matrix --json /tmp/a-um.jsonl | tail -8
```

Record every cell's status/area/seconds in the report next to the newest committed baseline on master (the latest `docs/superpowers/evidence/*/baseline-budget30-round1.jsonl` or `candidate-budget30-round1.jsonl` whose commit is an ancestor of the worktree's base).

- [ ] **Step 4: Commit**

```bash
uv run ruff check tests/test_pipeline.py
git add tests/test_pipeline.py
git commit -m "test(pipeline): a flow above the ceiling arrives on several lanes"
```

### Task 5: Corpus gate for Deliverable A

**Files:**
- Create: `docs/superpowers/evidence/<date>-multiple-belts/baseline-budget30-round{1,2,3}.jsonl` — generated fresh from a `git archive 60ab5f8` extraction (copy the two compiled kernels `src/flab2bp/layout/_*.so` into it; give it a minimal `.git` holding a detached `HEAD` file with the full SHA so `_head_commit` stamps rows; run the archive's own `scripts/audit.py` with the worktree's `.venv/bin/python`, exactly as `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/gate-d1.md` describes). No committed baseline is reusable: every earlier evidence directory pre-dates this base.
- Create: `docs/superpowers/evidence/<date>-multiple-belts/candidate-budget30-round{1,2,3}.jsonl`, `compare-round{1,2,3}.txt`, `gate.md`

- [ ] **Step 1: Baseline and candidate rounds**

```bash
d=docs/superpowers/evidence/$(date +%F)-multiple-belts; mkdir -p $d
# $ARCHIVE is the git-archive extraction of 60ab5f8 described under Files; the candidate is a
# git-archive extraction of this task's HEAD prepared the same way, so no in-flight edit leaks in.
for r in 1 2 3; do
  uptime | tee -a $d/load.txt; vmstat 1 3 | tail -3 >> $d/load.txt
  .venv/bin/python $ARCHIVE/scripts/audit.py --budget 30 --jobs 16 --json $d/baseline-budget30-round$r.jsonl | tail -5
  uptime | tee -a $d/load.txt; vmstat 1 3 | tail -3 >> $d/load.txt
  .venv/bin/python $CANDIDATE/scripts/audit.py --budget 30 --jobs 16 --json $d/candidate-budget30-round$r.jsonl | tail -5
done
for r in 1 2 3; do
  uv run python scripts/audit_compare.py $d/baseline-budget30-round$r.jsonl $d/candidate-budget30-round$r.jsonl \
    --expect-cells 72 --p95-seconds 31 --regressions-only | tee $d/compare-round$r.txt
done
```

- [ ] **Step 2: Write `gate.md`**

Verdict (PASS iff no `REGRESSION:` and no INVALID/CRASH in any round and p95 within threshold), the per-round CLEAN/72, the list of cells whose strip count changed (diff `detail` strings or the audit's `strips` field if present), area ratios on unchanged cells, the load snapshots, and a **coarsening count**: the cells where `_coarsen_saturated_strip_plan` (`freeform.py:2323`) used to collapse a plan over `_COARSE_STRIP_THRESHOLD` (`freeform.py:2320`) strips and now cannot because the cap binds (instrument with a one-off log line during the run, or compare strip counts against the baseline's), per spec §10. A must not cost a clean cell; more clean cells are the expected direction.

- [ ] **Step 3: Full verification and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy
git add $d
git commit -m "evidence: corpus gate for capacity-bounded strips"
```

---

## Deliverable B: stack-aware lanes

### Task 6: Pin the stacking facts from the game

> **EXECUTED 2026-09-03 at `8c6f4b1` on `multibelt` (Ruling P11).** No live game capture was needed: the numbers came from the shipped files. The delivered `stacking.json` is richer than Step 2's sample and its shape differs (two ladders, one marked `obsolete_ladder`; a `pile_sorter` entry with per-level `pick_stack_by_level` / `place_stack_by_level`; `parameter_index: null`; `throughput_cargo_per_second` stored per unit `beltSpeed`). The catalog surface that actually shipped is `SORTER_STACKING_LEVELS`, `sorter_pick_stack`, `sorter_place_stack`, `SORTER_STACK_RATE_FACTOR`, `PILER_MAX_STACK`, `PILER_SINGLE_PASS`, `piler_output_stack`, `PILER_THROUGHPUT` and `PILER_STACK_PARAMETER`. Tasks 7 to 15 below are written against that surface; the steps in this task are kept unchanged as the record of the request.

**Files:**
- Modify: `tools/dsp-oracle/` — the BepInEx plugin's probe (find its entry point and existing dump commands with Serena; the C# files are indexed too)
- Create: `src/flab2bp/dsp/data/stacking.json`
- Modify: `src/flab2bp/dsp/catalog.py` — loaders after `LogisticsTiers` (`:498`)
- Test: `tests/dsp/test_catalog.py`

**Interfaces:**
- Produces: `stacking.json` with the schema below; `catalog.SORTER_STACKING_LEVELS: int`; `catalog.sorter_pick_stack(item_id: int, level: int) -> int`; `catalog.sorter_place_stack(item_id: int, level: int) -> int`; `catalog.SORTER_STACK_RATE_FACTOR: bool` (a sorter carrying a stack of n moves n items per trip); `catalog.PILER_MAX_STACK: int`; `catalog.PILER_SINGLE_PASS: bool` (one piler takes an unstacked belt straight to its setting); `catalog.PILER_THROUGHPUT: Fraction` (cargo per second one piler processes); `catalog.PILER_STACK_PARAMETER: int | None` (the parameter index, if the piler's stack is a per-building parameter). (Shipped values: `PILER_SINGLE_PASS is False` and `PILER_STACK_PARAMETER is None` — both glosses above turned out FALSE; see the EXECUTED banner and use `catalog.piler_output_stack` instead.)

**This task is a human-in-the-loop prerequisite.** If the numbers cannot be obtained, stop the deliverable here: commit nothing but the oracle change and the report, and record in the ledger that B waits for the export.

- [ ] **Step 1: Extend the oracle to dump the upgrade table**

In the plugin's probe, add a dump that writes, for every `TechProto` in `LDB.techs.dataArray` whose `Name` contains `Cargo Stacking` or `Pile Sorter`, the fields `ID, Name, Level, MaxLevel, UnlockFunctions, UnlockValues, UnlockRecipes, PropertyOverrideItems`, and for item 2040 every `PrefabDesc` field whose name contains `pile`, `stack` or `Stack` with its value, plus the `PilerComponent` (or the component the prefab attaches; discover it) default stack setting, which `BuildingParameters` slot serialises it, its processing throughput (the per-tick cargo intake, converted to cargo per second; if the component processes whatever the belt delivers with no cap of its own, record `throughput = belt speed` and say why), and whether it stacks an unstacked belt straight to its setting in one pass (read the component's update loop; do not assume). Also record, from the sorter component, whether a carried stack of `n` counts as `n` items per trip (the `SORTER_STACK_RATE_FACTOR` fact). Follow the plugin's existing dump conventions (output path, JSON writer). Do not guess field names in the plan's code: the implementer reads the decompiled `Assembly-CSharp` the plugin already builds against.

- [ ] **Step 2: Run the game with the plugin and capture the dump**

The user runs the game; the dump lands where the plugin writes. Transcribe into `src/flab2bp/dsp/data/stacking.json`:

```json
{
  "source": "dsp-oracle dump <date>, game version <version>",
  "sorter_cargo_stacking": {
    "levels": 5,
    "pick_stack_by_level": {"0": 1, "1": 2, "2": 3, "3": 4, "4": 4, "5": 4},
    "place_stack_by_level": {"0": 1, "1": 2, "2": 3, "3": 4, "4": 4, "5": 4},
    "applies_to": ["sorter-1", "sorter-2", "sorter-3"],
    "pile_sorter": {"pick_stack": 4, "place_stack": 4, "needs_research": false}
  },
  "sorter_stack_rate_factor": true,
  "piler": {"max_stack": 4, "single_pass": true, "throughput_cargo_per_second": "30",
            "parameter_index": 0, "parameter_values": {"1": 1, "2": 2, "3": 3, "4": 4}}
}
```

The values above are the SHAPE, not facts; every number is replaced by the dump's, and the report quotes the dump lines each one came from. If the game exposes stacking as a single global (not per tier), record `applies_to` accordingly.

- [ ] **Step 3: Loaders and pins**

In `catalog.py`, load the file next to the other data files and expose:

```python
def sorter_pick_stack(item_id: int, level: int) -> int:
    """Largest cargo stack a sorter of this tier picks off a belt at research ``level``."""

def sorter_place_stack(item_id: int, level: int) -> int:
    """Largest stack it places on a belt from a machine buffer at ``level``."""
```

with the Pile Sorter (`2014`) answering its own entry. Tests in `tests/dsp/test_catalog.py` pin every table entry as a literal and fail if the JSON changes.

- [ ] **Step 4: Commit**

```bash
git add tools/dsp-oracle src/flab2bp/dsp/data/stacking.json src/flab2bp/dsp/catalog.py tests/dsp/test_catalog.py
git commit -m "data(dsp): pin sorter cargo stacking and piler stack facts from the oracle"
```

### Task 7: The spec learns the stack

**Files:**
- Modify: `src/flab2bp/spec.py` — `BuildSpec` fields, validator, `max_stack`, `planning_stack`
- Modify: `src/flab2bp/dsp/catalog.py` — `LogisticsTiers` (`:498`) gains `piler`, `sorter_pick_stacks`, `sorter_place_stacks`
- Modify: `src/flab2bp/lab/techs.py` — `logistics_tiers_for_request` (`:66`)
- Modify: `src/flab2bp/rates/candidates.py` — `_to_build_spec` (`:146`)
- Modify: `src/flab2bp/rates/solve.py` — the two `ObjectiveUnit.Belts` branches (`:260`, `:301`)
- Test: `tests/test_spec.py`, `tests/lab/test_techs.py`, `tests/rates/test_candidates.py`, `tests/rates/test_solve.py`

**Interfaces:**
- Consumes: `LabRequest.stack` (`lab/url.py:207`, parsed at `:538`), `request.researched_technology_ids`, Task 6's catalog functions.
- Produces (spec §5.2): `BuildSpec.belt_stack: int = 1`, `sorter_pick_stacks: tuple[int, ...] = (1, 1, 1, 2)`, `sorter_place_stacks: tuple[int, ...] = (1, 1, 1, 1)`, `piler_unlocked: bool = False`, property `max_stack`, and `planning_stack(item)` still returning 1 (Task 8 gives it its rule).

**Facts this task follows (Ruling P12):** the live ladder is `pile-sorter-{n}`, six levels, and only the Pile Sorter carries a stack. The defaults above are the level-0 row of the pinned table (`catalog.sorter_pick_stack(2014, 0) == 2`, `catalog.sorter_place_stack(2014, 0) == 1`), NOT the `(1, 1, 1, 4)` of the pre-amendment plan, which corresponded to no real research level.

- [ ] **Step 1: Write the failing tests**

`tests/test_spec.py`:

```python
def test_belt_stack_defaults_to_one_and_is_capped_at_four() -> None:
    assert BuildSpec(groups=()).belt_stack == 1
    with pytest.raises(ValueError, match="belt_stack"):
        BuildSpec(groups=(), belt_stack=5)


def test_stack_tuples_align_with_sorter_tiers() -> None:
    with pytest.raises(ValueError, match="sorter_pick_stacks"):
        BuildSpec(groups=(), sorter_item_ids=("sorter-1",), sorter_pick_stacks=(1, 1))


def test_max_stack_is_four_with_the_piler_else_the_largest_place_stack() -> None:
    assert BuildSpec(groups=(), piler_unlocked=True).max_stack == 4
    assert BuildSpec(groups=(), sorter_place_stacks=(1, 1, 1, 4)).max_stack == 4
    assert BuildSpec(groups=(), sorter_item_ids=("sorter-1",), sorter_pick_stacks=(1,),
                     sorter_place_stacks=(2,)).max_stack == 2


def test_the_defaults_are_the_level_zero_row_of_the_pinned_table() -> None:
    # Only the Pile Sorter stacks, and unresearched it picks 2 and places 1.
    spec = BuildSpec(groups=())
    assert spec.sorter_pick_stacks == (1, 1, 1, 2)
    assert spec.sorter_place_stacks == (1, 1, 1, 1)
    assert spec.sorter_pick_stacks[-1] == catalog.sorter_pick_stack(2014, 0)
    assert spec.sorter_place_stacks[-1] == catalog.sorter_place_stack(2014, 0)
```

`tests/lab/test_techs.py` (beside the existing derivation tests), all against the `pile-sorter-{n}` ladder:

```python
def test_no_technology_set_means_everything_is_researched() -> None:
    tiers = logistics_tiers_for_request(_request(researched=None))
    assert tiers.piler is True
    assert tiers.sorter_pick_stacks == (1, 1, 1, 4)   # level 6
    assert tiers.sorter_place_stacks == (1, 1, 1, 4)


def test_without_the_integrated_logistics_system_nothing_stacks() -> None:
    # The same tech unlocks the Pile Sorter and the Automatic Piler, so this
    # save has neither: every tier it can build picks and places 1.
    tiers = logistics_tiers_for_request(_request(researched=frozenset({"conveyor-belt-3"})))
    assert tiers.piler is False
    assert "sorter-4" not in tiers.sorter_item_ids
    assert set(tiers.sorter_pick_stacks) == {1}
    assert set(tiers.sorter_place_stacks) == {1}


def test_the_level_is_the_highest_researched_pile_sorter_tech() -> None:
    researched = frozenset({"integrated-logistics-system", "pile-sorter-1", "pile-sorter-2"})
    tiers = logistics_tiers_for_request(_request(researched=researched))
    assert tiers.sorter_pick_stacks == (1, 1, 1, 3)   # level 2
    assert tiers.sorter_place_stacks == (1, 1, 1, 2)


def test_the_obsolete_cargo_stacking_ladder_is_ignored() -> None:
    """3301-3305 carry IsObsolete=1; researching them must move nothing."""
    researched = frozenset({"integrated-logistics-system"} |
                           {f"sorter-cargo-stacking-{n}" for n in range(1, 6)})
    tiers = logistics_tiers_for_request(_request(researched=researched))
    assert tiers.sorter_pick_stacks == (1, 1, 1, 2)   # level 0, unmoved
    assert tiers.sorter_place_stacks == (1, 1, 1, 1)
```

(`_request` is the module's existing request helper; use whatever it is named there, and drop `sorter-4` from the tier list in the second case only if the existing derivation already does so.)

`tests/rates/test_candidates.py`: a request with `stack=Fraction(2)` yields `spec.belt_stack == 2`; `stack=None` yields 1.

`tests/rates/test_solve.py`: an `Output` objective of `1 Belts` with `stack=2` on `conveyor-belt-3` yields 60 items/s (find the module's existing Belts-objective test and extend it).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_spec.py tests/lab/test_techs.py tests/rates -q -k "stack or piler"`
Expected: FAIL on unknown fields / attributes.

- [ ] **Step 3: Implement**

`spec.py` fields after `sorter_item_ids`:

```python
    #: FactorioLab's belt stack (``ist``): the cargo stack the player's bus
    #: carries.  1 when the URL says nothing.  Never above 4, the game's
    #: largest pile.
    belt_stack: int = Field(default=1, ge=1, le=4)
    #: Largest stack each sorter TIER can PICK off a belt and PLACE onto one,
    #: aligned with ``sorter_item_ids``.  Never per item: DSP decides a stack
    #: from the sorter's grade and the researched Pile Sorter Upgrade level.
    #: The defaults are that table's level-0 row -- Sorter Mk.I to Mk.III at 1
    #: forever, an unresearched Pile Sorter picking 2 and placing 1.  They only
    #: matter when ``belt_stack > 1``: every stack the planner and validator
    #: derive is 1 when the URL does not stack (design rule 1), so a hand-built
    #: spec behaves as today.
    sorter_pick_stacks: tuple[int, ...] = (1, 1, 1, 2)
    sorter_place_stacks: tuple[int, ...] = (1, 1, 1, 1)
    piler_unlocked: bool = False
```

Extend `_tiers_are_ordered` (or add `_stacks_align`) so both tuples have `len(sorter_item_ids)` entries in `1..4`, with a message naming the field. Properties:

```python
    @property
    def max_stack(self) -> int:
        """The largest stack any lane may be planned at: 4 with a piler, else what sorters place."""
        return 4 if self.piler_unlocked else max(self.sorter_place_stacks)
```

`catalog.LogisticsTiers` gains `piler: bool = False`, `sorter_pick_stacks: tuple[int, ...] = ()`, `sorter_place_stacks: tuple[int, ...] = ()` (defaults keep every constructor in the tests valid). In `logistics_tiers_for_request`, after `unlocked` is known:

```python
    piler = "automatic-piler" in unlocked
    # DSP 0.10.34 has two cargo-stacking ladders and only ONE is reachable.
    # `sorter-cargo-stacking-{n}` (techs 3301-3305) carries IsObsolete = 1, so
    # it is hidden from the tree and moves nothing; the live ladder is
    # `pile-sorter-{n}` (techs 3311-3316).  Reading the obsolete ids here would
    # grant stacks the game never grants.  See stacking.json.obsolete_ladder.
    level = (
        catalog.SORTER_STACKING_LEVELS
        if researched_ids is None
        else max(
            (n for n in range(1, catalog.SORTER_STACKING_LEVELS + 1)
             if f"pile-sorter-{n}" in researched_ids),
            default=0,
        )
    )
    pick = tuple(catalog.sorter_pick_stack(catalog.item_id(s), level) for s in sorter_item_ids)
    place = tuple(catalog.sorter_place_stack(catalog.item_id(s), level) for s in sorter_item_ids)
```

`piler_unlocked` stays exactly what it was, the Automatic Piler recipe unlock. The `pile-sorter-{n}` entries are `category: upgrades` with no `recipeUnlock` (verified in `src/flab2bp/lab/vendored/data.json`: each has only `technology.prerequisites`), so they are tested by id membership in `researched`, not through `unlocked`; `integrated-logistics-system` is the sole `recipeUnlock` for both `automatic-piler` and `sorter-4`, which is why a save without it has no stacking at all. `catalog.item_id` (`catalog.py:946`) is the non-optional resolver and keeps mypy quiet where `get_item_id` (`:959`) would return `int | None`; `sorter_item_ids` is always a subset of the known sorters, so it cannot raise. Note the tuples are as long as `sorter_item_ids`, which is SHORTER than four on a save without the Pile Sorter — no index may be hard-coded, only `[-1]` for the fastest tier.

`_to_build_spec`: `belt_stack=min(4, int(request.stack)) if request.stack and request.stack > 1 else 1`, the two tuples and `piler_unlocked` from `tiers`. `rates/solve.py`: both `Belts` branches multiply by `stack = int(request.stack) if request.stack and request.stack > 1 else 1`, capped at 4, with a comment citing the spec's rule 1.

- [ ] **Step 4: Run, lint, type-check, commit**

```bash
uv run pytest tests/test_spec.py tests/lab tests/rates -q
uv run ruff check src/flab2bp/spec.py src/flab2bp/dsp/catalog.py src/flab2bp/lab/techs.py src/flab2bp/rates/candidates.py src/flab2bp/rates/solve.py
uv run mypy src/flab2bp/spec.py src/flab2bp/dsp/catalog.py src/flab2bp/lab/techs.py src/flab2bp/rates
git add src/flab2bp/spec.py src/flab2bp/dsp/catalog.py src/flab2bp/lab/techs.py src/flab2bp/rates/candidates.py src/flab2bp/rates/solve.py tests/test_spec.py tests/lab/test_techs.py tests/rates
git commit -m "feat(spec): carry the URL's belt stack and the save's sorter stacking levels"
```

### Task 8: Lanes are planned at a stack

**Files:**
- Modify: `src/flab2bp/spec.py` — `planning_stack` gets its rule (§5.3)
- Modify: `src/flab2bp/layout/strip_variants.py` — `LogicalLane` (`:183`) gains `stack: int = 1`; `_logical_lanes` sets it; `input_lane_fits` (`:978`), the surplus-sharing test (`:940`), and the `_merge_lanes` capacity (`:1095`) divide by it
- Modify: `src/flab2bp/layout/freeform.py` — `_check_shared_lane_capacity` (`:1864`) divides by the lane's stack
- Test: `tests/test_spec.py`, `tests/layout/test_strip_variants.py`, `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `spec.belt_stack`, `sorter_pick_stacks`, `sorter_place_stacks`, `max_stack`, `piler_unlocked` (Task 7); `_pick_sorter` (`freeform.py:4403`) for the sorter tier a lane will use.
- Produces: `BuildSpec.planning_stack(item, *, external: bool | None = None) -> int`; `LogicalLane.stack`; the effective capacity `lane_capacity * stack` at every planner comparison.

- [ ] **Step 1: Write the failing tests**

`tests/test_spec.py`:

```python
# Every `pick`/`place` pair below is a real row of spec §5.1's table: Mk.I to
# Mk.III are 1 at every level and only the last entry (the Pile Sorter) moves.
#   level 0: pick (1,1,1,2) place (1,1,1,1)    level 4: pick (1,1,1,4) place (1,1,1,3)
#   level 1: pick (1,1,1,2) place (1,1,1,2)    level 5: pick (1,1,1,4) place (1,1,1,4)
#   level 2: pick (1,1,1,3) place (1,1,1,2)    level 6: pick (1,1,1,4) place (1,1,1,4)
#   level 3: pick (1,1,1,3) place (1,1,1,3)    no Pile Sorter: three-entry tuples of 1
# Do not invent rows like (2, 2, 2, 4): DSP grants no Mk.II a stack.
# `ids` must stay aligned with `pick`/`place`: Task 7's validator requires both
# tuples to have `len(sorter_item_ids)` entries, so a save without the Pile
# Sorter is expressed by passing THREE ids and three-entry tuples.
def _stacked(
    *,
    belt_stack: int = 1,
    pick: tuple[int, ...] = (1, 1, 1, 4),
    place: tuple[int, ...] = (1, 1, 1, 4),
    piler: bool = False,
    ids: tuple[str, ...] = ("sorter-1", "sorter-2", "sorter-3", "sorter-4"),
) -> BuildSpec:
    return BuildSpec(
        groups=(MachineGroup(recipe_id="deuterium", machine_item_id="miniature-particle-collider", count=1,
                             inputs_per_machine={"hydrogen": Fraction(4)},
                             outputs_per_machine={"deuterium": Fraction(1, 2)}),),
        external_inputs={"hydrogen": Fraction(4)}, outputs={"deuterium": Fraction(1, 2)},
        belt_item_id="conveyor-belt-3", belt_items_per_second=Fraction(30),
        sorter_item_ids=ids,
        belt_stack=belt_stack, sorter_pick_stacks=pick, sorter_place_stacks=place,
        piler_unlocked=piler,
    )


def test_planning_stack_is_one_when_the_url_does_not_stack() -> None:
    assert _stacked(pick=(1, 1, 1, 4), place=(1, 1, 1, 4)).planning_stack("hydrogen") == 1
    assert _stacked(pick=(1, 1, 1, 4), place=(1, 1, 1, 4)).planning_stack("deuterium") == 1


def test_an_external_input_is_planned_at_the_bus_stack() -> None:
    assert _stacked(belt_stack=2, pick=(1, 1, 1, 2), place=(1, 1, 1, 1)).planning_stack("hydrogen") == 2   # level 0
    assert _stacked(belt_stack=4, pick=(1, 1, 1, 4), place=(1, 1, 1, 3)).planning_stack("hydrogen") == 4   # level 4


def test_a_bus_without_a_pile_sorter_is_refused_not_capped() -> None:
    # Mk.I to Mk.III pick 1 at EVERY level, so any ist > 1 on such a save is a
    # refusal.  This is the whole of the "unpickable bus" class in practice.
    # THREE ids and three-entry tuples: `integrated-logistics-system` is the
    # sole unlock for sorter-4, so a save without it has no Pile Sorter tier at
    # all, and Task 7's validator requires the tuples to match the ids.
    spec = _stacked(belt_stack=2, pick=(1, 1, 1), place=(1, 1, 1),
                    ids=("sorter-1", "sorter-2", "sorter-3"))
    with pytest.raises(NoValidLayout, match=r"stack 2.*pick only 1.*Integrated Logistics System"):
        spec.planning_stack("hydrogen")


def test_a_bus_above_the_researched_pick_stack_is_refused() -> None:
    spec = _stacked(belt_stack=4, pick=(1, 1, 1, 3), place=(1, 1, 1, 2))   # level 2
    with pytest.raises(NoValidLayout, match=r"stack 4.*pick only 3.*Pile Sorter Upgrade"):
        spec.planning_stack("hydrogen")


def test_a_produced_item_is_planned_at_the_place_stack() -> None:
    assert _stacked(belt_stack=2, place=(1, 1, 1, 4), pick=(1, 1, 1, 4)).planning_stack("deuterium") == 4
    assert _stacked(belt_stack=2, place=(1, 1, 1, 2), pick=(1, 1, 1, 2)).planning_stack("deuterium") == 2
    assert _stacked(belt_stack=2, place=(1, 1, 1, 1), pick=(1, 1, 1, 2)).planning_stack("deuterium") == 1


def test_the_piler_raises_a_produced_lane_along_the_doubling_ladder() -> None:
    # A piler doubles, so the reachable targets are 1, 2 and 4 -- never 3 --
    # and piling is elective, so it stops at what the sink can pick.
    assert _stacked(belt_stack=2, piler=True, place=(1, 1, 1, 1), pick=(1, 1, 1, 2)).planning_stack("deuterium") == 2
    assert _stacked(belt_stack=2, piler=True, place=(1, 1, 1, 2), pick=(1, 1, 1, 3)).planning_stack("deuterium") == 2
    assert _stacked(belt_stack=2, piler=True, place=(1, 1, 1, 3), pick=(1, 1, 1, 4)).planning_stack("deuterium") == 4
    assert _stacked(belt_stack=2, piler=True, place=(1, 1, 1, 4), pick=(1, 1, 1, 4)).planning_stack("deuterium") == 4


def test_a_place_stack_the_consumer_cannot_pick_is_refused_not_capped() -> None:
    # Unreachable with the real table (pick >= place at every level), so this
    # guards hand-built specs; it must stay a refusal, because a sorter cannot
    # be told to place less.
    with pytest.raises(NoValidLayout, match=r"stack 4.*pick"):
        _stacked(belt_stack=2, place=(1, 1, 1, 4), pick=(1, 1, 1, 2)).planning_stack("deuterium")


def test_an_item_fed_from_the_bus_and_from_inside_is_planned_at_the_smaller_stack() -> None:
    # Level 4: the Pile Sorter picks 4 and places 3.  The bus arrives at 4, the
    # internal producer's sorter places 3, and a merge is judged at its minimum.
    spec = _stacked(belt_stack=4, place=(1, 1, 1, 3), pick=(1, 1, 1, 4))
    both_fed = spec.model_copy(update={"groups": (*spec.groups, MachineGroup(
        recipe_id="hydrogen-cracking", machine_item_id="oil-refinery", count=1,
        inputs_per_machine={"refined-oil": Fraction(1)},
        outputs_per_machine={"hydrogen": Fraction(3)},
    ))})
    assert both_fed.planning_stack("hydrogen") == 3
    assert spec.planning_stack("hydrogen") == 4
```

(`BuildSpec` is a pydantic model; if the module builds specs through a helper rather than `model_copy`, use that helper. `oil-refinery` must be a catalog machine id; if `_adapt` rejects the recipe, any two-group spec where one group's `outputs_per_machine` names the external item works.)

(`pick`/`place` index the four default sorter tiers; the last entry is the Pile Sorter.) `planning_stack` raising `NoValidLayout` from a spec method is deliberate: it is the plan-time refusal §5.3 requires, and `generate_strip_families` is its first caller.

`tests/layout/test_strip_variants.py`: `generate_strip_families` on a stacked spec yields lanes with `stack == 2` for hydrogen and `machine_cap == 15` (30 × 2 / 4); on an `ist=1` spec every lane has `stack == 1`. `tests/layout/test_freeform.py`: `_check_shared_lane_capacity` accepts a shared lane at 40 items/s when its stack is 2 and refuses it at stack 1 (extend `test_shared_lane_capacity_is_judged_against_the_fastest_allowed_belt` at `:16629` with a `stack` argument).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_spec.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py -q -k "planning_stack or stack"`
Expected: FAIL — `planning_stack` returns 1 everywhere; `LogicalLane` has no `stack`.

- [ ] **Step 3: Implement `planning_stack`**

```python
#: The stacks one or more Automatic Pilers in series can produce.  A piler
#: DOUBLES its input, capped at 4 (catalog.PILER_SINGLE_PASS is False), so 3 is
#: not reachable from an unstacked lane and must never be planned.
PILER_LADDER = (1, 2, 4)


    def planning_stack(self, item: str, *, external: bool | None = None) -> int:
        """The cargo stack the planner may assume for a lane of ``item`` (design 5.3).

        1 when the URL does not stack.  An external input arrives at the bus
        stack, whatever the consumer can do about it; a produced item leaves
        at what the fastest allowed sorter places.  Either is refused, never
        lowered, when the fastest allowed sorter cannot pick it: a lowered
        plan would still be fed the stacked belt and starve.  A produced lane
        may then be RAISED by pilers, but only along ``PILER_LADDER`` and only
        as far as the sink can pick, because piling is elective.  ``external``
        overrides the spec's own classification when the caller knows better
        (a boundary output lane is "produced").
        """
        if self.belt_stack == 1:
            return 1
        is_external = item in self.external_inputs if external is None else external
        pick = self.sorter_pick_stacks[-1]
        place = self.sorter_place_stacks[-1]
        if is_external:
            stack = self.belt_stack
            if any(item in group.outputs_per_machine for group in self.groups):
                # Fed from the bus AND from an internal producer (universe-matrix's
                # hydrogen is the corpus case): the lane also carries what the
                # producer's sorter places, and a merge is judged at its minimum
                # (design 5.5), so plan it at the smaller of the two stacks.
                stack = min(stack, place)
        else:
            stack = place
        if stack > pick:
            # Name research the player can actually reach.  `pile-sorter-1`'s
            # only prerequisite IS `integrated-logistics-system`, so telling a
            # save with no Pile Sorter to research the upgrade ladder is dead
            # advice; it needs the unlock first.
            missing = (
                "research Integrated Logistics System to unlock the Pile Sorter"
                if "sorter-4" not in self.sorter_item_ids
                else "research Pile Sorter Upgrade (the Sorter Cargo Stacking ladder is "
                     "obsolete and grants nothing)"
            )
            raise NoValidLayout(
                f"{self.label or 'spec'}: {item!r} travels at stack {stack} but the fastest "
                f"sorter this save can build ({self.sorter_item_ids[-1]}) can pick only "
                f"{pick}; {missing}, or lower the URL's belt stack",
                spec_label=self.label, budget_s=0.0, attempt_reasons=(),
                attempt_failures=(), projection_failures=(),
            )
        if not is_external and self.piler_unlocked:
            reachable = max(s for s in PILER_LADDER if s <= min(self.max_stack, pick))
            stack = max(stack, reachable)
        return stack
```

The pick and place values are the fastest allowed tier's (`sorter_item_ids[-1]`), the ceiling of what any tier can promise; with §5.1's tables that tier is the Pile Sorter whenever anything stacks at all, and every slower tier is 1. Note the ORDER: the refusal is raised on the unavoidable stack (the bus, or what the producer's sorter places) BEFORE any piler raise, so the piler raise can never trip it — that is the difference between an unavoidable stack and an elective one. `layout/base.py` imports only the standard library at runtime (`BuildSpec` is under `TYPE_CHECKING`), so `spec.py` may import `NoValidLayout` directly; no cycle. `PILER_LADDER` is a module-level named constant so magic-constant lint R1 is satisfied; `layout/piling.py` (Task 12) imports the same tuple rather than redefining it.

- [ ] **Step 3b: The sorter keeps the promise (spec §5.3)**

`_pick_sorter(rate, span, machines, tiers=...)` (`freeform.py:4403`) takes the CHEAPEST tier that carries the rate, so a low-rate producer lane planned at stack 4 would be built with a `sorter-1` placing 1 and the validator would then judge the lane at 1. Give `_pick_sorter` two keyword-only parameters, `min_place_stack: int = 1` and `min_pick_stack: int = 1`, and skip any tier whose `spec`-derived place/pick stack is below them (the three callers, `_flank_lane` `:5089`, `_link_lane` `:5354`, `_bridge` `:14940`, pass the lane's `LogicalLane.stack` as `min_place_stack` for a producer-side sorter and `min_pick_stack` for a consumer-side sorter; the canvas already carries `sorter_tiers`, add the two stack tuples beside it from the spec). With `belt_stack == 1` every lane's stack is 1 and the parameters are inert. Test: a 1 item/s producer lane at stack 4 under `ist=2` with `sorter_place_stacks=(1, 1, 1, 4)` picks the Pile Sorter; the same at stack 1 picks `sorter-1`. Grep the quoted string `"_pick_sorter"` in tests for monkeypatch sites before changing the signature.

- [ ] **Step 4: Lanes carry the stack; comparisons divide by it**

`LogicalLane` gains `stack: int = 1` after `side_index`, with `__post_init__` rejecting values outside `1..4`. `_logical_lanes(plan, ...)` sets `stack=spec.planning_stack(item, external=...)`: for input lanes the item is external iff it is in `spec.external_inputs`; for output lanes `external=False`. (`_logical_lanes` does not receive `spec` today; thread it from `generate_strip_families`, whose only production callers are listed in the research note; keep the signature keyword-only.) In `_logical_strip_plans`: the surplus-sharing test at `:940` and `input_lane_fits` at `:991` compare against `spec.lane_capacity * spec.planning_stack(item, external=...)`; `_merge_lanes` at `:1095` receives `spec.lane_capacity * spec.planning_stack(item, external=False)` per shard's item. `_check_shared_lane_capacity` takes the lane's stack from the family's `LogicalLane` (its callers in `plan_strips` at `:2172` have `inputs_above + inputs_below` as item tuples; map each tuple back to the lane via the family and pass `stack`).

- [ ] **Step 5: Run, lint, type-check, commit**

```bash
uv run pytest tests/test_spec.py tests/layout -q
uv run ruff check src/flab2bp/spec.py src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py
uv run mypy src/flab2bp/spec.py src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py
git add src/flab2bp/spec.py src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/test_spec.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
git commit -m "feat(layout): plan every lane at the stack its cargo carries"
```

### Task 9: The validator derives the stack from what was built

**Files:**
- Modify: `src/flab2bp/layout/validate.py` — `_Cache`, `Context.stack_of`, `_belt_capacity` (`:5073`), `_sorter_capacity` (`:5118`), new `flow.stack_pickable`, `_external_entry_points` (`:4237`)
- Test: `tests/layout/test_validate.py`

**Interfaces:**
- Consumes: `_run_demand` (`:5588`), `_entry_runs` (`:4084`), `Context.pred`/`succ`, `junction_in`/`junction_out`, `cat.sorter_pick_stack` / `sorter_place_stack`, `ctx.spec.belt_stack`, `sorter_item_ids`.
- Produces: `Context.stack_of(run: int) -> int`; `flow.belt_capacity` compares `required <= capacity * stack`; `flow.stack_pickable` (ERROR); `flow.sorter_capacity` multiplies the sorter's capacity by its place/pick stack; `_external_entry_points` counts lanes at the effective capacity.

- [ ] **Step 1: Write the failing tests**

Using the module's `place`, `belt`, `machine`, `sorter`, `splitter`, `fired`, `hungry_spec` helpers (`hungry_spec` builds a Mk.II spec; add a `_stacked_spec(rate, *, belt_stack, pick, place)` helper on Mk.III):

```python
def test_flow_belt_capacity_passes_a_stacked_entry_run() -> None:
    # entry belt at the URL's stack 2: 40 items/s is 20 cargo/s on a 30/s belt
    r = validate(fed_machine(item_id=2003), _stacked_spec(Fraction(40), belt_stack=2, pick=2), ids=TWO_INPUT_IDS)
    assert not fired(r, "flow.belt_capacity")


def test_flow_belt_capacity_refuses_the_same_run_at_stack_one() -> None:
    r = validate(fed_machine(item_id=2003), _stacked_spec(Fraction(40), belt_stack=1, pick=2), ids=TWO_INPUT_IDS)
    assert fired(r, "flow.belt_capacity")


def test_stack_of_is_one_everywhere_when_the_url_does_not_stack() -> None:
    # rule 1 says an ist=1 save is judged at 1 whatever its sorters could carry
    p = fed_machine(item_id=2003, sorter_id=PILE)
    ctx = context_for(p, _stacked_spec(Fraction(4), belt_stack=1, pick=1))
    assert all(ctx.stack_of(r) == 1 for r in range(len(ctx.runs)))


def test_stack_of_a_merge_is_the_minimum_over_its_sources() -> None:
    # a stack-2 entry belt and a sorter-placed stack-1 run merge into one trunk
    p, spec, trunk_head = _merged_stacks(entry_stack=2, place=1)
    ctx = context_for(p, spec)
    assert ctx.stack_of(ctx.run_of[trunk_head]) == 1


def test_flow_stack_pickable_fires_for_any_sorter_below_a_pile_sorter() -> None:
    # Mk.I to Mk.III pick 1 at every research level (spec §5.1), so a stacked
    # bus over any of them is a refusal, not a slow build.
    r = validate(fed_machine(item_id=2003, sorter_id=2013), _stacked_spec(Fraction(4), belt_stack=2, pick=2), ids=TWO_INPUT_IDS)
    assert fired(r, "flow.stack_pickable")


def test_flow_stack_pickable_is_quiet_for_a_pile_sorter() -> None:
    r = validate(fed_machine(item_id=2003, sorter_id=PILE), _stacked_spec(Fraction(4), belt_stack=4, pick=4), ids=TWO_INPUT_IDS)
    assert not fired(r, "flow.stack_pickable")
```

Helpers this task writes in `tests/layout/test_validate.py`: `fed_machine(*, item_id: int = 2002, sorter_id: int = 2011)` (its current body is three lines at `:2706`; keep the no-argument behaviour identical); `_stacked_spec(rate: Fraction, *, belt_stack: int, pick: int, place: int | None = None) -> BuildSpec` (Mk.III floor, `sorter_pick_stacks=(1, 1, 1, pick)` and `sorter_place_stacks=(1, 1, 1, pick if place is None else place)` — the leading ones are the game's Mk.I to Mk.III, which never stack, and `pick`/`place` are the Pile Sorter's row from §5.1's table); `_merged_stacks(*, entry_stack: int, place: int) -> tuple[Placement, BuildSpec, int]` (an entry belt run and a machine-fed run joining through a splitter into one trunk, returning the trunk's head index); `context_for(p, spec) -> Context` (wrap `validate._context` with `id_map(spec)`, `soft_width=256`, `cat.DEFAULT_MAX_BELT_Z`, `True`, exactly as `belt_run_demands` does at `:5708`, unless the module already has such a helper). `PILE` already exists in the module. Add a `flow.sorter_capacity` test: a PILE SORTER moving 2 x its rate at stack 2 passes where stack 1 fails — `catalog.SORTER_STACK_RATE_FACTOR` is pinned `True` (spec §5.1), so this is a required behaviour and not conditional on the dump; a Mk.III at stack 2 is NOT a valid case, because a Mk.III can never carry a stack.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_validate.py -q -k "stack"`
Expected: FAIL — no `stack_of`, no `flow.stack_pickable` check registered.

- [ ] **Step 3: Implement `stack_of`**

Add `stack_of: dict[int, int] | None = None` to `_Cache`, and on `Context`:

```python
    def stack_of(self, run: int) -> int:
        """The cargo stack every unit on ``run`` is guaranteed to have (design 5.5).

        Walks upstream over ``pred`` from the run through junctions and other
        runs to every source and takes the MINIMUM: an entry belt carries the
        URL's stack, a sorter placing from a machine carries its tier's place
        stack, a piler DOUBLES the stack of the run into it (capped at 4;
        there is no stack setting on a piler to read -- design 5.1), and a run
        with no traceable source carries 1.  The minimum is the only stack a
        mixed merge is guaranteed to carry, so capacity at the minimum is never
        optimistic.
        """
```

Return 1 immediately when `self.spec is None or self.spec.belt_stack == 1` (rule 1: an `ist=1` save is judged exactly as today, Pile Sorters included). Otherwise implement with an explicit stack and a `seen` set over `Node`s (runs and junctions), reading `self.spec.belt_stack` at an entry run (`_entry_runs(self)` names them), the sorter's tier place stack for a run whose head is fed by a sorter (build `{cat.get_item_id(s): i for i, s in enumerate(spec.sorter_item_ids)}` once in `_Cache`, the idiom `_sorter_tier_allowed` uses at `:5195-5199`, then index `spec.sorter_place_stacks`), and 1 otherwise; cache per run. Pilers are Task 14's addition; leave a comment where the piler case goes.

- [ ] **Step 4: Apply it**

`_belt_capacity`: `capacity = min(rates) * ctx.stack_of(ridx)` and add `"stack": ctx.stack_of(ridx)` to the detail (the message says `at stack N` when N > 1). `_sorter_capacity`: `capacity = cat.sorter_rate(s.item_id, span) * stack` where `stack` is the sorter's pick stack when it draws from a belt run and its place stack when it feeds one (the module's `_sorter_items`/`_anchors` tell which end is the belt). New check:

```python
@check("flow.stack_pickable", needs_spec=True)
def _stack_pickable(ctx: Context) -> Iterable[Finding]:
    """A sorter drawing from a stacked run must be able to pick that stack.

    A stacked bus over Mk.I sorters would not starve loudly in the game; it
    would feed slowly.  This turns it into a refusal with the stack named.
    """
```

iterating `ctx.of_kind(Kind.SORTER)`, finding the run the sorter draws from (`s.input_obj` on a belt tile -> `ctx.run_of`), comparing `ctx.stack_of(run)` with the tier's pick stack. `_external_entry_points`: `capacity = spec.lane_capacity * spec.planning_stack(item, external=True)`.

- [ ] **Step 5: Run, lint, type-check, commit**

```bash
uv run pytest tests/layout/test_validate.py tests/layout/test_belt_tiers.py -q
uv run ruff check src/flab2bp/layout/validate.py tests/layout/test_validate.py
uv run mypy src/flab2bp/layout/validate.py
git add src/flab2bp/layout/validate.py tests/layout/test_validate.py
git commit -m "feat(validate): judge belt and sorter capacity at the cargo stack a run carries"
```

### Task 10: Retier at the stack, report it, and gate B

**Files:**
- Modify: `src/flab2bp/layout/belt_tiers.py` — `retier_belts` (`:30`, the `demand` at `:60`)
- Modify: `src/flab2bp/layout/validate.py` — `belt_run_demands` (`:5708`) returns the stack map too
- Modify: `src/flab2bp/cli.py`, `src/flab2bp/web/payload.py` — the `belts:` line and payload gain `stack N (URL ist=N)`
- Modify: `tests/test_pipeline.py` — the `ist=2` end-to-end test
- Create: `docs/superpowers/evidence/<date>-stacked-lanes/...`
- Test: `tests/layout/test_belt_tiers.py`, `tests/test_cli.py` (created by Task 3), `tests/web`

**Interfaces:**
- Produces: `belt_run_demands(placement, spec) -> tuple[tuple[BeltRun, ...], dict[int, dict[str | None, Fraction]], dict[int, int]]` (update its callers, found with Serena; the retier pass is the only production one).

- [ ] **Step 1: Tests**

`tests/layout/test_belt_tiers.py`: a Mk.II run at 20 items/s with `belt_stack=2` keeps Mk.II (`_spec` gains `belt_stack`, `sorter_pick_stacks`); the same at stack 1 takes Mk.III. `tests/test_pipeline.py`:

```python
@pytest.mark.slow
def test_a_stacked_url_belts_hydrogen_in_on_one_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ist=2`` with every technology researched: 40 items/s is 20 cargo/s,
    so one Mk.III entry lane carries it and no strip is shortened.  Budget as
    the other slow tests."""
    _with_belt(monkeypatch, "conveyor-belt-3", stack=Fraction(2))
    build = pipeline.build(DEUTERON_URL, strategy="sequence-pair", time_budget_s=45.0,
                           candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,))
    assert build.report.ok
    assert build.spec.belt_stack == 2
    hydrogen = [f for f in build.report.by_check("flow.external_entry_points")
                if f.detail["item"] == "hydrogen"]
    assert not hydrogen  # super-magnetic-ring's two lanes are unrelated to stacking
```

`_with_belt` gains a `stack` keyword that patches `LabRequest.stack`.

- [ ] **Step 2: Implement**

`retier_belts`: `runs, demands, stacks = belt_run_demands(placement, spec)`; `demand = sum(...) / stacks.get(index, 1)`; keep the fall-through to the fastest tier intact (`belt_tiers.py:62-67`), so a run above the ceiling still ends on the ceiling and `flow.belt_capacity` refuses. `belt_run_demands` computes `{index: ctx.stack_of(index) for index in range(len(ctx.runs))}` after `_run_demand`. CLI: append `; stack {spec.belt_stack}` plus `(URL ist={spec.belt_stack})` when above 1; payload adds `"stack": spec.belt_stack`.

- [ ] **Step 3: Gate B**

As Task 5, under `docs/superpowers/evidence/<date>-stacked-lanes/`, baseline = Task 5's candidate rounds. Additionally compare every cell in default mode (`--noise-area 0.013`) and assert in `gate.md` that no `ist=1` cell moved outside noise (the corpus has no `ist>1` URL today; say so, and record the deuteron `ist=2` test as the only evidence of the stacked path).

- [ ] **Step 4: Full verification and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy
git add src/flab2bp/layout/belt_tiers.py src/flab2bp/layout/validate.py src/flab2bp/cli.py src/flab2bp/web/payload.py tests/layout/test_belt_tiers.py tests/test_pipeline.py tests/test_cli.py tests/web docs/superpowers/evidence/*-stacked-lanes
git commit -m "feat(layout): retier and report belt runs at their cargo stack"
```

---

## Deliverable C: Automatic Pilers

### Task 11: The piler fixture and its record

**Files:**
- Create: `tests/fixtures/<name>-piler.txt` (a player-built blueprint with one Automatic Piler between two belts, obtained from the game)
- Modify: `src/flab2bp/layout/junction.py` — `make_piler` after `make_splitter` (`:157`)
- Modify: `src/flab2bp/dsp/catalog.py` — `PILER_ID = 2040`, `BELT_INTEGRATED_IDS` (`:258`) gains it
- Test: `tests/dsp/test_roundtrip.py` (parametrised over fixtures, picks the new one up automatically); Create: `tests/layout/test_junction.py` (there is none today; the splitter helpers are tested from `test_freeform.py` and `test_validate.py`)

**Fact this task follows (Ruling P12): the piler has no parameter block.** `catalog.PILER_STACK_PARAMETER is None` — `PilerDesc` declares no fields, `PilerComponent.Export` serialises no stack, and Pile versus Split comes from `CargoTraffic.RematchPilerConnection` reading the wiring. So `src/flab2bp/dsp/params.py` is NOT touched by this task: there is no `params.piler`, no `params.piler_stack`, and no `parameter_index` to pin. What the fixture must pin instead is the WIRING: which neighbour names the piler, in which direction, and the four slot fields.

**This task is a human-in-the-loop prerequisite for C.** Without the fixture the record convention is unverified; stop here and record it if it cannot be obtained.

- [ ] **Step 1: Obtain and decode the fixture**

Decode with `codec.decode` and print the piler's record: `item_id, model_index, x, y, z, yaw, input_obj_idx, output_obj_idx, input_from_slot, input_to_slot, output_from_slot, output_to_slot, parameters`, and the two neighbouring belts' records. Write those values into the test below as literals. Record the observed `parameters` in the report even though nothing reads it — if it is not empty, that is a finding against the pinned fact and C stops until it is explained.

- [ ] **Step 2: Tests**

```python
def test_the_piler_fixture_records_its_neighbours_the_way_a_splitter_does() -> None:
    bp = codec.decode(fixture_text("<name>-piler"))
    piler = next(b for b in bp.buildings if b.item_id == 2040)
    before = next(b for b in bp.buildings if b.output_obj_idx == piler.index)
    after = next(b for b in bp.buildings if b.input_obj_idx == piler.index)
    # The piler names nobody; the belts around it name IT.  (-1, -1) expected
    # like a splitter, but the fixture decides.
    assert (piler.input_obj_idx, piler.output_obj_idx) == (<literal>, <literal>)
    assert (piler.input_from_slot, piler.input_to_slot) == (<literal>, <literal>)
    assert (piler.output_from_slot, piler.output_to_slot) == (<literal>, <literal>)
    assert (before.x, before.y) == (<literal>, <literal>)
    assert (after.x, after.y) == (<literal>, <literal>)


def test_the_piler_carries_no_parameter_block() -> None:
    """catalog.PILER_STACK_PARAMETER is None: the stack is not a building setting.

    A piler's Pile-or-Split mode comes from its wiring and the stack it emits
    comes from the stack arriving on its input belt (spec §5.1, §6.3).
    """
    bp = codec.decode(fixture_text("<name>-piler"))
    piler = next(b for b in bp.buildings if b.item_id == 2040)
    assert catalog.PILER_STACK_PARAMETER is None
    assert piler.parameters == ()   # replace with the fixture's literal; report if non-empty
```

plus `make_piler(x, y, z, yaw=...)` producing a `PlacedBuilding` whose serialised record equals the fixture's piler record field for field (except position). There is no `params.piler(...)` pin, because there is no such function.

- [ ] **Step 3: Implement `make_piler` and the catalog entries**

```python
def make_piler(x: int, y: int, z: Fraction = Fraction(0), *, yaw: float = 0.0) -> PlacedBuilding:
    """An Automatic Piler at ``(x, y)`` facing ``yaw``.

    Like a splitter it names nobody: the belt before it names it as
    ``output_obj`` and the belt after as ``input_obj``, and that wiring is
    also what puts the component into Pile mode
    (``CargoTraffic.RematchPilerConnection``).

    There is NO stack argument.  ``catalog.PILER_STACK_PARAMETER is None``:
    the game stores no stack on the building.  A piler doubles whatever
    arrives, capped at ``catalog.PILER_MAX_STACK``, so the stack a lane ends
    up at is decided by how many pilers it passes through, which is
    ``layout/piling.py``'s job, not this function's.
    """
```

using `catalog.building(PILER_ID)` for the model index (257) and footprint (`width=1, height=3`). `BELT_INTEGRATED_IDS` gains `PILER_ID` so `_context` stops treating it as a blocking building.

- [ ] **Step 4: Commit**

```bash
uv run pytest tests/dsp tests/layout/test_junction.py -q
git add tests/fixtures/<name>-piler.txt src/flab2bp/dsp/catalog.py src/flab2bp/layout/junction.py tests/dsp tests/layout/test_junction.py
git commit -m "feat(dsp): decode, build, and re-encode an Automatic Piler byte for byte"
```

### Task 12: The merge tree

**Files:**
- Create: `src/flab2bp/layout/piling.py`
- Test: `tests/layout/test_piling.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class LaneLoad:
    lane_id: str
    strip_ordinal: int
    demand: Fraction       # items/s
    stack: int             # planned stack the lane carries before piling

@dataclass(frozen=True, slots=True)
class PilerPlan:
    lane_id: str
    count: int             # pilers IN SERIES at the lane's tail; a piler doubles
    stack: int             # the stack the LAST of them emits

@dataclass(frozen=True, slots=True)
class MergePlan:
    stack: int                            # the uniform stack every belt into the sink carries
    groups: tuple[tuple[str, ...], ...]   # lane ids sharing one belt each; a group of one is a parallel belt
    pilers: tuple[PilerPlan, ...]         # one per lane whose planned stack was below `stack`

def plan_merges(loads: Sequence[LaneLoad], *, lane_capacity: Fraction, max_stack: int,
                sink_pick_stack: int) -> MergePlan: ...
```

**Facts this task follows (Ruling P12):**

- `catalog.PILER_SINGLE_PASS is False` and `catalog.PILER_MAX_STACK == 4`: a piler DOUBLES, so `PilerPlan` carries a `count` of pilers in series (`ceil(log2(stack / lane.stack))`) and the candidate uniform stacks are the doubling ladder `spec.PILER_LADDER == (1, 2, 4)`, not every integer in `1..limit`. Targeting 3 would silently overshoot to 4 past a sink that picks only 3.
- `catalog.PILER_THROUGHPUT * beltSpeed == catalog.BELT_RATE`: a piler never throttles its belt, so **`plan_merges` has no `piler_throughput` parameter**. Spec §6.2's old step 5 is deleted, not defaulted; do not reintroduce it as an unused keyword.

- [ ] **Step 1: Tests**

```python
def _load(i: int, demand: int, stack: int = 1) -> LaneLoad:
    return LaneLoad(lane_id=f"lane-{i}", strip_ordinal=i, demand=Fraction(demand), stack=stack)


def _plan(loads: list[LaneLoad], *, sink_pick_stack: int = 4) -> MergePlan:
    return plan_merges(loads, lane_capacity=Fraction(30), max_stack=4, sink_pick_stack=sink_pick_stack)


def test_four_full_lanes_pile_to_four_through_two_pilers_each() -> None:
    # A piler doubles: 1 -> 2 -> 4, so an unstacked lane needs TWO in series.
    plan = _plan([_load(i, 30) for i in range(4)])
    assert plan.stack == 4
    assert plan.groups == (("lane-0", "lane-1", "lane-2", "lane-3"),)
    assert plan.pilers == tuple(PilerPlan(f"lane-{i}", count=2, stack=4) for i in range(4))
    assert sum(p.count for p in plan.pilers) == 8


def test_two_twenties_pile_to_the_smallest_stack_that_fits() -> None:
    plan = _plan([_load(0, 20), _load(1, 20)], sink_pick_stack=2)
    assert plan.stack == 2
    assert plan.groups == (("lane-0", "lane-1"),)
    assert plan.pilers == (PilerPlan("lane-0", count=1, stack=2), PilerPlan("lane-1", count=1, stack=2))


def test_a_lane_that_starts_stacked_needs_one_piler_where_an_unstacked_one_needs_two() -> None:
    plan = _plan([_load(0, 30, stack=2), _load(1, 30, stack=1), _load(2, 30), _load(3, 30)])
    assert plan.stack == 4
    assert plan.pilers == (
        PilerPlan("lane-0", count=1, stack=4),
        PilerPlan("lane-1", count=2, stack=4),
        PilerPlan("lane-2", count=2, stack=4),
        PilerPlan("lane-3", count=2, stack=4),
    )


def test_a_lane_at_stack_three_reaches_four_in_one_piler() -> None:
    # A level-3 Pile Sorter places 3; 2 x 3 caps at PILER_MAX_STACK.
    plan = _plan([_load(0, 40, stack=3), _load(1, 40, stack=3)])
    assert plan.stack == 4
    assert plan.pilers == (PilerPlan("lane-0", count=1, stack=4), PilerPlan("lane-1", count=1, stack=4))


def test_lanes_that_already_fit_share_a_belt_without_a_piler() -> None:
    plan = _plan([_load(0, 10), _load(1, 10)], sink_pick_stack=1)
    assert plan == MergePlan(stack=1, groups=(("lane-0", "lane-1"),), pilers=())


def test_a_lane_already_above_the_uniform_stack_keeps_it_and_gets_no_piler() -> None:
    plan = _plan([_load(0, 20, stack=4), _load(1, 20)], sink_pick_stack=4)
    assert plan.stack == 2
    assert plan.pilers == (PilerPlan("lane-1", count=1, stack=2),)


def test_a_flow_stack_four_cannot_absorb_is_grouped_by_ordinal() -> None:
    plan = _plan([_load(i, 30) for i in range(5)])
    assert plan.stack == 4
    assert plan.groups == (("lane-0", "lane-1", "lane-2", "lane-3"), ("lane-4",))
    assert sum(p.count for p in plan.pilers) == 10


def test_the_sink_pick_stack_caps_the_stack_and_forces_parallel_belts() -> None:
    plan = _plan([_load(0, 30), _load(1, 30)], sink_pick_stack=1)
    assert plan == MergePlan(stack=1, groups=(("lane-0",), ("lane-1",)), pilers=())


def test_a_sink_that_picks_three_is_planned_at_two_because_a_piler_cannot_land_on_three() -> None:
    # limit = 3, but the doubling ladder offers only 1 and 2 at or below it.
    # Planning 3 would build two pilers and deliver 4, which the sink cannot pick.
    plan = _plan([_load(0, 30), _load(1, 20)], sink_pick_stack=3)
    assert plan.stack == 2
    assert all(p.stack == 2 for p in plan.pilers)


def test_the_plan_is_deterministic_across_input_order() -> None:
    loads = [_load(2, 30), _load(0, 20), _load(1, 25)]
    by_ordinal = sorted(loads, key=_ordinal)
    assert _plan(loads) == _plan(by_ordinal)


def _ordinal(load: LaneLoad) -> int:
    return load.strip_ordinal
```

- [ ] **Step 2: Implement**

Per §6.2, deterministic and without set iteration:

```python
def _pilers_in_series(from_stack: int, to_stack: int) -> int:
    """Pilers needed to raise ``from_stack`` to ``to_stack``.

    A piler DOUBLES (``catalog.PILER_SINGLE_PASS`` is False), capped at
    ``catalog.PILER_MAX_STACK``, so this is ``ceil(log2(to / from))``: one for
    1 -> 2, 2 -> 4 and 3 -> 4 (the cap absorbs the overshoot), two for 1 -> 4.
    """
    count = 0
    stack = from_stack
    while stack < to_stack:
        stack = catalog.piler_output_stack(stack)
        count += 1
    return count
```

(the loop is used rather than `math.log2` so the cap and the pinned
`piler_output_stack` are the single source of truth and no float rounding
enters; it terminates because `piler_output_stack(s) > s` for every `s <
PILER_MAX_STACK`.)

Then: sort loads by `strip_ordinal`; `limit = min(max_stack, sink_pick_stack)`; `candidates = tuple(s for s in spec.PILER_LADDER if s <= limit)` — the doubling ladder, so `sink_pick_stack == 3` yields `(1, 2)` and a plan of 3 is never produced; `total = sum(load.demand)`; the uniform stack is the smallest candidate with `total / s <= lane_capacity`, else `candidates[-1]`. A `PilerPlan(lane_id, count=_pilers_in_series(lane.stack, s), stack=s)` is emitted for every lane whose `stack < s`; a lane at or above `s` keeps its stack and gets none. If `total / s <= lane_capacity` all lanes form one group; otherwise walk the lanes in ordinal order, opening a new group whenever adding the lane's `demand / max(lane.stack, s)` would push the group's cargo over `lane_capacity`. Docstring states the three cargo rules from the spec, why the smallest fitting stack is chosen (fewest pilers, most sink headroom), and why the candidates are a ladder rather than a range. `spec.PILER_LADDER` (Task 8) is imported, not redefined.

- [ ] **Step 3: Commit**

```bash
uv run pytest tests/layout/test_piling.py -q && uv run ruff check src/flab2bp/layout/piling.py tests/layout/test_piling.py && uv run mypy src/flab2bp/layout/piling.py tests/layout/test_piling.py && uv run pytest tests/rules -q
git add src/flab2bp/layout/piling.py tests/layout/test_piling.py
git commit -m "feat(layout): plan pilers and merges per item under the cargo rules"
```

### Task 13: The strip's tail extension and piler emission

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` — `Strip` (`:881` region) gains `tail_extension: int = 0` and `pilers: tuple[PilerPlan, ...] = ()`; `_box` (`:1544`) adds the extension on the output side; `plan_strips` (`:2070`) calls `plan_merges` per produced item and marks strips; the emission of output lanes (find where a strip's output belt row is laid and linked, from `_build_prepared` down; the research note names `_flank_lane`/`_link_lane` as the sorter-side emitters) places one `make_piler` per `PilerPlan.count` along the extension and links the belts around each
- Modify: `src/flab2bp/layout/sequence_solver.py` — the `Strip` REBUILD from a variant (`:3145-3164`, where a reservation is realised with `replace(strip, west_channel=...)` at `:3096`) must carry `tail_extension` and `pilers` through; packing widths already flow through `_box` (`sequence_solver.py:4095`), so no pitch read changes
- Test: `tests/layout/test_freeform.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `plan_merges` (Task 12), `make_piler` (Task 11), `LogicalLane.stack` (Task 8), `spec.piler_unlocked`, `spec.belt_stack`.
- Produces: a strip reserves `4 x count - 1` tiles on its output side, where `count` is the largest `PilerPlan.count` over its own output lanes (**Ruling P12:** a piler is `1 x 3` — `catalog.building(2040)` is `width=1, height=3` — a lane raised from unstacked to 4 carries TWO of them, and they cannot abut, because a `PilerComponent` reads an input belt and an output belt; two in series are `3 + 1 + 3 = 7` tiles, not 3 and not 6); emitted placements contain item 2040 exactly as many times as `MergePlan.pilers` said, each between two belts of its lane; the router sees each piler's ports as a source and a sink (a lane with `count` pilers becomes `count + 1` nets). There are no entry-side pilers (§6.3): a consumer's feed is the producer's piled lane, and the player's bus arrives stacked.

- [ ] **Step 1: Tests**

A strip planned from a stacked spec whose producer lanes need ONE piler has `tail_extension == 3` and `_box` three tiles wider; a strip whose lane must go from unstacked to stack 4 has `tail_extension == 7` (`4 x 2 - 1`: two pilers of three tiles plus the one separator belt tile) and `_box` seven tiles wider, and emits two pilers in series on that lane with a belt between them (the upstream one named as `output_obj` by the belt before it, the downstream one named as `input_obj` by the belt after it); a strip with no `PilerPlan` stays at 0 and produces byte-identical strips (assert equality against a plan from the same spec with `piler_unlocked=False`). An emitted placement for the two-twenties case contains exactly two pilers, one per lane. The sequence solver's rebuild preserves the fields: `_sequence_reservation_strips` (or whatever the rebuild site is named; find it with Serena) applied to a strip with `tail_extension=7, pilers=(...)` returns a strip with both intact, and a strip with `tail_extension=7` packs seven tiles wider through `_box`.

- [ ] **Step 2: Implement**

`plan_strips`: after families are partitioned into strips and only when `spec.piler_unlocked and spec.belt_stack > 1`, build `LaneLoad`s per (produced item, sink) from each producer strip's output lanes (`demand = machine_count * outputs_per_machine[item]`, `stack = lane.stack`, ordinal = the strip's index in plan order), call `plan_merges` with `lane_capacity=spec.lane_capacity`, `max_stack=spec.max_stack`, `sink_pick_stack=` the consumer's pick stack (`spec.sorter_pick_stacks[-1]`, or `spec.max_stack` for the boundary) and no throughput argument, and stamp `pilers` and `tail_extension = PILER_TILES * count + (count - 1)` on strips that received one, where `count = max(p.count for p in that strip's PilerPlans)` and `PILER_TILES = catalog.building(catalog.PILER_ID).height` (3) is read from the catalog rather than written as a literal, so R1 is satisfied and the number stays tied to the footprint. The `count - 1` belt tiles are the separators §6.3 requires between consecutive pilers, since a `PilerComponent` reads an input belt and an output belt and two pilers cannot abut: one piler is 3 tiles, two in series are 7. Record `MergePlan.groups` on the plan so the router's junction merges follow it (a group is the set of lanes that may share a belt; the router already merges tributaries into a consumer lane through junctions, so groups of one become separate nets to the sink, exactly A's parallel lanes). `_box` adds `tail_extension` on the output side.

Emission: when a strip lane has a `PilerPlan`, lay the lane's belt row through the extension and place `plan.count` pilers along it, each with `yaw` along the lane and separated by a belt tile. Every piler splits the lane's net, so a lane with `count` pilers yields `count + 1` nets: for each piler the belt before it names it as `output_obj` and the belt after names it as `input_obj`, and the router's ports for that lane are the belt tile before the FIRST piler (sink side of the head net) and the belt tile after the LAST (source side of the tail net). `make_piler` takes no stack argument (Task 11): what the chain delivers is `count` doublings of the lane's own stack, which Task 14 re-derives from the built placement. Resolve the exact port-registration site with Serena (`_prepare_routing_problem`'s in-port/out-port collection at `freeform.py:13960-13970` is where entry ports are gathered; output ports are gathered nearby). If the port split or the group-following needs more than a targeted change to `_prepare_routing_problem` or the router's merge order, stop and report with the exact obstacle.

- [ ] **Step 3: Digests and commit**

Both route digests must still MATCH (the corpus has no `ist>1` URL, so no piler is ever planned there). Then:

```bash
uv run pytest tests/layout -q && uv run ruff check src/flab2bp/layout && uv run mypy src/flab2bp/layout
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
git commit -m "feat(layout): reserve a tail for each piled lane and emit its piler"
```

### Task 14: The validator knows the piler

**Files:**
- Modify: `src/flab2bp/layout/validate.py` — `Kind.PILER`, `_kind` (`:141`), `_context` (`:680-687`), `_build_graph` (`:581`), `Context.stack_of` (Task 9), new checks `piler.ports`, `piler.input_rate`, `piler.tier_allowed`
- Test: `tests/layout/test_validate.py`

**Fact this task follows (Ruling P12):** there is no piler stack parameter to decode (`catalog.PILER_STACK_PARAMETER is None`), so `stack_of` after a piler is DERIVED — `catalog.piler_output_stack(stack_of(the run into it))`, i.e. `min(2 x input, 4)` — and two pilers in series are judged by applying it twice, which falls out of the upstream walk for free.

- [ ] **Step 1: Tests**

Hand-built placements with a `piler(x, y, yaw)` helper (no stack argument): `_kind` returns `Kind.PILER`; a belt->piler->belt chain forms two runs joined in `succ`/`pred`; `stack_of` on the run after one piler on a stack-1 feed is 2, after a second piler in series is 4, and after a piler on a stack-4 feed is still 4 (the `PILER_MAX_STACK` cap); `flow.belt_capacity` passes 60 items/s on the Mk.III run after one piler fed a stack-1 belt, and `piler.input_rate` fires when the run INTO the piler carries 40 cargo/s; `piler.ports` fires when a belt named around the piler is not on its port pose; `piler.tier_allowed` fires when `spec.piler_unlocked` is False, and fires when `spec.belt_stack == 1` even with the piler unlocked (spec §6.4 states both conditions); every existing `junction.*` and `machine.*` check ignores the piler.

- [ ] **Step 2: Implement**

`Kind.PILER`; in `_kind`, `if b.item_id == cat.PILER_ID: return Kind.PILER` before the catalog lookup; `_context`'s two `is Kind.SPLITTER` tests become `in (Kind.SPLITTER, Kind.PILER)`; `_build_graph` treats a piler like a splitter with one in and one out; `stack_of` for a run whose head draws from a piler returns `cat.piler_output_stack(self.stack_of(the run feeding that piler))` — never a parameter read, because the game stores none. Keep the existing memo so a chain of pilers is still linear in the graph, and keep the `seen` set so a cycle cannot recurse. Checks mirror `junction.ports` (`:2977`) and `sorter.tier_allowed` (`:5192`) in shape; `piler.input_rate` reads `_run_demand` on the run feeding the piler and compares `demand / stack_of(that run)` against `BELT_RATE` of its slowest tile (the piler itself imposes no lower bound: `PILER_THROUGHPUT * beltSpeed == BELT_RATE`, so the belt is the only constraint and no separate piler-throughput check is written).

- [ ] **Step 3: Commit**

```bash
uv run pytest tests/layout/test_validate.py -q && uv run ruff check src/flab2bp/layout/validate.py && uv run mypy src/flab2bp/layout/validate.py
git add src/flab2bp/layout/validate.py tests/layout/test_validate.py
git commit -m "feat(validate): judge pilers as run boundaries with their own checks"
```

### Task 15: Retier, report, end to end, and gate C

**Files:**
- Modify: `src/flab2bp/layout/belt_tiers.py` (the stack map already includes piler-fed runs through `stack_of`; add a test), `src/flab2bp/cli.py`, `src/flab2bp/web/payload.py`, `src/flab2bp/layout/base.py` (`PlacementStats`: `entry_lanes_needed: float`, `pilers: float`, alphabetical)
- Modify: `tests/test_pipeline.py`
- Create: `docs/superpowers/evidence/<date>-pilers/...`

- [ ] **Step 1: Stats and report**

`_build_prepared` counts pilers into `stats["pilers"]` and `entry_lanes_needed` (sum of `lanes_needed` over the entry-point findings, computed by the same arithmetic as Task 3, from the spec). CLI: `; N piler(s)` on the belts line; payload: `"pilers": N`.

- [ ] **Step 2: End to end**

Two synthetic specs (not corpus URLs; none stacks), both with `ist=2` and the piler unlocked:

1. **One piler per lane.** Two producer strips at 20 items/s each feeding one consumer strip: `lay_out` under both strategies emits two pilers (one per lane, stack 1 -> 2), validates clean, and `flow.belt_capacity` passes at the merge.
2. **Two pilers in series (Ruling P12).** THREE unstacked producer strips at 30 items/s each into one consumer strip whose sorters pick 4 (`sorter_pick_stacks[-1] == 4`, i.e. `pile-sorter-4` researched). Three is the smallest set that forces stack 4, and the arithmetic is worth stating because a smaller one silently emits nothing: one lane fits unpiled (`30 / 1 = 30 <= 30`, so `s = 1`), two lanes reach only stack 2 (`60 / 2 = 30 <= 30`, one piler each), and three lanes give `90 / 1 = 90` and `90 / 2 = 45`, both over the belt, so `s = 4` and `_pilers_in_series(1, 4) == 2` on every lane. Deliverable A's `machine_cap` bounds a strip's lane to `lane_capacity * planning_stack`, so a SINGLE unstacked lane can never need stack 4 — a one-lane version of this test would assert two pilers against a plan that emits none. Assertions: `lay_out` under both strategies emits SIX pilers, two in series per lane with a belt between them; each producer strip's `tail_extension == 7`; `Context.stack_of` on the run after each lane's second piler is 4; and the build validates clean. This is the case a single-pass piler model would have got wrong by half, so it is the regression pin for the doubling fact.

Mark slow only if either needs a real budget.

- [ ] **Step 3: Gate C**

As Task 10, under `docs/superpowers/evidence/<date>-pilers/`, baseline = Task 10's candidate rounds; the `ist=1` corpus must be byte-identical in strip counts and within noise in area, since no piler is ever planned for it.

- [ ] **Step 4: Full verification and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy
git add src/flab2bp/layout/belt_tiers.py src/flab2bp/cli.py src/flab2bp/web/payload.py src/flab2bp/layout/base.py tests/test_pipeline.py docs/superpowers/evidence/*-pilers
git commit -m "feat(layout): report pilers and gate the piled build"
```

---

## Self-review notes (kept for the reviewer)

- **Spec coverage (revision 3).** §2 rules -> Tasks 9, 12, 14. §4.1-4.5 -> Tasks 1-4. §4.4 (lane multiplicity) is deliberately not a task: the spec defers it to the gate. §5.1 -> Task 6 (EXECUTED; its four amended facts are carried into Tasks 7, 8, 11, 12, 13, 14, 15 and each of those names the one it follows). §5.2 -> Task 7 (including the `rates/solve.py` Belts objective, the `pile-sorter-{n}` level derivation and the level-0 defaults). §5.3-5.4 -> Task 8 (including `PILER_LADDER` and the elective-raise rule). §5.5 -> Task 9. §5.6 -> Task 10. §6.1-6.2 -> Tasks 12 and 13. §6.3 -> Tasks 11, 13 (the `4 x count - 1` tail). §6.4 -> Task 14 (derived `stack_of` after a piler). §6.5 and §7 -> Tasks 10, 15. §8 tests are distributed as listed, including §8's amended C bullet (eight pilers for 4 x 30; a sink picking 3 planned at 2) in Task 12 and the two-in-series end-to-end case in Task 15. §9 sequencing -> the three gates.
- **Type consistency (re-checked across Tasks 7-15 after the amendment).** `planning_stack(item, *, external=None)` is introduced in Task 1 with one positional parameter and gains the keyword in Task 8; Task 3's call uses the positional form and Task 9's the keyword form, both valid after Task 8. `spec.PILER_LADDER: tuple[int, int, int]` is introduced in Task 8 and imported (never redefined) by `layout/piling.py` in Task 12. `belt_run_demands`' three-tuple is introduced in Task 10 and consumed there only. `PilerPlan(lane_id: str, count: int, stack: int)` and `MergePlan(stack, groups, pilers)` are defined in Task 12 and consumed in Task 13 by name; `count` is what Task 13 turns into `tail_extension` (`4 x count - 1`, the separator belts included) and into the number of `make_piler` calls, and Task 15 sums it for `stats["pilers"]`; the three tile numbers agree — Task 13 Step 1 asserts 3 and 7, Task 13 Step 2 computes `PILER_TILES * count + (count - 1)`, Task 15 asserts 7, and spec §6.3 and §10 say the same. `junction.make_piler(x, y, z, *, yaw)` is defined in Task 11 and called in Task 13 with exactly that signature — no `stack` argument exists anywhere. `catalog.piler_output_stack(int) -> int` (Task 6, shipped) is called by Task 12's `_pilers_in_series` and by Task 14's `stack_of`, so the doubling rule has one implementation. `catalog.PILER_THROUGHPUT` is cited in Tasks 6 and 12 as a reason and read by no production code. `params.piler` / `params.piler_stack` were REMOVED by the amendment: no task defines them and no task calls them. `LogicalLane` is `order=True`; `stack` is appended as a trailing field so ordering of existing lanes is unchanged. Stack tuples are indexed only with `[-1]`, since a save without the Pile Sorter has three entries, not four; Task 7's alignment validator requires `len(sorter_pick_stacks) == len(sorter_place_stacks) == len(sorter_item_ids)`, so Task 8's `_stacked(..., ids=)` and Task 9's `_stacked_spec` must vary the ids and the tuples together — a three-entry tuple against the four default ids raises at construction.
- **Placeholders (re-scanned 2026-09-03).** Task 6's JSON sample and Task 11's `<literal>` fixture values are deliberately marked as shapes to be replaced by the shipped JSON and the fixture's decoded values; Task 11's `<name>-piler` is the fixture filename the implementer chooses. Nothing else is a placeholder: no code step says "add appropriate handling", every new test names its assertion, and every amended number is a table row from §5.1 rather than an illustrative one.
- **Amendment (Ruling P12, 2026-09-03)** applied to Tasks 7-15 after Task 6 pinned the game facts: the tech ids moved from the obsolete `sorter-cargo-stacking-{n}` to the live `pile-sorter-{n}` (Task 7); `BuildSpec`'s stack defaults moved to the real level-0 row `(1,1,1,2)`/`(1,1,1,1)` and every test tuple became a real table row (Tasks 7, 8, 9); `planning_stack` gained the doubling ladder and the elective-raise rule, and its refusal message names the right research (Task 8); `params.piler`/`params.piler_stack` and `make_piler`'s `stack` argument were deleted because the building has no parameter block (Tasks 11, 13, 14); `PilerPlan` gained `count` and `plan_merges` lost `piler_throughput` (Task 12); `tail_extension` became `4 x count - 1` (Task 13); `stack_of` after a piler became derived (Task 14); Task 15 gained the two-pilers-in-series end-to-end case. Tasks 1-6 and the Task 10 and 15 gates are unchanged.
- **Fix round 1 (2026-09-03, after review; 3 blocker / 3 medium / 4 minor, all applied).** B1: `tail_extension` was short by the separator belt tiles — two pilers cannot abut, because a `PilerComponent` reads an input belt and an output belt, so `count` pilers occupy `3 x count + (count - 1) = 4 x count - 1` tiles (3 for one, 7 for two); corrected in spec §6.3 and §10 and in Task 13's Produces, Step 1 (two assertions) and Step 2, and in Task 15. B2: Task 15's two-in-series case named ONE 30 items/s lane, which yields `s = 1` and no piler at all — and Deliverable A's `machine_cap` means a single unstacked lane can never need stack 4; rewritten to THREE lanes at 30 items/s (`90 / 2 = 45` over the belt, `90 / 4 = 22.5` under it), asserting six pilers, and the arithmetic for why one and two lanes do not work is stated in the task so nobody shrinks it again. B3: Task 8's `_stacked` helper could not express a save without a Pile Sorter — three-entry stack tuples against the four default `sorter_item_ids` would have failed Task 7's alignment validator at construction, before `pytest.raises`; the helper gained an `ids` parameter and the test passes three ids. M1: the refusal message now branches, naming Integrated Logistics System when `sorter-4` is absent (a save without the Pile Sorter cannot research the upgrade ladder, whose only prerequisite is that unlock) and Pile Sorter Upgrade otherwise, and both refusal tests' regexes pin the research name so the spec and the message cannot drift apart again. M2: the both-fed test moved to level 4 (`place 3`, `pick 4`, answer 3) — its `place` value is load-bearing and had been an unreal row. M3: three tests' rows made real (`place` passed explicitly in the two external-input assertions; Task 9's stale "a Pile Sorter places 4 by default" comment replaced). m1: Task 14 tests `piler.tier_allowed`'s second condition (`belt_stack == 1` with the piler unlocked). m2: GC-33 records A's line drift. m3: Task 6's preserved Produces carries a trailing "shipped values" note. m4: spec §8's Unit (B) bullet synced with Task 9's Mk.III case.
- **Re-validation at `60ab5f8` (2026-09-03, before execution)** found and this revision fixed: `particle-collider` is not a catalog id (`miniature-particle-collider`); `tests/test_cli.py` does not exist (Task 3 creates it); the deuteron build emits two `flow.external_entry_points` findings (hydrogen and super-magnetic-ring), so Tasks 4 and 10 filter on the item; the Mk.III test already passes today (the cap is inert at Mk.III) and is now the fast pin of `lanes_needed`; today's Mk.II refusal also names `flow.sorter_capacity`, which the belt cap cannot clear (Task 4's stop condition says what to report); gate baselines are generated fresh at the base from a git archive; a both-fed external item is planned at `min(belt_stack, place_stack)` (Task 8); `params.piler_stack` is the decoder Task 14 reads (Task 11) — **superseded by Ruling P12: the piler has no parameter block and there is no decoder**. The design premise (hydrogen belted in at 40 items/s; Mk.II refused with `flow.belt_capacity`) was re-measured and holds; both route digests MATCH at the base.
- **Review round 2 (2026-09-03)** found and this revision fixed: `merge_strip_instances` lives in `strip_variants.py`; the conservation test at `test_strip_variants.py:1343` needs its family uncapped; the three piler/sorter facts are now in Task 6's dump, schema and Produces and `plan_merges` takes `piler_throughput` (**superseded by Ruling P12: the pinned throughput equals `BELT_RATE`, so the parameter is gone**); `_pick_sorter` floors its tier by the planned stack (Task 8 Step 3b); `LogicalLane`, not `LanePlan`, carries the stack; §8's example count; §3 rule 3's edge; the pessimistic fit test is stated; `MachineGroup` import; typed `monkeypatch`.
- **Review round 1 (2026-09-03)** found and this revision fixed: the leaf-only merge tree could not express the spec's own example (resolved by single-pass piling to the uniform stack, no trunk pilers); `merge_strip_instances` as a second cap seam; `stack_of` and `planning_stack` gated on `belt_stack > 1`; an unpickable bus is refused, not capped; `cat.item_name` does not exist; `tests/layout/test_junction.py` is created, not modified; the Phase C collision reason; typed test signatures; the refusal regex order; `_family` always caps.
