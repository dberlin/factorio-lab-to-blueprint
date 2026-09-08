# Selectable power building (Tesla Tower / Satellite Substation / Wireless Power Tower)

## Design note

### The question this answers

> If I add "satellite power substation" to my preferred machines, will we use it for power?

No. Two independent reasons, both verified on master `a1401518`:

1. The FactorioLab URL's `mmr` parameter (`machineRankIds`) is parsed into
   `LabRequest.machine_rank_ids` (`src/flab2bp/lab/url.py:217,540`) and consumed by exactly one
   caller, `rates.adjust.select_machine` (`src/flab2bp/rates/adjust.py:84-98`), which matches the
   rank against a *recipe's* `producers`. A power building produces no recipe, so it can never win
   there.
2. Every power site the layout emits is a Tesla Tower, by constant. `catalog.TESLA_TOWER_ID = 2201`
   (`src/flab2bp/dsp/catalog.py:229`) is read at eight production call sites, all in
   `src/flab2bp/layout/freeform.py` (5558, 5740, 5746, 15473, 15556, 15837, 16051, 16058) plus two
   in `src/flab2bp/bench/metrics.py` (18, 65).

### Measured game data (not remembered — printed from the loaded catalog)

`uv run python -c "from flab2bp.dsp import catalog; ..."` in this worktree:

| | Tesla Tower | Wireless Power Tower | Satellite Substation |
|---|---|---|---|
| lab id | `tesla-tower` | `wireless-power-tower` | `satellite-substation` |
| DSP item id | 2201 | 2202 | 2212 |
| prefab | `tesla-tower-1` | `charging-pole` | `orbital-substation` |
| model index | 44 | 71 | 68 |
| `catalog.footprint()` | `(1, 1)` | `(1, 1)` | `(5, 5)` |
| `catalog.clearance(_, 0.0)` | `(1, 1)` | `(1, 1)` | `(6, 6)` |
| `collider_span(_, 0.0)` tiles | 0.477 | 0.796 | 5.491 |
| `cover_radius` | `21/2` = 10.5 | `13/2` = 6.5 | `53/2` = 26.5 |
| `connect_distance` | `45/2` = 22.5 | `91/2` = 45.5 | `107/2` = 53.5 |
| `is_power_node` | True | True | True |
| wind / geothermal | False | False | False |

**Units.** `cover_radius` and `connect_distance` are in **tiles**, not world units — both the planner
(`freeform.py:15473-15479`) and the validator (`layout/validate.py:3687-3721`) compare them against
doubled tile coordinates (`(2*dx)**2 + (2*dy)**2 <= floor((2*r)**2)`), the half-tile-precision integer
convention used throughout. Only *collider* extents are in world units (`GRID_ARC = 2*pi/5 ≈ 1.2566`
world units per tile, `src/flab2bp/dsp/colliders.py:162`).

**Footprint derivation.** The `"footprint"` array in `buildings.json` is *not* what the loader uses.
`catalog._load()` (`catalog.py:1652-1653`) derives it from `colliders.json` via
`colliders.own_centre_extent(model_index, 0.0)` then `catalog.derive_footprint(extent)`
(`catalog.py:1387`, `max(1, 2*ceil(half/GRID_ARC - 1e-9) - 1)`, always odd). That is why the JSON says
`[7,7]` for the Satellite Substation but the catalog reports `(5, 5)`. **The catalog is the authority;
never read the JSON `footprint` field.**

**Consequence of the radii.** The Satellite Substation's cover radius is 2.52x the Tesla Tower's, so
one substation covers ~6.4x the area — expect roughly 6x fewer power sites. The Wireless Power Tower
is the opposite trade: 0.62x the cover radius (~2.6x *more* sites) for 2.02x the link distance. It is
a long-reach relay, not a coverage building.

### Decisions

**D1 — Ship all three choices.** `tesla` (default), `substation`, `wireless`. Wireless is a genuine
three-line addition: its data record is complete and ordinary (`is_power_node` true, both radii
non-zero, no wind/geothermal flag), its footprint is 1x1 like the Tesla Tower's, and it is **not** in
`LOW_CONFIDENCE_FOOTPRINTS`. Nothing about it needs special handling — it does *not* power machines
without a link; it simply has a long `connect_distance` and a short `cover_radius`.

**D2 — The "small frozen record" is `catalog.Building`, not a new parallel type.** `catalog.Building`
already carries every field the brief asks for: `item_id`, `model_index`, `width`, `height`,
`cover_radius`, `connect_distance`, and the `power_node` view that `rules.power_node_keepout_offsets`
consumes. Inventing a second record would duplicate game data and give it a second chance to drift.
The choice is carried as a **lab id string on `BuildSpec`**, exactly like `belt_item_id`
(`spec.py:188`), and resolved once with `catalog.get_item_id()` / `catalog.building()` — the same
two-step `_prepare_routing_problem` already performs for belts at `freeform.py:16569`.

**D3 — The keep-out tier is *not* per-building.** `rules.POWER_TOO_CLOSE_SQR = 12.25` (world², = 3.5
world units = 2.785 tiles, `dsp/rules.py:882`) applies to every power node that is neither wind-forced
nor geothermal. The docstring at `rules.py:872-876` already names the Satellite Substation in that
tier. `rules.power_node_gate_sqr` / `power_node_condition` (`rules.py:922-972`) take `PowerNode`
instances and are already fully building-generic. **No rules.py change is required** — the record
carries `power_node` and the existing generic path does the rest.

**D4 — The validator needs no code change either.** `_tower_centres` (`layout/validate.py:3663`)
reads `info.cover_radius` / `info.connect_distance` off `cat.building(b.item_id)` per placed building;
`power.coverage`, `power.connectivity` and `game.power_too_close` are all generic, and
`rules.PASTE_POWER_NODE_IDS = (2199, 2300)` (`rules.py:919`) already contains 2201, 2202 and 2212.
This task set adds **tests only** for the validator.

**D5 — `TESLA_COVER_RADIUS` and `TESLA_LINK_DISTANCE` do not exist.** The brief names them as "the
planner's radii"; they are stale prose. They appear only in comments (`dsp/rules.py:46`,
`layout/validate.py:3852`) and as local readability aliases in `tests/layout/test_validate.py:61-62`.
The planner already reads the radii generically off the resolved `Building`. Only *which building* is
hardcoded. This makes the change far smaller than the brief assumed: the arithmetic is already
parameterised, so the work is plumbing plus footprint-claim correctness.

**D6 — Precedence: explicit flag > URL machine rank > default `tesla`.** The lab dataset's `machines`
list contains `satellite-substation` and `wireless-power-tower` but **not** `tesla-tower` (verified in
`src/flab2bp/lab/vendored/hash.json`; `tesla-tower` is an item with no `machine` block). So a URL can
only ever *opt in* to a substation or a wireless tower — it can never spell "tesla". That is fine:
tesla is the default, and "URL says nothing about power" and "URL says tesla" are the same state.
The bridge from lab id to DSP item id is `catalog.get_item_id()` (`catalog.py:1199`), verified to
resolve all three ids.

**D7 — The one real correctness risk is the 5x5 footprint.** Every arithmetic use of the tower is
already generic *including* `width`/`height` (`_power_coverage_discs` centres a disc at
`2*x + tower.width`; `_place_power` emits `width=tower.width, height=tower.height`). What is **not**
established is that the site-selection lattice in `_power_plan` only proposes sites where a 5x5
building actually fits and is then seen as an obstacle by the packer and the router. A 1x1 tower needs
one free tile; a substation needs a 5x5 free block plus its `(6, 6)` clearance pitch. Task 4 exists
solely to establish and test this.

