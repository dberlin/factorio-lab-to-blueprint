# Task4 — coordinated corridor mutation

## Baselines (Main execution)

`ordered-rollback-red.log`: ordinary cancellation in `test_reservation_abort_restores_held_corridor_precedence[False]` passed. Unexpected cancellation-callback exception in `[True]` reproduced loss of entry reservations/corridors, including held claims. This supports structural exceptional rollback repair; it does not make ordinary cancellation a reproduced defect.

First `test_failed_cluster_restores_two_corridors_and_unrelated_grid` attempt: both cases failed the fixture precondition (real selected cluster was `(1,)`, not containing the intended staked blocker). Main retained `corridor-release-red.log` as setup failure, not semantic evidence. The corrected fixture uses the already-discriminating `_one_stranded_net_fixture`, adds a legitimate opposite-role dead-end approach at the selected blocker source, preserves its forced destination approach on the stranded path's real wall, and retains the real `build_cluster` precondition. Corrected baseline is pending Main; Task4 production remains unchanged at this report boundary.

R2 (`corridor-release-red-r2.log`) reached final observation in both cases. The ordinary bounded case then saw empty reservations because final physical `_commit_paths` legitimately spends them; that was an observation-boundary error, not a transaction bug. The exceptional case observed re-held departure cells after the propagated cluster exception. The probe now observes the next real physical committer's ENTRY (before final cleanup) for ordinary return, and the propagated-exception boundary otherwise. It compares the real routing grid's reservations/occupancy/next flags, first_for and both ordered canvas stores. Neither R1 setup failure nor R2 ordinary final cleanup is claimed as a semantic defect.

## Inventory and implementation contract

Three coordinated stores: canvas.reserved (PortReservations), canvas.port_corridors, optional route grid.reserved and its occupancy cells. Preparation legitimately has no grid. Existing PortReservations.clear/update preserve supplied ordered item sequence and rebuild first_for's reverse index; no new storage primitive is required.

Mutation sites: detailed route served-role retirement and last-role restoration; failed crossing repair; bounded/rejected/exceptional last-mile cluster; relaxed whole-pack corridor release/restore; preparation clearing/re-holding/final assignment/cancellation; external boundary single-corridor retirement and legacy first-reservation fallback. Construction, clone and prepared-workspace snapshot loading remain separate initialization boundaries, not competing live route writers.

Private call-local `_CorridorReservations` will coordinate these writes, retaining `_CorridorRelease` as the only reservation rollback receipt with ordered immutable entries, exact grid reservation tuple, and exactly the cells opened by temporary release. Ordinary role reinsertion keeps its current canonical corridor/grid sorting semantics; exact rollback restores original forward-map precedence. Remaining roles sharing cells must keep protection. Selection eligibility stays `kind is None or corridor.kind in (None, kind)` with endpoint-intersection preference and coordinate tie order. Demand matching, policy, budgets and result status remain in existing callers.

Preparation will hold an explicit release context across enumeration/matching/publication; only explicit receipt commit retains new assignments. Exceptions restore entry state structurally instead of depending on each cancellation check. Existing held-safe top-up order and caught-survey give-up remain intact.

## Implemented cutover

`_CorridorReservations` owns ordinary eligible retirement, role reinsertion, shared served-role receipts, temporary exact release/restore, selected assignment publication, legacy single-cell boundary retirement, and terminal canvas-only reservation spending. Snapshot entries are ordered tuples; the existing `_CorridorRelease` additionally carries original retired-role membership and an explicit finished/commit bit, not a second rollback journal. PortReservations remains unchanged.

The detailed route constructs one grid-bound owner. `_stake` sends indexed endpoint roles to it; `_unstake` resolves which roles have no other staked member before restoring those roles. Role eligibility and endpoint preference are unchanged. A selected corridor cannot erase another role's shared access/exit protection. Exact rollback restores the original grid tuple and first_for precedence; only release-opened occupancy cells are re-blocked and newly claimed route ownership is not overwritten.

Failed crossing repair, strict cluster, and relaxed whole-pack paths use structural context/finally boundaries. Path/hint/guard/occupancy restoration stays in the route transaction, using StakedPaths ordered snapshots. The original whole-pack sequence is retained: un-stake all paths, temporarily release every re-held corridor, run the existing search, restore those corridors before re-staking, then restore exact outer reservation order. Solver outcomes, selected clusters and limits are unchanged. Successful commits explicitly commit their receipt.

Preparation holds the owner context over existing enumeration, joint matching, held-wins assignment assembly and result construction. Only successful result construction explicitly commits. Cancellation checks no longer manually rewrite stores; every escaping exception restores entry state. The matcher's caught-survey deadline can still return ordinary give-up and retain held claims. Held assignment order and demand matching stay in the caller.

`_commit_paths` and final prepared-build spending clear matching corridor inventory together with reservations through a canvas-only owner. These are terminal publication boundaries, not temporary rollback or new demand selection.

Source is frozen at the Main proof handoff. No worker validation/build/lint/format/service/browser run or commit occurred.

## Proof handoff

Worker runs no validation. Main exact pending selector:

`uv run pytest -q tests/layout/test_freeform.py::test_failed_cluster_restores_two_corridors_and_unrelated_grid`

Further green/review/source boundary and final smoke selectors will be appended after implementation and Main proof. No pass claim is made here.

Final focused command set for Main (isolated worktree):

`uv run pytest -q tests/indexed/test_staked_paths.py tests/indexed/test_port_reservations.py tests/indexed/test_nets.py tests/layout/test_freeform.py::test_failed_cluster_preserves_order_beside_unrelated_stakes tests/layout/test_freeform.py::test_reservation_abort_restores_held_corridor_precedence tests/layout/test_freeform.py::test_failed_cluster_restores_two_corridors_and_unrelated_grid tests/layout/test_freeform.py::test_a_bounded_cluster_search_restores_the_round_exactly tests/layout/test_freeform.py::test_a_hostile_cluster_solution_never_raises_and_never_routes tests/layout/test_freeform.py::test_an_unsorted_reservation_tuple_is_not_a_restore_mismatch tests/layout/test_freeform.py::test_the_relaxed_run_never_re_reserves_a_served_nets_corridor tests/layout/test_freeform.py::test_a_relaxed_run_that_closes_records_the_cluster_strips tests/layout/test_freeform.py::test_port_access_cancellation_inside_candidate_scan_restores_canvas tests/layout/hierarchy/test_compose.py::test_a_topped_up_partial_leaves_both_corridor_sets_on_the_canvas tests/layout/hierarchy/test_compose.py::test_a_top_up_that_expires_mid_enumeration_leaves_the_canvas_as_the_partial`

Actual owner smoke, staged separately before implementation:

`uv run python .superpowers/sdd/2026-09-08-abstraction-repairs/corridor-owner-smoke.py`

The smoke uses real canvas/grid owners to check eligible shared roles, first_for precedence, initially-open versus release-opened cells and unrelated live route ownership surviving an exception. It is not physical factory transfer proof. Main removes this throwaway after retaining evidence.
