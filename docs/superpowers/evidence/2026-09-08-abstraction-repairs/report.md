# Original abstraction repair acceptance

Source: isolated `abstraction-original`, through `c37b20bf`. No merge or push.

All seven original findings have explicit dispositions in
[`../2026-09-08-abstraction-review/findings.json`](../2026-09-08-abstraction-review/findings.json).
Independent whole-branch interface review and scoped ownership review approve the
source contracts; their exact verdicts are retained beside this report.

| Finding | Result | Source commit |
|---|---|---|
| Piler-blind router/validator adjacency | Confirmed defect repaired; algorithms retain distinct policies | `f81382e9` |
| Piler-blind producer/input boundaries | Confirmed defect repaired; intentional Splitter stopping preserved | `f5a81faf` |
| Paths/StakedPaths dual authority | Reproduced rollback order drift repaired; one ordered owner | `a3d04e68` |
| Corridor mutation across stores | Reproduced exceptional rollback loss repaired; one ordered receipt | `f6e5133f` |
| Nets key/live payload contract | Preventative frozen-key enforcement; no reachable stale-key writer established | `f6e5133f` |
| ReferenceGraph mixed snapshots | Constructor snapshot drift reproduced and repaired; production graph mutation not claimed | `0afdf7ec` |
| belt_run starting-anchor prose | Belt-seed precondition clarified; no new host-seed traversal | `c37b20bf` |

## Consumer contracts

`Buildings.transport_successors` and `transport_predecessors` describe actual
Belt/Splitter/Piler edges for live and frozen records. Router reachability,
neutral cycle validation and producer-boundary traversal consume those edges
without merging their cargo, branch or graph-algorithm policies.

`StakedPaths` is the sole live insertion-ordered path mapping. Mutation goes
through `stake`/`unstake`; immutable ordered snapshots restore linked heads,
first positions and subsequent query/route order. Completed results retain
read-only snapshots, not live workspace state.

The private corridor owner coordinates canvas reservations, corridor inventory
and the routing grid. Exact rollback preserves forward precedence and restores
only release-owned occupancy, without overwriting unrelated route ownership.
Ordinary role reinsertion remains distinct from exact rollback. Frozen phase
keys do not deep-copy opaque payloads. ReferenceGraph snapshots all queried
construction inputs together.

## Executed proof

- Focused path/corridor/key batch: 10 cases pass.
- Complete indexed/buildings/hierarchy-key consumer batch: 72 cases pass.
- Final affected-source Ruff and mypy: pass for all four remaining changed
  source files; earlier transport/snapshot static evidence is retained.
- Actual final corridor-owner smoke passes shared-role eligibility, precedence,
  own-grid rollback and preservation of unrelated route ownership.
- Actual final piled-transfer smoke passes finalization and full validation
  **without power**, then encodes/decodes 9 buildings. Piler6 feeds output tail7;
  iron-ore demand and iron-ingot supply are exactly1 each. Portable frame7x5,
  bands4/8/16, 348 encoded bytes, SHA256
  `68bcbf7b549617ace3c2b82281c0f8c94d4ae2bb6b79c26cdf78cc87addc0858`.
  The emitted artifact and decoded findings are retained under `piler-transfer/`.

The broader affected batch is **not reported as green**. It retained one
all-products cold-layout refusal and33 composition fixture-resolution errors.
A collection-only diagnostic isolated the fixture errors to interleaving parent
and hierarchy file arguments: the fixture was globally registered but missing
from the collected item's fixture map. Grouping the hierarchy first resolves
that lookup; the correctly scoped composition module passes all41 cases. No
fixture or production source was weakened to achieve this.

The same cold all-products test on unchanged `bbc8889d` source also refuses:
one pack at height65, `dynamic-access=1`. Its command, failure and candidate
failure are preserved. This is an inherited factory failure, not a claimed
regression repair. Initial invalid smoke fixtures and rollback observation
errors remain labeled separately from semantic defects in the task reports.

## Verification commands and retained failures

Run from this worktree with `PYTHONPATH=src` and its own `.venv`:

```text
.venv/bin/python -m pytest -q tests/layout/hierarchy/test_compose.py --tb=short
uv run ruff check src/flab2bp/indexed/nets.py src/flab2bp/indexed/staked_paths.py src/flab2bp/layout/buildings.py src/flab2bp/layout/freeform.py
uv run mypy src/flab2bp/indexed/nets.py src/flab2bp/indexed/staked_paths.py src/flab2bp/layout/buildings.py src/flab2bp/layout/freeform.py
```

Exact broader and baseline commands are retained in the corresponding
`*-command.json` records; complete outcomes and causal red/green logs are kept
alongside them. The smoke scripts were disposable; their output and emitted
artifact remain. The permanent regression cases exercise the repaired
boundaries.

This evidence does not establish powered-factory reliability, automatic piler
selection, in-game paste success, topology repair or hierarchical target
acceptance. Those failures and their separate acceptance gates remain intact.
