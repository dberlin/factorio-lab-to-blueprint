# Self-loop recipes (hydrogen from energetic graphite) — debug evidence

Date: 2026-09-06. Branch `design-selfloop` off master `23f6d098`.
Machine: 128 cores, load 4.5–5.9 throughout (I/O bound, never idle — see the
`uptime` lines beside every timing).

Reported URL (call it **AMM-URL** below):

```
https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFiWUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DKloJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11
```

Three user reports are covered here:

| # | Report | Verdict |
|---|--------|---------|
| **R1** | "it tries to reuse the hydrogen it produces from energetic graphite as input again to itself … requires the input start externally as well" | **Confirmed, and it is a cold-start deadlock.** The physical recirculation loop is built correctly; the block can never start because nothing seeds it. |
| **R2** | "it tried to take 3 inputs to the mining machine producers from the same belt … it looks like it tries to run them all through the same spray coater" | **Confirmed.** One belt run carries three distinct items into the two `advanced-mining-machine` assemblers, and a 2-into-1 belt merge sits on a tile the Spray Coater's body covers. |
| **R3** | implied: the validator says the build is clean | **Confirmed.** Both builds report `0 errors`. Every gap is named below with file:line. |

---

## Part 0 — Reproduction

Both runs used `--budget 30`. Probes and artefacts are in `probes/`.

| Run | Command | Wall | CPU% | uptime after | Result |
|-----|---------|------|------|--------------|--------|
| default | `uv run flab2bp "<AMM-URL>" --budget 30 -v -o probes/bp-default.txt` | 2:20.00 | 362% | `15:49:16 … load average: 5.56, 5.93, 5.45` | winner **sequence-pair / output-products**, 2652 tiles, **0 errors** |
| explicit pair | `uv run flab2bp "<AMM-URL>" --strategy sequence-pair --candidate-policy output-products --budget 30 -v -o probes/bp-seqpair-outputproducts.txt` | 0:31.19 | 543% | `15:55:47 … load average: 5.72, 5.26, 5.33` | 2652 tiles, **0 errors** |

The default `--strategy best` bake-off already selects the pair the user named,
so the reported blueprint and the explicit-pair blueprint are the same layout:

```
candidate           strategy      area  errors
output-products     sequence-pair    2652       0
no-proliferator     sequence-pair    2700       0
all-products        sequence-pair    3408       0
output-products     freeform         3612       0
all-products        freeform         3819       0
no-proliferator     freeform         4125       0
```

`inputs to belt in:` lists 18 items and **hydrogen is not one of them**.

Artefacts:

* `probes/build-default.log`, `probes/build-seqpair-outputproducts.log` — full CLI output plus `/usr/bin/time -v` and `uptime`.
* `probes/bp-default.txt`, `probes/bp-seqpair-outputproducts.txt` — the emitted blueprints.
* `probes/probe_spec.py` → `probes/spec-dump.txt` — rate solution + all three `BuildSpec` candidates.
* `probes/probe_decode.py` → `probes/decode-default.txt`, `probes/decode-seqpair-outputproducts.txt` — decoded census, belt runs, per-machine sorters.
* `probes/probe_runs.py` → `probes/runs-default.txt` — named belt runs tile by tile.
* `probes/probe_coater.py` → `probes/coater-seqpair.txt` — coater footprints, neighbouring belts with predecessor/successor links, addon-area resolution.

---

## Part 1a — R1: every recipe in the vendored dataset with an item on both sides

`src/flab2bp/lab/vendored/data.json` holds 493 recipes. **Exactly two** have an
item in both `in` and `out`:

| recipe id | name | machine | in | out | self item | net per craft | craft time |
|---|---|---|---|---|---|---|---|
| `x-ray-cracking` | X-ray Cracking | `oil-refinery` | `hydrogen: 2, refined-oil: 1` | `energetic-graphite: 1, hydrogen: 3` | **hydrogen** | **+1** | 4 s |
| `reforming-refine` | Reformed Refinement | `oil-refinery` | `coal: 1, hydrogen: 1, refined-oil: 2` | `refined-oil: 3` | **refined-oil** | **+1** | 4 s |

Both are `oil-refinery` recipes, both are net-POSITIVE in the looped item, and
both are `locked` (a technology gate, not an exclusion). There is no third case
now and none can appear without a dataset bump.

Near-misses that are *not* self-loops and must not be confused with them:

