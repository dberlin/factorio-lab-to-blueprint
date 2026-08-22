# DSP Ground-Truth Catalog — footprints, slots, power, throughput

Sources: game install `/Users/dannyb/Downloads/Dyson Sphere Program` (Unity 2022.3.62f3c1,
assets ≈ 0.10.34+); `Assembly-CSharp.dll` disassembled with `ikdasm` → `asm.il` (2.2M lines);
11 real blueprint fixtures in `dsp-blueprint-viewer/tests/fixtures/` (13,690 buildings decoded).

Machine-readable outputs in this directory:

| file | contents |
|---|---|
| `dsp_building_table.json` | **primary deliverable** — 61 buildings: itemId, modelIndex, blueprintBoxSize, integer footprint, slots, power, addon/multiLevel flags |
| `footprints.json` | raw `blueprintBoxSize` extraction + all trigger boxes per prefab |
| `slots_power.json` | slot poses, PowerDesc, InserterDesc, BeltDesc, SplitterDesc, SpraycoaterDesc |
| `build_condition_config.json` | all 61 raw `BuildConditionConfig` records |
| `bpdecode.py` | standalone stdlib blueprint decoder used for all validation |
| `extract_footprints.py`, `extract_slots_power.py`, `probe_*.py` | extraction scripts (`uv run`) |

---

## 1. Build-grid footprints — derivation

**The authoritative field is `PrefabDesc.blueprintBoxSize`.** From `PrefabDesc::ReadPrefab`
(`asm.il` IL_10a4–IL_112f):

```csharp
blueprintBoxSize = new Vector2(buildCollider.ext.x * 2, buildCollider.ext.z * 2);
if (bcc.blueprintBoxSizeOverride.x >= 0.25f) blueprintBoxSize.x = bcc.blueprintBoxSizeOverride.x;
if (bcc.blueprintBoxSizeOverride.y >= 0.25f) blueprintBoxSize.y = bcc.blueprintBoxSizeOverride.y;
```

`buildCollider` is selected at IL_0213–IL_027a as the first collider with
`usage == Build(1) && shape == Box(3)`. From `ColliderData::InitFromCollider` (IL_0000–IL_002d):

```csharp
usage  = !collider.isTrigger ? Physics(0) : (independent ? Through(2) : Build(1));
idType = (usage << 29) | (shape << 24);
ext    = BoxCollider.size * lossyScale * 0.5;
```

So **`blueprintBoxSize` = the world-space (x, z) size of the first *trigger* BoxCollider on the
prefab**, per-axis overridden by `BuildConditionConfig`. All 61 `blueprintBoxSizeOverride` values
in this build are `(0,0)`, so every value below comes from the collider.

**Integer footprint = round-half-up(blueprintBoxSize).** Validated in §2.

> Dead ends, recorded so they are not retried: `ItemProto` has **no** size field; `ModelProto` has
> no size field; `BuildConditionConfig.landPoints` is a 4-corner terrain-flattening hull that is
> *not* on the build grid (Matrix Lab ±2.8, Depot ±1.45) — do not use it as a footprint;
> `SlotConfig.selectSize` (what `dsp-blueprint-viewer/models.json` ships) is the click volume and
> is consistently larger than the build box.

### Production buildings

