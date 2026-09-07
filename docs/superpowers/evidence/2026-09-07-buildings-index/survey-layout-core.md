# Buildings-scan survey: layout core (10 files)

Scope: `finalize.py`, `validate.py`, `base.py`, `slots.py`, `junction.py`, `markers.py`,
`last_mile.py`, `global_router.py`, `route_feedback.py`, `observe.py` in
`src/flab2bp/layout/`. Produced by manual read (every enclosing function traced to its
callers) cross-checked against an independent AST-driven scan (holder resolution across
aliasing/`enumerate`/`list`/`sorted` wrapping). Line numbers verified against the worktree
at commit state as of 2026-09-07.

`PlacedBuilding` fields referenced below: `item_id`, `model_index`, `x`, `y`, `z`, `width`,
`height`, `yaw`, `recipe_id`, `filter_id`, `output_obj`, `input_obj`, `carries_item`,
`owner_strip`.

## Background: two ad-hoc index abstractions already exist

`validate.py`'s `Context` (built once per `validate()`/`certify()` call, in `_context()`
lines 753-820) and `finalize.py`'s `_CleanupSurvivorGraph` (built once per cleanup pass,
lines 2953-3600+) are hand-rolled versions of much of what a `Buildings` index would
provide: `ctx.kinds`/`ctx.of_kind()` (kind bucket, cached per kind), `ctx.occupancy` /
`ctx.blocking` / `_belts_by_tile()` (tile index, i.e. `at_tile`), `ctx.junction_in` /
`ctx.junction_out`, `ctx.succ` / `ctx.pred`, `_belt_successors()` (successor/predecessor
index), plus `_CleanupSurvivorGraph`'s incrementally-maintained indegree arrays,
intrusive-linked-list owner-bags, and sorted boundary-coordinate index. Most of the
~70+ `.buildings` / `bs` references in `validate.py` are O(1) lookups against these
caches, not raw scans — the table below lists genuine scan / index-construction sites,
not every downstream O(1) consumer of them.

## 1. Per-site table

Columns: `file:line` | enclosing function | holder | predicate keys | nesting | call
frequency | WORTH/HYGIENE | replacing query.

### finalize.py

