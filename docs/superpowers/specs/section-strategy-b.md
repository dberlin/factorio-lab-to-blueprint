# Strategy B — free-form packing + belt routing (`layout/freeform.py`)

Design spec. Consumes a `BuildSpec`, produces a `Placement`
(`src/flab2bp/layout/base.py`). Competes head-to-head with Strategy A.

The thesis: impose **no global skeleton**. Pack machine rectangles anywhere,
then route belts through whatever is left, using altitude to cross. The density
ceiling is higher than any structured scheme; the risk is the classic
place-then-route divergence. Everything below is aimed at making it converge.

---

## 0. Measured DSP facts this design rests on

Derived from the 11 real game blueprints in `tests/fixtures/` (7,502 belt
records), not from assumption:

| Fact | Value | Evidence |
|---|---|---|
| Altitude quantum | belts sit at `z` levels spaced **1.0** apart | level histogram: 6792 @ 0.0, 529 @ 1.0, 181 @ 0.5 |
| Ramp rate | **0.5 per belt tile** → **2 tiles per level** | per-tile chain delta: ±0.5 occurs 125×, ±1.0 only 7× |
| Stacking | up to **3** belts share one `(x, y)` | 426 positions with 2, 21 with 3 |
| Terrain noise | `z` carries jitter up to ~0.03 | values 0.003/0.009/0.02/0.022 etc. |
| Max level observed | 1 | corpus max after denoising |

**Denoising rule:** `level = round(z * 2) / 2`, then treat `0.5` as ramp-transit,
integers as settled levels. The encoder must add the level as `z`, not the
raw float.

`LEVELS = 2` (ground + one raised) by default; `--levels` may raise it to 3.
One level of separation is sufficient for a crossing, and the corpus shows the
game itself rarely goes higher.

---

## 1. Interface from `BuildSpec`

`BuildSpec` is owned by another agent and not yet frozen. Strategy B needs
exactly this much of it; if the final shape differs, adapt in one place
(`freeform._read_spec`).

```python
spec.machines      # list[MachineDemand]: recipe_id, machine_item_id, count:int,
                   #   proliferator_mode, footprint (w,h), per-machine in/out rates
spec.flows         # list[Flow]: item_id, source (recipe_id | EXTERNAL),
                   #   sink (recipe_id | EXTERNAL), rate: Fraction (items/s)
spec.belt_item_id  # chosen belt tier
spec.belt_capacity # Fraction items/s for that tier
spec.externals     # inputs (ores, proliferator) and the output product
```

**Heterogeneous footprints are the norm, not the exception.** Arc smelter 3×3
(9 tiles), assembler 4×4 (16), chemical plant and particle collider larger
still. Nothing in this design may assume uniform rectangles: `no_overlap_2d`
handles heterogeneity natively, the height sweep clamps to `max_i h_i`, and
block-mode grouping (§2.1) groups *per recipe*, so a block is internally uniform
while blocks differ from each other. The one place uniformity would sneak in is
the lexicographic symmetry-breaking of §2.1 — it is applied **only** within a
set of identical `(recipe, footprint)` machines, never across recipes.

**Per-machine proliferator mode.** `BuildSpec` carries the products-vs-speed
mode per recipe, chosen upstream; machines of the *same* recipe may split
between modes. Strategy B never chooses a mode. It matters here only because
sprayed-item rates differ by mode, so all rates are read off `BuildSpec`
per machine, never recomputed from the recipe.

**Netlist construction.** For every `Flow`:

```
effective_capacity = belt_capacity * stack_factor      # stack_factor == 1 in v1
lanes = ceil(rate / effective_capacity)                # exact Fraction
```

Emit `lanes` separate nets, partitioning source and sink machines between them
as evenly as possible. A net is then *guaranteed* to fit one belt by
construction, and the router never reasons about capacity again.

> **Extension point — belt stacking.** The DSP dataset carries a `beltStack`
> flag: piling multiplies lane throughput by up to 4×, at the cost of requiring
> Pile Sorters at the pile/unpile points. v1 fixes `stack_factor = 1`, but it is
> written as a **per-lane integer in `1..4`** rather than folded into a
> `one lane = tier items/sec` invariant. Adding it later means (a) making
> `stack_factor` a per-net decision variable, (b) forcing the sorter tier to
> Pile Sorter on any lane with `stack_factor > 1`, and (c) nothing else — the
> router is already capacity-blind by construction. Do not write
> `belt_capacity` anywhere except through `effective_capacity`.

---

## 2. Phase 1 — placement

### 2.1 Granularity and symmetry

Machines of the same recipe are interchangeable, so packing 17 identical 3×3
smelters as 17 free rectangles wastes the entire search on symmetric
permutations.

- **`total_machines ≤ 40`** → place every machine as its own rectangle
  (true free-form; this is where B earns its density).
- **otherwise** → group each recipe's machines into a rectangular
  **block** whose `(rows, cols)` factorisation is itself a decision
  (enumerate all factorisations of `count` plus ragged ones with
  `rows*cols ≥ count`), and pack blocks. Symmetry collapses; scalability
  holds to several hundred machines.

Symmetry breaking within the small case: for identical footprints of the same
recipe, impose a lexicographic order `(x_i, y_i) ≤ (x_j, y_j)` for `i < j`.
This alone typically cuts solve time by an order of magnitude.

### 2.2 Variables

For each placeable unit `i` (machine or block), with footprint `w_i × h_i`:

```
x_i ∈ [0, W_max]           IntVar
y_i ∈ [0, H_max]           IntVar
rot_i ∈ {0, 1}             BoolVar   (omitted when w_i == h_i)
w'_i, h'_i                 IntVar, tied to rot_i by reified equality
X_i = NewIntervalVar(x_i, w'_i, x_i + w'_i)
Y_i = NewIntervalVar(y_i, h'_i, y_i + h'_i)
```

### 2.3 The routability proxy — I/O pads as first-class rectangles

**This is the central design decision.** Of the four candidates (global free
fraction, regional congestion estimate, free I/O border, coarse global route)
the choice is **free I/O border, encoded as mandatory pad rectangles**, backed
by a weak global whitespace floor.

Reasoning: a machine whose four faces are all flush against neighbours is not
"hard to route" — it is *impossible* to route, and no amount of global
whitespace fixes it. That failure is local, so the remedy should be local and
hard. Regional congestion estimates and coarse global routing both spend a lot
of model on a soft, approximate signal that RRR's negotiated congestion already
handles better in phase 2. Pads make the *necessary* condition structural and
leave the *sufficient* condition to the router, which is the right split.

Encoding: each unit `i` gets a pad rectangle `P_i` placed against one chosen
face:

```
face_i ∈ {N, E, S, W}      IntVar, exactly one true via reified bools
depth   = 1 if the face is fully consumed by direct insertion, else 2
```

Depth 2 = one sorter tile + one belt tile, the minimum to reach a belt with a
Mk.I sorter. `P_i` joins the **same** `no_overlap_2d` set as the machines, so
the solver physically reserves the strip. A unit needing both an input and an
output belt face gets two pads on opposite faces.

Density cost: measured as pad area / total area. For a 3×3 machine with two
2-deep pads that is `2·(3·2) = 12` reserved tiles against 9 of machine — which
sounds ruinous until you note pads of *adjacent* machines are the belt corridor
itself, i.e. they are not waste, they are the routing channel that any layout
needs. The genuine overhead is only the pads that end up unused, which the
direct-insertion term below actively removes.

**A pad is a local guarantee, not a global one.** It guarantees each machine has
*some* free face; it says nothing about whether one commodity can reach *all*
machines. That distinction is exactly what the proliferator net exposes, and it
is handled in §4 — which also decides whether every machine needs a third,
reserved, proliferator-facing pad, and what that would cost.

Global whitespace floor (the weak second half):

```
W · H  ≥  Σ machine_area + Σ pad_area + α · route_estimate
```

`route_estimate = Σ_nets HPWL_lower_bound`, computed from a cheap pre-pass
(sum over nets of the Manhattan span of a quick greedy seed placement).
`α` defaults to `0.35` and is exposed as a tunable. Its only job is to stop the
solver producing a globally choked pack that is locally legal; RRR handles the
rest.

### 2.4 Objective

`W · H` is a product of two variables — CP-SAT can express it with
`AddMultiplicationEquality`, but the relaxation is weak and the search flounders.
Instead:

> **Outer loop over candidate heights `H`, inner CP-SAT minimises `W`.**

```
for H in candidate_heights:          # see below
    minimise  W  +  λ · HPWL  −  μ · Σ direct_insert_bonus
    subject to  all y_i + h'_i ≤ H
    record area = W* · H
keep the best area
```

Candidate heights: start from `H0 = ceil(sqrt(total_area_estimate))` and sweep
`{0.6·H0, 0.8·H0, H0, 1.25·H0, 1.6·H0}` rounded to integers, clamped to
`≥ max_i h_i`. Five solves, each far easier than one nonlinear solve, and the
sweep is embarrassingly parallel across the time budget.

`HPWL` (half-perimeter wirelength) per net `n` over its terminals:
`(max_x − min_x) + (max_y − min_y)`, standard reified min/max. This pulls
connected machines together — it is what makes phase 2's job tractable, and it
is a routability measure that costs almost nothing.

Weights: `λ = 1`, `μ = 4` by default (a direct insert removes an entire net, so
it is worth several tiles of wirelength). Both exposed for the bake-off to tune.

### 2.5 Direct insertion

Conditions for producer `p` → consumer `c` to direct-insert:

1. **Rate** — `p`'s output rate of the item is within the sorter tier's
   throughput, and `c` consumes the whole of it (or a splitter-free integral
   share). Checked in exact `Fraction`s *before* the model is built; only
   feasible pairs get a variable.
2. **Geometry** — the gap between `p`'s and `c`'s footprints along the shared
   axis is `g ∈ {1, 2, 3}` tiles (sorter span), and their extents overlap on the
   perpendicular axis by ≥ 1 tile so a sorter has somewhere to sit.
3. **Face budget** — the consumed faces are then exempt from pad requirements.

Encoding: `d_pc` BoolVar with reified channelling
`d_pc ⇒ (aligned ∧ gap ∈ [1,3])`, expressed as two reified linear constraints
per axis. Objective gains `− μ · d_pc`.

When `d_pc` is true, the pair is **pinned**: a sorter building is emitted
directly and **no net is created**, so phase 2 never sees it. This is where
Strategy B's density actually comes from — every direct insert deletes a net
*and* its corridor.

**Face contention.** A machine has four faces, and recipe-input sorters plus the
output sorter compete for them. A 4-input recipe already exceeds four faces and
must merge inputs onto a shared lane, which suppresses `d_pc` for those edges
because direct insertion needs a *free aligned face on both sides* of the pair.
Coaters consume no machine faces (§4), so proliferation does not add to this
pressure — but it constrains direct insertion far more severely by another route:

> ### 2.5.1 Proliferation forbids direct insertion, per edge
>
> Spray is applied to items **in transit on a belt**, and **spray does not
> survive crafting**. So to run recipe `R` proliferated, every one of `R`'s own
> input items must be sprayed on a belt before reaching `R`'s machines. A
> direct-inserted edge has no belt, therefore nothing can spray it, therefore
> **an edge feeding a proliferated recipe cannot be direct-inserted.**
>
> The rule is determined by the **consumer's** mode, not the producer's:
>
> ```
> edge (P → R) carrying item I is direct-insertable
>     ⟺  R.proliferator_mode == NONE
> ```
>
> **Model impact:** such edges are excluded from the direct-insert variable set
> **entirely** — no `d_pc` variable is created for them. This is strictly better
> than creating the variable and constraining it to 0: the model shrinks, and
> the `−μ·d_pc` objective term cannot mislead the search toward placements whose
> apparent reward is unrealisable.
>
> **The consequence is severe and worth stating plainly.** Under
> `--proliferator mk3` with every recipe proliferated, *every* edge feeds a
> proliferated recipe, so the direct-insert variable set is **empty** and `μ`
> contributes nothing at all. Strategy B's principal source of density
> advantage — restructuring the floorplan to eliminate nets — is switched off
> exactly in the configuration the user chose as the default. §11.1 reassesses
> the bake-off in light of this.

---

## 3. Phase 2 — routing

### 3.1 Choice: sequential A* with negotiated-congestion rip-up-and-reroute

Rejected: monolithic multi-commodity flow / CP-SAT over the free cells. A
60×60×2 grid is 7,200 nodes; with tens of nets, an exact model has hundreds of
thousands of Boolean edge variables and will not close. Exactness here buys
little because phase 1 already fixed the placement — the router's job is
throughput, not optimality.

Chosen: **PathFinder-style negotiated congestion** (Ebeling et al.), the
approach every real FPGA/VLSI router uses. It is simple, always terminates on a
cap, and degrades gracefully.

```
for iter in range(RRR_MAX):            # default 12
    rip up all nets
    for net in nets ordered by criticality:
        path = astar(net, cost=base + h[cell]·p_fac(iter))
        commit path
    if no cell is over-used: SUCCESS
    for each over-used cell: h[cell] += h_inc
    p_fac grows: 0.5 · 1.6**iter
FAILURE → section 4
```

Nets are ordered longest-first on the first iteration, then by
previous-iteration cost descending (hardest first).

### 3.2 Grid and moves

Nodes are `(x, y, level)` for `level ∈ [0, LEVELS)`. A cell is blocked if a
machine footprint or a pad-turned-building occupies it at that level. Machines
block **all** levels (they are tall); belts block only their own level.

Moves from a cell:

- **Straight / turn** on the same level: cost 1, target cell free.
- **Ramp**: change level by ±1. Consumes **2 consecutive cells in a straight
  line** (measured: 0.5 per tile), both free at *both* the origin and
  destination level for clearance. Cost 3 (2 tiles + a turn penalty, to
  discourage gratuitous climbing).
- Turn penalty +0.3 to favour straight runs, which look better and use fewer
  belt entities.

### 3.3 Multi-terminal nets (Steiner trees) and splitters

A net with one source and `k > 1` sinks is routed incrementally:

1. Route source → nearest sink. Mark every cell of that path as *net-attached*.
2. For each remaining sink, run **multi-source A\*** seeded from every
   net-attached cell. The path joins the existing tree at its cheapest point.
3. At each join, insert a **Splitter** building. Splitter footprint is
   **2×2** *(flagged — see §7)*. If the join point cannot accommodate a 2×2
   splitter, push the join outward along the trunk until it fits; if no point
   fits, mark the net failed for this RRR iteration.

Conversely, a net with `k > 1` sources merges: belts merge natively in DSP by
pointing two belt chains at the same downstream tile, so merges need **no**
splitter — just two `output_obj` links converging. Cheaper than splitting, and
the router should prefer source-merging over sink-splitting where it has a
choice.

### 3.4 Sorters at the endpoints

Every net terminates at a machine face, not a machine tile. The terminal cell is
the pad tile adjacent to the face; a sorter is emitted spanning from the belt
tile to the machine edge. Sorter tier is chosen as the cheapest tier whose
throughput covers the net's rate at the required span *(tier throughput table
owned by the catalog agent — §7)*.

### 3.5 Emitting belts

A routed path becomes one `PlacedBuilding` per tile, `item_id` = the belt tier,
forward-linked: tile `t`'s `output_obj` is tile `t+1`'s index; the last tile
points at the consuming building (or `None` for the product output). `yaw` may
be left 0 for belts — the corpus confirms the game zeroes belt yaw on
serialisation and derives direction topologically. `z` = level (+ 0.5 on ramp
tiles).

---

## 4. The proliferator commodity — the hardest net

Under the default `--proliferator mk3`, proliferator arrives on an external belt
and is needed wherever a proliferated recipe runs. Total rate is trivial
(~0.83 items/s for the example URL, against a 12/s belt), so **throughput is a
non-issue**. It is purely a *reachability* problem: one commodity, a sink set
spanning the whole build. That profile — low rate, universal reach — is the
worst possible case for place-and-route and the best possible case for a
structured skeleton, which is why this is where Strategy B is most at risk.