* `deuterium-fractionation` (`hydrogen: 0.01 -> deuterium: 0.01`, producer `fractionator`) — the Fractionator's hydrogen pass-through is **not modelled** in the dataset. FactorioLab expresses it as pure conversion, so no item is on both sides. See Part 2.
* `graphene-advanced` (`fire-ice -> graphene + hydrogen`) with `deuterium` (`hydrogen -> deuterium`) — two *different* recipes forming a producer/consumer pair. This is the case `CoproductBufferProof` exists for.
* `plasma-refining` + `reforming-refine` — DSP's only two-recipe cycle. Covered by `tests/rates/test_solve.py::test_two_recipe_cycle_balances_in_every_capacity_regime`.

Reproduce with `probes/probe_spec.py`, or:

```python
import json
d = json.load(open("src/flab2bp/lab/vendored/data.json"))
[(r["id"], sorted(set(r.get("in") or {}) & set(r.get("out") or {}))) for r in d["recipes"]
 if set(r.get("in") or {}) & set(r.get("out") or {})]
# [('x-ray-cracking', ['hydrogen']), ('reforming-refine', ['refined-oil'])]
```

## Part 1b — R1: what the rate solver and the BuildSpec say

From `probes/spec-dump.txt`, the winning `output-products` candidate:

```
group recipe=x-ray-cracking machine=oil-refinery n=4 mode=none
   in  hydrogen      149/360  (0.4139/s)   total 149/90  (1.6556/s)
   in  refined-oil   149/720  (0.2069/s)   total 149/180 (0.8278/s)
   out energetic-graphite 149/720 (0.2069/s) total 149/180 (0.8278/s)
   out hydrogen      149/240  (0.6208/s)   total 149/60  (2.4833/s)
   SELF-LOOP hydrogen: net per machine 149/720 (0.2069/s)

external_inputs:  … 'refined-oil': '437/180' …          <-- NO hydrogen
outputs:          {'advanced-mining-machine','re-composing-assembler','assembling-machine-3','plane-smelter'}
surplus_outputs:  {'hydrogen': '149/180'}                <-- 0.8278/s leaves the block
coproduct_buffer_proofs: ()                              <-- EMPTY
```

The other two candidates agree in shape (`no-proliferator`: 4 refineries, net
29/120 per machine, surplus 29/30; `all-products`: 3 refineries, net 125/648,
surplus 125/216).

**The rate layer nets the self-consumption correctly and completely.**

* `src/flab2bp/rates/solve.py:1306-1318` computes `external_inputs[item] = consumed - produced` over the whole block. Hydrogen's block-wide `produced` (149/60) exceeds `consumed` (149/90), so the shortfall is negative and **hydrogen never becomes an external input**.
* `src/flab2bp/rates/solve.py:1325-1329` computes `surplus[item] = produced - consumed - target`, giving `hydrogen: 149/180`.
* The closed-form solve is `x*(3-2) = demand`, covered by `tests/rates/test_solve.py:672 test_self_consuming_recipe_solves_in_closed_form`.
* `tests/rates/test_solve.py:596` carries the standing note **"No corpus URL at any tier activates a self-consuming recipe — I checked all twelve across Mk.I/II/III."** AMM-URL is the first URL that does. That is why nothing downstream was ever exercised on this shape.

`_coproduct_buffer_proofs` (`src/flab2bp/rates/candidates.py:101-149`) is the
existing start-up-liveness machinery and it **declines this case at three
separate gates**:

| gate | line | x-ray-cracking |
|---|---|---|
| producer recipe has >1 output | `candidates.py:115` | passes (energetic-graphite + hydrogen) |
| exactly one producer group and one consumer group | `candidates.py:120` | passes — they are the *same* group |
| producer machine ∈ `{chemical-plant, quantum-chemical-plant}` | `candidates.py:127` | **fails** — `oil-refinery` |
| consumer's recipe inputs == `{item}` | `candidates.py:128` | **fails** — `{hydrogen, refined-oil}` |
| producer's inputs ⊆ external inputs | `candidates.py:129` | passes (`{hydrogen, refined-oil}` … hydrogen is not external, so **fails**) |

So `coproduct_buffer_proofs` is empty, and `flow.coproduct_buffer`
(`src/flab2bp/layout/validate.py:4632-4636`) iterates that empty tuple and
yields nothing. **It is a certificate verifier, not a liveness requirement**:
it can only convict a proof that is wrong, never the absence of one.

