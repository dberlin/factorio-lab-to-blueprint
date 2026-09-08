# Original abstraction findings: transport and mutable ownership

Status: **approved by the user on2026-09-08; execution started in `.claude/worktrees/abstraction-original`**. This first tranche covers every finding in [the original review](../evidence/2026-09-08-abstraction-review/findings.json). The later [general-codebase review](../evidence/2026-09-08-abstraction-review/general-review.json) and [general repair plan](../plans/2026-09-08-general-abstraction-repairs.md) are separate and do not replace or delay these repairs.

## Evidence and scope

The original review covered Buildings/indexed-scans and their consumers, not the general codebase. Its executed logical-graph probe establishes two current defects at `bbc8889d`:

1. Producer → sorter → belt → Piler → belt loses the actual output belt from marker/hierarchical supply discovery and misidentifies the Piler output as an external input.
2. Belt → Piler → belt → original belt is rejected by `belt.acyclic`, but both router admission guards miss the cycle.

The probe is retained as `flab-abstraction-review-probe.py` and its log beside the findings. It proves transport semantics, not physical paste validity. The stake/corridor findings are distributed-ownership risks with no reproduced divergence. Nets/ReferenceGraph/run-anchor findings are contract questions, not established factory failures.

## Design decision

Use the existing domain owners. Add directed transport queries to the shared Buildings query surface; retain endpoint and cargo policies in their consumers. Promote StakedPaths from a secondary index to the sole ordered path store. Put corridor mutation/rollback behind one call-local owner that coordinates the existing canvas and grid stores. Tighten snapshot contracts without cloning arbitrary payloads or inventing a generic graph framework.

Alternatives rejected:

- Adding Piler branches independently to each walk fixes today's examples but retains the divergent transport definition.
- A universal graph/transaction abstraction merges unrelated policies and introduces more authority than it removes.
- Refactoring all findings before fixing the two confirmed bugs makes correctness depend on unrelated risk investigations.

## Contracts

### Directed transport adjacency

`Buildings` and `MutableBuildings` expose the same live/frozen query semantics:

```python
transport_successors(index: int) -> tuple[int, ...]
transport_predecessors(index: int) -> tuple[int, ...]
```

Nodes are belts, Splitters and Pilers. Belt forward edges come from valid `output_obj` links to transport nodes. A Splitter/Piler's successors are belts whose `input_obj` names that host; the host need not carry a forward link. Predecessors are the inverse of those exact edges. Sorters, machines and add-ons are not transport edges. Invalid references produce no adjacency and remain the validator's separate diagnostic responsibility.

Use the existing kind/link indexes, not a second cached adjacency map. Buildings' `Kind.OTHER` currently denotes Splitters/Pilers; it is not the validator's more detailed Kind enum. Preserve deterministic live-bucket ordering. Queries on MutableBuildings must observe relink/append/pop immediately.

Router reachability, cycle detection and validator DFS remain different algorithms sharing adjacency. Item-specific tail selection still filters cargo. Boundary discovery crosses serial Pilers but preserves the deliberate Splitter-branch stopping rule. A Piler output cannot become an external input solely because its upstream link is encoded on `input_obj`.

### Ordered staked paths

The existing StakedPaths becomes a read-only Mapping interface plus explicit `stake`/`unstake` mutation. Its stored paths, endpoint index, positions, linked-head membership and insertion order are one authority. No parallel mutable `paths` dictionary remains.

An immutable snapshot records ordered `(net, path, linked_head)` entries. Restoring it rebuilds the existing indexes and preserves all consumer-observable iteration/tie behavior. World occupancy, junction guards and route hints are not silently absorbed into this owner; the existing route transaction coordinates them. Empty paths remain supported. Replacing an existing stake must preserve the established ordering contract rather than relying on dict equality.

### Corridor transactions

