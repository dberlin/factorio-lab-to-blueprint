# Self-Consuming Flow Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route same-group product feedback in pinned steady-state flows so the exact refined-oil export produces valid Freeform and SequencePair layouts.

**Architecture:** Preserve producer-to-consumer destinations when the producing and consuming group are identical, because the physical output lane must feed the recipe's own input lane. Exclude that self edge only from Freeform's CP-SAT distance/separation proxy; detailed routing and both strategy families retain the real net. Rate solving, pinning, validation, and external-input classification remain unchanged.

**Tech Stack:** Python 3.14, pytest, OR-Tools CP-SAT, existing shared strip planner and detailed router.

**Spec:** `docs/superpowers/specs/2026-08-28-portable-bands-and-flow-fetch-design.md`

## Global Constraints

- Use the exact 10-line `/home/dannyb/factoriolab_list.csv` export and its line-one provenance URL.
- The candidate remains twenty `reforming-refine` Oil Refineries: gross 15 refined oil/s, recycled 10/s, requested net 5/s.
- A self-consuming product remains an internal routing net; never reclassify it as an external input.
- `_nets_between` is only the packer's distance/separation proxy. Detailed routing keeps the self net.
- Cross-strip producer/consumer edges remain unchanged.
- Do not change rate solving, flow parsing/pinning, `flow.lane_sourced`, or flow cross-check semantics.
- SequencePair deadline behavior remains unchanged.
- Every production change follows red-green TDD.

---

### Task 1: Preserve same-group destinations without self-separation

**Files:**
- Create: `tests/fixtures/flow_refined_oil_self_feedback.csv`
- Modify: `tests/conftest.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py:1534-1547,1989-2000`

**Interfaces:**
- Consumes: `flow_from_text(text, *, url)`, `pin_request()`, `build_candidates(..., flow=selection)`, `_logical_strip_plans(spec)`, `plan_strips(spec, *, strip_len)`, `_nets_between(strips)`, and `generate_strip_families(spec)`.
- Produces: session fixture `refined_oil_feedback_spec: BuildSpec`, same-group entries in `_LogicalStripPlan.out_lanes` and `StripFamily.output_lanes[*].destination_group_keys`; `_nets_between()` still returns only distinct strip pairs.

- [ ] **Step 1: Add the exact captured CSV fixture**

Create `tests/fixtures/flow_refined_oil_self_feedback.csv` with this exact content:

```csv
"https://factoriolab.github.io/dsp/list?z=eJxFxrEKgzAUBdC.yXCnxCpOb7mhuEkVW8hadSgqQqRil.ftYqn0TGcWBlysNbOwRZpZwB3..J8jsb8-kGTnSbjzzdHvX89eaGK.yQ0BHQa8wRK8g4NyBBf4Ar5SX5tpihKUetXKrOLcDk0nJEA_&v=11"
Item,Items,Inputs,Outputs,Targets,Belts,Belt,Recipe,Machines,Machine,Modules,Power
refined-oil,=900,"coal:0.3,hydrogen:1,refined-oil:2/3","refined-oil:1","reforming-refine:2/3",=1.25,conveyor-belt-2,reforming-refine,=20,oil-refinery,"1 ",=19200
hydrogen,=300,,"hydrogen:1","reforming-refine:1",=5/12,conveyor-belt-2,ice-giant-hydrogen,=25/12,orbital-collector,,
coal,=1000,,,"reforming-refine:0.3",=25/18,conveyor-belt-2,,,,
high-purity-silicon,=450,,,,=0.625,conveyor-belt-2,,,,
titanium-ingot,=450,,,,=0.625,conveyor-belt-2,,,,
iron-ingot,=200,,,,=5/18,conveyor-belt-2,,,,
copper-ingot,=2500,,,,=125/36,conveyor-belt-2,,,,
magnet,=100,,,,=5/36,conveyor-belt-2,,,,
```

- [ ] **Step 2: Add one exact pinned-spec fixture and failing logical-plan tests**

In `tests/conftest.py`, add imports for `Path`, `load_vendored`, `flow_from_text`, `pin_request`, `parse_url`, and `build_candidates`, then add:

```python
_REFINED_OIL_FLOW = Path(__file__).parent / "fixtures" / "flow_refined_oil_self_feedback.csv"
_REFINED_OIL_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFxrEKgzAUBdC.yXCnxCpOb7mhuEkVW8hadSgqQqRil.ftYqn0TGcWBlysNbOwRZpZwB3..J8jsb8-kGTnSbjzzdHvX89eaGK.yQ0BHQa8wRK8g4NyBBf4Ar5SX5tpihKUetXKrOLcDk0nJEA_&v=11"
)


@pytest.fixture(scope="session")
def refined_oil_feedback_spec() -> BuildSpec:
    data = load_vendored()
    selection = flow_from_text(_REFINED_OIL_FLOW.read_text(), url=_REFINED_OIL_URL)
    request = pin_request(parse_url(_REFINED_OIL_URL), data, selection)
    (spec,) = build_candidates(data, request, flow=selection).candidates
    assert spec.label == "flow-pinned"
    return spec
```

In `tests/layout/test_freeform.py`, add:

```python
def test_self_consuming_product_keeps_internal_and_boundary_output_lanes(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    (plan,) = _logical_strip_plans(refined_oil_feedback_spec)
    assert ("refined-oil", plan.group_key) in plan.out_lanes
    assert ("refined-oil", "") in plan.out_lanes


def test_packer_proxy_does_not_separate_a_strip_from_itself(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    strips = plan_strips(
        refined_oil_feedback_spec,
        strip_len=refined_oil_feedback_spec.machine_count,
    )
    assert all(left != right for left, right in _nets_between(strips))
```

Before the fix, the first test fails because only the boundary lane exists. After only preserving the destination, the second test fails with `(0, 0)` or another `(i, i)` pair.

In `tests/layout/test_strip_variants.py`, use the session fixture:

```python
def test_sequence_families_keep_same_group_feedback_destination(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    families = generate_strip_families(refined_oil_feedback_spec)
    feedback = [
        lane
        for family in families
        for lane in family.output_lanes
        if lane.items == ("refined-oil",)
        and family.group_key in lane.destination_group_keys
    ]
    assert feedback
```

- [ ] **Step 3: Run the focused tests and verify RED**

```bash
uv run pytest \
  tests/layout/test_freeform.py::test_self_consuming_product_keeps_internal_and_boundary_output_lanes \
  tests/layout/test_freeform.py::test_packer_proxy_does_not_separate_a_strip_from_itself \
  tests/layout/test_strip_variants.py::test_sequence_families_keep_same_group_feedback_destination -q
```

Expected: logical-plan and Sequence family tests fail because the same-group destination is absent.

- [ ] **Step 4: Preserve the physical destination and filter only the packer proxy**

In `_logical_strip_plans`, replace the self-filter with unconditional destination recording:

```python
consumers: dict[tuple[str, str], list[str]] = defaultdict(list)
for key, group in groups.items():
    for item in group.inputs:
        for source in producers.get(item, []):
            consumers[source, item].append(key)
```

In `_nets_between`, exclude only self pairs:

```python
for i, strip in enumerate(strips):
    for _item, destination in strip.out_lanes:
        for group_key in _dests(destination):
            for j in by_group.get(group_key, []):
                if i != j:
                    nets.add((i, j))
```

Do not filter self destinations in `_logical_lanes`, `generate_strip_families`, or `_prepare_routing_problem`.

- [ ] **Step 5: Run focused tests and static checks**

```bash
uv run pytest \
  tests/layout/test_freeform.py::test_self_consuming_product_keeps_internal_and_boundary_output_lanes \
  tests/layout/test_freeform.py::test_packer_proxy_does_not_separate_a_strip_from_itself \
  tests/layout/test_strip_variants.py::test_sequence_families_keep_same_group_feedback_destination -q
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py
uv run mypy src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py
```

Expected: all pass.

- [ ] **Step 6: Commit the logical fix**

```bash
git add src/flab2bp/layout/freeform.py tests/conftest.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/fixtures/flow_refined_oil_self_feedback.csv
git commit -m "Fix self-consuming flow feedback lanes"
```

### Task 2: Prove detailed routing and both strategy surfaces

**Files:**
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Test: existing CLI surface

**Interfaces:**
- Consumes: Task 1's `refined_oil_feedback_spec` fixture, `plan_strips()`, `_box()`, `_greedy_pack()`, `_prepare_routing_problem()`, `_build_prepared()`, `validate.certify()`, `FreeformLayout`, and `SequencePairLayout`.
- Produces: deterministic prepared-routing coverage plus focused strategy coverage for the same pinned spec.

