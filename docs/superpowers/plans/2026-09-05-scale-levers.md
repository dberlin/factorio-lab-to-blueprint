# Scale Levers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the six measured Python hotspots of a 30 s layout attempt without changing any layout, and fix the output-lane capacity defect that crashes `universe-matrix` above 60/min.

**Architecture:** Every throughput task is an exact rewrite of one function or call site (algorithm swap, memo, container clone, NumPy scatter, or a Cython kernel with a Python fallback) proven identical by unit tests and, for the kernel, a randomized parity test. The two defect tasks change one verdict (`_merge_lanes` judges a merged output lane by the shard's supply) and one exception boundary (`generate_strip_families` refuses with `NoValidLayout` instead of leaking `ValueError`). A three-round corpus gate against a same-day master baseline closes the branch.

**Tech Stack:** Python 3.14, `uv`, pytest, NumPy, Cython 3.1.3 via `setup.py` (`uv run python setup.py build_ext --inplace`), OR-Tools CP-SAT (untouched).

**Spec:** `docs/superpowers/specs/2026-09-05-scale-levers-design.md` (design), with the measurements in `docs/superpowers/evidence/2026-09-05-scale-profile/README.md`.

## Global Constraints

- **Exactness.** Tasks 1, 4, 5, 6, 7, 8 must not change any layout: same paths, same placements, same refusals. A test that compares the new code path with the old one on the same inputs is required in each of those tasks. Tasks 2 and 3 are the only behavior changes and are confined to `generate_strip_families` and `_merge_lanes` / `_logical_strip_plans`.
- **Code navigation.** Use Serena's symbolic tools (`activate_project` on the worktree path, then `get_symbols_overview`, `find_symbol` with `include_body=True`, `find_referencing_symbols` for every call site you touch). grep is for keyword discovery only. If a Serena tool fails, fall back to the LSP tools or Read. Only one implementer runs at a time, so Serena edits are safe here.
- **Tests.** `uv run pytest -q <files>` for the covering files, then `uv run pytest -q` for the whole suite before the task's final commit. The harness does not print pytest's summary line: judge by exit code (`echo $?` right after) and by the absence of `F`/`E` markers. pytest-timeout hard-kills a test at 120 s; a refusal test must pass `candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,)` so it lays out one candidate.
- **Lint and types.** `uv run ruff check src tests scripts` and `uv run ruff format --check src tests scripts` clean; `uv run mypy src` must report no more findings than master (record the master count first: `git stash` is forbidden, so run mypy on `git show master:...` is not possible; instead run it once on the worktree before your first edit and once after, and the count must not rise).
- **Kernels.** The Cython extensions are not tracked; build them in the worktree with `uv run python setup.py build_ext --inplace` and confirm `uv run python -c "from flab2bp.layout import route_kernel; print(route_kernel.selected_backend())"` prints `cython` before running the suite.
- **Commit discipline.** Explicit paths only (`git add <files>`); imperative sentence-case subject with the conventional prefix used in this repo (`perf:`, `fix:`, `test:`, `docs:`, `evidence:`); no blanket adds, stashes, resets, amends of pushed commits, or unrelated cleanup. Never commit anything under `.superpowers/`.
- **Timing evidence.** Before each timed run record `uptime` and `vmstat 1 3` next to the numbers. Delete a JSONL target before `scripts/audit.py`, which appends.
- **Evidence directory:** `docs/superpowers/evidence/2026-09-05-scale-levers/` (the master baseline rounds are already there: `baseline-round{1,2,3}.jsonl`, `baseline-commit.txt`).
- **Constants to use verbatim.** Belt ids: `catalog.BELT_IDS = range(2001, 2010)`; a plain Mk.I belt for tests is `item_id=2001, model_index=35`. Splitter: `catalog.SPLITTER_ID` (2020). Belt climb per tile: `catalog.BELT_CLIMB_PER_TILE = Fraction(1, 2)`. Level height: `freeform._LEVEL_HEIGHT`. Geometry kernel env override: `FLAB2BP_GEOMETRY_KERNEL` with values `python` or `cython`, mirroring `FLAB2BP_ROUTE_KERNEL`.

---

## File map

| File | Responsibility in this plan |
|---|---|
| `src/flab2bp/layout/freeform.py` | Tasks 1, 3, 4, 5, 6, 7: `_committed_path_closes_cycle`, `_merge_lanes`, `_altitude_profile`, `_Canvas.clone`, `commit_once`, `_power_plan`, `_projected_power_peer_possible`, `_direct_origin_deltas` memo |
| `src/flab2bp/layout/strip_variants.py` | Tasks 2, 3: `generate_strip_families` boundary, `_logical_strip_plans` supply |
| `src/flab2bp/layout/sequence_solver.py` | Task 7: `_refinement_direct_targets` memo |
| `src/flab2bp/dsp/colliders.py`, `src/flab2bp/dsp/planet.py` | Task 8: kernel wiring |
| `src/flab2bp/dsp/_geometry_kernel.pyx`, `_geometry_kernel.pyi`, `geometry_kernel.py` | Task 8: new kernel and backend selector |
| `setup.py` | Task 8: third extension |
| `tests/layout/test_freeform.py`, `tests/layout/test_strip_variants.py`, `tests/layout/test_sequence_solver.py`, `tests/dsp/test_colliders.py`, `tests/dsp/test_planet.py`, `tests/test_pipeline.py` | Tests beside the code they cover |
| `docs/superpowers/evidence/2026-09-05-scale-levers/` | Task 9: gate rounds, compare output, re-profile, `gate.md` |

---

### Task 1: One SCC pass for the committed-path cycle check

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_committed_path_closes_cycle`, currently ~lines 11797-11809; `_leads_back` and `_splitter_successors` stay as they are)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform._Canvas`, `freeform._splitter_successors(canvas) -> dict[int, tuple[int, ...]]`, `freeform._leads_back(canvas, start, own, splitter_successors)`.
- Produces: `_committed_path_closes_cycle(canvas, indices, splitter_successors=None) -> bool` with the same signature and the same truth table as today.

Semantics to preserve exactly: today the function returns `any(_leads_back(canvas, canvas.buildings[i].output_obj, {i}, succ) for i in indices if output_obj is not None)`. `_leads_back` walks from a start node: a node in `own` returns `True`; a node already seen or out of `range(len(canvas.buildings))` is skipped; a splitter continues to `splitter_successors.get(i, ())`; a belt (`catalog.is_belt(item_id)`) with `output_obj is not None` continues to that; anything else stops. So the answer is "does some index in `indices` lie on a directed cycle of the graph whose edges are splitter -> branches and belt -> output_obj". A node lies on a cycle iff its strongly connected component has more than one member or it has an edge to itself.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_freeform.py` (near the existing `_belt` helper at ~line 10392, which builds `PlacedBuilding(item_id=2001, model_index=35, x=x, y=y, width=1, height=1, carries_item=item)`):

```python
def _linked_belt(x: int, output_obj: int | None) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=2001, model_index=35, x=x, y=0, width=1, height=1, output_obj=output_obj
    )


def _splitter_at(x: int) -> PlacedBuilding:
    return PlacedBuilding(item_id=catalog.SPLITTER_ID, model_index=38, x=x, y=0, width=2, height=2)