One call-local corridor owner coordinates `canvas.reserved` (PortReservations), `canvas.port_corridors`, and `grid.reserved`, including exactly the occupancy cells opened by a temporary release. It does not own demand selection, matching, routing or global negotiation.

Single-role retirement preserves current demand-kind eligibility and path-preference selection. Restore preserves the appropriate operation's semantics: ordinary retirement/reinsertion versus exact transaction rollback are distinct. Exact rollback must restore original forward insertion precedence as observed by `first_for`, corridor inventory and grid eligibility. It must not block unrelated cells that were already open, erase another claimant, or retire a role still served by another path.

Reuse the existing `_CorridorRelease` information rather than creating a second journal of the same data. Snapshot at existing transaction boundaries, not for every cell mutation. Exceptions/cancellation restore before leaving the owner; search code keeps its current refusal/UNKNOWN semantics.

### Smaller contracts

- **Nets:** index keys and ordering are frozen for the query phase. Payload identity is retained; arbitrary payloads are not deep-copied. A caller changing identity-bearing fields must replace/re-index its phase input, never mutate a key behind a live index. Verify existing immutable net records before adding restrictions; decorative non-key payload state is a separate concern.
- **ReferenceGraph:** one constructed index observes one graph snapshot, including edge roots, ownership and import-time metadata. Later changes to the source Graph must not make different queries observe different versions. Preserve blocked-target-edge behavior, blocked roots reached as seeds, and missing-root semantics.
- **Buildings.belt_run:** keep the existing production belt-seed contract. Correct the misleading claim that a Splitter/Piler seed is already supported; do not broaden traversal as incidental cleanup. Its explicit `through_any_host` hierarchy weighting policy remains separate from transport adjacency.

## Sequencing and integration

Transport queries/cycle consumers precede endpoint migration. Stake and corridor ownership are separate reviewable steps but serialize their writes to freeform.py. Nets, ReferenceGraph and the run-anchor contract can be handled independently after their actual consumer inventory. One integration owner reconciles all shared-file changes.

Hierarchy v5 and topology experiments are already in flight. Implement this plan on a fresh isolated branch from the chosen integrated source, not by editing their worktrees. Reuse v5's committed-Coater geometry owner if it has landed. No compatibility shims, duplicate old helpers, validator exceptions, raised limits, recipe-specific branches, or mixed lanes.

## Verification and acceptance

- Confirm each Piler bug red using the retained graph input; prove the actual consuming boundary/guard green. Add physical finalized/emitted transfer evidence separately; a graph fixture is never called paste proof.
- For ownership work, run the focused mutation/rollback probe before changing code. If it does not fail, report a preventative consolidation, not a bug fix. Preserve its observable behavior through the cutover.
- Use changed tests and small deterministic scenarios during implementation. Run affected static/module checks once after a review batch settles, under the repository's150-second suite ceiling. Preserve inherited failures. No repeated full suites to answer one local question.
- Final integration verifies Piler transport, ordinary belts, legal merges, Splitter policy, exact rate attribution, ordered failed-transaction rollback and request-independent index snapshots. Any necessary wider release guard runs at the integrated source, not after every helper edit.
- No topology promotion or hierarchy gate is passed by these repairs. Their separately agreed acceptance plans remain in force.

## Coverage ledger

| Original finding | Planned disposition |
|---|---|
| Priority1: Piler-blind boundary discovery | Implementation Task2, using Task1 adjacency |
| Priority2: router/validator Piler disagreement | Implementation Task1 |
| Priority3: paths/StakedPaths dual authority | Task3: probe, consolidate, preserve rollback order |
| Priority4: three-store corridor ownership | Task4: probe and coordinated transaction owner |
| Nets frozen keys/live payloads | Task5: explicit phase contract and caller cutover where needed |
| ReferenceGraph mixed snapshot/live state | Task6: one snapshot across all query families |
| belt_run misleading starting-anchor contract | Task7: narrow documentation to supported belt seeds |
| Intentional distinctions listed in review | Global constraints and Task8 integration review |
