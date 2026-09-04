# R4 — Why the `hydrogen` nets into `casimir-crystal#1` and `energy-matrix#12` can never be wired

Read-only research, master `e0bf432`. Every experiment ran in a throwaway `git archive` copy at
`/tmp/claude-839601109/-home-dannyb-sources-factorio-lab-to-blueprint/8e787b45-e7bb-460a-9069-84e8ce0bea85/scratchpad/phase-e-R4`
with the checkout's compiled kernels copied in and the checkout's `.venv/bin/python` driving the
copy's own `scripts/audit.py`. **No file in the checkout was modified** (this report is written into
the git-ignored `.superpowers/` tree).

---

## 0. Headline

**Blocker class: (a), a strip-generation defect — with a router-side amplifier that cannot be
removed.**

The stranded `hydrogen` ports are the WEST HEAD TILE of the MIDDLE input lane of a stack of input
lanes. Three of that tile's four neighbours are the sink strip's **own** belts and its **own**
machine band: the lane above it, the lane below it (or the machine band), and its own lane's second
tile. Exactly one neighbour — the tile due west, in the strip's `WEST_CHANNEL` column — is free, and
that is true **by construction for every middle lane of every strip**, at every height, in every
pack, under every arrangement.

That single free tile is enough for one approach and the port needs **two**:
`_prepare_routing_problem`'s `twice` set (`freeform.py:14188-14196`) adds a second corridor demand to
any input port whose item is also a `spec.external_inputs` item, because that lane is fed from the
boundary *and* from an internal producer. `_reserve_port_access` (`freeform.py:10061-10190`) then
reports `wants=2, held=1` and the port lands in `unreachable_ports`, which
`freeform.py:14512-14529` turns into a `RouteFailureKind.STATIC_ACCESS` `NetFailure` for every net
that ends there — 6 for `no-proliferator`, 3 for `all-products`, 6 for `output-products`.

**`universe-matrix` is the only corpus spec in which `hydrogen` is both an external input and an
internally produced item**, which is why `casimir-crystal`, `energy-matrix` and `quantum-chip` place
the same two strips and wire cleanly (§4).

**The fix that works** is one line in strip generation: seat an ingredient that is fed from both
outside and inside on the **outermost** lane row, where the head tile has a second free neighbour.
`input_items` at `strip_variants.py:928` is a bare `tuple(sorted(group.inputs))` — plain
alphabetical — and `hydrogen` lands in the middle by accident of the alphabet. Ordering that key so
the both-fed items come first takes the corpus from **66/72 to 70/72 clean with zero regressions and
+0.11% total area over the 66 baseline-clean cells** (§6, §7).

---

## 1. Reproduction: the exact geometry of every stranded net

### 1.1 Instrumentation

Two dumps were added to the copy, both behind `PHASE_E_PORTDUMP`:

* `_phase_e_port_dump` (inserted before `_prepare_routing_problem`) — for each cell in
  `unreachable_ports`: the owning strip and lane item, the full sink `Strip` record, every lane's
  port cell / `x0` / `x1` / `row_of_input`, the four neighbours with what occupies them and their
  onward cells, and a 13x7 ASCII map.
* A line in `_reserve_port_access` just before it fills `failed_ports` — `wants`, `held`, `roles`,
  membership of `twice`, the free-neighbour set and the full corridor set.

Command (load recorded immediately before; the box is never idle):

```
 13:58:03 up 18 days, 19:44,  9 users,  load average: 4.06, 4.14, 4.27
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 2  0      0 1038427168  0 8613568   0    0 49764 15280 23399   4  5  2 93  0  0  0
 2  0      0 1038363828  0 8613568   0    0     0 18716 17241 44736 1 1 98  0  0  0
 1  0      0 1038298156  0 8613568   0    0     0    12 13651 24520 1 0 98  0  0  0
```

```bash
PHASE_E_PORTDUMP=1 /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python \
    <copy>/scripts/audit.py --budget 30 --jobs 1 --only universe-matrix \
    --strategy freeform --json dump.jsonl
```

Fourteen dump blocks were emitted — four for `no-proliferator` (heights 125/100/80/60; 160 dies at
the seed gate, see R1), five for `all-products`, five for `output-products`. The two failing ports
are **identical in every block**.

### 1.2 `casimir-crystal#1`, port `(1, 10, 0)` — verbatim

```
[R4] ==== unreachable_ports n=2 ====
[R4] canvas.limit=(-2, -3, 259, 122)
[R4] PORT (1, 10, 0) owners=[('casimir-crystal#1', 'in', 'hydrogen', 56, 1, 10, 10)]
[R4]      nets=[('dst', 'hydrogen'), ('dst', 'hydrogen')]
[R4]      sink strip #1 casimir-crystal#1 recipe=casimir-crystal machines=3 pw=4 ph=4 box_h=8
         in_above=(('graphene',), ('hydrogen',), ('titanium-crystal',))
         out_lanes=(('casimir-crystal', 'plane-filter#27', <CargoDomain.UNSPRAYED: 'unsprayed'>),)
         in_below=() flank=False machine_row=3 west_channel=1
[R4]        lane item=graphene         belt=47 cell=(1,9,0)  x0=1 x1=9  row_of_input=0 lane=('graphene',)
[R4]        lane item=hydrogen         belt=56 cell=(1,10,0) x0=1 x1=10 row_of_input=1 lane=('hydrogen',)
[R4]        lane item=titanium-crystal belt=66 cell=(1,11,0) x0=1 x1=11 row_of_input=2 lane=('titanium-crystal',)
[R4]      nb (2, 10, 0) free=False owner=blocked<b57 Conveyor Belt Mk.III strip=casimir-crystal#1> onward=[((3, 10, 0), False, 'blocked<b58 Conveyor Belt Mk.III strip=casimir-crystal#1>'), ((2, 11, 0), False, 'blocked<b67 Conveyor Belt Mk.III strip=casimir-crystal#1>'), ((2, 9, 0), False, 'blocked<b48 Conveyor Belt Mk.III strip=casimir-crystal#1>')]
[R4]      nb (0, 10, 0) free=False owner=reserved_for=(1, 10, 0) onward=[((-1, 10, 0), False, 'reserved_for=(1, 10, 0)'), ((0, 11, 0), False, 'reserved_for=(1, 11, 0)'), ((0, 9, 0), False, 'reserved_for=(1, 9, 0)')]
[R4]      nb (1, 11, 0) free=False owner=blocked<b66 Conveyor Belt Mk.III strip=casimir-crystal#1> onward=[((2, 11, 0), False, 'blocked<...>'), ((0, 11, 0), False, 'reserved_for=(1, 11, 0)'), ((1, 12, 0), False, 'blocked<b89 Assembling Machine Mk.III strip=?>,solid')]
[R4]      nb (1, 9, 0) free=False owner=blocked<b47 Conveyor Belt Mk.III strip=casimir-crystal#1> onward=[((2, 9, 0), False, 'blocked<...>'), ((0, 9, 0), False, 'reserved_for=(1, 9, 0)'), ((1, 8, 0), True, 'FREE')]
[R4]      map (y rows, x cols) '.'=free '#'=blocked 'R'=reserved:
[R4]      y=   7 x=  -5: ???...#######
[R4]      y=   8 x=  -5: ???..........
[R4]      y=   9 x=  -5: ???.RR#######
[R4]      y=  10 x=  -5: ???.RRP######
[R4]      y=  11 x=  -5: ???.RR#######
[R4]      y=  12 x=  -5: ???...###.###
[R4]      y=  13 x=  -5: ???...###.###
```

