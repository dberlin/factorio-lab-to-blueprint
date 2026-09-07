# Does any site need networkx?

Survey of every graph walk in `src/`, classified by which graph it walks.
The question the brief posed: does any site walk *building connectivity*
(`input_obj` / `output_obj` edges) for reachability, components, cycles or
topological order, such that `Buildings.graph()` as a `networkx.DiGraph`
would be a real conversion rather than a gratuitous dependency?

## A. Graph work over `PlacedBuilding` connectivity

| # | file:line | function | nodes / edges | hand-rolled algorithm | frequency | nearest networkx | verdict |
|---|---|---|---|---|---|---|---|
| 1 | `layout/validate.py:3511` | `_acyclic` (`belt.acyclic`) | belts + splitters + pilers / `_belt_successors` | iterative 3-colour DFS cycle detect, dedups by `frozenset`, yields the cycle node list | once per `certify` | `nx.simple_cycles` (exponential worst case) / `nx.find_cycle` (returns one) | LEAVE — output semantics differ: one Finding per distinct node set, in first-found path order |
| 2 | `layout/freeform.py:12959` | `_committed_path_closes_cycle` | belts + splitters / `output_obj`, splitter→branch | iterative **Tarjan SCC** over only the subgraph reachable from `indices` | per `_commit_paths`, many times per build (docstring: replaced 30k walks / 3.4M visits on `universe-matrix`) | `nx.strongly_connected_components` | LEAVE — exact semantics, but nx runs over the whole graph, not the reachable slice, and needs a fresh `DiGraph` per call on a mutating canvas |
| 3 | `layout/freeform.py:12919` | `_leads_back` | belts + splitters | DFS reachability, early-return on first hit in `own` | per candidate merge in `_sink_for` (13121, 13140, 13165) | `own & nx.descendants(G, s)` — no early exit, strictly slower | LEAVE — **real defect is elsewhere**: all three call sites omit `splitter_successors`, so it rebuilds the O(n) splitter index every call |
| 4 | `layout/hierarchy/contracts.py:67` | `_belt_run` | belts + junctions | adjacency build with an **O(n) inner scan per splitter-feeding belt → O(n²)**, then DFS | per `_machines_on_lane` | `nx.descendants` / `nx.ancestors` | LEAVE — nx replaces the cheap half (a 6-line DFS), not the O(n²) construction |
| 5 | `layout/validate.py:620` | `_build_runs` | belt tiles / `output_obj` | indegree-based segmentation into maximal runs, plus a pass giving each pure cycle its own run | once per `certify` | none — `weakly_connected_components` is the wrong grouping | LEAVE |
| 6 | `layout/validate.py:4609` | `_belt_reaches_any` | belts + splitters + item-matched sorters | DFS reachability that **rescans every sorter inside the pop loop → O(V·S)** | per flow check | `nx.has_path` / `nx.descendants` | LEAVE — the win is precomputing the sorter edge index once |
| 7 | `layout/validate.py:4920` | `_unsprayed_belts` (proliferator spray reach) | belts / `_belt_successors` + sorter belt→belt hops, stopped at coater rides, node-filtered per item | DFS forward reachability from three source classes | per item, per `certify` | per-item filtered subgraph view rebuilt per item | LEAVE — awkward and slower |
| 8 | `layout/freeform.py:13173` | `_run_cells` | belts + splitters, both directions | bounded 3-hop bidirectional BFS | per commit | `nx.ego_graph(G.to_undirected(), s, radius=3)` | LEAVE — hot, tiny, would cost a graph build per call |
| 9 | `layout/hierarchy/compose.py:468` | `_lane` | belt tiles / `output_obj` | walk back to head, forward to tail, filter to one contiguous row | per lane | none — the row-contiguity filter is the content | LEAVE |
| 10 | `layout/markers.py:79` | (open-tail scan) | belt tiles / `output_obj` | linear chain walk, `seen` set as cycle guard | per marker | none | LEAVE — a three-line chain walk |
| 11 | `layout/freeform.py:12866` | `_output_tail_nets` | belts + splitters | DFS collecting open downstream tails | per net | `nx.descendants` + out-degree filter | LEAVE |
| 12 | `layout/validate.py:4095` | `_run_components` | RUN / JUNCTION nodes / `ctx.succ` + `ctx.pred`, undirected | BFS connected components | once per `certify`, cached | `nx.weakly_connected_components` — **exact match** | LEAVE (marginal) — 20 lines, cached, runs once |
| 13 | `layout/validate.py:4126` | `_close_over_junctions` | RUN / JUNCTION | **naive fixpoint**: re-scans all junctions until nothing changes | O(iterations x junctions) | `nx.descendants` | LEAVE the dependency — but the algorithm is genuinely worse than necessary; a plain BFS over the `ctx.succ` that already exists fixes it |