| Building | itemId | modelIndex | blueprintBoxSize | **footprint** | slots | notes |
|---|---|---|---|---|---|---|
| Arc Smelter | 2302 | 62 | 2.90 × 2.90 | **3×3** | – | |
| Plane Smelter | 2315 | 194 | 2.90 × 2.90 | **3×3** | – | |
| Negentropy Smelter | 2319 | 457 | 2.90 × 2.90 | **3×3** | – | |
| Assembling Machine Mk.I | 2303 | 65 | 3.82 × 3.82 | **4×4** | – | |
| Assembling Machine Mk.II | 2304 | 66 | 3.82 × 3.82 | **4×4** | – | |
| Assembling Machine Mk.III | 2305 | 67 | 3.82 × 3.82 | **4×4** | – | |
| Re-composing Assembler | 2318 | 456 | 3.82 × 3.82 | **4×4** | – | |
| Chemical Plant | 2309 | 64 | 8.20 × 4.50 | **8×5** | – | |
| Quantum Chemical Plant | 2317 | 376 | 8.20 × 4.50 | **8×5** | – | |
| Oil Refinery | 2308 | 63 | 3.51 × 7.20 | **4×7** | – | |
| Matrix Lab | 2901 | 70 | 5.60 × 5.60 | **6×6** | – | stacks, `multiLevel` |
| Self-evolution Lab | 2902 | 455 | 5.60 × 5.60 | **6×6** | – | stacks |
| Miniature Particle Collider | 2310 | 69 | 9.60 × 5.56 | **10×6** | – | |
| Fractionator | 2314 | 119 | 4.50 × 4.50 | **5×5** | 3 | slot-restricted |
| Spray Coater | 2313 | 120 | 0.70 × 2.00 | **1×2** | – | belt addon, `addonType=1` |
| Storage Tank | 2106 | 121 | 4.50 × 4.50 | **5×5** | 4 | slot-restricted |
| Splitter | 2020 | 38 | 2.38 × 1.25 | **2×1** ⚠ | 4 | see §7 |
| Depot Mk.I | 2101 | 51 | 3.00 × 3.00 | **3×3** | – | |
| Depot Mk.II | 2102 | 52 | 5.85 × 3.90 | **6×4** | – | |
| Planetary Logistics Station | 2103 | 49 | 5.50 × 8.00 | **6×8** ⚠ | 12 | see §7 |
| Interstellar Logistics Station | 2104 | 50 | 10.00 × 10.00 | **10×10** | 12 | |
| Mining Machine | 2301 | 57 | 3.02 × 6.10 | **3×6** | 1 | needs ore vein |
| Advanced Mining Machine | 2316 | 256 | 11.30 × 5.47 | **11×5** | 9 | |
| Oil Extractor | 2307 | 61 | 6.00 × 11.60 | **6×12** | 1 | needs oil seep |
| Water Pump | 2306 | 60 | 2.40 × 6.00 | **2×6** | 1 | |

Belts (2001/2002/2003, model 35/36/37) and sorters (2011–2014, model 41/42/43/483) occupy
**1×1** per tile. Their `blueprintBoxSize` is degenerate (sorters 0.52 × 0.23) because they are
placed by endpoint, not by box — do not feed them through the footprint path.

Power/utility and combat buildings are in `dsp_building_table.json`; a few of note:
Tesla Tower 2201 **1×1**, Wireless Power Tower 2202 **1×1**, Satellite Substation 2212 **7×7**,
Solar Panel 2205 **4×4**, Wind Turbine 2203 **3×3**, Accumulator 2206 **3×3**,
Energy Exchanger 2209 **12×12**, Artificial Star 2210 **6×9**, Ray Receiver 2208 **9×5**.

---

## 2. Validation against real blueprints

Decoded all 10 factory fixtures (the 11th is `DYBP:`, a Dyson-sphere blueprint, correctly
rejected). 13,690 buildings; every fixture parsed to exactly the declared byte length.

**Method.** Minimum center-to-center spacing between same-type, same-altitude, same-orientation
neighbours in a row/column is an upper bound on the footprint; where builders pack tightly it
equals it.

| Building | predicted | observed min spacing | verdict |
|---|---|---|---|
| Arc / Negentropy Smelter | 3 | **3.00** (88 x-pairs, 85 y-pairs) | ✅ exact |
| Assembling Machine Mk.I | 4 | **4.00** (29 pairs) | ✅ exact |
| Assembling Machine Mk.III | 4 | **4.00** (186 pairs) | ✅ exact |
| Matrix Lab | 6 | **6.00** in 0.10.28 fixtures | ✅ exact |
| Depot Mk.I | 3 | 3.00 | ✅ |
| Interstellar Logistics Station | 10 | 40 (loose) | consistent, not tight |

**Two apparent contradictions were investigated and both are artifacts, not table errors:**

1. **Matrix Lab at spacing 5.** Comes only from `12-s-purple-…`, header gameVersion
   **0.8.19.7662**. The two 0.10.28 fixtures containing labs both show spacing **6.00**, matching
   `round(5.6)`. The lab was resized between 0.8 and 0.10. *Consequence: fixtures spanning
   0.8.19 → 0.10.34 must not be pooled when validating geometry.*
2. **Solar Panel at spacing 0.075–3.** All 663 such pairs come from
   `factory-full-planet-wind-ready-for-solar`, a whole-planet blueprint whose x is longitude in
   **latitude-compressed grid units** (observed x-steps of 4.0 at y=8 but 1.8 at y=17). Polar and
   whole-planet blueprints are not on a uniform grid and are excluded from geometric validation.

