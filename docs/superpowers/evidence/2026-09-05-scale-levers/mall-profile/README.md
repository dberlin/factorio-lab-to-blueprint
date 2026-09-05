# Mall URL profile at 60 s and 100 s (2026-09-05)

URL: `url.txt` (a five-objective mall: Mk.III belts 18/s, sorter Mk.IV 6/s, ray receivers, particle colliders, logistics distributors; 33 recipes). Tree: branch `scale-levers` at `commit.txt` (Tasks 1-6 of the scale-levers plan, master 789625f merged). Harness: `prof_harness.py --url` (the `--url` flag is added in Task 13 of the plan; this run used a scratch copy). 8 tally runs in parallel then 4 cProfile runs in parallel; box load in `load-*.txt` (load 10-11 on 128 cores, other agents' test suites running).

| candidate | machines | strips |
|---|---|---|
| no-proliferator | 935 | 54 |
| all-products | 449 | 46 |
| output-products | 830 | not run |

## Verdicts and where the seconds went (`tallies.jsonl`; `prepare` contains `power_plan`, `junction_ban`, `place_coaters`, `reserve_port_access`)

| run | wall | verdict | prepare | reserve_port_access | route_all | astar | place_coaters | commit_paths |
|---|---|---|---|---|---|---|---|---|
| all-products freeform 60 | 60.0 | REFUSED, 4 packs routed, best left 1 net unrouted | 56.2 / 4 | 49.7 / 8 | 1.9 | 7.6 | 2.6 | - |
| all-products freeform 100 | 100.0 | REFUSED, 6 packs routed, best left 1 net unrouted | 90.3 / 6 | 80.0 / 12 | 7.2 | 11.2 | 3.6 | 3.5 |
| all-products sequence-pair 60 | 42.6 | REFUSED, deadline exhausted | 11.5 / 2 | 4.0 | 5.8 | 4.0 | 1.3 | 3.1 |
| all-products sequence-pair 100 | 70.9 | REFUSED, deadline exhausted | 29.9 / 6 | 10.5 | 10.5 | 10.5 | 3.8 | 6.0 |
| no-proliferator freeform 60 / 100 | 0.9 / 0.7 | REFUSED in under a second: no pack of 54 strips at any candidate height; 2 heights over-band; sweep stopped after 3 draws that produced no new packing | - | - | - | - | - | - |
| no-proliferator sequence-pair 60 | 41.2 | REFUSED, deadline exhausted | 6.8 / 1 | 3.3 | 6.2 | 3.9 | - | 2.0 |
| no-proliferator sequence-pair 100 | 67.4 | REFUSED, deadline exhausted | 12.2 / 2 | 7.0 | 12.8 | 8.3 | - | 3.7 |

Nothing lays out at either budget. The per-candidate `prepare` calls on freeform all-products were 3.8, 3.9, 33.9, 33.5, 9.7, 5.6 s.

## Findings (cProfile, `cprofile-top.txt`)

1. **Freeform: the access-corridor matcher eats the budget.** `_prepare_routing_problem -> hold_ports -> _reserve_port_access -> _match_access_corridors -> solve_model` is 71 s of the 100 s (20 CP-SAT solves over 10 calls; `assignment_boundary_cut` itself only 1.2 s / 5 calls). With boundary validation on, the lexicographic tie-break `minimize` solve carries no deterministic-work cap (only the `validate is None` branch sets `_ACCESS_TIE_DETERMINISTIC_WORK`) and runs with `max_time_in_seconds = remaining`; an `UNKNOWN` at the deadline raises `_PreparationDeadline`, so a candidate that spent 35 s polishing is then discarded ("1 other pack stopped during exact preparation"). This code arrived with master's packer-fix merge (789625f).
2. **Freeform: one A\* grid per corridor probe.** `_reserve_port_access` and `assignment_boundary_cut` call `_astar` without a shared grid: 872 `_make_grid` builds for 872 searches, 3.9 s, plus 3.6 s of `_astar` self time.
3. **Sequence-pair at 449 machines: `_selected_strips` rebuilds every strip per anneal state.** 31 s of 93 s: 1857 calls x 46 strips of `dataclasses.replace` (570k calls, 7.9 s) and `_staged_static_clearance_keys` (76k calls, 14.9 s, 1.38M generator steps) recomputed for coater strips every time.
4. **Sequence-pair at 935 machines: direct-insert geometry.** `_refinement_direct_targets` 17.9 s (280k `DirectInsertTarget.__post_init__`, 24.5 s cumulative) and `_direct_net_candidates` 17.2 s (143k `_direct_origin_deltas`): 34 s of 78 s. Plan Task 7 memoizes exactly this.
5. **Sequence-pair prepare per candidate is 12 s at 449 machines**: `_projected_coater_junction_bans_by_frame` 6.8 s / 2, `_power_plan` 5.2 s / 2, `_tap_source` 4.5 s / 498 (in `_commit_paths`), `_place_coaters` 4.3 s, `_staged_static_relation_projection_risks` 4.0 s / 585.
6. **Freeform coater placement**: `_place_coaters` 10 s / 5 calls, of which `_CleanupSurvivorGraph.extended_snapshot -> snapshot_bounds -> _peel` 4.3 s / 371 calls (2M `_poll`, 800k `_resolve`) and `_coater_keepout_hits` 3.2 s / 365 calls.
7. **935 machines on freeform is a capacity refusal, not a hotspot**: the packer's three CP-SAT draws (0.27 s) yield no pack at the in-band heights and two heights are over-band. The largest band cannot hold 54 strips of this size; the refusal is right but could name the band ceiling.

## Levers added to the plan

Tasks 10-13 in `docs/superpowers/plans/2026-09-05-scale-levers.md`: cap the corridor matcher's solves and keep the rank-optimal assignment on a timeout (1); share one grid across the corridor probes (2); memoize `_selected_strips` per instance/variant and `_staged_static_clearance_keys` per strip (3); add `--url` to the harness and record this profile (repro). Items 5-7 are recorded as follow-ups in the design's §5.
