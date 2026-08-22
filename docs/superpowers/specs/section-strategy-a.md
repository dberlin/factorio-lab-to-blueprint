# Strategy A — Structured Spine + CP-SAT Arrangement

Design spec for `src/flab2bp/layout/spine.py`. Implements `LayoutStrategy` from
`src/flab2bp/layout/base.py`.

**Core claim.** The skeleton is *routable by construction*: every lane an item could
need has a reserved, collision-free channel before the solver runs. CP-SAT therefore
only ever chooses *how much* structure to spend, never *whether a route exists*. No
place-then-route repair loop, no infeasible-placement dead ends.

> **Revision 2.** Adds **power as a hard in-model constraint** (§5) — Tesla towers
> placed jointly with machines, coverage and connectivity as constraints, never a
> post-pass. Also carries revision 1's four items: belt stacking as an extension point
> (§2.4), proliferator as a distributed utility network (§4), per-group proliferator
> mode from `BuildSpec` (§0), non-uniform footprints (§1.4, §2.2). §4.1 records a
> **mechanic correction** for adjudication; §4.5 makes the explicit Strategy A vs B
> argument.

---

## 0. Required `BuildSpec` interface

`spec.py` does not exist yet (owned by the rates agent). Strategy A needs exactly the
following; anything else is ignorable. **If the delivered `BuildSpec` differs, only
the adapter at the top of `spine.py` changes.**

```python
Rate = Fraction          # items per second, exact

class ProliferatorMode(Enum):
    NONE = 0
    PRODUCTS = 1         # extra products
    SPEED    = 2         # production speedup

@dataclass(frozen=True)
class MachineGroup:
    key: str                     # unique; a recipe split across modes yields >1 group
    recipe_id: int               # DSP recipe id, 0 if none
    machine_item_id: int         # DSP item id of the machine building
    machine_model_index: int
    count: int                   # integer machine count, already rounded up
    footprint: tuple[int, int]   # (w, h) build-grid tiles -- NOT assumed uniform
    inputs:  dict[str, Rate]     # item id -> rate consumed PER MACHINE
    outputs: dict[str, Rate]     # item id -> rate produced PER MACHINE

    # Proliferator. Chosen upstream by the MILP; Strategy A never re-decides it.
    prolif_mode: ProliferatorMode
    prolif_item: str | None      # e.g. "proliferator-mk3", None if mode is NONE
    prolif_rate: Rate            # proliferator items/sec consumed PER MACHINE,
                                 # already correct for this group's mode
    sprayed_inputs: frozenset[str]   # which input items must arrive proliferated

@dataclass(frozen=True)
class BuildSpec:
    groups: tuple[MachineGroup, ...]
    external_inputs: dict[str, Rate]   # item id -> total rate entering the block
    external_outputs: dict[str, Rate]  # item id -> total rate leaving the block
    belt_item_id: int                  # chosen belt tier, DSP item id
    belt_capacity: Rate                # items/sec for that tier, stack factor 1
    item_ids: dict[str, int]           # lab item id -> DSP item id
```

Note `prolif_rate` and `sprayed_inputs` are **read, never derived** — the two modes
consume different amounts and the MILP may split one recipe across both, which is why
`key` is not the recipe id.

Power needs nothing from `BuildSpec`; tower geometry comes from the catalog (§10).

Two invariants Strategy A asserts at entry:

1. **Flow balance.** For every item, `Σ produced = Σ consumed + external_outputs −
   external_inputs`, with production ≥ consumption. Surplus is legal and routes to the
   output edge; a *deficit* is an upstream bug and raises.
2. **Acyclicity.** The producer→consumer graph is a DAG. A cycle raises rather than
   silently mis-ordering rows.

---

## 1. Skeleton geometry

### 1.1 Macro structure

Three regions: a **trunk** of vertical riser channels on the west edge, a stack of
alternating **rows** and **corridors**, and an optional **power spine** on the east.

```
   x=0..T-1              x=T ..                              x=W-tw..
 ┌───────────┬────────────────────────────────────────────┬─────────┐
 │  T R U N K│  CORRIDOR C0        (external inputs)       │         │
 │           ├────────────────────────────────────────────┤  POWER  │
 │  vertical │  ROW 0    [M][M][T][M][M]                   │  SPINE  │
 │  channels ├────────────────────────────────────────────┤         │
 │  running  │  CORRIDOR C1                                │ [T]     │
 │  the full ├────────────────────────────────────────────┤         │
 │  height   │  ROW 1    [ M ][T][ M ]                     │         │
 │           ├────────────────────────────────────────────┤ [T]     │
 │           │  CORRIDOR C2        (product out)           │         │
 └───────────┴────────────────────────────────────────────┴─────────┘
 │◄─── T ───►│◄──────────── max_r ww[r] ─────────────────►│◄─ tw ──►│
 │◄────────────────────────── W ───────────────────────────────────►│
```

`[T]` = Tesla tower. Towers inside rows are blocks in the row's 1D packing (§5.2);
spine towers form a vertical chain (§5.4).

- Rows are **topologically ordered**: raw-consuming recipes at the top, final product
  at the bottom. Row `r` generally feeds row `r+1`.
- **Corridor `Cc`** sits between row `c-1` and row `c`; `R` rows give `R+1` corridors.
  `C0` is the external-input corridor, `CR` the output corridor.
- A corridor is `Ltiles[c]` tiles tall, one tile per **lane** — a straight belt run
  along +X at fixed `y` carrying one item.
