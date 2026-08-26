# Handoff

State of the game-rule work as of `c6f51f11`. Read this before touching any
rule, and before believing any number in any other document.

---

# 1. How to work on a rule

## 1.1 Start from the game's failure modes, not from our rule list

`EBuildCondition` is a closed set of **59** values. It is every way the game can
refuse a building. Nothing outside it can happen.

`docs/EBUILD_COVERAGE.md` carries one row per value, each IMPLEMENTED /
INAPPLICABLE / MISSING, and `tests/conditions/` fails the build if a row loses
its verdict.

**This is the entry point.** `docs/RULE_LEDGER.md` verifies the rules we already
had; it is structurally unable to find a rule nobody wrote down. That gap cost a
real build: `PowerTooClose` refused two Tesla Towers in a shipped blueprint, and
no amount of auditing the rules we had would ever have surfaced it.

## 1.2 Find WHICH TOOL sets the condition

The single highest-yield check. `rg -n "EBuildCondition.<Name>"` across the
decompiled tree, then look at the file:

| tool | governs us? |
|---|---|
| `BuildTool_BlueprintPaste` | **yes** — this is what a pasted blueprint runs |
| `BuildTool_BlueprintCopy` | only when copying |
| `BuildTool_Path` / `_Click` / `_Inserter` | **no** — interactive tools |

Two items were resolved by this alone:

* `TooBendToLift` appears **only** in `BuildTool_Path.cs:1982`. Not a paste
  rule. Wiring it would have taken INVALID from 0 to 39 of 48 cells.
* `MatchInserter` runs only when a sorter's peer preview is null, and
  `BlueprintUtils.cs:1623-1624` fills that from the blueprint's own records. It
  **never runs on anything we emit**.

12 of the 44 INAPPLICABLE rows are `BuildTool_Path`-only. 5 more are never
assigned anywhere in the assembly — they exist only in
`BuildPreview.GetConditionText`'s switch.

## 1.3 Citation discipline

**The decompiled source is at `/home/dannyb/.claude/jobs/66c2051c/tmp/poseless/full/`**,
one file per type.

**Offsets are per-citation, not per-file, and not per-repository.**

| file | offset |
|---|---|
| `BuildTool_BlueprintPaste.cs` | **+143581** for most, **0** for others |
| `BlueprintUtils.cs` | 0 |
| `PlanetGrid.cs` | 0 |

`dsp/colliders.py` carries citations in *both* conventions three hundred lines
apart. One pre-existing citation resolved under neither and was simply wrong.

**Always grep for the literal** and confirm the surrounding code. That is what
`docs/RULE_LEDGER.md` did for 100 citations (0 unresolvable) and re-checked for
30 load-bearing ones (literal within ±3 lines).

## 1.4 State the units. Every time.

Four separate defects this session were unit confusion. When you write a
threshold, write what it is measured in:

| rule | value | unit |
|---|---|---|
| `CheckInserterDataLegal` | 0.8 | **world units** (= 0.637 tiles) |
| `MatchInserter` gate | `num4 < 6f` | **squared** world (= 2.449 world units) |
| `PowerTooClose` | `num35 < 12.25f` | **squared world, 3-D** (= 3.5 world = 2.785 tiles) |
| `num134` sorter floor | 1.451 | **grid cells** |
| a tile | `GRID_ARC = 2π/5` | **1.2566 world units** |

## 1.5 A rule needs controls that SUCCEED

A rule fitted to a known failure set proves nothing. The user built five
two-sorter blueprints one at a time:

```
REFUSED: (21,162) (55,162) (46,163)
BUILT:   (21,163) (46,162)
```

`game.sorter_collide` scores **5 of 5** — collides on all three refused, clean
on both controls. Those blueprints are `tests/fixtures/ours/test-pair-*.txt`.
That is the standard. Before it, the same rule's only evidence was that it
reproduced a set someone already knew.

The other control that matters: **`tests/fixtures/` holds real blueprints the
game itself wrote.** Any conviction there is your rule being wrong. Run every
new rule over them and report the number.

## 1.6 Tech level and tier are part of the rule