**D8 — The validator will NOT catch a belt run through a substation.** Item 2212 is in
`catalog.LOW_CONFIDENCE_FOOTPRINTS` (`catalog.py:917`) and therefore in
`UNPLACED_LOW_CONFIDENCE_FOOTPRINTS` (`catalog.py:1056`), which `layout/validate.py:2803` uses to
**suppress belt-collision findings** against it. So `certify()` passing on a substation build is
weaker evidence than it is for a Tesla build. Task 4 therefore adds a *direct geometric* assertion
(no belt/sorter tile inside any power building's claimed footprint rectangle) rather than trusting
`certify`, and the gate reports it separately. Do not "fix" the low-confidence flag in this branch —
the catalog docstring (`catalog.py:904-916`) records it as an unresolved measurement question and it
is out of scope.

**D9 — `hierarchy/compose.py` needs no change.** `canvas_for` (`compose.py:396-462`) routes towers to
the generic `else: canvas.add(b, solid=True)` branch by elimination — it never names
`TESLA_TOWER_ID`. It is already correct for a 5x5 building.

**D10 — The hierarchical seam.** `BuildSpec` is rebuilt for sub-blocks at
`layout/hierarchy/partition.py:328` and `:427`, which copy fields explicitly (`belt_item_id=spec.belt_item_id`).
Both sites must copy the new field or the hierarchical path silently reverts to tesla. That single
propagation is also the seam for the in-flight `hierarchical-v4` branch: whatever power infill it adds
must resolve its building from `spec.power_tower_item_id` through the same
`catalog.power_tower_building()` helper rather than calling `catalog.building(catalog.TESLA_TOWER_ID)`.
See the follow-up note in Task 11.

**D11 — Viewer.** `web/src/scene/BuildingInstances.tsx:75` draws every non-belt/non-sorter building as
one instanced unit box scaled by `.size`, with no per-model geometry table, so a 5x5 substation renders
correctly with zero front-end work. Endpoint icons (`web/src/model/overlays.ts:146-199`) iterate only
`model.beltRuns`, and per-building icons (`:81-99`) key on `recipeId > 0` / `filterId > 0` — a power
site sets neither. The verification in Task 9 is a check, not a change.

**D12 — Performance watch.** `_power_plan` allocates masks padded by `pad = link + reach + 1`. For
tesla that is 35; for a substation it is 82, and the coverage-disc offset list grows from 529 entries
to 2916. The default arm must be byte-identical and the substation arm must still finish inside
`--budget 30`; Task 11 gate (b) reports substation wall-clock per cell so a blow-up is visible rather
than silent.

---

# Selectable Power Building Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a build choose which power building the layout places — Tesla Tower (default,
byte-identical to today), Satellite Substation, or Wireless Power Tower — selectable by CLI flag, web
UI select, or the FactorioLab URL's machine rank.

**Architecture:** Carry the choice as a lab id string on `BuildSpec` (the `belt_item_id` pattern),
resolve it once to a `catalog.Building` in `_prepare_routing_problem`, park that record on `_Canvas`,
and have every power call site read it instead of `catalog.TESLA_TOWER_ID`. The radii arithmetic, the
`PowerTooClose` tier and the validator are already building-generic; the only new logic is
footprint-aware site claiming for a 5x5 building.

**Tech Stack:** Python 3.12 + pydantic (`BuildSpec`), numpy (power masks), pytest; React 19 + zod +
rstest for the web front end; `uv` for the Python env, `bun` for the front end.

**Spec:** This document's "Design note" section above. Read it before Task 1 — decisions D1-D12 are
binding and every task references them by number.

## Global Constraints

- **Worktree.** All work happens in `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/power-tower`
  (branch `power-tower`, merge base `a1401518`). Run `uv sync` first, then confirm
  `uv run python -c "import flab2bp; print(flab2bp.__file__)"` prints a path **inside the worktree**
  before reporting any test count. A `VIRTUAL_ENV ... does not match` warning from `uv` is expected
  and harmless — the printed path is what matters.
- **Never a git command that opens an editor.** `export GIT_EDITOR=true`; always `-m` or `--no-edit`.
- **Never `ps | grep`.** Use `pgrep -f` with an interpreter-anchored pattern.
- **CPU pressure** only as `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'` (fine below
  64). Never load average, never `uptime`.
- **ONE build at a time** from this branch — six other agents share this box. Use `--budget 30`.
- **Serena is a shared, last-activation-wins server.** Read with Serena/LSP; **edit with Read/Edit
  only**. Never issue a Serena write tool from this worktree.
- **Never commit** anything under `.superpowers/` or `web/dist`.
- **Evidence** goes under `docs/superpowers/evidence/2026-09-07-power-tower/`. Any size is fine; never
  shrink or omit evidence to save space.
- **No `for b in buildings` scans inside loops.** Build a dict index once outside the loop.
- **Never merge, push, or delete the branch.** Stop ready to merge.
- **`cover_radius` and `connect_distance` are in tiles** (D-note "Units"). Never divide them by
  `GRID_ARC`.
- **The catalog is the footprint authority.** Never read the `"footprint"` field out of
  `buildings.json` (D-note "Footprint derivation").
- **Known reds on master** (not regressions, do not chase):
  `test_two_stage_alignment_retains_cp_sat_direct_opportunity` and
  `test_all_products_sequence_pair_honours_the_exact_layout_deadline`. `universe-matrix` refuses on
  master today on producer-lane fan-out — a separate lever, not ours.
- **Choice vocabulary is fixed**: the three CLI/web values are exactly `tesla`, `substation`,
  `wireless`. The three lab ids are exactly `tesla-tower`, `satellite-substation`,
  `wireless-power-tower`. Do not invent synonyms.

---

### Task 1: The choice vocabulary and the resolver

Adds the one place that maps a choice name to a `catalog.Building`. Pure addition — nothing calls it
yet, so behaviour cannot change.

**Files:**
- Modify: `src/flab2bp/dsp/catalog.py` (add near `TESLA_TOWER_ID`, `catalog.py:229`)
- Modify: `src/flab2bp/dsp/registry.py` (add an entry beside `catalog.TESLA_TOWER_ID`, `registry.py:219`)
- Test: `tests/dsp/test_catalog.py`

**Interfaces:**
- Consumes: `catalog.get_item_id(factoriolab_id: str) -> int | None` (`catalog.py:1199`),
  `catalog.building(item_id: int) -> Building` (`catalog.py:1727`).
- Produces:
  - `catalog.POWER_TOWER_CHOICES: dict[str, str]` — choice name to lab id.
  - `catalog.DEFAULT_POWER_TOWER: str = "tesla-tower"` — the default lab id.
  - `catalog.power_tower_building(factoriolab_id: str) -> Building` — resolve a lab id to the record.
    Raises `ValueError` for an unknown id or a building that is not a power node.

- [ ] **Step 1: Write the failing test**

Add to `tests/dsp/test_catalog.py`:

```python
def test_power_tower_choices_resolve_to_power_nodes() -> None:
    assert catalog.POWER_TOWER_CHOICES == {
        "tesla": "tesla-tower",
        "substation": "satellite-substation",
        "wireless": "wireless-power-tower",
    }
    assert catalog.DEFAULT_POWER_TOWER == "tesla-tower"
    for lab_id in catalog.POWER_TOWER_CHOICES.values():
        building = catalog.power_tower_building(lab_id)
        assert building.is_power_node
        assert building.cover_radius > 0
        assert building.connect_distance > 0


def test_power_tower_building_matches_the_measured_game_data() -> None:
    tesla = catalog.power_tower_building("tesla-tower")
    assert (tesla.item_id, tesla.width, tesla.height) == (2201, 1, 1)
    assert (tesla.cover_radius, tesla.connect_distance) == (Fraction(21, 2), Fraction(45, 2))

    substation = catalog.power_tower_building("satellite-substation")
    assert (substation.item_id, substation.width, substation.height) == (2212, 5, 5)
    assert (substation.cover_radius, substation.connect_distance) == (
        Fraction(53, 2),
        Fraction(107, 2),
    )

    wireless = catalog.power_tower_building("wireless-power-tower")
    assert (wireless.item_id, wireless.width, wireless.height) == (2202, 1, 1)
    assert (wireless.cover_radius, wireless.connect_distance) == (
        Fraction(13, 2),
        Fraction(91, 2),
    )


def test_power_tower_building_refuses_a_non_power_building() -> None:
    with pytest.raises(ValueError, match="not a power"):
        catalog.power_tower_building("assembling-machine-1")


def test_power_tower_building_refuses_an_unknown_id() -> None:
    with pytest.raises(ValueError, match="unknown"):
        catalog.power_tower_building("no-such-building")


def test_the_default_power_tower_is_the_tesla_tower_id() -> None:
    assert catalog.power_tower_building(catalog.DEFAULT_POWER_TOWER).item_id == (
        catalog.TESLA_TOWER_ID
    )
```

Ensure `from fractions import Fraction` and `import pytest` are imported in that test module (check
the header before adding).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/power-tower
uv run pytest tests/dsp/test_catalog.py -k power_tower -x -q
```
Expected: FAIL with `AttributeError: module 'flab2bp.dsp.catalog' has no attribute 'POWER_TOWER_CHOICES'`.

- [ ] **Step 3: Write minimal implementation**

In `src/flab2bp/dsp/catalog.py`, immediately after `TESLA_TOWER_ID = 2201` (line 229):

```python
#: The power buildings a build may choose between, keyed by the name the CLI,
#: the web UI and ``BuildSpec`` use.  The values are FactorioLab ids, resolved
#: through :func:`get_item_id` like every other id the spec carries.
POWER_TOWER_CHOICES: dict[str, str] = {
    "tesla": "tesla-tower",
    "substation": "satellite-substation",
    "wireless": "wireless-power-tower",
}

