# Task5 — frozen query keys, live payload identity

## Evidenced disposition

Preventative contract enforcement, not a reproduced production stale-index bug. `_Net` was a mutable ordinary dataclass at this integrated source; `_PreparedNet`, `_Port`, `_PreparedPort`, `NetId` and `LogicalNetId` were already frozen/slotted. All actual indexed cells are immutable three-int tuples, item/kind/role strings or enums, and stable frozen NetIds. No production writer changing a live net's `src`, `dst`, `item`, `net_id`, cargo domain, boundary goals or prelinked flag was found. The only direct `_Net.item` writer in the source/test/script inventory was the fresh-workspace isolation fixture in `tests/layout/test_freeform.py`.

Main's `phase-contract-red.log` establishes the narrower pre-change fact: `tests/indexed/test_nets.py::test_replacing_phase_endpoints_preserves_old_queries_and_payload_identity` failed at DID NOT RAISE FrozenInstanceError. It does not establish a production stale-index failure. Earlier clauses of the same test construct a real detailed phase; post-change clauses exercise endpoint replacement/reindexing while the old phase retains its original queries and object identity.

## Complete consumer inventory

LSP references for Nets failed with `this._token.cancel is not a function`. Narrow source/test grep plus structural assignment queries were used as fallback.

Three production construction/query phases remain independently indexed:
1. `_prepared_routing_lower_bound`: stable NetId, NetId.item, destination cell, empty kind/role; `_PreparedNet` payload.
2. `_route_all.role_rows`: stable NetId, net.item, source/destination cells, empty kind and src/dst role; `(position, _Net)` payload. Both roles now receive the same tuple object, preserving the same net identity without duplicate tuple allocation.
3. `_prepare_routing_problem.demand_rows`: stable NetId, NetId.item, caller-resolved PortAccessKind.value and source/destination role/cell; `_PreparedNet` payload. Demand policy stays outside Nets.

Production construction/replacement sites: inline Piler transition records; `_bind_prepared_net`; `_output_tail_nets` via dataclasses.replace; internal lane pairing; proliferator chain/tree construction; boundary prepared records; coater connections; hierarchy.compose's route-list construction. `_with_sibling_groups` already replaces immutable `_PreparedNet` records before query-phase construction. The fresh-workspace producer creates separate mutable lists, not mutable key-bearing records. Structural assignment queries for `.src`, `.dst`, `.net_id` returned no source/test/script writes; reflective/key-field search identified only the isolation fixture's `.item` assignment.

The private `_NetRecord` wrapper intentionally remains mutable because littletable stamps/inserts row attributes; it is never exposed and no key writer exists after construction. Making that wrapper frozen would violate the existing backend contract. Arbitrary payloads are not cloned or frozen by Nets.

## Change

Freeze/slotted `_Net`, which carries only immutable endpoint/identity and solver-input values. No production caller changes are needed because existing construction and dataclasses.replace already define phase replacement boundaries. Migrate the workspace test's mutable-list element to `replace(first.nets[0], item=...)`, retaining its isolation contract. Document Nets constructor/query phase keys versus live opaque payload identity. Already-frozen producers intentionally unchanged; no wording test or new selection policy.

## Proof boundary / handoff

Source and phase test frozen pending Main's green. Suggested command:

`uv run pytest -q tests/indexed/test_nets.py tests/layout/test_freeform.py::test_prepared_problem_creates_fresh_workspaces tests/layout/test_freeform.py::test_prepared_net_ids_are_stable`

Main should carry the disposition above into the original findings ledger during integration: frozen-key contract was partly already satisfied, with preventative enforcement for the mutable detailed `_Net`; no reachable production stale writer established. No worker validation/build/format/commit was run.
