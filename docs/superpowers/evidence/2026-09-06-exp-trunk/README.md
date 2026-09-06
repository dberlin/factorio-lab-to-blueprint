# Trunk pre-assignment for the widest-spread ingredient

*Spike, branch `exp-trunk`, 2026-09-06. Everything here is throwaway except this
directory and the one default-off flag in `src`.*

**Question.** Does reserving a bus corridor with taps for the widest-spread
ingredient, before the placers run, turn refusals into layouts or cut wall time,
at a bounded area cost? This is the cheapest kind of specialisation in
`docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md` §4 -- a
problem transform in front of the existing placers -- and item 3 of
`docs/speedup-idea-backlog.md`.

**Answer: no, on every axis, and the router says why in its own words.** See
[Answers](#answers).

---

## What the pipeline already does

Two findings from reading the code and probing the prepared routing problem
reshaped the experiment before a line of it was written. Both are the reason the
result is negative, and both are worth more than the measurement.

### 1. The extreme case already has a trunk

`proliferator-3` is by far the widest item on any all-products spec: on the mall
it is wired by **73 nets to 73 destinations**, on `zurl2` by 66
(`probe-mall.jsonl`, `probe-zurl2.jsonl`). Those are already *post-transform*
nets. `_place_proliferator_entry` (`src/flab2bp/layout/freeform.py:19162`) stakes
a north-west root and `_proliferator_supply_tree` (`freeform.py:18914`) lays a
reserved perimeter run with one tap per coater group, guarding each future
Splitter's keep-out before any leaf net routes. Its own refusal strings -- *"the
reserved proliferator perimeter trunk is occupied"*, *"the proliferator
perimeter trunk cannot branch"* -- are the trunk idea, shipped, for the item the
backlog names as the extreme case.

**A separate proliferator arm is therefore not worth running: it would measure
the code that is already in production.**

### 2. Sharding has already dissolved every internal fan-out

The trunk's premise is that the router sees "one k-consumer family". It does
not. A producer group is sharded into strips, each with its own output lane, and
`_join_shard_islands` pairs shards to consumers. The widest INTERNAL item in the
prepared problem is therefore close to a 1:1 matching:

| cell | widest internal item | nets | source lanes | destination ports | fan-out |
| --- | --- | --- | --- | --- | --- |
| universe-matrix@60 | copper-ingot | 5 | 4 | 5 | 1.25 |
| universe-matrix@60 | iron-ingot | 5 | 4 | 4 | 1.25 |
| mall (all-products) | iron-ingot | 12 | 10 | 9 | 1.20 |
| zurl2 (all-products) | iron-ingot | 13 | 12 | 7 | 1.08 |

(`probe-um60.jsonl`, `probe-mall.jsonl`, `probe-zurl2.jsonl`, via
`sitecustomize.py`.) There is no k-consumer family left to decompose: with an
average fan-out of 1.1-1.3 a trunk replaces *k* short nets with *k+1* longer
ones, every one of them detouring to the perimeter and back.

### 3. Spread and capacity disagree exactly where it matters

Group-level spread (`spread.py`: consumer groups x depth span) over the 72-cell
corpus and the five large cells:

| cell | machines | widest internal item | k | span | spread | its total demand | one lane |
| --- | --- | --- | --- | --- | --- | --- | --- |
| um60 | 224 | iron-ingot | 4 | 5 | 20 | 20.00 /s | 30 /s -- **fits** |
| um120 | 439 | iron-ingot | 4 | 5 | 20 | 40.00 /s | 30 /s -- no |
| qc180 | 131 | copper-ingot | 2 | 1 | 2 | 9.22 /s | 30 /s -- fits |
| mall | 449 | iron-ingot | 7 | 3 | 21 | 278.62 /s | 30 /s -- **no, 9.3x** |
| zurl2 | 436 | graphene | 3 | 5 | 15 | 14.64 /s | 30 /s -- fits |
| zurl2 | 436 | iron-ingot | 6 | 2 | 12 | 86.60 /s | 30 /s -- no, 2.9x |

Corpus distribution of max internal spread (36 freeform cells): 3 cells at 0, 15
at 1, 12 at 2, 3 at 8 (`super-magnetic-ring`), 3 at 20 (`universe-matrix`).
**Twenty-seven of thirty-six corpus cells have a widest item with two consumer
groups or fewer** -- below any threshold at which a bus corridor could pay.

And on the three cells that actually refuse today (mall, zurl2, um120), the
max-spread item's total demand is **1.3x to 9.3x one lane's capacity**. A single
trunk lane there is not merely a bad idea, it is unbuildable, and the validator
says so (`flow.belt_capacity`, below).

---

## Method

### The switch, with file:line

Everything below is the production code path, not a monkeypatch: the trunk is a
default-off flag in `src`, committed separately as
`feat(layout): default-off trunk pre-assignment for a wide internal item`.

* `_TRUNK_ITEMS_ENV = "FLAB2BP_TRUNK_ITEMS"` (`freeform.py:16170`) -- OFF unless
  set. An environment variable rather than a constructor argument because
  `scripts/audit.py:806` fans cells out over a `ProcessPoolExecutor` that Python
  3.14 starts with **forkserver**; a parent-side setting never reaches the
  process that lays a cell out. `auto` picks the single widest internal item of
  the routing problem at hand.
* `_internal_trunk_items` (`freeform.py:16186`) reads it; `None` -- the
  production default -- yields the empty set.
* `_apply_internal_trunks` (`freeform.py:16200`) is the transform. It groups the
  `NetRole.INTERNAL` nets by `(item, cargo_domain)`, and for the chosen item
  replaces its producer-lane-to-consumer-lane nets with one reserved perimeter
  run: each producer lane hops onto a FEED tap at the head, each consumer draws
  from its own DRAW tap downstream. Feed taps precede draw taps because the run
  is linked head-to-tail, so a consumer must never sit upstream of its supply.
* `_TRUNK_MIN_CONSUMERS = 3` (`freeform.py:16175`) -- an item with fewer
  consumer ports is left alone.
* `_INTERNAL_TRUNK_TAP_SPACING = 3` (`freeform.py:16183`) -- wider than
  `_SHARED_EXTERNAL_TAP_SPACING = 2` because an internal trunk has feed taps as
  well as draw taps, so a junction is built on both sides of a tap. **Measured:**
  at spacing two `universe-matrix@60` wires and is then rejected `geom.collide
  (12818, 12821): build colliders intersect`; at three it is clean.
* Call site: `freeform.py:16907`, inside `_prepare_routing_problem` -- after the
  packer, after the strips and coaters and the proliferator trunk are on the
  canvas, before `_place_shared_external_input_trunks` (`freeform.py:16096`) and
  before the second `_reserve_port_access`.
* The perimeter-segment search was factored out of
  `_place_shared_external_input_trunks` into `_perimeter_sides`
  (`freeform.py:16066`) and `_free_perimeter_segment` (`freeform.py:16079`) and
  is shared by both; that function is otherwise unchanged.
* `tests/layout/test_freeform.py::test_internal_trunk_is_off_by_default_and_changes_nothing`
  pins the default: with the variable unset the request is empty and the
  transform mutates neither the canvas nor the nets, *on a net population it
  proves does qualify* once the item is asked for. Full
  `tests/layout/test_freeform.py` is green (exit 0, 0 failures).

### Scope caveat: this is in front of the ROUTER, not in front of the PACKER

The brief asked for the corridor to be reserved before the packer runs. It is
not. `_prepare_routing_problem` receives a finished `_Pack`, so the corridor is
staked on the perimeter of an already-packed core. Reserving it earlier means
teaching the CP-SAT packing model about a forbidden band, which is a different
and much larger change. The results below make that extension look unattractive
rather than merely unbuilt -- the trunk's damage is at the port-seating layer,
not the packing layer -- but it is a real limit on what was measured.

### Measurement

`docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py`, one
process per cell, **two at a time** (other experiments share this box). Load is
recorded at each arm boundary in `run_large.log` / `run_corpus.log` and in
`load-at-start.txt`; this box is never idle and its load is I/O wait.

* `run_large.sh` -- um60, um120 (`--policy no-proliferator`), qc180
  (`--policy all-products`), mall and zurl2 (`--policy all-products`), each in
  `--strategy freeform` and `--strategy sequence-pair --islands 4`, budget 60 s,
  **twice per arm**, arm `off` = unset, arm `on` = `FLAB2BP_TRUNK_ITEMS=auto`.
* `run_corpus.sh` -- the ten corpus cells with the largest max internal spread
  from `spread-corpus.json`, freeform at 30 s, both arms.
  `scripts/audit.py` is deliberately not used.
* `analyze.py` renders `tables.md` from the JSON rows.
* `probe_splitters.py` counts Splitters in the finished blueprint, which the
  harness does not report.

---

## Results

Full tables: [`tables.md`](tables.md). Raw rows: `large/*.json`,
`corpus/*.json`.

### Verdicts

| set | arm | OK | REFUSED |
| --- | --- | --- | --- |
| large (10 cells x 2 runs) | off | 12 | 8 |
| large (10 cells x 2 runs) | **on** | **6** | **14** |
| corpus (10 cells x 1 run) | off | 10 | 0 |
| corpus (10 cells x 1 run) | **on** | **8** | **2** |

Both rounds of every large cell agree on verdict, so nothing below is a
one-run accident.

**Rescued by the trunk: none.** `mall`, `zurl2`, `mallsp` and `zurl2sp` refuse
in both arms.

**Broken by the trunk: five cells that build today.**

| cell | off | on |
| --- | --- | --- |
| `qc180` freeform | OK, 9900 | REFUSED: *1 lane head could not obtain the belt approaches they need (**proliferator-3** into ? at (95, 2, 0) (wants 1, held 0, **0 free side(s)**))* |
| `um120` freeform | OK, 64345 | REFUSED: *`flow.belt_capacity` ... belt run 177 must carry **32 items/s** but its tier sustains only **30** (`per_item: {'copper-ingot': '32'}`)* |
| `um120sp` sequence-pair | OK, 36894 | REFUSED: all 4 islands, deadline + `flow` validation failures |
| `universe-matrix/all-products` corpus | OK, 29744 | REFUSED: *1 lane head could not obtain the belt approaches they need* |
| `quantum-chip/output-products` corpus | OK, 4290 | REFUSED: *no packing of 19 strips could be wired at any candidate height* |

### Cost on the cells that survive both arms

Pairwise, mean over runs:

| set | cells | area | belt tiles | wall | route_all |
| --- | --- | --- | --- | --- | --- |
| large | 3 | **1.0000** | **1.0620** | 0.9979 | 0.9475 (n=1) |
| corpus | 8 | **1.0503** | **1.0806** | 0.9556 | **1.0910** |

(geometric means of the on/off ratio; `qc180sp` is in the large set as the
proven no-op control and contributes exactly 1.0000 to every column.)

Per-cell highlights:

* `um60` freeform, the one large cell where the trunk both fires and survives:
  area identical at 26752, **belt tiles 11853 -> 12353 (+4.2 %)**, nets 69 -> 73,
  **Splitters 11 -> 13** (`splitters-off.json`, `splitters-on.json`). Wall
  32.3 -> 30.5 s and `route_all` 6.46 -> 6.12 s, but the steady-state rounds are
  30.9 vs 30.6 and 6.10 vs 6.09 -- noise, not a saving.
* `um60sp` sequence-pair: area identical, **belt tiles 8761 -> 10068 (+14.9 %)**.
* `universe-matrix/no-proliferator` at 30 s: **area 26752 -> 31898 (+19.2 %)**
  while wall FELL 29.5 -> 26.1 s. The sweep settled sooner on a worse layout;
  that is where most of the corpus "wall saving" comes from.
* `super-magnetic-ring/output-products`: belt tiles 1194 -> 1587 (**+32.9 %**),
  area +6.0 %, `route_all` 1.70 -> 3.87 s.

### Why it breaks things -- in the router's own words

Two distinct mechanisms, both named by the refusal strings:

1. **The trunk lane eats the corridor the PROLIFERATOR trunk needed.** On
   `qc180`, `mall`, `zurl2` and `universe-matrix/all-products` the trunk-on
   refusal is *"N lane heads could not obtain the belt approaches they need"*
   with `route_all_s == 0.00` -- routing never starts. The named casualties are
   `proliferator-3` ports reporting **0 free side(s)**. `_apply_internal_trunks`
   runs at `freeform.py:16907`, after `_proliferator_supply_tree` has staked its
   perimeter run but **before** the second `_reserve_port_access`, and it takes
   its segment from the same `route_bounds` ring. So it can and does occupy the
   only free neighbour of a proliferator tap. This is the predicted "the trunk
   eats the corridor the packer needed", one layer lower down: the corridor it
   eats belongs to the trunk that already exists.
2. **One lane cannot carry a wide item's whole demand.** `um120` refuses on
   `flow.belt_capacity` at exactly the number the spread table predicts:
   copper-ingot needs 32 items/s and a `conveyor-belt-3` run sustains 30.
   Merging *k* independent producer-to-consumer lanes onto one bus is precisely
   the operation that turns *k* under-capacity runs into one over-capacity run.
   The validator arbitrated, as required, and refused.

---

## Answers

**(a) Does the trunk rescue any refusal?** No. Zero of the eight large refusals
and zero of the corpus refusals become layouts; instead five cells that build
today stop building (`qc180`, `um120`, `um120sp`, `universe-matrix/all-products`,
`quantum-chip/output-products`), and the large arm goes 12 OK / 8 REFUSED to
6 OK / 14 REFUSED.

**(b) Does it cut route_all or wall?** No. On the corpus `route_all` is
**+9.1 %** and on the one large cell where it fires and survives it is flat
(6.10 s vs 6.09 s in the steady-state round). Corpus wall is -4.4 %, but that is
not a speed-up: `route_all` rose at the same time, and the biggest wall "saving"
(`universe-matrix/no-proliferator`, 29.5 -> 26.1 s) is the sweep settling sooner
on a layout **19.2 % larger**. Wall fell because quality fell.

**(c) Does it cost area?** Yes, and belt more than area. On the cells both arms
build: area geomean **1.0503** on the corpus (n=8) and 1.0000 on the large set
(n=3); belt tiles **1.0806** and **1.0620**. Worst single cells: +19.2 % area
(`universe-matrix/no-proliferator`) and +32.9 % belt tiles
(`super-magnetic-ring/output-products`). `um60`'s Splitter count rises 11 -> 13:
the trunk adds branch points rather than replacing them.

**(d) Which spread threshold should turn it on?** **None -- there is no
threshold that helps on any measured spec, so the answer is to leave it off.**
A gate would have to pass three tests at once: at least three consumer *lanes*,
the item's total demand at or below one lane's capacity, and a perimeter with
room to spare after the proliferator trunk. That intersection is empty on all 41
measured cells. The wide items fail capacity by 1.3x to 9.3x (mall iron-ingot
278.62 /s against 30 /s); the capacity-safe items are too narrow (27 of 36
corpus cells have a widest internal item with two consumer groups or fewer, and
after sharding the prepared fan-out is 1.1-1.3 nets per source lane); and the
all-products cells lose their proliferator approaches. The one cell that clears
all three -- `um60`, iron/copper-ingot at 20 /s on a 30 /s belt -- gains nothing
and pays 4.2 % more belt.

**Where the idea does still live.** The backlog's own extreme case is already
implemented and load-bearing: `_proliferator_supply_tree` is a reserved
perimeter trunk with taps, and it is what turns 73 coater feeds into 73 short
nets on the mall. The general lesson for the orchestrator is that *this*
transform is not free specialisation -- the perimeter is a scarce shared
resource with an incumbent, and any future trunk must be planned jointly with
the proliferator's, not stacked on top of it.

---

## Caveats

* **Not reserved before the packer.** See the scope caveat above. A trunk that
  the packer knew about could not be blamed for a corridor the packer needed --
  but the observed damage is to *port seating*, which happens after packing
  either way, so the fix would have to be reserving the corridor before
  `_place_proliferator_entry`, not before the packer.
* **One item at a time.** `auto` trunks the single widest item. Trunking several
  was never reached because the first one already regresses.
* **`sequence-pair` shares the transform** through
  `_prepare_routing_problem` (imported at `sequence_solver.py:74`), so its rows
  are a second independent read of the same change, not a control.
* **`qc180sp` is the noise control**: its widest internal item has two consumer
  ports, below `_TRUNK_MIN_CONSUMERS`, so the transform is a proven no-op there
  and both arms must agree exactly. They do.
* Spread in `spread.py` is computed at GROUP level; the router works at LANE
  level, where a group is sharded. The two agree on ordering but not on
  magnitude, which is why the prepared-problem probe was needed at all.
* Every measured spec has `belt_stack == 1`, so the existing shared external
  input trunk path never fires on any of them; the internal trunk measured here
  is the only trunk in play besides the proliferator's.