#: The choice a build gets when nothing says otherwise.  Keeping this the Tesla
#: Tower is what makes the default arm byte-identical to the era before the
#: choice existed.
DEFAULT_POWER_TOWER: str = "tesla-tower"


def power_tower_building(factoriolab_id: str) -> Building:
    """Resolve a power-building lab id to its catalog record.

    The record carries everything a power site needs -- item id, model index,
    footprint, cover radius, link distance and the ``power_node`` view the
    ``PowerTooClose`` tier consumes -- so no caller needs a second record and
    no caller needs a radius constant of its own.
    """
    item_id = get_item_id(factoriolab_id)
    if item_id is None:
        raise ValueError(f"unknown power building: {factoriolab_id!r}")
    info = building(item_id)
    if not info.is_power_node:
        raise ValueError(f"{factoriolab_id!r} is not a power node")
    return info
```

If `Building` is declared later in the file than line 229, place the function after the `building()`
definition (`catalog.py:1727`) instead and keep only the two constants at 229 — the constants must be
importable without a forward reference.

- [ ] **Step 4: Add the registry entry**

`src/flab2bp/dsp/registry.py` records catalog symbols for the hardcode lint. Beside the existing
`_e("catalog.TESLA_TOWER_ID", Kind.DATA)` at `registry.py:219`, add:

```python
    _e(
        "catalog.POWER_TOWER_CHOICES",
        Kind.DATA,
        note="Lab ids for the power buildings a build may choose between.",
    ),
    _e(
        "catalog.DEFAULT_POWER_TOWER",
        Kind.DATA,
        note="The power building a build gets when nothing chooses one.",
    ),
```

Match the exact keyword signature the neighbouring `_e(...)` calls use — read lines 210-230 first and
copy their shape; do not guess the parameter names.

- [ ] **Step 5: Run the tests and the registry lint**

```bash
uv run pytest tests/dsp/test_catalog.py -k power_tower -q
uv run pytest tests/dsp/ -q -k registry
```
Expected: both PASS (exit code 0 — the pytest summary line does not print in this environment, so
check `echo $?`).

- [ ] **Step 6: Commit**

```bash
export GIT_EDITOR=true
git add src/flab2bp/dsp/catalog.py src/flab2bp/dsp/registry.py tests/dsp/test_catalog.py
git commit -m "feat(catalog): resolve a power building from a choice name"
```

---

### Task 2: Carry the choice on `BuildSpec`

**Files:**
- Modify: `src/flab2bp/spec.py` (add a field beside `belt_item_id`, `spec.py:188`)
- Modify: `src/flab2bp/rates/candidates.py:240` (the one construction site that builds a spec from a request)
- Modify: `src/flab2bp/layout/hierarchy/partition.py:328,427` (both sub-block rebuilds — D10)
- Test: `tests/test_spec.py` (find the existing `BuildSpec` test module; if it is named differently,
  add to whichever module already tests `BuildSpec` field defaults)
- Test: `tests/layout/hierarchy/test_partition.py`

**Interfaces:**
- Consumes: `catalog.DEFAULT_POWER_TOWER`, `catalog.POWER_TOWER_CHOICES` (Task 1).
- Produces: `BuildSpec.power_tower_item_id: str` — a FactorioLab id, default `"tesla-tower"`,
  validated to be one of `catalog.POWER_TOWER_CHOICES.values()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_spec_defaults_to_the_tesla_tower() -> None:
    spec = BuildSpec(groups=())
    assert spec.power_tower_item_id == "tesla-tower"


def test_build_spec_accepts_every_power_tower_choice() -> None:
    from flab2bp.dsp import catalog

    for lab_id in catalog.POWER_TOWER_CHOICES.values():
        assert BuildSpec(groups=(), power_tower_item_id=lab_id).power_tower_item_id == lab_id


def test_build_spec_refuses_a_power_tower_it_cannot_place() -> None:
    with pytest.raises(ValidationError):
        BuildSpec(groups=(), power_tower_item_id="assembling-machine-1")
```

And in the partition tests (D10 — a sub-block that loses the choice silently reverts to tesla):

```python
def test_sub_block_specs_keep_the_power_tower_choice() -> None:
    parent = _a_partitionable_spec(power_tower_item_id="satellite-substation")
    for child in _sub_block_specs(parent):
        assert child.power_tower_item_id == "satellite-substation"
```

Read the existing partition tests first and reuse their fixture helpers — replace
`_a_partitionable_spec` / `_sub_block_specs` with whatever that module already uses to build a parent
spec and drive the two rebuild sites at `partition.py:328` and `:427`. Both sites must be covered.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_spec.py tests/layout/hierarchy/test_partition.py -k power_tower -x -q; echo $?
```
Expected: non-zero — unknown field `power_tower_item_id`.

- [ ] **Step 3: Add the field**

In `src/flab2bp/spec.py`, after the `sorter_item_ids` field (around line 195), following the
surrounding comment style:

```python
    #: The power building every power site places.  A FactorioLab id, resolved
    #: to a ``catalog.Building`` once by the layout stage.  The default keeps
    #: the Tesla Tower, so a spec built without a choice lays out exactly as it
    #: did before the choice existed.
    power_tower_item_id: str = "tesla-tower"

    @field_validator("power_tower_item_id")
    @classmethod
    def _known_power_tower(cls, value: str) -> str:
        from flab2bp.dsp import catalog

        if value not in catalog.POWER_TOWER_CHOICES.values():
            allowed = ", ".join(sorted(catalog.POWER_TOWER_CHOICES.values()))
            raise ValueError(f"power_tower_item_id must be one of {allowed}; got {value!r}")
        return value
```

Import `field_validator` from `pydantic` at the top of `spec.py` if it is not already imported (check
first — the module already uses `Field`, so it may also already import validators).

- [ ] **Step 4: Propagate it at the three construction sites**

`src/flab2bp/rates/candidates.py:240` — beside `belt_item_id=belt_id,` add
`power_tower_item_id=power_tower_item_id,`, and give the enclosing function a
`power_tower_item_id: str = catalog.DEFAULT_POWER_TOWER` keyword parameter. Thread that parameter up
through its callers until it reaches `pipeline.build` — Task 6 wires the CLI/web/URL value into it; for
now every caller may keep the default so behaviour is unchanged.

`src/flab2bp/layout/hierarchy/partition.py:328` and `:427` — beside the existing
`belt_item_id=spec.belt_item_id,` add:

```python
        power_tower_item_id=spec.power_tower_item_id,
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_spec.py tests/layout/hierarchy/ -q; echo $?
```
Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
export GIT_EDITOR=true
git add -A src/flab2bp/spec.py src/flab2bp/rates/candidates.py src/flab2bp/layout/hierarchy/partition.py tests/
git commit -m "feat(spec): carry the power building choice on BuildSpec"
```

---

### Task 3: Thread the resolved building through the power planner

The heart of the change. Replaces all eight `catalog.TESLA_TOWER_ID` reads in `freeform.py`. **The
default arm must stay byte-identical** — this task's own gate is a determinism check.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` — `_Canvas` (~5864), `_power_coverage_discs` (5553-5578),
  `_prepared_junction_ban` (~5735-5750), `_power_plan` (15402-15841), `_place_power` (16026-16058),
  `_prepare_routing_problem` (16553-16571, 17495-17509)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `catalog.power_tower_building(lab_id)` (Task 1), `BuildSpec.power_tower_item_id` (Task 2).
- Produces:
  - `_Canvas.power_building: catalog.Building` — defaults to the Tesla Tower record.
  - `_power_coverage_discs(buildings, sites, *, tower: catalog.Building)`
  - `_prepared_junction_ban(..., *, tower: catalog.Building)`
  - `_power_plan(canvas, demand, *, policy, ...)` — unchanged signature; reads `canvas.power_building`.
  - `_place_power(canvas, sites)` — unchanged signature; reads `canvas.power_building`.

- [ ] **Step 1: Write the failing tests**

```python
def test_power_sites_use_the_spec_power_building() -> None:
    spec = _a_small_spec(power_tower_item_id="satellite-substation")
    placement = _lay_out(spec)
    power = [b for b in placement.buildings if catalog.building(b.item_id).is_power_node]
    assert power, "the build placed no power sites at all"
    assert {b.item_id for b in power} == {2212}
    assert all((b.width, b.height) == (5, 5) for b in power)


def test_the_default_still_places_tesla_towers() -> None:
    placement = _lay_out(_a_small_spec())
    power = [b for b in placement.buildings if catalog.building(b.item_id).is_power_node]
    assert power
    assert {b.item_id for b in power} == {catalog.TESLA_TOWER_ID}


def test_a_substation_build_needs_far_fewer_power_sites() -> None:
    tesla = _lay_out(_a_wide_spec())
    substation = _lay_out(_a_wide_spec(power_tower_item_id="satellite-substation"))
    n_tesla = sum(1 for b in tesla.buildings if b.item_id == 2201)
    n_sub = sum(1 for b in substation.buildings if b.item_id == 2212)
    assert n_sub < n_tesla, (n_tesla, n_sub)


def test_a_wireless_build_places_wireless_towers() -> None:
    placement = _lay_out(_a_small_spec(power_tower_item_id="wireless-power-tower"))
    power = [b for b in placement.buildings if catalog.building(b.item_id).is_power_node]
    assert power
    assert {b.item_id for b in power} == {2202}
```