### 4.1 The mechanic, corrected

**Evidence from the game protos** (`raw_itemprotoset.json`):

| Item | ID | `Ability` |
|---|---|---|
| Proliferator Mk.I / II / III | 1141 / 1142 / 1143 | 1 / 2 / 4 |
| Spray Coater (喷涂机) | 2313 | — (model 120) |
| Assembling Machine Mk.II | 2304 | **0** |
| Arc Smelter | 2302 | **0** |

Production machines carry no spray ability and no proliferator input slot.
Proliferator is loaded into a **Spray Coater**, which mounts on a belt and
sprays the items passing along it. Two rules follow, and the second is the one
that shapes this design:

1. **Sinks are coaters, not machines.** The proliferator net terminates at
   coaters, which sit on belts the router is laying anyway.
2. **Spray does not survive crafting.** Proliferating recipe `R` requires
   spraying each of `R`'s *own inputs* in transit. A recipe cannot inherit
   proliferation from its ingredients' history.

FactorioLab models proliferator as a recipe *ingredient*, which is correct for
**rate accounting** — `BuildSpec` should keep doing that — but it is an
abstraction, not topology.

Rule 2 is what forbids direct insertion on proliferated edges (§2.5.1). Rule 1
is the good news: the sink set is small and lives in corridors.

**Sink count for the example URL** (~24 machines, 9 recipes, ~12 distinct
items): **~12 coaters**, one per *sprayed lane*. Not one per consumer —
spraying a shared lane once covers every downstream machine drawing from it.
External input lanes (ore, and the proliferator lane itself per `mps`) are
sprayed at the blueprint edge. Machine faces consumed: **zero**.

### 4.1a Which lanes need a coater, and how many

A lane carrying item `I` needs spraying iff some consumer drawing from it runs a
proliferated recipe.

```
coaters_on_lane = ceil(lane_rate / COATER_THROUGHPUT)
```

Because lanes are already capacity-split so `lane_rate ≤ effective_capacity`
(§1), this is **exactly one coater per sprayed lane** whenever
`COATER_THROUGHPUT ≥ effective_capacity`, which is the expected case.
`COATER_THROUGHPUT` is parameterised, not guessed.

**Mixed-consumer lanes.** If one lane feeds both a proliferated and a
non-proliferated consumer, spraying it would hand the non-proliferated consumer
a bonus the rate solve did not account for — silent over-production and a
desync from `BuildSpec`'s numbers. Resolution: **split the lane** into a sprayed
lane and an unsprayed lane, partitioning the consumers. This is a netlist-level
transform in §1, applied before the router runs, and it costs one extra net.

**Belt tiles.** Whether a coater consumes the belt tile it sprays or straddles
it from an adjacent cell is parameterised
(`COATER_OCCUPIES_BELT_TILE: bool`, plus its footprint and attachment offset) —
the geometry is being extracted from game assets. The router reserves cells
accordingly; if the coater straddles, it needs one free adjacent cell, which the
slab columns of §4.3 already provide.

**Feeding the coater.** Each coater needs its own proliferator input, delivered
by a sorter from the proliferator lane. Coaters are therefore placed **where
their lane passes nearest a utility column** (§4.3), minimising the spur to a
single sorter. This is a placement rule, not a search: for each sprayed lane,
walk the routed path and pick the cell minimising distance to a column.

### 4.2 Net shape — three options

**(a) Steiner tree over all sinks.** Minimal total length, but produces an
arbitrary organic shape. A ~12-terminal net is re-ripped and rerouted on
*every* RRR iteration and will dominate the congestion history, starving the
recipe nets it shares cells with. Rejected: it converts a reachability problem
into a congestion problem.

**(b) Dedicated utility lane, reserved in phase 1.** The placement is *required*
to leave a distribution channel; the net is then trivially routable. Costs a
fixed corridor whether or not it is fully used.

**(c) Per-row spurs off a trunk.** Structured like (b) but only branches where
needed. Strictly better than (b) on density, strictly worse on predictability.

**Chosen: (b) with (c)'s spurs for stragglers.** A low-rate, universal-reach
commodity is exactly what a utility distribution network is for — it is why real
factories and Strategy A both use a lane. Reserving the channel converts the
hardest routing problem in the design into a constraint that phase 1 satisfies
structurally, which is the same move that made §2.3's pads the right call, one
level up.

### 4.3 Encoding: utility slabs

Rather than a free-form reserved path (which needs its own routing model inside
phase 1), partition the build into vertical **slabs**:

```
SLAB_WIDTH = 12                 # tunable
```

- Machines are assigned to slabs; a machine may not straddle a slab boundary.
- Between adjacent slabs, a **1-tile free column** is reserved as a rectangle in
  the same `no_overlap_2d` set.
- The proliferator trunk runs along these columns; short spurs (option c) tap
  from a column to each coater.

Every coater is then within `SLAB_WIDTH / 2 = 6` tiles of a utility column, so
reachability is **guaranteed by construction** and phase 2 never fails on the
proliferator net. The columns are not dead space: they double as general routing
channels for recipe nets, so their cost is shared.

### 4.4 The honest density cost

| Component | Cost |
|---|---|
| Slab columns | 1 column per 12 tiles of width ≈ **8%** of bounding box, partly shared with recipe routing |
| Coaters | ~12 buildings, on lanes already routed; **0** machine faces |
| Coater feed sorters | ~12 sorters, in the slab columns |
| Lane splits for mixed consumers | ~1 extra net per affected item |