(`?` is outside `canvas.limit`; `P` is the port; the two `R` west of it are its ONE held corridor,
access `(0,10,0)` + exit `(-1,10,0)`.)

Reading the four sides:

| side | cell | occupant | owner |
|---|---|---|---|
| east | `(2,10,0)` | Conveyor Belt Mk.III `b57` | **its own hydrogen lane**, tile 2 |
| north | `(1,9,0)` | Conveyor Belt Mk.III `b47` | **its own graphene lane**, head |
| south | `(1,11,0)` | Conveyor Belt Mk.III `b66` | **its own titanium-crystal lane**, head |
| west | `(0,10,0)` | free, reserved to this port | the strip's `WEST_CHANNEL` column |

Row `y=12` is `casimir-crystal#1`'s own Assembling Machine band (`machine_row=3`, strip origin
`y=9`). **Nothing belonging to a neighbouring strip touches this port.** The blocker is 100% the
sink strip's own geometry.

### 1.3 `energy-matrix#12`, port `(1, 113, 0)` — verbatim

```
[R4] PORT (1, 113, 0) owners=[('energy-matrix#12', 'in', 'hydrogen', 988, 1, 33, 113)]
[R4]      nets=[('dst', 'hydrogen'), ('dst', 'hydrogen')]
[R4]      sink strip #14 energy-matrix#12 recipe=energy-matrix machines=6 pw=6 ph=5 box_h=8
         in_above=(('energetic-graphite',), ('hydrogen',)) in_below=() machine_row=2 west_channel=1
[R4]        lane item=energetic-graphite belt=956 cell=(1,112,0) x0=1 x1=32 row_of_input=0
[R4]        lane item=hydrogen           belt=988 cell=(1,113,0) x0=1 x1=33 row_of_input=1
[R4]      nb (2, 113, 0) free=False owner=blocked<b989 Conveyor Belt Mk.III strip=energy-matrix#12> ...
[R4]      nb (0, 113, 0) free=False owner=reserved_for=(1, 113, 0) onward=[((-1,113,0), False,'reserved_for=(1,113,0)'), ((0,114,0), True,'FREE'), ((0,112,0), False,'reserved_for=(1,112,0)')]
[R4]      nb (1, 114, 0) free=False owner=blocked<b1057 Matrix Lab strip=?>,solid ...
[R4]      nb (1, 112, 0) free=False owner=blocked<b956 Conveyor Belt Mk.III strip=energy-matrix#12> onward=[..., ((1, 111, 0), True, 'FREE')]
[R4]      map:
[R4]      y= 110 x=  -5: ???...#######
[R4]      y= 111 x=  -5: ???..........
[R4]      y= 112 x=  -5: ???.RR#######
[R4]      y= 113 x=  -5: ???.RRP######
[R4]      y= 114 x=  -5: ???...#####.#
```

Same shape: east is its own lane's tile 2, north is its own `energetic-graphite` lane head, south is
its **own** Matrix Lab (`machine_row=2`, strip origin `y=112`, so the band starts at `y=114`), west
is the one free channel tile.

### 1.4 The predicate that emits `STATIC_ACCESS` — nailed

`_reserve_port_access` (`src/flab2bp/layout/freeform.py:10061-10190`):

* `options[key]` = the port's free 4-neighbours (`freeform.py:10148-10156`);
* `corridors[key]` = `(access, exit)` pairs where `exit` is a free 4-neighbour of `access` other than
  the port (`freeform.py:10157-10165`);
* `wants[key] = len(roles[key]) + (1 if key in twice else 0)` (`freeform.py:10120`);
* `_match_access_corridors` (`freeform.py:9990-10058`) is a CP-SAT matching with
  `model.add(sum(by_cell[cell]) <= 1)` — **corridors are cell-disjoint**, so two corridors for one
  port require two distinct access cells;
* `missing = {key for key in order if held[key] < wants[key]}` (`freeform.py:10186`) →
  `failed_ports`.

`preparation_failures` at `freeform.py:14512-14529` maps each `unreachable_ports` cell onto every net
that starts or ends there, via `static_access_failure` (`freeform.py:14469-14510`), producing
`RouteFailureKind.STATIC_ACCESS` (`route_feedback.py:73`).

The `R4-RPA` dump, deduplicated over the whole three-cell run, is the whole story — **every** failing
port on **every** universe-matrix cell at **every** height:

```
[R4-RPA] port=(0, 10, 0)   wants=2 held=1 roles=['dst'] twice=True free_neighbours=((-1, 10, 0),)   corridors=(((-1,10,0),(-2,10,0)), ((-1,10,0),(-1,11,0)), ((-1,10,0),(-1,9,0)))
[R4-RPA] port=(1, 10, 0)   wants=2 held=1 roles=['dst'] twice=True free_neighbours=((0, 10, 0),)    corridors=(((0,10,0),(-1,10,0)), ((0,10,0),(0,11,0)), ((0,10,0),(0,9,0)))
[R4-RPA] port=(1, 113, 0)  wants=2 held=1 roles=['dst'] twice=True free_neighbours=((0, 113, 0),)   corridors=(((0,113,0),(-1,113,0)), ((0,113,0),(0,114,0)), ((0,113,0),(0,112,0)))
[R4-RPA] port=(128, 1, 0)  wants=2 held=1 roles=['dst'] twice=True free_neighbours=((127, 1, 0),)   ...
[R4-RPA] port=(75, 1, 0)   wants=2 held=1 roles=['dst'] twice=True free_neighbours=((74, 1, 0),)    ...
[R4-RPA] port=(75, 23, 0)  wants=2 held=1 roles=['dst'] twice=True free_neighbours=((74, 23, 0),)   ...
[R4-RPA] port=(75, 41, 0)  wants=2 held=1 roles=['dst'] twice=True free_neighbours=((74, 41, 0),)   ...
[R4-RPA] port=(93, 15, 0)  wants=2 held=1 roles=['dst'] twice=True free_neighbours=((92, 15, 0),)   ...
[R4-RPA] port=(93, 41, 0)  wants=2 held=1 roles=['dst'] twice=True free_neighbours=((92, 41, 0),)   ...
[R4-RPA] port=(97, 8, 0)   wants=2 held=1 roles=['dst'] twice=True free_neighbours=((96, 8, 0),)    ...
```

Ten distinct ports across three cells and five heights each: **`wants=2`, `held=1`,
`|free_neighbours| == 1`, `twice=True`, and every corridor shares the same single access cell.** It
is not a matching failure — the matching is optimal and there is nothing to match.

`twice` comes from `hold_ports` (`freeform.py:14187-14203`):

```python
shared_feed = {
    (port.x, port.y, port.z)
    for ports in strip_in_ports
    for item, port in ports.items()
    if item in spec.external_inputs
} & net_ports
```

`net_ports` is the set of ports named by an internal `_Net`, so `shared_feed` is exactly *"this input
lane is fed from the boundary AND from inside the block"*.

### 1.5 The blocker classification

**(a), unambiguously.** The blocking cells are the sink strip's own lane belts (`b47`, `b57`, `b66`,
`b956`, `b989`) and its own machine (`b89` Assembling Machine, `b1057` Matrix Lab). No neighbouring
strip is involved: on `casimir-crystal#1` all four neighbours belong to strip #1; on
`energy-matrix#12` all four belong to strip #14. The one free side is the strip's own reserved
`WEST_CHANNEL` column, which no other strip can occupy (`_size`, `freeform.py:1582`;
`_greedy_pack`, `freeform.py:3061`).

Not **(b)**: no packing decision touches these tiles. Not **(c)** *alone*: the router's access model
does add the second demand, but §5 proves the demand is real — removing it just moves the same
failure from prepare time to route time.

The failure is invariant under height, width, arrangement and clock exactly because the four
neighbours translate with the strip.

---

## 2. Strip generation for `casimir-crystal` and `energy-matrix`

| | `casimir-crystal` | `energy-matrix` |
|---|---|---|
| machine | Assembling Machine Mk.III (3 machines, `pw=4`, `ph=4`) | Matrix Lab (6 machines, `pw=6`, `ph=5`) |
| input items | 3: `graphene`, `hydrogen`, `titanium-crystal` | 2: `energetic-graphite`, `hydrogen` |
| lanes laid | 3, all `in_above`, one item each | 2, both `in_above`, one item each |
| `in_below` | `()` | `()` |
| `machine_row` | 3 | 2 |
| `box_height` | 8 | 8 |
| port | `lane_indices[0]`, the WEST head tile of each lane | same |

**How many lanes, and in what order.** `_seat_inputs` (`freeform.py:1991-2087`) slices the item tuple
into contiguous lanes (`lanes = [tuple(items[i:i+k]) for i in range(0, n, k)]`, `freeform.py:2057`)
and returns them **in input order**. The input order is `input_items = tuple(sorted(group.inputs))`
(`strip_variants.py:928`) — **plain alphabetical, with no notion of access at all**. `hydrogen` sorts
between `graphene` and `titanium-crystal`, and after `energetic-graphite`. Both times it lands on a
row whose head tile has one free neighbour.

**Port assignment is fully deterministic.** The lane belts are laid west-to-east starting at the
strip origin (`freeform.py:5186-5205`, `start = -s.west_channel if row in lane_starts_west else 0`,
and `lane_starts_west` is populated only for `CargoDomain.REQUIRES_SPRAY`), and `feed()` takes
`head = canvas.buildings[lane_indices[0]]` — always the west head, always at the strip's own origin
column, identically for every lane. So **every input lane head on a strip sits in the same column**,
which is what stacks them into a wall.

### 2.1 Does `strip_variants.py` already offer a variant that would work? No.

`_variants` (`strip_variants.py:1370-1419`) enumerates `_attachment_plan_seatings`
(`strip_variants.py:1235-1254`), which is `product(_side_seatings(south), _side_seatings(north))`.
`_side_seatings` (`strip_variants.py:1210-1232`) is the decisive one:

```python
side_lanes = tuple(
    sorted(
        (lane for lane in lanes if lane.side == side),
        key=lambda lane: (lane.side_index, lane.lane_id),
    )
)
...
for selected in combinations(side_profiles, len(side_lanes)):
    ordered = tuple(sorted(selected, key=lambda profile: profile.lane_y))
    ...
    seatings.append(tuple(zip(side_lanes, ordered, strict=True)))
```

`combinations`, not `permutations`, and the `zip` is order-preserving against `side_index`. **The
variant family varies which ROWS a side uses, never which lane goes on which row.** There is no
mirrored variant, no reversed-lane-order variant, no split-strip variant that would put `hydrogen`
outermost, and no alternative port side — the port is `lane_indices[0]` unconditionally. Yaw does
vary (`_CARDINAL_YAWS`, `strip_variants.py:31`) but yaw rotates the machine, not the lane stack.

So the answer to *"why is the working variant not selected"* is that **no such variant exists to
select**.