Reuse whatever helper `tests/layout/test_freeform.py` already uses to build a spec and run a layout —
read the module's existing power tests (around lines 9579-9763 and 13092-13146, which already assert
on `catalog.TESLA_TOWER_ID`) and copy their harness. Replace `_a_small_spec` / `_a_wide_spec` /
`_lay_out` with the real names. **Do not scan `buildings` inside a loop** — the comprehensions above
each make one pass, which is correct; keep it that way.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/layout/test_freeform.py -k "power_building or wireless_towers or fewer_power_sites" -x -q; echo $?
```
Expected: non-zero — the substation test finds item 2201, not 2212.

- [ ] **Step 3: Give `_Canvas` the resolved record**

In the `_Canvas` declaration (~`freeform.py:5864`), add a field defaulting to the Tesla Tower so every
existing construction site keeps today's behaviour without edits:

```python
    power_building: catalog.Building = field(
        default_factory=lambda: catalog.power_tower_building(catalog.DEFAULT_POWER_TOWER)
    )
```

Match `_Canvas`'s actual declaration style (it may be a `@dataclass` or a `slots` class — read it
first and follow it; if it is not a dataclass, add the attribute and set it in `__init__` with the
same default).

- [ ] **Step 4: Replace the eight hardcodes**

- `freeform.py:15473` (`_power_plan`): `tower = catalog.building(catalog.TESLA_TOWER_ID)` becomes
  `tower = canvas.power_building`.
- `freeform.py:15556` (`_power_plan`, the "skip already-placed towers" test):
  `if catalog.is_belt(b.item_id) or b.item_id == catalog.TESLA_TOWER_ID:` becomes
  `if catalog.is_belt(b.item_id) or b.item_id == tower.item_id:`. **Note:** this must compare against
  the chosen tower, not "any power node" — a build may legitimately contain other power buildings from
  the recipe set, and treating those as planner-placed towers would change the tesla arm.
- `freeform.py:15837` (`_power_plan` candidate): `item_id=catalog.TESLA_TOWER_ID,` becomes
  `item_id=tower.item_id,`. Confirm the neighbouring `width=`/`height=` already read `tower.width` /
  `tower.height`; if they are literal `1`s, replace them too.
- `freeform.py:16051` (`_place_power`): `tower = catalog.building(catalog.TESLA_TOWER_ID)` becomes
  `tower = canvas.power_building`.
- `freeform.py:16058` (`_place_power` emission): `item_id=catalog.TESLA_TOWER_ID,` becomes
  `item_id=tower.item_id,`.
- `freeform.py:5558` (`_power_coverage_discs`): delete the `tower = catalog.building(...)` line and
  add a keyword-only `tower: catalog.Building` parameter to the signature.
- `freeform.py:5740` (`_prepared_junction_ban`): same — delete the lookup, add a keyword-only
  `tower: catalog.Building` parameter.
- `freeform.py:5746` (`_prepared_junction_ban` obstacle): `item_id=catalog.TESLA_TOWER_ID,` becomes
  `item_id=tower.item_id,`; confirm its `width`/`height` read `tower.width`/`tower.height`.

Then update the callers of `_power_coverage_discs` and `_prepared_junction_ban` to pass
`tower=canvas.power_building` (they are in canvas scope; if a caller has no canvas, pass the record
down from the caller that does — do **not** re-resolve from the constant).

- [ ] **Step 5: Resolve from the spec in `_prepare_routing_problem`**

`_prepare_routing_problem` (`freeform.py:16553`) already has `spec: BuildSpec` and already resolves the
belt at `:16569`. Beside that, set the canvas field where the canvas is constructed:

```python
    power_building = catalog.power_tower_building(spec.power_tower_item_id)
```

and pass `power_building=power_building` into the `_Canvas(...)` construction in this function. Grep
for every `_Canvas(` construction reachable from a layout run; the ones that do not have a spec keep
the default.

- [ ] **Step 6: Run the new tests and the whole freeform suite**

```bash
uv run pytest tests/layout/test_freeform.py -q; echo $?
```
Expected: exit code 0. `tests/layout/test_freeform.py` has ~40 existing assertions on
`catalog.TESLA_TOWER_ID` — they must all still pass unchanged, which is the default-arm proof at unit
scale.

- [ ] **Step 7: Prove the default arm is byte-identical**

```bash
mkdir -p docs/superpowers/evidence/2026-09-07-power-tower
URL=$(uv run python -c "from flab2bp.bench.corpus import URL_CORPUS; print(next(iter(URL_CORPUS.values())).url)")
uv run flab2bp "$URL" --strategy freeform --budget 30 > /tmp/pt-head.txt
git stash && uv run flab2bp "$URL" --strategy freeform --budget 30 > /tmp/pt-base.txt; git stash pop
diff /tmp/pt-base.txt /tmp/pt-head.txt && echo "BYTE IDENTICAL" \
  | tee docs/superpowers/evidence/2026-09-07-power-tower/task3-default-identical.txt
```

If `URL_CORPUS` exposes its entries differently, read `src/flab2bp/bench/corpus.py` and adapt — the
requirement is one real corpus URL built on both sides of the change with identical stdout. If the
diff is non-empty, **stop and report**: the default arm has moved and the plan's core promise is
broken.

- [ ] **Step 8: Commit**

```bash
export GIT_EDITOR=true
git add -A src/flab2bp/layout/freeform.py tests/layout/test_freeform.py docs/superpowers/evidence/
git commit -m "feat(layout): place the spec's chosen power building at every power site"
```

---

### Task 4: Footprint-aware site claiming for a large power building (D7, D8)

A 1x1 tower needs one free tile. A 5x5 substation needs a 5x5 free block, its `(6, 6)` clearance
pitch, and the packer and router must see it as an obstacle. This is the one place where "it compiles
and places something" is not the same as "it is correct".

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` — `_power_plan` candidate feasibility (~15790-15841),
  `_place_power` (~16026-16058)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_Canvas.power_building`, `catalog.clearance(item_id, yaw)` (`catalog.py:1777`).
- Produces: no new public names — a behavioural guarantee, expressed as tests.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_substation_site_never_overlaps_another_building() -> None:
    placement = _lay_out(_a_wide_spec(power_tower_item_id="satellite-substation"))
    boxes = [
        (b.x, b.y, b.width, b.height, b.item_id)
        for b in placement.buildings
    ]
    power = [b for b in boxes if b[4] == 2212]
    assert power
    for px, py, pw, ph, _ in power:
        for bx, by, bw, bh, item in boxes:
            if item == 2212 and (bx, by) == (px, py):
                continue
            overlaps = (
                px < bx + bw and bx < px + pw and py < by + bh and by < py + ph
            )
            assert not overlaps, f"substation at {(px, py)} overlaps item {item} at {(bx, by)}"


def test_no_belt_or_sorter_tile_sits_inside_a_substation(  # D8: certify() cannot see this
) -> None:
    placement = _lay_out(_a_wide_spec(power_tower_item_id="satellite-substation"))
    subs = [(b.x, b.y, b.width, b.height) for b in placement.buildings if b.item_id == 2212]
    assert subs
    carriers = [
        (b.x, b.y)
        for b in placement.buildings
        if catalog.is_belt(b.item_id) or catalog.is_sorter(b.item_id)
    ]
    for sx, sy, sw, sh in subs:
        for cx, cy in carriers:
            assert not (sx <= cx < sx + sw and sy <= cy < sy + sh), (
                f"belt/sorter tile {(cx, cy)} inside substation at {(sx, sy)}"
            )


def test_a_substation_build_certifies_clean() -> None:
    placement = _lay_out(_a_wide_spec(power_tower_item_id="satellite-substation"))
    report = validate.certify(placement, expect_power=True)
    assert not report.findings, [f.rule for f in report.findings]
```

Adapt `validate.certify`'s call shape to whatever the existing freeform tests use (read the module's
existing `certify` calls). Note the two loops above each build their list once and then iterate — that
is a nested comparison over two prepared lists, not a `for b in buildings` rescan inside a loop, so it
satisfies the constraint.

- [ ] **Step 2: Run to verify — and record which ones fail**

