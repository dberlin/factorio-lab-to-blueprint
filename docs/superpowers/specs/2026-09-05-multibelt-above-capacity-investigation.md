# Does the multi-belt path work when supply or demand genuinely exceeds one belt?

**Date:** 2026-09-05. **Tree:** master `a1afec5`, read-only investigation by a session agent; scratch scripts and raw run outputs under `.superpowers/scratch/demand-investigation/` (git-ignored; `run_case.py`, `capture_invalid.py`, `dump_plans.py`, `probe_d1_without_mergebug.py`, `urls.py`, `out/`, `out120/`, `out300/`). **Status:** report and fix plan; nothing here is implemented. The `_merge_lanes` producer-supply fix (§3.4) is implemented by `docs/superpowers/plans/2026-09-05-scale-levers.md` Task 3.

All runs used `pipeline.build(url, strategy=..., candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,), time_budget_s=B)`. URLs are `.../dsp/list?o=<item>*<rate>&ibe=<belt>&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11`. `mk2ceil` cases pin `researched_technology_ids` to the DEUTERON test's Mk.II set exactly as `tests/test_pipeline.py::_with_belt` does. A bare `ibe=conveyor-belt-2` only sets the floor: with every technology researched `spec.lane_capacity` is still 30, so the naive "Mk.II variant" tests nothing.

## 1. Results