## Part 1c — R1: what the layout actually emits (decoded, by hand)

Decoded from `probes/bp-seqpair-outputproducts.txt`. 2105 buildings: 1893
`conveyor-belt-2`, 140 `sorter-1`, 12 `sorter-2`, 28 `assembling-machine-2`,
16 `tesla-tower`, 6 `splitter`, **4 `oil-refinery`**, 3 `chemical-plant`,
**2 `spray-coater`**, 1 `arc-smelter`.

The four refineries:

```
oil-refinery#742 at (6,17)  recipe=x-ray-cracking  in_sorters=2 out_sorters=3
oil-refinery#743 at (13,17) …
oil-refinery#744 at (20,17) …
oil-refinery#745 at (27,17) …
      from run 25: [(no filter)]        <-- hydrogen INPUT
      from run 55: [(no filter)]        <-- refined-oil INPUT (external, head at (4,0))
      out -> run 23: energetic-graphite
      out -> run 24: energetic-graphite
      out -> run 25: hydrogen           <-- hydrogen OUTPUT, ONTO THE SAME RUN
```

**Run 25 is both the hydrogen output lane and the hydrogen input lane.** It is
one physical belt run of 107 tiles. Traced tile by tile from
`probes/runs-default.txt`:

```
[  0] belt#714  (3,21,0)   HEAD: fed by NOTHING (open belt head)
[  4] belt#718  (7,21,0)   <- hydrogen from oil-refinery#742
[ 11] belt#725  (14,21,0)  <- hydrogen from oil-refinery#743
[ 18] belt#732  (21,21,0)  <- hydrogen from oil-refinery#744
[ 25] belt#739  (28,21,0)  <- hydrogen from oil-refinery#745
[ 27..68]  (30,21) -> (30,23) -> (31,23) -> climbs z 0->3 -> west along y=15 at z=3
           -> (9,14,3) -> descends -> (3,13,0)
[ 69] belt#609  (3,14,0)   turns east along y=14 at z=0
[ 71] belt#611  (5,14,0)   -> oil-refinery#742 hydrogen input sorter
[ 78] belt#618  (12,14,0)  -> oil-refinery#743
[ 85] belt#625  (19,14,0)  -> oil-refinery#744
[ 92] belt#632  (26,14,0)  -> oil-refinery#745
[ 93..106] (26,13) -> (26,0)  TAIL TERMINATES (open belt end at the north edge)
```

So the emitted geometry is:

1. collect all produced hydrogen (2.4833/s) on one lane;
2. carry it over the machine band and back to the refineries' input row;
3. let each refinery's input sorter tap it in series (1.6556/s total);
4. let whatever survives the last tap (0.8278/s — exactly `surplus_outputs`) run to the block edge at (26,0) and leave.

**This is a correct steady-state priority loop and it needs no splitter.** A
serial belt gives strict priority to the first tap; consumers are fed before
the boundary sees anything. The user's suggested "splitter with the priority
set to loop to itself and push the excess off to the output" is already
achieved by belt order, at zero extra buildings. Nothing here is broken in the
*routing*.

### The actual defect: cold start

DSP machines paste **empty**, and a DSP blueprint cannot carry building
inventory (`BlueprintBuilding` in `src/flab2bp/dsp/records.py:66-119` has no
inventory field; `content` is a text string). At paste time:

* refined oil arrives on run 55 from the boundary;
* hydrogen exists **nowhere** — run 25 is empty, and its only source is the
  refineries themselves;
* an Oil Refinery running X-ray Cracking needs `hydrogen: 2` **and**
  `refined-oil: 1` in its slots before it crafts.

The block therefore never produces its first craft. **The blueprint pastes
cleanly, validates with zero errors, and deadlocks forever.** That is exactly
the user's "requires the input start externally as well": the only way to start
it is to inject hydrogen by hand into run 25 (its open head at `(3,21)` is
where you would do it), or to belt the surplus tail at `(26,0)` back around to
that head.

Minimum seed: 2 hydrogen starts one refinery (net +1 per 4 s craft), so the
loop bootstraps from a single injection; 8 (2 per refinery) starts all four at
once. Nothing in the blueprint, its description, the CLI output, or the web
payload says so.

### Why no validator check fires