```bash
uv run pytest tests/layout/test_freeform.py -k "substation" -x -q; echo $?
```
Some of these may already pass if `_power_plan` happens to reserve the footprint. **Record exactly
which pass and which fail before changing anything** — that determines whether this task is a fix or a
confirmation. Write the result to
`docs/superpowers/evidence/2026-09-07-power-tower/task4-before.txt`.

- [ ] **Step 3: Make the candidate feasibility footprint-aware**

Read `_power_plan`'s candidate loop (~`freeform.py:15790-15841`). It proposes a site `(x, y)` and
builds a `PlacedBuilding` candidate. Wherever it asks the canvas whether the site is free, that
question must cover the full `tower.width x tower.height` rectangle anchored the same way
`_place_power` anchors it, not a single tile. Concretely, before accepting a candidate site:

```python
        if not canvas.fits(site[0], site[1], tower.width, tower.height):
            continue
```

Use the canvas's real free-space predicate — read `_Canvas` for the existing method (it is whatever
`_emit_strip` and `_place_power` already use to test placement; if `_place_power` calls
`canvas.add(..., solid=True)` unconditionally, find the predicate the packer uses and reuse it). If no
such predicate exists, add one that tests every tile of the rectangle against `canvas.blocked` and
`canvas.keep_out`. **Do not invent a second occupancy model** — reuse the canvas's.

Then confirm the spacing tie-break at `freeform.py:15596-15603` uses
`rules.power_node_keepout_offsets(tower.power_node, tower.power_node)` with the *chosen* tower on both
sides (it already reads `tower`, so it follows automatically once Task 3 rebound `tower`).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/layout/test_freeform.py -k "substation" -q; echo $?
uv run pytest tests/layout/test_freeform.py -q; echo $?
```
Expected: exit code 0 for both. The second run re-proves the tesla arm did not move.

- [ ] **Step 5: Re-prove the default arm is still byte-identical**

Repeat Task 3 Step 7 and write the result to
`docs/superpowers/evidence/2026-09-07-power-tower/task4-default-identical.txt`.

- [ ] **Step 6: Commit**

```bash
export GIT_EDITOR=true
git add -A src/flab2bp/layout/freeform.py tests/layout/test_freeform.py docs/superpowers/evidence/
git commit -m "fix(layout): reserve the full footprint of a large power building"
```

---

### Task 5: Make the bench metrics power-generic

**Files:**
- Modify: `src/flab2bp/bench/metrics.py:18,65`
- Test: `tests/bench/test_metrics.py` (find the real path; if no such module exists, add the tests to
  whichever module already imports `bench.metrics`)

**Interfaces:**
- Consumes: `catalog.building(item_id).is_power_node`.
- Produces: `metrics.measure(...)["towers"]` (or the existing field name) counts **any** power node,
  not only item 2201.

- [ ] **Step 1: Write the failing test**

```python
def test_measure_counts_a_substation_as_a_tower() -> None:
    buildings = [_a_building(item_id=2212, width=5, height=5)]
    assert measure(buildings).towers == 1


def test_measure_excludes_a_substation_from_the_machine_count() -> None:
    buildings = [_a_building(item_id=2212, width=5, height=5)]
    assert measure(buildings).machines == 0
```

Adapt `_a_building` and the result accessor (`.towers` vs `["towers"]`) to what `metrics.measure`
actually returns — read `src/flab2bp/bench/metrics.py:55-75` first.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/bench/ -k "substation" -x -q; echo $?
```
Expected: non-zero — a substation counts as a machine and not as a tower.

- [ ] **Step 3: Implement**

`metrics.py:18`:

```python
    if b.item_id == catalog.SPLITTER_ID or catalog.building(b.item_id).is_power_node:
        return False
```

`metrics.py:65`:

```python
    towers = sum(1 for b in buildings if catalog.building(b.item_id).is_power_node)
```

`catalog.building` is a cached lookup, so this is one dict hit per building — no rescan. If it turns
out not to be cached, build `power_ids = {catalog.POWER_TOWER_CHOICES...}`-style index once above the
loop and test membership; do not call an uncached loader per building.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/bench/ -q; echo $?
```
Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
export GIT_EDITOR=true
git add -A src/flab2bp/bench/metrics.py tests/
git commit -m "fix(bench): count any power node as a tower, not only the Tesla Tower"
```

---

### Task 6: CLI flag, pipeline parameter, and the description line

**Files:**
- Modify: `src/flab2bp/pipeline.py` — `build()` signature (~639-670), the spec-construction call, the
  description f-string (1264-1273), and a new `_power_note` beside `_prime_note` (482-502)
- Modify: `src/flab2bp/cli.py` — argparse (~372-435), the `pipeline.build(...)` call (~556-566)
- Test: `tests/test_pipeline.py`, `tests/test_cli.py` (use the real module names in this repo)

**Interfaces:**
- Consumes: `catalog.POWER_TOWER_CHOICES`, `BuildSpec.power_tower_item_id`.
- Produces:
  - `pipeline.build(..., power_tower: str | None = None)` — a **choice name** (`tesla` /
    `substation` / `wireless`) or `None` meaning "nothing explicit was said, fall back to the URL then
    the default".
  - `pipeline.POWER_TOWER_CHOICES` re-exported for the CLI's `choices=`.
  - `pipeline._power_note(spec) -> str` — `""` for tesla, `f"; power: {name}"` otherwise.
  - CLI flag `--power-tower {tesla,substation,wireless}` (no default, so `None` means unset).

- [ ] **Step 1: Write the failing tests**

```python
def test_power_tower_flag_reaches_the_spec(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def spy(*args: object, **kwargs: object) -> object:
        seen.update(kwargs)
        return _a_spec_set()

    monkeypatch.setattr(pipeline, "_candidates_for", spy)  # real name from pipeline.py
    pipeline.build(URL, power_tower="substation", budget=1)
    assert seen["power_tower_item_id"] == "satellite-substation"


def test_the_description_names_a_non_default_power_building() -> None:
    build = pipeline.build(URL, power_tower="substation", budget=1)
    assert "Satellite Substation" in build.blueprint.description


def test_the_description_is_unchanged_for_the_default() -> None:
    build = pipeline.build(URL, budget=1)
    assert "power:" not in build.blueprint.description


def test_cli_rejects_an_unknown_power_tower() -> None:
    with pytest.raises(SystemExit):
        cli.main([URL, "--power-tower", "nuclear"])
```

Replace `_candidates_for` with the real function `pipeline.build` calls to make its `BuildSpecSet`
(read `pipeline.py` around 850-880), and `build.blueprint.description` with the real accessor (the
description is set at `pipeline.py:1264-1273` via `replace(marked, description=...)`).

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_pipeline.py tests/test_cli.py -k power_tower -x -q; echo $?
```
Expected: non-zero — `build()` has no `power_tower` keyword.

- [ ] **Step 3: Add the pipeline parameter and the note**

In `src/flab2bp/pipeline.py`, beside `_prime_note` (482-502):

```python
def _power_note(spec: BuildSpec) -> str:
    """Name the power building when it is not the default one.

    Empty for the Tesla Tower so every pre-existing description is unchanged,
    which is what keeps the default arm byte-identical.
    """
    if spec.power_tower_item_id == catalog.DEFAULT_POWER_TOWER:
        return ""
    return f"; power: {catalog.power_tower_building(spec.power_tower_item_id).name}"
```

Append it in the description f-string at `pipeline.py:1264-1273`:

```python
        description=(
            f"flab2bp {sname} layout, {spec.label} candidate, "
            f"{spec.machine_count} machines, {placement.area} tiles"
            f"{_prime_note(spec, marked)}"
            f"{_power_note(spec)}"
        ),
```

Add the `build()` parameter (near `no_proliferator` at `pipeline.py:668`):

```python
    power_tower: str | None = None,
```

and resolve it once, before specs are built, applying the precedence from D6:

```python
    chosen = _resolve_power_tower(power_tower, request)
```

with:

```python
def _resolve_power_tower(explicit: str | None, request: LabRequest) -> str:
    """Explicit flag beats the URL's machine rank beats the Tesla Tower (D6).

    The lab dataset ranks ``satellite-substation`` and ``wireless-power-tower``
    as machines but not ``tesla-tower``, so a URL can only ever opt in to a
    non-default building -- "the URL said nothing" and "the URL said tesla" are
    the same state, and both land on the default.
    """
    if explicit is not None:
        try:
            return catalog.POWER_TOWER_CHOICES[explicit]
        except KeyError:
            allowed = ", ".join(sorted(catalog.POWER_TOWER_CHOICES))
            raise ValueError(f"power_tower must be one of {allowed}; got {explicit!r}") from None
    known = set(catalog.POWER_TOWER_CHOICES.values())
    for lab_id in request.machine_rank_ids or ():
        if lab_id in known:
            return lab_id
    return catalog.DEFAULT_POWER_TOWER
