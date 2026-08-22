# Design section — validator and bake-off harness

Covers `src/flab2bp/layout/validate.py` and `src/flab2bp/bench/`. These are the
*arbiter* of the project: two competing layout strategies (A = structured spine,
B = free-form pack-and-route) consume the same `BuildSpec` and emit the same
`Placement`, so every judgement about correctness and density must live outside
both of them.

Written against the frozen contract in `src/flab2bp/layout/base.py`.

---

## 0. Grounding facts established while writing this

Measured from the live FactorioLab DSP dataset and the viewer's decoder, not
assumed:

| Fact | Value | Source |
|---|---|---|
| Belt throughput | Mk.I 6/s, Mk.II 12/s, Mk.III 30/s | `data.json` `belt.speed` |
| Proliferator products mode | Mk.I +12.5%, Mk.II +20%, Mk.III +25% | `module.productivity` |
| Proliferator speed mode | Mk.I +25%, Mk.II +50%, Mk.III +100% | `module.speed` |
| Proliferator sprays | Mk.I 12, Mk.II 24, Mk.III 60 | `module.sprays` |
| Multi-producer items (LP-ambiguous) | `accumulator`, `hydrogen`, `refined-oil`, `organic-crystal`, `sulfuric-acid`, `deuterium`, `space-warper` | computed after `defaults.excludedRecipes` |
| Format cap: areas | `areaCount ≤ 64`, area `width`/`height` are i16 | `blueprint.ts:32` |
| Format cap: buildings | `0 ≤ buildingCount ≤ 1048576` | `blueprint.ts:51` |
| Format cap: parameters | `0 ≤ parameterCount ≤ 32768` | `building.ts:94` |

**On a DSP footprint cap:** I could not find any in-game limit on blueprint
extent beyond these format-level bounds. The real constraint is that DSP planets
are spheres — a blueprint wide in longitude distorts and eventually fails to
paste near the poles. That is not checkable offline, so `geom.bounds` enforces
only the format caps and emits a `WARNING` above a configurable soft width
(default 256 tiles) noting the wrapping risk. Flagged in §4.

---

## 1. The validator

### 1.1 Finding datatype

Checks return structured findings, never bare booleans, so a failure is
debuggable from the report alone.

```python
class Severity(StrEnum):
    ERROR = "error"      # the blueprint is wrong; must not ship
    WARNING = "warning"  # legal but suspect (e.g. wrapping risk, slack capacity)
    INFO = "info"        # informational metrics for the bench

@dataclass(frozen=True, slots=True)
class Finding:
    check: str                        # stable dotted id, e.g. "flow.belt_capacity"
    severity: Severity
    message: str                      # human-readable, names the actual numbers
    buildings: tuple[int, ...] = ()    # indices into Placement.buildings
    detail: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class Report:
    findings: tuple[Finding, ...]
    @property
    def ok(self) -> bool: ...          # no ERROR findings
    def by_check(self, check: str) -> tuple[Finding, ...]: ...
```

`detail` carries the numbers behind the claim (`{"lane": 7, "flow": "37/2",
"capacity": "12"}`) with `Fraction` values rendered as exact strings. Never
format a rate as a float in a finding — rounding is what these checks exist to
catch.

### 1.2 Check registry

Every check is a standalone function with the same signature, registered by id.
This is what makes them individually testable: a unit test constructs a tiny
`Placement` exhibiting one defect and asserts exactly one check fires.

```python
Check = Callable[[ValidationContext], Iterable[Finding]]
CHECKS: dict[str, Check] = {}

def check(cid: str) -> Callable[[Check], Check]:  # decorator, registers into CHECKS
    ...

def validate(placement, spec, catalog, *, only=None, soft_width=256) -> Report:
    ctx = ValidationContext.build(placement, spec, catalog, soft_width=soft_width)
    return Report(tuple(f for cid, c in CHECKS.items()
                        if only is None or cid in only
                        for f in c(ctx)))
```

`ValidationContext` is built once and shared, so no check pays to rederive
indices:

```python
@dataclass(frozen=True)
class ValidationContext:
    placement: Placement
    spec: BuildSpec
    catalog: Catalog                       # footprints, sorter reach/rates, belt rates
    occupancy: Mapping[tuple[int,int,int], int]   # cell -> building index
    kind: Sequence[BuildingKind]           # per building: MACHINE | BELT | SORTER | OTHER
    belt_runs: Sequence[BeltRun]           # maximal forward-linked belt chains
    run_of: Mapping[int, int]              # belt building index -> run index
    sorters_of: Mapping[int, list[int]]    # machine index -> attached sorter indices
    soft_width: int
```

`BuildingKind` is derived from the id-range predicates (belts 2001–2009,
sorters 2011–2019, splitter 2020, everything else a machine or "other"), so the
validator never needs to special-case individual buildings.

### 1.3 Geometry checks

| id | Severity | Statement |
|---|---|---|
| `geom.overlap` | ERROR | No two buildings' footprint tiles share a cell at the same `z`. Reports both indices and the colliding cell. |
| `geom.belt_single_occupancy` | ERROR | At most one belt per `(x, y, z)`. Redundant with `geom.overlap` for correctness but reported separately because it is the failure a router produces, and a distinct id makes the bench's failure histogram readable. |
| `geom.bounds` | ERROR / WARNING | ERROR if `len(buildings) > 1_048_576`, if any area dimension exceeds i16, or if `parameters` exceeds 32768 on any building. WARNING if bounding-box width or height exceeds `soft_width` (planet-wrapping risk). |
| `geom.machine_ground` | ERROR | Machines sit at `z == 0`. Only belts (and the sorters bridging to them) may occupy `z > 0`. |
| `geom.altitude_step` | ERROR | Consecutive tiles in a belt run differ by at most one altitude level, and a level change accompanies a horizontal step (no vertical teleports). This is the ramp-legality rule for stacked belts. |
| `geom.altitude_range` | ERROR | `0 <= z <= MAX_BELT_ALTITUDE` (catalog constant). |

### 1.4 Sorter checks

| id | Severity | Statement |
|---|---|---|
| `sorter.reach` | ERROR | The axis-aligned span between a sorter's two anchors is within its tier's reach. DSP sorters are straight-line, so the check is: the two anchors share a row or column, and the span is `≤ reach(tier)`. A diagonal pair is an ERROR regardless of distance. |
| `sorter.anchors_present` | ERROR | `x2`/`y2`/`z2` are all set (not `None`) on every sorter. The contract lets them be `None` for non-sorters; a sorter missing its second anchor is a strategy bug. |
| `sorter.endpoints` | ERROR | Both anchors land on an occupied cell that is either a machine footprint tile or a belt tile. Reports which end is dangling. |
| `sorter.endpoint_pair` | ERROR | The two ends are not on the same belt run (a no-op sorter), and `input_obj` / `output_obj` name exactly the buildings the anchors sit on. |
| `sorter.direction` | ERROR | `input_obj` is where it picks up, `output_obj` where it puts down — assert consistency with the item's direction of travel implied by the recipe graph (a sorter feeding a machine must carry an input of that machine's recipe; one draining a machine must carry an output). |
| `sorter.filter` | WARNING | Where a sorter draws from a lane carrying a single item, `filter_id` should be either 0 or that item. A mismatch is almost always a bug. |

### 1.5 Belt checks

| id | Severity | Statement |
|---|---|---|
| `belt.link_adjacent` | ERROR | A belt's `output_obj` names a building whose footprint is orthogonally adjacent to it (allowing the one-level altitude step from `geom.altitude_step`). |
| `belt.continuity` | ERROR | Following `output_obj` from any belt reaches either another belt or a non-belt consumer; no link points into empty space. Belt chains are forward-linked only, matching what the game emits, so `input_obj` being `-1` is expected and never reported. |
| `belt.termination` | ERROR | Every run ends at a consumer, a splitter, or a boundary tile declared in `spec` as an external output. A run that just stops is reported with its tail index. |
| `belt.acyclic` | ERROR | No cycles. (A deliberate sushi loop would be legal DSP but no strategy here emits one; if that changes, downgrade to WARNING behind a flag rather than deleting the check.) |
| `belt.single_item` | ERROR | Each run carries exactly one item id. **This check is load-bearing for §1.7** — it is what makes the throughput problem decompose into independent single-commodity flows. |

### 1.6 Machine / spec-conformance checks

