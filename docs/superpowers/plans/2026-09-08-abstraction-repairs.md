# Original Abstraction Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two confirmed Piler transport defects and give every remaining original ownership/contract finding an explicit, independently verifiable disposition.

**Architecture:** Extend the existing Buildings query owner for directed transport rather than maintaining separate Piler/Splitter walks. Consolidate path and corridor mutation at their existing domain boundaries, then make index snapshot contracts explicit. Preserve independent traversal algorithms and intentionally different endpoint, cargo, geometry and rollback policies.

**Tech Stack:** Repository-locked Python/uv, pytest, Ruff, mypy, existing indexed backends. No new dependencies.

**Spec:** [Original abstraction repair design](../specs/2026-09-08-abstraction-repairs-design.md).

## Status and priority

Approved by the user on2026-09-08; execution started in isolated worktree `.claude/worktrees/abstraction-original`. This is the **first, separate repair tranche**. It includes all four ranked findings and all three lower-priority contracts from [the original findings](../evidence/2026-09-08-abstraction-review/findings.json). The [general repair plan](2026-09-08-general-abstraction-repairs.md) is separately approved and cannot displace these tasks.

All eight tasks are complete in the isolated worktree; source through `c37b20bf`
passes independent interface review and scoped consumer proof. The broader
all-products cold-layout refusal remains a baseline-confirmed factory failure.
See the [acceptance report](../evidence/2026-09-08-abstraction-repairs/report.md)
for all seven dispositions, actual emitted transfer, exact commands and
retained failures. No merge or push has been performed.

The original review was scoped to Buildings/indexed-scans and consumers. The later review sampled domain/rates/DSP, layout, orchestration/tooling, and frontend/service seams. Neither was an exhaustive line-by-line audit; the later report records its coverage and omissions explicitly.

## Global constraints

- Baseline evidence is `bbc8889d`; implement on a fresh isolated worktree from the chosen integrated source. Never edit the live hierarchy/topology experiment worktrees for this plan.
- Inventory current references with LSP before changing exported APIs. The earlier LSP references failure was `this._token.cancel is not a function`; if it persists, retain the failure and use a complete narrow source/test consumer inventory. Do not assume old line numbers survived integration.
- Fix Piler transport generally. No recipe/item/URL special cases, mixed lanes, validator exceptions, raised deadlines/work bounds, or compatibility aliases.
- Preserve physical footprints versus collision/keepout, unique versus last-writer predecessor policies, cycle-refusing versus cycle-breaking ordering, item/cargo filtering, and internal versus external endpoint allocation.
- Buildings' `Kind.OTHER` identifies Splitters/Pilers; it is not the validator's detailed Kind enum. Never copy enum comparisons across those modules blindly.
- Use existing indexes. No second mutable transport graph, global cache, deep copy of arbitrary net payloads, or generic transaction framework.
- Preserve deterministic order. Dict equality alone is not an order-preservation proof.
- Shared-file mutation has one owner. Tasks1/2/3/4 touch freeform.py and serialize their edits; independent Nets/ReferenceGraph work may proceed concurrently with an explicit integration owner.
- Focused red/green and small runtime scenarios during implementation. Run affected static/module checks once after a review batch settles, under the project's150-second suite ceiling. Preserve original failures; serial adjudication never replaces them.
- No merge or push is authorized by this planning request. Hierarchy and topology retain their separately agreed acceptance gates.

## File and ownership map

| Area | Existing owner / change | Consumers |
|---|---|---|
| Directed belt/host edges | `layout/buildings.py`, shared query mixin | marker boundary policy, hierarchy, router guards, validator adjacency |
| Endpoint policy | `layout/markers.py`; hierarchy retains rate attribution | labels and `hierarchy/contracts.py:boundary_lanes` |
| Staked path data/indexes | `indexed/staked_paths.py` becomes sole ordered path store | freeform stake/rip-up/last-mile readers and transactions |
| Corridor mutation | Small private `_CorridorReservations` owner in existing `layout/freeform.py` | preparation reservation, served-role retirement, cluster release/restore |
| Frozen net keys | `indexed/nets.py` and actual key-bearing producer records | prepared, detailed and lower-bound query phases |
| Provenance snapshot | `indexed/reference_graph.py` | `dsp/provenance.py` query consumers |
| Run-anchor documentation | `layout/buildings.py:belt_run` | existing hierarchy weighting caller |

