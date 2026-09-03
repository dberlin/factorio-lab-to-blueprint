# Multiple Belts and Automatic Pilers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a flow above the fastest researched belt build anyway: first by capping machines per strip so every lane fits one belt and the flow arrives on parallel lanes (Phase A, no new building), then by placing Automatic Pilers where the URL says the player stacks belts (Phase B, prerequisites first).

**Architecture:** Phase A adds one rate-derived bound to the strip planner: `StripFamily.machine_cap`, computed in `_logical_strip_plans` from the group's per-machine rates and `spec.lane_capacity`, and applied inside `partition_strip_variant`, the single partition seam both strategies use. A single machine over the ceiling is refused early with the rate named. The validator's `flow.external_entry_points` warning learns how many lanes an item needs, and the reports say it. Phase B's implementation waits on two pieces of game evidence this plan makes into tasks: a player-built blueprint containing a piler, and the sorter cargo-stacking level mapping.

**Tech Stack:** Python 3.12+, frozen dataclasses in `layout/`, pydantic in `spec.py`, exact `Fraction` rates, pytest, `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-02-multiple-belts-and-pilers-design.md`

## Global Constraints

- Every rate is an exact `Fraction`; no float reaches geometry or the validator.
- A lane is one belt: its planned demand never exceeds `spec.lane_capacity` (Phase A) or `spec.lane_capacity x belt_stack` for a stacked lane (Phase B).
- Belt stacking is used only when the FactorioLab URL asked for it (`LabRequest.stack`, the `ist` parameter) and the researched technologies allow it; a URL silent about stacking gets Phase A only.
- The validator judges what was built; nothing is argued at planning time that `flow.belt_capacity` does not then confirm.
- Builds whose flows already fit one belt must be unchanged: the corpus gate (`scripts/audit.py --budget 30 --jobs 16`, compared with `scripts/audit_compare.py`) may not lose a clean cell, and evidence is committed under `docs/superpowers/evidence/<date>-multiple-belts/`.
- When several agents are active, use the built-in Read/Edit tools and the LSP tools, never Serena writes (Serena is one shared server; see memory `feedback-serena-shared-server-worktrees`). Confirm with `git status` that edits land in the intended worktree.
- Run tests with `uv run pytest <path> -q`; lint with `uv run ruff check` and `uv run mypy` on touched files before each commit (`freeform.py` carries 8 pre-existing mypy errors; add none).
- Commit messages end with the two trailer lines:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01RbwnAXJMnsp5fcmrB3TzuW`.
- Work on a branch from `master` in its own worktree.

---

## File structure

| File | Responsibility |
| --- | --- |
| `src/flab2bp/layout/strip_variants.py` | `machine_cap` on `_LogicalStripPlan` and `StripFamily`; the single-machine-over-ceiling refusal; the cap applied in `partition_strip_variant`. |
| `src/flab2bp/layout/validate.py` | `flow.external_entry_points` gains `lanes_needed` and a demand-aware message. |
| `src/flab2bp/cli.py`, `src/flab2bp/web/payload.py` | Entry-lane counts per external item in the reports. |
| `src/flab2bp/lab/techs.py`, `src/flab2bp/dsp/catalog.py` | Phase B: `LogisticsTiers.piler`, stacking-level mapping constants (after the evidence task). |
| `tests/layout/test_strip_variants.py`, `tests/layout/test_validate.py`, `tests/test_pipeline.py`, `tests/web/test_payload.py` | Tests per task. |
| `tests/fixtures/` | Phase B: the piler blueprint fixture. |

---

## Phase A: parallel belts

### Task 1: `machine_cap` on the logical plan and the family

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py` (`_LogicalStripPlan` at line 42, `StripFamily` at line 442, the plan construction near line 1107, the family construction near line 1476)
- Test: `tests/layout/test_strip_variants.py`