| check | file:line | why it passes |
|---|---|---|
| `flow.conservation` | `validate.py:5112-5158` | clause 1 is `produced - consumed + external - outputs - surplus` per item; hydrogen nets to exactly 0. Clause 2 (`_lane_balance`) is a directed max-flow *steady-state* feasibility question; the produced hydrogen does reach the input taps. Neither clause has any notion of an initial fill. |
| `flow.coproduct_buffer` | `validate.py:4632-4636` | iterates `spec.coproduct_buffer_proofs`, which is empty. Vacuous. |
| `flow.external_entry_points` | `validate.py:4499-4530` | `_entry_runs` (`validate.py:4345-4367`) filters by `set(spec.external_inputs)`. Hydrogen is not in it, so run 25 is not an entry and is never reported. |
| `flow.external_entry_reachable` | `validate.py:4439-4466` | same filter; run 25 is invisible to it. |
| `flow.lane_sourced` | `validate.py:4150-4184` | run 25 **is** sourced — four refinery output sorters put onto it. Correctly silent. |
| `belt.termination` | `validate.py:3572-3657` | judges only the TAIL overshoot past the last tap. Run 25's tail leaves the block; its four-tile unfed HEAD stub at `(3,21)`–`(6,21)` is not a question this check asks. |
| `belt.acyclic` | `validate.py:3510-3562` | **ERROR** on any belt cycle. Relevant to the design: physically closing the loop into a true ring is forbidden by our own validator today, even though DSP permits belt loops. |
| `markers.mark_external_belts` | `layout/markers.py:96-140` | marks heads whose `carries_item` is in `spec.external_inputs`. Hydrogen is not, so run 25's head gets **no icon**. `unmarked_external_inputs` (`markers.py:146`) also only speaks about `external_inputs`, so nothing warns. |
| CLI / web | `cli.py:39-50`, `web/payload.py:124,212` | both print `spec.external_inputs`. Hydrogen is absent from both surfaces. |

**Summary of R1:** the loop is built, correctly and elegantly; the spec's
arithmetic is right; what is missing is a *start-up* obligation — nothing
declares that hydrogen must be primed once, nothing marks the lane, and no
check requires either.

---

## Part 1d — R2: three items on one belt, and the coater merge

The user's "mining machine producers" are the two
`assembling-machine-2` running the `advanced-mining-machine` recipe (the
assemblers that BUILD Advanced Mining Machines), at `(58,22)` and `(62,22)`:

```
assembling-machine-2#30 at (58,22) recipe=advanced-mining-machine in_sorters=5 out_sorters=1
      from run 7:  ['frame-material', 'optical-grating-crystal', 'super-magnetic-ring']
      from run 16: ['quantum-chip', 'titanium-alloy']
assembling-machine-2#31 at (62,22)  — identical
```

Five ingredients, five filtered sorters, but only **two** belt runs. Run 7
carries three distinct items; run 16 carries two.

The two Spray Coaters ride exactly those two runs:

```
Spray Coater footprint: (1, 3)          # 1x3, so at yaw 90 it covers 3 tiles along x
addon_areas: (dx=0, dy=0,     dz=0, area=0)   # the cargo belt it rides
             (dx=0, dy=-5/4,  dz=1, area=1)   # the proliferator supply, 1.25 behind and 1 level up

coater#768 at (54,20,0) yaw=90  -> area 0 = belt#1  (54,20,0) run 7   [3 items]
coater#771 at (54,26,0) yaw=90  -> area 0 = belt#20 (54,26,0) run 16  [2 items]
```

Both coaters store `input_obj = output_obj = -1`: a coater carries no
connection of its own and the game resolves it by position
(`catalog.py:1305-1319`, `validate.py:2188-2210`). So the literal claim "three
belts are attached to the coater" is not in the record — but the geometry that
produced the picture is, and it is worse than it looks:

```
belt#0   (53,20,0) run 7  pred=[817, 1872]  <<< 2-INTO-1 BELT MERGE, ON A TILE THE COATER BODY COVERS
belt#1   (54,20,0) run 7  pred=[0]              (this is the coater's area-0 belt)
belt#1871(54,19,1) run 7  pred=[1870, 1886] <<< 2-INTO-1 BELT MERGE, one tile away
belt#19  (53,26,0) run 16 pred=[830, 2037]  <<< 2-INTO-1 BELT MERGE, on coater#771's body
```

Run 7 is assembled from three sources that converge within two tiles of the
coater:

* `frame-material` — from the five `frame-material` assemblers, head `belt#173 (33,10)`;
* `super-magnetic-ring` — run 22, merging at `belt#1871 (54,19,1)`;
* `optical-grating-crystal` — run 27 (external, from the east boundary at `(67,20)`), merging at `belt#0 (53,20,0)`, **under the coater**.

A native DSP belt merge is not proportional-fair: the merged lane is
first-come, and when one source runs ahead it fills the belt and the others
back up. Three items whose consumers are the same two assemblers must arrive
**interleaved in the recipe's exact proportion** or the lane deadlocks on
whichever item is over-supplied. Nothing in the emitter arranges that
interleaving and nothing could: the three sources are independent.

### A second, narrower hazard on coater#768

Coater#768's addon area 1 (the proliferator supply) sits 1.25 tiles from the
coater body at z+1. **Two belts are equidistant at 0.250, on opposite sides:**

```
area 1 (one yaw reading)  -> world (55.25,20.00,1.00); nearest belt#812 (55,20,1) run 27  [cargo lane]  dist=0.250
area 1 (other yaw reading) -> world (52.75,20.00,1.00); nearest belt#767 (53,20,1) run 59  [proliferator] dist=0.250
```

`ADDON_AREA_RADIUS = 1.0`, so **both** are inside the area the game searches.
Only the yaw convention separates them. Coater#771 is unambiguous (the mirror
side's nearest belt is 1.031 away, outside the radius). Our validator's
`game.addon_supply` (`validate.py:2228-2247`) only asks whether *a* belt is
found in each area; it never asks whether a *second* belt is also in there.
Run 27 — a cargo lane — is routed through coater#768's proliferator supply
area at z=1, and nothing forbids it. This is not proven to mis-resolve in game,
but it is an unbounded ambiguity our geometry created and our checks do not see.

### Where the mixed lane comes from

Two distinct mechanisms, and they must not be conflated:

**M1 — mixing as a FEASIBILITY fallback.**
`freeform._seat_inputs` (`src/flab2bp/layout/freeform.py:2170-2292`) seats
ingredients into lane rows. Its "mixing ladder" is

```python
# freeform.py:2243-2245
mix_sizes = (
    range(max(1, max_per_lane), 0, -1) if prefer_shared else range(1, max(1, max_per_lane) + 1)
)
```

Without `prefer_shared` it tries **one item per lane first** and only escalates
to 2, 3, … items per lane when the row caps (`_side_lane_caps`) or the face's
insert-pose columns cannot hold one-per-lane. Its own docstring records the
load-bearing case (`freeform.py:2208-2223`): **`universe-matrix` takes six
ingredients into a Matrix Lab that offers three columns per face, and seats
only as "three ingredients mixed onto one lane above, three onto one below,
and the product out east."** Banning mixed lanes outright turns that spec into
a refusal.

**M2 — mixing as a DENSITY PREFERENCE.**
`strip_variants._logical_strip_plans` (`src/flab2bp/layout/strip_variants.py:1358-1360`):

```python
prefer_shared_inputs = (
    prefer_shared_proliferation and group.proliferated and len(input_items) >= 3
)
```

and it hands `_seat_inputs` both `prefer_shared=True` (which **reverses** the
ladder — mix as hard as possible first) and `lane_fits=input_lane_fits`
(`strip_variants.py:1363-1374`), a pure rate test:

```python
def input_lane_fits(lane, input_rates=group_input_rates, machine_count=group.count) -> bool:
    total = sum((rate * machine_count for item, rate in input_rates if item in lane), ...)
    return total <= spec.lane_capacity * _input_stack(lane, spec)
```

`input_lane_fits` asks only "does the SUM fit the belt". It does not ask whether
the items can interleave, whether their sources can be merged fairly, or
whether one of them can back up. `prefer_shared_proliferation` is threaded from
`generate_strip_families` (`strip_variants.py:1985,1996`); the whole purpose is
to reduce coater count — five sprayed ingredients become two lanes and
therefore two coaters instead of five. **This is the mechanism that produced
run 7, and it fires even though one-item-per-lane would have fitted.**

A third, unrelated mechanism that must be preserved:

**M3 — belt SHARING between several consumers of the SAME item.**
`freeform._merge_lanes` (`freeform.py:1854-1959`) folds a producer's
*destinations* onto fewer OUTPUT lanes: one item, several consumer strips, one
lane, each consumer tapping it. `_merge_frontier` (`freeform.py:8934`) does the
routing half. This is one item per lane throughout and is documented as
load-bearing for feasibility on 12 of 36 corpus cells. **It is not the same
mechanism and must not be touched.**