---

## 3. Would the topmost lane work? Yes — measured

In both dumps the head tile of the OUTERMOST lane has a second free neighbour:

* `casimir-crystal#1` graphene head `(1,9,0)`: onward list contains `((1, 8, 0), True, 'FREE')`;
* `energy-matrix#12` energetic-graphite head `(1,112,0)`: `((1, 111, 0), True, 'FREE')`.

That is not luck. `_size` (`freeform.py:1582`) charges each strip `height + MARGIN` with `MARGIN = 1`
(`freeform.py:161`), and `_greedy_pack` (`freeform.py:3044-3065`) seats each strip at the top of its
slot, so the row directly north of every strip is a free margin row by construction. Only the
outermost north lane can reach it; every inner lane's north neighbour is the sibling lane above.

The innermost lane (adjacent to the machine band) also has exactly one free neighbour
(`titanium-crystal` head `(1,11,0)`: north is hydrogen's lane, south is the machine band, east is its
own tile 2, west is the channel). It is fine only because `titanium-crystal` is not an external
input, so `wants = 1`.

---

## 4. Why the same strips wire in the CLEAN cells

Four corpus specs place `casimir-crystal` or `energy-matrix`. Probe
(`<copy>/probe.py`, `flab2bp.rates.build_candidates` over `URL_CORPUS`):

```
energy-matrix/{no-proliferator,output-products,all-products}:   hydrogen_external=True  hydrogen_internal=False  n_groups=2
casimir-crystal/{no-proliferator,output-products,all-products}: hydrogen_external=True  hydrogen_internal=False  n_groups=5
quantum-chip/{no-proliferator,output-products,all-products}:    hydrogen_external=True  hydrogen_internal=False  n_groups=15
universe-matrix/{no-proliferator,output-products,all-products}: hydrogen_external=True  hydrogen_internal=True   n_groups=38
```

**`universe-matrix` is the only spec in the corpus where `hydrogen` is BOTH an external input AND
internally produced** (by `plasma-refining#28` and `mass-energy-storage#23`). Everywhere else the
hydrogen lane head is named by no internal `_Net`, so it is absent from `net_ports`, absent from
`shared_feed`, and absent from `ports` in `_reserve_port_access` entirely. The strip shape is
byte-identical; only the *demand* on the port differs.

The difference is therefore **not** fewer input items, a different lane order, or more clearance. It
is that one net arrives instead of two, and one is what the geometry supplies.

---

## 5. Why Phase B's last-mile cluster search and relation no-goods never touched it

Three independent reasons, all read off the code.

### 5.1 A `STATIC_ACCESS` failure short-circuits the whole router

`freeform.py:15042-15049`:

```python
if route and prepared.preparation_failures:
    internal_routing = DetailedRouteResult(
        DetailedRouteStatus.STRANDED, (), prepared.preparation_failures, 0, 0,
    )
else:
    ... _route_external_inputs ... _route_external_outputs ...
```

and `freeform.py:15074`, `15091`, `15142` all gate on `not prepared.preparation_failures`. `_route_all`
never runs. **The last-mile cluster search is inside `_route_all` and therefore never executes on such
a pack**; `internal_routing.last_mile` is `None`, and `_power_plan` is skipped too
(`freeform.py:14583`).

### 5.2 A `STATIC_ACCESS` failure produces NO no-good of any kind

The combined result at `freeform.py:15141-15147` sets

```python
exhaustive = not prepared.preparation_failures and external_routing.exhaustive and ...
```

so `routing.exhaustive is False`. `_proof_scoped_no_goods` (`freeform.py:14791-14883`) opens with

```python
if (
    not routing.exhaustive
    or routing.status is not DetailedRouteStatus.STRANDED
    or not routing.failures
    or any(failure.kind is RouteFailureKind.BUDGET for failure in routing.failures)
):
    return (), None, ()
```

→ **no `ExactPackNoGood`, no `ClusterRelationNoGood`, no `_DirectRelationNoGood`.** The sweep learns
literally nothing from the attempt and reproduces the identical shape at the next height. This is the
precise mechanism behind R1's observation that the failure count is *identical at every height from
48 to 154*.

### 5.3 Even if a no-good were produced, relocation could not satisfy it

`route_feedback.py:290` puts `STATIC_ACCESS` in `_PLACEMENT_FAILURES`, so
`geometric_failure_instances` (`route_feedback.py:601-615`) and `select_lns_neighbourhood`
(`route_feedback.py:679-748`) would nominate the implicated strips for relocation. But
`ClusterRelationNoGood` and `ExactPackNoGood` are exclusions over **origins** — relative and absolute
strip positions. The blocking cells are the sink strip's own belts and its own machine, which
translate rigidly with the strip. **No assignment of origins whatsoever changes `held` or `wants` for
this port.** A relation no-good would exclude arrangements one at a time from an infinite family, all
of which fail identically.

---

## 6. Experiments in the copy

All four candidate fixes were tried. Loads recorded before each timed run.

### E1 — narrow the `twice` predicate to genuinely MIXED lanes (router access model). **FAILS.**

The docstring for `twice` (`freeform.py:10091-10099`) describes a *shared* lane carrying two
different items, one external and one internal. The failing lanes carry ONE item
(`lane=('hydrogen',)`). Gated on `PHASE_E_MIXEDFEED`, `shared_feed` was narrowed with
`and len(strips[strip_index].lane_of_input(item)) > 1`.

```
 14:00:51 up 18 days, 19:46,  8 users,  load average: 8.85, 5.33, 4.64
 28  0      0 1038876968  0 8599032   0    0 49759 15282 23398   4  5  2 93  0  0  0
```

Result — the `STATIC_ACCESS` failures vanish and the router runs, but the SAME ports fail again at
route time with `dynamic-access` and **zero expansions**:

```
[R4-ROUTE] dynamic-access item=hydrogen role=internal src_family=plasma-refining#28 dst_family=energy-matrix#12 src=(88,125,0) dst=(1,113,0)   wall=0 exp=0
[R4-ROUTE] dynamic-access item=hydrogen role=internal ... dst=(128, 1, 0) wall=0 exp=0
[R4-ROUTE] dynamic-access item=hydrogen role=internal ... dst=(97, 8, 0)  wall=0 exp=0
[R4-ROUTE] dynamic-access item=hydrogen role=internal ... dst=(93, 41, 0) wall=0 exp=0
[R4-ROUTE] dynamic-access item=hydrogen role=internal ... dst=(75, 41, 0) wall=0 exp=0
[R4-ROUTE] dynamic-access item=hydrogen role=internal ... dst=(93, 15, 0) wall=0 exp=0
[R4-ROUTE] dynamic-access item=hydrogen role=internal ... dst=(75, 23, 0) wall=0 exp=0
```

`exp=0` is the signature `_Canvas.reserved`'s docstring warns about: the external run took the one
corridor, laid a belt on it, and the internal net was handed an empty goal set. Cell verdicts:

```
  X universe-matrix/no-proliferator REFUSED  (band, R1's bug)
  X universe-matrix/output-products REFUSED  no packing ... left nets unrouted
  X universe-matrix/all-products    REFUSED  best pack left 1 net unrouted (was 3)
```

**Conclusion: the second corridor demand is REAL.** The fix must supply a second access tile, not
remove the demand. This rules out the router-access-model option.

### E2 — E1 plus R1's seed-width fix. Still 0/3.

`PHASE_E_SEEDWIDTH` changes `_band_policy_candidate_heights` (`freeform.py:18798-18814`) to pass
`max(_minimum_pack_width(strips, h), seeds[h].width)`. It removes the false `game.blueprint_area`
headline (R1 option (a)) and nothing else: 0/3 clean.

### E4 — reorder the lanes so external-input items sit outermost (strip generation). **2/3 CLEAN.**

`PHASE_E_LANEORDER=1`, at `strip_variants.py:928`:

```python
input_items = tuple(sorted(group.inputs, key=lambda item: (item not in spec.external_inputs, item)))
```

```
 14:06:17 up 18 days, 19:52,  8 users,  load average: 3.11, 4.67, 4.66
  X [  1/3]  17s freeform stress universe-matrix/no-proliferator  REFUSED  16.3s
  . [  2/3]  29s freeform stress universe-matrix/output-products  CLEAN    27.4s
  . [  3/3]  31s freeform stress universe-matrix/all-products     CLEAN    30.0s
=== freeform: 2/3 clean
```

The remaining refusal is R1's band bug verbatim (`a 264x162 extent fits no band`).

### E5 — E4 plus R1's seed-width fix. **2/3 CLEAN, honest message.**

```
 14:06:57 up 18 days, 19:53,  8 users,  load average: 3.97, 4.71, 4.68
  X [  1/3]  20s freeform stress universe-matrix/no-proliferator  REFUSED  18.6s
  . [  2/3]  27s freeform stress universe-matrix/all-products     CLEAN    25.4s
  . [  3/3]  30s freeform stress universe-matrix/output-products  CLEAN    28.8s
```

`no-proliferator`'s message becomes the honest routing one. Under `PHASE_E_PORTDUMP` there are now
**zero `R4-RPA` lines on any cell** — no port is unreachable anywhere. Its residual failures are
ordinary, pack-specific and scattered (1-5 per pack, different nets each time):

```
[R4-ROUTE] strips=43 pack=212x148 failed=1
[R4-ROUTE]   dynamic-access item=circuit-board  circuit-board#2 -> electromagnetic-matrix#9
[R4-ROUTE] strips=43 pack=256x116 failed=1
[R4-ROUTE] strips=43 pack=242x93  failed=2   (copper-ingot -> magnetic-coil#22, dynamic-access + commit-link)
[R4-ROUTE] strips=43 pack=292x100 failed=3
```

At `--budget 120` it still refuses **at 20 s** — it is out of candidates, not out of clock (R1 §6:
`freeform.py:17729` breaks the arrangement loop once arrangement 0 fails at every height). That is a
separate Phase E work item, not this one.

### E6 (recommended) — the SURGICAL lane order. **Same coverage, one tenth the disturbance.**

`PHASE_E_LANEORDER=2` restricts the reorder to items that actually trigger `twice` — external AND
internally produced:

```python
_internal = {item for other in groups.values() for item in other.outputs}
_needs_two = set(spec.external_inputs) & _internal
input_items = tuple(sorted(group.inputs, key=lambda item: (item not in _needs_two, item)))
```

Effect on the two strips, verbatim (`<copy>/lanes.py`, `freeform.plan_strips` on the
`no-proliferator` candidate):

```
=== BASELINE ORDER ===
casimir-crystal#1 in_above=(('graphene',), ('hydrogen',), ('titanium-crystal',)) box_h=8 width=12
    rows=[('graphene',0), ('hydrogen',1), ('titanium-crystal',2)]  cols=[('graphene',0), ('hydrogen',1), ('titanium-crystal',2)]
    lane_tiles=[(('graphene',),9), (('hydrogen',),10), (('titanium-crystal',),11)]
energy-matrix#12  in_above=(('energetic-graphite',), ('hydrogen',)) box_h=8 width=36
    rows=[('energetic-graphite',0), ('hydrogen',1)]  cols=[('energetic-graphite',1), ('hydrogen',2)]
    lane_tiles=[(('energetic-graphite',),32), (('hydrogen',),33)]

=== LANEORDER=2 ===
casimir-crystal#1 in_above=(('hydrogen',), ('graphene',), ('titanium-crystal',)) box_h=8 width=12
    rows=[('hydrogen',0), ('graphene',1), ('titanium-crystal',2)]  cols=[('hydrogen',0), ('graphene',1), ('titanium-crystal',2)]
    lane_tiles=[(('hydrogen',),9), (('graphene',),10), (('titanium-crystal',),11)]
energy-matrix#12  in_above=(('hydrogen',), ('energetic-graphite',)) box_h=8 width=36
    rows=[('hydrogen',0), ('energetic-graphite',1)]  cols=[('hydrogen',1), ('energetic-graphite',2)]
    lane_tiles=[(('energetic-graphite',),33), (('hydrogen',),32)]
```

**`box_height` and `width` are unchanged on both strips.** Only the row assignment swaps, so the
strip costs nothing extra; the pack differences downstream come from the lanes' differing *lengths*
being attached to different rows.