Do not move the routing engine out of Freeform in this tranche. The broader review's strategy-neutral routing-domain proposal is separate; it must later consume these owners rather than duplicate them.

## Execution DAG and review batches

```text
Task1 transport adjacency/cycle admission -> Task2 boundary discovery
Task3 ordered path ownership -> Task4 coordinated corridor mutation
Task5 Nets contract       (independent)
Task6 ReferenceGraph     (independent)
Task7 belt-run contract  (serialize Buildings edit after Task1)
all -> Task8 integration and evidence
```

Execute the confirmed fixes first. Review Tasks1+2 together as a transport cutover; Tasks3+4 together only after their separate focused probes; Tasks5+6+7 as contract repairs. Keep task-sized commits and split any review package beyond roughly3000 changed lines. A preventative consolidation is not mislabeled a reproduced bug fix.

## Task 1: Canonical transport edges and Piler-aware cycle admission

**Files:** Modify `src/flab2bp/layout/buildings.py`, `src/flab2bp/layout/freeform.py`, `src/flab2bp/layout/validate.py`; tests `tests/layout/test_buildings.py`, `tests/layout/test_freeform.py`, `tests/layout/test_validate.py`. Retained input: `docs/superpowers/evidence/2026-09-08-abstraction-review/flab-abstraction-review-probe.py`.

**Interfaces:** Add `transport_successors(index: int) -> tuple[int, ...]` and `transport_predecessors(index: int) -> tuple[int, ...]` to `_BuildingsQueries`, shared by Buildings/MutableBuildings. Consume existing kind and reverse-link indexes. Query results contain only belt/Splitter/Piler nodes and are inverse descriptions of the same directed edges.

- [ ] Inventory `splitter_successors`, `_splitter_successors`, `_leads_back`, `_committed_path_closes_cycle`, `_output_tail_nets`, validator `_belt_successors`, and every actual caller. Record which consumers want transport edges versus raw all-building links; do not replace `by_input_obj`'s broader contract.
- [ ] Add the confirmed consumer regression using the retained three-node graph. A concrete logical fixture is:

```python
from fractions import Fraction
from types import SimpleNamespace
from typing import cast
from flab2bp.dsp import catalog
from flab2bp.layout import freeform, validate
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.buildings import MutableBuildings


def _transport_building(name: str, x: int, **links: int) -> PlacedBuilding:
    item = catalog.item_id(name)
    return PlacedBuilding(
        item_id=item, model_index=catalog.building(item).model_index,
        x=x, y=0, z=Fraction(0), carries_item="gear", **links,
    )


def test_piler_transit_cycle_is_rejected_by_router_admission() -> None:
    placement = Placement(buildings=(
        _transport_building("conveyor-belt-1", 0, output_obj=1),
        _transport_building("automatic-piler", 1),
        _transport_building("conveyor-belt-1", 2, input_obj=1, output_obj=0),
    ))
    canvas = cast(freeform._Canvas, SimpleNamespace(
        buildings=MutableBuildings(placement.buildings)))
    assert freeform._leads_back(canvas, 0, {2})
    assert freeform._committed_path_closes_cycle(canvas, [0])
    report = validate.validate(placement, only=("belt.acyclic",), expect_power=False)
    assert any(f.check == "belt.acyclic" for f in report.errors)
```

This fixture is intentionally graph-only, not a claimed legal physical paste. Run its single selector red; both admission assertions currently miss the Piler. Use the existing real-canvas fixture for additional commit-path coverage where available; do not mock either traversal algorithm.

- [ ] Implement the shared indexed query. The forward decision is exactly:

```text
invalid seed -> empty
Splitter/Piler seed -> belts in the seed's input_obj reverse bucket
belt seed -> its valid output_obj when the target is belt/Splitter/Piler
all other seeds -> empty
```

For predecessors, include belt records whose `output_obj` names the seed and, for a belt seed, its valid Splitter/Piler `input_obj` host. Do not infer a forward belt edge from an arbitrary redundant input link. Preserve deterministic bucket order and avoid materializing a whole adjacency table for a one-node question.