- Rows begin at `x = T`, so machine blocks are contiguous — no obstacles inside rows.

### 1.2 Why the trunk exists

Corridors connect only *adjacent* rows. An item produced in row 0 and consumed in row 4
needs vertical transport: a **riser**, a vertical belt in a trunk channel spanning from
its source corridor to its sink corridor.

Risers live west of every row, so they never collide with machines. Two risers share a
channel iff their y-spans are disjoint — interval-graph colouring, `T` the chromatic
number (= max simultaneously-active risers at any `y`).

### 1.3 The junction, and why altitude is required

A riser in channel `j` must turn east and merge into corridor `Cc` at `y = y_c`. To
reach `x = T` it crosses channels `j+1 … T-1`, occupied by other risers.

**Resolution: the eastward junction runs at `z = 1`.** The riser ramps up inside its own
column, runs east over the intervening channels at altitude, and descends into the
corridor at `x ≥ T`.

```
  side view, looking north, at y = y_c

  z=1        ╭───────────────────────►  (junction, crosses channels freely)
             │                       ╲
  z=0   … ───┴─ riser j ─ … [r]  [r]  ╰──► corridor lane C_c …
             ▲              ▲    ▲
          channel j     channels j+1, j+2 (other risers, z=0, unaffected)
```

Provably collision-free: every junction sits at a distinct `y`, so junctions never meet
each other, and they cross risers only in the `z=0` / `z=1` sense.

`RAMP_TILES` (default **2**) is the horizontal run per altitude level.
**⚠ GUESS.** Fallback: raise it, or `allow_altitude=False`, forcing `T ≤ 1`.

### 1.4 Row internals — footprints are never uniform

Footprints vary sharply: arc smelter **3×3 = 9 tiles**, assembler **4×4 = 16**, large
plants bigger still. Nothing here may assume uniformity.

Row `r` has height `hh[r] = max` footprint height over its machines *and towers*, and
width `ww[r] = Σ_p k[p][r]·w_p + nt[r]·tw`. Machines of one group are contiguous as a
**block**; blocks and towers lie left to right in a solver-chosen order.

```
   CORRIDOR C_r     lane(iron-ingot)  ══════════════════════════
                    lane(magnet)      ══════════════════════════
                                       ▲s   ▲s      ▲s          sorters
   ROW r            ┌───┐┌───┐┌───┐┌────┐┌────┐┌────┐
                    │ M ││ M ││ M ││ M  ││ M  ││ M  │   ← 3x3 and 4x4 mixed:
                    │3x3││3x3││3x3││4x4 ││4x4 ││4x4 │     row height = 4, the
                    └───┘└───┘└───┘└────┘└────┘└────┘     3x3 block wastes 1/col
                                       ▼s   ▼s      ▼s
   CORRIDOR C_r+1   lane(gear)        ══════════════════════════
```

Mixing heights wastes `(hh[r] − h_p)·w_p·k[p][r]` tiles, which the bounding-box
objective **cannot see** — hence the explicit tie-break in §2.6.

A machine at `x ∈ [a, a+w)` presents `w` edge tiles to the corridor above and `w` below;
each can host one sorter. Wide machines are therefore better at high-throughput
connections, tall ones worse — another reason not to assume uniformity.

### 1.5 Sorter reach and corridor width

A sorter spans `d ≤ reach(tier)`; Mk.I/II/III reach 1/2/3. The **Pile Sorter** is the
fourth tier and the prerequisite for belt stacking (§2.4). **⚠ Confirm with catalog.**

For a row-edge machine to tap a lane at corridor depth `k`, the span is `k`. With Mk.III:

> **Every lane in a corridor of width ≤ 3 is tappable from both sides.**

Wider corridors have lanes reachable from neither side; those must be *pass-through
only*. Lanes are ordered within the corridor — tapped-from-above at the top,
tapped-from-below at the bottom, pass-through in the middle.

### 1.6 Optional lane stacking

`stack_corridor_lanes` (default **False**) halves corridor height by placing a second
lane at `z=1`: `Ltiles[c] = ceil(L[c]/2)`.
**⚠ GUESS — whether a ground sorter can tap a `z=1` belt is unverified.** When enabled,
only pass-through lanes may occupy `z=1`, which is always safe since they are never
tapped. That restricted form is the first thing to enable once confirmed.

---

## 2. The CP-SAT model

One model, solved once per candidate width (§2.6). Groups `p ∈ P`, rows `r ∈ [0,R)`,
corridors `c ∈ [0,R]`, items `i ∈ I`, flow edges `e ∈ E`.
`R_max = min(2·|P|, 64)`.

### 2.1 Variables

