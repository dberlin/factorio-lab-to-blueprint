# Task 1 — transport adjacency and cycle admission

Status: implementation staged and ready for Main's proof/review; NOT a PASS or committed completion. Source/test writes are settled. No test, build, lint, format, benchmark, commit, or merge command was run by this implementer.

## Changed files and symbols

- `src/flab2bp/layout/buildings.py`: shared `_BuildingsQueries.transport_successors(index)` and `transport_predecessors(index)`; remove obsolete `splitter_successors`.
- `src/flab2bp/layout/freeform.py`: migrate `_leads_back`, `_committed_path_closes_cycle`, `_commit_paths`, `_output_tail_nets`; remove `_splitter_successors` and optional whole-map traversal parameters.
- `src/flab2bp/layout/validate.py`: migrate `_acyclic`, `_belt_reaches_any`, `_unsprayed_belts` directly to `ctx.buildings_index.transport_successors`; remove `_belt_successors`.
- `tests/layout/test_buildings.py`: replace obsolete helper-equality test with inverse-edge/nontransport/invalid-seed contract; replace append-only helper test with live relink/append/pop ordering; migrate rebuilt-index comparison.
- `tests/layout/test_freeform.py`: retained Piler admission regression using a real `_Canvas`; serial Piler legal-merge/relink-cycle regression; cargo-filtered late-output regression; migrate existing Tarjan reference walk off the removed map.
- `tests/layout/test_validate.py` intentionally unchanged: existing Piler cycle, Splitter branch, sprayed cargo transfer, and coproduct consumer regressions cover retained validator behavior.

## Contract and caller inventory

Forward edges: invalid/nontransport seed -> empty; host -> belt members of its input reverse bucket; belt -> valid belt/Splitter/Piler `output_obj`. Inverse edges are belt members of the output reverse bucket plus the valid host named by a belt's `input_obj`. Results are ascending positional order, including relink insertion; invalid raw links are not repaired. No adjacency table/cache was added; `Kind.OTHER` remains the existing Splitter/Piler classification.

Fresh LSP references at the `splitter_successors` declaration failed with `-32603 this._token.cancel is not a function`; issue reported. Scoped source/test text inventory was the fallback. A final scoped inventory found no `splitter_successors` or `_belt_successors` references in source/tests.

| Original symbol | Complete direct caller inventory | Disposition |
|---|---|---|
| `_BuildingsQueries.splitter_successors` | freeform `_splitter_successors`, `_leads_back`, `_committed_path_closes_cycle`; test_buildings old named helper test, append test, rebuilt-index test | Transport callers migrated; old helper removed |
| freeform `_splitter_successors` | `_commit_paths`, `_output_tail_nets`; `TestCommittedPathClosesCycle._reference` | Whole-map owner removed; consumers query live owner |
| `_leads_back` | `_sink_for` preferred destination, hint destination, sibling merge; `TestCommittedPathClosesCycle._reference`; new admission/serial merge regressions | Reachability/own membership stays here; only adjacency changes |
| `_committed_path_closes_cycle` | `_commit_paths`; existing `TestCommittedPathClosesCycle` tests; existing committed-cycle/linear-path tests near original lines14773/14783; new admission/serial merge tests | Tarjan, roots and cycle attribution retained |
| `_output_tail_nets` | `_build_prepared` late output routing; `test_self_consuming_requested_output_routes_from_late_tail`; new cargo-domain regression | Crosses both hosts, retaining same-item filter, integer-height terminal selection, free-neighbor/distance/index tie breaks and deduplication |
| validator `_belt_successors` | `_acyclic` DFS (two sites), `_belt_reaches_any`, `_unsprayed_belts` | Removed; all consume indexed edges directly |
| `_belt_reaches_any` | `_coproduct_buffer` (`flow.coproduct_buffer`) | Cargo-specific sorter hops remain separate |
| `_unsprayed_belts` | `_sprayed_cargo_reaches_machines` | Coater cut, cargo filter, roots and belt-to-belt sorter hops remain separate |

Raw links are intentionally broader: `by_input_obj`/`by_output_obj` retain every building including sorters and machines. `attached_to` uses both raw queries and stays unchanged. Hierarchy compose `_lane` uses `by_output_obj` then its own belt/contiguous-row policy; it is not a transport reachability consumer and stays unchanged. Validator `junction_in`/`junction_out` retain port-count/run-graph/termination consumers; they are not obsolete transport maps. `belt_run(... through_any_host=True)` retains its distinct hierarchy weighting policy (Task7 contract work is not part of this batch).

