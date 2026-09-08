# Survey: `src/flab2bp/layout/freeform.py`

55 classified sites. The naive grep in the brief found 10; the real population
is 55, because most scans are comprehension filters, `next(...)` lookups,
`min`/`max` passes and guarded `buildings[i]` lookups rather than a bare
`for b in buildings`.

| file:line | function | holder | predicate keys | nesting | frequency | verdict | replacing query |
|---|---|---|---|---|---|---|---|
| 1738 | `_staged_static_projection_peers` | `enumerate(buildings)` (full canvas) | kind(belt,sorter), owner_strip | inside per-strip x per-item x per-seat loop at 18909 — **quadratic-or-worse** | per placement candidate (coater seat) | **WORTH** | `NEW: peers_excluding_strip(owner_strip)` |
| 5300 | `_building_collider_hits` | `enumerate(buildings)` | kind(belt,sorter), item_id, tile(x,y) | per stack member from 5490/5940/9753 — **quadratic** | per router step | **WORTH** | `NEW: near_tile(x, y, radius, kind='machine')` |
| 5322 | `_building_collider_hits` | `obstacles` (derived) | none | single-pass over survivors | per router step | HYGIENE (falls out of 5300) | — |
| 5369 | `_coater_keepout_hits` | `enumerate(buildings)` | kind(belt,sorter), z, tile(x,y,w,h) | from 18816 (per seat) and 18434 — **quadratic** | per placement candidate | **WORTH** | `NEW: in_box(x0,y0,x1,y1,z)` |
| 5454 | `_power_coverage_discs` | `buildings` | item_id (cover_radius) | single-pass | per pack attempt | HYGIENE | `NEW: power_sources()` |
| 5622 | `_prepared_junction_ban` | `buildings` | kind(belt,sorter) | single-pass, paired with 5671 | per pack attempt | **WORTH** (two full passes on the prepare hot path) | `machines()` |
| 5644 | `_prepared_junction_ban` | `obstacles` (derived) | item_id, model_index, w, h, yaw, z | single-pass | per pack attempt | HYGIENE | — |
| 5671 | `_prepared_junction_ban` | `enumerate(buildings)` | item_id (`SPRAY_COATER_ID`) | single-pass | per pack attempt | **WORTH** (free once 5622 converts) | `by_item(SPRAY_COATER_ID)` |
| 5935 | `_Canvas.junction_is_clear` | `self.buildings` | item_id (`SPLITTER_ID`) | inside per-tap-cell `_can_junction` and per `_splitter_stack_geometry` member — **quadratic** | per router step | **WORTH** | `by_item(SPLITTER_ID)` |
| 6041-6044 | `_core_bounds` | `canvas.buildings` | x, y, x+width, y+height | **4 separate full passes** | per pack attempt x 4 call sites (15270, 17058, 18709, 18711) | **WORTH** | `NEW: bounds()` |
| 6925 | `_flank_lane` | `out_lane` -> `canvas.buildings[i].x` | tile(x) | inside `for m_idx in machines` (6913) — **quadratic in strip machines** | per emit | **WORTH** | `at_tile(gx, lane_y, z)` |
| 7221 | `_dock_lane` | `out_lane` -> `canvas.buildings[i].x` | tile(x) | inside `for machine_index in machines` (7190) — **quadratic** | per emit | **WORTH** | `at_tile(dock.cell[0], lane_y, z)` |
| 8784 | `_junction_geometry_required` | `nets` indexing `buildings[...]` | output_obj, index | single-pass over nets | per pack attempt | HYGIENE | `by_index(i)` |
| 8883 | `_protected_template_belt_indices` | `enumerate(templates)` | kind(belt) | pass 1 of 2 | per prepared candidate | **WORTH** | `belts()` |
| 8886 | `_protected_template_belt_indices` | `templates` | kind(belt), input_obj, output_obj | pass 2 of 2 | per prepared candidate | **WORTH** | `NEW: link_targets_of(kind != 'belt')` |
| 8904 | `_prepared_candidate_area_lower_bound` | `enumerate(problem.building_templates)` | kind(belt), index | followed by 4 min/max at 8911-8914 | per prepared candidate | **WORTH** | `NEW: bounds(where=...)` |
| 8911-8914 | `_prepared_candidate_area_lower_bound` | `survivors` | x, y, width, height | 4 more passes | per prepared candidate | **WORTH** | `NEW: bounds(...)` |
| 9758 | `_route_all` | `enumerate(canvas.buildings)` | kind(belt), output_obj | single-pass building `building_predecessors` | per pack attempt | **WORTH** (this *is* the reverse index) | `NEW: belts_into(i)` |
| 12500 | `_commit_paths` | `enumerate(canvas.buildings)` | output_obj | single-pass building `into`, then incrementally maintained | per commit -> per router repair round | **WORTH** | `NEW: predecessors_of(i)` |
| 12581 | `_commit_paths` | `range(previous_count, len(canvas.buildings))` | output_obj, index | inside per-net loop | per net per commit | **WORTH** | `NEW: added_since(n)` |
| 12602 | `_commit_paths` | `range(previous_count, len(...))` | item_id (`SPLITTER_ID`), index | inside per-net loop | per net per commit | **WORTH** | `NEW: by_item(SPLITTER_ID, since=n)` |
| 12615 | `_commit_paths` | `canvas.buildings` | model_index, x, y, z, w, h, yaw | single-pass (preview build) | per commit, only when splitters added | HYGIENE (must touch every record) | `all()` |
| 12825 | `_splitter_successors` | `enumerate(canvas.buildings)` | input_obj, item_id of target | full scan, **recomputed at 12660, 12846, 12940, 12976** | per commit + per `_leads_back` / `_committed_path_closes_cycle` default call | **WORTH** | `NEW: by_input_obj(i)` |
| 12873-12883 | `_output_tail_nets` | `canvas.buildings[index]` walk | item_id, kind(belt), carries_item, output_obj | DFS per net over the belt graph | per pack attempt | **WORTH** | `belts_carrying(item)` + `by_input_obj(i)` |
| 12891 | `_output_tail_nets` | `tails` (derived, small) | tile(x,y,z) | inside `min(key=...)` | per net | HYGIENE | `by_index(i)` |
| 13294 | `_tap_source` | `enumerate(canvas.buildings)` | kind(belt), output_obj | full rebuild when `predecessor_choices is None`; callers 7151 (per machine, emit), 19487 — **quadratic** | per emit / per tap | **WORTH** | `NEW: belts_into(i)` |
| 13319 | `_tap_source` | `enumerate(canvas.buildings)` | input_obj, output_obj == `junction_idx` | inside per-tap path — **quadratic** | per net per commit | **WORTH** | `NEW: attached_to(i)` |
| 13353 | `_tap_source` | `enumerate(canvas.buildings)` | kind(belt), output_obj == `belt_idx` | inside per-tap path — **quadratic** | per net per commit | **WORTH** | `belts_into(belt_idx)` |
| 14139 | `_ProjectedObstacleIndex.build` | `list(enumerate(canvas.buildings))` | kind(belt,sorter), model_index, yaw, x, y, z | single-pass + `bisect` insert | per pack attempt | **WORTH** (this hand-rolled x-sorted index is subsumed by `Buildings`) | `NEW: machines_sorted_by_x()` |
| 14231 | `_ProjectedObstacleIndex.candidates_for_bands` | `self.obstacles[lo:hi]` | x, y, z, w, h | bisect-narrowed slice | per placement candidate | HYGIENE (already indexed) | `NEW: near_tile(...)` |
| 14732 | `_prospective_static_failure` | pre-narrowed `(idx, b)` tuple | kind(belt,sorter) | inside per-candidate loop | per placement candidate | HYGIENE (already narrowed) | `machines()` on the sub-list |
| 14850 | `_projected_coater_junction_bans_by_frame` | `coaters` (pre-filtered) | tile(x,y) | single-pass over coaters | per pack attempt | HYGIENE | `coaters()` |
| 15273/15277 | `_power_projection_envelope` | `tuple(canvas.buildings)` | none (materialisation) | single-pass copy | per pack attempt | HYGIENE | `all()` |
| 15440 | `_power_plan` | `canvas.buildings` | item_id, kind(belt), tiles | single-pass | per pack attempt | HYGIENE (needs every tile) | `all()` |
| 15508 | `_power_plan` | `enumerate(canvas.buildings)` | item_id (power_node), x, y, z, w, h | single-pass, **second full scan in the same function** | per pack attempt | **WORTH** | `NEW: power_nodes()` |
| 15541 | `_power_plan` | `list(enumerate(canvas.buildings))` | none | single-pass copy | per pack attempt | HYGIENE | `all()` |
| 17425/17474 | `_prepare_routing_problem` | `tuple(canvas.buildings)` | none | single-pass copy x2 | per pack attempt | HYGIENE | `all()` |
| 17445 | `_prepare_routing_problem` | `enumerate(canvas.buildings)` | item_id (`SPRAY_COATER_ID`) | single-pass | per pack attempt | **WORTH** | `by_item(SPRAY_COATER_ID)` |
| 18047 | `_build_prepared` | `canvas.buildings[tower_start:]` | index | slice | once per build | HYGIENE | `NEW: added_since(n)` |
| 18089 | `_build_prepared` | `wired` | item_id (`PILER_ID`) | single-pass | once per build (stats) | HYGIENE — explicitly single pass, once per build | `NEW: count_by_item(PILER_ID)` |
| 18098 | `_build_prepared` | `canvas.buildings` | kind(belt) | single-pass | once per build (stats) | HYGIENE — single pass, once per build | `NEW: count(kind='belt')` |
| 18209 | `_bridge.is_machine` | `buildings[index]` | owner_strip, kind(belt,sorter), recipe_id, parameters | O(1) lookup in two comprehensions | per direct-insert candidate | HYGIENE | `by_index(i)` |
| 18219 | `_bridge` | `canvas.buildings` | kind(sorter), input_obj, output_obj, source_tiles set | inside direct-insert loop at 16719 — **quadratic** | per placement candidate | **WORTH** | `sorters_out_of(machine)` / `NEW: sorters_between(srcs, dsts)` |
| 18228 | `_bridge` | `buildings` | kind(sorter), input_obj, output_obj | mirror of 18219 — **quadratic** | per placement candidate | **WORTH** | `sorters_into(machine)` |
| 18521 | `_coater_seats` | `port.tiles[start:stop]` -> `canvas.buildings[i]` | index, tile(x,y) | bounded slice | per coater port | HYGIENE | `by_index(i)` |
| 18703 | `_place_coaters` | `enumerate(canvas.buildings)` | item_id (`SPLITTER_ID`) | single-pass | per pack attempt | **WORTH** | `by_item(SPLITTER_ID)` |
| 18719 | `_place_coaters` | `enumerate(canvas.buildings)` | kind(belt), z denominator, tile(x,y,z) | single-pass building `belt_at` | per pack attempt | **WORTH** (this dict *is* `at_tile`) | `at_tile(x, y, z)` |
| 18816 | `_place_coaters` -> `_coater_keepout_hits` | `prospective` | see 5369 | per strip x per item x per seat — **quadratic-or-worse** | per placement candidate | **WORTH** | `NEW: in_box(...)` |
| 18909 | `_place_coaters` -> `_staged_static_projection_peers` | `prospective` | see 1738 | per seat — **quadratic-or-worse** | per placement candidate | **WORTH** | `NEW: peers_excluding_strip(...)` |
| 18918 | `_place_coaters` -> `_prospective_static_failure` | narrowed tuple | index | per seat, over narrowed peers | per placement candidate | HYGIENE | `by_index(i)` |
| 3689 | `_exact_retry_evidence` | `failure.buildings` -> `buildings.get(index)` | index, item_id, model_index, z, w, h | single-pass over a short tuple | per rejected finding | HYGIENE | `by_index(i)` |
| 22195 | `FreeformLayout._sweep` | `dict(enumerate(placement.buildings))` | index | full materialisation inside the per-failure learning loop | per pack attempt (per failure) | **WORTH** (built solely to serve `by_index`) | `by_index(i)` |
| 9791, 12760, 12799, 12948, 12978, 13127, 13156, 13204, 13237, 13440, 13474, 9281 | `_direct_tap_clear`, `_source_for`, `_sink_for`, `_leads_back`, `_committed_path_closes_cycle`, `_run_cells`, `_belt_keepout_blockers`, `_tap_source.reaches_tap_downstream`, `_junction_belt_clear` | `canvas.buildings[i]` guarded by `0 <= i < len(...)` | index | O(1) lookups, not scans | per router step | HYGIENE (all become one `by_index(i)` returning `None` out of range) | `by_index(i)` |