**Interfaces:**
- Produces: `_LogicalStripPlan.machine_cap: int` and `StripFamily.machine_cap: int = 0` (0 means unbounded, the value every hand-built family gets); `strip_variants.machine_cap_for(inputs: Mapping[str, Fraction], outputs: Mapping[str, Fraction], lane_capacity: Fraction) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_strip_variants.py` (it already imports `Fraction`, `BuildSpec`, `MachineGroup`, `generate_strip_families`; add `BeltTier` to the `flab2bp.spec` import and `machine_cap_for` to the `strip_variants` import):

```python
def test_machine_cap_is_the_floor_of_capacity_over_the_busiest_lane() -> None:
    inputs = {"hydrogen": Fraction(4), "titanium-alloy": Fraction(1, 10)}
    outputs = {"deuterium": Fraction(2)}
    assert machine_cap_for(inputs, outputs, Fraction(30)) == 7
    assert machine_cap_for(inputs, outputs, Fraction(12)) == 3
    assert machine_cap_for(inputs, outputs, Fraction(4)) == 1


def test_machine_cap_never_drops_below_one() -> None:
    assert machine_cap_for({"x": Fraction(40)}, {}, Fraction(30)) == 1


def test_families_carry_the_cap_from_the_spec_ceiling() -> None:
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=10,
                inputs_per_machine={"hydrogen": Fraction(4)},
                outputs_per_machine={"deuterium": Fraction(2)},
            ),
        ),
        external_inputs={"hydrogen": Fraction(40)},
        outputs={"deuterium": Fraction(20)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),),
    )
    (family,) = generate_strip_families(spec)
    assert family.machine_cap == 7
    floor_only = spec.model_copy(update={"belt_upgrades": ()})
    (family,) = generate_strip_families(floor_only)
    assert family.machine_cap == 3
```

