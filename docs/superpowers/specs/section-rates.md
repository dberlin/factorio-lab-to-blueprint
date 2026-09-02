# Design Spec — Stages 1–3: URL → Rates → BuildSpecSet

Modules: `lab/url.py`, `lab/data.py`, `rates/solve.py`, `spec.py`

All facts below were verified against the live dataset
(`https://factoriolab.github.io/data/dsp/data.json`, version `DSP 0.10.29.21950`,
486 items / 493 recipes) and against FactorioLab `main` source, not assumed.
Corrections to the briefing assumptions are collected in §8.

**Revision 2.** Proliferator is consumed by spray coaters on belts, not by machines, so
proliferation and direct insertion compete for the same edges (§4.0). Stage 3 therefore emits
a **`BuildSpecSet`** — an ordered frontier of candidate builds (§6.3) — and the layout stage
picks whichever places smallest. Revision 1's single "optimal" answer survives only as the
`max-proliferation` endpoint of that frontier.

---

## 1. `lab/url.py` — URL parsing

### 1.1 Wire format

Two encodings, distinguished by presence of `z`:

| form | detection | contents |
|---|---|---|
| **bare** | `z` absent | plain ids in query params (`o=super-magnetic-ring*60`) |
| **zipped** | `z` present | `z=<payload>&v=11`, payload decodes to a full `k=v&k=v` string |

Zipped payload decoding (verified against `src/state/router/compression.ts`):

```python
ZB64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.'
STD  = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
_TBL = str.maketrans(ZB64 + '_', STD + '=')

def inflate(s: str) -> str:
    s = s.replace('+', '-').replace('/', '.').replace('=', '_')  # legacy rewrite
    return zlib.decompress(base64.b64decode(s.translate(_TBL))).decode()
```

**`CompressionStream('deflate')` is RFC 1950 zlib** (header `0x78 0x9C`, payloads begin
`eJw`), *not* raw deflate — so plain `zlib.decompress` with default `wbits=15` is correct.
`decompress(..., -15)` would be wrong.

FactorioLab's `inflate()` retries with `-`, `.`, `_` appended to repair URLs truncated by
chat clients. **Mirror that**: try the string as-is, then with each of the three padding
chars appended (up to 2), and raise only if all fail. Cheap, and it fixes a real class of
user-pasted URLs.

Structural rules from `base64ToBytes`: length must be `% 4 == 0`; `_` may only appear in
the final two positions.

### 1.2 Separators (`src/state/router/constants.ts`, verified)

```
ZEMPTY = '_'   ZARRAYSEP = '~'   ZFIELDSEP = '*'   ZTRUE = '1'   ZFALSE = '0'
```

Two encoding rules that are easy to get wrong and must be handled:

- **Empty field means "default", not "absent".** `zipDiffNumber`/`zipDiffRational` emit an
  empty string when the value equals the default. `o=iron-ingot**3` is
  `targetId=iron-ingot, value=<default 1>, unit=3`.
- **Trailing empty fields are stripped** (`.replace(/\*+$/, '')`). A record with fewer
  fields than the schema is normal; missing tail fields take defaults.
- `_` as a whole field value means an explicitly empty string (distinct from default).

### 1.3 Field orders

`o` (objectives), from `RouterSync.zipObjectives`:

```
0 targetId  1 value  2 unit  3 type  4 machineId
5 moduleIndices(~)  6 beaconIndices(~)  7 overclock  8 fuelId
```

Defaults: `value=1`, `unit=ObjectiveUnit.Items(0)`, `type=ObjectiveType.Output(0)`.

```
ObjectiveUnit:  0 Items   1 Belts   2 Wagons   3 Machines
ObjectiveType:  0 Output  1 Input   2 Maximize 3 Limit
```

When `unit == Machines(3)`, `targetId` is a **recipe id**; otherwise an **item id**.

Other repeatable params:

```
i  itemId * beltId * wagonId * stack * excludeRockets
r  recipeId * machineId * modules * beacons * overclock * cost * fuelId * productivity
m  machineId * modules * beacons * fuelId * overclock
e  count * moduleId                       (module list; `o`/`r`/`m` index into it)
b  count * moduleIndices * beaconId * total
```

### 1.4 Params honored vs ignored

**Honored:**

| param | use |
|---|---|
| `o` | objectives — the whole point |
| `v` | version gate |
| `z` | compressed payload |
| `ibe` | belt tier → belt items/s for lane sizing (**not** machine counts) |
| `mmr` | machine rank → which producer builds each recipe; drives `machine.speed` |
| `odr` | display rate → objective normalization (1=/s, 60=/min, 3600=/h) |
| `rex`, `iex` | excluded recipes/items — changes which recipes the solve may use |
| `mps` | proliferator self-spray — read, but see §4.5 (ignored by default, deliberately) |
| `mpr` | preset → belt/machine/module rank defaults |
| `mer` | module rank → the URL's own proliferator choice, used by `--proliferator url` |
| `bmi` | mining productivity — affects only mining recipes, which we cut (§5); recorded for reporting |

**Ignored, with rationale:**

- `ipi`, `icw`, `ifw`, `ifr`, `ist` — pipes/wagons/flow/stack. DSP has no fluid wagons in
  this dataset and we belt everything; stack/pile is out of scope for v1 (see §6.4).
- `mbe`, `mbr`, `moc` — beacons and overclock do not exist in DSP; the dataset has no
  beacon items. Parse and warn if non-default.