A blanket pairwise overlap test using raw float `blueprintBoxSize` over mixed-version fixtures
reports 280 violations / 39,862 pairs, concentrated in Tesla Tower, Energy Exchanger, ILS and
Matrix Lab — i.e. exactly the version-skew and loose-box cases above. **Recommended regression
test for this project: run the overlap check only over the 0.10.x fixtures
(`factory-heretical-smelter-block`, `factory-endgame-distribution-hub`,
`factory-quick-start-step-1/3`), using integer footprints.** That subset is clean.

---

## 3. Coordinate convention (high confidence)

- `localOffset` is `(x, y, z)` with **z = altitude**; x/y are planet-grid units.
- `localOffset` is the building **CENTER**, not a corner.
- On normal (non-polar) blueprints, machine centers are **exact integers** — 100.0% of
  non-sorter buildings in `12-s-purple`, `quick-start-step-1`, `temple-of-effectiveness`, and
  99.8% in `falk-v7-mall`. This holds for both odd (3×3 smelter) and even (4×4 assembler)
  footprints in the *same* blueprint, so DSP does **not** offset even-sized buildings to
  half-integers: a W×H building at integer center `(cx, cy)` covers `[cx-W/2, cx+W/2] ×
  [cy-H/2, cy+H/2]`.
- **Encoder rule:** emit integer x/y for machines. A 4×4 at x=3 and a 3×3 at x=0 do not
  collide (spans `[1,5]` and `[-1.5,1.5]`); the two parities live on interleaved half-grids and
  that is normal and correct.
- Sorters are the exception — their x/y are interpolated endpoints and are routinely fractional
  (e.g. 0.8055). Do not integer-snap sorters.
- **Polar / whole-planet blueprints break the uniform grid.** Latitude bands re-segment longitude
  (`BlueprintArea.areaSegments` 4 → 200 across bands), so x units are not comparable across
  bands. This generator should emit a single equatorial area and stay well inside one band.

## 4. Yaw convention (high confidence, from 0.10.x fixtures)

| class | observed yaws |
|---|---|
| machines | `0` (503), `180` (32) — essentially always axis-aligned; 90/270 legal but rare |
| belts | `270` (2990), `90` (1268), `180` (384), `0` (299) |
| sorters | `180` (440), `0` (383), `270` (35), `90` (29) |

Yaw is degrees; the viewer maps `yawRad = -yaw * π/180` and world `(x, z, -y)`.
**Belt yaw is not authoritative for direction** — the game zeroes it on serialize for belts and
direction comes from the `outputObjIdx` chain. For a 90°/270° rotated machine, swap W and H.

---

## 5. Machine I/O slots — *answers the highest-priority question*

**Finding: production machines have NO slot restrictions.** `SlotConfig.slotPoses` is empty for
Arc/Plane/Negentropy Smelter, all four Assemblers, Chemical Plant, Quantum Chemical Plant, Oil
Refinery, Matrix Lab, Self-evolution Lab, Miniature Particle Collider, and both Depots.

Only these buildings define slots (root-local x/z and facing, full data in `slots_power.json`):

| Building | slots | geometry |
|---|---|---|
| Planetary / Interstellar Logistics Station | 12 | 3 per side at ±1.26, 0 offset, on a ±2.70 ring |
| Advanced Mining Machine | 9 | 3 per side on a ±1.80 ring |
| Splitter | 4 | one per side at ±0.25 |
| Storage Tank | 4 | one per side at ±1.40 |
| Energy Exchanger | 4 | one per side at ±2.85 |
| Fractionator | 3 | `(0,+1.40)`, `(+1.40,0)`, `(−1.40,0)` — **no −z slot** |
| Ray Receiver | 2 | `(0,±1.41)` |
| Automatic Piler | 2 | `(0,±0.25)` |
| Mining Machine / Oil Extractor / Water Pump | 1 | single output |

**Validation.** Of the 1,335 machine-side sorter endpoints across all fixtures, the target
buildings were: Assembling Machine Mk.III 648, Negentropy Smelter 200, Assembling Machine Mk.I
197, Depot Mk.I 99, Artificial Star 88, Matrix Lab 47, Oil Refinery 36, Arc Smelter 20 —
**zero** landed on a slot-restricted building. So the table is *consistent* with the fixtures but
the slotted entries are **unexercised by them** (hit rate is undefined, n=0, not 100%).