| Var | Type | Domain | Meaning |
|---|---|---|---|
| `k[p][r]` | int | `[0, n_p]` | machines of group `p` in row `r` |
| `used[p][r]` | bool | | `k[p][r] > 0` |
| `hh[r]`, `ww[r]` | int | | row height / width |
| `rowactive[r]` | bool | | any machine in row `r` |
| `sx[p][r]` | int | `[T, W_max]` | block start x |
| `lanes[c][i]` | int | `[0, Lmax]` | parallel belt lanes for item `i` in corridor `c` |
| `stackf[c][i]` | int | `[1, 1]` *(v1)* | lane stack multiplier — §2.4 |
| `tap_up[c][i]`, `tap_dn[c][i]` | bool | | lane tapped by row `c-1` / row `c` |
| `Ltiles[c]` | int | `[0, Lmax]` | corridor height in tiles |
| `di[e]` | bool | | edge `e` is direct-inserted |
| `riser[i]` | bool | | item `i` uses a trunk channel |
| `ch[i]` | int | `[0, T_max)` | trunk channel index |
| **`nt[r]`** | int | `[0, NT_max]` | **towers in row `r`** — §5.2 |
| **`tx[r][m]`** | int | `[T, W_max]` | **x of the `m`-th tower in row `r`** |
| **`hr[r]`** | int | `[0, SUPPLY_R]` | **horizontal supply reach in row `r`** — §5.3 |
| **`use_spine`** | bool | | **east power spine present** — §5.4 |
| **`ns`**, **`sy[m]`** | int | | **spine tower count and y positions** |
| `T`, `W`, `H`, `area` | int | | totals |

**Count.** `k`/`used`: `2·|P|·R`. `lanes`/`tap`/`stackf`: `5·|I|·(R+1)`. `di`: `|E|`.
Risers: `2·|I|`. **Towers: `R·(1 + NT_max) + 2·NS_max`.** Typical flow (`|P|=12`,
`|I|=15`, `R≤24`, `NT_max=6`): ≈ 3k + ~200 tower vars ≈ **3.2k**. At `|P|=40`,
`|I|=50`, `R≤80`: ≈ **31k**. Power adds well under 10 % — it is nearly free in variable
count because the lattice formulation (§5) replaces general connectivity.

### 2.2 Structural constraints

```
∀p:            Σ_r k[p][r] == n_p
∀p,r:          used[p][r] ⇔ k[p][r] ≥ 1
∀r:            rowactive[r] ⇔ Σ_p used[p][r] ≥ 1
∀r,p:          hh[r] ≥ h_p · used[p][r]              (per-row max, heterogeneous)
∀r:            hh[r] ≥ th · (nt[r] ≥ 1)              (towers are in the row too)
∀r:            ww[r] == Σ_p k[p][r]·w_p + nt[r]·tw
∀r:            ww[r] ≤ W_cap − T − tw·use_spine
∀r:            blocks and towers in row r pairwise non-overlapping on x  (AddNoOverlap)
rows compact:  rowactive[r] ≥ rowactive[r+1]         (symmetry break)
H  == Σ_r hh[r] + Σ_c Ltiles[c]
W  == T + max_r ww[r] + tw·use_spine
```

`rowactive[r] ≥ rowactive[r+1]` forbids the `R!` permutations differing only by empty
rows — worth a large constant factor.

### 2.3 Flow and lanes

For edge `e = (p → q, item i, rate f_e)`, `crosses[e][c]` is true iff `p`'s row `< c ≤
q`'s row. Encode via `rowidx[p] = Σ_r r·used[p][r]`; split groups weight by `k[p][r]/n_p`.

```
flow[c][i] == Σ_{e carrying i} f_e^up · crosses[e][c] · (1 − di[e])
Ltiles[c]  == Σ_i lanes[c][i]                     (or ceil(·/2) if stacking on)
```

`f_e · crosses[e][c]` is a constant times a bool — plain linear, good propagation.

### 2.4 Lane capacity, and the belt-stacking extension point

DSP's `beltStack` flag lets a lane's throughput be multiplied **up to 4×** by piling,
which requires **Pile Sorters** to load it. **Out of scope for v1**, but the capacity
constraint is written so it drops in without changing the model's shape:

```
lanes[c][i] · stackf[c][i] · down(belt_capacity)  ≥  flow[c][i]
```

`stackf` is pinned to `1` in v1 and CP-SAT folds it away, so the constraint is linear
and free. To enable later: widen the domain to `[1,4]`; add `stackf ≥ 2 ⇒ every sorter
loading this lane is a Pile Sorter`; introduce `cap == lanes·stackf` via
`AddMultiplicationEquality` (both domains ≤ 8, which CP-SAT handles well); give Pile
Sorters their own `sorter_tp` curve. A domain change plus one reification, not a
rewrite — and the §8 throughput tests already parameterise over it.

### 2.5 Throughput correctness — the integer boundary

```
SCALE   = 1_000_000
up(f)   = ceil(f * SCALE)      # every DEMAND / FLOW quantity
down(f) = floor(f * SCALE)     # every CAPACITY quantity
```

**Safety lemma.** If the integer model satisfies `n · down(cap) ≥ up(f)` then exactly
`n · cap ≥ f`.

*Proof.* `n·cap·SCALE ≥ n·floor(cap·SCALE) = n·down(cap) ≥ up(f) = ceil(f·SCALE) ≥
f·SCALE`. Divide by `SCALE > 0`. ∎

Every rounding is conservative, so model-feasible ⇒ throughput-feasible in exact
arithmetic. The converse may fail — we may reject a *just barely* feasible layout — the
correct direction to err. `SCALE = 10⁶` bounds pessimism at 1 part in 10⁶; with rates
below 10⁴/s and `stackf ≤ 4` products stay under 2⁶³. Assert at model-build time.

Applied at three places:

```
lanes[c][i] · stackf[c][i] · down(belt_capacity)  ≥ flow_up[c][i]
nsorters[e] · down(sorter_tp(tier, span))         ≥ up(f_e)
Σ over a machine's edge tiles                      ≥ nsorters[e]
```

### 2.6 Objective

`area = W·H` is a variable product. Rather than `AddMultiplicationEquality` (weak
bounds), **sweep candidate widths**:

```
for W_cap in candidate_widths():          # descending, ~6-10 values
    model.Add(W <= W_cap)
    minimize H
    record (W_actual * H, placement)