- `cfa`…`cre` — LP cost weights. We replace FactorioLab's objective entirely (§3.4), so
  these do not apply. **Warn** if set to non-defaults, since the user's intent differs.
- `tfi`, `tso`, `tas`, `tpg`, `tro`, `och`, `omt`, `orm`, `rnp`, `rcm`, `tre`, `loc`,
  `bre`, `brp` — table UI state, or research/tech settings with no bearing on a factory
  floorplan.

`omt`/`ObjectiveType.Maximize` and `Limit` are **rejected** in v1 with a clear error:
a "maximize" objective has no finite machine count, so there is no blueprint to build.
`ObjectiveType.Input(1)` is likewise rejected (it constrains a supply, not a build target).

### 1.5 Version policy

Recommend **V11 only**. `migration.ts` is 1068 lines implementing V0→V10, and pre-V11
zipped payloads use a different, delimiter-less key scheme (key = first character only).
Porting it is a large, low-value surface.

Error message must give the user the fix rather than just failing:

> `Unsupported FactorioLab URL version '9' (only v11 is supported). Open the URL in
>  FactorioLab — it migrates automatically — then copy the updated URL from the address bar.`

Detect version from `v`; **absence of `v` with bare params is also V11** (FactorioLab omits
`v` on short bare URLs — the example URL carries `v=11` explicitly, but do not require it).

### 1.6 Dataclasses

```python
@dataclass(frozen=True)
class Objective:
    target_id: str                 # item id, or recipe id when unit is MACHINES
    value: Fraction
    unit: ObjectiveUnit = ObjectiveUnit.ITEMS
    type: ObjectiveType = ObjectiveType.OUTPUT
    machine_id: str | None = None
    module_indices: tuple[int, ...] = ()
    fuel_id: str | None = None

@dataclass(frozen=True)
class LabRequest:
    objectives: tuple[Objective, ...]
    machine_rank: tuple[str, ...] = ()      # mmr
    module_rank: tuple[str, ...] = ()       # mer
    belt_id: str | None = None              # ibe
    proliferator_spray_id: str | None = None  # mps
    display_rate: int = 60                  # odr; 60 = per minute (FactorioLab default)
    excluded_recipes: frozenset[str] = frozenset()
    excluded_items: frozenset[str] = frozenset()
    preset: int | None = None               # mpr
    raw_params: Mapping[str, list[str]] = field(default_factory=dict)  # for warnings
```

`raw_params` is retained solely so the CLI can emit "ignored parameter" warnings without
`url.py` importing a logger.

---

## 2. `lab/data.py` — dataset access

### 2.1 Fetch and cache

- Primary: `https://factoriolab.github.io/data/dsp/data.json` (263 KB, verified 200).
- Cache to `platformdirs.user_cache_dir("dsp-blueprint")/dsp-data-<sha256[:12]>.json`
  with a 24h freshness stamp.
- **Vendored fallback** committed at `src/dsp_bp/data/dsp-data.json`, so the tool works
  offline and tests are hermetic and reproducible. `--offline` forces the vendored copy;
  `--refresh-data` forces a fetch.
- Record `data["version"]["DSP"]` in the generated blueprint's description field so a
  blueprint can be traced to the dataset that produced it.

`hash.json` is **not needed** — it is only required to decode `z=` payloads written in the
*hash* encoding. Since `getHash()` picks bare whenever `len(bare) < max(len(zip), 200)`,
and we decode `z=` to a plain `k=v` string containing bare ids, we never index into
`hash.json`. *Caveat:* FactorioLab does emit hash-encoded ids inside `z=` for long URLs.
Detect this — an id that is not found in the dataset but is a valid base-64-ish token —
and fall back to fetching `hash.json` and resolving via `idToN`. Implement the detection
in v1, the resolution behind a clear `NotImplementedError` unless a real URL needs it.

### 2.2 Typed accessors

```python
class DspData:
    items: Mapping[str, Item]         # 486
    recipes: Mapping[str, Recipe]     # 493
    limitations: Mapping[str, frozenset[str]]
    default_excluded_recipes: frozenset[str]
    min_machine_rank / max_machine_rank / min_belt / max_belt / module_rank: tuple[str,...]

    def producers_of(item_id) -> tuple[str, ...]   # recipe ids, post-exclusion
    def machine(machine_item_id) -> Machine        # speed, usage, drain, modules, type
    def belt_speed(belt_item_id) -> Fraction       # items/s
```

All numeric fields converted to `Fraction` **at parse time** via `Fraction(str(x))` —
never `Fraction(float)`. `Fraction(str(0.75))` is exactly `3/4`; `Fraction(0.75)` happens
to be exact but `Fraction(0.1)` is not. Parse from the JSON text, not the float.

Verified constants worth pinning in tests:

```
belts:   conveyor-belt-1 = 6/s   conveyor-belt-2 = 12/s   conveyor-belt-3 = 30/s
speeds:  arc-smelter 1   plane-smelter 2   df-negentropy-smelter 3
         assembling-machine-1 0.75   assembling-machine-2 1   assembling-machine-3 1.5
         df-recomposing-assembler 3   chemical-plant 1   quantum-chemical-plant 2
         matrix-lab 1   df-self-evolution-lab 3
```

---

## 3. `rates/solve.py` — the production solve

### 3.1 Machine selection

`bestMatch`: first id in `mmr` that appears in `recipe.producers`; else `producers[0]`.
Per-recipe `r` overrides and per-objective `machineId` take precedence when present.

### 3.2 Per-machine rate