`_seat_both_fed_outermost` (`strip_variants.py:1137-1249`) is a fourth,
orthogonal thing: it moves an item that is BOTH belted in and produced inside
(`both_fed = frozenset(spec.external_inputs) & frozenset(producers)`,
`strip_variants.py:1295`) to a lane row with two belt approaches. Its own
comment records `universe-matrix`'s `{'hydrogen'}` as the only corpus instance.
Note that a lane may hold several items and still count as one both-fed lane
(`strip_variants.py:1157-1160`).

### Why no validator check fires on R2

| check | file:line | why it passes |
|---|---|---|
| `flow.belt_capacity` | `validate.py:5469-5491` | correctly sums **across every item on the run**. Run 7's three items total well under `conveyor-belt-2`'s 12/s. Genuinely satisfied. |
| `prolif.coaters_are_supplied` | `validate.py:4832-4879` | checks `selected_item(coater, 0) in spec.spray_lanes` — a single `carries_item` label on the host belt. A mixed lane still has exactly one label, so the other two items are invisible here. |
| `prolif.sprayed_cargo_reaches_machines` | `validate.py:5011-5039` | asks, per machine and per sprayed ingredient, whether its pickup is downstream of a coater. All three items pass under coater#768, so all three are satisfied. |
| `game.addon_supply` | `validate.py:2188-2247` | asks whether *a* belt exists in each addon area. It never asks whether the area is unambiguous, nor whether the coater's own belt run merges under its body. |
| `_coater_rides` | `validate.py:4898-4917` | maps `belt -> coater` for area 0 only. Nothing constrains that belt's predecessors. |
| `belt.acyclic`, `game.belt_crossing`, `game.belt_collide` | `validate.py:3510, 2559, 2766` | a 2-into-1 merge is a legal DSP shape (`validate.py:3520-3522` says so explicitly), so none of these object. |

**There is no check anywhere that a belt run carries one item, and no check
that a Spray Coater's host run has a single predecessor chain under its body.**

---

## Part 2 — Prior art: what actually exists, and why it does not cover this

The brief hypothesised an existing "fractionator loop block producer". **It does
not exist.** Searching `src/` for `fractionator`, `loop`, `recirculat`:

```
src/flab2bp/dsp/catalog.py:228     FRACTIONATOR_ID = 2314
src/flab2bp/dsp/catalog.py:1299    (docstring) "... Fractionator, the mining machines, the logistic stations"
src/flab2bp/dsp/catalog.py:1305    (docstring) "no sorter at all (Storage Tank, Fractionator, Splitter, belts)"
src/flab2bp/dsp/registry.py:218    _e("catalog.FRACTIONATOR_ID", Kind.DATA)
src/flab2bp/layout/validate.py:1643 (docstring) "... or a Fractionator, neither of which defines a sorter slot"
```

That is the complete set. `FRACTIONATOR_ID` is a catalog constant with no
layout, rates, emission, or validation behaviour behind it, and
`deuterium-fractionation` never becomes a `MachineGroup` in any corpus build.
Crucially, the dataset does **not** model the Fractionator's hydrogen
pass-through at all (`hydrogen: 0.01 -> deuterium: 0.01`), so it is not a
self-loop recipe in our terms and would not be one even if it were built.

Three things that DO exist and are the real prior art:

### 2.1 `CoproductBufferProof` — a start-up-liveness certificate for a *pair* of recipes

End to end:

* **rates** — `rates/candidates.py:101-149` derives proofs. For each item both produced and consumed, with exactly one producer group (multi-output) and one consumer group, on a `chemical-plant`, where the consumer's only ingredient is that item and the producer's ingredients are all external, it computes `required = producer_batch + consumer_batch - gcd(...)` against `intrinsic = producer_batch * rules.CHEMICAL_OUTPUT_BUFFER_CRAFTS` and emits a proof when the machine's own output buffer covers it.
* **spec** — `spec.py:110-119` `CoproductBufferProof`, carried on `BuildSpec.coproduct_buffer_proofs` (`spec.py:199`), described as "Startup-liveness certificates derived from exact recipe batches and the selected machine's game-defined internal output capacity."
* **strip plan / emission** — nothing. Proofs impose no geometry.
* **hierarchy** — `layout/hierarchy/partition.py:349-351,419` propagates proofs into sub-block specs.
* **validation** — `validate.py:4632-4724` re-derives the arithmetic, then requires that the single producer's buffered output physically aggregates at the single consumer.