return best by area
```

`candidate_widths()` starts at the fallback's width and steps down geometrically,
stopping when a solve proves infeasible. Each gets `time_budget_s / len(candidates)`;
anytime, so a truncated sweep still returns the best found.

Tie-breaks, lexicographically after area:

1. minimise `Σ_r Σ_p (hh[r] − h_p)·w_p·k[p][r]` — the §1.4 height waste;
2. **minimise `Σ_r nt[r] + ns` — total tower count (§5.5);**
3. minimise `Σ_c Ltiles[c]` — fewer belts is denser and cheaper to build;
4. maximise `Σ_e di[e]`.

**Warm start:** feed the §7 fallback via `AddHint` on every solve, making the sweep
monotone by construction.

---

## 3. Direct insertion

`di[e]` for `e = (p → q, item i)` means no lane carries `i` for this edge.

### 3.1 Geometric condition

```
di[e] ⇒ ∃r:  used[p][r] ∧ used[q][r+1]           (vertically adjacent rows)
di[e] ⇒ Ltiles[c] ≤ reach(tier) − 1              (c = r+1; Mk.III ⇒ Ltiles ≤ 2)
di[e] ⇒ block_contained(p@r, q@r+1)
```

`block_contained` — the narrower block's x-interval is contained in the wider one:

```
   ROW r      [ P ][ P ][ P ][ P ]          block P: x ∈ [10,26), w=4, k=4
                   ▼    ▼    ▼
   ROW r+1        [ Q ][ Q ][ Q ]           block Q: x ∈ [14,26), w=4, k=3   ✓
```

Every machine of the narrower block then has one of the wider directly opposite, so a
sorter of span `Ltiles[c]+1` always connects them. Deliberately *sufficient, not
necessary*: rejects some legal partial overlaps rather than ever emit an unreachable
sorter. Reified as `sx[q] ≥ sx[p] ∧ sx[q]+w_q·k_q ≤ sx[p]+w_p·k_p`, or mirrored.

### 3.2 Rate condition

```
di[e] ⇒ nsorters[e] · down(sorter_tp(tier, Ltiles[c]+1)) ≥ up(f_e)
        ∧ nsorters[e] ≤ min(w_p·k[p][r], w_q·k[q][r+1])
```

Sorter throughput *falls* with span, so a wider corridor both costs height and weakens
direct insertion — the model trades these off itself.

### 3.3 Proliferation forbids direct insertion — see §4.3

```
di[e] == 0    for every e = (p → q, i) with i ∈ q.sprayed_inputs
```

The single largest density constraint in a proliferated build.

### 3.4 Fan-out and fan-in

- **P feeds several consumers.** `Σ_{e out of p, di[e]} nsorters[e] ≤ w_p·k[p][r]` on
  the downward edge, separately upward. A group direct-inserts to at most one row below
  and one above.
- **Q needs several inputs.** Same on `q`'s upward tiles. A 4-wide assembler with 3
  ingredients has 4 upward tiles, so all three need ≤1 sorter each *and* all three
  producers block-contained in one row — usually forbidden. Expect 1–2 per consumer.

### 3.5 The rigidity trade-off

`di[e]` forces containment, coupling `sx[p]`/`sx[q]` and removing packing freedom —
often *increasing* `max_r ww[r]`. The model sees this through `ww → W → area`, so no
hand-tuned penalty is needed.

---

## 4. Proliferator as a distributed utility network

### 4.1 Mechanic correction — flagged for adjudication

The brief stated proliferator is "consumed by machines… an extra input connection per
machine." **In DSP that is not how it works, and building to that description yields a
blueprint that does not function.**

- Proliferator is consumed by **Spray Coaters** (item 2313), belt-mounted buildings that
  spray items *travelling on a belt*. A production machine does not accept proliferator
  as a recipe ingredient.
- Spray does **not** survive crafting. Outputs emerge unproliferated regardless of
  inputs. So **every recipe you want boosted needs its own inputs sprayed.**

FactorioLab's model — proliferator added to `recipe.in` — is a correct *rate*
abstraction. It is not a *placement* model.

**⚠ ADJUDICATE.** The distribution network below serves **either** consumer model,
because the geometric problem is identical: get proliferator within sorter reach of
every consumption point, be it a spray coater or a machine. Only the leaf attachment
differs, isolated in one function. If the spray-coater mechanic is confirmed, §4.3
applies and costs real density; if the per-machine model is somehow right, drop §4.3
and the rest stands unchanged.

### 4.2 Geometry: a utility item, not a per-recipe lane

Proliferator's consumption points are spread across **every row running a proliferated
recipe**, rather than concentrated at one consumer. It is therefore a **utility item**:

> A utility item takes a trunk riser spanning the whole build **and** a tapped lane in
> every corridor within its span.

Ordinary items choose *either* `carry_all` *or* `riser`; utility items take both:

```
riser[u]          == 1
lanes[c][u]       ≥ 1     ∀c ∈ prolif_span
tap_dn[c][u]      == 1    ∀c adjacent to a proliferated row
```

Cost: **+1 tile of height per corridor, +1 trunk channel.**

Rate sanity: the example URL needs ≈ **0.83 proliferator/sec** for the whole build —
under 14 % of a Mk.I belt (6/s). So `lanes[c][u] == 1` essentially always. Read the
per-machine rate from `MachineGroup.prolif_rate`; **do not derive it.**

### 4.3 Spray coater placement, and why it kills direct insertion

A spray coater sits on the lane it sprays and needs proliferator delivered to it. Place
it in the corridor, adjacent to the proliferator lane:

```
   CORRIDOR C_c
     depth 1   lane(magnet)  ═══════[SPRAY]═══════════════►   ← sprayed input
     depth 2   lane(prolif)  ═══════════▲═════════════════►   ← utility lane
                                        └ sorter, span 1
   ROW c        [ assembler ][ assembler ]   ← consumes proliferated magnet