A rule whose value depends on researched tech or building tier is still a rule —
its citation resolves to a lookup rather than a literal. Flattening one to a
single constant is a guess: right by coincidence for one tech level, silently
wrong for the rest.

Live examples: sorter reach by Mk.I/II/III (measured NOT tier-dependent), belt
throughput by tier, `SORTER_SEGMENTS_MAX`/`SORTER_COMBINED_MIN` keyed on how
many of a sorter's ends are machines, `Splitter.stackHeight`, and the blueprint
building-count limit (150 → 3600 → unlimited).

## 1.7 Reachability is not exercise

R4 measures whether perturbing a constant turns a test red. Two rules read by
the search measured **inert** — `DRAG_MAX_ALIGNMENT` and all four
`planet.SORTER_*` — because no test sits near their bound. A wrong value ships.
Declaring a rule "consulted" because a reference graph reaches it is not
evidence.

---

# 2. Where the rules are

All **59** declared game rules live in three files and nowhere else:

```
src/flab2bp/dsp/rules.py        paste/sorter/addon geometry
src/flab2bp/dsp/catalog.py      rates, reach, belt and tech rules
src/flab2bp/dsp/colliders.py    collision boxes, planet grid
src/flab2bp/dsp/planet.py       longitude bands, exact projection
```

Enforced by:

| file | what it does |
|---|---|
| `docs/EBUILD_COVERAGE.md` | 59 conditions, one verdict each |
| `docs/RULE_LEDGER.md` | every rule: verdict, citation, dependency, code path |
| `dsp/registry.py` | declares RULE / KNOB / DATA / DERIVED |
| `dsp/provenance.py` | reference graph, rooted at `validate.CHECKS` |
| `tests/rules/`, `tests/conditions/` | R1 lint, R2 registry, R4 mutation |
| `scripts/rule_report.py` | prints the tables without a suite run |

**Consolidation figure: 49.2%** — 29 of 59 rules named by both a validator check
and a search strategy. Rules are consolidated by *location*; only about half are
consolidated by *consultation*.

Rule vs knob is **declared, not inferred** — no numeric heuristic separates
`freeform.LEVELS = 3` from `SORTER_MAX_REACH = 3`.

R1 does **not** start green with no exceptions: it fires 13 times, all
coincidences (`timeout_s = 200.0` vs `PLANET_RADIUS`, `0.5 * 1.6**it` vs
`PASTE_RADIAL`). The game's constants are ordinary numbers. Lint only on
distinctive values — `0.9702957` yes, `0.5` and `6.0` no.

---

# 3. Verified facts — do not re-derive

## Geometry

* A tile is **1.2566** world units (`GRID_ARC = 2π/5`), not 1.0.
* Blueprint `z` is 3/4 of world height. `WORLD_UNITS_PER_LEVEL = 4/3`.
* Sorter endpoints are **not** at tile centres. The game's own are 3% integer;
  ours as emitted are 100%. The paste re-seats them
  (`RefreshBuildPreview` 2090-2190), so emitted coordinates are not where the
  sorter lands. `slots.seated_sorter` reproduces the landing to **2e-5 tiles**
  over 66 ends of 33 sorters the game actually built.
* Writing seated coordinates into a blueprint is a **no-op** — the game re-seats
  regardless. Sorter fixes belong in the layout, not the coordinates.

## Planet bands

* `PlanetGrid.DetermineLongitudeSegmentCount` computes a cosine then quantises
  through a **512-entry** `segmentTable`. `_SEGMENT_TABLE_HEAD` used to hold 8
  of those entries and fall through; `table[i] != i` for **478 of 492** indices
  in the fall-through range. It was correct only where the table is the
  identity — including index 200, the one the equatorial model reaches.
* Terrestrial planets: `segment = 200`, 5 grid tiles per segment in both axes.
* Band heights (tiles): 200→**161** rows (symmetric, −80..80), 160→50, 120→25,
  100→25, 80→15, 60→15, 40→10, 32→10, 20→5, 16→5, 8→5, 4→5.
* **Column width is a sawtooth, not a ramp.** Quantisation overshoots at each
  band's equatorward edge. Band 8's equatorward edge is **1.41× the equatorial
  column** — wider than the equator. The narrowest column in the system is band
  32's poleward edge at 0.783.