| file:line | function | holder | predicate | nesting | frequency | class | replacing query |
|---|---|---|---|---|---|---|---|
| finalize.py:509-533 | `_power_nodes` | `placement.buildings` | item_id (power catalog `is_power_node`) | single-pass | per distinct placement/frame-candidate, memoized in `_ProjectionCache.invariants` keyed by buildings identity (called from `_projection_invariants`, lines 1839/1842) | WORTH | `NEW: power_nodes()` |
| finalize.py:549-… | `_planet_sorters` | `placement.buildings` | kind=sorter (`is_sorter`), x2/y2 present | single-pass; per-sorter work (`emitted_sorter`/`seated_sorter`) does O(1) index lookups, not nested scans | same as above (via `_projection_invariants`) | WORTH | `sorters()` |
| finalize.py:1808-… | `_projection_invariants` | `placement.buildings` (enumerate) | kind (belt/sorter/addon/splitter bucketing), item_id (SPRAY_COATER_ID, SPLITTER_ID) | single-pass, plus internally triggers `_power_nodes` + `_planet_sorters` (2 more full passes) | once per distinct placement/frame-candidate, memoized via `active_cache.invariants[building_key]` (lines 1986-1994) | **WORTH** | `belts()`, `sorters()`, `addons()`, `by_item_id()` |
| finalize.py:881-885 | `first_projected_static_failure` | `buildings` param | kind (not belt, not sorter — machines only) | single-pass | per placement candidate (caller: `freeform.py`'s per-candidate collision probe via `projected_static_failure`) | WORTH | `by_kind` exclusion / `machines()` |
| finalize.py:904-909 | `first_projected_static_failure` | `retained` (already-filtered list) | index equality — `next()` linear search for a candidate's position | single-pass linear search | per placement candidate, only when `candidate_index` is given | **WORTH** | `by_index(i)` / position map |
| finalize.py:913, 932 | `first_projected_static_failure` (pair-projection prep) | `pair_buildings` | none — full coordinate transform (rotate x/y) | single-pass | per placement candidate | HYGIENE | n/a — transform, not a filter |
| finalize.py:2394-2406 | `_materialize_frame` | `placement.buildings` | none — full coordinate rewrite via `materialize_frame_building` | single-pass, **per frame candidate** | once per `finalize_placement`, looped over `frame_candidates` (small bounded set) | HYGIENE | n/a — full rebuild is inherent to the transform |
| finalize.py:2570-2588 | `_frame_content_valid` | `placement.buildings` | x, y, width, height vs frame bounds | single-pass, per frame candidate (via `_frame_satisfies_policy`) | once/build, bounded by candidate count | HYGIENE | n/a |
| finalize.py:2780-2791 | (post-removal remap in boundary-cleanup commit) | `placement.buildings` (enumerate) | index (`in removed`), output_obj/input_obj remap | single-pass | once per cleanup pass (final commit) | HYGIENE | n/a — inherent rebuild |
| finalize.py:2809-2844 | `_prunable_open_belts` | `placement.buildings` (3 separate full passes: belts set, predecessors via O(1) `output_obj` lookup, nonbelt_references) | kind=belt, input_obj/output_obj | single-pass ×3 | once per build (last-mile / boundary cleanup) | HYGIENE (falls out for free) | `belts()` |
| finalize.py:2875-2889 | (open-boundary-belts helper) | `placement.buildings` (enumerate) | kind=belt, input_obj/output_obj None, tile-position vs side | single-pass, called once per side (×4) | once per cleanup pass | HYGIENE | `belts()` + `at_tile` bound check |
| finalize.py:2903-2906 | `_required_external_input_belts` | `placement.buildings` | kind=belt | single-pass | once per cleanup pass | WORTH | `belts()` |
| finalize.py:2908-2917 | `_required_external_input_belts` | `placement.buildings` (enumerate) | input_obj / output_obj | single-pass | once per cleanup pass | HYGIENE | reverse-link index |
| finalize.py:2922-2940 | `_required_external_input_belts` | `placement.buildings` (enumerate) | index, kind=belt, carries_item, tile-position | single-pass, compound predicate | once per cleanup pass | HYGIENE | `belts_carrying(item)` partially |
| finalize.py:2985-2988 | `_CleanupSurvivorGraph.__init__` | `self.buildings` | item_id (kind=belt) | single-pass — **index-construction site** | once per finalize/cleanup call | WORTH (this is where `Buildings` would be consumed) | `buildings.belts()` seed |
| finalize.py:2990-2991 | `_CleanupSurvivorGraph.__init__` | `self.buildings` (2 comprehensions) | input_obj, output_obj (column materialization) | single-pass ×2 | once per build | HYGIENE | direct field columns, no change needed |
| finalize.py:3006-3019 | `_CleanupSurvivorGraph.__init__` | `self.buildings` (enumerate) | input_obj/output_obj → builds intrusive linked-list owner-bags + indegree array | single-pass | once per build | **HYGIENE — already O(1)-incremental after construction via `extended()`/`_fork()`; do not replace with a generic re-queried index** | n/a |
| finalize.py:3210-3238 | `_CleanupSurvivorGraph.extended` | `extended.buildings` (appended slice, `range(old_size, size)`) | item_id, input_obj/output_obj | single-pass over the *new* slice only (not the whole sequence — genuinely incremental) | per cleanup-wave extension step | HYGIENE (already correct) | n/a |
| finalize.py:3475-3478 | `_enqueue_outer` | `records[coordinate]` (a boundary-coordinate bucket, not the full sequence) | tile-position bucket membership | bounded by bucket size, not a full scan | per cleanup queue pop | HYGIENE — **not actually a buildings-holder scan**, listed for completeness | n/a |

### validate.py

Every `@check(...)`-decorated function and its private helpers run once per
`validate()`/`certify()` call — once per finished placement handed to `certify()`
(`finalize.py:3702`, `3810`) or once per pipeline gate / racing-strategy call — never
once per placement-candidate-during-search. That is the key frequency distinction from
the `finalize.py` frame-search family above.

| file:line | function | holder | predicate | nesting | frequency | class | replacing query |
|---|---|---|---|---|---|---|---|
| validate.py:392-405 | `Context.of_kind` | `self.placement.buildings` | kind | single-pass, **memoized** in `ctx.cache.of_kind` per kind (docstring: ~30 call sites reuse it) | first call per kind per `Context` | **WORTH** | `by_kind(kind)` — replaces the whole ad hoc per-kind cache with upfront bucketing |
| validate.py:626-671 | `_build_runs` | `buildings` param (×2 passes) | kind=belt (precomputed `is_belt[i]`), output_obj/input_obj (predecessor counts) | single-pass ×2 | once/certify | HYGIENE | successor/predecessor index |
| validate.py:761 | `_context` | `placement.buildings` | item_id → Kind classification — **this computes `ctx.kinds` itself** | single-pass | once/certify (foundational) | **WORTH** | this is literally the kind-column a Buildings table would precompute |
| validate.py:764-771 | `_context` | `placement.buildings` (enumerate) | tile occupancy (x,y,z), is_belt_integrated | single-pass | once/certify | HYGIENE | `at_tile` build-out |
| validate.py:779-802 | `_context` | `placement.buildings` (enumerate) | kind=belt, output_obj/input_obj vs splitter/piler | single-pass | once/certify | HYGIENE | reverse-link (`junction_in`/`junction_out`) index |
| validate.py:1826-… | `_slot_occupancy` | `bs` alias | output_obj/input_obj + slot fields | single-pass (inner loop is a fixed 2-tuple, not nested over `bs`) | once/certify | HYGIENE | n/a |
| validate.py:2060-2069 | `_belts_by_tile` | `ctx.of_kind(Kind.BELT)` (cached bucket) | x, y (tile grouping) | single-pass, cached in `ctx.cache.belts_by_tile` | first call per Context | n/a (already the `at_tile` index) | this *is* the `at_tile(x,y)` query, already implemented |
| validate.py:2211-2214 | `_addon_supply` | `bs` alias | item_id (`is_belt_addon`) | single-pass | once/certify | HYGIENE | `belt_addons()` |
| validate.py:2228-2298 | `_addon_supply` | `bs` alias | item_id (`addon_areas`) | single-pass; per-addon inner work calls cached `_belt_in_addon_area` (uses `_belts_by_tile`, effectively O(1)) | once/certify | HYGIENE | n/a — already spatial-indexed downstream |
| **validate.py:2321-2344** | **`_addon_rides`** | **`bs` alias, `enumerate(bs)` nested inside a per-addon loop** | **kind=belt + exact tile (x,y,z) match** | **NESTED — O(addons × N buildings), confirmed quadratic-shaped** | **called 3× per `validate()` pass, UNCACHED** (lines 2426, 2532, 4910) — unlike every other derived structure in `Context`, this result is not memoized | **WORTH — strongest finding in the survey** | **`at_tile(x,y,z)`** — note `_belts_by_tile(ctx)` (validate.py:2060), an identical spatial index, already exists 260 lines above this function and is simply not used here |
| validate.py:2130-2137 | `_addon_belt_line_distance` | `ctx.of_kind(Kind.BELT)` fallback `next()` | output_obj equality (reverse-link search for a belt's predecessor) | single-pass over the cached belt bucket, fallback path only | per (addon, area) needing the fallback, uncached | WORTH (minor) | reverse `output_obj` index |
| validate.py:2694 | `_addon_crossings` | `bs` alias | kind=ADDON via `ctx.kinds` | single-pass | once/certify | HYGIENE | `by_kind(ADDON)` |
| validate.py:3314-… | `_port_docks` | `bs` alias | kind, ports | single-pass | once/certify, but its result is iterated by other checks (e.g. `_sprayed_cargo_reaches_machines` inside a per-item loop, validate.py:5350) | HYGIENE→WORTH if the caller re-derives it per item rather than caching the tuple once | `port_docks()` cached query |
| validate.py:3359-… | `_port_dock` (check) | `bs` alias | ports/slots | single-pass | once/certify | HYGIENE | n/a |
| validate.py:3490-3507 | `_belt_successors` | `ctx.placement.buildings` (direct index) | output_obj, kind | **O(1) lookup, not a scan** | called from `_acyclic`'s DFS, O(1) per call | n/a (already optimal) | this *is* the `successors(i)` query — expose directly |
| validate.py:3510-3562 | `_acyclic` (`belt.acyclic` check) | `ctx.of_kind(BELT/SPLITTER/PILER)` for start set + DFS over `_belt_successors` | kind buckets (cached) | iterative colored DFS, O(V+E), not a scan | once/certify | n/a (already correct/efficient) | see §3 |
| validate.py:3610-3620 | (lane-overshoot / termination-area check) | `ctx.placement.buildings` (bare for-loop, **not** via `of_kind`) | item_id → addon_areas | single-pass, raw scan (no kind bucket covers "multi-area addons" specifically) | once/certify | WORTH (minor, falls out free) | `NEW: multi_area_addons()` |
| validate.py:4052-… | `_internal_seeds` | `bs` alias | kind=belt, links | single-pass | once/certify | HYGIENE | n/a |
| validate.py:4411-4436 | `_reachable_from_outside` | `ctx.occupancy` (already `at_tile`-shaped) | **not a buildings scan** — BFS over the bounding-box grid | grid BFS, cached per z-level | once per distinct `b.z` value needing it | n/a | confirms `ctx.occupancy` = the `at_tile` query |
| validate.py:4920-5008 | `_unsprayed_belts` (proliferator spray-reach) | `ctx.of_kind(SORTER)` + `ctx.runs` / `ctx.pred` | sorter input_obj/output_obj, run-head predecessors | forward-reachability DFS/BFS, O(V+E) via cached buckets | once per distinct proliferated item, memoized in `unsprayed` dict (line 5059) | n/a (already correctly amortized) | see §3 |
| validate.py:5299-5313, 5315-5348 | max-flow capacity check (`machine.inputs_supplied` family) | `ctx.of_kind(BELT)` / `ctx.of_kind(SORTER)` | output_obj/input_obj, kind | single-pass over cached buckets, inside `for item in wanted_items:` | once per item — O(items × (sorters+belts)), the *correct* complexity for a per-item flow graph (compare `_SorterPeers` docstring, lines 283-292, documenting a previously-fixed true `sorters × buildings` quadratic bug) | HYGIENE (already fixed once; do not regress) | n/a |

### base.py

| file:line | function | holder | predicate | nesting | frequency | class | replacing query |
|---|---|---|---|---|---|---|---|
| base.py:539-540 | `Placement.bounds` (property) | `self.buildings` | none — min/max over x, y, width, height | **4 full single-passes per call, no caching** | **called on every access**, uncached: ~10× from `freeform.py`, ~8× from `finalize.py` (inside the frame-search hot path), ~6× from `validate.py`, frequently per placement candidate | **WORTH — likely the single highest-value target in the survey** | `NEW: bounds()`, maintained incrementally on construction/extension rather than recomputed from scratch every call |

### slots.py

| file:line | function | holder | predicate | nesting | frequency | class | replacing query |
|---|---|---|---|---|---|---|---|
| slots.py:745-750 | `sorter_seat_boxes` | `buildings` param | kind=sorter, index (`skip`) | single-pass; docstring explicitly notes it is built once per placement pass specifically to avoid cubic cost if rebuilt per candidate | once per placement pass (already deliberately hoisted out of the candidate loop) | WORTH (trivial win, already correctly amortized) | `buildings.sorters()` |
| slots.py:1189-1199 | `assign_belt_slots` (validation loop) | `buildings` param | item_id, model_index (splitter model check) | single-pass | once per finished placement (shared post-pass, both strategies) | HYGIENE | n/a |
| slots.py:1203-1207 | `assign_belt_slots` | `buildings` param | kind=belt, input_obj | single-pass | once per finished placement | HYGIENE | n/a |
| slots.py:1209-1264 | `assign_belt_slots` | `buildings` param | kind=belt, input_obj/output_obj slot bookkeeping | single-pass | once per finished placement | HYGIENE | n/a |
| slots.py:1273-1302 | `_assign_sorter_slots_only` | `buildings` param | is_belt_addon, kind=sorter | single-pass | once per finished placement | HYGIENE | `sorters()` / `belt_addons()` |

### junction.py

| file:line | function | holder | predicate | nesting | frequency | class | replacing query |
|---|---|---|---|---|---|---|---|
| junction.py:133 | `site_is_clear` | `buildings` param | item_id (`occupies_tiles`), x, y, width, height, yaw (distance) | single-pass, would be re-run **per candidate junction site (x,y)** by design | **no production caller** (see §4) | flag for confirmation, not for indexing effort | `at_tile`/proximity index, if kept alive |
| junction.py:303 | `check_ports` | `buildings` param | item_id == SPLITTER_ID | single-pass | **no production caller** (see §4) | flag for confirmation | n/a until re-wired |
| junction.py:307-312 | `check_ports` | `buildings` param | kind=belt, input_obj/output_obj (fan-in count) | single-pass | same as above | flag | n/a |

`make_splitter_stack` (junction.py:246-292) does **not** scan the placement's buildings —
its `buildings.append(...)` at line 291 builds a fresh, small, local list (the splitter
stack under construction), unrelated to the main placement sequence. Excluded from the
table as a false match on the holder-name heuristic.

### markers.py

| file:line | function | holder | predicate | nesting | frequency | class | replacing query |
|---|---|---|---|---|---|---|---|
| markers.py:45-49 | `input_belt_heads` | `placement.buildings` | output_obj (builds reverse "fed" set), kind=belt | single-pass | once/build ×2 (called from `mark_external_belts` and again from `unmarked_external_inputs`) | HYGIENE | `NEW:` reverse output_obj index |
| markers.py:50-56 | `input_belt_heads` | `placement.buildings` (enumerate) | kind=belt, index membership, connectivity (`_links_splitter`, O(1) per element) | single-pass | once/build ×2 | HYGIENE | `belts()` |
| markers.py:68-75 | `output_belt_tails` | `buildings` local | kind=sorter, output_obj, kind=belt (peer) | single-pass | once/build | HYGIENE | `sorters()` for the seed set |
| markers.py:76-93 | `output_belt_tails` | `buildings` | output_obj chain-walk from each start | **connectivity walk** (bounded chain length, not a full scan) | once/build | HYGIENE | see §3 |
| markers.py:112, 123, 135, 137, 143 | `mark_external_belts` | `buildings = list(placement.buildings)` | index assignment (`parameters` field); L137 does an O(N) tuple-equality check | single-pass ×2 (marking loops) + O(N) equality check | once per build | HYGIENE | n/a |

### last_mile.py, global_router.py, route_feedback.py, observe.py

None. Verified by reading every top-level `def`/`class` signature in each file plus a
full-text grep for `buildings`/`entities`/`placed`/`objects`/`records`/`bldgs`: these four
files operate exclusively on routing grids, cells, nets, paths, and feedback/observer
state — never on a `PlacedBuilding` sequence. The handful of `buildings` hits that do
appear (`global_router.py:119`, `observe.py:13,63`) are docstring prose, not code. The
one `cycle` reference in `global_router.py:673` (`AssertionError("cycle in relaxed A*
predecessor chain")`) is a defensive sanity check on A* grid-cell backtracking, unrelated
to belt `input_obj`/`output_obj` connectivity — a false lead ruled out, not a hit.

## 2. Mutation sites

Buildings sequences are treated as immutable tuples almost everywhere in these ten
files — copy-on-write (materialize a `list`, mutate by index, freeze back into a new
`Placement` via `dataclasses.replace`), not in-place tuple mutation. No file ever does
`placement.buildings.append(...)` or index-assigns directly into the tuple (impossible —
`Placement` and `PlacedBuilding` are both frozen dataclasses). Two real mutation sites:

1. **`markers.py:96-143`, `mark_external_belts`.** Phase: pipeline post-processing
   (external belt labelling), once per build. Materializes `buildings =
   list(placement.buildings)` (line 112), mutates entries in place at lines 123 and 135
   (`buildings[i] = replace(b, parameters=...)`), then freezes into a new `Placement` via
   `replace(placement, buildings=tuple(buildings), stats=stats)` at line 143.
2. **`finalize.py:3210-3238`, `_CleanupSurvivorGraph.extended(...)`.** Phase: last-mile
   belt-pruning/extension, one call per cleanup-wave extension step. `extended.buildings
   += additions` (line 3221) grows the tracker's own buildings tuple when new/replacement
   buildings are added during a cleanup wave; the parallel index arrays (`active`,
   `input_jump`, `output_jump`, `predecessors`, the owner-bag linked lists, and the
   boundary-coordinate records/counts/coordinates structures) are extended in lockstep
   over the newly-added slice only (`range(old_size, size)`), never rescanning the
   existing prefix — this is the private working-copy analogue of appending to
   `Placement.buildings`, not a mutation of the placement itself.

Any cache the `Buildings` abstraction keeps must be invalidated/extended at exactly these
two sites — nowhere else in these ten files does a buildings sequence change shape after
construction.

## 3. Connectivity walks

Four distinct hand-rolled graph structures exist over `input_obj`/`output_obj`, all
already O(V+E), none using networkx (repo-wide grep for `import networkx` / `from
networkx` returns zero hits):

1. **`validate.py:3490-3562` — `_belt_successors` / `@check("belt.acyclic") _acyclic`.**
   The belt-cycle check. Iterative (explicit stack, deliberately non-recursive — the
   docstring notes a 51-tile corridor chain would approach the interpreter's recursion
   limit) 3-color DFS (`colour` dict: 1 = on the current path, 2 = settled) over belt /
   splitter / piler successor chains, following flow-boundary crossings via
   `ctx.junction_out`. Runs once per `validate()` call.
2. **`validate.py:4920-5008` — `_unsprayed_belts`**, used by `@check
   ("prolif.sprayed_cargo_reaches_machines") _sprayed_cargo_reaches_machines`
   (validate.py:5011) — the proliferator spray-reach check. Forward-reachability DFS
   (explicit stack) over belt successors plus sorter-created "hop" edges, seeded from
   external-entry belts and machine-fed sorters, stopped at each Spray Coater. Called
   once per distinct ingredient item requiring the check, memoized in a dict — not once
   per belt or per machine.
3. **`validate.py:5188-5430` — the flow/demand graph** (`_add_flow_link`, feeding
   `predecessors: dict[int, set[int]]`), backing the belt-capacity/demand check family.
   Builds a reverse-adjacency dict from `input_obj`/`output_obj` and `ctx.run_of`, then
   walks it (`for previous in predecessors.get(node, ())`) to propagate downstream
   demand — a topological-order-ish accumulation over the belt/run graph, with explicit
   cycle handling ("cycles contribute nothing rather than looping forever," line
   6058-6059). Built once per `validate()` call, once per item within it.
4. **`finalize.py:2953-3038`, extended through 3210-3238 — `_CleanupSurvivorGraph`.** Its
   own predecessor array (`self.predecessors`) and doubly-linked owner lists
   (`input_head`/`output_head`/`*_next`) are built once from `input_obj`/`output_obj`,
   then incrementally maintained across successive belt-removal "waves" (`extended()`,
   `_fork()`) rather than rebuilt — the most sophisticated of the four, effectively a
   hand-built persistent index.

`markers.py:76-93` (`output_belt_tails`) additionally does a small bounded chain-walk
over `output_obj` per boundary-output start, terminating at a splitter or non-belt — a
point-to-point successor chase, not a full-graph traversal.

**networkx verdict: no.** All four structures are already linear-time, correctly avoid
recursion-depth blowups, and are invoked at most once per `validate()`/cleanup-pass
call — never per placement candidate. Introducing networkx would add a real dependency
and object/edge-construction overhead to replace code that is neither the bottleneck nor
broken. The higher-value move is exposing `successors(i)` / `predecessors(i)` /
`at_tile(x,y,z)` as first-class `Buildings` accessors so `_belt_successors`,
`_CleanupSurvivorGraph`, `_belts_by_tile`, and the flow-demand builder stop each
re-deriving similar adjacency from raw `input_obj`/`output_obj` fields independently.

## 4. Dead code: `junction.site_is_clear` and `junction.check_ports`

Both functions appear to have **no production caller** in the repository:

- `junction.site_is_clear` (junction.py:89-147): a repo-wide grep for
  `junction.site_is_clear` and for `site_is_clear(` in every file importing `junction`
  turns up only its own definition and its own docstring self-reference
  (`freeform.py:9253`, prose only: *"junction.site_is_clear asks the machine half"*).
  `freeform.py` — the only strategy that would plausibly need it — has its own
  separately-implemented, differently-shaped local function `_junction_site_is_clear`
  (freeform.py:5483), which takes a 1-tuple `(obstacle,)` rather than the full buildings
  sequence, and is what it actually calls (freeform.py:5548, 5602). `hierarchy/compose.py`
  imports the `junction` module (`from flab2bp.layout import junction, slots`) but its
  only use of it is `junction.keepout_cells(...)` (compose.py:447) — never
  `junction.site_is_clear`.
- `junction.check_ports` (junction.py:295-320): same pattern — a repo-wide grep for
  `check_ports(` outside `junction.py` and outside the test tree finds no call sites.

Two independent passes (a manual grep-the-callers trace and a separate AST-driven scan)
converged on the same conclusion. Recommend confirming with the user whether these are
intentionally-kept public API, slated for deletion, or should be wired back into
`freeform.py` in place of its local duplicate — folding either into the `Buildings` index
is wasted effort if they stay dead, and `freeform.py`'s `_junction_site_is_clear` should
probably be surveyed separately since it is the one actually on a hot path (called per
candidate junction site during routing).

## 5. Ranking by (nesting × call frequency)

Files ordered by how much scanning work they actually contribute, worst first:

1. **`validate.py`** — highest total scan volume: it hosts the confirmed quadratic site
   (`_addon_rides`, called 3× uncached per `validate()` pass) plus ~25 single-pass
   `@check` scans that each run once per build but compound across dozens of checks
   (roughly 40N work per `validate()` call). It also owns the four connectivity
   walks (all O(V+E), not scans, but real work). Highest priority for the `Buildings`
   abstraction because `_context()` (its index-construction site) is exactly where
   `Buildings` would be built and consumed once, collapsing ~6 of its own manual index
   arrays into one object.
2. **`finalize.py`** — second-highest: hosts `_projection_invariants` /
   `_power_nodes` / `_planet_sorters`, which re-scan per distinct frame candidate (memoized,
   but still real per-candidate work across a placement's certification search), plus
   `first_projected_static_failure`'s per-placement-candidate scan and linear index
   search, plus the `_CleanupSurvivorGraph` construction/extension machinery. The
   frame-candidate loop means its scans are the closest thing in this file set to
   "nested in a search loop."
3. **`base.py`** — small file, one site, but that site (`Placement.bounds`) is called
   **uncached, from inside both `finalize.py`'s and `validate.py`'s hot paths, and from
   `freeform.py`'s search loop** roughly 24+ times traced. Per-call cost is only 4×O(N),
   but call frequency is high enough that this ranks above `slots.py`/`junction.py`
   despite having far fewer distinct sites.
4. **`slots.py`** — several single-pass scans, but every one is already deliberately
   hoisted to run once per placement pass or once per finished placement (the
   `sorter_seat_boxes` docstring explicitly documents this design choice to avoid cubic
   cost). Genuinely low-priority: correctness-neutral hygiene only.
5. **`markers.py`** — small, single-digit sites, all once-per-build, one minor
   connectivity chain-walk. Low priority.
6. **`junction.py`** — two functions with scan sites, but both are dead code (no
   production caller, §4) — zero actual runtime cost today. Lowest priority until/unless
   revived.
7. **`last_mile.py`, `global_router.py`, `route_feedback.py`, `observe.py`** — zero
   buildings-holder scans. Excluded from further ranking; no work needed here.