```

Corridors are ≤3 lanes and the proliferator lane is one of them, so the sprayer is
always within Mk.I reach of its supply. No new geometry required.

**Consequence.** A directly-inserted edge has no belt, hence nowhere to mount a sprayer,
hence its item arrives unproliferated. So for any group `q` with `prolif_mode ≠ NONE`,
every edge delivering an item in `q.sprayed_inputs` **must** use a lane — §3.3.

**Proliferation and direct insertion compete.** Proliferation cuts machine *count*
(≈20 % in `PRODUCTS`, up to 50 % in `SPEED`); direct insertion cuts *tiles per machine*.
The model resolves this per edge, since `prolif_mode` is fixed per group upstream while
`di[e]` stays free for unsprayed edges.

**Feedback for the rate-solver agent:** its mode choice minimises machine count in
isolation, which is not the same as minimising *area*. If the bake-off shows this
mattering, emit 2–3 candidate `BuildSpec`s and let the layout stage pick the smallest.

### 4.4 Spray coater footprint

Selection volume reads `1.3 × 2.5 × 4.8`, which does not map cleanly to a footprint.
**⚠ Needs the catalog table.** Assume **1×2** straddling the belt, as
`SPRAY_FOOTPRINT`. If larger, corridors hosting a sprayer grow locally — already
handled, since corridor height is a variable.

### 4.5 Why this should beat Strategy B — an explicit, falsifiable prediction

I do believe this is where Strategy A wins, and the reason is structural rather than
incidental.

**Strategy B** treats proliferator as one more commodity in its multi-commodity routing.
Its sinks are *every machine running a proliferated recipe* — under default settings,
nearly all of them. So B must find `Θ(N)` additional routes through free space that is
already congested with recipe belts, and each route competes for the same cells. B's
proliferator overhead therefore **grows with machine count**, and worse, it grows fastest
exactly where free space is scarcest — a dense B packing is the hardest case for adding
one more commodity to.

**Strategy A** pays for proliferator **once per corridor**, not once per machine. A
single lane at +1 tile of corridor height is simultaneously within sorter reach of every
machine on both sides of that corridor. Overhead scales with the number of corridors —
i.e. with recipe *depth*, typically 4–8 — and is **flat in machine count**. Widening a
row from 4 machines to 40 adds zero proliferator cost in A; in B it adds 36 routes.

This is the general principle behind the whole strategy: a shared linear structure
amortises any distribution problem across every machine adjacent to it. Proliferator is
the clearest instance, and power (§5) is the second — both are "reach everything"
problems, and both cost A a constant per corridor or per row rather than a term per
machine.

**How to measure it.** In `bench/`, report `area(--proliferator mk3) − area(--proliferator
none)` for both strategies across corpus entries of increasing machine count. The
prediction is that A's delta is roughly flat while B's grows with N. If A's delta also
grows with N, this argument is wrong and I want to know — that would mean corridor height
is being driven by something other than lane count.

---

## 5. Power — a hard constraint in the model

Scope: place **Tesla towers** so every powered building is inside some tower's supply
radius, and all towers form one connected electrical network via their tower-to-tower
link radius. **No generation** — the user connects the block to their planetary grid.

Coverage is a *constraint solved jointly with placement*, never a post-pass. That
matters: a post-pass can discover a machine is uncoverable only after the layout is
fixed, forcing either a re-solve or an unpowered building. Here infeasibility surfaces
while the solver can still move machines.

### 5.1 Why towers fit this skeleton for free

The awkward part of power is that towers occupy space and must not collide with what
they power. In a free-form layout that is a genuine 2D packing interaction. Here it is
not, because of one structural fact:

> **Rows hold machines; corridors hold belts. A tower placed in a row blocks no belt.**

So a tower is simply **another block in the row's existing 1D packing** (§2.2's
`AddNoOverlap`). No new geometry, no interaction with lanes, no interaction with risers.
This is the same amortisation argument as §4.5: the structure already exists, so the new
requirement rides on it.

### 5.2 Tower placement variables

Towers are placed in rows, plus an optional east spine (§5.4).

```
nt[r]     ∈ [0, NT_max]        towers in row r
tx[r][m]  ∈ [T, W_max]         x of the m-th tower in row r, for m < NT_max
active[r][m] ⇔ m < nt[r]       (ordering / symmetry break)
tx[r][m] < tx[r][m+1]          strictly increasing -- kills m! permutations
```

Each active tower contributes a `tw × th` block to row `r`'s `AddNoOverlap` and
`nt[r]·tw` to `ww[r]` (§2.2). A tower's centre is at `(tx[r][m] + tw/2,
row_y[r] + hh[r]/2)` — vertically centred in its row, which maximises the reach
available to that row's machines (§5.3).

### 5.3 Coverage constraint

**Geometric reading: every *tile* of a powered building's footprint must lie within
`SUPPLY_R` of some tower centre — not merely the building's centre.**

This is the conservative reading and it is the right one. DSP requires a building to be
inside the supply area to draw power; a footprint straddling the boundary is at best
undefined and at worst unpowered. Testing centres only would let a 4×4 assembler be
"covered" while two of its tiles sit outside the radius. Erring this way can only ever
*add* towers, never produce an unpowered machine — the same failure direction as every
other rounding choice in this spec (§2.5).

**Powered buildings** are machines, sorters, spray coaters, and labs. **Belts are not
powered in DSP** and are excluded — worth stating because it is what makes corridors
cheap to cover.

*Linearising the circle.* Both the tower and the machine sit in row `r`, so the vertical
offset is bounded by the row band. Let `dy_max[r] = hh[r]/2 + max(Ltiles[r], Ltiles[r+1])`
— half the row height (machine tiles above/below the tower centre) plus the taller
adjacent corridor, since sorters and sprayers in those corridors also need power. Then
the exact horizontal reach at that vertical offset is

```
hr[r] = floor( sqrt( SUPPLY_R² − dy_max[r]² ) )
```

This is **exact for the circle**, not an inscribed-square approximation — because we
evaluate the circle at the worst-case `dy` rather than bounding `dx` and `dy`
independently. An inscribed square would throw away ~36 % of the supply area; this
throws away only the coverage above `dy_max`, which no building occupies.

`hh[r]` and `Ltiles[c]` are variables with small domains, so `hr[r]` is a table lookup:
`AddElement(dy_max[r], REACH_TABLE, hr[r])` with `REACH_TABLE[d] = floor(sqrt(R²−d²))`
precomputed, and `0` where `d ≥ SUPPLY_R`.

*The covering constraint.* Row `r`'s powered span is the contiguous interval
`[T, T + ww[r])`. Tower `m` covers `[tx[r][m] − hr[r], tx[r][m] + tw + hr[r]]`. Full
coverage of a contiguous interval by intervals of equal reach is a simple chain:

```
nt[r] ≥ 1                                    whenever rowactive[r]
tx[r][0] − hr[r]              ≤ T                          (left end covered)
tx[r][m+1] − (tx[r][m] + tw)  ≤ 2·hr[r]                    (no gap between towers)
tx[r][last] + tw + hr[r]      ≥ T + ww[r]                  (right end covered)
```

Three linear constraints per tower. **If `hr[r] == 0` the row is uncoverable** — the row
is taller than the supply diameter. The model then simply cannot use that row height,
which is exactly the desired behaviour: it pushes machines to other rows *while they can
still move*. If no assignment works, we report a clear error naming the offending
machine and suggest `--no-power`.

### 5.4 Connectivity — a lattice, not a flow formulation

Connectivity on a graph whose edges depend on placement is the genuinely awkward part.
The textbook encoding is a **single-commodity spanning-tree flow**: pick a root, give
each tower a unit demand, push flow along candidate edges, and reify each edge on the
distance between its endpoints. That costs `O(NT²)` edge variables plus `O(NT²)` flow
variables, and — the real problem — every edge's existence is a reified *quadratic*
distance test between two variable positions, which CP-SAT propagates poorly.

**I reject that in favour of connectivity by construction**, which the coordinator
correctly anticipated is much cheaper here. Two structural facts do the work:

1. **Within a row**, §5.3 already forces consecutive towers to satisfy
   `tx[m+1] − tx[m] ≤ 2·hr[r] + tw`. Add the single extra constraint
   `tx[r][m+1] − tx[r][m] ≤ LINK_R` and every row's towers form a **connected chain**,
   left to right, with no new variables at all. In practice `LINK_R > 2·hr`, so this
   constraint is usually slack and costs nothing.

2. **Between rows**, either adjacent rows are close enough to link directly, or the
   **east power spine** bridges them:

```
use_spine == 0  ⇒  ∀c: row_pitch[c] ≤ LINK_R
                   where row_pitch[c] = hh[c-1]/2 + Ltiles[c] + hh[c]/2