For recipe `R`, machine `M`, proliferator module `P` (possibly none):

```
eff_time  = R.time / (M.speed * (1 + P.speed))
eff_out_i = R.out[i] * (1 + P.productivity)
eff_in_i  = R.in[i]                          # productivity does NOT reduce inputs
rate_i    = (eff_out_i - eff_in_i) / eff_time      # items/s per machine, signed
```

`R.in` is **not** scaled by productivity — that is the whole reason products-mode
compounds: more output per identical input.

### 3.3 Objective normalization

```
ObjectiveUnit.ITEMS    : rate = value / display_rate_seconds
ObjectiveUnit.BELTS    : rate = value * belt_speed(ibe)
ObjectiveUnit.MACHINES : target is a recipe; rate derived from its per-machine output
```

`odr` values are seconds-per-period: 1, 60, 3600. Default 60 (per minute). So
`o=super-magnetic-ring*60` with no `odr` = 60/min = **1/s**.

### 3.4 Formulation: MILP, not LP-then-round

**This is the single most important decision in this section, and it differs from the
briefing.** Do *not* solve an LP and then ceil the machine counts.

Model:

```
for each (recipe R, proliferator mode m) pair:
    n[R,m]    ∈ ℤ≥0          number of machines
    x[R,m]    ∈ ℚ≥0          crafts/second actually run
constraints:
    x[R,m] ≤ n[R,m] * craft_rate(R,M,m)          # machines may idle, never exceed
    for each internal item i:
        Σ produced(i) − Σ consumed(i)  ≥  demand(i)   # ≥, surplus permitted
    external items (§5) are unconstrained sources
objective:
    minimize  Σ n[R,m] * footprint_area(machine(R))
```

Why each piece:

- **Integer `n` with separate continuous `x`** models DSP truthfully: a machine whose
  output backs up throttles, so 6 smelters covering a 5.64 requirement each run at 94%.
  Upstream demand is driven by `x` (what is actually consumed), not by `n`.
- **`≥` not `=`** admits surplus, which is required anyway for the two joint-product
  recipes (`plasma-refining` → hydrogen + refined-oil; `mass-energy-storage` → antimatter
  + hydrogen), where exact balance is generally infeasible.
- **Area objective, not machine count.** Measured on the example chain: minimizing exact
  machine count yields **339 tiles**, minimizing footprint area yields **325 tiles** — a
  4% density win, and minimizing *ceil machine count* gives 25 machines but **330 tiles**,
  i.e. fewer machines occupying more space (arc-smelter 9 tiles vs assembler 16). Since
  the deliverable is density, area is the correct objective.

The LP relaxation (265.32 tiles here) is retained as a **lower bound** and reported, so
the bake-off in stage 4 can be scored against a known optimum.

### 3.5 Solver choice

**`highspy`** (HiGHS). Native mixed integer + continuous, MIT-licensed, pip/uv installable,
and fast at this scale (tens of columns). OR-Tools CP-SAT is used for layout in stage 4,
but is a poor fit here: CP-SAT is a pure-integer solver, so the rational craft-rates would
need scaling to a common denominator, which for exact rationals over a deep chain produces
enormous integers. Keep the two solvers in their respective lanes.

Always MILP — no tree-walk fast path. Only 7 of 173 available DSP recipes' output items
have more than one producer, so a tree walk would cover most inputs, but maintaining two
code paths that must agree is a standing correctness liability for a solve that takes
milliseconds either way. **One path, always the MILP.**

### 3.6 Exact-rational post-verification

HiGHS returns floats. After solving:

1. Take the integer `n[R,m]` values (round to nearest int, assert within 1e-6).
2. **Re-derive all flow rates in exact `Fraction` arithmetic** by propagating demand
   through the fixed mode assignment.
3. Assert every item balance holds exactly (`produced ≥ consumed`) in `Fraction`.

Everything downstream consumes only the `Fraction` values. Floats never reach `BuildSpec`.
This gives MILP's search quality with exact-rational guarantees.

---

## 4. Proliferator

### 4.0 The placement mechanic — proliferation and direct insertion COMPETE

**This reframes the whole section and was corrected after the first draft.**

Proliferator is *not* an extra input consumed by a production machine. It is consumed by
**spray coaters mounted on belts**, which apply spray to items *travelling on a belt*.
Spray does **not survive crafting** — the bonus is granted to the machine that consumes
sprayed items, and that machine's own output emerges unsprayed.

Therefore, to proliferate recipe `R`, **every input item of `R` must arrive on a belt**, so a
spray coater can spray it before it enters the machine.

The consequence for layout is direct and unavoidable:

> A directly-inserted edge has no belt, so nothing can spray it.
> **Proliferating a recipe forbids direct insertion on every one of that recipe's input edges.**

FactorioLab's placement of proliferator inside `recipe.in` is a correct *rate* abstraction
and the arithmetic in §4.4 stands. It is **not** a placement model, and the first draft of
this spec wrongly treated proliferation as geometrically free. The consequences:

- The reported "2.7× fewer machines" is an **upper bound**, not a prediction. It buys machine
  area by spending belt corridors and sorters.
- Mode choice can no longer be optimised in isolation from geometry. Since the rate stage
  cannot see geometry, it must **hand the layout stage a set of candidates** (§6) rather than
  one answer.