- [ ] Migrate the router guards and validator adjacency to these queries. Keep DFS/Tarjan/reachability algorithms, graph roots, warning/error construction, and cargo filters in their existing owners. `_output_tail_nets` must cross Piler transit without treating it as an arbitrary machine or dropping its item filter. Remove obsolete Splitter-only transport maps/helpers once references show no remaining consumer; do not retain aliases.
- [ ] Prove the consumer regression green, plus a legal merge/shared prefix, multiple serial Pilers, a Splitter branch, and live relink/append/pop. Observable contract: a newly closed transport cycle is denied, a legal merge remains admissible, and queries on the live owner follow the current links. Do not add tests that merely assert helper calls.
- [ ] Run the touched tests as one batch, retain red/green output and update the task report. Commit the complete adjacency/admission cutover.

## Task 2: Piler-aware producer boundaries without changing Splitter policy

**Files:** Modify `src/flab2bp/layout/markers.py`, `src/flab2bp/layout/hierarchy/contracts.py` only where boundary interpretation needs adjustment, and any actual freeform endpoint consumer identified in Task1. Tests: `tests/layout/test_markers.py`, `tests/layout/hierarchy/test_contracts.py`.

**Consumes:** Task1 transport queries. **Produces:** Existing `input_belt_heads`, `output_belt_tails` and `boundary_lanes` signatures, with correct Piler transit and unchanged rated-lane output types.

- [ ] Port the retained producer→sorter→belt2→Piler3→belt4 fixture into the existing marker/contract tests. Use the real catalog records and `BuildSpec(groups=(), outputs={"gear": Fraction(1)})` exactly as the retained probe does. Assert:

```python
assert output_belt_tails(placement) == [4]
assert 4 not in input_belt_heads(placement)
tails, heads = boundary_lanes(placement, spec, 0)
assert [(lane.building, lane.rate) for lane in tails] == [(4, Fraction(1))]
assert all(lane.building != 4 for lane in heads)
```

Define `placement` with the five real records from the retained probe; use its builder or the test module's existing catalog builder. Run these consumer assertions red. This is a rated logical-boundary regression; physical sorter/collider legality is a separate transfer scenario.

- [ ] Preserve the current producer-sorter root selection and sorted output order. Replace raw forward-link stopping at Pilers with Task1 adjacency. Stop at intentional Splitter branch boundaries as before; do not report every reachable same-item branch as an external output.
- [ ] Make exposed-input detection exclude a belt fed through a Piler/Splitter host, not only a belt with another belt predecessor. Preserve truly exposed belts and existing producer-root/input filtering in hierarchy. Do not infer ownership merely from `carries_item`.
- [ ] Verify multiple serial Pilers, ordinary producer belts, a real external input, an internal Splitter branch, and two producers sharing a legal output tail. Verify no output is counted twice and hierarchy still apportions exact rates rather than assigning the entire block deficit to every lane.
- [ ] Run a small real piled placement through the existing layout/finalization/encoding path, decode the emitted bytes, and inspect its boundary supply. Retain exact input/bytes/checks; if no suitable existing physical fixture is available, build the smallest legal catalog fixture rather than calling the graph-only fixture paste proof.
- [ ] Review Tasks1+2 together, retain scoped test/smoke evidence, remove obsolete endpoint walkers, and commit Task2 separately.

## Task 3: Make StakedPaths the sole ordered path authority

**Files:** Modify `src/flab2bp/indexed/staked_paths.py`, `src/flab2bp/layout/freeform.py`; tests `tests/indexed/test_staked_paths.py`, the existing last-mile rollback cases in `tests/layout/test_freeform.py`.

**Interfaces:** `StakedPaths` supplies read-only Mapping operations over `int -> tuple[Cell, ...]`, existing `stake`/`unstake` and query methods, plus `snapshot()`/`restore(snapshot)`. Snapshot entries are immutable ordered `(net, path, linked_head)` records. No second path map survives the cutover.