---

## 7. Corpus-level evidence (72-cell gate, budget 30 s)

Four full gates were run: baseline twice (on the checkout, unmodified) and `LANEORDER` variants on
the copy. Loads before each:

```
 14:09:19 up 18 days, 19:55,  8 users,  load average: 2.81, 4.10, 4.46   (baseline run 1)
 14:11:49 up 18 days, 19:57,  8 users,  load average: 10.56, 7.55, 5.74  (LANEORDER=1 + SEEDWIDTH)
 14:14:34 up 18 days, 20:00,  8 users,  load average: 11.02, 10.07, 7.05 (LANEORDER=1)
 14:19:56 up 18 days, 20:06,  8 users,  load average: 2.87, 7.65, 7.16   (LANEORDER=2 run 1)
 14:22:34 up 18 days, 20:08,  8 users,  load average: 9.41, 9.68, 8.05   (LANEORDER=2 run 2)
 14:24:43 up 18 days, 20:10,  8 users,  load average: 13.81, 11.60, 8.97 (baseline run 2)
```

```bash
# baseline, checkout, unmodified
uv run python scripts/audit.py --budget 30 --max-seconds 1800 --json base_full.jsonl
# arms, copy
PHASE_E_LANEORDER=1                     .venv/bin/python <copy>/scripts/audit.py --budget 30 --max-seconds 1800 --json lo_full.jsonl
PHASE_E_LANEORDER=1 PHASE_E_SEEDWIDTH=1 .venv/bin/python <copy>/scripts/audit.py --budget 30 --max-seconds 1800 --json e_full.jsonl
PHASE_E_LANEORDER=2                     .venv/bin/python <copy>/scripts/audit.py --budget 30 --max-seconds 1800 --json lo2_full.jsonl
```

| arm | freeform | sequence-pair | total | wall |
|---|---|---|---|---|
| baseline run 1 | 33/36 | 33/36 | **66/72** | 123 s |
| baseline run 2 | 33/36 | 33/36 | **66/72** | 123 s |
| `LANEORDER=1` | 35/36 | 35/36 | **70/72** | 131 s |
| `LANEORDER=1 + SEEDWIDTH` | 35/36 | 35/36 | **70/72** | 132 s |
| `LANEORDER=2` run 1 | 35/36 | 35/36 | **70/72** | 129 s |
| `LANEORDER=2` run 2 | 35/36 | 35/36 | **70/72** | 128 s |

Baseline's six misses are exactly the six `universe-matrix` cells. Newly clean in every arm:
`freeform|universe-matrix|1`, `freeform|universe-matrix|2`, `sequence-pair|universe-matrix|1`,
`sequence-pair|universe-matrix|2` (i.e. `output-products` and `all-products` on **both** strategies —
the fix is in `strip_variants.py`, which both share). Still refused in every arm:
`universe-matrix/no-proliferator` on both strategies.

### Area, over the 66 baseline-clean cells

```
### lo_full.jsonl   (LANEORDER=1):            regressions=0 identical=52 changed=14  total 98487 -> 99255 (+0.78%)
    sequence-pair|quantum-chip|2:       3655 -> 4648 (+27.2%)
    sequence-pair|information-matrix|1: 3960 -> 4453 (+12.4%)
    sequence-pair|quantum-chip|0:       3621 -> 4061 (+12.2%)
    freeform|processor|0:                864 ->  884  (+2.3%)
    ... 10 more, all reductions, down to sequence-pair|graphene|1: 518 -> 442 (-14.7%)

### lo2_full.jsonl  (LANEORDER=2, surgical):  regressions=0 identical=64 changed=2   total 98487 -> 98597 (+0.11%)
    freeform|super-magnetic-ring|0: 2220 -> 2310 (+4.1%)
    freeform|processor|0:            864 ->  884 (+2.3%)

### e_full.jsonl    (LANEORDER=1+SEEDWIDTH):  regressions=0 identical=53 changed=13  total 98487 -> 99976 (+1.51%)
```

**Zero regressions in every arm** (no cell that was CLEAN became REFUSED or INVALID).

### Run-to-run noise, measured

Two identical baseline runs and two identical `LANEORDER=2` runs:

```
### baseline run1 vs run2 (pure noise): identical 62, differ 4
    freeform|casimir-crystal|2:          1100->1144  (+4.0%)
    freeform|processor|0:                 864-> 884  (+2.3%)
    sequence-pair|information-matrix|1:  3960->4453 (+12.4%)
    freeform|plastic|1:                   850-> 820  (-3.5%)
### lo2 run1 vs run2 (pure noise): identical 68, differ 2
    freeform|processor|0:                 884-> 864  (-2.3%)
    freeform|super-magnetic-ring|0:      2310->2146  (-7.1%)
```

So the noise floor is already **±12% per cell / 4 cells per pair of runs**. `LANEORDER=2`'s two
changed cells are *inside* the noise band and are not stable across its own two runs — it is
indistinguishable from a no-op on area. `LANEORDER=1`'s `sequence-pair|quantum-chip|2` at **+27.2%**
is above the noise band and reproduces in both `LANEORDER=1` arms; that is a real cost of the broad
rule and the reason to prefer the surgical one. Coverage (70/72) is stable in both `LANEORDER=2` runs.

---

## 8. Design options

### (A) Seat both-fed ingredients on the outermost lane row — **RECOMMENDED**

**Owner: strip generation** (`src/flab2bp/layout/strip_variants.py`, `_logical_strip_plans`, the
`input_items` assignment at line 928).

Replace the bare alphabetical sort with a two-key sort whose primary key is *"does this ingredient
need two access corridors"*:

```python
internally_produced = {item for other in groups.values() for item in other.outputs}
needs_two_approaches = set(spec.external_inputs) & internally_produced
input_items = tuple(sorted(group.inputs, key=lambda item: (item not in needs_two_approaches, item)))
```

* **Exactness.** No geometry rule is relaxed. `_seat_inputs` still enforces the row caps and the
  column bound; `_side_seatings` still enforces reach profiles; the attachment plan, the sorter tier
  and the emitted blueprint are all derived from the new order exactly as they were from the old one.
  `box_height` and `width` are unchanged on both affected strips (§6, E6). The validator is the
  arbiter and every cell in the gate is validator-clean.