**Assumption (conservative, must be verified):** a recipe gets the proliferator bonus only if
**all** of its inputs are sprayed. Partial spraying is modelled as no bonus. This is the safe
direction — assuming a full bonus from partially-sprayed inputs would over-estimate output and
under-build, violating throughput-correctness. *Open question for the catalog agent, who has
the game files: check how `AssemblerComponent` combines the per-item `incLevel` of consumed
inputs (minimum? average? per-item?). If DSP grants a proportional bonus, a finer model is
possible and the frontier in §6.3 gains intermediate points.*

**Spray coaters are shared per lane.** One coater on a lane sprays for every consumer of that
lane, so the coater count is the number of distinct *sprayed lanes*, not sprayed recipes.

### 4.1 Verified module table

From `data.json` — the briefing's spray counts were **correct**:

| module id | productivity | speed | sprays | consumption | limitation |
|---|---|---|---|---|---|
| `proliferator-1-products` | +0.125 | — | 12 | 0.3 | productivity |
| `proliferator-2-products` | +0.2 | — | 24 | 0.7 | productivity |
| `proliferator-3-products` | +0.25 | — | 60 | 1.5 | productivity |
| `proliferator-1-speed` | — | +0.25 | 12 | 0.3 | *(none)* |
| `proliferator-2-speed` | — | +0.5 | 24 | 0.7 | *(none)* |
| `proliferator-3-speed` | — | **+1.0** | 60 | 1.5 | *(none)* |

### 4.2 The `limitation` constraint — a real gate

`limitations.productivity` is a list of **464 recipe ids** (verified: all 464 resolve as
recipe ids; only 432 resolve as item ids, so it is unambiguously recipe-keyed).

- **products-mode is legal only for recipes in that set.**
- **speed-mode has no `limitation` field and is legal for every recipe.**

26 non-technology recipes are speed-only, including several that matter in real builds:
`reforming-refine`, `deuterium-fractionation`, `deuterium`, `critical-photon`,
`antimatter-fuel-rod`, plus all the machine/belt/sorter upgrade recipes
(`conveyor-belt-2/3`, `sorter-2/3/4`, `assembling-machine-2/3`, `plane-smelter`,
`df-negentropy-smelter`, `quantum-chemical-plant`, …).

The MILP simply omits the `(R, products)` column when `R ∉ limitations.productivity`.

### 4.3 Mode choice folds into the MILP — measured payoff

One column per `(recipe, mode)` pair. Measured on the example chain (target 1 ring/s):

| strategy | exact machines | ceil machines | ceil area |
|---|---|---|---|
| no proliferator | 57.50 | 58 | — |
| all Mk.III products | 27.18 | 32 | — |
| all Mk.III speed | 28.75 | 30 | — |
| **per-recipe optimum (area)** | **21.64** | **26** | **325 tiles** |

Per-recipe mixing beats the better uniform strategy by ~19% and beats no-proliferator by
**2.7×** *in machine count alone*. Per §4.0 this is an **upper bound**: the "per-recipe
optimum" row proliferates every recipe and therefore forbids direct insertion everywhere.
§6.3 prices that geometric cost and turns this single number into a frontier.

The chosen assignment shows the underlying principle:

```
magnet              arc-smelter   5.640 → 6   mk3-speed
iron-ingot          arc-smelter   3.840 → 4   mk3-speed
electromagnetic-turbine  asm-2    2.560 → 3   mk3-products
electric-motor      asm-2         2.560 → 3   mk3-speed
super-magnetic-ring asm-2         2.400 → 3   mk3-products
magnetic-coil       asm-2         1.280 → 2   mk3-speed
copper-ingot        arc-smelter   1.280 → 2   mk3-speed
gear                asm-2         1.280 → 2   mk3-speed
energetic-graphite  arc-smelter   0.800 → 1   mk3-speed
```

**Products-mode's compounding only pays when a recipe's inputs are produced internally.**
For recipes fed entirely from external belts (`magnet`, `iron-ingot`, `copper-ingot`,
`energetic-graphite` — all consume only ore), reducing input demand buys nothing because
the input is free, while Mk.III speed halves the machine count outright. The MILP
discovers this without being told; do not hand-code the heuristic.

Note also that fractional splitting between modes is **physically realizable** — proliferator
mode is a per-machine setting, so "3 machines in products mode, 2 in speed" is legal. The
integer `n[R,m]` per mode expresses exactly that.

### 4.4 Proliferator consumption

Verified against `adjustment.ts:450-490`. Per craft:

```
proliferator_used = (Σ over R.in of quantity) / sprays
```

i.e. **total input item count per craft, divided by sprays** — every input item consumes
one spray, and one proliferator unit provides `sprays` sprays.

For the example chain at Mk.III optimum this totals **0.8293 proliferator-mk3/s**, which is
what sizes the proliferator input belt.

### 4.5 Self-spray (`mps`) — deliberately ignored by default

If `settings.proliferatorSprayId` is set, FactorioLab (a) multiplies `sprays` by
`(1 + P_spray.productivity)` and floors it — Mk.III with `mps=proliferator-2-products`
gives `floor(60 * 1.2) = 72` — and (b) adds self-consumption at
`uses / (floor(sprays*(1+prod)) - 1)`.

**Default: ignore `mps` and use the raw `sprays` value.** Rationale: proliferator is belted
in from outside this blueprint (user requirement), so whether it arrives pre-sprayed is the
external supply's business. Assuming it *is* pre-sprayed would under-size the proliferator
input belt by ~17% and break the throughput-correctness guarantee. Ignoring it over-supplies
slightly, which is the safe direction.

`--self-spray` opts into honoring `mps`, and the CLI warns when `mps` is present but ignored.

### 4.6 CLI