- [ ] Before editing, execute a focused failed-cluster scenario after unrelated stakes exist. Capture `tuple(paths.items())`, endpoint scan order, linked heads and first positions; fail the transaction; compare the later repair choice as well as these query answers. Include replacing a stake, removing/reinserting one, and a path with a repeated cell. Record whether divergence is reproduced. A passing probe supports preventative ownership consolidation, not a new bug claim.
- [ ] Inventory every `paths` read/write, including any in-place payload mutation, copied best-path snapshot, `_round_state`, `_restore_staked`, whole-pack sweep and final result publication. Preserve readonly result snapshots rather than leaking a live mapping into completed outcomes.
- [ ] Promote the existing owner, not another wrapper. Mapping reads come from its stored paths; mutation is only `stake`/`unstake`. Keep absent lookup and empty-path behavior distinct. Preserve the existing `nets()` sorted-ID query while Mapping iteration follows live insertion order.
- [ ] Implement and exercise ordered rollback through the owner:

```python
paths = StakedPaths(((1, 0), (-1, 0), (0, 1), (0, -1)))
paths.stake(8, ((0, 0, 0), (1, 0, 0)), linked_head=True)
paths.stake(3, ((4, 0, 0), (5, 0, 0)))
saved = paths.snapshot()
paths.unstake(8)
paths.stake(8, ((0, 1, 0), (1, 1, 0)))
paths.restore(saved)
assert tuple(paths) == (8, 3)
assert paths.linked_heads() == frozenset({(0, 0, 0)})
assert paths.position_in(8, (1, 0, 0)) == 1
```

Keep the permanent test centered on consumer-observable failed-transaction behavior; this small snippet defines the new API and can be a throwaway smoke if equivalent behavior is already tested.

- [ ] Migrate stake/rip-up callers so they do not update both a dict and StakedPaths. Snapshot before destructive mutation; retain the path needed to undo occupancy. Keep guard claims, role retirement and source/sink hints in the enclosing route transaction. Change `_round_state`'s path component from equality-only dictionaries to an ordered snapshot where order is observable.
- [ ] Re-execute the original transaction probe and relevant route cases. Verify a failed attempt does not alter the next attempt's order or indexed answers. Keep first-position semantics for repeated cells and linked-head restoration. Review and commit without claiming a bug was reproduced if it was not.

## Task 4: One coordinated corridor reservation mutation/rollback owner

**Files:** Modify existing `src/flab2bp/layout/freeform.py` around `_retire_served_roles`, `_restore_unserved_roles`, `_CorridorRelease`, `_retire_port_corridor`, `_restore_port_corridor`, cluster release/restore and `_reserve_port_access`. Modify `indexed/port_reservations.py` only if the storage owner itself lacks a required ordered restore primitive. Tests: `tests/layout/test_freeform.py`, `tests/indexed/test_port_reservations.py`, relevant held-safe top-up cases in `tests/layout/hierarchy/test_compose.py`.

**Interfaces:** A private call-local `_CorridorReservations` coordinates the existing stores. It is constructed with `_Canvas` and, in routing phases, `_Grid`; preparation legitimately has no grid. It exposes served-role retirement/restoration and exact temporary-release transactions using the existing corridor types/receipt data. Demand selection and search status stay outside it.

- [ ] Run two discriminating probes first: cancel reservation after one held corridor; fail last-mile routing with two corridors for one port and unrelated existing reservations. Observe `first_for`, corridor membership and actual subsequent grid eligibility. Preserve the before/after insertion sequence, not only dict equality. Record current pass/fail accurately.
- [ ] Move three-store updates behind this owner. Preserve current corridor eligibility (`kind is None or corridor.kind in (None, kind)`) and endpoint-intersection preference. Retiring an eligible corridor must update canvas reservations, corridor inventory, and the bound grid view together; a remaining shared role must retain its protection.
- [ ] Reuse/strengthen `_CorridorRelease` as the rollback receipt: ordered original reservations/corridors, original grid reservation tuple, and exactly the cells opened by the release. Do not duplicate it with a second parallel journal. Restore must not re-block cells that were already open or overwrite unrelated route ownership.
- [ ] Make exceptional temporary mutation structurally restore its entry state. The intended use is:

```text
with reservations.temporarily_released(selected_corridors):
    run the existing bounded cluster operation
# receipt restores original ordered reservations and only its own grid changes
```

