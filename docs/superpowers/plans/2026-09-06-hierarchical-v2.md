# Hierarchical Block Decomposition v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `--strategy hierarchical` produce validator-clean blueprints on the large URLs inside the budget the user gives it, by fixing the four defects the v1 gate measured (`docs/superpowers/evidence/2026-09-07-hierarchical-v1/gate.md` §6) and adding the first adaptive memory (§7): a both-fed lane contract, a strip count that matches what freeform packs, per-block funding on a pool sized to the box, a port-access corridor reserved before the packing is committed, and a within-build no-good on block shape.

**Architecture:** Five bounded changes inside `src/flab2bp/layout/hierarchy/`, nothing outside it except one helper import. `contracts.allocate_cuts` decides per (block, item) how much of a head's deficit the internal producers owe and leaves the rest to the player only for items the parent spec already belts in. `partition.strip_count` calls freeform's `plan_strips` so the cap counts packed strips. `strategy` funds one job per block from the wall it has, on a pool sized from the CPU affinity set, with one pool per `lay_out` and a `_ShapeNoGood` memo consulted before every solve and every re-cut. `compose.pack_with_access` grows the inter-block gap until `_reserve_port_access` with a boundary reports no missing corridor, and only then routes. A v2 gate adds the user's titanium-glass mall URL to the five v1 cells and measures at both 60 s and the web UI's 15 s.

**Tech Stack:** Python 3.14, `uv run`, the freeform router (`_reserve_port_access`, `_route_all`), `multiprocessing` spawn pools, `scripts/audit.py`, `docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py`.

**Spec:** `docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md` §1 (coverage and bounded time first, area within a band) and §4 E (a bus corridor reserved before block placement); the measurements in `docs/superpowers/evidence/2026-09-07-hierarchical-v1/gate.md` §3, §6, §7 and `docs/superpowers/evidence/2026-09-06-debug-url/README.md` (C5: at budget 15 the reserve is 10 s and one 5 s wave refuses instantly; at 60 s five blocks x 2 arms over a pool of 4 is 3 waves and `11.8 / 3 < 5`). The v1 plan `docs/superpowers/plans/2026-09-06-hierarchical-v1.md` is the file structure this plan extends; its Global Constraints carry over unchanged unless restated below.

## Global Constraints

- **Default behaviour is byte-identical.** `PRODUCTION_STRATEGIES` unchanged; one paired `scripts/audit.py --budget 30 --json` round vs the merge base: identical CLEAN counts and identical freeform per-cell areas; sequence-pair geomean within ±0.11 %.
- **The validator is the arbiter; no player-closed loops for internally produced items.** A head for an item the parent spec does NOT belt in must be fully fed by cuts or the build refuses. A head for an item the parent DOES belt in (a both-fed item) may be left to the player, and then every head of that item on that block is left to the player: a (block, item) is wired entirely or not at all (evidence README "Other things that broke" item 2: a partially wired cut convicts `flow.conservation`).
- **Bounded time.** Every job's deadline is `min(parent, start + budget)`; a round is never started with less than `BLOCK_BUDGET_MIN_S` per job; settlement is entered only before the parent deadline; the strategy may overshoot by the pipeline's race grace, as recorded in v1.
- **Exact arithmetic** everywhere rates appear.
- **Process discipline:** worktree on a branch off master; never `git stash`; never commit under `.superpowers/`; Read/Edit for edits; `ruff check` 0, `ruff format --check` 0, `mypy src` 0; verify once per code change; pytest summary never prints (judge by exit code); 120 s per-test timeout; record `(uptime; vmstat 1 3 | tail -1)` beside every timing; one layout build at a time from this plan; never two audits at once. `git diff` is wired to difftastic: use `--no-ext-diff` for patches.
- **Known-red on master:** `tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`; load flakes `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`, `tests/layout/test_strategy_race.py::test_the_real_pool_races_both_arms_end_to_end`.
- **Large URLs:** `docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt` (belt3, zurl2, mall) plus the titanium-glass mall URL in `docs/superpowers/evidence/2026-09-06-debug-url/README.md`. Best-known dense areas: belt3 all-products 12408; zurl2 40905; titanium-glass all-products 5727 (sequence-pair, `best` at 30 s).