```
--proliferator {none,mk1,mk2,mk3,url}    default: mk3
```

`url` honors the URL's own `mer`/`mpr` (note: with `mpr` absent and no `mer`, DSP resolves
`moduleRank` to empty, so `url` usually means *no proliferator* — this is why the example
URL's `mps` is a no-op). `none` disables. `mk1`/`mk2`/`mk3` cap the tier; the MILP then
picks products-vs-speed per recipe at that tier.

---

## 5. Raw inputs: extraction is priced, never built

**Use the `mining` recipe flag to identify extraction.** Verified: exactly 22 recipes carry `flags: ["mining"]`,
and they are precisely the extraction set — all `mining-machine`/`advanced-mining-machine`
veins, `ocean` and `sulphuric-acid-vein` (water-pump), `crude-oil-seep` (oil-extractor),
and the six `orbital-collector` gas-giant recipes.

This is cleaner and more reliable than the briefing's proposed heuristic (producer-name
matching plus `totalRecipe` plus vein-input detection). `totalRecipe` is a property of the
*machine* (`mining-machine`, `advanced-mining-machine` only) and would miss `oil-extractor`,
`water-pump`, and `orbital-collector` entirely.

```python
def is_extraction(recipe) -> bool:   # priced as a supply column, never built
    return 'mining' in recipe.flags
```

The flag is NOT a cut line that makes an item external by itself; what makes an item
external is the LP choosing its extraction column, as described next.

An item is **external** (arrives on an input belt) when the URL supplies it (an Input
objective), when no recipe here can make it, or when the production LP prices its supply in
from extraction rather than crafting. Every enabled mining-flagged recipe is priced as an
ordinary LP column using FactorioLab's `adjustCosts`: a declared `cost` (veins 100-200,
`ocean` 1) prices it at output rate times that cost times the cost factor; an undeclared cost
(the six orbital-collector recipes) prices it at the machine cost. Crafting columns are priced
the same way: `costs.machine`, multiplied by `machine.size` area only when the dataset declares
one — and no DSP machine does, so for this dataset every machine, crafting or extraction,
costs exactly `costs.machine`. Weighting crafting machines by our own catalog footprint is
NOT FactorioLab's objective and flipped a boundary (five colliders lost to 31 deuterium
collectors, so deuterium was belted in where FactorioLab crafts it from collected hydrogen);
area belongs to the layout stage and the geometric lower bound, not to recipe choice.
That column then competes against crafting columns for the same
item, and the LP picks whichever mix is globally cheapest — not the cheapest single recipe,
since a crafting alternative also drags in its own upstream machines and their costs.
Extraction is never built — it gets no `SolvedGroup`, no footprint, no integer machine count
— so its chosen supply arrives on a belt exactly like a raw ore's. This is not a per-item
structural rule: in one captured flow, `graphene-advanced` (fire ice plus a hydrogen
coproduct from an `ice-giant` collector, priced around 0.18/unit) still beats crafting from
coal and sulfuric acid veins priced at 100-200/unit, while hydrogen for deuterium fuel rods
is instead collected directly from a gas/ice-giant collector rather than made via
`graphene-advanced` — each is simply the cheaper total route for its own request. A requested
output is always crafted: an Output objective asks for the item to be MADE, and a blueprint
of zero machines satisfies nobody. Concretely for the example chain: `iron-ore`, `copper-ore`,
`coal`; for the graphene chain, `sulfuric-acid` via `sulphuric-acid-vein`. Proliferator is
always forced external (§4).

Also treated as external: items in `iex`, and items with no producing recipe at all.

Recipes flagged `technology` (306 of them) are never buildable products and are excluded
from the recipe pool along with `defaults.excludedRecipes` (14 entries) and the URL's `rex`.
This leaves **173 available recipes**.

The 7 items with multiple producers after default exclusions — `accumulator`, `deuterium`,
`hydrogen`, `organic-crystal`, `refined-oil`, `space-warper`, `sulfuric-acid` — are what
make the MILP genuinely necessary rather than decorative.

---

## 6. `spec.py` — the `BuildSpecSet` interface

Because proliferation trades machine area against direct-insertion freedom (§4.0), and the
rate stage cannot see geometry, **stage 3 emits an ordered set of candidate `BuildSpec`s**
and the layout stage picks whichever places smallest. Each candidate is independently
complete and valid; they differ only in how far they trade belts for machines.

### 6.1 Dataclasses