`selected_corridors` is the existing caller-resolved mapping of ports to eligible corridors, not a new demand selector. If success intentionally commits a new reservation, use an explicit commit operation; implicit successful return must not accidentally retain a temporary release. Preserve ordinary role reinsertion semantics separately from exact rollback.

- [ ] Migrate canvas-only preparation cancellation and grid-bound routing/last-mile paths; remove their duplicate manual restore blocks after the owner covers all raising/returning paths. Keep held-safe top-up behavior and assignment ordering. No relaxation of earlier held corridors is authorized by this extraction.
- [ ] Re-run the initial probes and retained cancellation/top-up/failed-cluster cases. Verify first-for precedence, shared-role eligibility and the next route outcome. Review Tasks3+4 together and commit this owner separately. If no current mismatch was found, label it preventative consolidation.

## Task 5: Establish the Nets frozen-key/live-payload phase contract

**Files:** `src/flab2bp/indexed/nets.py`, actual key-bearing `_Net`/`_PreparedNet` producers and their construction/replacement sites in `layout/freeform.py`; tests `tests/indexed/test_nets.py` and the smallest affected prepared-routing consumer cases.

**Interfaces:** Preserve indexed query semantics, first-seen ID order, multiple role rows sharing one payload, and payload identity. Freeze index keys for a query phase; rebuilding/replacing phase input is the only way to change identity-bearing fields. Do not deep-copy opaque payloads.

- [ ] Inventory what each row indexes (`net_id`, item/kind/cell signature and role) and verify whether each actual producer record is already frozen. Distinguish mutable non-key payload data from identity mutation. Do not claim a current stale-index bug without a reachable writer.
- [ ] Add or retain immutable row/key construction and explicit constructor/query documentation. If any production key-bearing record is mutable, migrate that record's key-changing callers to immutable replacement and rebuild the relevant phase index. Leave unrelated payload state and solver metadata untouched.
- [ ] Exercise two phase inputs representing different endpoints for the same logical net. The first index must keep its original role/signature answers, the second must answer the replacement endpoints, and multiple role rows must still return the same payload object for that phase. Also preserve duplicate-ID first-seen behavior and empty role lookup.
- [ ] If the inventory shows every production key is already immutable, make the contract clarification without manufacturing an implementation change or wording-pinning test. Record that explicit disposition in the original findings ledger. Commit only actual contract/caller changes.

## Task 6: Make ReferenceGraph queries observe one snapshot

**Files:** Modify `src/flab2bp/indexed/reference_graph.py`; preserve `src/flab2bp/dsp/provenance.py` public graph semantics. Tests: `tests/indexed/test_reference_graph.py`.

**Interfaces:** Existing `ReferenceGraph.of`, `reachable_from`, `nodes_in`, `module_reach`, `import_time_captures`, `holders_of`. Every accessor must use the same construction-time graph version, including roots, owners, kinds and call edges.

- [ ] Run a small discriminating probe with mutable backing maps passed to `provenance.Graph`; build ReferenceGraph, then mutate source edges/owner/kind/calls. Compare query families. Classify any divergence as a constructor snapshot-contract issue, not evidence that current call-local production graphs mutate.
- [ ] Replace the live Graph reference/owner maps with a coherent immutable snapshot of the graph fields actually queried. Build NetworkX adjacency and lazy capture/module indexes from that same snapshot. No extra global cache; do not duplicate graph traversals or change blocked-edge semantics.
- [ ] Use this concrete fixture shape for a focused snapshot test:

```python
edges = {"a.root": frozenset({"b.leaf"}), "b.leaf": frozenset()}
owners = {"a.root": "a", "b.leaf": "b"}
kinds = {"a.root": "const", "b.leaf": "func"}
calls = {"a.root": frozenset()}
graph = provenance.Graph(edges=edges, owner=owners, kind=kinds, calls=calls)
indexed = ReferenceGraph.of(graph)
edges["a.root"] = frozenset()
owners["b.leaf"] = "a"
assert indexed.reachable_from(["a.root"]) == frozenset({"a.root", "b.leaf"})
assert indexed.reachable_from(["a.root"], block=["b"]) == frozenset({"a.root"})
assert indexed.nodes_in("b") == frozenset({"b.leaf"})
```