## File Structure

| file | responsibility |
| --- | --- |
| `src/flab2bp/layout/hierarchy/contracts.py` | + `CutAllocation`, `allocate_cuts(spec, blocks, cuts, tails, heads) -> tuple[list[LaneFlow], set[tuple[int, str]]]`; `assign_lanes` unchanged and called by it |
| `src/flab2bp/layout/hierarchy/partition.py` | `strip_count` counts packed strips via `freeform.plan_strips` |
| `src/flab2bp/layout/hierarchy/compose.py` | + `pack_with_access(...)`: gap search with `_reserve_port_access` (boundary set) as the oracle; `compose` takes the reservation instead of recomputing it |
| `src/flab2bp/layout/hierarchy/strategy.py` | funding per block on `_available_cpu_count() // _BLOCK_WORKERS`, one pool per `lay_out`, `_ShapeNoGood`, player-fed (block, item) pairs threaded into `composed_spec` |
| `src/flab2bp/layout/hierarchy/partition.py` | `composed_spec(spec, blocks, *, player_fed=...)` adds the player-fed block deficits to `external_inputs` |
| `tests/layout/hierarchy/test_contracts.py`, `test_partition.py`, `test_compose.py`, `test_strategy.py` | per-task tests |
| `docs/superpowers/evidence/2026-09-07-hierarchical-v2/` | gate evidence (Task 6) |

---

### Task 1: The both-fed lane contract (`allocate_cuts`)

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/contracts.py`, `src/flab2bp/layout/hierarchy/partition.py` (`composed_spec`), `src/flab2bp/layout/hierarchy/strategy.py` (call site)
- Test: `tests/layout/hierarchy/test_contracts.py`, `tests/layout/hierarchy/test_partition.py`

**Interfaces:**
- Consumes: `Cut(item, src, dst, rate)`, `LaneEnd`, `LaneFlow`, `assign_lanes(cuts, tails, heads)`, `boundary_lanes`.
- Produces:

```python
@dataclass(frozen=True)
class CutAllocation:
    flows: list[LaneFlow]
    #: (block index, item) pairs whose entry heads are left to the player.
    player_fed: frozenset[tuple[int, str]]

def allocate_cuts(
    spec: BuildSpec,
    cuts: list[Cut],
    tails: dict[int, list[LaneEnd]],
    heads: dict[int, list[LaneEnd]],
) -> CutAllocation: ...
```

Rule, per item: total internal supply `S = sum(tail rates over every producing block)`; consumers sorted by block index; each consumer block `b` with deficit `D_b = sum(head rates on b)` is served in order while `S >= D_b` (all-or-nothing per block); a consumer that cannot be fully served is `player_fed` if `item in spec.external_inputs`, else `ContractError` (`f"{item}: internal supply {S} cannot cover block {b}'s {D_b}; the parent does not belt it in"`). Served consumers' heads are passed to `assign_lanes` with the tails; unserved consumers' heads are dropped from the call.

- [ ] **Step 1: Failing tests**

```python
def test_a_both_fed_item_leaves_the_unserved_block_to_the_player():
    spec = _chain_with_external("ingot")          # ingot both produced inside and in external_inputs
    cuts = [Cut("ingot", 0, 1, Fraction(2)), Cut("ingot", 0, 2, Fraction(2))]
    tails = {0: [_end(0, 10, "ingot", 2)]}
    heads = {1: [_end(1, 20, "ingot", 2)], 2: [_end(2, 30, "ingot", 2)]}
    got = allocate_cuts(spec, cuts, tails, heads)
    assert [(f.src.building, f.dst.building, f.rate) for f in got.flows] == [(10, 20, Fraction(2))]
    assert got.player_fed == {(2, "ingot")}


def test_an_internal_item_short_of_supply_is_a_contract_error():
    spec = _chain()                                # ingot NOT in external_inputs
    cuts = [Cut("ingot", 0, 1, Fraction(2)), Cut("ingot", 0, 2, Fraction(2))]
    tails = {0: [_end(0, 10, "ingot", 2)]}
    heads = {1: [_end(1, 20, "ingot", 2)], 2: [_end(2, 30, "ingot", 2)]}
    with pytest.raises(ContractError, match=r"ingot.*block 2.*does not belt it in"):
        allocate_cuts(spec, cuts, tails, heads)