```python
class ProliferatorMode(StrEnum):
    NONE = "none"; PRODUCTS = "products"; SPEED = "speed"

@dataclass(frozen=True)
class MachineGroup:
    recipe_id: str
    machine_item_id: str              # e.g. "assembling-machine-2"
    count: int                        # integer, ≥ 1
    proliferator_mode: ProliferatorMode
    proliferator_item_id: str | None  # "proliferator-mk3" item actually consumed
    inputs:  Mapping[str, Fraction]   # item -> items/s consumed by THIS GROUP (all machines)
    outputs: Mapping[str, Fraction]   # item -> items/s produced by THIS GROUP
    utilization: Fraction             # x / (n * craft_rate); ≤ 1

@dataclass(frozen=True)
class SprayLane:
    """A lane that must carry sprayed items, and the proliferator it consumes."""
    item_id: str                      # the item being sprayed on this lane
    consumers: tuple[str, ...]        # recipe ids relying on this lane being sprayed
    proliferator_item_id: str
    proliferator_rate: Fraction       # items/s of proliferator this coater consumes
    is_external_lane: bool            # True if this lane is an external input belt
                                      # (coater is then ~free: the belt exists anyway)

@dataclass(frozen=True)
class BuildSpec:
    groups: tuple[MachineGroup, ...]
    external_inputs: Mapping[str, Fraction]   # item -> items/s entering on belts
    outputs: Mapping[str, Fraction]           # item -> items/s leaving on belts
    belt_item_id: str                         # from ibe, default conveyor-belt-1
    belt_speed: Fraction                      # items/s capacity of one belt lane
    surplus: Mapping[str, Fraction]           # unavoidable byproducts, items/s
    dataset_version: str
    lower_bound_area: Fraction                # LP relaxation, for bake-off scoring; loose,
                                              # since extraction columns count 0 area

    # --- proliferation / geometry contract (see §4.0) ---
    spray_lanes: tuple[SprayLane, ...]
    belt_required_edges: frozenset[tuple[str, str]]
        # (producer_recipe_id, consumer_recipe_id) pairs that MUST be belted because the
        # consumer is proliferated and needs this input sprayed. The layout stage may NOT
        # direct-insert these. Every other internal edge is free to direct-insert.
    label: str                 # e.g. "free-proliferation (k=0)"
    rationale: str             # one line: what this candidate optimises

@dataclass(frozen=True)
class BuildSpecSet:
    candidates: tuple[BuildSpec, ...]   # ordered; see §6.3 for ordering
    request: LabRequest

    def __post_init__(self):
        assert self.candidates, "at least one candidate required"
        # every candidate must satisfy the same objective
        assert len({tuple(sorted(c.outputs.items())) for c in self.candidates}) == 1
```

`belt_required_edges` is the load-bearing field: it is the *only* channel through which the
proliferation decision constrains the layout stage. A layout strategy that ignores it will
emit blueprints that paste cleanly and then under-produce in game, because machines it
direct-inserted are receiving unsprayed inputs while the rate model assumed sprayed ones.
**`layout/validate.py` must assert that no edge in `belt_required_edges` was direct-inserted.**

### 6.2 Invariants (asserted at construction)

1. Every `count ≥ 1`; no zero-machine groups.
2. Exact `Fraction` balance per item:
   `Σ outputs + external_inputs ≥ Σ inputs + outputs + surplus`, with equality on
   everything except declared `surplus`.
3. `0 < utilization ≤ 1` for every group.
4. No item appears in both `external_inputs` and any group's `outputs`
   (an item is either made here or belted in, never both).
5. `belt_speed == data.belt_speed(belt_item_id)`.
6. Every `recipe_id` is unique across groups **per mode** — a recipe may appear twice
   with different `proliferator_mode`, and consumers must handle that.

7. Every recipe with `proliferator_mode != NONE` has **all** its internal input edges listed
   in `belt_required_edges`, and every one of its input items appears in some `SprayLane`.
8. `Σ SprayLane.proliferator_rate == external_inputs[proliferator_item_id]` — the proliferator
   belt is sized to exactly what the coaters draw.
9. Every candidate in a `BuildSpecSet` produces the same `outputs` at the same rate.

Invariant 6 is the one most likely to be violated by downstream code that assumes
`{g.recipe_id: g for g in groups}`. Invariant 7 is the one whose violation is *invisible until
the factory is running*, which is why it is asserted rather than trusted.

### 6.3 Candidate generation — the proliferation frontier

Proliferating recipe `R` costs the direct-insertion freedom of every internal input edge of
`R` (§4.0). Partition the recipe set:

- **free recipes** — every input is external, so those inputs arrive on belts *anyway*.
  Spraying them forbids no direct insertion at all and reuses input belts that must exist.
- **costly recipes** — at least one input is produced inside the blueprint, so proliferating
  them converts a direct-insertable edge into a mandatory belt.

Candidates are generated by a single knob **k = the number of costly recipes permitted to
proliferate**. For each k, solve the §3.4 MILP restricted to that budget and keep the best.
k=0 is free-proliferation; k=|costly| is the unconstrained optimum of §4.3.

Measured on the example chain (11 internal edges, 4 free recipes, 5 costly):

| candidate | k | edges lost | edges kept | machines | area | coaters |
|---|---|---|---|---|---|---|
| `no-proliferator` | — | 0 | 11 | 58 | 683 | 0 |
| **`free-proliferation`** | **0** | **0** | **11** | **41** | **530** | **3** |
| `frontier-1` | 1 | 3 | 8 | 37 | 466 | 6 |
| `frontier-2` | 2 | 5 | 6 | 31 | 405 | 8 |
| `frontier-3` | 3 | 8 | 3 | 28 | 357 | 10 |
| `max-proliferation` | 5 | 11 | 0 | 26 | 325 | 11 |

Every row is Pareto-non-dominated in (area, edges kept) — the frontier is strictly monotone
in both, so no candidate can be dropped a priori.

**`free-proliferation` is the candidate to beat, and is emitted second (right after
`no-proliferator`).** It captures a 29% machine and 22% area reduction *at zero
direct-insertion cost*, and its three spray coaters sit on the iron-ore / copper-ore / coal
input belts that the blueprint must have regardless. Whether the remaining rows beat it
depends entirely on what a belted edge costs in tiles — a belt corridor plus two sorters
versus one sorter and two touching machines — which only the layout stage can price. Hence
the set.

**Default candidate list** (in emission order):

