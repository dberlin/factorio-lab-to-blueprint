# Scale profile, 2026-09-05: where a 30 s attempt goes on the large cells

Question: across the largest corpus cells, and instances built larger than the
corpus, where does the wall clock go, and which of it is a Cython or caching
lever?  Master at `a1afec5`, Cython route and sequence kernels loaded
(`route_backend=cython`), 8 workers, 30 s budget, `no-proliferator`, in-process
`FreeformLayout(BandPolicy("portable"))` and `SequencePairLayout(islands=1)`.
Box: 128 cores, load 5.9, `vmstat` 95 % idle at start (`load-at-start.txt`).

## Instances

| cell | machines | groups | note |
|---|---|---|---|
| universe-matrix*60, fast rank, Mk.III | 224 | 38 | the corpus stress cell |
| quantum-chip*180, fast rank, Mk.III | 252 | 15 | 3x the corpus rate |
| gravity-matrix*200, fast rank, Mk.III | 349 | 26 | not in the corpus; the largest instance that builds |
| universe-matrix*90 / *120, fast rank | 331 / 439 | 38 | **crash** in `strip_variants._logical_strip_plans`: one hydrogen output lane would carry 44 items/s over the 30/s Mk.III cap |
| quantum-chip*60 | 87 | 15 | small reference |

The two universe-matrix scale-ups never reach layout: `generate_strip_families`
raises `ValueError` (not a refusal) because `mass-energy-storage`'s hydrogen
output feeds two destinations from one lane.  The Deliverable A per-strip cap
bounds input lanes, not a shared output lane.  That is a separate defect,
diagnosed in the same session; it is the ceiling on how large an instance this
code can profile today.

## Method

`prof_harness.py` builds a spec for an arbitrary URL, installs the phase shims
from `scripts/route_profile.py` (real seconds, inner loops untouched) and
optionally `cProfile` (ratios only; it inflates every Python call).  Each cell
ran twice without cProfile and once with.  Raw rows: `tallies.jsonl`; the
table: `tally-table.md`; cProfile digests: `cprofile-top.txt`.

## Where the seconds go (real seconds, `phase/n calls`)

Every large cell runs to the budget: a faster phase buys more candidate
evaluations inside 30 s, not an earlier finish.  Note `prepare` CONTAINS
`power_plan` and `junction_ban`.

| cell | wall | route_all | commit_paths | astar | merge_frontier | prepare | power_plan | last_mile | finalize | validate |
|---|---|---|---|---|---|---|---|---|---|---|
| um60 freeform (2 runs) | 23.7 / 27.3 | 12.7 / 13.7 | 5.5 / 6.4 | 3.8 / 3.7 | 2.1 / 2.1 | 5.4 / 5.6 | 3.5 / 3.7 | 3.4 / 3.2 | 1.7 / 2.9 | 1.6 / 2.4 |
| gm200 freeform | 20.9 / 27.2 | 10.1 / 12.6 | 4.8 / 6.5 | 2.7 / 2.7 | 1.2 / 1.6 | 4.6 / 5.7 | 3.3 / 4.2 | 0 | 2.1 / 3.5 | 2.6 / 3.5 |
| qc180 freeform | 26.0 | 10.0 | 3.6 | 3.1 | 1.2 | 3.8 | 2.5 | 0 | 8.9 (n=5) | 1.5 |
| um60 sequence-pair | 24.5 / 25.3 | 5.6 / 6.5 | 3.3 / 3.8 | 0.7 / 0.8 | 0.9 / 1.1 | 4.9 / 5.6 | 2.9 / 3.3 | 0.1 | 0.9 | 0.6 |
| gm200 sequence-pair | 22.5 / 22.3 | 1.3 | 0.9 | 0.1 | 0.1 | 3.8 / 3.7 | 2.3 / 2.2 | 0 | 1.2 | 0.7 |
| qc180 sequence-pair | 23.2 | 1.1 | 0.5 | 0.1 | 0.3 | 2.6 | 1.2 | 0 | 0.6 | 0.5 |

Sequence-pair um60 also spends ~6.8 s of the 30 blocked on a thread lock
(cProfile), which is the CP-SAT solve in its worker thread: solver time, not
Python.  Sequence-pair gm200/qc180 spend the bulk of their Python time in the
direct-insert eligibility path (below), which the shims do not cover.

The A\* kernel is no longer the problem: 6M expansions cost 3.7 s (~0.6 us per
expansion), and the Python wrapper adds little.

## Ranked opportunities

### 1. `_commit_paths` -> `_committed_path_closes_cycle` -> `_leads_back`  (validated, ~3.5 s per freeform run)

The largest single Python hotspot on every cell (13-14 % of cProfile self
time, 3.4M belt visits in um60).  `_committed_path_closes_cycle` calls
`_leads_back` once per committed belt cell (30k per run), and each call walks
the belt graph from scratch.  The question it answers per index is "is this
belt on a directed cycle", which one Tarjan pass over the reachable belt graph
answers for all indices at once.

`proto_cycle.py` monkeypatches an SCC version beside the original, asserts
they agree on every call, and times both (`proto-cycle.jsonl`):