* Therefore **"smallest band that fits" is not "narrowest tiles"** and is not a
  conservative proxy. `spine._band_rejected` uses the satisfiable reading:
  smallest band the layout is actually *legal* in, searched upward.
* `colliders.collisions()` evaluates on a flat equatorial grid, which is the
  **supremum** of real spacing. A layout it passes can still collide poleward.

## Sorters

* The five sorters the game refused were **collisions**, not a band-transition
  artifact. Confirmed by the user's own rebuild: after the `_bridge` fix all 35
  sorters built.
* `_bridge` was asking geometry questions about **slot 0** of every machine,
  because slot fields sit at the dataclass default until `assign_sorter_slots`
  runs at emission. 15 of 96 mid cells emitted bridges the paste refuses.
* `entityConnPool[objId * 16 + slot]` — one int per (object, slot).
  `WriteObjectConn` **evicts** the sitting tenant rather than refusing.
* `WriteObjectConn` with `otherSlot == -1` takes the **first free cell in 4..12**
  — no position term. It runs at BUILD time, after `CheckBuildConditions` has
  passed, so it is irrelevant to any refusal.

## Power

* `PowerTooClose`: two power nodes closer than **3.5 world units** (2.785 tiles)
  are refused. Guard is `isPowerNode && !isAccumulator`. Wind 10.5, geothermal 12.
* **Three loops**, not two: live network (`:2549`), ghosted prebuilds (`:2593`),
  and other previews of this paste (`:2641`). The third convicts a
  self-contained blueprint.
* `isPowerNode` covers **13** buildings. Three have `cover_radius == 0`.
* The `protoId 2199..2299` window is not redundant with `isPowerNode` — the
  **Signal Tower (3007)** is a power node outside the window.
* A Tesla Tower has **no build collider** (`build_colliders(2201)` → `()`), which
  is why `geom.collide` could never see this.

## Belts

* The paste's belt test is one **0.23-radius probe sphere**, no footprint, tile,
  or altitude term (`BuildTool_BlueprintPaste.cs:2179`). Clearing a machine is
  purely height, priced by `colliders.belt_crossing_height`.
* Freeform's "machines are solid at every altitude" was invented. Removed. At
  `LEVELS = 3` removing it changed **nothing** (shortest packable collider
  exceeds the top lattice level); at `LEVELS = 4` it buys ~1 cell in 72 in
  refusals, and **no measurable area**.

## Measurement

* Same-arm noise floors: **spine 0.06–0.56%**, **freeform 1.0–1.8%**.
* A null arm — provably identical geometry — measured **0.63% "denser"**. Any
  area claim smaller than the noise floor is noise. Establish the null.
* The full suite is ~**270s** against a 300s command cap. It exceeds the cap
  under load. Run it in chunks and say which chunk verified what.

---

# 4. Open work

## 4.1 Fires on today's output

| what | detail |
|---|---|
| `OutOfVerticalConstructionHeight` | 4–5 splitters at z=3. Splitter refused when `round(z/2) >= stackHeight` (**2** on a new save). `validate.py` says "we never stack any of the four" — the game measures **altitude**, not stacking. |
| `BlueprintNeedTech` | 9 of 11 builds exceed 150 buildings; `quantum-chip` is 8225. Rungs 150 → 3600 → unlimited. Nothing in the repo mentions `blueprintLimit`. |
| `catalog.MAX_BELT_SLOPE = 4/5` cited from the wrong tool | That is `BuildTool_Path.cs:1954`, the drag. The paste rule is `:2093`, a **sine** test → tan θ ≤ 3/4, **stricter**. Doesn't bite today (ramps are 0.53) but would permit a ramp the game refuses without the vertical-construction unlock. |
| `_Canvas.ramped = False` | assumes `beltVerticalConstruction`; `belt_rules_for_technologies` is never consulted, and there is no `belt_max_z` check in freeform. |
| `DEFAULT_MAX_BELT_Z` | freeform, spine and validate all consult the ceiling at a **hardcoded lab level** rather than the spec-derived `BeltAltitudeRules.max_z`. |