class TestCommittedPathClosesCycle:
    """`_committed_path_closes_cycle` answers "is any committed belt on a loop"."""

    def _reference(self, canvas: _Canvas, indices: list[int]) -> bool:
        successors = freeform._splitter_successors(canvas)
        return any(
            (onward := canvas.buildings[index].output_obj) is not None
            and freeform._leads_back(canvas, onward, {index}, successors)
            for index in indices
        )

    def test_a_straight_chain_is_not_a_cycle(self) -> None:
        canvas = _Canvas(buildings=[_linked_belt(0, 1), _linked_belt(1, 2), _linked_belt(2, None)])
        assert freeform._committed_path_closes_cycle(canvas, [0, 1, 2]) is False

    def test_a_chain_whose_tail_feeds_its_head_is_a_cycle(self) -> None:
        canvas = _Canvas(buildings=[_linked_belt(0, 1), _linked_belt(1, 2), _linked_belt(2, 0)])
        assert freeform._committed_path_closes_cycle(canvas, [1]) is True

    def test_a_cycle_elsewhere_does_not_condemn_a_belt_off_it(self) -> None:
        # 0 -> 1 -> 2 -> 1 loops; belt 0 merely feeds the loop and is not on it.
        canvas = _Canvas(buildings=[_linked_belt(0, 1), _linked_belt(1, 2), _linked_belt(2, 1)])
        assert freeform._committed_path_closes_cycle(canvas, [0]) is False
        assert freeform._committed_path_closes_cycle(canvas, [2]) is True

    def test_a_self_loop_is_a_cycle(self) -> None:
        canvas = _Canvas(buildings=[_linked_belt(0, 0)])
        assert freeform._committed_path_closes_cycle(canvas, [0]) is True

    def test_a_dangling_output_index_is_not_followed(self) -> None:
        canvas = _Canvas(buildings=[_linked_belt(0, 7)])
        assert freeform._committed_path_closes_cycle(canvas, [0]) is False

    def test_splitter_branches_are_followed(self) -> None:
        # belt 0 -> splitter 1 -> belts 2 and 3 (input_obj=1); belt 3 -> belt 0.
        canvas = _Canvas(
            buildings=[
                _linked_belt(0, 1),
                _splitter_at(1),
                replace(_linked_belt(2, None), input_obj=1),
                replace(_linked_belt(3, 0), input_obj=1),
            ]
        )
        assert freeform._committed_path_closes_cycle(canvas, [0]) is True
        assert freeform._committed_path_closes_cycle(canvas, [2]) is False

    def test_agrees_with_the_per_index_walk_on_random_belt_graphs(self) -> None:
        rng = random.Random(20260905)
        for _trial in range(300):
            n = rng.randint(1, 12)
            buildings = []
            for i in range(n):
                if rng.random() < 0.15:
                    buildings.append(_splitter_at(i))
                else:
                    out = rng.choice([None, *range(-1, n + 1)])
                    buildings.append(_linked_belt(i, out))
            for i, b in enumerate(buildings):
                if catalog.is_belt(b.item_id) and rng.random() < 0.3:
                    buildings[i] = replace(b, input_obj=rng.randrange(n))
            canvas = _Canvas(buildings=buildings)
            indices = [i for i in range(n) if catalog.is_belt(buildings[i].item_id) and rng.random() < 0.6]
            assert freeform._committed_path_closes_cycle(canvas, indices) == self._reference(
                canvas, indices
            ), (buildings, indices)