If `miniature-particle-collider` has no strip pose in the catalog and `generate_strip_families` yields no family for it, use `assembling-machine-2` with recipe `magnetic-coil` and the same rates; the cap arithmetic is the assertion.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_strip_variants.py -q -k machine_cap`
Expected: FAIL with `ImportError: cannot import name 'machine_cap_for'`

- [ ] **Step 3: Implement**

In `src/flab2bp/layout/strip_variants.py`:

Add the helper before `_logical_strip_plans`:

```python
def machine_cap_for(
    inputs: Mapping[str, Fraction],
    outputs: Mapping[str, Fraction],
    lane_capacity: Fraction,
) -> int:
    """Most machines one strip may hold before some lane of its exceeds one belt.

    A strip's input lane for an item carries ``count x inputs[item]`` and its
    output lanes for an item carry at most ``count x outputs[item]`` between
    them, so the busiest single-item rate bounds the count.  Shared lanes are
    still checked by ``input_lane_fits`` and ``_check_shared_lane_capacity``;
    this is the bound that makes a lane splittable at all.  Never below one: a
    single machine over the ceiling is refused by the caller, not here.
    """
    busiest = max((*inputs.values(), *outputs.values()), default=Fraction(0))
    if busiest <= 0:
        return 0
    return max(1, int(lane_capacity // busiest))
```

(`Mapping` is already imported from `collections.abc`? The file imports `Iterable, Sequence`; add `Mapping`.)

Add `machine_cap: int` to `_LogicalStripPlan` after `total_machine_count`, and `machine_cap: int = 0` to `StripFamily` after `flank_outputs` with the comment `#: Most machines one strip may hold before a lane exceeds one belt; 0 means unbounded (hand-built families).` In `_logical_strip_plans`, where `_LogicalStripPlan(...)` is constructed (near line 1107), add `machine_cap=machine_cap_for(group.inputs, group.outputs, spec.lane_capacity),`. In `generate_strip_families`, pass `machine_cap=plan.machine_cap,` into `StripFamily(...)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_strip_variants.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py
uv run mypy src/flab2bp/layout/strip_variants.py
git add src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py
git commit -m "feat(layout): strip families know how many machines one belt can serve"
```

---

### Task 2: The cap binds inside `partition_strip_variant`

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py::partition_strip_variant` (line 1589)
- Test: `tests/layout/test_strip_variants.py`

**Interfaces:**
- Consumes: `StripFamily.machine_cap`.
- Produces: `partition_strip_variant` never yields an instance with more than `family.machine_cap` machines when the cap is non-zero.

- [ ] **Step 1: Write the failing test**

Append to `tests/layout/test_strip_variants.py` (reuse the spec from Task 1's third test as a helper `_collider_spec(upgrades: bool)`; `partition_strip_family` and `default_strip_variant` are already imported or importable from `strip_variants`):

```python
def test_partition_never_exceeds_the_family_cap() -> None:
    (family,) = generate_strip_families(_collider_spec(upgrades=True))
    instances = partition_strip_family(family, max_machine_count=12)
    assert max(i.machine_count for i in instances) <= 7
    assert sum(i.machine_count for i in instances) == 10
    (family,) = generate_strip_families(_collider_spec(upgrades=False))
    instances = partition_strip_family(family, max_machine_count=12)
    assert max(i.machine_count for i in instances) <= 3
    assert len(instances) == 4


def test_partition_keeps_the_caller_bound_when_it_is_tighter() -> None:
    (family,) = generate_strip_families(_collider_spec(upgrades=True))
    instances = partition_strip_family(family, max_machine_count=2)
    assert max(i.machine_count for i in instances) <= 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_strip_variants.py -q -k partition_never_exceeds`
Expected: FAIL: `max(...) <= 7` is false (one instance of 10)

- [ ] **Step 3: Implement**

In `partition_strip_variant`, after the `max_machine_count <= 0` guard:

```python
    if family.machine_cap:
        max_machine_count = min(max_machine_count, family.machine_cap)
```

and extend the docstring: "``family.machine_cap`` (when set) is the belt-capacity bound from ``machine_cap_for``; the caller's ``max_machine_count`` is a search-cost bound, and the tighter one wins."

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_strip_variants.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q` (solver-heavy; several minutes)
Expected: PASS. Any change in an existing layout test's strip count is a finding to report, not to silence: it means a lane in that fixture exceeded the ceiling and the old test was passing on a placement the validator would refuse.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py
git add src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py
git commit -m "feat(layout): cap machines per strip so no lane exceeds one belt"
```

---

### Task 3: Refuse a single machine over the ceiling, early and explained

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py::_logical_strip_plans`
- Test: `tests/layout/test_strip_variants.py`

**Interfaces:**
- Produces: `NoValidLayout` (from `flab2bp.layout.base`) raised from `_logical_strip_plans` naming the recipe, the item, the rate, and the ceiling belt.

- [ ] **Step 1: Write the failing test**

```python
def test_a_single_machine_over_the_ceiling_is_refused_with_the_rate_named() -> None:
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": Fraction(40)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ingot": Fraction(40)},
        outputs={"magnetic-coil": Fraction(1)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
    )
    with pytest.raises(NoValidLayout, match=r"copper-ingot.*40.*conveyor-belt-3.*30"):
        generate_strip_families(spec)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_strip_variants.py -q -k over_the_ceiling`
Expected: FAIL (no exception, or a `ValueError` from `_merge_lanes` instead of `NoValidLayout`)

- [ ] **Step 3: Implement**

In `_logical_strip_plans`, right after `groups = _adapt(spec)`, before any planning:

```python
    ceiling = spec.belt_tiers[-1]
    for key, group in groups.items():
        for item, rate in (*group.inputs.items(), *group.outputs.items()):
            if rate > spec.lane_capacity:
                raise NoValidLayout(
                    f"recipe {group.recipe_id!r}: one machine moves {item!r} at "
                    f"{rate} items/s, more than the {ceiling.items_per_second}/s "
                    f"{ceiling.item_id} sustains, the fastest belt this save can "
                    f"build; a single machine's lane cannot be split across belts"
                )
```

Import `NoValidLayout` from `flab2bp.layout.base` (the module already imports from there). Both strategies call `generate_strip_families` inside their layout entry points, which already turn `NoValidLayout` into a refusal; check with a grep for `generate_strip_families(` that no caller catches `ValueError` only and would let `NoValidLayout` escape as a crash.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_strip_variants.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py
git add src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py
git commit -m "feat(layout): refuse a single machine over the fastest belt, naming the rate"
```

---

### Task 4: `flow.external_entry_points` says how many lanes were needed

**Files:**
- Modify: `src/flab2bp/layout/validate.py::_external_entry_points` (line 4237)
- Test: `tests/layout/test_validate.py`

**Interfaces:**
- Produces: the finding's `detail` gains `"lanes_needed": int` (`ceil(spec.external_inputs[item] / lane_capacity)`), and the message says `"... ; <rate> items/s needs <n> lane(s) of <cap>/s"` when `entry_lanes == lanes_needed`, else keeps today's wording.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_validate.py`, after the existing `flow.external_entry_points` tests (grep for `external_entry_points` in the file to find them and reuse their fixture: two entry runs for one item into two machines):

```python
def test_external_entry_points_reports_the_lanes_the_rate_needs() -> None:
    p, spec, ids = _two_entry_lanes_fixture()  # the fixture the existing test uses
    spec = spec.model_copy(update={"external_inputs": {"copper-ingot": Fraction(20)}})
    r = validate(p, spec, ids=ids)
    (finding,) = r.by_check("flow.external_entry_points")
    assert finding.detail["lanes_needed"] == 2
    assert "20 items/s needs 2 lane(s) of 12/s" in finding.message


def test_external_entry_points_keeps_the_plain_wording_when_lanes_exceed_the_need() -> None:
    p, spec, ids = _two_entry_lanes_fixture()
    spec = spec.model_copy(update={"external_inputs": {"copper-ingot": Fraction(5)}})
    r = validate(p, spec, ids=ids)
    (finding,) = r.by_check("flow.external_entry_points")
    assert finding.detail["lanes_needed"] == 1
    assert "needs" not in finding.message
```

Write `_two_entry_lanes_fixture()` as a thin wrapper around whatever placement the existing entry-points test builds, returning `(placement, spec, ids)`; the spec must have `belt_items_per_second=Fraction(12)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_validate.py -q -k external_entry_points`
Expected: FAIL with `KeyError: 'lanes_needed'`

- [ ] **Step 3: Implement**

In `_external_entry_points`, compute per item:

```python
        rate = ctx.spec.external_inputs.get(item)
        capacity = ctx.spec.lane_capacity
        needed = int(-(-rate // capacity)) if rate else 0
        explained = needed == len(runs) and needed > 1
        tail = (
            f"; {rate} items/s needs {needed} lane(s) of {capacity}/s"
            if explained
            else "; the player must connect a supply to every one of them"
        )
        yield Finding(
            "flow.external_entry_points",
            Severity.WARNING,
            f"{item!r} is belted in at {len(runs)} separate lanes ({where}){tail}",
            tuple(ctx.runs[r].head for r in runs),
            {"item": item, "entry_lanes": len(runs), "lanes_needed": needed, "runs": sorted(runs)},
        )
```

Keep the check a WARNING and keep the docstring's reasoning; add a sentence that a count equal to the need is the multiple-belts design working as intended.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_validate.py -q`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/layout/validate.py tests/layout/test_validate.py
uv run mypy src/flab2bp/layout/validate.py
git add src/flab2bp/layout/validate.py tests/layout/test_validate.py
git commit -m "feat(validate): entry-point warning says how many lanes the rate needs"
```

---

### Task 5: Report entry-lane counts in the CLI and payload

**Files:**
- Modify: `src/flab2bp/cli.py` (after the `inputs to belt in` line, line 44), `src/flab2bp/web/payload.py` (`_attempt_detail` and `describe`)
- Test: `tests/web/test_payload.py`

**Interfaces:**
- Produces: payload key `entry_lanes`: `{item: {"lanes": int, "needed": int}}` on the build and each attempt detail, from the report's `flow.external_entry_points` findings (items with one lane are listed with `lanes 1, needed 1`); CLI line `entry lanes: hydrogen x2 (40/s needs 2 of 30/s), steel x1`.

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_payload.py`:

```python
def test_entry_lanes_travel_on_the_build_and_each_attempt(small_build: pipeline.Build) -> None:
    body = describe(small_build)
    lanes = body["entry_lanes"]
    assert isinstance(lanes, dict)
    assert set(lanes) == set(small_build.spec.external_inputs)
    for entry in lanes.values():
        assert isinstance(entry, dict)
        assert set(entry) == {"lanes", "needed"}
        assert entry["lanes"] >= 1 and entry["needed"] >= 1
    attempts = body["attempts"]
    assert isinstance(attempts, list)
    detail = attempts[0]["detail"]
    assert isinstance(detail, dict)
    assert set(detail["entry_lanes"]) == set(small_build.spec.external_inputs)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/web/test_payload.py -q -k entry_lanes`
Expected: FAIL with `KeyError: 'entry_lanes'`

- [ ] **Step 3: Implement**

In `payload.py` add a helper next to `_belt_tiers`:

```python
def _entry_lanes(spec: BuildSpec, report: validate.Report) -> Json:
    """Per external item, how many entry lanes were built and how many the rate needs."""
    found = {
        str(f.detail["item"]): (int(f.detail["entry_lanes"]), int(f.detail["lanes_needed"]))
        for f in report.by_check("flow.external_entry_points")
    }
    out: dict[str, JsonValue] = {}
    for item, rate in spec.external_inputs.items():
        lanes, needed = found.get(item, (1, max(1, int(-(-rate // spec.lane_capacity)))))
        out[item] = {"lanes": lanes, "needed": needed}
    return out
```

Wire `"entry_lanes": _entry_lanes(spec, attempt.report)` into `_attempt_detail` and `"entry_lanes": _entry_lanes(build.spec, build.report)` into `describe`. Add `entry_lanes: z.record(z.string(), z.object({lanes: z.number(), needed: z.number()}))` to both zod schemas in `web/src/api/build.ts` and the fixture defaults in `web/tests/support/build.ts`; render nothing new in the UI in this task (the "Belt in" line already lists the items).

In `cli.py`, after the `inputs to belt in` print:

```python
    lanes = {
        str(f.detail["item"]): (int(f.detail["entry_lanes"]), int(f.detail["lanes_needed"]))
        for f in build.report.by_check("flow.external_entry_points")
    }
    if lanes:
        parts = []
        for item, (count, needed) in sorted(lanes.items()):
            rate = build.spec.external_inputs.get(item, Fraction(0))
            why = f" ({rate}/s needs {needed} of {build.spec.lane_capacity}/s)" if needed == count else ""
            parts.append(f"{item} x{count}{why}")
        print(f"  entry lanes: {', '.join(parts)}", file=out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/web tests/test_pipeline_cli_strategy.py -q`; `cd web && bun run typecheck && bun run test && cd ..`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/flab2bp/cli.py src/flab2bp/web/payload.py tests/web/test_payload.py
uv run mypy src/flab2bp/cli.py src/flab2bp/web/payload.py
git add src/flab2bp/cli.py src/flab2bp/web/payload.py web/src/api/build.ts web/tests/support/build.ts tests/web/test_payload.py
git commit -m "feat(report): say how many entry lanes each input needed"
```

---

### Task 6: End to end on the hydrogen-at-40/s URL, and the corpus gate

**Files:**
- Test: `tests/test_pipeline.py`
- Create: `docs/superpowers/evidence/<date>-multiple-belts/{baseline-budget30.jsonl,candidate-budget30.jsonl,gate.md}`
- Modify: `README.md` ("What it builds"), the spec's status line

- [ ] **Step 1: Write the failing end-to-end tests**

Append to `tests/test_pipeline.py` next to the existing deuteron tests (`DEUTERON_URL`, `_with_belt`, `CandidatePolicy` are already there):

```python
@pytest.mark.slow
def test_hydrogen_above_the_ceiling_arrives_on_parallel_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the extraction-recipe change hydrogen is belted in at 40 items/s,
    above Mk.III's 30: the collider strips are capped so each entry lane fits
    one belt, and the warning says two lanes were needed."""
    build = pipeline.build(
        DEUTERON_URL,
        strategy="sequence-pair",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=45.0,
    )
    assert build.report.ok
    findings = build.report.by_check("flow.external_entry_points")
    hydrogen = [f for f in findings if f.detail.get("item") == "hydrogen"]
    assert hydrogen, "hydrogen must enter on more than one lane"
    assert hydrogen[0].detail["lanes_needed"] >= 2
    assert hydrogen[0].detail["entry_lanes"] >= hydrogen[0].detail["lanes_needed"]


@pytest.mark.slow
def test_mk2_floor_without_upgrade_splits_hydrogen_four_ways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_belt(monkeypatch, "conveyor-belt-2")
    original = pipeline.parse_url

    def patched(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return dataclasses.replace(
            original(url, **kwargs),
            belt_id="conveyor-belt-2",
            researched_technology_ids={
                "basic-logistics-system",
                "improved-logistics-system",
                "high-efficiency-logistics-system",
                *(f"vertical-construction-{n}" for n in range(1, 7)),
            },
        )

    monkeypatch.setattr(pipeline, "parse_url", patched)
    build = pipeline.build(
        DEUTERON_URL,
        strategy="sequence-pair",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=45.0,
    )
    assert build.report.ok
    (hydrogen,) = [
        f for f in build.report.by_check("flow.external_entry_points") if f.detail.get("item") == "hydrogen"
    ]
    assert hydrogen.detail["lanes_needed"] == 4
```

The second test replaces the refusal test from the belt-tier plan (`test_without_planetary_logistics_the_same_url_is_refused`): with Phase A that URL builds instead of refusing. Delete that test in the same commit and say so in the message.

- [ ] **Step 2: Run the tests to verify they fail before Tasks 1-5 and pass after**

Run: `uv run pytest tests/test_pipeline.py -q -k "parallel_lanes or four_ways"`
Expected: PASS after Tasks 1-5 (before them the first test refuses on `flow.belt_capacity` if the strips happen to exceed 30/s, or passes with `lanes_needed` missing).

- [ ] **Step 3: Full suite and corpus gate**

```bash
uv run pytest -q -p no:cacheprovider
mkdir -p docs/superpowers/evidence/$(date +%F)-multiple-belts
git worktree add --detach /tmp/flab2bp-baseline master
(cd /tmp/flab2bp-baseline && uv sync -q && uv run python scripts/audit.py --budget 30 --jobs 16 --json "$OLDPWD/docs/superpowers/evidence/$(date +%F)-multiple-belts/baseline-budget30.jsonl" | tail -4)
uv run python scripts/audit.py --budget 30 --jobs 16 --json docs/superpowers/evidence/$(date +%F)-multiple-belts/candidate-budget30.jsonl | tail -4
uv run python scripts/audit_compare.py docs/superpowers/evidence/$(date +%F)-multiple-belts/baseline-budget30.jsonl docs/superpowers/evidence/$(date +%F)-multiple-belts/candidate-budget30.jsonl
git worktree remove --force /tmp/flab2bp-baseline
```

Write `gate.md` with both commits, both counts, the compare output verbatim, and every cell whose status differs. A CLEAN→non-CLEAN cell is a defect to investigate (the cap only binds where a lane would have been refused, so a regression means the cap bound a lane the validator accepted; compare that cell's `flow.belt_capacity` findings on both trees).

- [ ] **Step 4: Docs and commit**

README "What it builds": after the belt-tier sentence add "a flow above the fastest belt is split across as many parallel lanes as it needs, one per strip". Spec status line: `Status: Phase A implemented on branch <name>; Phase B pending its prerequisites`.

```bash
git add tests/test_pipeline.py docs/superpowers/evidence README.md docs/superpowers/specs/2026-09-02-multiple-belts-and-pilers-design.md
git commit -m "test: hydrogen above the ceiling arrives on parallel lanes; corpus gate evidence"
```

---

## Phase B prerequisites (evidence before implementation)

### Task 7: The sorter cargo-stacking level mapping, from the game's data

**Files:**
- Create: `docs/superpowers/evidence/<date>-pilers/stacking-levels.md`
- Modify: `src/flab2bp/dsp/catalog.py` (constants only, with the evidence cited)
- Test: `tests/dsp/test_catalog.py`

- [ ] **Step 1: Find the numbers**

The snap oracle under `oracle/` is a C# probe against the game's assemblies (`oracle/Probe.cs`, `oracle/Oracle.cs`). Extend it, or use the existing `scripts/extract_dsp_tables.py`, to dump for each of `sorter-cargo-stacking-1..5` the `TechProto.UnlockValues` it applies and the game field it targets (the sorter's max stack), and for `pile-sorter-1..6` likewise, plus the Automatic Piler's own stack limit. Record the raw dump and the derived table in `stacking-levels.md`: for each researched level, the largest stack a Mk.I..III sorter may carry, and the same for the Pile Sorter.

- [ ] **Step 2: Encode**

Add to `catalog.py`, next to `SORTER_RATE_AT_1`:

```python
#: Largest cargo stack a sorter may carry at each researched
#: ``sorter-cargo-stacking-N`` level, index = level (0 = none researched).
#: From <stacking-levels.md>; every value is a game constant, not a guess.
SORTER_STACK_BY_LEVEL: tuple[int, ...] = (...)
#: Largest stack an Automatic Piler builds.
PILER_MAX_STACK = ...
```

with a test in `tests/dsp/test_catalog.py` asserting the tuple is non-decreasing, starts at 1, and ends at `PILER_MAX_STACK` or less. Commit with the evidence file.

### Task 8: A player-built blueprint containing an Automatic Piler

**Files:**
- Create: `tests/fixtures/<name>-with-piler.txt`
- Test: `tests/dsp/test_roundtrip.py`, `tests/dsp/test_local_offset.py`

- [ ] **Step 1: Obtain the fixture** — this needs the game: paste a small build in DSP with one Automatic Piler inline on a Mk.III belt between a source and a sorter-fed machine, copy the blueprint string, and save it under `tests/fixtures/`. Record in the file's header comment which game version produced it.
- [ ] **Step 2: Byte-identical re-encode** — add the fixture to the round-trip corpus in `tests/dsp/test_roundtrip.py` (follow how the other fixtures are listed) and run it. If it fails, the codec does not know a piler parameter block: that failure is the finding, report it with the decoded record.
- [ ] **Step 3: Geometry oracle** — add the fixture to `GEOMETRY_CORPUS` in `tests/dsp/test_local_offset.py` so the piler's port anchors are checked against its neighbouring belts like every other building.
- [ ] **Step 4: Commit** — `git commit -m "test: a player-built blueprint with an Automatic Piler as codec and geometry oracle"`.

### Task 9: Phase B plan

- [ ] Once Tasks 7 and 8 are committed, write `docs/superpowers/plans/<date>-automatic-pilers.md` from spec sections 4 and 5 with the numbers and fixture in hand: `BuildSpec.belt_stack` and `LogisticsTiers.piler` (from `logistics_tiers_for_request`, gated on `request.stack`), `LanePlan.stacked`, `junction.make_piler`, `Kind.PILER` and `Context.stack_of`, the `piler.ports` / `piler.tier_allowed` / `flow.stack_supported` / `flow.stack_mixed` checks, the retier pass dividing demand by the stack, and reporting. That plan is not written here because every one of those tasks quotes a number or a port pose this plan's Tasks 7 and 8 exist to establish.
