# Scale levers: profile-driven throughput fixes and the output-lane capacity defect

**Date:** 2026-09-05. **Base:** master `a1afec5`. **Status:** design approved by the user in session ("productionize and merge your SCC work ... implement the other parts of the plan and merge to master"); plan at `docs/superpowers/plans/2026-09-05-scale-levers.md`.

## 1. Where the evidence comes from

`docs/superpowers/evidence/2026-09-05-scale-profile/README.md` profiles the largest corpus cell (`universe-matrix*60`, 224 machines), two scale-ups (`quantum-chip*180`, 252; `gravity-matrix*200`, 349) and a small reference under both strategies at the 30 s corpus budget with the Cython route kernels loaded. Two facts frame this design:

1. Every large cell runs to the budget. A cheaper phase buys more candidate evaluations inside 30 s; it never finishes a cell early. So the gate for this work is *no regression* on the corpus plus a measured drop in the phases named below, not a wall-clock target.
2. A\* is no longer the bottleneck (~0.6 us per expansion). The remaining Python cost is concentrated in a handful of functions, ranked in §3.

A second finding fell out of building the scale-ups: `universe-matrix` above 60/min cannot be laid out at all, because strip planning raises a `ValueError` that escapes both strategies as a CRASH. §2 is the diagnosis (from the session's investigation agent, verified against the code).

## 2. The output-lane capacity defect

**Symptom.** `universe-matrix*90` and `*120` (Mk.III, fast rank, `no-proliferator`) raise from `strip_variants._logical_strip_plans`:

```
ValueError: recipe 'mass-energy-storage': hydrogen: destinations ['casimir-crystal#1', 'deuterium#6'] have to share one output lane carrying 44 items/s, over the 30/s the belt sustains
```

**Root cause.** `freeform._merge_lanes` (freeform.py ~1745-1838) folds a shard's destinations onto at most `reach` output lanes and refuses when a lane's load exceeds `capacity * stack`. The load it sums is `demand[(item, dest, domain)]`, built in `_logical_strip_plans` from `freeform._sink_demand`, which for an internal destination returns `dest.count * dest.inputs[item]`: the **consumer's whole draw**. Nothing on that path multiplies the producer's `outputs_per_machine[item]` by its machine count. For `universe-matrix*90`:

| quantity | value |
|---|---|
| `mass-energy-storage` machines | 2 |
| hydrogen supplied by the whole group | 1.5/s |
| casimir-crystal draw (4 x 4.5) + deuterium draw (4 x 3.75) | 33/s |
| external hydrogen on the bus | 33/s |
| load the check computed | 33/s > 30/s |

Hydrogen is *both-fed* (external input and internal product); the consumers' draw is served almost entirely by the bus, and the producer lane physically carries at most 1.5/s. The fold happens because the group has 2 machines, 2 output lanes (`out_capacity` 2 after `in_below` and `south_columns`), and 3 hydrogen destinations plus antimatter, so `_shard_sinks` cannot shard further and `_merge_lanes` must put two hydrogen destinations on one lane.

**Why Deliverable A did not cover it.** `strip_variants._machine_cap` bounds `count * outputs[item]` per single-item lane (40 machines here; never binding) and is applied after `_logical_strip_plans`, at `generate_strip_families` and the partition seams. It bounds the right quantity (supply) but `_merge_lanes` runs earlier on the unpartitioned shard and compares a different quantity (draw). Spec §4.1 of `2026-09-02-multiple-belts-and-pilers-design.md` ("`_merge_lanes`'s over-capacity `ValueError` becomes unreachable except for a single machine over the ceiling") assumed `_merge_lanes` measured supply; it does not. The corpus never exercised this: `bench/corpus.py` hard-codes `*60`, at which the draw is 22/s. Measured: 60, 70, 80 plan; 90 and 120 crash.

**Why gravity-matrix*200 (349 machines) passes.** It has no `mass-energy-storage` group; its one multi-destination producer above 30/s (`iron-ingot`, 25 machines, 4 destinations) shards to at most `reach` sinks per shard, so `_merge_lanes` returns early and the cap bounds each strip.

**Decision (Option 1).** Judge a merged output lane by what the shard *supplies*, keeping consumer draw as the bin-packing weight that decides which destinations share a lane:

- `_merge_lanes` gains `supply: Mapping[str, Fraction] | None = None` (items/s of each product the shard's machines emit). The verdict compares `min(loads[b], supply[item])` when supply is known; the packing order is unchanged.
- `_logical_strip_plans` passes `{item: per_shard[i] * group.outputs[item] for item in shard products}` per shard; `per_shard` is already computed before the merge.
- `_allocate_machines`'s draw weighting is left alone (routing order and machine split, not a capacity verdict); it is a named follow-up.

Rejected: sharding by output-lane *demand* (would ask a 1.5/s producer for two hydrogen lanes; `_shard_sinks` cannot shard a 2-machine group further) and one belt per destination above the ceiling (geometry forbids it at `out_capacity` 2; keep for §4.4 lane multiplicity).

**Crash versus refusal.** The `ValueError` escapes because `FreeformLayout.lay_out` calls `generate_strip_families` before the `try` that maps `plan_strips` errors to `NoValidLayout`, and `sequence_solver._production_run` wraps only `plan_strips`. `pipeline.py` and `strategy_race.py` catch only `NoValidLayout`. The boundary is `generate_strip_families` itself, where `_machine_cap` already raises `NoValidLayout(..., spec_label=spec.label, budget_s=0.0)`. A planning `ValueError`/`KeyError` from `_logical_strip_plans` becomes `NoValidLayout` there, so both strategies and the race see a refusal. `ValueError` stays the internal contract of `_logical_strip_plans`/`_merge_lanes` (tests assert it).

## 3. Throughput levers, ranked by measured cost

Real seconds per 30 s attempt (phase shims, not cProfile), universe-matrix*60 unless stated. Each lever is an exact rewrite: identical outputs, verified by tests and, for the kernel, a randomized parity test.

1. **`_commit_paths` -> `_committed_path_closes_cycle` -> `_leads_back`: 3.5-3.7 s freeform, 1.8 s sequence-pair.** The per-index walk is replaced by one Tarjan SCC pass over the reachable belt graph per call: an index lies on a directed cycle iff its SCC has more than one member or it has a self-edge. Prototype (`evidence/2026-09-05-scale-profile/proto_cycle.py`): exact on 2009 calls, 3.61 s -> 0.15 s. No call returned `True` on the corpus, so the cycle branch needs constructed unit cases.
2. **Sequence-pair direct-insert eligibility, recomputed per anneal state (~3-4 s real on gravity-matrix*200).** `_selected_direct_targets` rebuilds strips and recomputes `_direct_origin_deltas` for ~45 nets per state (45k calls), then `_refinement_direct_targets` runs 45k `replace(DirectInsertTarget)` whose `__post_init__` re-validates `origin_deltas` (8.5M generator steps). Memoize `_direct_origin_deltas` per strip pair on the fields the geometry reads, and memoize the refined target per `(target, producer_offset, consumer_offset)`.
3. **`_power_plan`: 0.85 s per call, 2.2-4.2 s per run in both strategies.** (a) The free-mask fill probes `canvas.blocked` once per level per tile through a generator (503k steps): precompute the set of blocked `(x, y)` columns once and probe it. (b) `_projected_power_peer_possible` runs for every tower candidate against every power node (95k calls) recomputing both centres each time: compute the candidate centre once and keep peer centres parallel to `power_nodes`.
4. **Finalizer projection geometry: 1.7-8.9 s per freeform run.** `planet.collisions_at -> colliders.obb_overlap` runs 65k-329k times per run. A Cython kernel for the separating-axis test and the boxes-vs-boxes loop, selected like `route_kernel` (env override `FLAB2BP_GEOMETRY_KERNEL`), compiled with `-ffp-contract=off` so the C arithmetic matches Python's double arithmetic operation for operation. Parity is proven by a randomized test against the Python implementation, which remains the fallback.
5. **`_merge_frontier` -> `_altitude_profile` (~1.2 s cProfile).** Called once per sibling per frontier build on unchanged paths; 287k `Fraction` operations. Cache by `(tuple(path), ramped)`; callers receive a fresh list.
6. **`commit_once` deep-copies the canvas (0.7-1.2 s).** `PlacedBuilding` is frozen; the copy only needs fresh containers. `_Canvas.clone()` copies every container field one level deep (and `belt_ban`'s inner sets) and shares immutable values.

Not levers: A\* and the relaxed search (compiled), CP-SAT solve time in sequence-pair (~7 s of 30 on universe-matrix), `strip_families`/`plan_strips`/`junction_ban` (under 1 s each). `dataclasses.replace` churn (~0.7 s cProfile across `_relink`, `assign_belt_slots`, `_merge_frontier`) is deferred.

## 4. Gate

Three 30 s audit rounds (`scripts/audit.py --budget 30 --json`) on the branch, compared cell by cell with `scripts/audit_compare.py` against three master rounds taken on `a1afec5` the same day (`evidence/2026-09-05-scale-levers/baseline-round{1,2,3}.jsonl`). Pass: INVALID 0, CRASH 0, no cell CLEAN in every baseline round and REFUSED in every candidate round (a deadline-flake cell is re-run three times on both trees before it counts), geometric-mean area ratio within `audit_compare`'s default noise. In addition, `evidence/2026-09-05-scale-profile/prof_harness.py` re-run on universe-matrix*60, quantum-chip*180 and gravity-matrix*200 must show `commit_paths` under 1.5 s and `power_plan` under 2.5 s per freeform run, and `universe-matrix*90` and `*120` must lay out or refuse, never crash. Record `uptime` and `vmstat 1 3` beside every timing; the box is never idle and its load is disk I/O.

## 5. Follow-ups this design names but does not do

- `_allocate_machines` weights shards by consumer draw; clamp to supply share (freeform.py ~1841-1890).
- Spec §4.1 status note in `2026-09-02-multiple-belts-and-pilers-design.md`: the `_merge_lanes` verdict is now supply-based, which makes the §4.1 unreachability claim true.
- `projection_safe_machine_pitch_x` is `@cache`d in-process but depends only on catalog and planet constants; a persisted table would save 0.7-1.2 s per fresh process.
- `dataclasses.replace` churn on the routing canvas.
- Whether the multi-belt path works end to end when supply genuinely exceeds one belt is under separate investigation (session agent, 2026-09-05); its report is presented after this plan lands.