use_spine == 1  ⇒  spine towers at x = W − tw, y = sy[0] < sy[1] < …,
                   sy[m+1] − sy[m] ≤ LINK_R,  sy[0] ≤ LINK_R,  sy[ns-1] ≥ H − LINK_R,
                   and ∀r: (T + ww[r]) ≥ (W − tw) − LINK_R      (rows reach the spine)
```

The last clause is what ties each row's rightmost tower to the spine. Given (1) chains
each row internally and the spine chains vertically, the whole network is connected **by
induction over rows** — no flow variables, no reified distance tests, `O(NT)` constraints
total.

`use_spine` is a free bool, so the model chooses between "keep rows close" and "pay `tw`
columns of width". Both are cheap; letting the objective pick is better than guessing.

*Diagonal links between row towers are ignored.* A diagonal link could sometimes save a
spine tower, but admitting it reintroduces exactly the variable-position distance tests
this formulation exists to avoid. Ignoring them is conservative — it can only add towers.

### 5.5 Tower count as a secondary objective

Towers cost area twice: `tw` of row width each, and possibly `tw` columns for the spine.
Row width feeds `W` feeds `area`, so the **primary objective already prices them**. The
explicit term at tie-break position 2 (§2.6) breaks ties among equal-area solutions —
fewer towers is cheaper to build, less power drain, and less visual clutter.

Placing it *above* the belt-count and direct-insertion tie-breaks reflects that a tower
is a whole building occupying multiple tiles, while a lane is one tile of corridor.

### 5.6 `--no-power` degradation

The flag drops power cleanly and completely:

- Skip all tower variables (`nt`, `tx`, `hr`, `use_spine`, `ns`, `sy`).
- Skip §5.3 and §5.4 entirely.
- `ww[r] == Σ_p k[p][r]·w_p` (no tower term); `W == T + max_r ww[r]` (no spine term).
- Drop tie-break 2 from §2.6.
- Emit no tower `PlacedBuilding`s.
- The §7 fallback skips its tower pass.

Implement as a single `power: bool` parameter threaded to model construction, guarding
each block — *not* as a post-hoc filter of the emitted `Placement`, which would leave the
area objective having paid for towers that were then removed. The §8 test suite runs the
whole corpus both ways, so the no-power path is exercised on every run.

---

## 6. External I/O

**Convention: all external inputs enter on the north edge (corridor `C0`); all external
outputs leave on the south edge (corridor `CR`).**

```
   ═══ iron-ore ═══ copper-ore ═══ coal ═══ proliferator-mk3 ═══   ← C0, inputs
   [ smelters ]
   ...
   [ final assemblers ]
   ═════════════ super-magnetic-ring ═══════════════════════════   ← CR, output