* **Deterministic unit test, no wall clock.** Two pure-function tests beside
  `tests/layout/test_strip_variants.py`:
  1. `test_an_ingredient_fed_from_outside_and_inside_takes_the_outermost_lane_row` — build the
     `universe-matrix` `no-proliferator` candidate, call `freeform.plan_strips(spec)`, and assert
     `strip.in_above[0] == ('hydrogen',)` and `strip.row_of_input('hydrogen') == 0` for both
     `casimir-crystal#1` and `energy-matrix#12`, and that `box_height` and `width` are the same as
     the alphabetical seating's.
  2. The **generalised invariant** (see below) as a property test over every corpus spec: for every
     strip and every ingredient `i` in `set(spec.external_inputs) & internally_produced`,
     `strip.row_of_input(i) == 0` (north side) or `== strip.height - 1` (south side). Both are pure
     over `plan_strips`; no clock, no solver.
  3. A router-side pin beside `tests/layout/test_freeform.py:3108`: construct a canvas with a
     three-lane strip whose middle lane head is in `twice`, call `_reserve_port_access`, and assert
     `failed_ports == {middle_head}` — this is the regression that would catch a future reordering
     that puts a both-fed item back in the middle.
* **Risk to the 66 clean cells.** Measured: **zero status regressions, 64 of 66 byte-identical
  areas, +0.11% total, both changed cells inside the measured noise floor** (§7).
* **Does it generalise?** Yes, and it should be stated as an invariant *checked at strip build time*:
  **"every input lane head must have at least as many free 4-neighbours as the number of independent
  feeds that lane accepts."** Today the only lever the strip builder has is row order, and row order
  can guarantee at most **two** such lanes per strip (the outermost north row and the outermost south
  row). A recipe with three both-fed ingredients would still refuse — see §9.

### (B) Give every input lane head its own west channel column (staircase)

**Owner: strip generation + packer clearance** (`freeform.py:5186-5205` lane emission, `_size` at
`freeform.py:1582`).

Start lane `k` at column `-k` instead of column `0`, so lane heads form a west-facing staircase and
each head's north neighbour is the free channel of the lane above, not that lane's belt. This gives
*every* lane two access tiles, so it generalises past two both-fed ingredients per strip.

* **Exactness:** the lane still covers every column its sorters need (`input_lane_tiles`), so the
  attachment plan is untouched; the extra tiles are dead belt like the coater's prepended tile
  already is (`freeform.py:5157-5170`).
* **Cost:** `west_channel` must grow from 1 to `len(in_above)` (and again for `in_below`), which is a
  real width charge on **every strip in the corpus** — `_size` adds it and `_pack` offsets by it
  (`freeform.py:3061`). Unmeasured, but structurally an O(lanes) width tax on 43 strips; the
  `_COATER_WEST_CHANNEL = 3` precedent (`freeform.py:196`) shows the mechanism exists and is
  expensive.
* **Test:** a pure geometry test that for every strip and every input lane, the head tile has ≥ 2 free
  neighbours on a canvas containing only that strip.
* **Verdict:** the right answer if §9's three-both-fed-ingredient case ever appears; too expensive to
  buy now for a case the corpus does not contain.

### (C) Teach the router to share one corridor between an external run and an internal net

**Owner: router access model** (`_reserve_port_access`, `_net_ends`, `_route_external_inputs`).

Let the external run terminate on the corridor's access cell and let the internal net **merge into
its belt** rather than demanding its own corridor. Same-item merging is legal (both nets carry
`hydrogen`) and the router already "settles for merging into a sibling net's path" elsewhere
(`_reserve_port_access` docstring, `freeform.py:10078-10082`).

* **Ruled out by measurement.** E1 (§6) removed the demand and the same ports failed again at route
  time with `dynamic-access, exp=0` — a search that expands nothing, exactly the pathology the
  reservation exists to prevent. Making merging actually work means changing goal-set construction,
  the belt link graph (`output_obj`), and the fan-out check; it touches the most load-bearing part of
  the router for a case option (A) fixes in one sort key.
* Retained as a note: **the `twice` predicate is broader than its own docstring**, which speaks of a
  *shared* lane carrying two different items. Narrowing it is NOT safe (E1 proves it), so the
  docstring should be corrected to describe what the code does — *"a lane fed from both the boundary
  and inside the block"* — rather than the code being narrowed to match the docstring.

### (D) A packer clearance rule reserving an access corridor beside every port

**Owner: packer.** Ruled out on the evidence: the blocking cells belong to the sink strip itself
(§1.5). No packing constraint can move a strip's own belts off its own port.

### Recommendation

**(A), the surgical form (`LANEORDER=2`), on its own.** It is one sort key in one function, it is
exact, it costs nothing measurable in area, it fixes four cells across both strategies, and it lifts
the gate from 66/72 to 70/72 reproducibly.

Pair it with R1's option (c) — do not retain a pre-pack seed rejection as a *"wired then rejected"*
refusal — so that `universe-matrix/no-proliferator`'s remaining refusal names the router. R1's option
(a) (the seed-width witness) is **not** needed for coverage here and costs +0.73% more area in this
measurement (§7, `e_full` vs `lo_full`); it should be judged on its own merits, not bundled.

---

## 9. Open unknowns

1. **`universe-matrix/no-proliferator` still refuses.** After the fix its residual failures are
   ordinary, pack-specific `dynamic-access` / `sealed-pocket` / `commit-link` (1-5 per pack, a
   different net each time). It refuses at 20 s of a 120 s budget, so it is out of *candidates*, not
   clock — R1 §6's arrangement short-circuit (`freeform.py:17729`). That is a distinct Phase E item.
2. **The rule places the item at index 0 of `input_items`, not at "the outermost row of whichever
   side it lands on".** `_seat_inputs` may put lane 0 in `in_above` (correct — outermost north) or,
   if the north side is full, in `in_below`, where index 0 is the row nearest the machine band —
   i.e. the WORST row. No corpus spec exercises that path today. The invariant in §8(A) test 2 would
   catch it; the fix must ultimately be expressed on the seated rows, not on the input order.