## Mutation grammar of the live canvas

Every append goes through `_Canvas.add` (5889 `self.buildings.append(b)`)
**except four raw appends**, and the only removal is a tail-only `pop()`.

| file:line | function | phase | shape |
|---|---|---|---|
| 5889 | `_Canvas.add` | all | `append` — the sanctioned insertion point; also writes `blocked` / `solid` / `world_taken` |
| 6491, 6503 | `_emit_piler_tail` | strip emit | `canvas.add` |
| 6497 | `_emit_piler_tail` | strip emit | `canvas.buildings[previous] = replace(...)` |
| 6686, 6708 | `_emit_strip` | strip emit | `canvas.add` |
| 6701 | `_emit_strip` | strip emit | in-place relink at index |
| **6960** | `_flank_lane` | strip emit | **raw `canvas.buildings.append(...)` — bypasses `add`** |
| 6932 / 6947 | `_flank_lane` | strip emit | `canvas.add` / in-place relink |
| 7118 / 7133 | `_dock_input_lane` | strip emit | `canvas.add` / in-place relink |
| 7229 / 7248 | `_dock_lane` | strip emit | `canvas.add` / in-place relink |
| **7321** | `_link_lane` | strip emit | **raw append — bypasses `add`** |
| 12467 | `_commit_paths` | routing commit | `canvas.add` (one belt per routed cell) |
| **12444** | `_commit_paths.roll_back_prefix` | routing commit | **`canvas.buildings.pop()`** — asserts the popped index is the tail |
| 12492 | `_commit_paths` | routing commit | in-place relink |
| 13299, 13500 | `_tap_source` | tap commit | in-place relink |
| 13489, 13503, 13527 | `_tap_source` | tap commit | `canvas.add` |
| 13763 / 13779, 13781 | `_route_boundary_nets` | boundary routing | `canvas.add` / in-place relink |
| 15943 | `_place_power` | power placement | `canvas.add` |
| 16392 / 16407 | `_place_shared_external_input_trunks` | pre-routing emit | `canvas.add` / in-place relink |
| **18302** | `_bridge` | direct-insert emit | **raw append** |
| 18360 / 18375 | `_emit_coater_node` | emit | `canvas.add` / in-place relink |
| **19267** | `_place_coaters` | coater staging | **raw append** (index asserted `== candidate.port.coater`) |
| 19255, 19260 | `_place_coaters` | coater staging | `canvas.add` |
| 19438, 19461 / 19450, 19475 | `_proliferator_supply_tree` | proliferator emit | `canvas.add` / in-place relink |
| 19573 | `_place_proliferator_entry` | proliferator emit | `canvas.add` |