```

Add `import random` and `from dataclasses import replace` to the test module imports if they are not already there (check the top of the file first).

- [ ] **Step 2: Run the tests to verify they fail or pass against the old code**

Run: `uv run pytest -q tests/layout/test_freeform.py -k TestCommittedPathClosesCycle`
Expected: all PASS against the current implementation (they pin behavior). If any fails, the test is wrong, not the code: fix the test until it passes on the untouched function, because it is the reference the rewrite must match.

- [ ] **Step 3: Replace the implementation**

Replace the body of `_committed_path_closes_cycle` with an iterative Tarjan pass restricted to nodes reachable from `indices`:

```python
def _committed_path_closes_cycle(
    canvas: _Canvas,
    indices: Sequence[int],
    splitter_successors: Mapping[int, Sequence[int]] | None = None,
) -> bool:
    """Whether flow from any committed belt can return to that same belt.

    A belt is on a loop iff it sits in a strongly connected component with
    more than one member, or feeds itself.  One Tarjan pass over the part of
    the belt graph reachable from ``indices`` answers that for every index at
    once; the per-index walk it replaces re-traversed the same graph once per
    committed cell (30k walks and 3.4M visits on ``universe-matrix``) and was
    the largest single cost of ``_commit_paths``.  Edges are the same ones
    ``_leads_back`` follows: a Splitter to each branch fed from it, a belt to
    its ``output_obj``; anything else has no successors.
    """
    if splitter_successors is None:
        splitter_successors = _splitter_successors(canvas)
    buildings = canvas.buildings
    n = len(buildings)
    wanted = {i for i in indices if 0 <= i < n}
    if not wanted:
        return False

    def successors(i: int) -> tuple[int, ...]:
        b = buildings[i]
        if b.item_id == catalog.SPLITTER_ID:
            return tuple(splitter_successors.get(i, ()))
        if catalog.is_belt(b.item_id) and b.output_obj is not None:
            return (b.output_obj,)
        return ()

    order = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack: list[int] = []
    counter = 0
    for root in wanted:
        if order[root] != -1:
            continue
        order[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        work = [(root, iter(successors(root)))]
        while work:
            v, it = work[-1]
            descended = False
            for w in it:
                if not 0 <= w < n:
                    continue
                if order[w] == -1:
                    order[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack[w] = True
                    work.append((w, iter(successors(w))))
                    descended = True
                    break
                if on_stack[w] and order[w] < low[v]:
                    low[v] = order[w]
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                if low[v] < low[parent]:
                    low[parent] = low[v]
            if low[v] == order[v]:
                component = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    component.append(w)
                    if w == v:
                        break
                if len(component) > 1:
                    if any(c in wanted for c in component):
                        return True
                elif component[0] in wanted and component[0] in successors(component[0]):
                    return True
    return False
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/layout/test_freeform.py -k "TestCommittedPathClosesCycle or commit or acyclic"`
Expected: PASS, exit code 0.

- [ ] **Step 5: Measure**

Run: `uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py universe-matrix --rate 60 --strategy freeform --out /tmp/scale-levers-task1-um60` and read `commit_paths` from the JSON (`python -c "import json;r=json.load(open('/tmp/scale-levers-task1-um60.json'));print(r['phases'].get('commit_paths'))"`). Expected: `commit_paths` total under 3 s (it was 5.5-6.4 s). Put the number in your report.

- [ ] **Step 6: Run the whole suite, lint, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): decide committed-path cycles with one SCC pass"
```

---

### Task 2: Strip planning refuses instead of crashing

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py` (`generate_strip_families`, ~lines 1682-1753)
- Test: `tests/layout/test_strip_variants.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `flab2bp.layout.base.NoValidLayout` (already imported in `strip_variants.py`); `_machine_cap`'s existing `raise NoValidLayout(<reason>, spec_label=spec.label, budget_s=0.0, ...)` call, whose exact keyword set you copy.
- Produces: `generate_strip_families(spec, *, prefer_shared_proliferation=False)` raises `NoValidLayout` whose reason starts with `"the spec cannot be planned into strips: "` followed by the inner message, whenever `_logical_strip_plans` raises `ValueError` or `KeyError`. `ValueError` remains the internal contract of `_logical_strip_plans` and `_merge_lanes`.

- [ ] **Step 1: Write the failing tests**

In `tests/layout/test_strip_variants.py`, next to `test_a_single_machine_over_the_ceiling_is_refused_early_with_the_rate` (~line 133):

```python
def test_an_unplannable_shard_is_a_refusal_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_logical_strip_plans` speaks ValueError; every caller of
    `generate_strip_families` speaks NoValidLayout.  The boundary is here."""

    def unplannable(*_args: object, **_kwargs: object) -> tuple[()]:
        raise ValueError("hydrogen: destinations ['a', 'b'] have to share one output lane")

    monkeypatch.setattr(strip_variants, "_logical_strip_plans", unplannable)
    with pytest.raises(NoValidLayout, match=r"cannot be planned into strips.*hydrogen") as caught:
        generate_strip_families(_rated_spec(Fraction(4)))
    assert caught.value.spec_label == _rated_spec(Fraction(4)).label
    assert isinstance(caught.value.__cause__, ValueError)
```

Import `strip_variants` as a module (`from flab2bp.layout import strip_variants`) if the test file only imports names from it; the monkeypatch must target the module attribute `generate_strip_families` reads.

In `tests/test_pipeline.py`, beside the `DEUTERON_URL` tests (~line 1044), a real-corpus regression that today crashes (it becomes a refusal in this task and a clean plan in Task 3; write it so it passes in both states):

```python
UNIVERSE_MATRIX_90_URL = (
    "https://factoriolab.github.io/dsp/list?o=universe-matrix*90&ibe=conveyor-belt-3"
    "&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11"
)


def test_universe_matrix_at_90_per_minute_never_crashes_strip_planning() -> None:
    """Until 2026-09-05 this URL escaped both strategies as a ValueError from
    `_logical_strip_plans`; a plan that cannot be made is a refusal."""
    spec = build_candidates(
        load_vendored(),
        parse_url(UNIVERSE_MATRIX_90_URL),
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    ).candidates[0]
    try:
        families = generate_strip_families(spec)
    except NoValidLayout as refusal:
        assert "cannot be planned into strips" in refusal.reason
    else:
        assert len(families) >= 40
```

Add the imports the test needs (`build_candidates`, `load_vendored`, `parse_url`, `CandidatePolicy`, `generate_strip_families`, `NoValidLayout`); check which are already imported at the top of `tests/test_pipeline.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/layout/test_strip_variants.py -k unplannable tests/test_pipeline.py -k universe_matrix_at_90`
Expected: both FAIL (a raw `ValueError` escapes).

- [ ] **Step 3: Implement the boundary**

In `generate_strip_families`, replace the direct iteration over `_logical_strip_plans(...)` with:

```python
    try:
        plans = tuple(
            _logical_strip_plans(
                spec,
                prefer_shared_proliferation=prefer_shared_proliferation,
            )
        )
    except (ValueError, KeyError) as exc:
        # `_logical_strip_plans` and `_merge_lanes` speak ValueError to each
        # other; every caller of this function -- both strategies, the race
        # and the pipeline -- catches only NoValidLayout, so a plan that
        # cannot be made used to escape as a CRASH.  Same seam and same
        # shape as `_machine_cap`'s early refusal below.
        raise NoValidLayout(
            f"the spec cannot be planned into strips: {exc}",
            spec_label=spec.label,
            budget_s=0.0,
        ) from exc
    for plan in plans:
        ...
```

Match `_machine_cap`'s exact `NoValidLayout(...)` keyword set (open its body with Serena; if it passes more keywords than `spec_label` and `budget_s`, pass the same ones with the same empty values).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/layout/test_strip_variants.py tests/test_pipeline.py -k "unplannable or universe_matrix_at_90 or machine_cap or ceiling"`
Expected: PASS.

- [ ] **Step 5: Whole suite, lint, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
git add src/flab2bp/layout/strip_variants.py tests/layout/test_strip_variants.py tests/test_pipeline.py
git commit -m "fix(layout): refuse an unplannable strip shard instead of crashing"
```

---

### Task 3: Judge a merged output lane by what the shard supplies

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_merge_lanes`, ~lines 1745-1838), `src/flab2bp/layout/strip_variants.py` (`_logical_strip_plans`, the `_merge_lanes` call ~lines 1300-1317)
- Test: `tests/layout/test_freeform.py` (`TestOneLaneCanServeSeveralDestinations`, ~line 11340), `tests/layout/test_strip_variants.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `_merge_lanes(shard, reach, demand, capacity, stacks=None)`; `_logical_strip_plans`'s locals `shards`, `demand`, `per_shard`, `group` (a `freeform._Group` with `.count`, `.inputs`, `.outputs` mappings of `Fraction` per machine; confirm the field name of the per-machine outputs with Serena on `_Group` before using it).
- Produces: `_merge_lanes(shard, reach, demand, capacity, stacks=None, *, supply: Mapping[str, Fraction] | None = None)`. With `supply` given, the over-capacity verdict on a lane for `item` compares `min(loads[b], supply[item])` (falling back to `loads[b]` when `item` is absent from `supply`) against `lane_capacity`. Packing order and the geometry refusal are unchanged. `_logical_strip_plans` passes, for shard `i`, `supply={item: per_shard[i] * <group per-machine outputs>[item] for each product item in shard i}`.

- [ ] **Step 1: Write the failing tests**

In `tests/layout/test_freeform.py`, inside `TestOneLaneCanServeSeveralDestinations`:

```python
    def test_a_merged_lane_is_judged_by_what_the_shard_supplies(self) -> None:
        """Two consumers drawing 18/s and 15/s of hydrogen from a producer that
        emits 1.5/s share one lane: the bus feeds the rest.  Without a supply
        figure the old draw-based verdict stands, so callers that do not know
        their supply plan exactly as before."""
        shard = [
            ("hydrogen", "casimir-crystal#1", CargoDomain.UNSPRAYED),
            ("hydrogen", "deuterium#6", CargoDomain.UNSPRAYED),
            ("antimatter", "universe-matrix#37", CargoDomain.UNSPRAYED),
        ]
        demand = {
            ("hydrogen", "casimir-crystal#1", CargoDomain.UNSPRAYED): F(18),
            ("hydrogen", "deuterium#6", CargoDomain.UNSPRAYED): F(15),
            ("antimatter", "universe-matrix#37", CargoDomain.UNSPRAYED): F(1),
        }
        lanes = _merge_lanes(shard, 2, demand, F(30), supply={"hydrogen": F(3, 2), "antimatter": F(1)})
        hydrogen = [dest for item, dest, _domain in lanes if item == "hydrogen"]
        assert hydrogen == ["casimir-crystal#1|deuterium#6"]
        with pytest.raises(ValueError, match=r"33.*over the 30"):
            _merge_lanes(shard, 2, demand, F(30))
        with pytest.raises(ValueError, match=r"33.*over the 30"):
            _merge_lanes(shard, 2, demand, F(30), supply={"hydrogen": F(60)})
```

Check the module's existing alias for `Fraction` in that test file (`F`) and the `_dests`/`DEST_SEP` convention (`"|"`) already used by its neighbours.

In `tests/layout/test_strip_variants.py`, a both-fed fixture built with the file's spec helpers (read `_rated_spec` and `_single_machine_spec` at lines ~64-110 and build a `BuildSpec` the same way, with `MachineGroup`s for these four recipes; keep item and machine ids valid for the vendored catalog by copying the `machine=` and `item_id`/`model_index` conventions those helpers use):

```python
def test_a_both_fed_product_whose_consumers_draw_more_than_a_belt_still_plans() -> None:
    """mass-energy-storage: 2 machines emit 0.75/s hydrogen each into three
    consumers whose combined draw (18 + 15 + 3 = 36/s) is served mostly by a
    33/s bus entry.  The producer's shared hydrogen lane carries 1.5/s and
    must plan; before 2026-09-05 it was refused for "carrying" 33/s."""
    spec = _both_fed_hydrogen_spec()  # helper you write beside `_rated_spec`
    families = generate_strip_families(spec)
    mes = [family for family in families if family.recipe_id == "mass-energy-storage"]
    assert mes, [family.recipe_id for family in families]
    hydrogen_lanes = [
        lane
        for family in mes
        for lane in family.output_lanes
        if lane.items == ("hydrogen",)
    ]
    assert hydrogen_lanes
    destinations = {
        key for lane in hydrogen_lanes for key in lane.destination_group_keys
    }
    assert {"casimir-crystal#1", "deuterium#6"} <= destinations
```

The helper `_both_fed_hydrogen_spec()` builds: `mass-energy-storage` count 2, `outputs_per_machine={"hydrogen": Fraction(3, 4), "antimatter": Fraction(3, 4)}`, `inputs_per_machine={"critical-photon": Fraction(3, 4)}`; `casimir-crystal#1` count 4, `inputs_per_machine={"hydrogen": Fraction(9, 2), ...}`; `deuterium#6` count 4, `inputs_per_machine={"hydrogen": Fraction(15, 4)}`; `energy-matrix#12` count 1, `inputs_per_machine={"hydrogen": Fraction(3)}`; `external_inputs={"hydrogen": Fraction(33), "critical-photon": Fraction(3, 2), ...}`; `belt_item_id="conveyor-belt-3"`, `belt_items_per_second=Fraction(30)`. Use whatever other required `BuildSpec`/`MachineGroup` fields the existing helpers fill (recipe ids, item ids, model indices, `outputs`). If the spec model rejects an unbalanced flow, balance it minimally and note the balancing in the docstring; the assertion that matters is that the MES hydrogen lane plans with both destinations.

Also tighten the Task 2 pipeline test so it now asserts the clean branch: in `tests/test_pipeline.py::test_universe_matrix_at_90_per_minute_never_crashes_strip_planning`, replace the `try/except/else` with:

```python
    families = generate_strip_families(spec)
    mes = [family for family in families if family.recipe_id == "mass-energy-storage"]
    assert len(families) >= 40 and len(mes) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/layout/test_freeform.py -k judged_by_what_the_shard_supplies tests/layout/test_strip_variants.py -k both_fed tests/test_pipeline.py -k universe_matrix_at_90`
Expected: FAIL (`_merge_lanes` has no `supply` keyword; the both-fed and *90 specs refuse).

- [ ] **Step 3: Implement**

In `_merge_lanes`, add the keyword and change the verdict (keep the packing loop as it is):

```python
def _merge_lanes(
    shard: Sequence[_CargoSink],
    reach: int,
    demand: Mapping[_CargoSink, Fraction],
    capacity: Fraction,
    stacks: Mapping[str, int] | None = None,
    *,
    supply: Mapping[str, Fraction] | None = None,
) -> list[_CargoSink]:
```

Extend the docstring with one paragraph: ``supply`` is items/s of each product the shard's own machines emit.  A lane cannot carry more than its producer puts on it, whatever its consumers draw -- a both-fed item's consumers are served mostly by the bus -- so the over-capacity verdict is taken on ``min(draw, supply)``.  Draw still decides which destinations share a lane.  Without ``supply`` the verdict is the draw, exactly as before.

Then in the verdict loop:

```python
        for b, group in enumerate(bins):
            if not group:
                continue
            carried = loads[b]
            if supply is not None and item in supply and supply[item] < carried:
                carried = supply[item]
            if carried > lane_capacity:
                raise ValueError(
                    f"{item}: destinations {sorted(group)} have to share one "
                    f"output lane carrying {carried} items/s, over the "
                    f"{lane_capacity}/s the belt sustains"
                )
            out.append((item, DEST_SEP.join(sorted(group)), cargo_domain))
```

In `strip_variants._logical_strip_plans`, pass the shard's supply. `per_shard` is a list aligned with `shards`; use `enumerate(shards)` and pass `supply={item: per_shard[index] * outputs[item] for item in {item for item, _dest, _domain in shard}}` where `outputs` is the group's per-machine outputs mapping (confirm the attribute on `_Group` with Serena; `_sink_demand` reads `dest.inputs`, so the outputs twin is the mapping to use; fall back to `Fraction(0)` for an item the group does not list).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/layout/test_freeform.py -k "TestOneLaneCanServeSeveralDestinations" tests/layout/test_strip_variants.py tests/test_pipeline.py -k "universe_matrix_at_90 or both_fed or deuteron or mk3 or mk2"`
Expected: PASS, including the pre-existing `test_a_merged_lane_over_belt_capacity_is_refused`.

- [ ] **Step 5: Confirm the scale-ups lay out**

Run (each takes about 35 s):

```bash
uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py universe-matrix --rate 90 --strategy freeform --out /tmp/scale-levers-um90-ff
uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py universe-matrix --rate 120 --strategy sequence-pair --out /tmp/scale-levers-um120-sp
```

Expected: both print a JSON line with a verdict of `OK` or `REFUSED: ...`, never a traceback. Put both verdicts in your report.

- [ ] **Step 6: Whole suite, lint, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/strip_variants.py tests/layout/test_freeform.py tests/layout/test_strip_variants.py tests/test_pipeline.py
git commit -m "fix(layout): judge a merged output lane by the shard's supply"
```

---

### Task 4: Cache the altitude profile per path

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_altitude_profile`, ~lines 6706-6787)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: `_altitude_profile(path, *, ramped) -> list[Fraction] | None` unchanged in signature and values; a new module-level `_altitude_profile_cached(path: tuple[Cell, ...], ramped: bool) -> tuple[Fraction, ...] | None` decorated with `functools.lru_cache(maxsize=16384)` holds the existing body and returns a tuple. `_altitude_profile` converts its argument with `tuple(path)`, calls the cached function and returns `None` or `list(result)`, so every caller still gets its own list.

- [ ] **Step 1: Write the failing tests**

```python
class TestAltitudeProfileCache:
    def test_ramped_profile_puts_the_half_level_on_the_via_cell(self) -> None:
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1), (4, 0, 0)]
        unit = freeform._LEVEL_HEIGHT
        assert freeform._altitude_profile(path, ramped=True) == [
            0 * unit,
            0 * unit + catalog.BELT_CLIMB_PER_TILE,
            1 * unit,
            1 * unit - catalog.BELT_CLIMB_PER_TILE,
            0 * unit,
        ]

    def test_consecutive_ramps_have_no_profile(self) -> None:
        assert freeform._altitude_profile([(0, 0, 0), (1, 0, 1), (2, 0, 2)], ramped=True) is None

    def test_unramped_profile_steps_whole_levels(self) -> None:
        unit = freeform._LEVEL_HEIGHT
        assert freeform._altitude_profile([(0, 0, 0), (1, 0, 1)], ramped=False) == [0, unit]

    def test_callers_get_a_fresh_list_each_time(self) -> None:
        path = ((0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1))
        first = freeform._altitude_profile(path, ramped=True)
        second = freeform._altitude_profile(list(path), ramped=True)
        assert first == second and first is not second
        first.append(Fraction(99))
        assert freeform._altitude_profile(path, ramped=True) == second
```

- [ ] **Step 2: Run them against the current code**

Run: `uv run pytest -q tests/layout/test_freeform.py -k TestAltitudeProfileCache`
Expected: PASS on the untouched function (they pin values). If `test_ramped_profile...` fails, re-derive the expected values from the function's docstring table rather than from this plan, and fix the test.

- [ ] **Step 3: Implement the cache**

Rename the existing function body to `_altitude_profile_cached(path: tuple[Cell, ...], ramped: bool) -> tuple[Fraction, ...] | None`, decorated `@lru_cache(maxsize=16384)`, returning `tuple(out)` (and `tuple(lvl * _LEVEL_HEIGHT for lvl in levels)` on the unramped branch). Keep the docstring on the public wrapper:

```python
def _altitude_profile(
    path: Sequence[tuple[int, int, int]], *, ramped: bool
) -> list[Fraction] | None:
    <existing docstring>
    profile = _altitude_profile_cached(tuple(path), ramped)
    return None if profile is None else list(profile)
```

Add `from functools import lru_cache` if not imported. The `AssertionError` branches stay inside the cached function; `lru_cache` does not cache raised exceptions, so their behavior is unchanged.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/layout/test_freeform.py -k "TestAltitudeProfileCache or altitude or merge_frontier or ramp"`
Expected: PASS.

- [ ] **Step 5: Whole suite, lint, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): cache the altitude profile per routed path"
```

---

### Task 5: Clone the canvas instead of deep-copying it

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_Canvas`, ~lines 5001-5242; `commit_once` inside `_route_all`, ~line 10613)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: `_Canvas.clone(self) -> _Canvas`: a new canvas whose every `dataclasses.fields(_Canvas)` value equals the original's, whose mutable containers (`buildings` list, `blocked`/`reserved`/`port_corridors`/`belt_ban` dicts, `world_taken`/`solid`/`keep_out`/`guard`/`junction_ban` sets, and each inner set of `belt_ban`) are fresh objects, and whose immutable values (`ramped`, `sorter_tiers`, `sorter_stacks`, `lane_stacks`, `routing_ports`, `limit`, `junction_geometry_prepared`, every `PlacedBuilding`, every `PortAccessCorridor` tuple) are shared. `commit_once` calls `canvas.clone()` where it called `deepcopy(canvas)`.

- [ ] **Step 1: Write the failing tests**

```python
class TestCanvasClone:
    def _populated(self) -> _Canvas:
        canvas = _Canvas(ramped=True, limit=(0, 0, 9, 9))
        canvas.buildings.append(_linked_belt(0, None))
        canvas.blocked[(1, 1, 0)] = 0
        canvas.world_taken.add((1, 1, Fraction(0)))
        canvas.solid.add((2, 2))
        canvas.reserved[(3, 3, 0)] = (3, 3, 0)
        canvas.keep_out.add((4, 4))
        canvas.guard.add((5, 5, 0))
        canvas.belt_ban[(6, 6)] = {1}
        canvas.junction_ban.add((7, 7, 0))
        return canvas

    def test_clone_equals_the_original_field_for_field(self) -> None:
        original = self._populated()
        clone = original.clone()
        for f in fields(_Canvas):
            assert getattr(clone, f.name) == getattr(original, f.name), f.name

    def test_clone_matches_deepcopy(self) -> None:
        original = self._populated()
        assert original.clone() == deepcopy(original)

    def test_mutating_the_clone_leaves_the_original_alone(self) -> None:
        original = self._populated()
        clone = original.clone()
        clone.buildings.append(_linked_belt(1, None))
        clone.blocked[(8, 8, 0)] = 1
        clone.world_taken.add((8, 8, Fraction(0)))
        clone.solid.add((8, 8))
        clone.reserved[(8, 8, 0)] = (8, 8, 0)
        clone.keep_out.add((8, 8))
        clone.guard.add((8, 8, 0))
        clone.belt_ban[(6, 6)].add(2)
        clone.belt_ban[(8, 8)] = {0}
        clone.junction_ban.add((8, 8, 0))
        reference = self._populated()
        for f in fields(_Canvas):
            assert getattr(original, f.name) == getattr(reference, f.name), f.name
```

Add `from dataclasses import fields` and `from copy import deepcopy` to the test imports as needed. The `_linked_belt` helper is from Task 1.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/layout/test_freeform.py -k TestCanvasClone`
Expected: FAIL with `AttributeError: '_Canvas' object has no attribute 'clone'`.

- [ ] **Step 3: Implement**

Add to `_Canvas` after `free_owned_guard`:

```python
    def clone(self) -> _Canvas:
        """A disposable copy for proving a commit without touching this canvas.

        ``deepcopy`` used to do this and was 0.7-1.2 s of every attempt: it
        re-created every frozen ``PlacedBuilding`` (800k ``deepcopy`` calls on
        ``universe-matrix``) although nothing ever mutates one -- links are
        re-pointed with ``replace``.  Only the containers need to be fresh.
        ``belt_ban`` holds mutable sets, so those are copied one level down;
        every other value is immutable and shared.  Listing every field by
        name is deliberate: a field added without a line here fails
        ``test_clone_equals_the_original_field_for_field``.
        """
        return _Canvas(
            ramped=self.ramped,
            sorter_tiers=self.sorter_tiers,
            sorter_stacks=self.sorter_stacks,
            lane_stacks=self.lane_stacks,
            buildings=list(self.buildings),
            blocked=dict(self.blocked),
            world_taken=set(self.world_taken),
            solid=set(self.solid),
            reserved=dict(self.reserved),
            routing_ports=self.routing_ports,
            port_corridors=dict(self.port_corridors),
            limit=self.limit,
            keep_out=set(self.keep_out),
            guard=set(self.guard),
            belt_ban={column: set(levels) for column, levels in self.belt_ban.items()},
            junction_ban=set(self.junction_ban),
            junction_geometry_prepared=self.junction_geometry_prepared,
        )
```

Before writing it, list the class's fields with Serena (`find_symbol` `_Canvas` with `depth=1`) and make sure every field appears; if a field exists that is not in the list above, add it with the same copy rule (fresh container if mutable, shared if immutable) and mention it in your report.

Then in `commit_once` replace `deepcopy(canvas)` with `canvas.clone()`. Search the module for other `deepcopy(canvas` calls with Serena's `find_referencing_symbols` on `deepcopy` or a grep; do not change them, list them in the report.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/layout/test_freeform.py -k "TestCanvasClone or commit or route_all"`
Expected: PASS.

- [ ] **Step 5: Whole suite, lint, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): clone the routing canvas for commit proofs"
```

---

### Task 6: Cheaper power plan without changing a tower

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_power_plan`, ~lines 14016-14560: the free-mask loop ~14119-14132, `power_nodes` at ~14224/14234 and ~14537, the peer filter ~14453-14462; `_projected_power_peer_possible`, ~lines 12793-12846)
- Test: `tests/layout/test_freeform.py` (existing `_power_plan` tests at ~11514-12127 and `_projected_power_peer_possible` tests at ~11672-11686 are the pinned behavior; add the two below)

**Interfaces:**
- Produces: `_projected_power_peer_possible(candidate, peer, projection_contexts, *, cancelled=None, candidate_centre=None, peer_centre=None) -> bool`. When a centre is given it is used instead of recomputing `codec.tile_to_local_offset(...)` for that side; results are identical. `_power_plan` returns the same site list as before for every input.

- [ ] **Step 1: Write the failing tests**

```python
class TestPowerPlanIsExact:
    def test_peer_possible_accepts_precomputed_centres(self) -> None:
        candidate, peer, contexts = _two_power_nodes()  # build with the fixtures the tests at ~11672 use
        def centre(b: PlacedBuilding) -> tuple[float, float, float]:
            return codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height)
        assert freeform._projected_power_peer_possible(
            candidate, peer, contexts,
            candidate_centre=centre(candidate[1]), peer_centre=centre(peer[1]),
        ) == freeform._projected_power_peer_possible(candidate, peer, contexts)

    def test_blocked_column_shortcut_matches_the_per_level_probe(self) -> None:
        canvas = _Canvas(limit=(0, 0, 9, 9))
        canvas.blocked[(2, 3, 1)] = 0   # blocked only at level 1
        canvas.blocked[(4, 4, 0)] = 0
        blocked_columns = {(x, y) for (x, y, _level) in canvas.blocked}
        for x in range(10):
            for y in range(10):
                assert ((x, y) in blocked_columns) == any(
                    (x, y, level) in canvas.blocked for level in range(freeform.LEVELS)
                )
```

For `_two_power_nodes()`, read the existing test at ~line 11672 (`assert freeform._projected_power_peer_possible(`) and factor its inputs into a helper you can call from both places; keep the existing test passing.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/layout/test_freeform.py -k TestPowerPlanIsExact`
Expected: the first FAILs with `TypeError` (unexpected keyword); the second passes (it pins the equivalence the rewrite relies on).

- [ ] **Step 3: Implement**

(a) In `_projected_power_peer_possible`, add the two keyword-only parameters and use them:

```python
    candidate_centre = candidate_centre or codec.tile_to_local_offset(
        candidate_building.x, candidate_building.y, candidate_building.z,
        candidate_building.width, candidate_building.height,
    )
    peer_centre = peer_centre or codec.tile_to_local_offset(
        peer_building.x, peer_building.y, peer_building.z,
        peer_building.width, peer_building.height,
    )
```

(Write `if candidate_centre is None:` form rather than `or`, since a tuple of zeros is falsy-free but explicit is clearer.)

(b) In `_power_plan`, immediately before the `free = np.zeros(shape, dtype=bool)` fill loop, add `blocked_columns = {(bx, by) for (bx, by, _level) in canvas.blocked}` and replace `if any((x, y, lvl) in canvas.blocked for lvl in range(LEVELS)): continue` with `if (x, y) in blocked_columns: continue`. Keep the `canvas.free((x, y, 0))` and `canvas.solid` checks exactly as they are, in the same order.

(c) Keep a list `peer_centres: list[tuple[float, float, float]]` parallel to `power_nodes`: append the centre wherever `power_nodes.append(...)` happens (the initial fill ~14234 and the accepted candidate ~14537), computed with `codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height)` on that entry's building. At the candidate filter (~14453), compute `candidate_centre` once for the candidate and rewrite the generator as:

```python
        projected_power_peers = tuple(
            peer
            for peer, peer_centre in zip(power_nodes, peer_centres, strict=True)
            if _projected_power_peer_possible(
                candidate,
                peer,
                power_projection_contexts,
                cancelled=cancelled,
                candidate_centre=candidate_centre,
                peer_centre=peer_centre,
            )
        )
```

Use Serena `find_referencing_symbols` on `power_nodes` within `_power_plan` to find every append; if a third site exists, extend `peer_centres` there too.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/layout/test_freeform.py -k "power or Power or tower"`
Expected: PASS (all pre-existing `_power_plan` tests unchanged).

- [ ] **Step 5: Measure**

Run: `uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py universe-matrix --rate 60 --strategy freeform --out /tmp/scale-levers-task6-um60` and report `phases.power_plan` (was 3.5-3.7 s over 4-5 calls; expect roughly 2.5 s or less).

- [ ] **Step 6: Whole suite, lint, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): reuse power-node centres and a blocked-column set in the power plan"
```

---

### Task 7: Memoize sequence-pair direct-insert geometry

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_direct_origin_deltas`, ~lines 2761-2785), `src/flab2bp/layout/sequence_solver.py` (`_refinement_direct_targets`, ~lines 4041-4062)
- Test: `tests/layout/test_freeform.py` (existing `_direct_net_candidates` tests at ~2067, 2108, 2705), `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `Strip` fields read by `_output_attachment_plan`, `_input_attachment_plan`, `input_lane_tiles`, `lane_of_input`, `_direct_clear_columns` (open each with Serena and list the fields; expect `physical_variant`, `machines`, `pw`, `mw`, `width`, `lane_plan`, `attachment_plan`, `port_dock_plan`, `in_lanes`, `out_lanes`, `pilers`, `tail_extension`, `west_channel`). `StripVariant` and `DirectInsertTarget` are `@dataclass(frozen=True, slots=True)` and hashable.
- Produces: `freeform._DIRECT_ORIGIN_DELTAS_MEMO: dict[tuple[object, ...], tuple[int, ...]]` bounded at `_DIRECT_ORIGIN_DELTAS_MEMO_LIMIT = 65536` entries (cleared when exceeded); `_direct_origin_deltas` consults it when both strips carry a `physical_variant` (otherwise computes as today). `sequence_solver._REFINED_TARGET_MEMO: dict[tuple[DirectInsertTarget, int, int], DirectInsertTarget | None]` bounded the same way; `_refinement_direct_targets` returns identical tuples.

- [ ] **Step 1: Write the failing tests**

In `tests/layout/test_freeform.py`, beside the `_direct_net_candidates` test at ~2108 (reuse its `strips, spec` fixture):

```python
def test_direct_origin_deltas_memo_is_transparent(...same fixture params as the ~2108 test...) -> None:
    freeform._DIRECT_ORIGIN_DELTAS_MEMO.clear()
    first = _direct_net_candidates(strips, spec)
    assert freeform._DIRECT_ORIGIN_DELTAS_MEMO or all(
        strip.physical_variant is None for strip in strips
    )
    second = _direct_net_candidates([replace(strip) for strip in strips], spec)
    assert first == second
    freeform._DIRECT_ORIGIN_DELTAS_MEMO.clear()
    assert _direct_net_candidates(strips, spec) == first
```

In `tests/layout/test_sequence_solver.py`:

```python
def test_refinement_direct_targets_memo_returns_equal_targets() -> None:
    target = DirectInsertTarget(
        key=(0, 1), producer=0, consumer=1, producer_row=0, consumer_row=0,
        producer_span=6, consumer_span=6, origin_deltas=(-2, 0, 3),
    )
    strips = [SimpleNamespace(west_channel=2), SimpleNamespace(west_channel=1)]
    sequence_solver._REFINED_TARGET_MEMO.clear()
    first = sequence_solver._refinement_direct_targets((target,), strips)
    assert (target, 2, 1) in sequence_solver._REFINED_TARGET_MEMO
    second = sequence_solver._refinement_direct_targets((target,), strips)
    assert first == second == (
        DirectInsertTarget(
            key=(0, 1), producer=0, consumer=1, producer_row=0, consumer_row=0,
            producer_span=7, consumer_span=5, origin_deltas=(-1, 1, 4),
        ),
    )


def test_refinement_direct_targets_memo_remembers_a_dropped_target() -> None:
    target = DirectInsertTarget(
        key=(0, 1), producer=0, consumer=1, producer_row=0, consumer_row=0,
        producer_span=1, consumer_span=6, origin_deltas=(0,),
    )
    strips = [SimpleNamespace(west_channel=0), SimpleNamespace(west_channel=5)]
    sequence_solver._REFINED_TARGET_MEMO.clear()
    assert sequence_solver._refinement_direct_targets((target,), strips) == ()
    assert sequence_solver._REFINED_TARGET_MEMO[(target, 0, 5)] is None
```

(`producer_span + 2 - 1 = 7`, `consumer_span + 1 - 2 = 5`, `origin_shift = 1`; in the second test `producer_span = 1 + 0 - 5 < 0` drops the target.) Check `_refinement_direct_targets`'s exact arithmetic against these expectations before running.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/layout/test_freeform.py -k memo tests/layout/test_sequence_solver.py -k memo`
Expected: FAIL with `AttributeError` on the memo names.

- [ ] **Step 3: Implement**

In `freeform.py`, above `_direct_origin_deltas`:

```python
#: (producer geometry, consumer geometry, lane, item) -> origin deltas.  The
#: sequence-pair annealer asks for these once per state for every net (45k
#: calls on gravity-matrix*200) while a move changes one or two strips, so
#: nearly every ask repeats an earlier one.  Bounded so a long audit worker
#: cannot grow without limit; clearing on overflow keeps the answer exact.
_DIRECT_ORIGIN_DELTAS_MEMO: dict[tuple[object, ...], tuple[int, ...]] = {}
_DIRECT_ORIGIN_DELTAS_MEMO_LIMIT = 65536


def _direct_geometry_key(strip: Strip) -> tuple[object, ...] | None:
    if strip.physical_variant is None:
        return None
    return (strip.physical_variant, strip.machines, <every other field the helpers read>)
```

and in `_direct_origin_deltas`:

```python
    source_key = _direct_geometry_key(source)
    destination_key = _direct_geometry_key(destination)
    memo_key = (
        None
        if source_key is None or destination_key is None
        else (source_key, destination_key, source_lane, item)
    )
    if memo_key is not None:
        cached = _DIRECT_ORIGIN_DELTAS_MEMO.get(memo_key)
        if cached is not None:
            return cached
    <existing body computing `deltas`>
    if memo_key is not None:
        if len(_DIRECT_ORIGIN_DELTAS_MEMO) >= _DIRECT_ORIGIN_DELTAS_MEMO_LIMIT:
            _DIRECT_ORIGIN_DELTAS_MEMO.clear()
        _DIRECT_ORIGIN_DELTAS_MEMO[memo_key] = deltas
    return deltas
```

The `except IndexError, KeyError: return ()` early exit must also be memoized as `()` (an empty tuple is a valid cached value; use a sentinel check `cached is not None`, and store `()`).

In `sequence_solver.py`:

```python
_REFINED_TARGET_MEMO: dict[tuple[DirectInsertTarget, int, int], DirectInsertTarget | None] = {}
_REFINED_TARGET_MEMO_LIMIT = 65536


def _refinement_direct_targets(direct_targets, strips):
    adjusted: list[DirectInsertTarget] = []
    for target in direct_targets:
        producer_offset = strips[target.producer].west_channel
        consumer_offset = strips[target.consumer].west_channel
        memo_key = (target, producer_offset, consumer_offset)
        if memo_key in _REFINED_TARGET_MEMO:
            refined = _REFINED_TARGET_MEMO[memo_key]
        else:
            <existing arithmetic; refined = replace(...) or None when a span is not positive>
            if len(_REFINED_TARGET_MEMO) >= _REFINED_TARGET_MEMO_LIMIT:
                _REFINED_TARGET_MEMO.clear()
            _REFINED_TARGET_MEMO[memo_key] = refined
        if refined is not None:
            adjusted.append(refined)
    return tuple(adjusted)
```

Add a docstring sentence to each memo explaining that `replace(DirectInsertTarget)` re-runs `__post_init__`'s three passes over `origin_deltas`, which was 5.8 s of 31 s under cProfile on gravity-matrix*200.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/layout/test_freeform.py -k "direct" tests/layout/test_sequence_solver.py tests/layout/test_sequence_pair.py tests/layout/test_compact_seed.py`
Expected: PASS.

- [ ] **Step 5: Measure**

Run: `uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py gravity-matrix --rate 200 --strategy sequence-pair --cprofile --out /tmp/scale-levers-task7-gm200` then `uv run python -c "import pstats; s=pstats.Stats('/tmp/scale-levers-task7-gm200.pstats'); s.sort_stats('cumulative').print_stats('_refinement_direct_targets|_direct_net_candidates|__post_init__', 6)"`. Expected: `_refinement_direct_targets` and `_direct_net_candidates` cumulative well under 1 s each (were 4.3 s and 5.9 s). Report the numbers.

- [ ] **Step 6: Whole suite, lint, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py
git commit -m "perf(layout): memoize direct-insert geometry across anneal states"
```

---

### Task 8: A Cython kernel for the oriented-box overlap test

**Files:**
- Create: `src/flab2bp/dsp/_geometry_kernel.pyx`, `src/flab2bp/dsp/_geometry_kernel.pyi`, `src/flab2bp/dsp/geometry_kernel.py`
- Modify: `setup.py`, `src/flab2bp/dsp/colliders.py` (`obb_overlap` ~line 935; new `any_box_overlap`), `src/flab2bp/dsp/planet.py` (`collisions_at` inner loop ~lines 1143-1160), `pyproject.toml` only if `[tool.setuptools.package-data]` lists kernel files by name
- Test: `tests/dsp/test_colliders.py`, `tests/dsp/test_planet.py`

**Interfaces:**
- Consumes: `colliders.Box(centre: Vec3, half: Vec3, rot: Quat)` frozen dataclass; the Python `obb_overlap` body (lines 935-975) and its helpers `_axes` (via `_qrot`), `_dot`, `_box_radius`; `route_kernel.py` as the selector template (`_candidates`, `_choose`, `selected_backend`, `compiled_available`).
- Produces: `geometry_kernel.selected_backend() -> Literal["python", "cython"]`, `geometry_kernel.compiled_available() -> bool`, `geometry_kernel._compiled_obb_overlap: Callable[[Box, Box], bool] | None`, `geometry_kernel._compiled_any_overlap: Callable[[Sequence[Box], Sequence[Box]], bool] | None`. `colliders.obb_overlap(a, b)` keeps its signature and dispatches to the compiled function when selected; `colliders._obb_overlap_python(a, b)` is the renamed Python body. New `colliders.any_box_overlap(queries: Sequence[Box], targets: Sequence[Box]) -> bool` returns `any(obb_overlap(q, t) for q in queries for t in targets)` (compiled when available). `planet.collisions_at` uses `any_box_overlap(boxes[pair[0]], boxes[pair[1]])` per pair and keeps its per-pair `cancelled()` check.

- [ ] **Step 1: Write the failing tests**

In `tests/dsp/test_colliders.py`:

```python
def _random_box(rng: random.Random, *, spread: float) -> colliders.Box:
    axis = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
    norm = math.sqrt(sum(c * c for c in axis)) or 1.0
    angle = rng.choice([0.0, math.pi / 2, math.pi, rng.uniform(0, 2 * math.pi)])
    s = math.sin(angle / 2)
    rot = (axis[0] / norm * s, axis[1] / norm * s, axis[2] / norm * s, math.cos(angle / 2))
    return colliders.Box(
        centre=(rng.uniform(-spread, spread), rng.uniform(-spread, spread), rng.uniform(-spread, spread)),
        half=(rng.uniform(0.1, 2.0), rng.uniform(0.1, 2.0), rng.uniform(0.1, 2.0)),
        rot=rot,
    )


@pytest.mark.skipif(not geometry_kernel.compiled_available(), reason="geometry kernel not built")
def test_compiled_obb_overlap_agrees_with_python_on_random_pairs() -> None:
    rng = random.Random(20260905)
    hits = 0
    for _ in range(20000):
        a = _random_box(rng, spread=3.0)
        b = _random_box(rng, spread=3.0)
        expected = colliders._obb_overlap_python(a, b)
        hits += expected
        assert geometry_kernel._compiled_obb_overlap(a, b) is expected, (a, b)
    assert 2000 < hits < 18000, hits  # the sample exercises both verdicts


@pytest.mark.skipif(not geometry_kernel.compiled_available(), reason="geometry kernel not built")
def test_compiled_obb_overlap_agrees_on_touching_axis_aligned_boxes() -> None:
    identity = (0.0, 0.0, 0.0, 1.0)
    a = colliders.Box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), identity)
    for gap in (-1e-9, 0.0, 1e-9, 1e-12, 2.0, 2.0000001, 1.9999999):
        b = colliders.Box((gap + 2.0, 0.0, 0.0), (1.0, 1.0, 1.0), identity)
        assert geometry_kernel._compiled_obb_overlap(a, b) is colliders._obb_overlap_python(a, b), gap


@pytest.mark.skipif(not geometry_kernel.compiled_available(), reason="geometry kernel not built")
def test_any_box_overlap_matches_the_nested_loop() -> None:
    rng = random.Random(7)
    for _ in range(500):
        queries = [_random_box(rng, spread=2.0) for _ in range(rng.randint(0, 4))]
        targets = [_random_box(rng, spread=2.0) for _ in range(rng.randint(0, 4))]
        expected = any(colliders._obb_overlap_python(q, t) for q in queries for t in targets)
        assert geometry_kernel._compiled_any_overlap(queries, targets) is expected


def test_forced_python_backend_disables_the_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geometry_kernel, "_compiled_obb_overlap", None)
    monkeypatch.setattr(geometry_kernel, "_compiled_any_overlap", None)
    assert geometry_kernel.selected_backend() == "python"
    a = colliders.Box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0))
    assert colliders.obb_overlap(a, a) is True
    assert colliders.any_box_overlap([a], [a]) is True
    assert colliders.any_box_overlap([], [a]) is False
```

In `tests/dsp/test_planet.py`, parametrize the existing `test_collisions_at_the_equator_reproduce_the_flat_model` (~line 486) and its two neighbours over both backends by adding a fixture:

```python
@pytest.fixture(params=["python", "cython"])
def geometry_backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "cython" and not geometry_kernel.compiled_available():
        pytest.skip("geometry kernel not built")
    if request.param == "python":
        monkeypatch.setattr(geometry_kernel, "_compiled_obb_overlap", None)
        monkeypatch.setattr(geometry_kernel, "_compiled_any_overlap", None)
    return request.param
```

and take `geometry_backend` as a parameter in those three tests. For the monkeypatch to bite, `colliders.obb_overlap` and `colliders.any_box_overlap` must look the compiled callable up on the `geometry_kernel` module at call time (see Step 3), not bind it at import.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest -q tests/dsp/test_colliders.py tests/dsp/test_planet.py`
Expected: FAIL with `ImportError`/`AttributeError` for `geometry_kernel`.

- [ ] **Step 3: Implement the kernel**

`src/flab2bp/dsp/_geometry_kernel.pyx` (Cython, `language_level=3`). Port `_qrot`, `_axes`, `_dot`, `_box_radius` and `obb_overlap` line for line into `cdef` functions on C `double`s, keeping every operation in the same order as the Python (the epsilon `1e-9` on `abs_rot`, `radius**2` written as `radius * radius`, the three loops in the same sequence with the same early returns). Read `_qrot` with Serena and port it exactly. Expose:

```cython
def obb_overlap(a, b) -> bool:
    # unpack a.centre / a.half / a.rot and b.* into C doubles, call the cdef test
def any_box_overlap(queries, targets) -> bool:
    for q in queries:
        for t in targets:
            if _overlap(...): return True
    return False
```

`src/flab2bp/dsp/_geometry_kernel.pyi`:

```python
from collections.abc import Sequence
from flab2bp.dsp.colliders import Box

def obb_overlap(a: Box, b: Box) -> bool: ...
def any_box_overlap(queries: Sequence[Box], targets: Sequence[Box]) -> bool: ...
```

`src/flab2bp/dsp/geometry_kernel.py`: copy `route_kernel.py`'s structure with `FLAB2BP_GEOMETRY_KERNEL`, importing `obb_overlap as _cython_obb_overlap` and `any_box_overlap as _cython_any_overlap` from `flab2bp.dsp._geometry_kernel` inside `try/except ImportError`; module globals `_compiled_obb_overlap` and `_compiled_any_overlap` (both `None` when the backend is `python`); `compiled_available()` and `selected_backend()` as in `route_kernel`.

`setup.py`: add

```python
            Extension(
                "flab2bp.dsp._geometry_kernel",
                ["src/flab2bp/dsp/_geometry_kernel.pyx"],
                extra_compile_args=["-ffp-contract=off"],
            ),
```

`-ffp-contract=off` forbids fused multiply-add contraction so the C doubles round exactly where Python's do; without it a `-march` that enables FMA would make the parity test flaky at the boundary.

`colliders.py`: rename the existing function to `_obb_overlap_python` and add

```python
def obb_overlap(a: Box, b: Box) -> bool:
    """Separating-axis test, matching ``Physics.OverlapBox`` on two boxes.

    Dispatches to the compiled kernel when one is selected (see
    :mod:`flab2bp.dsp.geometry_kernel`); looked up per call so a test can
    switch backends with ``monkeypatch``.  The Python body is the reference
    the kernel is proven against.
    """
    compiled = geometry_kernel._compiled_obb_overlap
    if compiled is not None:
        return compiled(a, b)
    return _obb_overlap_python(a, b)


def any_box_overlap(queries: Sequence[Box], targets: Sequence[Box]) -> bool:
    compiled = geometry_kernel._compiled_any_overlap
    if compiled is not None:
        return compiled(queries, targets)
    return any(_obb_overlap_python(q, t) for q in queries for t in targets)
```

Import `geometry_kernel` in `colliders.py` with a plain module import (`from flab2bp.dsp import geometry_kernel`); `geometry_kernel.py` must not import `colliders` at module level (only in the `.pyi`), or the import cycle bites.

`planet.py` `collisions_at`: replace the nested `for query ... for target ... obb_overlap` loop with

```python
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if colliders.any_box_overlap(boxes[pair[0]], boxes[pair[1]]):
            hits.append(pair)
```

Build: `uv run python setup.py build_ext --inplace`, then `uv run python -c "from flab2bp.dsp import geometry_kernel; print(geometry_kernel.selected_backend())"` prints `cython`. Check `pyproject.toml` `[tool.setuptools.package-data]`: if it enumerates `layout/*.pyi` or `layout/*.so` patterns by directory, add the matching `dsp/` patterns so a wheel ships the new kernel; `git add` the `.pyx` and `.pyi` but never the `.so`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/dsp tests/layout/test_finalize.py tests/layout/test_freeform.py -k "collide or collision or obb or projection or geometry"`
Expected: PASS, with the parity tests running (not skipped). Also `FLAB2BP_GEOMETRY_KERNEL=python uv run pytest -q tests/dsp` passes.

- [ ] **Step 5: Measure**

Run: `uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py quantum-chip --rate 180 --strategy freeform --out /tmp/scale-levers-task8-qc180` and report `phases.finalize` and `phases.validate` (finalize was 8.9 s over 5 calls). Run the same with `FLAB2BP_GEOMETRY_KERNEL=python` once and report both, so the kernel's share is visible.

- [ ] **Step 6: Whole suite, lint, mypy, commit**

```bash
uv run pytest -q; echo "pytest exit $?"
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src | tail -1
git add setup.py src/flab2bp/dsp/_geometry_kernel.pyx src/flab2bp/dsp/_geometry_kernel.pyi src/flab2bp/dsp/geometry_kernel.py src/flab2bp/dsp/colliders.py src/flab2bp/dsp/planet.py tests/dsp/test_colliders.py tests/dsp/test_planet.py
git commit -m "perf(dsp): compile the oriented-box overlap test"
```

If `pyproject.toml` changed, add it to the same commit.

---

### Task 9: Corpus gate, re-profile, evidence and status notes

**Files:**
- Create: `docs/superpowers/evidence/2026-09-05-scale-levers/gate.md`, `candidate-round{1,2,3}.jsonl`, `candidate-round{1,2,3}.txt`, `candidate-round{1,2,3}-load.txt`, `compare-round{1,2,3}.txt`, `profile-after.jsonl`, `profile-after-load.txt`
- Modify: `docs/superpowers/evidence/2026-09-05-scale-profile/README.md` (append an "After" section), `docs/superpowers/specs/2026-09-05-scale-levers-design.md` (status line), `docs/superpowers/specs/2026-09-02-multiple-belts-and-pilers-design.md` (one status note under §4.1)

**Interfaces:**
- Consumes: `baseline-round{1,2,3}.jsonl` and `baseline-commit.txt` already in the evidence directory (master `a1afec5`, 72 cells, budget 30, taken 2026-09-05 before this branch); `scripts/audit.py --budget 30 --json PATH`; `scripts/audit_compare.py BASELINE CANDIDATE`; `docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py`.

- [ ] **Step 1: Three candidate rounds**

From the worktree root, for `r` in 1 2 3:

```bash
E=docs/superpowers/evidence/2026-09-05-scale-levers
(uptime; vmstat 1 3 | tail -1) > $E/candidate-round$r-load.txt
rm -f $E/candidate-round$r.jsonl
uv run python scripts/audit.py --budget 30 --json $E/candidate-round$r.jsonl > $E/candidate-round$r.txt 2>&1; echo "exit $?"
uv run python scripts/audit_compare.py $E/baseline-round$r.jsonl $E/candidate-round$r.jsonl > $E/compare-round$r.txt 2>&1; echo "compare exit $?"
```

`audit.py` prints `NOT CLEAN` whenever any cell refuses and `audit_compare.py` prints `FAIL` for every non-clean candidate row regardless of the baseline (master itself is 70/72). The gate reads the CLEAN/REFUSED/INVALID/CRASH counts and the set of cells whose status differs between the paired files, not the banner.

- [ ] **Step 2: Judge**

Write a small script (keep it in the evidence directory as `judge.py`) that, for each round, loads both JSONL files, keys rows by `(strategy, url_id, spec_index)`, and prints: counts per status for baseline and candidate; the cells CLEAN in the baseline and not CLEAN in the candidate; the cells that moved the other way; INVALID and CRASH rows in the candidate with their detail; the geometric-mean area ratio over cells clean in both. A cell that regressed in some but not all rounds is a deadline flake: re-run it three times on both trees with `scripts/audit.py --budget 30 --only <url_id> --strategy <arm>` and record all six verdicts before attributing it. Pass criteria are in the spec §4.

- [ ] **Step 3: Re-profile**

```bash
E=docs/superpowers/evidence/2026-09-05-scale-levers
(uptime; vmstat 1 3 | tail -1) > $E/profile-after-load.txt
P=docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py
for cell in "universe-matrix 60" "quantum-chip 180" "gravity-matrix 200" "universe-matrix 90" "universe-matrix 120"; do
  set -- $cell
  for s in freeform sequence-pair; do
    uv run python $P $1 --rate $2 --strategy $s --out /tmp/after-$1-$2-$s && cat /tmp/after-$1-$2-$s.json | uv run python -c "import json,sys; print(json.dumps(json.load(sys.stdin), separators=(',',':')))" >> $E/profile-after.jsonl
  done
done
```

Run the pairs two at a time at most so the timings stay comparable to the before-profile (which ran eight in parallel on an idle box; note the difference in `gate.md`).

- [ ] **Step 4: Write `gate.md` and the status notes**

`gate.md` states: commits compared (baseline commit, branch head), the three-round counts table, differing cells with rulings, area ratios, p95 walls, the before/after phase table (`commit_paths`, `power_plan`, `finalize`, `validate`, `route_all`, wall) for the five cells under both strategies, and the verdict against spec §4. Append the "After" table to `2026-09-05-scale-profile/README.md`. Add to `2026-09-02-multiple-belts-and-pilers-design.md` under §4.1 one paragraph beginning "Status 2026-09-05:" recording that `_merge_lanes` now judges a merged output lane on `min(draw, supply)` and why the earlier unreachability claim did not hold (draw versus supply). Update the status line at the top of `2026-09-05-scale-levers-design.md`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/evidence/2026-09-05-scale-levers docs/superpowers/evidence/2026-09-05-scale-profile/README.md docs/superpowers/specs/2026-09-05-scale-levers-design.md docs/superpowers/specs/2026-09-02-multiple-belts-and-pilers-design.md
git commit -m "evidence: scale-levers corpus gate and re-profile"
```

---

## Self-review

- Spec coverage: §2 -> Tasks 2 and 3; §3 items 1-6 -> Tasks 1, 7, 6, 8, 4, 5; §4 -> Task 9; §5 follow-ups are recorded, not implemented.
- Type consistency: `_committed_path_closes_cycle(canvas, indices, splitter_successors=None) -> bool` (Task 1); `_merge_lanes(..., *, supply=None)` (Task 3, consumed by `_logical_strip_plans` in the same task); `_altitude_profile_cached(path: tuple, ramped: bool) -> tuple | None` (Task 4); `_Canvas.clone() -> _Canvas` (Task 5); `_projected_power_peer_possible(..., candidate_centre=None, peer_centre=None)` (Task 6); `_DIRECT_ORIGIN_DELTAS_MEMO` / `_REFINED_TARGET_MEMO` (Task 7, tests reference the same names); `geometry_kernel._compiled_obb_overlap`, `_compiled_any_overlap`, `colliders._obb_overlap_python`, `colliders.any_box_overlap` (Task 8, tests and `planet.py` use the same names).
- Task order: Task 2 before Task 3 so the *90 regression test is meaningful in both states; Task 1 first because it is the validated prototype the user asked to productionize; Task 8 last among code tasks because it adds a build step; Task 9 closes.