```

Pass `power_tower_item_id=chosen` into the spec construction Task 2 parameterised.

- [ ] **Step 4: Add the CLI flag**

In `src/flab2bp/cli.py`, beside the other build flags (~429):

```python
    ap.add_argument(
        "--power-tower",
        choices=sorted(catalog.POWER_TOWER_CHOICES),
        default=None,
        help=(
            "which building powers the blueprint: tesla (default), substation "
            "(Satellite Substation, ~6x the coverage area, 5x5 footprint), or "
            "wireless (Wireless Power Tower, long link, short reach). "
            "Overrides a power building named in the URL's machine ranks."
        ),
    )
```

and at the `pipeline.build(...)` call (~566): `power_tower=args.power_tower,`.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_pipeline.py tests/test_cli.py -q; echo $?
```
Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
export GIT_EDITOR=true
git add -A src/flab2bp/pipeline.py src/flab2bp/cli.py tests/
git commit -m "feat(cli): add --power-tower and name the choice in the description"
```

---

### Task 7: The URL machine-rank default

Task 6 wrote `_resolve_power_tower`; this task proves the URL half of the precedence against real
FactorioLab URLs and locks D6's asymmetry (a URL cannot name the Tesla Tower).

**Files:**
- Test only: `tests/lab/test_url.py` and `tests/test_pipeline.py`
- Modify (only if the tests find a gap): `src/flab2bp/pipeline.py`

**Interfaces:**
- Consumes: `LabRequest.machine_rank_ids` (`lab/url.py:217`), `pipeline._resolve_power_tower`.
- Produces: no new names.

- [ ] **Step 1: Write the tests**

```python
def test_a_url_machine_rank_selects_the_substation() -> None:
    request = _request_with_machine_rank(["satellite-substation", "assembling-machine-3"])
    assert pipeline._resolve_power_tower(None, request) == "satellite-substation"


def test_the_first_power_building_in_the_rank_wins() -> None:
    request = _request_with_machine_rank(
        ["wireless-power-tower", "satellite-substation"]
    )
    assert pipeline._resolve_power_tower(None, request) == "wireless-power-tower"


def test_an_explicit_choice_beats_the_url() -> None:
    request = _request_with_machine_rank(["satellite-substation"])
    assert pipeline._resolve_power_tower("tesla", request) == "tesla-tower"


def test_a_rank_without_a_power_building_leaves_the_default() -> None:
    request = _request_with_machine_rank(["assembling-machine-3", "smelter-2"])
    assert pipeline._resolve_power_tower(None, request) == "tesla-tower"


def test_an_empty_rank_leaves_the_default() -> None:
    assert pipeline._resolve_power_tower(None, _request_with_machine_rank(None)) == "tesla-tower"


def test_the_lab_dataset_ranks_the_substation_but_not_the_tesla_tower() -> None:
    """D6: a URL can only opt in to a non-default power building."""
    import json
    from pathlib import Path

    hash_path = Path(url.__file__).parent / "vendored" / "hash.json"
    machines = set(json.loads(hash_path.read_text())["machines"])
    assert "satellite-substation" in machines
    assert "wireless-power-tower" in machines
    assert "tesla-tower" not in machines
```

Write `_request_with_machine_rank` as a small helper that builds a `LabRequest` with the given
`machine_rank_ids` (use the module's existing request fixture if there is one).

- [ ] **Step 2: Run them**

```bash
uv run pytest tests/lab/test_url.py tests/test_pipeline.py -k "machine_rank or power_tower" -q; echo $?
```
Expected: exit code 0 (Task 6 already implemented the resolver). If any fail, fix
`_resolve_power_tower` — the tests are the specification.

- [ ] **Step 3: Add one end-to-end URL test**

```python
def test_a_url_naming_the_substation_builds_with_substations() -> None:
    build = pipeline.build(_URL_WITH_SUBSTATION_IN_MMR, budget=1)
    power = [b for b in build.placement.buildings if catalog.building(b.item_id).is_power_node]
    assert power and {b.item_id for b in power} == {2212}
```

Construct `_URL_WITH_SUBSTATION_IN_MMR` by taking a small corpus URL and adding/extending its `mmr`
parameter so it names `satellite-substation`. `mmr` is a `~`-joined list of base-64 indices into
`hash.json`'s `machines` array (`lab/params.py:282-341`); read `parse_array` and build the encoded
value with the repo's own encoder rather than hand-rolling one. Record the URL you built in
`docs/superpowers/evidence/2026-09-07-power-tower/task7-url.txt`.

- [ ] **Step 4: Commit**

```bash
export GIT_EDITOR=true
git add -A tests/ src/flab2bp/pipeline.py docs/superpowers/evidence/
git commit -m "test: the URL machine rank selects the power building"
```

---

### Task 8: Web backend — option, validation, pipeline call, echo

**Files:**
- Modify: `src/flab2bp/web/jobs.py` — `Options` (64-155), `parse_options` (~274-325), `run_build`
  (399-414), `Builder.snapshot` (592-596)
- Modify: `src/flab2bp/web/payload.py` — `describe()`, add the resolved building name to the result
- Test: `tests/web/test_options.py`, `tests/web/test_jobs.py`, `tests/web/test_payload.py`

**Interfaces:**
- Consumes: `pipeline.build(power_tower=...)` (Task 6), `catalog.POWER_TOWER_CHOICES`.
- Produces:
  - `Options.power_tower: str | None = None` — a choice name or `None` for "auto".
  - Request key `"power_tower"`, accepting `"auto" | "tesla" | "substation" | "wireless"`.
  - `snapshot()["options"]["power_tower"]` — echoes `"auto"` when unset.
  - `describe()` result key `"power_building"` — the resolved building's display name, e.g.
    `"Satellite Substation"`.

Note: the web path calls `pipeline.build()` **in process**; it does not build a CLI argv. Do not add
flag-string plumbing.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_options.py`:

```python
def test_power_tower_is_optional_and_explicit() -> None:
    assert parse_options({"url": URL}).power_tower is None
    assert parse_options({"url": URL, "power_tower": "auto"}).power_tower is None
    assert parse_options({"url": URL, "power_tower": "substation"}).power_tower == "substation"
    assert parse_options({"url": URL, "power_tower": "wireless"}).power_tower == "wireless"
    assert parse_options({"url": URL, "power_tower": "tesla"}).power_tower == "tesla"
    with pytest.raises(InvalidOptions, match="power_tower"):
        parse_options({"url": URL, "power_tower": "nuclear"})
```

`tests/web/test_jobs.py`:

```python
def test_explicit_power_tower_reaches_pipeline(
    self, monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
) -> None:
    seen: dict[str, object] = {}

    def spy(url: str, **kwargs: object) -> pipeline.Build:
        seen.update(kwargs)
        return small_build

    monkeypatch.setattr(pipeline, "build", spy)
    run_build(Options(url=URL, power_tower="substation"), lambda _s: None)
    assert seen["power_tower"] == "substation"


def test_the_snapshot_echoes_auto_when_no_power_tower_was_chosen(self) -> None:
    builder = _a_builder(Options(url=URL))
    assert builder.snapshot()["options"]["power_tower"] == "auto"
```

`tests/web/test_payload.py`:

```python
def test_the_result_names_the_power_building() -> None:
    result = describe(_a_build())
    assert result["power_building"] == "Tesla Tower"
```

Adapt `_a_builder` / `_a_build` to the fixtures those modules already use.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/web/ -k power_tower -x -q; echo $?
```
Expected: non-zero.

- [ ] **Step 3: Implement**

`Options` (`jobs.py`, beside `proliferator_tier`):

```python
    power_tower: str | None = None
```

`parse_options` (`jobs.py`, following the `proliferator_tier` match-block style at 274-287):

```python
    raw_power = raw.get("power_tower", "auto")
    if raw_power in (None, "auto"):
        power_tower = None
    elif raw_power in catalog.POWER_TOWER_CHOICES:
        power_tower = raw_power
    else:
        allowed = ", ".join(sorted(catalog.POWER_TOWER_CHOICES))
        raise InvalidOptions(f"'power_tower' must be one of auto, {allowed}")
```

and pass `power_tower=power_tower` into the `Options(...)` construction (~313-325).

`run_build` (`jobs.py:399-414`): add `power_tower=options.power_tower,` to the `pipeline.build(...)`
kwargs.

`Builder.snapshot` (`jobs.py:592-596`): add

```python
        "power_tower": job.options.power_tower or "auto",