Total: roughly **8–12% of bounding-box area**, mostly recovered because the
columns carry recipe nets too. This is a modest, well-behaved cost.

**The expensive consequence of proliferation is not area — it is §2.5.1.**
Forbidding direct insertion on every proliferated edge removes B's main
optimisation lever entirely. That cost does not appear in this table because it
is not reserved space; it is foregone density, and it is much larger than 8%.

### 4.5 Degrading to zero

The design must vanish cleanly when proliferator is off:

- `--proliferator none`, or a `BuildSpec` in which no machine has a proliferated
  mode ⇒ **zero** proliferator nets, **zero** coaters, `SLAB_WIDTH = ∞` (no
  reserved columns), and the direct-insert variable set is **unrestricted**.
  Strategy B is then exactly the design of §2–§3, at full strength.
- Mixed builds are the normal case, since mode is per recipe. A slab column is
  reserved **only if some lane in an adjacent slab needs a coater**; otherwise
  the boundary is dropped and the slabs merge. Overhead is proportional to
  actual proliferator use, not to the flag being on.
- `products` vs `speed` changes only the sprayed-item *rate*, read from
  `BuildSpec`. It never changes topology — both need the same coater on the same
  lane, and both equally forbid direct insertion on that edge (§2.5.1).

---

## 5. Power distribution — Tesla towers as a phase-1 constraint

Power is a **hard constraint inside phase 1**, not a post-pass: towers occupy
cells that machines want, so placing them afterwards would either fail or
require ripping up the placement. No generation is emitted — the user wires the
build into an existing planetary grid.

All numeric constants are parameterised; the catalog agent owns the real values.

```python
POWER_TOWER_ITEM_ID   # Tesla Tower item id
TOWER_W, TOWER_H      # footprint (expected 1x1)
SUPPLY_RADIUS  = R    # tiles; machines within R are powered
LINK_RADIUS    = L    # tiles; towers within L connect to each other
```

### 5.1 What "covered" must mean

Take the **conservative** reading: *every tile of a machine's footprint* lies
within `R` of some tower, not merely its centre. A 4×4 assembler whose centre is
covered can still have a corner 2.1 tiles outside a radius the centre clears by
2.0 — the game powers a building by its own position rule, and guessing the
lenient version risks an unpowered machine in a blueprint the user has already
pasted. The cost of being wrong is silent factory failure; the cost of being
conservative is a few extra towers. Easy call.

**Sorters need power too** (belts in DSP do not). Sorters live in the pad cells
scattered across every corridor, so in practice coverage must extend to
essentially every non-empty cell, not just machine footprints.

### 5.2 The encoding problem, and the way around it

The obvious formulation is poisonous. Coverage of machine `i` by tower site `s`
depends on `dist(pos_i, pos_s)`, and `pos_i` is a *variable* — so the coverage
predicate is a function of two decision variables, and the naive encoding needs
an implication per (machine, position, site) triple. That does not scale.

Two observations collapse it:

1. Because §5.1 already forces coverage of nearly every non-empty cell, and
   because the objective is *minimising the bounding box*, requiring
   **every cell of the bounding box to be covered** is barely more conservative
   than requiring machine coverage — and it is entirely
   **placement-independent**. Coverage becomes a property of the tower set and
   the bounding box alone. The machine variables drop out of the constraint.
2. Once tower sites are drawn from a **fixed lattice**, the tower-to-tower
   adjacency graph is static and known at model-build time.

### 5.3 Chosen encoding: a covering, self-connected lattice

Choose lattice spacing

```
d = min( R * sqrt(2), L )        # so a full lattice both covers and connects
```

The full lattice is then covering *and* connected **by construction**, which
means:

- **Coverage** (§5.1) is satisfied structurally — no constraint needed.
- **Connectivity** is satisfied structurally — no flow model needed.
- Towers become **fixed 1×1 blockage rectangles** in the `no_overlap_2d` set at
  known positions, and machines simply pack around them.

Tower count is then `≈ ceil(W/d) · ceil(H/d)`, i.e. proportional to bounding-box
area — which the objective *already* minimises. So item 4 (tower count in the
objective) needs no extra term under this encoding; minimising area minimises
towers, exactly.

**What this gives up.** A free-form tower placement could cover an irregular
build with fewer towers than a lattice. That optimum is not worth the model: it
requires the flow formulation below and makes the packing far harder, for a few
percent of a resource that is ~1 tile each.

### 5.4 Optional exact variant (small builds only)

For `total_machines ≤ 40`, offer free tower selection. Candidate sites on a
finer lattice, `t_s ∈ {0,1}`:

- **Coverage:** `Σ_{s : dist(s,c) ≤ R} t_s ≥ 1` for every cell `c` in the
  bounding box. Placement-independent, as above.
- **Connectivity:** single-commodity flow over the *static* candidate-adjacency
  graph (edge iff `dist(u,v) ≤ L`). Choose a root; the root emits `Σ_s t_s − 1`
  units; every other selected tower consumes exactly 1; edge capacity
  `f_uv ≤ N · y_uv` with `y_uv ≤ t_u`, `y_uv ≤ t_v`. This is the standard
  spanning-connectivity trick and is exact.
- **Objective:** add `+ ν · Σ_s t_s`, since towers now cost area the objective
  cannot otherwise see.