## B. Graph work over something that is not building connectivity

| file:line | function | graph |
|---|---|---|
| `layout/validate.py:4411` | `_reachable_from_outside` | tile lattice, 4-connected flood fill |
| `layout/validate.py:3856` | `_connectivity` (`power.connectivity`) | power towers / link-distance pairs; O(n^2) adjacency + BFS |
| `layout/validate.py:5198` | `_max_flow` | rate flow network, exact integer Edmonds-Karp |
| `layout/validate.py:6035` | `_propagate` | RUN/JUNCTION with `Fraction` fair-share division — not an nx primitive at all |
| `layout/global_router.py:365` | `_hot_regions` | grid cells, flood-fill components |
| `layout/freeform.py:7734` | `_GridIndex._sweep` | routing lattice columns; bit-twiddled, perf-critical |
| `layout/sequence_pair.py:1057` | `_topological_order` | placement relation graph, Kahn with deterministic tie-break |
| `dsp/provenance.py:158` | `ImportGraph.closure` | Python modules/symbols |
| `dsp/colliders.py` | `_belt_chain_excuses_direction` / `_hops` | game preview links; reproduces `CheckBuildConditions` byte-for-byte, must not be generalised |
| `web/trace.py` | — | not graph work; the `deque`s are bounded ring buffers |
| `layout/finalize.py`, `last_mile.py`, `route_feedback.py` | — | no connectivity graph work; finalize's `output_obj` uses are one-hop peer lookups |

## Ruling: do NOT add networkx

Thirteen sites do real building-connectivity graph work, so this is not a
"one three-line chain walk" case — but not one of them is an exact, cheap
`nx.*` swap:

- The two heaviest sites (#2 Tarjan SCC, #3 reachability) are on freeform's
  commit hot path and are *tighter* than the nx primitive: #2 walks only the
  reachable slice, #3 early-exits. Each call would also pay a fresh `DiGraph`
  build against a canvas that mutates between commits.
- The one site with matching semantics and no perf risk (#12) is 20 lines,
  cached, and runs once per certify. That does not buy a dependency.
- Where the code *is* algorithmically weak — #13's fixpoint, #6's rescan in
  the pop loop, #4's O(n^2) adjacency build, #3's per-call index rebuild —
  networkx fixes none of them. Each is fixed by precomputing an edge index
  from data structures already on `Context` / `_Canvas`. Adding nx would
  leave all four defects in place *and* add a dependency.
- #1 `belt.acyclic` cannot be converted at all without changing Finding
  output.

`pyproject.toml` has five runtime dependencies and an explicit comment about
a dependency conflict (`highspy` vs ortools). The bar for a sixth is high and
this does not clear it.

**What is worth doing instead**, and what the plan schedules: build the
successor / predecessor edge index **once** inside `Buildings` and share it
across #2, #3, #6 and #8 — freeform half-does this via `_splitter_successors`
and `validate.Context` fully does it via `succ`/`pred`. That is a refactor of
what already exists, and it fixes the four algorithmic defects nx would have
papered over.

Cost if wrong: if a later feature genuinely needs `nx.max_flow` or
`nx.lexicographical_topological_sort`, adding networkx then is a one-line
`uv add` — nothing in this plan forecloses it.