def test_a_block_is_wired_entirely_or_not_at_all():
    spec = _chain_with_external("ingot")
    cuts = [Cut("ingot", 0, 1, Fraction(3))]
    tails = {0: [_end(0, 10, "ingot", 3)]}
    heads = {1: [_end(1, 20, "ingot", 2), _end(1, 21, "ingot", 2)]}   # wants 4, has 3
    got = allocate_cuts(spec, cuts, tails, heads)
    assert got.flows == [] and got.player_fed == {(1, "ingot")}


def test_composed_spec_declares_player_fed_block_deficits():
    spec = _chain_with_external("ingot")
    part = partition.initial_partition(spec, strip_cap=2)
    built = partition.composed_spec(spec, part.blocks, player_fed={(1, "ingot")})
    consumer_deficit = sum(u.consumes("ingot") for u in part.blocks[1])
    assert built.external_inputs["ingot"] >= consumer_deficit
```

- [ ] **Step 2: Run, expect failure.** `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_contracts.py tests/layout/hierarchy/test_partition.py -k "both_fed or contract_error or entirely or player_fed"`.
- [ ] **Step 3: Implement** `allocate_cuts` as specified; `composed_spec(spec, blocks, *, player_fed: frozenset[tuple[int, str]] = frozenset())` adds each player-fed block's deficit of that item to `external_inputs[item]` (keeping the `max(...)` with the parent's declared rate); `strategy.lay_out` replaces the direct `assign_lanes` call with `allocate_cuts` and passes `player_fed` to `composed_spec`. Add `_chain_with_external(item)` to `tests/layout/hierarchy/test_pressure.py` next to `_chain` (same graph, `item` also in `external_inputs` at 1/s).
- [ ] **Step 4: Verify.** `uv run pytest -q -p no:randomly tests/layout/hierarchy` exit 0; ruff/mypy/format. `uv run flab2bp "<zurl2>" --strategy hierarchical --budget 60 --candidate-policy all-products` no longer refuses on `lane contract: hydrogen ...` (record the new outcome, whatever it is).
- [ ] **Step 5: Commit** `fix(hierarchy): allocate cuts per block and leave both-fed remainders to the player`

### Task 2: Count the strips freeform packs

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/partition.py` (`strip_count`)
- Test: `tests/layout/hierarchy/test_partition.py`