Edge count is the risk: sites every 2 tiles on a 30×30 build gives ~225 sites,
and a generous `L` yields thousands of edges. Prune to the 8 nearest neighbours
per site, which preserves connectivity on a lattice while keeping the graph at
~900 edges.

**Honesty about the cost:** this is materially harder for free-form placement
than for a structured skeleton. Strategy A knows where its corridors are, so it
can drop towers into them at fixed intervals and get coverage and connectivity
for free. B has no corridors until phase 2, which is precisely why B is pushed
back onto the lattice — see §11.1.

### 5.5 `--no-power`

Drops cleanly and completely: no tower rectangles, no lattice, `d = ∞`, no
objective term. The bake-off should run both ways, because power changes the
achievable density materially and A and B do not pay for it equally.

---

## 6. The repair loop

Phase 2 failure feeds back to phase 1:

```
for outer in range(OUTER_MAX):         # default 4
    placement = phase1(H_candidates, blockages, α)
    result    = phase2(placement)
    if result.ok: return result
    # feedback
    hot = cells with h[cell] in the top decile of history cost
    blockages += bounding boxes of hot regions, as pseudo-rectangles
                 joining the no_overlap set (forces machines apart there)
    α *= 1.3                            # more global whitespace
    H_candidates = [h + 2 for h in H_candidates]
return fallback()
```

**Termination** is guaranteed: `OUTER_MAX` is a hard cap, and each iteration
strictly enlarges the permitted bounding box, so the sequence is monotone and
cannot cycle. On exhaustion we call the fallback, which cannot fail.

Every outer iteration is logged into `Placement.stats` (`outer_iters`,
`rrr_iters`, `nets_failed`, `fell_back`) so the bake-off can report *how* B got
its answer, not just the area.

---

## 7. Throughput correctness and the `Fraction` → integer boundary

The safety rule: **every capacity decision is made in exact `Fraction`
arithmetic before CP-SAT is constructed. The solver never rounds a
safety-critical quantity.**

- `lanes = ceil(rate / effective_capacity)` — exact `Fraction`, `math.ceil` on a
  `Fraction` is exact. Splitting into `lanes` nets means each net's rate is
  `rate / lanes ≤ effective_capacity` by construction. When belt stacking is
  added, `effective_capacity = belt_capacity · stack_factor` with
  `stack_factor ∈ 1..4` an integer, so the property is preserved exactly and no
  float ever enters.
- Sorter tier selection compares `Fraction` rate against a `Fraction`
  throughput table. Exact.
- Direct-insert feasibility (§2.5 condition 1) — exact `Fraction`.
- Machine counts arrive already integral from `BuildSpec` (rounded **up**
  upstream, which over-produces; documented there).

Only *objective* terms are scaled to integers: `HPWL`, `W`, and the
direct-insert bonus are all pure tile counts and already integral. `λ` and `μ`
are integers. Therefore **no scaling of rates into the solver occurs at all** —
the `Fraction`→int hazard is designed out rather than managed. This is worth
stating as an invariant test.

---

## 8. Fallback — guaranteed-feasible construction

Must never fail, because the bake-off needs a comparable number from B even when
the solver times out or the repair loop exhausts.

**Row layout.** One recipe per row, machines laid left-to-right. Between rows, a
corridor of 3 tiles: belt lane, sorter lane, belt lane. A vertical trunk of
`n_items` lanes runs down the left edge at level 0, with crossings at level 1.
Every machine's input face abuts the corridor above it and its output face the
corridor below. Routable by construction — no search, no failure mode.

The proliferator lane is trivial here: it is one more lane in the vertical
trunk, with coaters placed on each item lane as it leaves the trunk (or, under
`MACHINES`, a spur along each row corridor). This is precisely the "utility lane
by construction" that Strategy A gets for free, and its ease in the fallback is
a fair warning about §10.

This is deliberately a degenerate Strategy A. That is fine and even useful: if B
falls back often, the bake-off will show B ≈ A, which is itself the honest
answer.

Invoked when: `OUTER_MAX` exhausted, or the time budget expires at any point, or
phase 1 returns INFEASIBLE.

---

## 9. Open questions and unresolved constants

Everything Strategy B could not determine itself, in one place. All numeric
entries are behind a single catalog lookup, so correcting them is a constant
change, not a redesign.

### 9.1 Resolved since the first draft

| # | Question | Answer |
|---|---|---|
| B1 | Proliferator sink model | **Coaters on lanes.** Machines have `Ability = 0` and no input slot. Confirmed independently by the Strategy A designer. |
| B1a | Does spray survive crafting? | **No.** Each recipe's own inputs must be sprayed in transit — this is what forbids direct insertion on proliferated edges (§2.5.1). |

### 9.2 Numeric constants owned by the catalog agent

Nothing below is hardcoded; all are catalog lookups.

| Constant | Status | Used at |
|---|---|---|
| Splitter footprint | assumed 2×2 (from a 2.7 selection volume), **Low** confidence | §3.3 |
| Sorter span | 1–3 tiles, Medium | §2.5, §3.4 |
| Sorter throughput vs span | unknown table, **Low** | §3.4 |
| Belt capacity 6/12/30 per s | from `belt.speed`, Medium | §1 |
| Sorter reach across a belt at another level | assumed **yes**, **Low** | §3.4 |
| Machines block all altitude levels | assumed yes (they are tall), Medium | §3.2 |
| `COATER_THROUGHPUT` | **unknown**, being extracted | §4.1a |
| Coater footprint + belt attachment geometry, `COATER_OCCUPIES_BELT_TILE` | **unknown**, being extracted | §4.1a |
| `POWER_TOWER_ITEM_ID`, `TOWER_W/H`, `SUPPLY_RADIUS`, `LINK_RADIUS` | **unknown**, being extracted | §5 |