**Implication.** All growth is tail-append, all removal is tail-pop, and every
in-place write is a `_relink` / `replace` touching only `input_obj` /
`output_obj` (and `z` at 13503 / 13315). Geometry — `x`, `y`, `width`,
`height`, `item_id`, `model_index`, `owner_strip` — is **never** rewritten after
insertion. So geometry / tile / item / kind indexes need only append and
truncate; only the link indexes need per-relink maintenance, which
`_commit_paths.refresh_predecessor` (12504) already hand-rolls.

The four raw appends (6960, 7321, 18302, 19267) and the pop (12444) bypass
`_Canvas.add`, so an index hooked into `add` would silently miss them. Wrap the
**list itself**, which no call site can bypass.

## Connectivity walks

freeform walks connectivity in six places, all over `output_obj` forward edges
plus splitter branch edges from `input_obj`. `networkx` is imported nowhere.

- **12822 `_splitter_successors`** — builds the splitter -> branch adjacency
  (`input_obj` reverse index). Recomputed from scratch at 12660, 12846, 12940,
  12976.
- **12862-12883 `_output_tail_nets`** — `stack` / `seen` DFS per net following
  `output_obj`. Reachability.
- **12919-12956 `_leads_back`** — DFS over the same edge set: "does flow leaving
  `start` return to this path". Cycle detection. Called per candidate sink link.
- **12959-13041 `_committed_path_closes_cycle`** — hand-written iterative
  **Tarjan SCC**, replacing a per-index walk that cost 30k walks / 3.4M visits
  on `universe-matrix`.
- **13173-13219 `_run_cells`** — bounded 3-hop bidirectional BFS.
- **13434-13446 `_tap_source.reaches_tap_downstream`** — bounded 3-hop forward
  chase.
- Reverse-adjacency construction at **9757-9760** (`building_predecessors`) and
  **12499-12511** (`into`, with incremental `refresh_predecessor` at 12504).

The edge source these all want is `Buildings`' `by_input_obj` / `by_output_obj`
link indexes, built once and shared — see the graph survey for why networkx is
not the answer.