Task2 marker/hierarchy consumers are listed in task-2-report.md.

## Baseline evidence

- Baseline `bbc8889dd28dc04ee9d223f10387dc8af2d076cc`.
- Root read-only evidence: `docs/superpowers/evidence/2026-09-08-abstraction-review/flab-abstraction-review-probe.py` and `.log`. Observed three-node belt->Piler->belt->first loop: `_leads_back=false`, `_committed_path_closes_cycle=false`, validator reports `belt.acyclic` through `[0,1,2]`. This is graph evidence, not physical legality.
- New tail consumer was staged before changing its source. Main reported expected RED in `.superpowers/sdd/2026-09-08-abstraction-repairs/tail-red-r2.log`: exit1,9.6s, actual source `[0]`, expected `[2]` at then-line12043. During that run freeform and its old Splitter helper were unchanged; new query methods/marker changes existed but were not called by this selector. Initial `tail-red.log` is a separate25s collection timeout, NOT semantic red evidence.
- Main's first green selected batch (`transport-green.log`) reported exit1:62 passed,1 failed. The late-tail traversal assertion now passed; its cargo companion then violated the pre-existing immutable `carries_item` identity restriction during fixture setup. The companion now constructs a separate canvas with the changed cargo record instead of assigning identity through `MutableBuildings.__setitem__`. Production restrictions were not relaxed. Main reported the corrected targeted regression EXIT0 in `tail-green-r2.log`; this is not a whole-task/factory PASS.

## Main's focused selectors / commands

From the abstraction-original worktree:

```sh
uv run --locked pytest -q tests/layout/test_buildings.py tests/layout/test_markers.py tests/layout/hierarchy/test_contracts.py tests/layout/test_validate.py tests/layout/test_freeform.py -k 'transport or piler or Piler or CommittedPathClosesCycle or self_consuming_requested_output_routes_from_late_tail or belt_acyclic or sprayed_cargo or flow_coproduct_buffer or splitter_port_belts or boundary_lanes or shared_piled_tail'
```

Key new selectors:

- `tests/layout/test_freeform.py::test_piler_transit_cycle_is_rejected_by_router_admission`
- `tests/layout/test_freeform.py::test_serial_piler_merge_stays_admissible_until_relinked_into_cycle`
- `tests/layout/test_freeform.py::test_output_tail_nets_cross_pilers_without_crossing_cargo_domains`
- `tests/layout/test_buildings.py::test_transport_edges_are_inverse_and_exclude_raw_nontransport_links`
- `tests/layout/test_buildings.py::test_transport_edges_follow_live_relink_append_and_pop_order`

Existing real commit-path assertions near original lines14773/14783, existing sink legal-merge cases, and `TestCommittedPathClosesCycle` remain available for the touched-file batch. Main owns the final full touched-test/static batch under the project150s ceiling; the selector command above is focused proof, not a full-suite claim.

Physical fixture/command: task-2-report.md and `piler-transfer-smoke.py`. Main reported physical smoke r2 EXIT0 (`piler-transfer-smoke-r2.log`):9 decoded buildings, Piler6 feeding tail7, exact supply1 iron-ingot/s and demand1 iron-ore/s at head0, portable7x5 frame certified for bands4/8/16, full validator clean with power outside the fragment contract. Emitted348 bytes, SHA256 `68bcbf7b549617ace3c2b82281c0f8c94d4ae2bb6b79c26cdf78cc87addc0858`. This proves explicit low-throughput piling materialization/finalization/encode/decode, not automatic selection or a factory gate.

## Pending proof and risks

- Main has observed the selected consumer batch, corrected tail regression and physical smoke evidence above. Independent review and affected static/touched-test integration checks remain required before accepting either task.
- No retained evidence establishes factory gates, solver selection of piling, or automatic requested-output piling. These repairs do not promote hierarchy/topology.
- Adjacency deliberately excludes machine/sorter raw forward links; validator's explicit sorter hops remain necessary and are unchanged.
- Live queries avoid whole-graph materialization. Performance was not measured by this implementer; Main can use the existing focused throughput/profiling evidence if review requires it.
- Task1 and Task2 changes are identifiable by file/symbol sets above and in the second report; no commits were made.