1. `no-proliferator` — maximum direct-insertion freedom, the geometric baseline.
2. `free-proliferation` (k=0) — the likely winner; free machine reduction.
3. `max-proliferation` (k=all) — minimum machine area, zero direct insertion.
4. `all-speed-mode` — every recipe in speed mode. Uniform, dodges the products
   `limitation` gate entirely (§4.2), and is the most predictable for a human to read.
   Worth emitting because it never fails the gate and gives the layout stage a candidate
   whose proliferator lane feeds a single mode.

Intermediate `frontier-k` rows fill in when `--candidates N` exceeds 4, chosen to spread
evenly across k.

### 6.4 Cost of candidates

**Candidates multiply layout solve time linearly** — the layout stage runs once per
candidate, and layout dominates total runtime (the rate MILP is milliseconds; CP-SAT
placement is seconds to minutes). Four candidates means roughly 4× the wall clock.

```
--candidates N     default: 3      (no-proliferator, free-proliferation, max-proliferation)
--candidates 1     rate stage picks free-proliferation only; fastest path
```

Default 3 rather than 4 because `all-speed-mode` is a robustness/legibility candidate rather
than a density one, and is rarely the area winner. Raise to 4+ when chasing density.

Candidates are independent, so the layout stage **may run them in parallel** — with enough
cores the wall-clock cost of extra candidates is close to zero. Recommend the bake-off
harness exploit this.

### 6.5 Rounding and over-production

Machine counts are integers **from the MILP**, not from ceiling an LP solution. The
`utilization` field records the resulting slack: the example's magnet group is
`count=6, utilization=0.94`, meaning six smelters each run at 94%.

Consequences to document for the user:

- The build **meets or exceeds** the requested rate; it never under-produces.
- Belts are sized on the **actual flow rates** (`x`), not machine capacity. In DSP steady
  state a machine whose output backs up throttles to consumption rate, so this is correct.
  During cold start machines run flat out briefly; that transient is not modeled.
- `--belt-margin FLOAT` (default 1.0) multiplies computed lane rates when sizing lanes, for
  users who want headroom.

A `--report` flag prints the per-group table (exact rate, machine count, utilization, mode)
so the numbers are auditable against FactorioLab's own flow view.

### 6.6 Explicitly out of scope for v1

- **Belt stacking / piling** (`beltStack` flag is present in the dataset). It multiplies
  lane throughput up to 4× with pile sorters and would meaningfully improve density, but
  it changes sorter selection and lane math throughout. Flag as the highest-value v2 item.
- Fuel chains (`mfr`) — DSP machines here are all `electric`; no burner producers appear in
  a normal chain. Power generation is not built.
- `Maximize` / `Limit` / `Input` objectives (§1.4).

---

## 7. Testing

### 7.1 Golden test — the example URL, no proliferator

`?o=super-magnetic-ring*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&mps=proliferator-2-products&v=11`

Reproduced exactly, in `Fraction`, by the reference implementation:

| recipe | machine | machines |
|---|---|---|
| super-magnetic-ring | assembling-machine-2 | 3 |
| electromagnetic-turbine | assembling-machine-2 | 4 |
| electric-motor | assembling-machine-2 | 8 |
| gear | assembling-machine-2 | 4 |
| magnetic-coil | assembling-machine-2 | 4 |
| iron-ingot | arc-smelter | 12 |
| copper-ingot | arc-smelter | 4 |
| magnet | arc-smelter | **33/2** |
| energetic-graphite | arc-smelter | 2 |

External inputs: `iron-ore 23/s`, `copper-ore 4/s`, `coal 2/s`.
Cross-check: 23 / (1 ore per 2 s) = **46 mining machines**, 4/0.5 = **8**, 2/0.5 = **4** —
matching FactorioLab's miner counts exactly, which validates the cut line.

Assert `magnet == Fraction(33, 2)` **as a Fraction**, not `16.5` as a float — this is the
test that catches any accidental float contamination.

### 7.2 Proliferator tests

- Mk.III products-only: 27.183 exact machines, `iron-ore` drops 23 → 9.457/s
  (demonstrates upstream compounding).
- Mk.III speed-only: 28.75 exact machines, `iron-ore` stays **23/s**
  (demonstrates speed-mode does *not* compound).
- Per-recipe optimum: 21.64 exact machines, 325 ceil-area tiles, 0.8293 proliferator/s.
- Assert products-mode is rejected for a speed-only recipe, e.g. `deuterium-fractionation`
  or `conveyor-belt-2`, and that the MILP silently falls back to speed there.

### 7.2b Candidate-set tests (§6.3)

- The example chain partitions into free `{iron-ingot, copper-ingot, magnet,
  energetic-graphite}` and costly `{super-magnetic-ring, electromagnetic-turbine,
  electric-motor, gear, magnetic-coil}`, with 11 internal edges. Assert exactly this.
- Assert the frontier reproduces the §6.3 table: `(k, machines, area)` =
  `(0,41,530) (1,37,466) (2,31,405) (3,28,357) (5,26,325)`, baseline `(—,58,683)`.
- Assert **Pareto monotonicity**: area strictly decreases and edges-kept strictly decreases
  as k rises. A violation means the MILP budget constraint is wrong.
- Assert `free-proliferation` has `belt_required_edges == frozenset()` — the defining
  property of that candidate. This is the single most important test in the section.
- Assert every candidate's `spray_lanes` for `free-proliferation` have
  `is_external_lane == True`.
- Assert invariant 7 on every candidate: no proliferated recipe has an internal input edge
  missing from `belt_required_edges`.
- Assert all candidates in a set produce identical `outputs`.