| id | Severity | Statement |
|---|---|---|
| `machine.recipe_valid` | ERROR | `recipe_id` is non-zero for every production machine and names a recipe that this machine type can actually produce (`recipe.producers` contains it). |
| `machine.inputs_supplied` | ERROR | For every ingredient of a machine's recipe, at least one sorter delivers that item into it. |
| `machine.output_removed` | ERROR | For every product, at least one sorter (or direct insertion) removes it. |
| `spec.machine_counts` | ERROR | The multiset of `(recipe_id, machine_item_id)` in the placement equals what `BuildSpec` demanded. Guards against a strategy silently dropping a machine it could not place. |
| `spec.external_io` | ERROR | Every external input item in `BuildSpec` has a boundary belt run that sources it, and the target output has a run that leaves the bounding box. |
| `spec.proliferator_input` | ERROR | If any machine is sprayed, `proliferator-N` appears as an external input with a belt sized for it — the user's explicit requirement that proliferator is belted in, never produced inside. |

### 1.7 Throughput checks — the rigorous part

This is the "throughput-correct" guarantee, so it is a real flow computation in
exact `Fraction` arithmetic, not a spot check.

**The decomposition.** `belt.single_item` guarantees each belt run carries one
item. Therefore the multi-commodity flow problem separates into one independent
**single-commodity** flow problem per item id. That is the whole reason the
check can be both rigorous and fast — general multi-commodity integral flow
would be NP-hard; this is a sequence of ordinary max-flow feasibility instances.

**Per-item flow network.** For item `i`, build a digraph:

- **Source** `S_i` → each producer machine, capacity = that machine's production
  rate of `i` from `BuildSpec` (exact `Fraction`).
- **Source** `S_i` → each external input port for `i`, capacity = the declared
  external rate.
- **Machine → sorter** edge for each sorter draining that machine, capacity =
  `sorter_rate(tier, span)` from the catalog.
- **Sorter → belt-run** edge, capacity = the same sorter rate.
- **Belt-run node split**: each run becomes `run_in → run_out` with capacity =
  `belt_rate(tier)`. Splitting the node is what enforces the lane capacity; a
  plain edge would let a run carry unlimited flow through a junction.
- **Run → run** edges where runs join, capacity = `belt_rate(tier)`.
- **Belt-run → sorter → machine** edges for consumers, capacity = sorter rate.
- Each consumer machine → **sink** `T_i`, *lower bound* = the rate that
  machine's recipe demands for `i`.
- External output port → `T_i`, lower bound = the target output rate.