3. **"The row north of a strip is free" is an unwritten coupling** between strip generation and the
   packer: it holds because `_size` charges `height + MARGIN` (`MARGIN = 1`) and `_greedy_pack` seats
   at the top of each slot. Empirically it also holds for sequence-pair packs (all four newly-clean
   cells include two sequence-pair cells), but nothing states or checks it. A packer change that
   removed the margin row would silently reintroduce this refusal.
4. **Two both-fed ingredients per strip is the ceiling** of the row-order lever (one outermost row
   per side). Three would refuse again, and would need option (B).
5. **Sequence-pair area is noisy** (±12% per cell between two identical baseline runs). The `+27.2%`
   on `sequence-pair|quantum-chip|2` under the BROAD rule reproduces across arms and looks real, but
   a proper A/B would need several repeats; the surgical rule makes the question moot.
6. **Only the freeform path was instrumented.** The sequence-pair strategy shares
   `strip_variants.plan`/`_logical_strip_plans` and its two universe-matrix cells go clean, so the
   mechanism is the same — but its own port-reservation path was not dumped.

---

## Appendix — every command run

```bash
# throwaway copy
mkdir -p <scratch>/phase-e-R4
git -C /home/dannyb/sources/factorio-lab-to-blueprint archive HEAD | tar -x -C <scratch>/phase-e-R4
cp src/flab2bp/layout/_*.cpython-314-x86_64-linux-gnu.so <scratch>/phase-e-R4/src/flab2bp/layout/

# instrumented reproduction (copy only)
PHASE_E_PORTDUMP=1 .venv/bin/python <copy>/scripts/audit.py --budget 30 --jobs 1 \
    --only universe-matrix --strategy freeform --json dump.jsonl

# experiments (copy only)
PHASE_E_MIXEDFEED=1                        .venv/bin/python <copy>/scripts/audit.py --budget 30 --jobs 3 --only universe-matrix --strategy freeform --json e1.jsonl
PHASE_E_MIXEDFEED=1 PHASE_E_SEEDWIDTH=1    .venv/bin/python <copy>/scripts/audit.py --budget 30 --jobs 3 --only universe-matrix --strategy freeform --json e2.jsonl
PHASE_E_ROUTEDUMP=1 PHASE_E_MIXEDFEED=1 PHASE_E_SEEDWIDTH=1 \
                                           .venv/bin/python <copy>/scripts/audit.py --budget 30 --jobs 1 --only universe-matrix --strategy freeform --json e3.jsonl
PHASE_E_LANEORDER=1                        .venv/bin/python <copy>/scripts/audit.py --budget 30 --jobs 3 --only universe-matrix --strategy freeform --json e4.jsonl
PHASE_E_LANEORDER=1 PHASE_E_SEEDWIDTH=1    .venv/bin/python <copy>/scripts/audit.py --budget 30 --jobs 3 --only universe-matrix --strategy freeform --json e5.jsonl
PHASE_E_LANEORDER=1 PHASE_E_SEEDWIDTH=1    .venv/bin/python <copy>/scripts/audit.py --budget 120 --jobs 2 --only universe-matrix --strategy freeform --json np120.jsonl

# 72-cell gates
uv run python scripts/audit.py --budget 30 --max-seconds 1800 --json base_full.jsonl   # checkout, twice
PHASE_E_LANEORDER=1                     .venv/bin/python <copy>/scripts/audit.py --budget 30 --max-seconds 1800 --json lo_full.jsonl
PHASE_E_LANEORDER=1 PHASE_E_SEEDWIDTH=1 .venv/bin/python <copy>/scripts/audit.py --budget 30 --max-seconds 1800 --json e_full.jsonl
PHASE_E_LANEORDER=2                     .venv/bin/python <copy>/scripts/audit.py --budget 30 --max-seconds 1800 --json lo2_full.jsonl  # twice

# corpus probes
.venv/bin/python <copy>/probe.py    # which specs place casimir-crystal / energy-matrix, and hydrogen's provenance
.venv/bin/python <copy>/lanes.py    # lane rows/columns/tiles for the two strips, both orders
```

Baseline audit output on master, verbatim (run 1):

```
=== freeform: 33/36 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
=== sequence-pair: 33/36 clean -- NOT CLEAN   (refused 3, invalid 0, crashed 0, not run 0)
123s wall, 72/72 cells
  X [  1/72]     4s freeform      stress universe-matrix/no-proliferator power=1 budget=30s REFUSED  3.1s
  X [  2/72]     6s freeform      stress universe-matrix/output-products power=1 budget=30s REFUSED  2.2s
  X [  3/72]     8s freeform      stress universe-matrix/all-products    power=1 budget=30s REFUSED  6.5s
  X [ 14/72]    34s sequence-pair stress universe-matrix/no-proliferator power=1 budget=30s REFUSED 27.4s
  X [ 15/72]    34s sequence-pair stress universe-matrix/all-products    power=1 budget=30s REFUSED 26.4s
  X [ 16/72]    36s sequence-pair stress universe-matrix/output-products power=1 budget=30s REFUSED 27.4s
```

`LANEORDER=2` gate output, verbatim (run 1):

```
=== freeform: 35/36 clean -- NOT CLEAN   (refused 1, invalid 0, crashed 0, not run 0)
=== sequence-pair: 35/36 clean -- NOT CLEAN   (refused 1, invalid 0, crashed 0, not run 0)
129s wall, 72/72 cells
  X [  5/72]    18s freeform      stress universe-matrix/no-proliferator power=1 budget=30s REFUSED 16.3s
  X [ 14/72]    40s sequence-pair stress universe-matrix/no-proliferator power=1 budget=30s REFUSED 26.4s
```

Final load record:

```
 14:28:44 up 18 days, 20:14,  9 users,  load average: 4.28, 9.37, 8.84
 0  0      0 1039289920  0 8619924   0    0 49708 15293 23395   4  5  2 93  0  0  0
 6  0      0 1039289096  0 8619928   0    0     0     0 13943 26906 1 1 98  0  0  0
 1  0      0 1039289996  0 8619928   0    0     0     0 12983 24704 1 0 98  0  0  0
```