### 7.3 URL parsing tests

- Bare round-trip of the example URL.
- `z=` decode: build a payload with the custom alphabet and assert it inflates. Known-good
  fixtures exist in FactorioLab's `router-sync.spec.ts` (e.g. one decoding to `test=test`).
- Empty-field defaults: `o=iron-ingot**3` → `value=1, unit=MACHINES`.
- Trailing-separator stripping: `o=iron-ingot*60***` parses identically to `o=iron-ingot*60`.
- Truncated-URL repair: truncate a valid `z=` payload's padding and assert recovery.
- `v=9` → error whose message tells the user to re-copy from FactorioLab.
- `omt`/Maximize objective → clear rejection.

### 7.4 Property tests

- For 50 random target items across the dataset, assert the MILP is feasible and every
  exact-`Fraction` item balance holds.
- Assert `--proliferator none` machine counts are never *fewer* than any `mkN` run.
- Assert `--proliferator mk3` total area ≤ `mk1` total area (monotone in tier).
- Assert every `BuildSpec` invariant on every generated spec.

### 7.5 Hermeticity

All tests run against the **vendored** `dsp-data.json`. A single separately-marked test
(`@pytest.mark.network`) fetches the live dataset and asserts the vendored copy's version
still matches, so dataset drift is detected loudly rather than silently changing goldens.

---

## 8. Corrections to the briefing's assumptions

1. **`assembling-machine-1` speed is 0.75, not 1.** The briefing stated both asm-1 and
   asm-2 are speed 1 and that the example URL's `mmr` therefore causes "no numeric change".
   That is wrong: swapping asm-1 → asm-2 is a genuine 1.33× speedup and changes every
   assembler count in the example. (The stated expected counts are correct *for asm-2*.)

2. **Use the `mining` flag, not producer/`totalRecipe` heuristics** (§5). The proposed
   heuristic would have missed `oil-extractor`, `water-pump`, and `orbital-collector`
   recipes, since `totalRecipe` belongs only to the two mining-machine variants.

3. **Products-mode has a hard `limitation` gate** (§4.2) that the briefing did not mention.
   26 non-technology recipes cannot take products mode at all. Ignoring this would generate
   blueprints whose in-game machine counts are wrong — silently under-producing.

4. **Solve as a MILP, not "LP then ceil"** (§3.4). Measured: the objective actually matters,
   and the three plausible objectives disagree (339 / 330 / 325 tiles). "Minimize machine
   count then round up" is not the density optimum.

5. **Minimize footprint area, not machine count** (§3.4). Fewer machines can occupy more
   space, since arc-smelter is 9 tiles and assembler 16.

6. **`CompressionStream('deflate')` is zlib-wrapped, not raw deflate** (§1.1) — the briefing
   said "zlib" correctly but this is the most common implementation error, so it is pinned.

7. Spray counts 12/24/60 — **confirmed correct**.

8. The 7 multi-producer items and 2 joint-product recipes — **confirmed correct**, and they
   are the justification for keeping a real solver rather than a tree walk.

9. **Proliferator is consumed by spray coaters on belts, not by machines** (§4.0) — corrected
   in revision 2 after the Strategy A designer caught it. This is the most consequential
   correction in the document: it makes proliferation and direct insertion *competing* uses
   of the same edges rather than independent wins, converts the single "optimal" answer into
   the frontier of §6.3, and turns `BuildSpec` into `BuildSpecSet`. My revision-1 claim that
   per-recipe mode choice is worth 2.7× stands only as an upper bound on machine count.

10. **A correction to my own revision-1 framing.** In revision 1 I wrote that products-mode
    compounding "only pays when a recipe's inputs are produced internally", and treated that
    as a neat emergent insight. Under the corrected mechanic it is sharper and more useful
    than I realised: recipes fed *entirely from external inputs* are exactly the recipes that
    can be proliferated **for free**, because their inputs are belted by construction. The
    same partition that governs mode choice also governs geometric cost — which is what makes
    `free-proliferation` (§6.3) a principled candidate rather than a heuristic guess.

## 9. Open questions for the parent

**9.1 — Deviation from URL settings.** `--proliferator mk3` is the default per the user's
"most dense" directive, but it makes the generated build **deviate from the URL's own
settings** (the example URL resolves to no proliferator). The build still satisfies the
stated objective — 60 super-magnetic-ring/min. Recommend defaulting to `mk3` as instructed
and printing a one-line notice naming the candidate that actually won, e.g.
*"Proliferator Mk.III, free-proliferation candidate (58 → 41 machines, no direct-insertion
cost). Requires 0.48 proliferator-mk3/s on an input belt. Use --proliferator url to match
FactorioLab exactly."*

**9.2 — Partial spray semantics (blocking a finer model, not blocking v1).** §4.0 assumes a
recipe is proliferated only if *all* inputs are sprayed. If DSP actually grants a
proportional bonus from partially-sprayed inputs, the frontier gains intermediate points —
a recipe could proliferate only its belted inputs while direct-inserting the rest, which
would likely dominate several current candidates. The catalog agent has the game files and
can settle it from `AssemblerComponent`. v1 ships the conservative model either way.

**9.3 — Who prices an edge?** The frontier is only useful if the layout stage genuinely
prices a belted edge. If both layout strategies end up picking the same candidate on every
test URL, the candidate machinery is dead weight and should collapse back to
`free-proliferation` alone. Recommend the bake-off harness report **which candidate won per
URL per strategy**, so this is measured rather than assumed.