```

`payload.describe()`: add the resolved building's display name. Read the `Build` object for the spec
it was built from and use
`catalog.power_tower_building(spec.power_tower_item_id).name`. If `describe()` has no spec in scope,
carry the name on the `Build` where `pipeline.build` already assembles it — do not re-resolve from the
URL inside `payload.py`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/web/ -q; echo $?
```
Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
export GIT_EDITOR=true
git add -A src/flab2bp/web/ tests/web/
git commit -m "feat(web): accept a power_tower option and report the chosen building"
```

---

### Task 9: Web front end — the select, the report line, the viewer check

**Files:**
- Modify: `web/src/api/build.ts` — zod enum (~40), `BuildOptions` (209-228), `DEFAULT_OPTIONS`
  (237-253), `BuildResult` (~143) for `power_building`
- Modify: `web/src/ui/BuildPanel.tsx` — a new select beside the proliferator select (221-235)
- Modify: `web/src/ui/BuildReport.tsx` — show the power building in the `<dl>` (108-150)
- Test: `web/tests/ui/BuildPanel.test.tsx`, `web/tests/ui/BuildReport.test.tsx`

**Interfaces:**
- Consumes: request key `power_tower`, result key `power_building` (Task 8).
- Produces: `PowerTower = z.enum(['auto', 'tesla', 'substation', 'wireless'])`; `DEFAULT_OPTIONS.power_tower === 'auto'`;
  a select labelled exactly `Power tower`; a report row labelled exactly `Power`.

Runner is **rstest** (`web/package.json`: `"test": "rstest run"`), not vitest or bun test.

- [ ] **Step 1: Write the failing tests**

`web/tests/ui/BuildPanel.test.tsx`:

```tsx
test('power tower exposes auto and every power building', () => {
  mount();
  const select = screen.getByLabelText('Power tower');
  for (const label of [
    'URL selection (Tesla Tower if unspecified)',
    'Tesla Tower',
    'Satellite Substation',
    'Wireless Power Tower',
  ]) {
    expect(within(select).getByText(label)).toBeTruthy();
  }
});

test.each([
  ['Satellite Substation', 'substation'],
  ['Wireless Power Tower', 'wireless'],
  ['Tesla Tower', 'tesla'],
])('submits an explicit %s power tower', async (_label, choice) => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  fireEvent.change(screen.getByLabelText('Power tower'), {
    target: { value: choice },
  });
  build();

  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.power_tower).toBe(choice);
});

test('defaults the power tower to auto', async () => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  build();
  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.power_tower).toBe('auto');
});
```

`web/tests/ui/BuildReport.test.tsx`:

```tsx
test('names the power building', () => {
  render(<BuildReport result={aResult({ power_building: 'Satellite Substation' })} />);
  expect(screen.getByText('Satellite Substation')).toBeTruthy();
});
```

Match the surrounding tests' imports and helpers (`mount`, `serving`, `aJob`, `build`, `aResult`) —
read the neighbouring tests first; `within` may need adding to the `@testing-library` import.

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/power-tower/web
bun install
bun run test 2>&1 | tail -30
```
Expected: the new tests fail — no element labelled `Power tower`.

- [ ] **Step 3: Implement the schema and default**

`web/src/api/build.ts`, beside `ProliferatorTier` (~40):

```ts
export const PowerTower = z.enum(['auto', 'tesla', 'substation', 'wireless']);
```

Add `power_tower: PowerTower` to the `BuildOptions` object schema (209-228), add
`power_tower: 'auto'` to `DEFAULT_OPTIONS` (237-253), and add `power_building: z.string().optional()`
to the `BuildResult` schema (~143).

- [ ] **Step 4: Implement the select**

`web/src/ui/BuildPanel.tsx` — add `const powerTowerId = useId();` beside `proliferatorTierId`
(line 44), and after the proliferator select (235):

```tsx
<label htmlFor={powerTowerId}>Power tower</label>
<select
  id={powerTowerId}
  value={options.power_tower}
  onChange={(event) => {
    const choice = PowerTower.safeParse(event.target.value);
    if (choice.success) set('power_tower', choice.data);
  }}
>
  <option value="auto">URL selection (Tesla Tower if unspecified)</option>
  <option value="tesla">Tesla Tower</option>
  <option value="substation">Satellite Substation</option>
  <option value="wireless">Wireless Power Tower</option>
</select>
```

Import `PowerTower` from `../api/build` alongside `ProliferatorTier`.

- [ ] **Step 5: Implement the report row**

`web/src/ui/BuildReport.tsx`, in the `<dl>` (108-150), following the shape of the rows around it:

```tsx
{result.power_building ? (
  <>
    <dt>Power</dt>
    <dd>{result.power_building}</dd>
  </>
) : null}
```

- [ ] **Step 6: Run the web tests, typecheck and lint**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/power-tower/web
bun run test 2>&1 | tail -20
bun run typecheck 2>&1 | tail -20
bun run lint 2>&1 | tail -20
```
Expected: all clean. (Read `web/package.json` for the exact script names if `typecheck`/`lint` differ.)

- [ ] **Step 7: Verify the viewer renders a substation (D11 — a check, not a change)**

Build one substation blueprint, load it in the viewer harness, and confirm: (a) a 5x5 box appears at
each power site, (b) it carries no endpoint icon and no recipe/filter icon. The cheapest form of this
is a test over the model builder rather than a browser:

```tsx
test('a substation renders as a 5x5 box with no icons', () => {
  const model = buildModel(aBlueprintWithSubstations());
  const sub = model.buildings.find((b) => b.itemId === 2212);
  expect(sub?.size).toEqual([5, 5]);
  const overlays = buildOverlays(model, { endpointIcons: true });
  expect(overlays.filter((o) => o.at === sub?.position)).toHaveLength(0);
});
```

Adapt to the real `buildModel` / `buildOverlays` signatures in `web/src/model/`. If a model-level test
is not feasible, capture a screenshot with the existing `scripts/web_smoke.py` harness and save it
under the evidence directory. **Never commit `web/dist`** — rebuild only to test.

- [ ] **Step 8: Commit**

```bash
export GIT_EDITOR=true
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/power-tower
git add -A web/src web/tests docs/superpowers/evidence/
git commit -m "feat(web): select the power building and show it in the report"
```

Confirm with `git status --short` that no `web/dist` path was staged.

---

### Task 10: Validator tests (D4 — tests only, no validator change)

**Files:**
- Test: `tests/layout/test_validate.py`

**Interfaces:**
- Consumes: `validate.certify`, `power.coverage`, `power.connectivity`, `game.power_too_close`.
- Produces: no new names.

- [ ] **Step 1: Write the tests**

```python
def test_a_substation_blueprint_passes_coverage_and_connectivity() -> None:
    sub = catalog.building(2212)
    placement = _placement(
        [
            _machine(x=0, y=0),
            _power(item_id=2212, x=10, y=10),
        ]
    )
    report = validate.certify(placement, expect_power=True)
    rules_hit = {f.rule for f in report.findings}
    assert "power.coverage" not in rules_hit
    assert "power.connectivity" not in rules_hit


def test_two_substations_beyond_the_link_distance_break_connectivity() -> None:
    sub = catalog.building(2212)
    far = int(sub.connect_distance) + 5
    placement = _placement([_power(2212, 0, 0), _power(2212, far, 0)])
    report = validate.certify(placement, expect_power=True)
    assert "power.connectivity" in {f.rule for f in report.findings}


def test_a_machine_outside_the_substation_cover_radius_breaks_coverage() -> None:
    sub = catalog.building(2212)
    far = int(sub.cover_radius) + 5
    placement = _placement([_power(2212, 0, 0), _machine(x=far, y=0)])
    report = validate.certify(placement, expect_power=True)
    assert "power.coverage" in {f.rule for f in report.findings}


def test_two_substations_inside_the_keepout_are_convicted() -> None:
    """The PowerTooClose tier is the same 12.25 world-units-squared bound for
    every ordinary power node (D3), so a substation pair is convicted at the
    same separation a Tesla pair is."""
    placement = _placement([_power(2212, 0, 0), _power(2212, 1, 0)])
    report = validate.certify(placement, expect_power=True)
    assert "game.power_too_close" in {f.rule for f in report.findings}


def test_a_substation_pair_at_the_keepout_bound_is_clean() -> None:
    placement = _placement([_power(2212, 0, 0), _power(2212, 6, 0)])
    report = validate.certify(placement, expect_power=True)
    assert "game.power_too_close" not in {f.rule for f in report.findings}
```

Reuse the module's existing `_placement` / `_machine` helpers and its `TOWER = 2201` fixtures at
lines 61-62 as the template; add a `_power(item_id, x, y)` helper that stamps the right
`width`/`height` from `catalog.building(item_id)`. The exact separations in the last two tests must be
**derived** from `catalog` and `rules.POWER_TOO_CLOSE_SQR`, not guessed — if a chosen separation lands
on the wrong side of the bound, compute it rather than nudging the number until the test passes.

- [ ] **Step 2: Run them**

```bash
uv run pytest tests/layout/test_validate.py -k "substation" -q; echo $?
```
Expected: exit code 0 with no production change (D4). If any fail, the validator is **not** as generic
as D4 claims — report that as a finding before changing any production code.

- [ ] **Step 3: Commit**

```bash
export GIT_EDITOR=true
git add -A tests/layout/test_validate.py
git commit -m "test(validate): coverage, connectivity and keep-out for the Satellite Substation"
```

---

### Task 11: Gate, evidence, and the hierarchical-v4 follow-up note

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-power-tower/` (tables, JSON, logs)
- Create: `docs/superpowers/plans/2026-09-07-power-tower-followup.md` (the hierarchical-v4 seam note)