### 9.3 Established — no longer open

| Mechanic | Value | Basis |
|---|---|---|
| Ramp = 2 tiles per level, 0.5/tile | measured | 125 vs 7 occurrences in corpus |
| Level spacing 1.0, stacking ≤ 3 | measured | 426 double, 21 triple positions |
| Proliferator item ids / ability | 1141/1142/1143 → 1/2/4 | `raw_itemprotoset.json` |
| Spray Coater item id | 2313, model 120 | `raw_itemprotoset.json` |
| Machines cannot take proliferator | `Ability = 0` on 2302/2304 | `raw_itemprotoset.json` |
| Spray does not survive crafting | game mechanic | confirmed by Strategy A designer |

### 9.4 Deliberately out of scope for v1

- **Belt stacking / piling** (`beltStack` flag). Kept as a per-lane integer
  `stack_factor ∈ 1..4` tied to Pile Sorters — see the extension point in §1.
  Nothing in the router assumes `stack_factor == 1`.

---

## 10. Test plan

**Unit**
- `lanes` computation: exact `Fraction` boundaries, e.g. rate exactly equal to
  capacity → 1 lane, capacity + ε → 2 lanes.
- Ramp move consumes exactly 2 cells and lands on the right level.
- Pad rectangles genuinely appear in the no-overlap set (place two machines,
  assert a free strip exists between them).
- Direct-insert reification: construct a placement where a pair is 2 tiles apart
  and aligned, assert `d_pc` is forced true; misalign, assert forced false.

**Integration**
- The example URL's spec (58 machines) lays out, validates, and encodes.
- Every net's belt count ≥ Manhattan distance between its terminals (sanity).
- Total emitted machine count equals `BuildSpec` machine count exactly.

**Adversarial — designed to break place-and-route**
- *Crossbar*: two machine groups at opposite ends that must exchange four
  distinct items, forcing four full-width nets. Tests negotiated congestion.
- *Choke*: a spec whose machine area is ~95% of any plausible bounding box,
  so routing must use level 1 throughout. Tests ramps and stacking.
- *Single-face*: a recipe with five distinct inputs on a machine with four
  faces — must force lane merging onto one face, or fail cleanly to the
  fallback. This one is expected to exercise the fallback; assert it does so
  rather than crashing.
- *Long-thin*: `H` forced to the minimum, so the build is one machine tall and
  very wide. Tests the height sweep's clamping.
- *Proliferator-everywhere*: `--proliferator mk3` on a spec with ~24 machines
  spread wide enough that a naive Steiner tree would cross every corridor.
  Asserts the slab columns are reserved, that every sink is within
  `SLAB_WIDTH/2` of one, and that the proliferator net routes on the **first**
  RRR iteration (it should never contend, by construction).

**Proliferator-specific**
- `--proliferator none` ⇒ exactly zero coaters, zero proliferator nets, zero
  reserved slab columns; and the resulting area is **strictly smaller** than the
  same spec with mk3. A regression here would mean the overhead is not actually
  conditional.
- Mixed modes: a spec where one recipe is `products`, one `speed`, one `none`.
  Assert topology is identical for the first two and absent for the third, and
  that only sprayed-item *rates* differ.
- Slab merging: a spec where no machine in two adjacent slabs needs
  proliferator ⇒ that boundary column is dropped and the slabs merge.
- **Direct-insert exclusion (§2.5.1):** for a spec where recipe `R` is
  proliferated, assert **no** `d_pc` variable exists for any edge whose consumer
  is `R`; and for the all-proliferated spec, assert the direct-insert variable
  set is empty. Then assert the same spec with `--proliferator none` has a
  non-empty set. This is the single most important new test — it pins the
  constraint that governs B's density.
- Mixed-consumer lane splitting: a lane feeding one proliferated and one
  non-proliferated consumer produces **two** lanes, and the unsprayed one has no
  coater.
- One coater per sprayed lane when `COATER_THROUGHPUT ≥ effective_capacity`;
  `ceil` behaviour when it is not.

**Power**
- Full-bounding-box coverage: every cell within `SUPPLY_RADIUS` of some tower.
- Tower network is connected under `LINK_RADIUS` (verify on the emitted
  placement, independent of the encoding that produced it).
- `--no-power` emits zero towers and yields strictly smaller area.
- Towers never overlap machines, pads, slab columns, or belts.

**Properties (the ones that matter)**
- `validate(strategy_b.lay_out(spec))` passes for every spec in the corpus —
  **including when `time_budget_s = 0.05`**, which must trigger the fallback.
  This is the single most important test: B always returns something valid.
- Determinism: same spec + same budget ⇒ identical `Placement` (seed CP-SAT,
  fix net ordering).
- No two buildings share a `(x, y, level)` cell.
- Every machine has ≥ 1 connected input path per input item and ≥ 1 output path.

---

## 11. Honest assessment vs Strategy A

