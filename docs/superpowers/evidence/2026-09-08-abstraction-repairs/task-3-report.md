# Task3 — ordered path ownership

Scope: approved original Tasks3/4/5 ownership slice in abstraction-original. Main owns commands, review, commits and integration. No worker validation, build, formatting, commit or root edit.

## Baseline boundary

Main ran the staged probes before production mutation and reported `ordered-rollback-red.log`: 3 failures/1 pass across the initial Task3/4 selectors. Task3 API probe failed because StakedPaths was not iterable (new-contract red, not a pre-existing consumer bug). The real failed-cluster probe separately reproduced path insertion reordering: unrelated stake2 moved ahead of restored stake0. Ordinary reservation cancellation passed; unexpected reservation callback failure lost entry reservations (Task4 evidence, not Task3).

Selectors:
- `tests/indexed/test_staked_paths.py::test_ordered_snapshot_restores_replaced_and_reinserted_paths`
- `tests/layout/test_freeform.py::test_failed_cluster_preserves_order_beside_unrelated_stakes`

The cluster probe invokes the real route loop and real commit consumer, bounds only the cluster search result, retains an unrelated route, compares ordered path items, and observes the next commit's path order. The owner probe additionally covers replacement versus remove/reinsert, repeated-cell first position, linked head restoration and sorted `nets()` versus insertion-ordered Mapping.

## Inventory / implementation

LSP references for StakedPaths failed with `this._token.cancel is not a function`; reported via tool QA. Complete source/test fallback found the indexed package export, the StakedPaths module/tests, and one production constructor in `_route_all`. All endpoint/position/linked-head readers now query that same `paths` owner. Mapping lookup distinguishes absent keys from present empty paths; existing `path()` query retains its documented empty-on-absence semantics.

Removed the parallel mutable path dict and all dual stake/unstake writes. `_unstake` captures the immutable path before owner removal so occupancy restoration still has its cells. `_round_state` now includes ordered immutable path snapshots. Both full-pack and selected-cluster restoration rebuild path indexes from the full entry snapshot after restoring external occupancy/hints, retaining positions relative to unrelated stakes. Failed crossing repair also restores the owner snapshot. Guard claims, role retirement, hints and cell ownership stay in the enclosing route transaction.

Best-round paths are detached readonly MappingProxy snapshots, not a live owner reference. `_finish`, `_budget_result`, `_commit_paths`, last-mile cluster construction and all remaining readers consume Mapping; no completed outcome exposes live paths. No solver selection, rate, endpoint or search bound changes.

## Proof handoff

Main reported `paths-green.log` EXIT0: three selected ordered snapshot/failed-cluster rollback cases passed. Main retained `task-3-review.diff` at the Task3-only source boundary before Tasks4/5 changed shared freeform.py. This is scoped evidence, not an integrated suite claim. Suggested final focused command, from the isolated worktree:

`uv run pytest -q tests/indexed/test_staked_paths.py tests/layout/test_freeform.py::test_failed_cluster_preserves_order_beside_unrelated_stakes tests/layout/test_freeform.py::test_a_bounded_cluster_search_restores_the_round_exactly tests/layout/test_freeform.py::test_a_hostile_cluster_solution_never_raises_and_never_routes`

Task4's separately staged two-corridor probe is not part of the Task3 source cutover. Review Tasks3/4 together; Main commits them separately.