- [ ] **Step 1: Add the deterministic prepared-routing regression**

Add to `tests/layout/test_freeform.py`:

```python
def test_self_consuming_refined_oil_feedback_routes_and_validates(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    strips = plan_strips(
        refined_oil_feedback_spec,
        strip_len=refined_oil_feedback_spec.machine_count,
    )
    height = max(_box(strip)[1] for strip in strips)
    pack = _greedy_pack(strips, height)
    prepared = _prepare_routing_problem(
        refined_oil_feedback_spec,
        strips,
        pack,
        power=False,
    )

    feedback = [
        net
        for net in prepared.nets
        if net.item == "refined-oil"
        and net.src is not None
        and net.net_id.role is not NetRole.EXTERNAL
    ]
    assert feedback

    result = _build_prepared(
        refined_oil_feedback_spec,
        strips,
        prepared,
        power=False,
        route=True,
        budget={"left": 5_000_000},
    )
    assert result.routing.failed_count == 0
    report = validate.certify(
        result.placement,
        refined_oil_feedback_spec,
        expect_power=False,
    )
    assert not [finding for finding in report.errors if finding.check == "flow.lane_sourced"]
    assert report.ok
```

This test is deterministic: the pack is greedy/fixed and the router has a fixed expansion budget rather than a CP-SAT wall clock.

- [ ] **Step 2: Run the deterministic regression**

```bash
uv run pytest tests/layout/test_freeform.py::test_self_consuming_refined_oil_feedback_routes_and_validates -q
```

Expected: PASS after Task 1. Before Task 1 it fails because `prepared.nets` has no internal refined-oil feedback.

- [ ] **Step 3: Add focused strategy contract tests**

In `tests/layout/test_sequence_solver.py`, use the same exact pinned spec and the existing deterministic one-island/worker conventions:

```python
@pytest.mark.slow
def test_sequence_pair_routes_self_consuming_pinned_flow(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    placement = SequencePairLayout(power=False, islands=1).lay_out(
        refined_oil_feedback_spec,
        time_budget_s=15.0,
    )
    assert validate.certify(
        placement,
        refined_oil_feedback_spec,
        expect_power=False,
    ).ok
```

Add the corresponding Freeform contract in `tests/layout/test_freeform.py`:

```python
@pytest.mark.slow
def test_freeform_routes_self_consuming_pinned_flow(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    placement = FreeformLayout(power=False, workers=1).lay_out(
        refined_oil_feedback_spec,
        time_budget_s=15.0,
    )
    assert validate.certify(
        placement,
        refined_oil_feedback_spec,
        expect_power=False,
    ).ok
```

The deterministic prepared-routing test remains the regression authority; these strategy tests prove both public layout adapters retain the shared self net.

- [ ] **Step 4: Run focused strategy tests**

```bash
uv run pytest \
  tests/layout/test_freeform.py::test_freeform_routes_self_consuming_pinned_flow \
  tests/layout/test_sequence_solver.py::test_sequence_pair_routes_self_consuming_pinned_flow -q
```

Expected: both pass at the existing 15-second budget.

- [ ] **Step 5: Exercise the exact CLI file-flow path**

```bash
uv run flab2bp \
  'https://factoriolab.github.io/dsp/list?z=eJxFxrEKgzAUBdC.yXCnxCpOb7mhuEkVW8hadSgqQqRil.ftYqn0TGcWBlysNbOwRZpZwB3..J8jsb8-kGTnSbjzzdHvX89eaGK.yQ0BHQa8wRK8g4NyBBf4Ar5SX5tpihKUetXKrOLcDk0nJEA_&v=11' \
  --flow tests/fixtures/flow_refined_oil_self_feedback.csv \
  --strategy best \
  --budget 15 \
  -o /tmp/refined-oil-self-feedback.txt
```

Expected: exit 0, non-empty blueprint output, no `flow.lane_sourced` refusal. Flow cross-check findings about gross/net/capped CSV rows may remain and must not be suppressed by this fix.

- [ ] **Step 6: Run focused regression/static checks and commit**

```bash
uv run pytest tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/layout/test_sequence_solver.py -q
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/layout/test_sequence_solver.py
git add tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
git commit -m "Test self-consuming flow routing end to end"
```

Do not commit `/tmp/refined-oil-self-feedback.txt`.