**Where B wins.** Heterogeneous recipe graphs with lumpy machine counts — a
spec with 3, 4, 8, 4, 4, 12, 4, 17, 2 machines (the example URL) has no natural
row width, so A's skeleton wastes the ragged remainder of every row while B
tetrises the odd machines into gaps. B also wins wherever direct insertion is
plentiful: the `−μ·d_pc` term restructures the whole floorplan around
eliminating nets, whereas A can only direct-insert within its fixed row
structure. Expect B to win by 15–30% on mid-size, direct-insert-rich specs.

**Where B loses.** Large specs (≳150 machines), where B is forced into block
mode and its freedom evaporates, while A's skeleton was never the bottleneck —
here they should tie, with A far faster. Bus-heavy specs where many items must
reach many machines: A's dedicated lanes are near-optimal and B's RRR will
thrash, likely falling back. And anything hitting the time budget, where B
degrades to a *worse* version of A (the fallback has no optimisation at all).

**The real risk** is not density but variance: A's output quality is a smooth
function of the input, B's is bimodal — excellent when it converges, fallback
when it does not. The bake-off should therefore report **fallback rate**
alongside area, because a B that wins by 25% on 60% of specs and ties on the
rest is a very different proposition from one that wins by 25% always. I would
report median area ratio, worst-case ratio, and fallback rate as three separate
columns.

**Prediction.** B beats A on the example URL and on most single-product specs
under ~80 machines; A wins on wide multi-product specs and on everything large.
If that is what the bake-off shows, the right end state is not to pick one but
to run both and keep the smaller — they are cheap relative to a human's time,
and the `LayoutStrategy` protocol already makes that a three-line dispatcher.

### 11.1 Revised for proliferation, power, and pads together

**Yes. The prediction changes materially, and not in B's favour.** My original
15–30% claim was made before any of the three global constraints existed. Taking
them in order of damage:

**1. Proliferation forbids direct insertion (§2.5.1) — this is the big one.**
Not because of its area cost (a well-behaved 8–12%), but because it deletes B's
optimisation lever. B's density advantage was never really "free-form packing";
it was `−μ·d_pc` restructuring the floorplan to *eliminate whole nets*. On a
fully-proliferated spec the direct-insert variable set is **empty**, `μ` is
inert, and B degenerates to plain area-minimising packing with an HPWL term —
which is a modest improvement over a good skeleton, not a large one.

**2. Power forces a lattice (§5.3).** The tractable encoding is a fixed tower
lattice that machines pack around. That is a regular structure imposed on the
build.

**3. Proliferator forces slab columns (§4.3).** Another regular structure, at a
different pitch.

Put together: B now packs into a field pre-divided by a tower lattice every
`d` tiles and a utility column every 12, with mandatory I/O pads on every
machine. **That is a skeleton.** B has arrived at a coarser, less
carefully-chosen version of what Strategy A was designed around from the start,
having paid full price in solver complexity to get there. The candid summary is
that each constraint demanding *global reach* converts B into A with extra
steps, and we now have three of them.

**Revised numbers.** On a fully-proliferated spec I would expect B to land
between **5% better and 5% worse** than A — inside the noise, decided by
tuning rather than by approach. On a non-proliferated spec, where direct
insertion is unrestricted, I still expect B to win by **15–25%**. B's advantage
is now almost entirely a function of *how much proliferation the winning spec
uses*.

### 11.2 The multi-candidate `BuildSpec` search changes the conclusion

The rate solver emitting several candidate specs — no-proliferator, all-speed,
per-recipe-optimum, and proliferate-only-what-must-be-belted-anyway — and taking
the smallest layout is the right design, and it interacts with everything above.

**It does not change my design.** Each candidate is an independent `BuildSpec`;
`lay_out` is already pure and stateless, so running it N times is free of new
machinery. Two consequences worth acting on:

- **Time budget is now per-candidate.** With 4 candidates, B gets a quarter of
  the wall clock per run, which raises the fallback rate — and B's fallback is
  strictly worse than A's normal output. Either budget per-candidate explicitly,
  or run candidates in parallel. I would run them in parallel; they are
  perfectly independent.
- **The `proliferate-only-what-must-be-belted-anyway` candidate is the
  interesting one**, and it is precisely the co-optimisation of §2.5.1: it
  proliferates only edges that were never direct-insertable, so it buys
  proliferation's machine-count reduction *without* surrendering B's direct
  inserts. That candidate is where B should look best. It deserves to exist
  regardless of which strategy wins.

**Which candidate will win on area?** Proliferation cuts machine counts by
20–25% (products) or up to 50% (speed at Mk.III); direct insertion saves perhaps
15–25% of area. Machine-count reduction is the larger effect and it compounds
upstream, so I expect a **heavily-proliferated candidate to win most URLs** —
which means B will usually be judged on exactly the specs where its advantage is
switched off. That is the single most important thing this analysis surfaced:
**B may well win a benchmark that the final pipeline never actually uses.**

### 11.3 Recommendation

Build A first. It is now the strategy the constraints favour, and B's fallback
(§8) is essentially a degenerate A anyway, so A is on the critical path either
way.

Then build B and run the bake-off, but report it as a **matrix, not a single
number**: {proliferated, not} × {power, no-power}, with median area ratio,
worst-case ratio, and fallback rate in each cell. If B only wins the
non-proliferated / no-power cell, that is a clear and honest answer that B is
not worth carrying — and it is much better to learn that from four cheap numbers
than from a single average that hides it.

I would also keep the `run both, keep the smaller` dispatcher regardless of the
outcome: it costs three lines, it is strictly never worse, and with per-candidate
parallelism the wall clock is already dominated by the slowest single run.