**Interfaces:** none — this task produces evidence and a note.

Run **one build at a time**. Before each long run, record CPU pressure with
`vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'` beside the timing; do not wait for it to
drop.

- [ ] **Step 1: Gate (a) — default arm vs master, full 72-cell corpus**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/power-tower
E=docs/superpowers/evidence/2026-09-07-power-tower
mkdir -p $E
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "cpu_runnable_mean", sum/5}' > $E/gate-a-load.txt
uv run python scripts/audit.py --budget 30 --json $E/gate-a-head.json
```

Then the same at the merge base `a1401518` (use the master checkout or `git stash`; do **not** rebase),
producing `$E/gate-a-base.json`, and compare:

```bash
uv run python scripts/audit_compare.py $E/gate-a-base.json $E/gate-a-head.json | tee $E/gate-a-compare.txt
```

`audit.py` prints NOT CLEAN whenever any cell refuses, so **do not read the headline** — compare the
CLEAN **counts** and the **named differing cells**. Requirement: **zero regressions**. Record the
count on each side and any cell that changed in either direction.

- [ ] **Step 2: Gate (a) continued — determinism on 12 cells**

Re-run 12 deterministic corpus cells twice at HEAD and confirm byte-identical output both times, and
identical to the base run:

```bash
uv run python scripts/audit.py --budget 30 --json $E/gate-a-det-1.json --url-ids <12 ids>
uv run python scripts/audit.py --budget 30 --json $E/gate-a-det-2.json --url-ids <12 ids>
diff $E/gate-a-det-1.json $E/gate-a-det-2.json && echo "DETERMINISTIC 12/12" | tee $E/gate-a-determinism.txt
```

Read `scripts/audit.py --help` for the real flag name for selecting url ids (the parser at
`audit.py:578-592` refuses unknown ids and prints the corpus list, which is also how you enumerate
them).

- [ ] **Step 3: Gate (b) — substation arm on the full corpus**

Add a way to run the corpus with a power choice. `audit.py` builds through the pipeline; give it a
`--power-tower` passthrough matching the CLI flag (a few lines beside the existing `--budget` at
`audit.py:746`), then:

```bash
uv run python scripts/audit.py --budget 30 --power-tower substation --json $E/gate-b-substation.json
```

Produce a **per-cell table** in `$E/gate-b-table.md` with columns: cell, tesla CLEAN, substation CLEAN,
tesla towers, substation towers, tesla area, substation area, substation wall-clock. Expect far fewer
substation towers (D-note: ~6x). **Report honestly if area or CLEAN moves** — a substation arm that
loses cells is a real result, not a failure to hide. Also report the D8 caveat beside the table: belt
collisions against a substation are suppressed by `UNPLACED_LOW_CONFIDENCE_FOOTPRINTS`, so cite the
Task 4 direct-overlap test as the belt evidence rather than CLEAN.

- [ ] **Step 4: Gate (c) — the six reported URL/strategy pairs with `--power-tower substation`**

The pairs are in `docs/superpowers/evidence/2026-09-07-coater-placed-gate`. Build each with
`--power-tower substation --budget 30`, certify green, and record the six results in
`$E/gate-c-reported-urls.md` (URL, strategy, CLEAN, tower count, area, wall-clock).

- [ ] **Step 5: Gate (d) — paste-validate one substation blueprint against the game's C#**

`dotnet` is on PATH at `/home/dannyb/.local/share/mise/installs/dotnet/latest/dotnet` and the oracle
lives in `oracle/`. The marker is declared at `pyproject.toml:94`
(`dotnet: differential-tests against the game's own C# in oracle/`).

```bash
uv run pytest -m dotnet -q 2>&1 | tail -20; echo $?
```

Then paste-validate one substation blueprint through the same oracle path those tests use and record
the transcript in `$E/gate-d-dotnet.txt`. If the oracle cannot run (game not installed), say so
explicitly in the report — an unavailable validator is a stated limitation, not a pass.

- [ ] **Step 6: Verification at HEAD**

```bash
uv run ruff check . 2>&1 | tail -5
uv run ruff format --check . 2>&1 | tail -5
uv run mypy src 2>&1 | tail -5
uv run pytest -q 2>&1 | tail -20; echo "EXIT $?"
cd web && bun run typecheck && bun run lint && bun run test; cd ..
```

The pytest summary line does not print in this environment — the **exit code** is the result. Name the
two known reds explicitly and confirm nothing else is red.

- [ ] **Step 7: Write the hierarchical-v4 follow-up note**

Create `docs/superpowers/plans/2026-09-07-power-tower-followup.md` stating, for whoever merges
`hierarchical-v4`:

- `BuildSpec.power_tower_item_id` (`src/flab2bp/spec.py`) is the single source of the choice.
- `catalog.power_tower_building(lab_id)` (`src/flab2bp/dsp/catalog.py`) is the only resolver.
- `_Canvas.power_building` (`src/flab2bp/layout/freeform.py`) carries the resolved record inside a
  layout run; anything running in canvas scope reads it and needs no parameter.
- The sub-block rebuilds at `layout/hierarchy/partition.py:328` and `:427` already copy the field;
  any **new** `BuildSpec(...)` construction that v4 adds must copy it too or that block silently
  reverts to the Tesla Tower.
- v4's power infill in `compose.py`/`freeform.py` must call `catalog.power_tower_building(spec.power_tower_item_id)`
  — **one line** — instead of `catalog.building(catalog.TESLA_TOWER_ID)`.
- `hierarchy/compose.py` itself needs no change (D9): `canvas_for` routes power buildings to the
  generic `solid=True` branch by elimination.
- The trap: a 5x5 substation inside a composed block must be an obstacle to the *parent's* router too;
  v4 should reuse the Task 4 direct-overlap test at block boundaries.

- [ ] **Step 8: Commit the evidence and the note**

```bash
export GIT_EDITOR=true
git add -A docs/superpowers/evidence/2026-09-07-power-tower docs/superpowers/plans/2026-09-07-power-tower-followup.md scripts/audit.py
git commit -m "docs: power-tower gate evidence and the hierarchical-v4 seam note"
git status --short   # must be clean; nothing under .superpowers/ or web/dist
git rev-parse HEAD
```

---

## Self-review

**Spec coverage.** Brief item 1 (single `power_tower` choice, resolved once, no caller keeps
`TESLA_TOWER_ID`) — Tasks 1, 2, 3, 5; the "grep proves it" check is Task 3 Step 4 plus Task 5, after
which the only surviving `TESLA_TOWER_ID` uses are the constant's definition, the registry entry, and
tests. Item 2 (three inputs, one precedence, documented) — Tasks 6, 7, 8, 9; D6 states the precedence
and Task 7 tests all four branches of it. Item 3 (planner correctness for a big radius) — Tasks 3 and
4; D7 and D12 name the risks. Item 4 (validator unchanged in meaning) — Task 10, tests only, per D4.
Item 5 (web UI) — Tasks 8 and 9, including the viewer/endpoint-icon check per D11. Item 6 (gate
a-d) — Task 11.

**Placeholder scan.** Every code step carries real code. Four steps deliberately say "read the
neighbouring code and match its shape" (Task 1 Step 4 registry `_e` signature, Task 2 Step 1 partition
fixtures, Task 3 Step 3 `_Canvas` declaration style, Task 9 Step 1 test helpers) — these are
name-discovery instructions with the exact file and line to read, not deferred design.

**Type consistency.** `power_tower_item_id` is a **lab id string** (`"satellite-substation"`)
everywhere on `BuildSpec` and in `candidates.py`/`partition.py`. `power_tower` is a **choice name**
(`"substation"`) everywhere on the CLI, `pipeline.build`, `web.Options` and the web request.
`catalog.POWER_TOWER_CHOICES` maps the second to the first, and `_resolve_power_tower` is the single
crossing point. The web result key is `power_building` (a display name) and is distinct from both.

**Known gap, stated not hidden.** D8: `certify()` cannot convict a belt running through a Satellite
Substation, because item 2212 is in `LOW_CONFIDENCE_FOOTPRINTS`. Task 4's direct geometric test is the
substitute evidence and Task 11 Step 3 reports the caveat beside the gate table. Resolving the
low-confidence flag itself is explicitly out of scope.