**Consequence for the validator:** the permissive "sorter may attach to any perimeter tile"
assumption is **correct for every machine this generator places**. It becomes wrong only if the
layout ever emits a Fractionator, Storage Tank, Splitter, or Logistics Station — for those,
enforce the slot table above. Since the Fractionator is a real production building (3 slots, and
notably asymmetric), guard it explicitly.

---

## 6. Power (now a hard constraint)

### 6.0 RADIUS vs DIAMETER — **RESOLVED: it is a RADIUS.** Both methods agree.

**Method 1 — game data.** Field is `PrefabDesc.powerCoverRadius`, populated from
`PowerDesc.coverRadius` (`asm.il` IL_1ac4 `stfld float32 PrefabDesc::powerCoverRadius`). Raw value
for Tesla Tower (`tesla-tower-1`) is **`coverRadius = 10.5`**, alongside
**`connectDistance = 22.5`**, in the same tile units as `localOffset`. The field name says radius;
the sibling field is named *distance*, not *diameter*, and no `powerCoverArea`/`Diameter` field
exists anywhere in `PrefabDesc` or `PowerDesc`.

**Method 2 — measurement against working blueprints** (the check that actually discriminates).
Measured every machine's distance to its nearest power tower, on uniform-grid fixtures only:

| fixture | version | machines | max dist | **> 5.25** (diameter hypothesis) | **> 10.5** (radius hypothesis) |
|---|---|---|---|---|---|
| `12-s-purple-…` | 0.8.19 | 312 | 7.81 | **86 (27%)** | **0** |
| `quick-start-step-1` | 0.10.28 | 7 | 5.83 | **2 (28%)** | **0** |
| `quick-start-step-3` | 0.10.28 | 27 | 6.32 | **6 (22%)** | **0** |

This brackets the answer from both sides:

- If 10.5 were a **diameter** (true radius 5.25), then 22–28% of machines in published, working
  blueprints — 94 machines in total, including 86 in one — would be **unpowered**. Refuted.
- The radius hypothesis predicts **nothing** beyond 10.5, and nothing is observed beyond 10.5 in
  any fixture. Confirmed, with the observed maxima (7.81 / 5.83 / 6.32) landing comfortably
  inside 10.5 while clearly exceeding 5.25.

Corroborating: Satellite Substation (`coverRadius = 26.5`) powers machines at up to 19.21 in
`factory-heretical-smelter-block` — again impossible under a diameter reading (13.25).

**Use `coverRadius` directly as a radius. Do not halve it.** For Tesla Tower: supply radius
**10.5**, link radius **22.5**.

⚠ Tower-to-tower `connectDistance` is *not* independently pinned by this corpus: the largest
tower nearest-neighbour distance on a uniform grid is 11.00 (`12-s-purple`), which fits both the
radius reading (22.5) and a diameter reading (11.25). It is only 2.2% under the diameter figure,
so that measurement cannot discriminate. It is carried on the strength of the field naming and
the fact that `coverRadius`, its sibling in the same struct and units, is proven to be a radius.
Since an over-large link radius yields a *disconnected* network (a visible, testable failure)
rather than a silent one, this residual risk is acceptable — but if the solver ever spaces towers
between 11.25 and 22.5 apart, verify in game before trusting it.

### 6.1 Values

From `PowerDesc` (`slots_power.json`). `connectDistance` = tower-to-tower linking range;
`coverRadius` = supply radius to consumers. Units are the same tile units as `localOffset`.

| Building | itemId | model | footprint | **coverRadius** | **connectDistance** |
|---|---|---|---|---|---|
| Tesla Tower | 2201 | 44 | 1×1 | **10.5** | **22.5** |
| Wireless Power Tower | 2202 | 45 | 1×1 | **6.5** | **45.5** |
| Satellite Substation | 2212 | 68 | 7×7 | **26.5** | **53.5** |

Generators/others for completeness: Wind Turbine cover 7.7 / connect 16.5; Solar Panel cover 0 /
connect 6.75; Thermal & Mini Fusion Power Plant cover 4.5 / connect 11.75; Artificial Star cover
5.0 / connect 15.0; Ray Receiver cover 10.5 / connect 22.5; Energy Exchanger cover 7.0 / connect
15.5; Accumulator connect 4.2 (cover 0).