## 4.2 Latent

* `TooSkew` (spray-coater form): `abs(reshape.x\|y) > 0.265f`, bites only at
  `area_segments` 8 and 4. `magnetic-coil` carries a coater at band 32 — one rung away.
* `TooFar` (belt-to-belt): 0 of 6373 links today. "A belt link may not climb two levels."
* `lanes_requiring_split`: computed by the rate solver, read by **no** strategy.
  A lane feeding both a proliferated and unproliferated consumer is sprayed
  whole, so the unproliferated one silently over-produces. 1 of 14 proliferated
  candidates hits it.
* `colliders._longitude_segment_count` is **wrong away from the equator** —
  omits the band decrement, and a `-1e-9` fudge changes 300 `(segment, latIdx)`
  cases including every pole. `preview_pose(anchor_lat=)` and
  `collisions(anchor_lat=)` are its only readers. Its docstring figures were
  measured against the broken lookup and must be re-measured.
* `catalog.UNPOWERED_ITEM_IDS` has no production reader — `power.coverage`
  restates the rule in `validate._POWERED`.
* `rules.CONN_SLOTS_PER_OBJECT` is read by no code; four **prose** copies exist
  in `slots.py:827`, `spine.py:2543`, `freeform.py:795` and `:2726`.
* Coverage holes where a wrong value would ship: `DRAG_MAX_ALIGNMENT`,
  `planet.SORTER_SEGMENTS_MAX`, `SORTER_COMBINED_MIN`, `SORTER_PARAM_BIAS`,
  `SORTER_ALTITUDE_UNIT`, `PASTE_LATERAL`, `PASTE_LATERAL_EPS`, `SKEW_PAIR_DEG`.
* `planet.SORTER_PARAM_BIAS` is read by nothing — `sorter_condition` ports the
  `num129` bias inline instead of through the mapping.
* `BELT_SLOT_AUTO_RANGE = (4, 12)` gives 8 auto-assigned cells per belt. Past 8
  the connection is **silently dropped**, not refused. Nothing counts. No
  evidence it has fired on our output.

## 4.3 Cannot be settled here

* `NeedGround` — terrain raycasts. Depends on the player's planet.
* `PowerTooClose` loops 1 and 2 test against what is already on the player's
  planet. Unknowable from a blueprint.
* The `desc.*` flags in EBUILD_COVERAGE group D are argued from the guard plus
  the named building, not from a `PrefabDesc` dump. That needs UnityPy against
  the install.

---

# 5. Verification status of the current tree

`c6f51f11` is **not fully test-verified.**

* Everything through `f28b8b57` passed ruff, mypy and a full suite.
* The `PowerTooClose` merge (`38bff9d9`) had ruff and mypy clean and every test
  directory passing individually; a single whole-suite run exceeded the 300s cap
  at 98% with zero failures.
* The `bl-belt-ports` merge (`c6f51f11`) was made **on instruction without
  running tests**. Six conflicts, all additive, both sides kept. **Run the suite
  before trusting this commit.**

---

# 6. Tooling

* Decompiled C#: `/home/dannyb/.claude/jobs/66c2051c/tmp/poseless/full/` (1964 files).
* The game assembly **loads and executes under .NET 10**. `oracle/` compiles the
  snap ladder against it and agrees 15488/15488 with our port. `Vector3` is
  managed; `Quaternion.Euler`/`Inverse`/`LookRotation`/`AngleAxis`/`Slerp` are
  ECalls and throw. `GetUninitializedObject` bypasses MonoBehaviour ctors.
  `asm.GetTypes()` throws on `OptionValue` — enumerate selectively.
* Headless simulation of the build conditions is **not** viable: they query the
  PhysX scene (18 queries in `CheckBuildConditions`). Any collider set you supply
  is the thing under test.
* `tools/dsp-oracle/` is a BepInEx 5.4.17 plugin that dumps the game's own
  verdicts to JSON. Press F9 with a blueprint on the cursor; nothing is built.
  Output in `<BepInEx>/flab2bp-oracle/`. Never yet run in-game.