Extend the same observable snapshot case to import-time captures and holders after changing the backing kind/call maps. Retain existing real-graph closure comparisons, blocked roots and missing-root behavior; no new full-project provenance suite per accessor.

- [ ] Run the focused graph module, document the snapshot contract and commit separately from transport/routing work.

## Task 7: Resolve the misleading belt_run starting-anchor contract

**Files:** `src/flab2bp/layout/buildings.py:belt_run`; current production consumers discovered through references. Existing tests: `tests/layout/test_buildings.py`, `tests/layout/hierarchy/test_contracts.py`.

**Decision:** Preserve the established belt-seed behavior. The docstring currently promises a host seed that the loop does not traverse; the reported production caller supplies a belt. Do not add host-seed traversal merely to satisfy prose.

- [ ] Re-inventory actual seeds after Task1 integration. If callers still supply belts, narrow the docstring to the supported precondition and accurately describe host transit reached from a belt. Preserve `through_any_host`'s intentionally broader hierarchy weighting semantics.
- [ ] If a new legitimate host-seed consumer exists at the chosen integrated source, stop this narrow documentation cutover and record the changed requirement for a deliberate behavior task; do not silently reinterpret that caller.
- [ ] Run the existing belt-run/hierarchy weighting cases only if source behavior changed elsewhere in the shared file. Do not write a test asserting docstring text or preserving accidental host-seed output. Record this finding as resolved by contract clarification, not a Piler cycle fix.

## Task 8: Integrate, verify and close every original finding explicitly

**Files:** All task files, this plan/spec, original `findings.json`, and existing project backlog/report documents as relevant.

- [ ] Check the seven-item coverage table below against actual commits and reports. No item disappears because the broad review produced more findings. For risk/contract tasks, record reproduced bug, preventative consolidation, or already-satisfied contract with evidence.
- [ ] Run one integrated affected test/static batch after shared edits settle: Buildings, markers, hierarchy contracts, focused routing/rollback cases, StakedPaths, PortReservations, Nets and ReferenceGraph; Ruff/mypy using repository configuration. Respect the150-second suite ceiling and retain inherited failures. Do not repeatedly run the full repository suite while diagnosing one failed selector.
- [ ] Exercise real piled input/output transport with unchanged physical validators, finalization and encoded/decode inspection. Retain the graph red/green proof separately. Verify no altered rate attribution, exposed Piler output, accepted transport cycle, or lost legal merge.
- [ ] Perform an independent final interface review covering all migrated callers and intentionally separate policies. Verify no obsolete Splitter-only transport walker, duplicate path map or hand-maintained corridor transaction remains in the migrated domain; raw all-building queries and different algorithm policies may legitimately remain.
- [ ] After smoke proof, remove disposable scripts only; retain minimal original/repaired witnesses, exact commands, review reports and any failed outcomes. Update user-facing docs/backlog with actual contract changes. Do not delete unrelated worktrees or claim a topology/hierarchy gate from these local results.
- [ ] Report source/worktree, each confirmed fix, each risk disposition, emitted examples, executed checks and unresolved boundaries. Do not merge or push without authorization.

## Original findings coverage: nothing omitted

| Finding | Task | Acceptance |
|---|---|---|
| Piler-blind output/input discovery | 2, depends on1 | Rated producer supply crosses Piler; no phantom external input |
| Piler-blind router cycle guards | 1 | Router admission and validator agree on transport edges, while algorithms stay distinct |
| Paths/StakedPaths mutable dual authority | 3 | One ordered path owner; failed transaction preserves later route behavior |
| Three-store corridor mutation | 4 | Coordinated retirement/restore; exact ordered rollback and held-safe top-up |
| Nets key/payload contract | 5 | Explicit frozen query phase; complete writer disposition, no arbitrary deep copy |
| ReferenceGraph snapshot/live mixture | 6 | All query families observe one graph version |
| belt_run host-anchor prose mismatch | 7 | Supported belt-seed precondition made explicit without unrequested behavior |
| Intentional distinctions/non-findings | Global constraints,8 | No forced unification of different domain policies |