The modelled case is `graphene-advanced` (fire ice → graphene + hydrogen) feeding
`deuterium` (hydrogen → deuterium) — see `tests/layout/test_validate.py:680-708`.

**Why it does not apply to X-ray Cracking:** four of its five gates fail (table
in Part 1b). Structurally, it is a *two-machine* certificate — producer buffer
carries the consumer over one atomic batch — and X-ray Cracking is *one*
machine that is its own producer and consumer, on an `oil-refinery` (not a
chemical plant), with a second ingredient (`refined-oil`). Its buffer rule
(`rules.CHEMICAL_OUTPUT_BUFFER_CRAFTS`) is a chemical-plant fact and is not
transferable. And even a valid proof would not help: a self-loop's problem is
not "one batch is indivisible", it is "the loop contains zero items at t=0".

### 2.2 The 2026-08-28 self-consuming flow feedback work — the routing half

`docs/superpowers/plans/2026-08-28-self-consuming-flow-feedback.md` did exactly
the routing part of this problem for `reforming-refine`:

* fixture `tests/fixtures/flow_refined_oil_self_feedback.csv` (twenty refineries, gross 15 refined-oil/s, recycled 10/s, requested net 5/s);
* the rule "**a self-consuming product remains an internal routing net; never reclassify it as an external input**";
* `_logical_strip_plans` keeps BOTH `(item, own_group_key)` and `(item, "")` in `out_lanes`, so the strip gets an internal loop lane and a boundary lane;
* `_nets_between` (`freeform.py:3895-3906`) excludes the self edge from the CP-SAT distance proxy only, keeping the real net for detailed routing;
* tests: `tests/layout/test_freeform.py:971, 993, 1047` and `tests/layout/test_sequence_solver.py:9150`.

**This is why run 25 exists and is correct.** That plan explicitly scoped
itself to routing: "Do not change rate solving … or external-input
classification". The start-up question was never in it, and the fixture is a
`flow`-pinned CSV in which hydrogen arrives from an orbital collector, so the
loop was seeded from outside and the deadlock never appeared.

### 2.3 `both_fed` seating — an item belted in AND produced inside

`strip_variants.py:1289-1295` and `_seat_both_fed_outermost`
(`strip_variants.py:1137-1249`) put such a lane on a true outer row so it can
accept two belt approaches. `universe-matrix` is the only corpus spec with a
non-empty `both_fed` — measured as exactly `{'hydrogen'}`.

This is the machinery a "declare a seed input" design would reuse: it already
knows how to give one lane a boundary feed *and* an internal feed. What it does
not have is any notion of the boundary feed being a *one-off prime* rather than
a continuous rate.

**Net conclusion for Part 2:** every piece needed for a self-loop already
exists except the start-up obligation itself. There is nothing to copy from a
"fractionator loop producer" because no such thing was ever written.

---

## Findings, ordered by severity

| id | finding | severity |
|----|---------|----------|
| **F1** | A mixed-item input lane is emitted whenever `prefer_shared_proliferation` fires (`strip_variants.py:1358-1360`), even when one-item-per-lane fits. Three items on run 7, two on run 16, feeding the same two assemblers. The lane can deadlock at run time on whichever item over-supplies. | correctness |
| **F2** | Two belt runs merge 2-into-1 on a tile a Spray Coater's 1×3 body covers (`belt#0 (53,20,0)` under coater#768; `belt#19 (53,26,0)` under coater#771). No check forbids it. | correctness |
| **F3** | A self-loop recipe's loop lane is emitted with no seed and no declaration. The blueprint pastes, validates clean, and deadlocks at t=0. | correctness |
| **F4** | Coater#768's proliferator addon area has two belts inside `ADDON_AREA_RADIUS` at equal distance, one of them a cargo lane. `game.addon_supply` accepts the first it resolves. | robustness |
| **F5** | Run 25's four-tile unfed head stub at `(3,21)`–`(6,21)` serves nothing and is not reported (`belt.termination` measures only tail overshoot). | cosmetic |

The design and the plan that follow are
`docs/superpowers/specs/2026-09-06-self-loop-recipes-design.md` and
`docs/superpowers/plans/2026-09-06-self-loop-recipes.md`.