| cell | calls | original | SCC | mismatches |
|---|---|---|---|---|
| um60 freeform | 678 | 3.61 s | 0.15 s | 0 |
| gm200 freeform | 468 | 3.70 s | 0.11 s | 0 |
| qc180 freeform | 399 | 1.79 s | 0.07 s | 0 |
| um60 sequence-pair | 464 | 1.75 s | 0.08 s | 0 |

Pure Python, no Cython needed.  Caveat: no call returned `True` on these
cells, so the cycle-found branch needs a unit test with a constructed loop
(the `belt.acyclic` fixture) before this replaces the original.  Doing the SCC
once per `_commit_paths` call rather than once per net would be cheaper still,
but the residual is already noise.

### 2. Sequence-pair direct-insert eligibility recomputed per anneal state  (~3-4 s real, cache)

`_variant_direct_eligibility` / `anneal_stage` call `_selected_direct_targets`
for every state (1006 calls on gm200).  Each call rebuilds the selected strips
with `dataclasses.replace`, recomputes `_direct_net_candidates` ->
`_direct_origin_deltas` -> `_direct_column_deltas` for all ~45 nets (45k
calls), then `_refinement_direct_targets` does 45k `replace(DirectInsertTarget)`
whose `__post_init__` re-validates `origin_deltas` with three generator passes
(8.5M iterations; 5.8 s of 31 s cProfile).  An anneal move changes one or two
strips, so a memo keyed per net on `(producer physical variant, machine count,
consumer physical variant, machine count, lane k, item)` would hit almost
always.  The 2026-09-01 review already named `_variant_direct_eligibility` as
the cause of the quantum-chip deadline overshoot; this is the same code.

### 3. `_power_plan`  (~0.85 s per call, 2.2-4.2 s per run, both strategies)

Called once per candidate inside `_prepare_routing_problem`.  Two Python loops
dominate: (a) the free-mask fill iterates every tile of the demand box and
probes `canvas.blocked` for each of `LEVELS` levels (503k generator steps,
122k `canvas.free` calls) -- scatter the `blocked` keys into the NumPy mask
once instead, or move the loop to Cython; (b) for every tower candidate,
`_projected_power_peer_possible` runs against every existing power node
(95k calls per run), recomputing both centres via `codec.tile_to_local_offset`
each time -- precompute peer centres and gates once per call and vectorize the
distance test.  Both are exact rewrites.

### 4. Finalizer projection geometry  (1.7-8.9 s per freeform run; Cython candidate)

`finalize_placement -> _certify_frame -> _failure_at_projection ->
_projected_static_failure / _projected_sorter_failure /
_projected_power_candidates -> planet.collisions_at -> colliders.obb_overlap`.
`obb_overlap` runs 65k (um60) to 329k (gm200 sequence-pair) times per run;
qc180 freeform spent 8.9 s in finalize over 5 calls.  This is the "NumPy
follow-up" the evaluation-throughput spec deferred: a compiled separating-axis
test over flat float buffers, with `collisions_at`'s pair loop alongside it,
is the natural second Cython kernel.  Separately, `projection_safe_machine_pitch_x`
is `@cache`d but depends only on catalog and planet constants; every fresh
process pays 0.7-1.2 s of misses (244 on gm200) that a persisted table would
remove.

### 5. `_merge_frontier` -> `_altitude_profile` with `Fraction`  (~1.2 s cProfile, um60 freeform)

Called 3114 times per run, once per sibling per frontier build, on paths that
do not change between calls: 287k `Fraction` multiplications.  Memoize per
path tuple within the routing pass, or compute the half-level profile in
integers (`2 * altitude`).  `_merge_frontier` also makes 1M `canvas.free`
calls per run; a flat free-mask from the shared `_Grid` would replace them.

### 6. `commit_once` deep-copies the whole canvas  (0.7-1.2 s per run)

`deepcopy(canvas)` per commit proof: 800k `deepcopy` calls in um60.  An undo
log over the fields `_commit_paths` mutates (`buildings`, `blocked`,
`world_taken`) would replace it.

### 7. `dataclasses.replace` churn  (~0.7 s cProfile)

97k-121k `replace` calls per run: `_relink` 41k, `slots.assign_belt_slots`
22k, `_merge_frontier` 18k, `junction.make_splitter_stack` 10k.  `replace`
re-runs `__init__`; a slotted fast copy or mutable link fields on the routing
canvas's belts would cut most of it.  Minor on its own; free once #1 and #2
land.

## What is not a lever

* A\* (`astar_flat`) and `relaxed_search_flat`: already compiled, ~15 % of wall.
* CP-SAT solve time in sequence-pair (~7 s on um60): a solver setting, not code.
* `strip_families`, `plan_strips`, `junction_ban`: under 1 s each per run.

## Suggested order

1 (pure Python, validated, ~3.5 s freeform / ~1.8 s sequence-pair), then 2
(cache, sequence-pair's dominant Python cost), then 3 (exact NumPy rewrite),
then 4 as the next Cython kernel.  1-3 together are roughly 8 s of a 24-27 s
freeform attempt on universe-matrix, which is more candidate heights inside
the same 30 s budget; whether that converts refusals is the corpus gate's
question, not this profile's.