```

- Topological row ordering already puts raw consumers at the top and product at the
  bottom — the natural flow direction, needing no extra risers.
- Opposite edges make the block **tileable in a column**: stack `n` copies and each
  block's outputs meet the next one's inputs.
- In game you connect one input bundle and one output belt, both on straight edges.
- Proliferator enters as another input on `C0`, then takes its utility riser (§4.2).
- The power spine sits on the **east** edge, deliberately orthogonal to the I/O edges, so
  tiling a column of blocks leaves the spines adjacent and linkable.

Surplus items from rounding machine counts up route to `CR` alongside the product so
nothing backs up; the description records which outputs are surplus.

---

## 7. Fallback — guaranteed feasible

`fallback_layout(spec) -> Placement` is deterministic, used when CP-SAT is infeasible,
times out with no incumbent, or `--no-solver` is passed. It is *also* the `AddHint` warm
start and width-sweep seed, so it runs every time and cannot rot.

1. Topologically sort groups; one group per row, in topological order.
2. Every item gets a lane in every corridor of its span — no risers, `T = 0`.
3. Proliferator gets a lane in every corridor (§4.2), with spray coaters on every sprayed
   input lane.
4. No direct insertion; every connection is machine → lane → machine.
5. If `L[c] > 3`, insert an empty spacer row so no lane is deeper than 3 from a tapper.
6. Row width is the plain sum of machine widths.
7. **Power (unless `--no-power`):** append towers to each row greedily at spacing
   `min(2·hr[r] + tw, LINK_R)` from `x = T`, then add the east spine at vertical spacing
   `LINK_R`. Greedy interval covering is optimal for equal-reach intervals on a line, so
   this is not merely feasible but *tower-minimal for the given row widths*.

`O(|P| + |I|·R + NT)`, always valid, typically **1.5–3× the solved area** — a useful
bake-off baseline. Emit `Placement.stats["fallback"] = 1.0`.

---

## 8. Test plan

### 8.1 Geometry helpers (pure unit tests)

- `row_y`, `corr_y` monotone and non-overlapping for random row/corridor heights.
- `sorter_anchors` spans within `reach(tier)` for every tier and orientation.
- Interval colouring: random riser spans → no two overlapping risers share a channel; `T`
  equals max point-coverage.
- **`up`/`down` scaling** — Hypothesis property test over random `Fraction`s asserting
  the §2.5 lemma, parameterised over `stackf ∈ [1,4]`. The one place a correctness bug
  would be invisible in game; test it hard.
- Height-waste term matches brute force on random row contents.
- **`REACH_TABLE[d] == floor(sqrt(R²−d²))` for all `d`, and `0` for `d ≥ SUPPLY_R`.**
- **Coverage chain:** random row widths and reaches → the §5.3 constraints hold iff every
  tile of `[T, T+ww)` is within `SUPPLY_R` of some tower, checked by brute force against
  the true circular distance. This is the test that catches a linearisation error.

### 8.2 End-to-end properties

Corpus: the example URL's spec, a single-recipe spec, a deep linear chain, a wide fan-in,
a spec forcing a riser, a fully proliferated spec, **and a spec with a machine taller than
`SUPPLY_R` (exercises the §5.3 uncoverable path)**. Every entry runs **both with and
without `--no-power`**.

- **No overlaps.** No two footprints share an `(x,y,z)` cell — towers included. Use
  `layout/validate.py` so A and B are judged identically.
- **Every machine fed.** For each machine and ingredient, a sorter exists whose
  `output_obj` is that machine and whose input chain reaches a source.
- **Every sprayed input is actually sprayed** (asserts §3.3 and §4.3).
- **Proliferator reaches every consumer**, lane within capacity.
- **Power coverage.** Every powered building — machine, sorter, spray coater — has all
  footprint tiles within `SUPPLY_R` of some tower centre, checked with true Euclidean
  distance, *not* the linearised form. Belts exempt.
- **Power connectivity.** Build the tower graph with true Euclidean `LINK_R` edges and
  assert a single connected component via union-find. Independent of the lattice
  reasoning, so it would catch a broken induction argument in §5.4.
- **`--no-power` emits zero towers** and every other property still holds.
- **Throughput.** Recompute exact `Fraction` rates over the emitted graph.
- **Belt continuity.** Every chain ends at a machine, sorter pickup, or block edge.
- **Monotone anytime.** `area(30s) ≤ area(5s)` — guaranteed by warm start plus descending
  sweep, so a real regression test rather than a flake.
- **Determinism.** Fixed budget and seed → byte-identical `Placement`. Set
  `num_search_workers = 1`; multi-worker CP-SAT is *not* deterministic.
- **Fallback validity.** The fallback alone passes every property above, power included.

### 8.3 Bake-off hooks

`Placement.stats`: `area`, `machines`, `belts`, `sorters`, `spray_coaters`, `towers`,
`corridor_tiles`, `trunk_width`, `spine_width`, `direct_inserts`, `height_waste`,
`solve_seconds`, `solver_status`, `fallback`.

`bench/` additionally reports the two **amortisation deltas** that test §4.5's prediction:
`area(prolif) − area(no-prolif)` and `area(power) − area(no-power)`, per strategy, across
corpus entries of increasing machine count. Strategy A's deltas should be roughly flat in
machine count; Strategy B's should grow.

---

## 9. Catalog-dependent constants — the one place they live

All of these come from `dsp/catalog.py`, extracted from game assets by the catalog agent.
**Nothing below is hardcoded in `spine.py`;** it reads a single `LayoutConstants` frozen
dataclass so a correction lands in one place.

| Constant | Used by | Status |
|---|---|---|
| `footprint(machine_item_id) -> (w,h)` | §1.4, §2.2 | from catalog |
| `reach(sorter_tier) -> tiles` | §1.5, §3 | from catalog |
| `sorter_tp(tier, span) -> Rate` | §2.5, §3.2 | from catalog |
| `belt_capacity(tier) -> Rate` | §2.4 | from `BuildSpec` |
| `SPRAY_FOOTPRINT` | §4.4 | from catalog; assumed 1×2 |
| **`TESLA_ITEM_ID`** | §5 emission | **pending catalog agent** |
| **`TESLA_MODEL_INDEX`** | §5 emission | **pending catalog agent** |
| **`tw`, `th` — tower footprint** | §5.2, §2.2 | **pending catalog agent** |
| **`SUPPLY_R` — supply radius, tiles** | §5.3 | **pending catalog agent** |
| **`LINK_R` — tower-to-tower link radius, tiles** | §5.4 | **pending catalog agent** |
| `RAMP_TILES` | §1.3 | in-game check; default 2 |
| `MAX_STACK` | §2.4 | 4, `beltStack` flag |

Two notes on the pending power constants. First, **`SUPPLY_R` is a radius in tiles and
DSP states supply areas as a diameter in some UI text** — confirm which, since a factor-2
error here silently doubles or halves tower count. Second, whether the radius is measured
from the tower's **centre** or its **footprint edge** changes `hr[r]` by up to `tw/2`;
assume centre, and note it in `LayoutConstants` so the catalog agent can correct it.

---

## 10. Open questions — flagged guesses

| # | Assumption | Default | Fallback if wrong |
|---|---|---|---|
| 1 | Sorter reach Mk.I/II/III = 1/2/3 | as stated | catalog table; only `reach()`/`sorter_tp()` change |
| 2 | Sorter throughput decreases with span | yes | if flat, direct insertion gets cheaper |
| 3 | Belt needs `RAMP_TILES=2` per altitude level | 2 | raise it; or `allow_altitude=False` ⇒ `T ≤ 1` |
| 4 | A ground sorter can tap a `z=1` belt | assumed **NO** | `stack_corridor_lanes=False`; enabling is upside |
| 5 | Sorter anchors are the connected tiles | assumed | isolated in `sorter_anchors()` |
| 6 | Machines have no forced I/O faces | assumed free | add a facing var restricting which edge tiles host sorters |
| 7 | **Proliferator is consumed by spray coaters** | **assumed YES — §4.1** | if per-machine, drop §3.3/§4.3; §4.2 unchanged |
| 8 | Spray coater footprint 1×2 | 1×2 | `SPRAY_FOOTPRINT`; corridor height already variable |
| 9 | Spray does not survive crafting | assumed YES | if it propagates, §3.3 relaxes to raw-input edges — large win |
| 10 | **Belts do not consume power in DSP** | assumed YES | if they do, corridors need coverage too — `dy_max` already includes `Ltiles`, so §5.3 covers it unchanged |
| 11 | **Supply radius measured from tower centre** | assumed centre | shifts `hr[r]` by `tw/2`; one constant |
| 12 | **`SUPPLY_R` is a radius, not a diameter** | assumed radius | factor-2 error in tower count — **verify first** |

Items 1, 2, 5, 8 and all of §9's power constants come from the catalog agent. Items 3, 4,
6, 7, 9, 11, 12 need in-game confirmation. All fail toward a working-but-larger build
rather than a broken one — **except 12**, which is the one assumption that could produce
*unpowered machines* if it is wrong in the permissive direction. Treat it as blocking for
the power feature, and note that §8.2's Euclidean coverage check uses the same constant,
so it would not catch the error. Confirm it against a real blueprint containing towers.