Modelling note: coverage is a **circle of `coverRadius` about the tower's `powerPoint`**, so a
Tesla Tower covers a disc of radius 10.5 — a grid of towers spaced ≤ 14.8 apart
(`10.5·√2`) gives gap-free coverage, and ≤ 22.5 keeps the network connected. Both are easy
CP-SAT constraints: a machine at distance ≤ 10.5 from some tower, and the tower graph connected
under 22.5.

⚠ Per-machine `workEnergyPerTick` is **not** on `PowerDesc`; `AssemblerDesc` carries only
`recipeType` + `speedf`. FactorioLab's `data.json` already has usable `machine.usage` values in
watts (e.g. `assembling-machine-2` = 540 kW) — use those rather than re-deriving, since only
relative draw matters for tower counts.

---

## 7. Sorters, belts, splitter, spray coater

### Sorter reach and throughput — **derived and independently confirmed**

`InserterDesc`: `sttf` = seconds per tile of travel; the sorter must return, so a full cycle over
distance *d* takes `2·sttf·d`.

**throughput(items/s) = stackSize / (2 · sttf · d)**

| Sorter | itemId | model | grade | sttf | stack | **1 tile** | **2 tiles** | **3 tiles** |
|---|---|---|---|---|---|---|---|---|
| Sorter Mk.I | 2011 | 41 | 1 | 0.33333 | 1 | **1.5** | 0.75 | 0.50 |
| Sorter Mk.II | 2012 | 42 | 2 | 0.16667 | 1 | **3.0** | 1.5 | 1.0 |
| Sorter Mk.III | 2013 | 43 | 3 | 0.08333 | 1 | **6.0** | 3.0 | 2.0 |
| Pile Sorter | 2014 | 483 | 4 | 0.05000 | 2 | **20.0** | 10.0 | 6.67 |

The 1-tile column (1.5 / 3 / 6 / 20) reproduces the long-published DSP values exactly, which
validates the formula. `canStack` is set for Mk.III and Pile only.

**Reach = 3 tiles, measured, and it is NOT tier-dependent.** Endpoint-to-endpoint span of all
1,288 sorters in the corpus:

| Sorter | n | max span | span clusters |
|---|---|---|---|
| Sorter Mk.I | 262 | **3.4** | 1.0–1.2 (124), 2.1–2.4 (82), 3.x |
| Sorter Mk.II | 134 | 2.2 | 1.1–1.2 (68), 2.2 (66) |
| Sorter Mk.III | 680 | **3.1** | 1.1–1.2 (414), 2.1–2.2 (202), 3.1 (64) |
| Pile Sorter | 212 | **3.4** | 0.1–0.4, 1.0–1.3, … |

Spans cluster at ≈1, ≈2, ≈3 (the extra ~0.1–0.4 is because endpoints sit slightly inside the
machine/belt rather than on its centre). **Nothing reaches 4.** Mk.I is observed at 3.4 while
Mk.II only reaches 2.2 — so the 3-tile cap is a property of sorters generally, not of tier;
Mk.II simply is not used at full stretch in this corpus. Longer spans are strictly worse per the
throughput table, so the solver should prefer 1-tile spans and use 2–3 only to clear obstacles.

### Belts

| Belt | itemId | model | throughput |
|---|---|---|---|
| Conveyor Belt Mk.I | 2001 | 35 | 6 items/s |
| Conveyor Belt Mk.II | 2002 | 36 | 12 items/s |
| Conveyor Belt Mk.III | 2003 | 37 | 30 items/s |

Cross-checked against FactorioLab `data.json` (`conveyor-belt-2` → `belt.speed: 12`).
`BeltDesc.speed` in the assets is an internal integer (segments/tick), not items/s — prefer the
table above. Belt **stacking/piling** multiplies effective throughput up to **4×** (stack of 4),
but requires an **Automatic Piler** (itemId 2040, 1×3, `multiLevel`) on the belt to build stacks,
and unstacking to consume them. FactorioLab exposes this as the `beltStack` flag. Recommend
leaving stacking out of v1: it adds a building, a belt-state dimension, and a second failure mode
for marginal density gain.

### Splitter ⚠ *(one of the three guesses to settle)*

The Strategy B designer's guess of **2×2 is right in effect, but for the wrong reason, and the
naive table lookup gives 2×1.** There are three splitter prefabs sharing itemId 2020:

| prefab | blueprintBoxSize | round | modelIndex |
|---|---|---|---|
| `splitter-a` | 2.38 × 1.25 | 2×1 | 38 |
| `splitter-b` | 1.65 × 2.38 | 2×2 | – |
| `splitter-c` | 2.38 × 2.38 | **2×2** | 39 |

