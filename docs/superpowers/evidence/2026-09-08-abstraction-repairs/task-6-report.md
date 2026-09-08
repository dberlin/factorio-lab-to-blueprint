# Task 6 — ReferenceGraph construction snapshot

## Status

Snapshot implementation and regression coverage are settled. Main confirmed five semantic baseline failures before production mutation, then reported all 12 tests in the full ReferenceGraph and provenance consumer modules passing (exit 0, `snapshot-green.log`). No self-validation, formatter, build, commit, merge or push performed. Source/tests remain frozen for Main's independent review and static integration batch.

## Baseline and green selectors

Working directory: `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/abstraction-original`.

Baseline command handed to Main before production mutation:

```sh
uv run pytest tests/indexed/test_reference_graph.py -k source_mutation -q
```

Exact selected tests:

- `test_source_mutation_preserves_reachability_and_blocked_targets`
- `test_source_mutation_preserves_root_membership`
- `test_source_mutation_preserves_module_queries`
- `test_source_mutation_preserves_import_time_captures`
- `test_source_mutation_preserves_holders`

Baseline result reported by Main: `snapshot-red.log`, exit 1, all five selectors fail semantically. Blocked-target reach leaks `b.leaf`; original seed membership disappears; module membership changes with the owner map; lazy captures mix later kind/call state with original adjacency; holders loses `a.root`. Main explicitly authorized the snapshot implementation after this result. This establishes constructor contract drift, not production caller mutation.

Focused graph command supplied for green verification:

```sh
uv run pytest tests/indexed/test_reference_graph.py -q
```

Existing public consumer compatibility command supplied for green verification:

```sh
uv run pytest tests/dsp/test_provenance.py -q
```

Main executed both full modules and reported exit 0, 12 passed; `snapshot-green.log` records all twelve passing indicators. Exact executed command from the worktree above, with `PYTHONPATH` set to that worktree's `src`:

```sh
taskset -c 124 .venv/bin/python -m pytest -q tests/indexed/test_reference_graph.py tests/dsp/test_provenance.py --tb=short
```

After this green run, Main reported running Ruff `--fix` and formatting on the settled original transport/reference batch; those subsequent changes were mechanical. Final static verification remains pending.

## Complete queried-field and lazy-index inventory

| Input/index | Reads and derived queries |
|---|---|
| `Graph.edges` keys | Eager NetworkX node population; `reachable_from` seed eligibility, including keys deleted/added after construction |
| `Graph.edges` values | Eager NetworkX adjacency; lazy direct import-time captures |
| `Graph.owner` | Blocked-target filtering; lazy `_nodes_by_module` bucketing |
| `Graph.kind` | Lazy `_captures` includes `const` and `default` only |
| `Graph.calls` | Lazy `_captures` computes reachability of called roots |
| `_nodes_by_module` | `nodes_in`; `module_reach` seeds |
| `_captures` | `import_time_captures` returns a defensive dictionary copy; `_holders` inversion |
| `_holders` | Sorted holder tuples excluding the captured node itself |

All four Graph fields are queried. The present mixed authority is an eager NetworkX adjacency built from the original edges, a retained live Graph, and a retained live owner map. Lazy indexes can consequently reflect a later version than adjacency.

## Probe coverage

The shared fixture constructs real `provenance.Graph` and `ReferenceGraph` objects, then mutates all backing maps before the first query. It removes a direct edge, removes an existing root key, adds a new root key, moves a node's owner, adds a later owner, changes a const into a function and a function into a const, removes a call and adds a different call. Literal expected results are independent of the implementation.

The five tests cover unblocked closure, blocked targets, blocked roots seeded directly, deleted original roots, added/missing roots, node/module membership, per-module closure, const/default import-time captures, transitive call capture and holder inversion. Existing real-graph closure and capture formula comparisons remain in place. Existing NetworkX traversal and blocked-edge policy must remain unchanged.

## Consumer inventory and risk disposition

LSP `references` on `ReferenceGraph` failed with the recorded server cancellation bug (`-32603`, `this._token.cancel is not a function`); the tool failure was reported. Complete fallback search for `ReferenceGraph|reference_graph` covered worktree `src`, `tests` and `scripts`. Production consumers are the indexed package export and `dsp.provenance.frozen_captures`, which constructs a call-local index and uses `holders_of`. `hardcoding_readers` mentions ReferenceGraph only in its explicit non-conversion comment and retains its separate traversal; `consultation` also retains Graph queries. No public caller migration is required.

`Graph` is a frozen dataclass but accepts Mapping fields whose dictionaries may still be mutable. `build_graph` creates dict-backed Graph fields (edge/call values are frozensets). The source-map probe concerns the constructor's snapshot contract. It is not evidence that existing production callers mutate these maps during an index lifetime, nor evidence of a factory failure.

## Later source changes

Implemented in `src/flab2bp/indexed/reference_graph.py`: the private Graph now owns copied `MappingProxyType` dictionaries for edges, owner, kind and calls. Existing field values are immutable strings/frozensets under the Graph API, so copying mapping containers is sufficient; arbitrary payload deep copying is unnecessary. NetworkX adjacency is built from this snapshot. Root eligibility and captures already read the private Graph and therefore now read the same version; blocked-target filtering and module bucketing also read its owner mapping rather than retaining a separate live alias. Class/`of` docstrings state the construction snapshot contract.

No duplicate traversal, global cache, provenance public behavior change, transport edit or changed limit. NetworkX reachability, blocked-edge refusal, root eligibility and lazy index behavior remain structurally unchanged. No caller migration was required. The returned import-time capture dictionary still defensively copies the cached result.

## Pending verification

Focused green and existing consumer compatibility are verified by Main's reported red5/green12 result. Integration static checks and independent review remain Main-owned and pending. This fixes the demonstrated constructor snapshot contract; no claim is made that production graphs mutate during index lifetimes.