Feasibility with lower bounds reduces to a standard max-flow via the usual
supersource/supersink transformation. Solve with exact `Fraction` capacities —
integer/rational max-flow (Dinic's) terminates exactly and needs no LP.

**Checks derived from it:**

| id | Severity | Statement |
|---|---|---|
| `flow.feasible` | ERROR | The per-item flow instance is feasible. Infeasibility means some machine cannot be fed at its demanded rate. The finding names the item, the deficit as an exact `Fraction`, and the min-cut edges — which is precisely the bottleneck to report to the user. |
| `flow.belt_capacity` | ERROR | Reported as part of the min cut when a run is saturated: the run's required flow exceeds `belt_rate(tier)`. Names the run, its item, required vs capacity. |
| `flow.sorter_capacity` | ERROR | Same, for a sorter edge: required flow exceeds `sorter_rate(tier, span)`. |
| `flow.machine_feed` | ERROR | A consumer's lower bound is unmet. |
| `flow.conservation` | ERROR | Independently of the max-flow: total production minus total consumption of each intermediate item equals zero, and the boundary items match `BuildSpec`. A cheap arithmetic cross-check that catches spec-vs-placement drift the flow model would rationalise away. |
| `flow.headroom` | INFO | Per run and per sorter, `flow / capacity` as an exact fraction. Feeds the bench's density-vs-slack reporting and makes near-saturation visible before it becomes a bug. |

**Deliberately not checked:** *starvation ordering* — whether machines early on
a shared lane can starve later ones. The user chose "throughput-correct" over
"throughput-correct + no starvation", so a single lane tapped in series is
accepted as long as aggregate capacity suffices. `flow.headroom` at INFO makes
the risk visible without failing the build. If that choice is revisited, the
extension is per-tap sequential capacity accounting, not a new framework.

### 1.8 Testing the validator

Each check gets a focused test constructing a minimal `Placement` with exactly
one defect, asserting exactly that check fires and no other. Plus:

- **Negative control**: the 11 real game blueprints in `tests/fixtures/*.txt`,
  decoded into `Placement`s, must pass `geom.overlap` and `geom.belt_*`. Real
  blueprints are known-good, so any firing there is a validator bug (or, more
  usefully, a footprint-table bug — this is the same signal the catalog work
  relies on).
- **Property test**: for a randomly generated valid spine layout, all checks
  pass; for the same layout with one building nudged by one tile, at least one
  ERROR fires.

---

## 2. The bake-off harness

### 2.1 Corpus

Twelve URLs, chosen by measuring the real recipe graph rather than guessing —
spanning 1 → 955 machines and 1 → 42 distinct recipes, with five entries whose
trees touch the LP-ambiguous multi-producer items (oil / hydrogen chains).
Machine counts below are computed at the stated rate with the default rank
`arc-smelter~assembling-machine-2~chemical-plant~matrix-lab`, ceiling-rounded,
mining excluded.

| # | Tier | Target | Rate/min | Recipes | Machines | Notes |
|---|---|---|---|---|---|---|
| 1 | trivial | `iron-ingot` | 60 | 1 | 1 | degenerate case; one smelter |
| 2 | trivial | `magnetic-coil` | 60 | 3 | 4 | smallest real tree |
| 3 | small | `graphene` | 60 | 3 | 6 | |
| 4 | small | `electromagnetic-matrix` | 60 | 6 | 9 | red science |
| 5 | small | `plastic` | 60 | 4 | 11 | **oil chain, MULTI** |
| 6 | mid | `processor` | 60 | 6 | 21 | three raw inputs |
| 7 | mid | `energy-matrix` | 60 | 4 | 22 | **MULTI**, hydrogen byproduct |
| 8 | mid | `super-magnetic-ring` | 60 | 9 | 58 | **the user's own example URL** |
| 9 | large | `casimir-crystal` | 60 | 9 | 99 | **MULTI** |
| 10 | large | `information-matrix` | 60 | 17 | 101 | **MULTI**, 5 raw inputs |
| 11 | stress | `quantum-chip` | 60 | 20 | 300 | |
| 12 | stress | `universe-matrix` | 60 | 42 | 955 | **MULTI**, deepest real chain (d=9) |

The literal URLs (`URL_CORPUS` in `bench/corpus.py`), all ZipVersion 11:

```
https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=magnetic-coil*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=graphene*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=electromagnetic-matrix*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=plastic*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=processor*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=energy-matrix*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&mps=proliferator-2-products&v=11
https://factoriolab.github.io/dsp/list?o=casimir-crystal*60&ibe=conveyor-belt-3&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=information-matrix*60&ibe=conveyor-belt-3&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=quantum-chip*60&ibe=conveyor-belt-3&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11
https://factoriolab.github.io/dsp/list?o=universe-matrix*60&ibe=conveyor-belt-3&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11
```

Entries 9–12 use Mk.III belts and 11–12 use the faster machine rank, both to
keep the stress cases physically buildable and to exercise the belt-tier and
machine-speed paths rather than testing one configuration twelve times.

Corpus URLs are **frozen fixtures**: `BuildSpec`s are computed once and cached
to `tests/fixtures/specs/*.json`, so a change in the upstream FactorioLab
dataset cannot silently move the bench's baseline. A `--refresh` flag
regenerates them deliberately.

### 2.2 Metrics

Per `(strategy, url)`:

```python
@dataclass(frozen=True, slots=True)
class BenchResult:
    strategy: str
    url_id: str
    # density
    area: int                 # Placement.area — the headline number
    used_tiles: int           # occupied cells; area/used_tiles = packing efficiency
    width: int
    height: int
    # composition
    machines: int
    belt_tiles: int
    sorters: int
    direct_inserts: int       # sorters with both ends on machines
    altitude_levels: int      # max z used
    # cost
    solve_seconds: float
    hit_time_budget: bool
    solver_status: str        # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN
    # correctness
    valid: bool
    errors: int
    warnings: int
    findings: tuple[Finding, ...]
```

`area` is the headline density metric because it is what actually costs planet
surface. `used_tiles / area` is reported alongside it so a strategy that wins on
bounding box purely by being a long thin ribbon is visible as such.

### 2.3 Reporting

Two artefacts, written to `bench/results/`:

- `results.json` — the full `list[BenchResult]`, machine-readable, the input to
  regression checking.
- `report.md` — a markdown table per tier plus a summary, printed to stdout too.

```
| target                 | machines |  A area |  B area | B/A  | A time | B time | A ok | B ok |
|------------------------|---------:|--------:|--------:|-----:|-------:|-------:|:----:|:----:|
| iron-ingot             |        1 |      12 |      12 | 1.00 |  0.01s |  0.02s |  ok  |  ok  |
| super-magnetic-ring    |       58 |     682 |     611 | 0.90 |  1.2s  | 47.3s  |  ok  |  ok  |
| universe-matrix        |      955 |   11284 |       — |   —  | 38.1s  | 300s   |  ok  | FAIL |
```

### 2.4 Declaring a winner

A single number, computed only over URLs where **both** strategies produced a
valid placement:

```
score(B vs A) = geometric_mean(area_B / area_A)
```

Geometric mean, not arithmetic — area ratios are multiplicative, and one
enormous stress case must not dominate twelve results.

Decision rule, in order:

1. **Validity first.** A strategy that fails to produce a valid placement on
   more corpus entries than the other loses outright, regardless of area. A
   dense invalid blueprint is worth nothing.
2. **Density.** If validity ties, the lower geometric-mean area wins, but only
   if the margin exceeds **3%** — below that the strategies are declared
   equivalent on density and the tie-break moves on.
3. **Time.** On a density tie, the strategy with lower median solve time wins.
4. **Scaling.** Reported but not scored: the largest corpus entry each strategy
   solves within budget. Called out in prose because it decides which strategy
   is usable on real factories even if it loses on the mean.

The rule is deliberately lexicographic rather than a weighted sum — a weighted
sum invites tuning the weights until the preferred answer wins.

### 2.5 Determinism and fairness

CP-SAT is the main threat to a meaningful comparison, since it is
nondeterministic across runs by default.

- **Workers are NOT pinned.** *(Superseded — this section originally required
  `num_search_workers = 1` in bench mode.)* Pinning was rejected once it was
  measured: single-worker search does not merely run slower, it lands on
  materially worse layouts. On the magnetic-ring spec, 8 workers reach area 1435
  where 1 worker plateaus at 1885 — 23% worse. Parallel CP-SAT runs a portfolio
  of differing strategies, so extra workers explore genuinely different regions
  rather than racing to the same answer.

  Pinning would therefore have made the bake-off reproducible *and wrong*: it
  would compare two strategies under a configuration neither would ever ship.
  Solves now take ~1s rather than ~15s, so run-to-run variance costs little to
  absorb directly: **repeat each cell and report the median and spread** instead
  of forcing a single deterministic sample. That measures the nondeterminism
  rather than hiding it.
- **`random_seed`** fixed (default 0) and recorded in `results.json`.
- **Identical `BuildSpec`** — computed once per URL and handed to both
  strategies, never recomputed per strategy.
- **Identical `time_budget_s`**, scaled by tier (trivial/small 10s, mid 60s,
  large 120s, stress 300s) and recorded per result.
- **Wall-clock caveat**: `solve_seconds` is measured but explicitly *not* used
  for the primary ranking, because it is the least reproducible number in the
  report. It only ever breaks a density tie.
- **`--repeat N`** runs each cell N times and reports the spread; if area varies
  at all across repeats with a fixed seed and single worker, that is a bug in
  the strategy's determinism and the harness says so loudly.

### 2.6 Regression use

After the bake-off picks a winner, the same harness guards it:

- `bench/baseline.json` records the winning strategy's area per corpus entry.
- `uv run flab2bp-bench --check` fails if any entry's area exceeds its baseline
  by more than **2%**, or if any entry that was valid becomes invalid (zero
  tolerance — validity never regresses).
- An area *improvement* beyond 2% prints a notice to re-baseline; it does not
  fail. Re-baselining is an explicit `--bless` step so improvements are recorded
  deliberately.
- The stress tier is marked `slow` and excluded from the default CI run; CI runs
  tiers trivial→mid, and the full corpus runs nightly.

---

## 3. Cross-validation against the viewer's decoder

The user asked that generated blueprints be checked by the independent
TypeScript decoder at `/Users/dannyb/sources/dsp-blueprint-viewer`. That repo is
a genuinely independent implementation, so it catches encoder bugs our own
Python decoder would share by construction.

### 3.1 The bridge script

`scripts/crossvalidate.ts` in *our* repo, run by `bun`, importing the viewer's
parser by absolute path:

```ts
import { parseBlueprint } from `${VIEWER}/src/format/index`;
// stdin:  one blueprint string per line
// stdout: one JSON object per line
```

For each input line it emits:

```json
{"ok": true, "hashValid": true, "buildings": 143, "areas": 1,
 "version": 1, "itemIds": {"2303": 58, "2002": 71, "2013": 14},
 "bounds": {"minX": -12.5, "maxX": 11.5, "minY": -8.5, "maxY": 9.5}}
```

or `{"ok": false, "error": "..."}` on a parse failure.

Bun runs the viewer's TypeScript directly — no build step — and the viewer
already has `node_modules` installed (confirmed present), with `fflate` as its
only decode-path dependency.

### 3.2 What the Python side asserts

`tests/dsp/test_crossvalidate.py` encodes each bench corpus entry plus the 11
real fixtures, pipes them through the bridge in one batch (one subprocess for
the whole set, not one per blueprint), and asserts:

- `ok is True` and `hashValid is True` — the independent implementation accepts
  our MD5F.
- `buildings` equals our building count.
- `itemIds` histogram equals ours — catches item/model id mix-ups that a bare
  count would miss.
- `bounds` matches our expected extent after the tile→`localOffset` conversion.
  **This is the check that independently pins the centre-vs-corner convention**,
  which is otherwise the most likely silent encoder bug.

### 3.3 Skipping cleanly

The viewer is a sibling checkout, not a dependency. Resolution order for its
path: `$DSP_VIEWER_PATH` → `../dsp-blueprint-viewer` relative to the repo root.

```python
viewer_available = pytest.mark.skipif(
    not _viewer_path() or not shutil.which("bun"),
    reason="cross-validation needs `bun` and a dsp-blueprint-viewer checkout "
           "(set DSP_VIEWER_PATH)",
)
```

Skip, never fail — CI without the sibling repo must stay green. The skip reason
names exactly what is missing and how to fix it. A `--strict-crossvalidate` flag
turns the skip into a failure for the one environment where it is guaranteed
present.

---

## 4. Things I could not make rigorous

Called out honestly rather than papered over:

1. **Sorter reach and throughput constants.** I specified the *interface*
   (`catalog.sorter_reach(tier)`, `catalog.sorter_rate(tier, span)`) but not the
   values — those come from the game-asset extraction happening in parallel.
   `sorter.reach` and `flow.sorter_capacity` are only as correct as that table.
   If the rate turns out to depend on more than `(tier, span)` — e.g. on cargo
   stacking — the interface needs a third parameter and the flow edges change.

2. **In-game footprint cap.** Only format-level caps are enforceable offline.
   The real limit is planet curvature, which depends on the paste latitude and
   cannot be validated from a blueprint string alone. `geom.bounds` therefore
   warns rather than errors above the soft width, and the number (256) is a
   judgement call, not a measured limit.

3. **Direct-insertion legality.** Whether a given machine face accepts a sorter
   from an adjacent machine is game data I do not have. `sorter.endpoints`
   currently accepts any machine footprint tile. If DSP restricts insertion to
   specific faces, this check is too permissive and will let a strategy emit
   blueprints that paste but do not run — the most dangerous failure mode in the
   whole design, because it is invisible until you are in-game. **Recommend
   resolving this before trusting either strategy's output.**

4. **Starvation ordering** — deliberately out of scope per the user's choice of
   "throughput-correct" over "throughput-correct + no starvation" (§1.7).

5. **Power.** Nothing here checks that the build has power poles or sufficient
   generation. `BuildSpec` does not currently carry power, and the user's scope
   ("ingredients belted in") did not mention it. Worth an explicit decision:
   a factory with no tesla towers is throughput-correct on paper and dead in
   game.
