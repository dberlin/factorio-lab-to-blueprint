# Survey: hierarchy, solver, dsp, bench, web

## Part 1 — `layout/hierarchy/*` and the sequence solver family

**Files with no `PlacedBuilding`-sequence scans at all** (verified by grep for
`buildings` / `entities` / `placed` / `objects` / `input_obj` / `output_obj` /
`PlacedBuilding`): `hierarchy/partition.py` (operates on `spec.groups` /
`MachineGroup`, pre-placement), `hierarchy/pressure.py` (same),
`hierarchy/strategy.py` (none of its own — only forwards
`composition.placement.buildings` into `assign_sorter_slots`),
`sequence_solver.py` (its two `buildings` hits are `failure.buildings`
collision-index tuples), `sequence_pair.py`, `sequence_islands.py`,
`sequence_alns.py`, `compact_seed.py`, `strategy_race.py`.

| # | file:line | function | holder | predicate keys | nesting | frequency | verdict | replacing query |
|---|---|---|---|---|---|---|---|---|
| 1 | contracts.py:64 | `_machines_behind` | one block's `buildings` tuple | owner_strip, recipe_id | single-pass, but invoked once per index inside `_apportion`'s `for i in indices` loop (:164) | per block x per boundary-lane index, once per hierarchical build | **WORTH** | `NEW: machines_for_strip(strip)` |
| 2 | contracts.py:77-88 | `_belt_run` (onward-map build) | one block's `buildings` tuple | kind(belt), output_obj / input_obj, plus an inner scan rediscovering belts drawn off a splitter/piler junction | **nested double loop, O(n^2) worst case** | per (block, boundary-lane index) lacking `owner_strip`, once per build | **WORTH — strongest in contracts.py** | `NEW: belt_successors(i)` / `belt_predecessors(i)`, built once per block |
| 3 | contracts.py:117 | `_machines_on_lane` | one block's `buildings` tuple | kind(sorter), input_obj / output_obj, recipe_id | single-pass O(n) per call | per boundary-lane index inside `_apportion`'s loop -> per-block x per-lane rescans | **WORTH** | `sorters_into(belts)` / `sorters_out_of(belts)` |
| 4 | contracts.py:205, 208 | `boundary_lanes` (`sorter_fed` / `sorter_drawn`) | `buildings` | kind(sorter), output_obj / input_obj | single-pass x2 | once per block, once per build | HYGIENE | `sorters_out_of()` / `sorters_into()` |
| 5 | compose.py:221 | `_normalize` | `placement.buildings` | none — coordinate-shift map | single-pass | per block, per pack attempt (<=6 rungs/build) | HYGIENE | n/a (map, not a query) |
| 6 | compose.py:315 | `_translate` | `placement.buildings` | none — coordinate + link rebase map | single-pass | per block, per pack attempt | HYGIENE | n/a (map) |
| 7 | compose.py:429 | `canvas_for` | whole composed canvas | kind via item_id (sorter/coater/belt+splitter/other) | single-pass over the FULL canvas | per pack attempt (<=6/build) | HYGIENE (unavoidable canvas build, but the natural place to source from an index) | `NEW: by_kind()` groups instead of re-classifying |
| 8 | compose.py:476 | `_lane` (`prev` reverse map) | whole composed canvas | output_obj link | single-pass build, **rebuilt on every call** | via `_port`, called **twice per `LaneFlow`/cut** inside `_pack_at`'s net loop (:715-737) -> O(flows x canvas size), x6 rungs/build | **WORTH — standout site** | `NEW: predecessor_by_output_obj`, precomputed once per pack attempt |
| 9 | compose.py:551 | `_machines_behind` (compose's own) | `buildings[block.base:stop]` | recipe_id, owner_strip | single-pass over block slice | twice per `LaneFlow` (src+dst) in `_pack_at`'s net loop | **WORTH** | `NEW: machines_for_strip(block, strip)` |
| 10 | strip_variants.py:607 | `projection_pitch_requirements` | one candidate's full building list | kind(machine) via `_is_machine_building`, owner_strip, item_id, model_index, yaw, width, height | single-pass O(n), not nested internally | **per candidate state** in the sequence-pair anneal search, via `_stage_projection_pitch_requirement` (sequence_solver.py:2649, :5639) — unconditional every stage evaluation | **WORTH — hottest call site** | `NEW: machines_by_key()` built once per placement |

Rows 5, 6, 7 are pure single-pass maps with no repeat-rescan pattern, hence
HYGIENE despite running up to 6x/build: cost scales with canvas size once, not
with flow or candidate count. Rows 1-3, 8, 9 are WORTH because the *same* full
scan is redone once per lane-index or once per flow instead of being computed
once and reused. Row 10 is WORTH purely on call frequency.

### Mutation sites

- `compose.py:431`, `:434` — `canvas.buildings.append(b)` in `canvas_for`
  (packing phase, once per pack attempt).
- `compose.py:709` — `buildings.extend(_translate(...))` in `_pack_at`,
  assembling the composed list block-by-block (packing phase).
- `compose.py:942`, `:1029` — `Placement(buildings=tuple(canvas.buildings), ...)`
  in `_budget_refusal` / `compose`: freezing the canvas (once per build).
- `strategy.py:787-789` — `replace(composition.placement,
  buildings=assign_sorter_slots(composition.placement.buildings))`: functional
  replace of the whole tuple after sorter-slot assignment (once per build).

No `PlacedBuilding` mutation in `contracts.py` (pure/read-only),
`strip_variants.py`, or any `sequence_*` / `compact_seed` / `strategy_race`
file.

### Connectivity walks

`input_obj` / `output_obj` occur only in `contracts.py` and `compose.py`:

- **contracts.py:67-103 `_belt_run`** — builds a directed adjacency map
  (`onward`, reverse `backward`) over belt links, crossing splitters/pilers via a
  nested rediscovery scan, then an explicit **BFS with a visited set**
  (lines 95-103). Genuine reachability, rebuilt from scratch on every call.
- **compose.py:468-511 `_lane`** — follows `output_obj` forward and a
  locally-built predecessor map backward to find the maximal contiguous belt run
  through a lane head, then restricts to one row. Linear chain-follow, rebuilt
  per call.

No connected-components, cycle check or topological sort anywhere in these 12
files. The higher-value fix is a precomputed successor / predecessor index
shared across calls within one pack attempt or block — not a graph library.

## Part 2 — `dsp/*`, `bench/metrics.py`, `web/*`, `pipeline.py`, `spec.py`

**Scope note.** `dsp/colliders.py` and `dsp/planet.py` never receive
`PlacedBuilding` directly — callers convert to lightweight `colliders.Placed` /
`Preview` / `SorterPreview` structs first. Rows cover those functions' internal
scans as the analogous holder iteration. `dsp/provenance.py`, `pipeline.py`,
`spec.py` and `web/payload.py` contain **no** building-sequence scans.

| # | file:line | function | holder | predicate keys | nesting | frequency | verdict | replacing query |
|---|---|---|---|---|---|---|---|---|
| 1 | bench/metrics.py:56-60 | `measure` | `placement.buildings` | kind, tile-position | single-pass | offline (bench only) | HYGIENE | `at_tile` / bulk occupancy |
| 2-5 | bench/metrics.py:62-65 | `measure` | `buildings` | kind(machine), kind(belt), kind(sorter), item_id | 4 separate single passes | offline | HYGIENE | `NEW: count_by_kind(...)` / `count_by_item(...)` |
| 6 | bench/metrics.py:67 | `measure` | `buildings` | kind(machine) + index | single-pass | offline | HYGIENE | `NEW: indices_by_kind(machine)` |
| 7 | bench/metrics.py:68-74 | `measure` | `buildings` | kind(sorter), input_obj, output_obj | single-pass, uses a precomputed set | offline | HYGIENE | `sorters_between(machine_indices)` |
| 8 | bench/metrics.py:76 | `measure` | `buildings` | z only | single-pass | offline | HYGIENE | n/a |
| 9-11 | dsp/colliders.py:1116-1158 | `collisions` | `list[Placed]`, `targets` | tile-position (32-unit 3D cell hash, 26-neighbour) | single-pass building its **own spatial index** | per pack attempt + per validation pass | HYGIENE — already an index | n/a |
| 12 | dsp/colliders.py:1334-1355 | `sorter_collisions` | `Sequence[SorterPreview]` | tile-position (8-unit cell hash) | own spatial index | once per validation pass | HYGIENE | n/a |
| 13 | dsp/colliders.py:1543-1554 | `belt_crossings` | `belts` x `buildings` nested | tile-position, sphere-vs-OBB, **no internal index** | **nested triple loop, quadratic if given full sets** | called only with singleton `[probe]` / `[pose]` lists (validate.py:2749, freeform.py:18632); callers pre-tile | **WORTH** (flag: safe today only because every caller pre-tiles) | the `at_tile`-backed bucket callers build ad hoc |
| 14 | dsp/colliders.py:1748-1781 | `_belt_overlap_candidates` | `previews` | kind(belt) + 8-unit tile bucket | own spatial index | per pack attempt / validation pass | HYGIENE — already an index | n/a |
| 15 | dsp/colliders.py:1630-1635 | `paste_input_links` | `previews` | kind(belt) + output_obj chase | single-pass, **builds a reverse index of output_obj -> predecessor** | once per `belt_collisions` / `stable_belt_collisions` call | **WORTH** | `NEW: belts_into(i)` |
| 17 | dsp/colliders.py:1810-1822 | `_reverse_input_choices` | `previews` | kind(belt) + output_obj, full multi-feeder reverse index | single-pass | once per `stable_belt_collisions` call | **WORTH** | `NEW: all_predecessors_by_output_obj()` |
| 19 | dsp/colliders.py:1904-1922 | `stable_belt_collisions` | pre-indexed candidates | none | single-pass | per pack attempt / validation pass | HYGIENE | n/a |
| 20 | dsp/planet.py:998-1001 | `candidate_pairs` | `Sequence[Placed]` | radius lookup | single-pass | per candidate/band | HYGIENE | n/a |
| 21 | dsp/planet.py:1008-1024 | `candidate_pairs` (focused branch) | `buildings` | scaled-ellipsoid gap vs radius sum | single-pass **per new building against all peers** | once per placed building during packing -> **O(N) per building, O(N^2) across a build** (deliberate incremental broad-phase) | **WORTH** (accumulating quadratic, though individually necessary) | tile/radius-bucketed neighbour query |
| 22 | dsp/planet.py:1029-1055 | `candidate_pairs` (bucketed branch) | `buildings` | column-bucket by `x/span` | own spatial index ("linear in near pairs, not quadratic") | once per full collision pass | HYGIENE — already an index | n/a |
| 23 | dsp/planet.py:1104-1113 | `collisions_at` (pairs=None fallback) | `buildings` | none — **literal O(n^2) all-pairs generator** | quadratic; the docstring admits it | **not exercised**: every caller supplies pre-filtered `pairs` first | **WORTH flagging as a latent trap** | keep `pairs` pre-filtered |
| 24-25 | dsp/planet.py:1126-1148 | `collisions_at` | `wanted` / `pairs` | index membership | single-pass over subset, cached | per candidate | HYGIENE | n/a |
| 26 | dsp/splitter_ports.py:112-123 | `_NodeIndex.build` | `nodes` | kind(belt) + output_obj / input_obj; builds `by_id`, reverse-predecessor-by-output_obj, attachments-by-splitter-id | single-pass — **a hand-rolled Buildings index already** | once per slot-assignment pass and once per validation pass | **WORTH — direct precedent, model the abstraction on it** | `by_index`, `belts_into(splitter_id)` / `belts_out_of` |
| 27-28 | dsp/splitter_ports.py:133-174 | `_raw_placement_nodes` / `_blueprint_nodes` | `Sequence[PlacedBuilding]` / `Sequence[BlueprintBuilding]` | none (projection) | single-pass | as #26 / decode-side | HYGIENE | n/a |
| 29 | dsp/splitter_ports.py:460-467 | `_issues` | `nodes` | item_id == SPLITTER_ID outer, then O(1) index lookup | single-pass outer + indexed inner | once per `placement_issues` / `blueprint_issues` | **WORTH** | `NEW: splitters()` |
| 30 | dsp/splitter_ports.py:598-603 | `placement_port_context` | `buildings` | builds index once, reused via `PlacementPortContext` | **build-once/query-many — already the target pattern** | once per slot-assignment pass | HYGIENE — the model for the abstraction | n/a |
| 31 | dsp/splitter_ports.py:606-613 | `expected_placement_port` | `buildings` | **rebuilds the full index every call** | single-pass, re-run per call | **dead code — zero callers repo-wide** | **WORTH flagging as a latent trap** | build atop #30/#26's index if ever wired up |
| 32-33, 35 | dsp/codec.py:214-225, 282-283, 319-370 | `_area_for`, `placement_to_blueprint` | `placement.buildings` | none (bounds / projection / classification) | single-pass | once per emit | HYGIENE | n/a |
| 34 | dsp/codec.py:285-316 | `placement_to_blueprint` (splitter-anchor fixup) | `placement.buildings` | kind(belt) outer + output_obj/input_obj peer (O(1)) + item_id == SPLITTER_ID on peer | single-pass outer, O(1) inner | once per emit | WORTH-leaning-HYGIENE (already cheap, clean fit) | `belts()` |
| 36 | web/trace.py:75-101 | `frame_json` | `placement.buildings` | none (stride sampling, then projection) | single-pass | throttled per sampled observer event; the file's docstring calls itself "THE ONLY PLACE that walks `placement.buildings`" | HYGIENE | n/a |

### Mutation sites

**None** in any of these ten files. They only read placement / blueprint records
and construct new tuples.

### Connectivity walks

- **`web/trace.py` — NOT a walker.** `frame_json` emits `output_obj` /
  `input_obj` as raw numbers per row for the client to render; it never chases
  the chain. Its `deque`s are bounded ring buffers.
- **`dsp/colliders.py` — walks, but bounded and non-general.** `_hops`
  (1638-1660) walks a belt's own run forward or backward for exactly 1-3 hops,
  stopping at the first non-belt, replaying DSP's own bounded rescue rule
  (`CheckBuildConditions` 147443-147453). `_upstream_rescue_for_every_choice`
  (1832-1869) is a memoized recursive walk over the reverse-feeder map, branching
  at every merge, still capped at `hop == 3` and memoized on `(node, hop)`.
  `paste_input_links` and `_reverse_input_choices` build the reverse-adjacency
  maps — index construction, exactly the primitive a graph walk would need.
- **`dsp/splitter_ports.py`** builds reverse-index maps but only ever does one
  hop.
- **No file in this set does general reachability, connected components, cycle
  detection or topological sort.** Every chain walk is hard-capped at 1-3 hops to
  replicate a specific decompiled game rule. This does not justify networkx; the
  `Buildings` index's value here is supplying the reverse-adjacency maps that
  `paste_input_links`, `_reverse_input_choices` and `_NodeIndex.build` currently
  hand-roll per call.