**Interfaces:**
- Consumes: `freeform.plan_strips(spec, *, strip_len=6) -> list[Strip]` (freeform.py ~2443; `strip_len=6` is the sweep's default).
- Produces: `strip_count(spec, block) -> int` = `len(plan_strips(sub_spec(spec, block, 0)))`; `STRIP_CAP_DEFAULT` re-tuned in Task 6.

- [ ] **Step 1: Failing test**

```python
def test_strip_count_is_the_packed_count_not_the_logical_plan_count(mall_all_products):
    spec, _vertical = mall_all_products
    part = partition.initial_partition(spec, strip_cap=10_000)     # no cap: seed blocks only
    block = max(part.blocks, key=lambda b: sum(u.count for u in b))
    logical = len(_logical_strip_plans(partition.sub_spec(spec, block, 0)))
    packed = partition.strip_count(spec, block)
    assert packed >= logical
    assert packed == len(plan_strips(partition.sub_spec(spec, block, 0)))
```

- [ ] **Step 2: Run, expect failure** (today `packed == logical`). **Step 3: Implement** with a lazy import of `plan_strips` (the same import-cycle shape `initial_partition` uses). **Step 4: Verify** hierarchy tests exit 0; ruff/mypy/format; print belt3 all-products' seed partition (blocks, packed strips each) at cap 12 and record it in the report: the 129-machine block must now split. **Step 5: Commit** `fix(hierarchy): bound blocks by the strips freeform packs`

### Task 3: Fund per block on a pool sized to the box, one pool per build

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/strategy.py`
- Test: `tests/layout/hierarchy/test_strategy.py`

**Interfaces:**
- Consumes: `pipeline._available_cpu_count()` (import lazily inside `_pool_width` to keep the import direction: `pipeline` imports `hierarchy`).
- Produces: `_pool_width(self) -> int = max(1, min(_POOL_CAP, (self.workers or _available_cpu_count()) // _BLOCK_WORKERS))` with `_POOL_CAP = 32`; the round's arithmetic becomes `waves = ceil(jobs / width)`, `share = remaining / waves` as now, but with the wide pool a 20-job round on this box is ONE wave; `SETTLEMENT_RESERVE_MIN_S = 5.0` (was 10) so a 15 s web build has a 10 s round; the pool is created once in `lay_out` (`with self._executor_factory(width) as pool:` around the whole round loop) and passed into `_solve_round(..., pool=pool)`; spawn start-up is paid once.

- [ ] **Step 1: Failing tests**

```python
def test_pool_width_comes_from_the_affinity_set(monkeypatch):
    monkeypatch.setattr(strategy, "_available_cpu_count", lambda: 128)
    layout = HierarchicalLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"))
    assert layout._pool_width() == 32
    layout = HierarchicalLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"), workers=16)
    assert layout._pool_width() == 4


def test_a_fifteen_second_build_funds_one_round(chain_spec, monkeypatch):
    seen: list[float] = []
    real = strategy._solve_block
    def spy(args):
        seen.append(args[2])
        return real(args)
    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = HierarchicalLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"),
                                workers=8, strip_cap=2)
    layout._executor_factory = ThreadPoolExecutor
    layout.lay_out(chain_spec, time_budget_s=15.0)
    assert seen and min(seen) >= strategy.BLOCK_BUDGET_MIN_S


def test_one_pool_serves_every_round(chain_spec, monkeypatch):
    made: list[int] = []
    class Counting(ThreadPoolExecutor):
        def __init__(self, width):
            made.append(width)
            super().__init__(width)
    monkeypatch.setattr(strategy, "_solve_block", _refuse_first_shape_then_real)   # from v1 tests
    layout = HierarchicalLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"),
                                workers=8, strip_cap=2)
    layout._executor_factory = Counting
    layout.lay_out(chain_spec, time_budget_s=40.0)
    assert len(made) == 1
```

- [ ] **Step 2: Run, expect failure. Step 3: Implement. Step 4: Verify** hierarchy tests exit 0; ruff/mypy/format; titanium-glass URL at `--budget 15` and `--budget 60` (`--strategy hierarchical`): record verdict, blocks, waves, wall; the 15 s build must attempt at least one round. **Step 5: Commit** `perf(hierarchy): one pool per build, sized to the box, funding a round per block`

### Task 4: Reserve port access before committing the packing

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/compose.py`
- Test: `tests/layout/hierarchy/test_compose.py`

**Interfaces:**
- Consumes: `pack_blocks(sizes, gap)`, `canvas_for`, `_port_access_inventory(nets).demands`, `_reserve_port_access(canvas, demands, *, boundary, bounds, cancelled, deadline) -> PortAccessReservation` (`.missing`, `.evidence`), `PortAccessDemand.cell`.
- Produces:

```python
GAP_LADDER = (2, 4, 6, 8, 12, 16)

@dataclass(frozen=True)
class PackedCanvas:
    buildings: list[PlacedBuilding]
    blocks: list[BlockPlaced]
    canvas: _Canvas
    nets: list[_Net]
    reservation: PortAccessReservation
    gap: int

def pack_with_access(placements, flows, spec, *, ramped, deadline, margin) -> PackedCanvas: ...
```

For each `gap` in `GAP_LADDER` (stop early on deadline): pack, translate, build the canvas and nets exactly as `compose` does today, compute `boundary` = every cell `(x, y, 0)` on the outer ring of `canvas.limit`, call `_reserve_port_access(..., boundary=boundary, bounds=bounds, cancelled=..., deadline=...)`, and return the first `PackedCanvas` whose reservation is `complete`; if none is complete, return the one with the fewest `missing`. `compose` calls `pack_with_access` and routes on its canvas (the reservation is already staked on it), reporting `missing` as today. The margin outside the packing stays `_limit_margin` (8).

- [ ] **Step 1: Failing tests**

```python
def test_pack_with_access_widens_the_gap_until_every_port_has_a_corridor(two_solved_blocks, monkeypatch):
    left, right, flows, spec, ramped = two_solved_blocks
    seen: list[int] = []
    real = compose_mod._reserve_port_access
    def scripted(canvas, demands, **kw):
        seen.append(kw["bounds"][2] - kw["bounds"][0])
        reservation = real(canvas, demands, **kw)
        if len(seen) == 1:                       # first gap: pretend one port is walled in
            return replace(reservation, missing=demands[:1], assigned=reservation.assigned[1:])
        return reservation
    monkeypatch.setattr(compose_mod, "_reserve_port_access", scripted)
    packed = compose_mod.pack_with_access([left, right], flows, spec, ramped=ramped, deadline=None, margin=8)
    assert packed.gap == compose_mod.GAP_LADDER[1]
    assert packed.reservation.complete


def test_pack_with_access_passes_the_outer_ring_as_the_boundary(two_solved_blocks, monkeypatch):
    left, right, flows, spec, ramped = two_solved_blocks
    captured = {}
    real = compose_mod._reserve_port_access
    def spy(canvas, demands, **kw):
        captured["boundary"] = set(kw["boundary"]); captured["limit"] = canvas.limit
        return real(canvas, demands, **kw)
    monkeypatch.setattr(compose_mod, "_reserve_port_access", spy)
    compose_mod.pack_with_access([left, right], flows, spec, ramped=ramped, deadline=None, margin=8)
    x0, y0, x1, y1 = captured["limit"]
    assert (x0, y0, 0) in captured["boundary"] and (x1, y1, 0) in captured["boundary"]
    assert all(x in (x0, x1) or y in (y0, y1) for x, y, _ in captured["boundary"])


def test_compose_still_routes_both_cuts_on_the_chain(two_solved_blocks):
    left, right, flows, spec, ramped = two_solved_blocks
    result = compose_mod.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)
    assert result.failures == () and result.routed == len(flows)
```

- [ ] **Step 2: Run, expect failure. Step 3: Implement. Step 4: Verify** hierarchy tests exit 0; ruff/mypy/format; belt3 all-products at `--strategy hierarchical --budget 60`: record the gap chosen, `missing` before/after, unrouted cuts and their kinds (the v1 result at cap 4 was 8-50 lanes `DYNAMIC_ACCESS`). **Step 5: Commit** `feat(hierarchy): reserve port access before committing the block packing`

### Task 5: A within-build no-good on block shape

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/strategy.py`
- Test: `tests/layout/hierarchy/test_strategy.py`

**Interfaces:**
- Produces:

```python
ShapeKey = tuple[tuple[str, int], ...]          # sorted (recipe_id, count)

def shape_key(units: list[Unit]) -> ShapeKey: ...

@dataclass
class _ShapeNoGood:
    refused: dict[tuple[ShapeKey, str], float] = field(default_factory=dict)   # -> budget refused at
    def remembers(self, key: ShapeKey, arm: str, budget_s: float) -> bool:
        seen = self.refused.get((key, arm)); return seen is not None and seen >= budget_s
    def record(self, key: ShapeKey, arm: str, budget_s: float) -> None: ...
```

`_solve_round` skips a job whose `(shape, arm)` is remembered at a budget ≥ this round's and records refusals; `_next_cut` skips a cut whose every child is remembered for every arm (tries the next attempt); the memo lives on the `lay_out` call (not the instance). `stats["resplits"]` gains a sibling `stats["nogood_skips"]` (add to `PlacementStats`).

- [ ] **Step 1: Failing tests**

```python
def test_a_refused_shape_is_not_re_solved_at_the_same_budget(chain_spec, monkeypatch):
    calls: list[tuple[ShapeKey, str, float]] = []
    real = strategy._solve_block
    def spy(args):
        calls.append((shape_key_from_spec(args[0]), args[1], args[2]))
        if len(args[0].groups) == 1 and args[0].machine_count == 2:
            return ({"strategy": args[1], "verdict": "REFUSED: forced", "ok": False, "wall_s": 0.0}, None)
        return real(args)
    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = HierarchicalLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"),
                                workers=8, strip_cap=2)
    layout._executor_factory = ThreadPoolExecutor
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)
    keys = [(k, arm) for k, arm, _ in calls]
    assert len(keys) == len(set(keys)), "a (shape, arm) was solved twice"
    assert placement.stats["nogood_skips"] >= 0


def test_the_memo_forgets_across_lay_out_calls(chain_spec):
    layout = HierarchicalLayout(belt_vertical_construction=True, band_policy=BandPolicy.parse("portable"),
                                workers=8, strip_cap=2)
    layout.lay_out(chain_spec, time_budget_s=30.0)
    assert not hasattr(layout, "_nogood")
```

- [ ] **Step 2: Run, expect failure. Step 3: Implement. Step 4: Verify** hierarchy tests exit 0; ruff/mypy/format. **Step 5: Commit** `feat(hierarchy): remember refused block shapes within a build`

### Task 6: The v2 gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v2/` (`gate.md`, `large-*.{json,log}`, `-load.txt`, `judge.py` copied from v1's gate dir, `run_large.sh`, `sweep-*.json`)
- Modify: `docs/speedup-idea-backlog.md` (move the four levers to done/partly), `src/flab2bp/layout/hierarchy/partition.py` (`STRIP_CAP_DEFAULT` if the sweep picks another cap)

- [ ] **Step 1: Strip-cap sweep** on belt3 all-products with the packed count (caps 8, 12, 16, 24 at 60 s); pick the smallest cap that builds CLEAN with the smallest area; commit the default if it changes.
- [ ] **Step 2: Large-URL runs**, twice each, `--strategy hierarchical --candidate-policy <label>`: belt3 all-products and no-proliferator, zurl2 all-products, mall all-products and no-proliferator, titanium-glass all-products, all at `--budget 60`; titanium-glass and belt3 all-products also at `--budget 15`. Record verdict, wall, area, blocks, gap, cut lanes, player-fed pairs, nogood skips, validator errors by class, `area / best_known`.
- [ ] **Step 3: Default-unchanged guard:** one paired audit round vs the merge base with `judge.py`.
- [ ] **Step 4: `gate.md`** with the rule declared before running: **PASS** if belt3 all-products, zurl2 and titanium-glass build CLEAN at 60 s within budget + race grace with zero unrouted cuts, belt3 ≤ 1.25 x 12408, zurl2 ≤ 1.0 x 40905, titanium-glass ≤ 1.25 x 5727, titanium-glass builds at 15 s, both malls either build or refuse with every block placed and the refusal naming the composition stage, and the default guard is unchanged. FAIL otherwise, naming the clause. Then the next three levers and the two remaining adaptive memories (cross-build solved-block cache, outcome-driven cap) with the evidence.
- [ ] **Step 5: Commit** `evidence: hierarchical v2 gate on the large URLs`

---

## Self-review

- **Spec coverage.** Gate §6 lever 1 (corridor before packing): Task 4. Lever 2 (funding): Task 3. Lever 3 (both-fed contract): Task 1. The cheaper lever below them (packed strip count): Task 2. §7's first memory: Task 5; the other two are deliberately deferred and named in Task 6. Design §1's objective is the gate rule; §4 E's reserved corridor is Task 4's boundary-aware reservation over a gap ladder rather than a physical bus lane, which is the smallest change that gives every port a corridor by construction.
- **Placeholders.** None: every task carries its test code and its interface. Task 4's boundary cell convention (`(x, y, 0)`) follows `Cell = (x, y, level)` in `route_feedback`.
- **Type consistency.** `CutAllocation.player_fed` is a `frozenset[tuple[int, str]]` in Task 1 and the keyword of `composed_spec` in Task 1; `PackedCanvas` fields match what `compose` needs from `pack_with_access`; `ShapeKey` is the same tuple type in `shape_key`, `_ShapeNoGood` and the tests.