| case | what exceeds one belt | strategy | budget | verdict | evidence |
|---|---|---|---|---|---|
| A1 iron-ingot*2400 | ore in 40/s, ingot out 40/s (cap 30) | both | 30 s | CLEAN | 20 machines, `machine_cap` 15, 4 lanes @10/s, entry 4/2 |
| A2 iron-ingot*3000 | 50/s in and out | both | 30 s | CLEAN | 25 machines, 5 lanes @10/s, entry 5/2 |
| A3 copper-ingot*2400 | copper-ore 40/s | both | 30 s | CLEAN | 4 lanes @10/s |
| A4 magnet*2400 | ore 40/s, magnet 40/s | both | 30 s | CLEAN | cap 22, 5 lanes @8/s |
| A5 iron-ingot*1200 mk2ceil | ore 20/s on 12/s ceiling | both | 30 s | CLEAN | cap 6, 2 lanes @10/s, entry 2/2, tiers {2002} |
| A6 iron-ingot*2400 mk2ceil | ore 40/s on 12/s ceiling | both | 30 s | CLEAN | 4 lanes @10/s, entry 4/4, no Mk.III emitted |
| B1 magnetic-coil*3600 | magnet 60/s to one consumer | both | 30 s | CLEAN | 80 machines; magnet on 21 runs; iron-ore entry 8/2 |
| B2 gear*2400 | iron-ingot 40/s to one consumer | both | 30 s | CLEAN | 47 machines |
| B3 circuit-board*3600 | iron-ingot 60/s to one consumer | both | 30 s | CLEAN | 65 machines |
| B4 magnetic-coil*900 mk2ceil | magnet 15/s on 12/s ceiling | both | 30 s | CLEAN | 21 machines, tiers {2002} |
| C1 electric-motor*2400 | iron-ingot 120/s to 2 consumers | sequence-pair | 120 s | CLEAN | 195 machines, iron-ingot on 17 runs, entry ore 8/6 |
| C1 | same | freeform | 30/120 s | REFUSED | packer: "no pack of 34 strips was ever produced at any candidate height" |
| C2 processor*1200 | hps 80/s to 1 consumer; copper-ingot 60/s to 2 | sequence-pair | 300 s | CLEAN | 238 machines, hps on 21 runs, max run 24.44/s |
| C2 | same | freeform | 30/120/300 s | REFUSED, `flow.belt_capacity` | run 34 carries 73/2 = 36.5/s of high-purity-silicon on a 30/s belt; identical building indices at every budget |
| C2 | same | sequence-pair | 30/120 s | REFUSED | deadline only |
| C3 electromagnetic-matrix*1800 | ore 60/s, circuit-board 143/s over 15 runs | sequence-pair | 120 s | CLEAN | 163 machines |
| C3 | same | freeform | 30/120 s | REFUSED | packer: 29 strips, best pack left 4 nets unrouted |
| C4 electric-motor*600 mk2ceil | ore 40/s, iron-ingot 30/s on 12/s ceiling | freeform | 30 s / 60 s | CLEAN (flaky) | 51 machines; a 30 s repeat and the 120 s run both REFUSED (packer) |
| C4 | same | sequence-pair | 30/120 s | REFUSED, `flow.belt_capacity` (+ `flow.sorter_capacity` at 120 s) | "exact validation failures: flow.belt_capacity" |
| D1 universe-matrix*90 | hydrogen: external 33/s and produced 3/s | both | 30 s | CRASH | the `_merge_lanes` `ValueError` (§3.4) |
| D1 | same, that one refusal suppressed | both | 150 s | CLEAN | freeform 42.9 s, sequence-pair 136.8 s, `report.ok=True`, zero errors, hydrogen entry 3 lanes / 2 needed |
| D2 universe-matrix*60 | coal 33/s external; hydrogen both-fed at 22/s | both | 30 s | CLEAN | 224 machines, hydrogen entry 3/1, coal 2/2 |
| D3 universe-matrix*30 mk2ceil | hydrogen both-fed on 12/s ceiling | both | 30/120 s | REFUSED, `flow.sorter_capacity` | "sorter 46 must move 3 items/s of hydrogen across 3 tiles but sustains only 2" |
| E1 energetic-graphite*2400 | coal 80/s external | both | 30 s | CLEAN | 7 entry lanes / 3 needed |
| E2 crystal-silicon*1800 | silicon-ore 60/s | both | 30 s | CLEAN | |
| F1 crystal-silicon*2400 | hps 80/s to one consumer (C2's failing pair, isolated) | both | 30 s | CLEAN | 80 machines, hps on 13 runs |
| F2 crystal-silicon*3000 | hps 100/s | both | 30 s | CLEAN | 100 machines |
| F3/F4 crystal-silicon mk2ceil | hps 15/s, 20/s on 12/s ceiling | both | 30 s | CLEAN | tiers {2002} |
| F5 microcrystalline-component*1800 | hps 172/s over 22 runs | sequence-pair | 120 s | CLEAN | 115 machines |
| F5 | same | freeform | 30/120 s | REFUSED | packer: 20 strips, nets unrouted |

## 2. Verdict

**(a) Input side above one belt: works.** Every A/E/F case is CLEAN on both strategies inside 30 s, on a 30/s and on a 12/s ceiling. `_machine_cap` shortens the strips, the entry ring hands the item to as many lanes as there are strips, no run exceeds its tier, and `belt.tier_allowed` never fires: capacity comes from lane splitting, not from a belt upgrade. `flow.external_entry_points.entry_lanes` agreed with the runs the census counted in every case.

**(b) One producer above one belt into one consumer: works.** B1-B4, F1-F4 all CLEAN on both strategies.

**(c) One producer above one belt fanning out to several consumers: works on sequence-pair; freeform has two distinct defects.** C1, C3, F5 are CLEAN on sequence-pair given budget; C2 is CLEAN on sequence-pair at 300 s. Freeform refuses all four: C2 with a genuine `flow.belt_capacity` violation (§3.1), the others in the packer on the larger strip counts the cap creates (§3.3). Sequence-pair has its own `flow.belt_capacity` refusal on C4 (§3.2).

**(d) Both-fed above one belt: blocked only by the known bug.** `universe-matrix` is the only objective in the vendored dataset where an item is both external and internally produced (checked across 34 objectives), and hydrogen first crosses 30/s at exactly `universe-matrix*90`. With only the `_merge_lanes` refusal suppressed, both strategies lay it out cleanly with zero validator errors.

## 3. Failures, with root cause

### 3.1 Freeform merges producer lanes onto a consumer lane with no rate bound (C2)

Routing bug with a planning-time root: the router has no rate model. It also falsifies the multi-belt design's soundness argument (spec §4.2). `capture_invalid.py C2-processor-1200 40` keeps the first rejected placement:

```
--- run 34: required=73/2 capacity=30 per_item={'high-purity-silicon': '73/2'}
    head b3895 @(49,60,1) tail b2188 @(120,36,0) len=114
    pred=((0, 11), (0, 36))
      run 11 load={'high-purity-silicon': 13.333}
      run 36 load={'high-purity-silicon': 23.5}
    TAKE off run (26.667/s): 18 sorters x 1.4815/s into microcrystalline-component
```

The consumer strip on run 34 draws 26.67/s; two upstream lanes side-load 13.33 + 23.5 = 36.83/s onto it, so `validate._run_demand`'s push propagation charges 36.5/s against a 30/s tier and `validate._belt_capacity` (`validate.py:5371`) convicts. Deterministic at 30, 120 and 300 s.

Why it can happen:

- `strip_variants._machine_cap` (`strip_variants.py:1649`) is a min over all the group's items. For `high-purity-silicon` the binding item is the input (silicon-ore, 2/s per machine), so `cap = min(30/2, 30/1) = 15` and the 80-machine group partitions into 6 strips whose output lanes carry only 13-14/s. The consumer (`microcrystalline-component`, cap 20) partitions into 3 strips drawing 26.67/s each. Six half-full producer lanes cannot be assigned whole to three nearly-full consumer lanes; at least one producer lane must split, and nothing splits it.
- `freeform._nets_between` (`freeform.py:3267`) returns the full cross product of producer-strip x consumer-strip as bare `(i, j)` pairs (`freeform.py:4369`: "returns bare strip-index pairs with no item identity"). With no rate on a net, neither `global_router` nor `last_mile` can refuse to side-load a full lane.
- Spec §4.2 asserts "a merged run into a consumer lane carries at most that consumer strip's demand". The per-strip cap does not compose into a cap on the wire between strips.

The same pair in isolation (F1/F2) is CLEAN, and sequence-pair lays C2 out CLEAN, so this is freeform's merge choice on this geometry, not an unroutable spec.

### 3.2 Sequence-pair hits `flow.belt_capacity` on C4

Same defect class, other strategy; not separately localised. The sequence-pair refusal path does not retain the offending run. Reproducer: `run_case.py C4-electric-motor-600-mk2ceil sequence-pair 120`.

### 3.3 Freeform's packer/router fails on the strip counts the cap creates

Density pressure the spec predicted (§4.4) and did not build the recovery for: C1 ("no pack of 34 strips"), C3 ("29 strips, 4 nets unrouted"), F5 ("no packing of 20 strips could be wired"), C4 at 120 s. Sequence-pair lays C1, C3, F5 out. §4.4's designed recovery, lane multiplicity inside a strip with the cap becoming `capacity(item) x lanes(item)`, is documented and unbuilt. C4 is also budget-non-monotonic on freeform: CLEAN at 30 s and 60 s, REFUSED at a 30 s repeat and at 120 s.

### 3.4 `universe-matrix*90` crash: the `_merge_lanes` draw-versus-supply bug

Diagnosed separately (`2026-09-05-scale-levers-design.md` §2). Measured result of removing only that refusal: both strategies produce a clean 331-machine layout.

### 3.5 `flow.sorter_capacity` has no planner-side cap (D3)

Spec gap adjacent to the multi-belt work. `_machine_cap` bounds what a lane carries; nothing bounds what a sorter must move. `universe-matrix*30` on a 12/s ceiling refuses on both strategies: one casimir-crystal machine wants 3/s of hydrogen through a 3-tile sorter that sustains 2/s. Per-machine, so no strip length fixes it; only a shorter span, a faster sorter tier, or a second sorter, and there is no early explained refusal the way §4.5 gives one for belts.

## 4. Ranked fix plan (not yet executed)

Invariants for every task: zero `validate.validate` errors on every cell clean today; `flow.belt_capacity`, `flow.conservation`, `flow.sorter_capacity`, `flow.external_entry_points` (`entry_lanes` must keep agreeing with the runs built) and `belt.tier_allowed` must not regress; `scripts/audit.py` must not lose a cell.

**Task 1: land the `_merge_lanes` producer-supply fix.** Done by the scale-levers plan (Task 3). Add the regression this run earned: `universe-matrix*90` at `NO_PROLIFERATOR` builds on both strategies, as a `@pytest.mark.slow` sibling of `tests/test_pipeline.py::test_at_mk3_hydrogen_above_the_ceiling_arrives_on_two_lanes` (measured 42.9 s freeform / 136.8 s sequence-pair).

**Task 2: give nets a rate, and bound the producer-to-consumer lane merge.** Fixes 3.1 and probably 3.2; the only place a strategy is wrong rather than slow. Files: `freeform.py`, `_nets_between` (3267) and its call sites (`freeform.py:2804`, `:3932`, `:4381` `_pack_relation_problem`), plus the last-mile/global-router seam that realises a net as belts. (1) Widen the net tuple to `(item, cargo_domain, rate)`, the producer strip's share of that destination, the arithmetic `_allocate_machines` (`freeform.py:1841`) already does per shard; `logical_net_ids` becomes fillable at the same time. (2) Replace the cross product with a capacity-feasible assignment: a transportation solve over producer-strip supply and consumer-strip demand (6 x 3 in C2), constrained so the total rate arriving on any consumer lane is `min(consumer strip demand, spec.lane_capacity x planning_stack(item))`; where the numbers force it, one producer strip splits across two consumer lanes. (3) Amend spec §4.2. Cheaper alternative: align the two partitions by passing a smaller `max_machine_count` to `partition_strip_variant` (`strip_variants.py:1852`) so the producer-lane count is an integer multiple of the consumer-lane count (C2: micro as 6 strips of 9 at 13.33/s instead of 3 of 18); keeps the router rate-free, costs strips, pushes on Task 3. Tests beside: `tests/layout/test_freeform.py::test_plan_strips_shortens_strips_to_the_capacity_cap` (18485) and the sharding cluster at `test_freeform.py:10340`; add a unit test that 6 producer lanes at 13.33/s feeding 3 consumer lanes at 26.67/s yields no lane above `spec.lane_capacity`, plus a slow pipeline test that `processor*1200` builds on freeform.

**Task 3: build §4.4 lane multiplicity.** Fixes 3.3. Files: `strip_variants.py` (`_logical_lanes`, `LogicalLane`, `_machine_cap`, `generate_strip_families`) and `freeform.py::_seat_inputs`. Today `LogicalLane` requires unique items per lane and unique lane ids per family, so a second belt for the same item is not representable, and a side holds at most `catalog.SORTER_MAX_REACH` (3) rows. Add `lanes(item)` per side, split that item's sorters by machine index, relax the cap to `capacity(item) x lanes(item)`. Hold the spec rule: parallel belts whenever `ist == 1`, stacked lanes whenever `ist > 1`, pilers only where a lane's achievable stack is below `ist`; this is the `ist == 1` arm and must not touch any `belt_stack > 1` plan. Invariants: A6 still emits only Mk.II belts, and `test_without_planetary_logistics_hydrogen_arrives_on_four_lanes` still sees four hydrogen entry lanes. Tests beside: `tests/layout/test_strip_variants.py:1656`, `:1669`, `:1679`.

**Task 4: a planner-side sorter-rate bound.** Fixes 3.5. Files: `strip_variants.py` (`_machine_cap`, the seating choice in `_seat_inputs`), keeping `validate.py`'s `flow.sorter_capacity` as the arbiter. When a per-machine rate exceeds what the best sorter tier moves across the span the seating would use, seat closer or refuse early with the numbers, as §4.5 does for belts. Reproducer: D3.

**Task 5: freeform budget non-monotonicity.** Lowest priority: costs a refusal, never a bad blueprint. Files: `freeform.py` height sweep and `_coarsen_saturated_strip_plan`. A longer clock must never lose a placement a shorter clock found: retain the best completed placement across the sweep. Reproducer: C4 on freeform at 30, 60 and 120 s.

## 5. Residual limits observed

- Size, not capacity, is the practical ceiling. Largest CLEAN builds: 238 machines (sequence-pair, 300 s) and 224 machines (30 s). Above ~200 machines a 30 s budget refuses on the deadline; freeform's packer gives out at ~20-34 strips regardless of clock.
- Entry lanes are heavily over-provisioned: coal 7/3 (E1), iron-ore 8/2 (B1), silicon-ore 7/3 (F1), hydrogen 3/1 (D2). Correct as a warning, but the lane count tracks strip count, not demand; the player must feed every one.
- Nothing invalid was ever emitted. Across ~70 runs there was not one INVALID verdict; every failure was REFUSED or the §3.4 CRASH. Where planner and validator disagreed (3.1, 3.2) the build was refused, not shipped.
- `belt.tier_allowed` never fired; on Mk.II-ceiling cases only item 2002 was emitted. Capacity came from lane splitting, as Deliverable A promised.
- The both-fed-above-a-belt case has exactly one witness in the dataset (`universe-matrix` at 90/min or more). There is no second corpus cell for that path.