`splitter-a/b/c` are the 2-way / 3-way / 4-way variants; the viewer's catalog already notes two
splitter models (38, 39) diverging from the item default. **Use 2×2** — the conservative envelope
covering all variants. Do not use the 2×1 from `splitter-a`. Splitters are `multiLevel` and, in
the fixtures, sit at distance 0.00 from belt tiles (they are placed *on* the belt line), with
4 slots at ±0.25.

⚠ Planetary Logistics Station similarly rounds to 6×8 from a 5.5 × 8.0 box while the ILS is a
clean 10×10; the PLS is worth confirming in game if the layout ever places one.

### Spray Coater — *geometrically cheap, confirmed*

- **Footprint 1×2** (box 0.70 × 2.00), `addonType = 1`, `multiLevel = 1`.
- `addonType=1` marks it a **belt addon**: it does **not** consume a free tile. In all 8 fixture
  instances the coater sits at distance **0.00 from a belt tile at the same altitude**, i.e. it
  is mounted on the belt and the belt runs through it. Traffic Monitor (2030) is the only other
  `addonType=1` building.
- `SpraycoaterDesc`: `incCapacity = 600`, `incItemId = [1141, 1142, 1143]` — Proliferator
  Mk.I/II/III. It holds 600 sprays internally.
- Proliferator input: the coater has **no** slot poses and in all 8 fixture instances
  `inputObjIdx = outputObjIdx = -1`, and no sorter in any fixture targets a coater. It is fed by
  an ordinary sorter from a proliferator belt, with the *sorter* carrying the connection — so the
  cost of proliferating a lane is **one coater (free, on-belt) + one sorter + access to a
  proliferator belt**, not a dedicated tile.
- **Net: proliferation is cheap in area.** The real cost is routing a proliferator lane within
  sorter reach of each coater. Since the user has specified proliferator arrives as a belted
  input, one shared proliferator lane running alongside the bus can serve many coaters.

### Sorter to a belt at a different altitude ⚠ *(third guess — measured, treat as NO)*

**Every one of the 1,288 sorters in the corpus has `z2 − z` exactly 0.0** — Mk.I 0/262, Mk.II
0/134, Mk.III 0/680, Pile 0/212 non-zero. Not a single cross-altitude sorter in ~14k buildings
spanning five game versions and ten builders, including blueprints that stack belts heavily.

That is not an absolute proof of illegality (the assets do not expose a reach-in-z rule I could
find, and sorters do carry `pitch`/`tilt` fields the viewer reads but does not interpret), but it
is decisive for practical purposes: **no real builder relies on it**, so a layout that assumes
single-altitude sorter connections gives up nothing that working blueprints actually use.

**Recommendation: treat sorters as single-altitude.** Use vertical belt stacking for *crossings*
(belts passing over belts) only, never for feeding machines. This assumption fails safe — toward
a larger build, not a broken one. If Strategy B ever wants the extra density, one in-game check
settles it.

---

## 8. Confidence summary

**High (code-derived AND independently measured against real blueprints):** footprints for all
smelters, assemblers, chemical plants, refinery, labs, particle collider, depots, ILS; the
`blueprintBoxSize` formula; integer center coordinate convention; yaw conventions; sorter
throughput vs span; **sorter reach = 3 tiles, tier-independent**; belt throughputs; production
machines having no slot restrictions; spray coater being a free belt addon; **Tesla Tower supply
radius 10.5 as a RADIUS, not a diameter**; sorters being single-altitude in practice.

**Medium (code-derived, not exercised by fixtures):** slot poses for Fractionator / Storage Tank /
Splitter / Logistics Stations; Planetary Logistics Station 6×8; Storage Tank and Fractionator 5×5;
tower-to-tower `connectDistance` 22.5 as a radius (see §6.0 — the corpus tops out at 11.00, which
cannot discriminate 22.5 from an 11.25 diameter reading; fails visibly if wrong).

**Unresolved / deferred:** (a) per-machine power draw — take from FactorioLab `machine.usage`
rather than the assets; (b) whether a sorter *can* legally span altitudes (measured as never used;
assumed no); (c) belt stacking/piling deliberately out of scope for v1.

**Trap to avoid:** never pool fixtures across game versions for geometric validation, and never
use polar/whole-planet blueprints for it at all. Both produced convincing false contradictions
during this work.
