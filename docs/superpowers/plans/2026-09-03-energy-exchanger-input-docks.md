# Energy Exchanger Input Docks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Energy Exchanger blueprint paste with zero belt/collider convictions, and let a charge exchanger with two sinks for its product lay out, so the URL in `/home/dannyb/broke6.txt` builds clean on all six strategy/candidate pairs.

**Architecture:** Four code changes, ordered so the suite is green at every commit. First a shared predicate that asks the paste's own question -- does a belt on this tile probe into that building's build collider. Then the emitter's port approach uses it to pick a tap column whose in-collider tiles are the last hops into the port, and the strip's input lane is trimmed to reach that column. Then the strip planner sizes a belt-port host's output lanes by how many ports face the lane band, so the existing `_merge_lanes` machinery folds same-cargo destinations onto that one lane instead of asking the emitter to fan a single port across lane rows -- which was built four ways and measured, and does not work. Only then does `validate` stop skipping the buildings we place, because until the first three land that narrowing makes an Energy Exchanger unbuildable.

**Tech Stack:** Python 3.14, `uv`, `pytest`, `mypy`, `ruff`; `flab2bp.dsp.colliders` (a transcription of DSP's `CheckBuildConditions`), `flab2bp.layout.freeform`, `flab2bp.layout.slots`, `flab2bp.layout.validate`, Cython kernels under `src/flab2bp/layout/_*.pyx`.

**Spec:** `.superpowers/sdd/broke6/diagnosis.md` (the diagnosis is the spec: reproduction, mechanism with file:line, ruled-out alternatives, three fix options). Reviews: `.superpowers/sdd/broke6/plan-review-A.md`, `.superpowers/sdd/broke6/plan-review-B.md`.

## Global Constraints

- **Symbol work uses Serena.** `mcp__serena__find_symbol` to read a symbol,
  `mcp__serena__find_referencing_symbols` to find its call sites, Serena's
  editing tools to change it. LSP is the fallback when Serena returns nothing or
  something wrong. Grep is for strings and quoted names only.
- **When a signature changes, also grep for the QUOTED name.** Run
  `grep -rn '"<name>"' src tests scripts docs` and the single-quoted variant
  alongside `find_referencing_symbols`; a symbol reached by string is invisible
  to the language server.
- **No wall-clock tests.** Never assert on elapsed seconds in `pytest`.
- **Record `uptime` and `vmstat 1 3` before any timed run.** The box is never
  idle and its load is I/O wait; never wait for it to go quiet.
- **`registry.LintException` for colliding constants.** A new numeric literal in
  `layout/` that equals a game constant gets a `registry.LintException` entry
  naming module, top-level definition, value and why -- not a `# noqa`.
- **mypy stays at its 184-error baseline.** `uv run mypy src tests` must print
  `Found 184 errors in 16 files (checked 167 source files)`.
- **ruff clean.** `uv run ruff check .` and `uv run ruff format --check .` pass.
- **Explicit-path commits.** Every `git add` names files. Never `git add -A`,
  `git add .`, `git commit -a`, `git stash`, `git checkout --`, or `git reset`.
- **Commit trailers.** Every commit message ends with:

  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv
  ```

- **The validator is the arbiter.** No change may weaken `game.belt_collide` or
  `game.belt_crossing`, and no blueprint may be emitted that
  `colliders.stable_belt_collisions` convicts.
- **Every commit leaves `uv run pytest -q` green.** That is why the exemption
  narrowing is Task 4 and not Task 1: applied alone it turns
  `tests/layout/test_freeform.py:5355` and `:9414` red, because
  `_assert_energy_exchanger_port_routing` (`test_freeform.py:9354`) ends with
  `assert validate.certify(...).ok` and `freeform` refuses a placement its own
  validator rejects (`freeform.py:17027`).
- **No `.pyx` edits.** No task touches `src/flab2bp/layout/_*.pyx`, which is what
  makes Task 6's "copy the checkout's `.so` into the baseline archive" sound. If
  a task ever needs one, Task 6's baseline recipe must be rebuilt first.
- **The URL lives in `/home/dannyb/broke6.txt`.** Read it with
  `URL=$(head -1 /home/dannyb/broke6.txt)`; retyping corrupts the `.`/`-`
  characters in the FactorioLab payload.

## Measured ground truth this plan rests on

Everything below was re-measured against `688cbed` in a `git archive` copy with
the checkout's `.venv/bin/python`, with Tasks 1-3 implemented. Cited so no task
has to guess.

| Fact | Value |
| --- | --- |
| `catalog.clearance(2209, 0.0)` / footprint | `(10, 10)` / `(9, 9)` |
| Strip pitch actually used for a port-input host | `group.pitch_w + 1` = **11** (`freeform.py:2216`, `port_inputs`) |
| Exchanger strip, 2 machines | machines at `x=1` and `x=12`; input lane `x=1..19` |
| Machine 2's east dock | `(18, 6)`; `tap+1 = 19` is in the lane, `tap+2 = 20` is **not** |
| Why | `Strip.input_lane_tiles` (`freeform.py:1163`) trims the lane to `(machines-1)*pw + dock.cell[0] + 1 + 1` -- the `+ 1` hardcodes the old tap column. The **pitch is already wide enough** (the box is `machines*pw = 22` columns); the lane trim is the blocker. |
| After Tasks 1-3 | all six pairs build, `errors=0`, `stable_belt_collisions=0`; areas 1512 / 1785 / 1792 / 1568 / 1548 / 2262 (no-prolif / all-products / output-products, freeform then sequence-pair). `tests/layout/test_freeform.py` + `test_strip_variants.py`: 646 passed. |
| Two figures that need saying out loud | **(1) freeform/all-products reads 1785 here and 1505 in the bug report's own CLI run.** Same commit, same URL: CP-SAT is time-limited and multi-worker, so a single-policy 15 s `pipeline.build` and a three-policy CLI run explore differently. Run-to-run variation, not a regression -- and exactly what Task 6's baseline self-check exists to quantify. Do not treat either number as a target. **(2) sequence-pair/output-products goes 1909 -> 2262, +18.5%.** That arm previously laid out two output lane rows for the charge exchangers; capped to one, it packs a different and larger shape. It is the only figure that moves materially, it is still a *valid* layout where the freeform arm now wins at 1792, and `pipeline.build` picks the smallest valid result -- so the blueprint the user gets is smaller, not larger. Task 6's `--noise-area` geometric-mean check is what decides whether this is acceptable across the corpus; no corpus cell places a 2209, so it cannot show up there. |
| Before | 8 / 6 / REFUSED / 8 / 6 / 10 collisions, all hidden by the exemption |
| Same-cargo drain: four designs measured (Task 3) | (a) fan one port across two lane rows by tapping the lane tile the column feeds -- `_tap_source` fails **12/12** with `splitter-port` (that tile has two feeders), silently, `certify ok=True`. (b) tap one column east instead -- fails `belt-keepout`. (c) excuse the keep-out -- taps attach but the emitted splitters are convicted by our own `game.belt_collide` as unstable merges. (d) raise on failure -- `output-products` regresses to **REFUSED on both strategies**, because `_emit_strip`'s caller (`freeform.py:14146`) has no per-arrangement `try`. **(e) cap the lanes so the case never arises -- all six pairs clean, 646 tests pass.** Task 3 implements (e). |
| `strip_variants._logical_strip_plans` `out_capacity` | set at `:1032-1038`, then fed to `_shard_sinks(cap=...)` (`:1061`) and `_merge_lanes(..., out_capacity, ...)` (`:1091`). `_merge_lanes` folds several destinations onto ONE lane, joining their group keys with `DEST_SEP` -- the representation already exists and is documented at `freeform.py:864-871`. |
| Belt-port drain capacity | docks with `facing.delta[1] > 0`: **1** for 2209 at every yaw, **1** for 2208 at yaw 0. |
| `LOW_CONFIDENCE_FOOTPRINTS` | `{2101, 2104, 2203, 2205, 2209, 2210, 2212}`; minus `{2208, 2209}` leaves `{2101, 2104, 2203, 2205, 2210, 2212}`. **2209 is the only newly-checked id**; 2208 was never exempt. |
| Corpus | `universe-matrix` places **8-10 Ray Receivers** in all three candidates (`MachineGroup.machine_item_id` is the string `"ray-receiver"`, never the int `2208`). No corpus cell places a 2209, so Task 4 is corpus-inert; Tasks 2 and 3 are not. |
| Ray Receiver docks | yaw 0: NORTH `(3,4)`, SOUTH `(3,2)` -- **no east dock**, so `_dock_input_lane` never runs for one; yaw 90: EAST `(4,3)`, whose `tap+1` IS inside its collider. |
| `cat.building(2303).port_poses` | `()` -- an assembler is not a belt-port host and is a vacuous control. Use Storage Tank `2106` (3x3, east dock `(2,1)`, `tap+1` outside its collider). |
| `Finding` fields | `check, severity, message, buildings, detail` -- **no `indices`** |
| `load_vendored` | `flab2bp.lab.data`; `Dataset` has `recipes` (each with `producers`) and a `machine_ids` property, **no `machines`** |
| `LogicalLane` fields | `lane_id, kind, items, destination_group_keys, cargo_domain, side, side_index` -- **`items`, not `item`** |

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `src/flab2bp/layout/slots.py` | `belt_tile_hits_collider`, `MAX_RESCUED_COLLIDER_TILES`: the paste's own in-collider question, shared by emitter and tests. | 1 |
| `tests/layout/test_slots_ports.py` (new) | Unit tests for the predicate and the tap-column rule. | 1, 2 |
| `src/flab2bp/layout/freeform.py` | `_port_approach`, `_port_approach_offset`; `Strip.input_lane_tiles`; `_dock_input_lane`; `_feedable_by_port` (Task 2). The refusal text's wrong-blame arm (Task 3). | 2, 3 |
| `src/flab2bp/layout/strip_variants.py` | `_logical_strip_plans`: cap a belt-port host's output lanes at its drain-dock count (Task 3). Also the contingent site if Task 2 step 5's pitch assertion fails, where `MachinePlacementGeometry.with_minimum_pitch_x` is the tool. | 3, 2 (contingent) |
| `tests/layout/test_freeform.py` | Exchanger emission, ray-receiver byte-identity, the two-sink drain. | 2, 3 |
| `tests/layout/test_strip_variants.py` | The lane cap itself. | 3 |
| `src/flab2bp/dsp/catalog.py` | `MODE_DRIVEN_MACHINE_ITEM_IDS`, `UNPLACED_LOW_CONFIDENCE_FOOTPRINTS`. | 4 |
| `src/flab2bp/dsp/registry.py` | Registers both as `Kind.DERIVED`; the `MAX_RESCUED_COLLIDER_TILES` lint exception if needed. | 1, 4 |
| `src/flab2bp/layout/validate.py` | `_belt_collide_findings` consults the narrowed set; both check docstrings. | 4 |
| `tests/dsp/test_catalog.py` | The stale hardcoded `generator_places` guard becomes derived. | 4 |
| `tests/layout/test_validate.py` | Positive control: an exchanger approach is convicted. | 4 |
| `tests/bench/test_broke6_url.py` (new) | End-to-end acceptance for this URL. | 5 |
| `docs/superpowers/evidence/broke6/gate.md` (new) | The three-round gate output. `.superpowers/` is git-ignored and would lose it. | 6 |

---

### Task 1: The paste's own in-collider question, in one place

The emitter must count belt tiles inside a host's build collider, and it must
count them exactly as `game.belt_collide` does or the two drift. Task 1 exposes
that one question over `dsp.colliders`. It changes no behaviour, so the suite
stays green.

**Files:**
- Modify: `src/flab2bp/layout/slots.py:72` (import) and after `port_docks` (ends `:968`)
- Modify: `src/flab2bp/dsp/registry.py` (only if step 4 says so)
- Create: `tests/layout/test_slots_ports.py`

**Interfaces:**
- Produces: `slots.MAX_RESCUED_COLLIDER_TILES: int = 3`
- Produces: `slots.belt_tile_hits_collider(host: PlacedBuilding, x: int, y: int, z: Fraction = Fraction(0)) -> bool`
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/layout/test_slots_ports.py`:

```python
"""The exact in-collider question the paste asks, shared by emitter and tests."""

from __future__ import annotations

from dataclasses import replace

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import codec, colliders
from flab2bp.layout import slots
from flab2bp.layout.base import Facing, PlacedBuilding


def _host(item_id: int, yaw: float = 0.0) -> PlacedBuilding:
    info = cat.building(item_id)
    return PlacedBuilding(
        item_id=info.item_id,
        model_index=info.model_index,
        x=0,
        y=0,
        width=info.width,
        height=info.height,
        yaw=yaw,
    )


def test_the_tower_box_reaches_three_tiles_and_no_further() -> None:
    """2209's belt-height collider is the 3.9 tower, not the 5.85 cap.

    Read from the data, never from the 9x9 footprint: the exchanger's boxes are
    a cap 5.8..9.9 units up, which a belt probe at 0.4 never reaches, and a
    tower whose 3.9 / 1.2566 = 3.10 tiles it does.  So dx=3 is inside and dx=4
    is not, on both axes.
    """
    host = _host(cat.ENERGY_EXCHANGER_ID)
    centre_x, centre_y = 4, 4
    assert slots.belt_tile_hits_collider(host, centre_x + 3, centre_y)
    assert slots.belt_tile_hits_collider(host, centre_x + 3, centre_y + 3)
    assert not slots.belt_tile_hits_collider(host, centre_x + 4, centre_y)
    assert not slots.belt_tile_hits_collider(host, centre_x + 3, centre_y + 4)


def test_the_east_dock_is_inside_its_own_hosts_collider() -> None:
    """The game's own port pose sits under the building.  Not a defect."""
    host = _host(cat.ENERGY_EXCHANGER_ID)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    assert dock.cell == (6, 4)
    assert slots.belt_tile_hits_collider(host, *dock.cell)


def test_a_storage_tank_dock_clears_its_own_collider() -> None:
    """The contrast case: a belt-port host that never needed this fix.

    An assembler is NOT the control -- cat.building(2303).port_poses is (), so
    it never takes this path at all and a test on it proves nothing.
    """
    host = _host(2106)  # Storage Tank, 3x3, east dock (2, 1)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    assert dock.cell == (2, 1)
    assert not slots.belt_tile_hits_collider(host, dock.cell[0] + 1, dock.cell[1])


def test_the_game_rescues_the_dock_and_the_two_belts_behind_it() -> None:
    """MAX_RESCUED_COLLIDER_TILES is the paste's answer, not our number.

    Diagnosis 3.3's run, rebuilt: a column at dx=+3 climbing the exchanger,
    turning west into the east dock.  The paste convicts everything more than
    three hops from the host.  Belt (7, 0) is at dy=-4 and does not overlap at
    all, so of the six belts, 4/5/6 are rescued and 2/3 are convicted.
    """
    belt_model = cat.building(2002).model_index
    buildings = [_host(cat.ENERGY_EXCHANGER_ID)]
    buildings += [
        PlacedBuilding(item_id=2002, model_index=belt_model, x=7, y=y, width=1, height=1)
        for y in range(0, 5)
    ]
    buildings.append(
        PlacedBuilding(item_id=2002, model_index=belt_model, x=6, y=4, width=1, height=1)
    )
    for i in range(1, 6):
        buildings[i] = replace(buildings[i], output_obj=i + 1)
    buildings[6] = replace(buildings[6], output_obj=0)
    previews = tuple(
        colliders.Preview(
            b.model_index,
            *codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height),
            b.yaw,
            is_belt=cat.is_belt(b.item_id),
            output=b.output_obj,
            input=b.input_obj,
        )
        for b in buildings
    )
    convicted = {belt for belt, _other in colliders.belt_collisions(previews)}
    assert convicted == {2, 3}
    inside = [
        i for i, b in enumerate(buildings) if i and slots.belt_tile_hits_collider(buildings[0], b.x, b.y)
    ]
    assert len(inside) - len(convicted) == slots.MAX_RESCUED_COLLIDER_TILES
```

Confirm `colliders.Preview`'s keyword names (`is_belt`, `output`, `input`) with
`mcp__serena__find_symbol` before running; `validate._paste_previews`
(`validate.py:2739`) is the reference construction.

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/layout/test_slots_ports.py -q; echo "exit=$?"`
Expected: non-zero, `AttributeError: module 'flab2bp.layout.slots' has no attribute 'belt_tile_hits_collider'`.

The pytest summary line does not print in this project. Judge by `echo $?` and
the traceback, never by a "1 failed" line.

- [ ] **Step 3: Implement**

In `src/flab2bp/layout/slots.py:72`, change

```python
from flab2bp.dsp import colliders, splitter_ports
```

to

```python
from flab2bp.dsp import codec, colliders, splitter_ports
```

and after `port_docks` add:

```python
#: How many belt tiles inside a host's build collider the game lets off.
#:
#: ``colliders.belt_run_ends_in_a_building`` (CheckBuildConditions 147492)
#: excuses the belt that ends in the port, and ``colliders.belt_chain_excuses``
#: (147443) the TWO behind it -- its three-hop walk reaches the host from a belt
#: two tiles back and no further, because the host itself is one of the hops.
#:
#: THE RESCUE IS BY HOP DISTANCE, NOT BY COUNT.  Three in-collider tiles that
#: are not the last three hops into the port are still convicted, and a
#: splitter inside the run moves the budget (147443's two-hop clause).  A
#: caller counting with this number must ALSO check that the hits are the run's
#: suffix; :func:`flab2bp.layout.freeform._port_approach` is the one that does.
MAX_RESCUED_COLLIDER_TILES = 3


def belt_tile_hits_collider(
    host: PlacedBuilding, x: int, y: int, z: Fraction = Fraction(0)
) -> bool:
    """Would a belt standing on ``(x, y, z)`` probe into ``host``'s collider?

    The paste's own question, asked with the paste's own primitives, so the
    emitter cannot disagree with ``validate``'s ``game.belt_collide`` about
    which tiles need excusing.  The geometry comes from the asset table through
    ``colliders.target_boxes``; no footprint number is consulted, because a
    footprint is a derived tile count and the collider is what the game probes.

    Raw overlap only.  Whether a hit is then rescued is a property of the
    belt's RUN, not of the tile -- see :data:`MAX_RESCUED_COLLIDER_TILES`.
    """
    pose_args = codec.tile_to_local_offset(
        host.x, host.y, host.z, host.width, host.height
    )
    preview = colliders.Preview(host.model_index, *pose_args, host.yaw)
    boxes = colliders.target_boxes(
        preview, *colliders.flat_pose(preview.x, preview.y, preview.z, preview.yaw)
    )
    probe = colliders.belt_probe(*codec.tile_to_local_offset(x, y, z, 1, 1))
    return any(
        colliders.sphere_box_overlap(probe, colliders.BELT_PROBE_RADIUS, box)
        for box in boxes
    )
```

Add both names to `slots.__all__`.

- [ ] **Step 4: Register the constant if the rule lint sees it**

Run: `uv run python scripts/rule_report.py 2>&1 | tail -20`

If it reports `3` at `flab2bp.layout.slots` as a bare literal, add to
`src/flab2bp/dsp/registry.py`'s `LintException` list:

```python
    LintException(
        module="flab2bp.layout.slots",
        where="MAX_RESCUED_COLLIDER_TILES",
        value=3.0,
        why="CheckBuildConditions 147443's hop budget, not SORTER_MAX_REACH",
    ),
```

- [ ] **Step 5: Run the tests and the suite**

```bash
uv run pytest tests/layout/test_slots_ports.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
uv run mypy src tests 2>&1 | tail -1
uv run ruff check . && uv run ruff format --check .
```

Expected: both `exit=0`; `Found 184 errors in 16 files (checked 167 source files)`; ruff silent.

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/layout/slots.py tests/layout/test_slots_ports.py src/flab2bp/dsp/registry.py
git commit -m "feat(slots): share the paste's in-collider tile question

The emitter needs to know which belt tiles of an approach stand inside the
host's build collider, and it has to ask exactly what game.belt_collide asks
or the two drift.  One function over dsp.colliders' own boxes, plus the hop
budget the game's rescue admits -- documented as a suffix rule, because that
is what CheckBuildConditions 147443 actually is.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 2: The port approach turns outside the collider, and the lane reaches it

`_dock_input_lane` (`freeform.py:5473-5580`) taps the input lane at
`tap_x = dock.cell[0] + 1` (`:5514`) and climbs to the dock row. For an Energy
Exchanger the dock is 2 tiles from the centre and the tower collider reaches 3,
so that column stands inside the collider for its whole length: measured 5
tiles, of which the paste rescues 3 and convicts 2, on every exchanger.

Moving the tap to `+2` is not enough on its own, and this is the half the first
draft dropped. `Strip.input_lane_tiles` (`freeform.py:1163`) trims the lane to
`(machines - 1) * pw + dock.cell[0] + 1 + 1`, hardcoding the old tap column, so
for the **last** machine in a strip the `+2` column is not a lane column and the
emitter refuses. Measured: 2 machines at `x=1, 12`, lane `x=1..19`, dock
`(18, 6)`, `tap+2 = 20` absent.

The strip **pitch** does not need widening: `freeform.py:2216` already sets
`pitch_width = group.pitch_w + 1` for a port-input host, so the box is
`machines * 11 = 22` columns and column 20 is inside it. Step 5 asserts that
rather than assuming it, and names the fix if a future host ever needs more.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:69` (add `Container` to the `collections.abc` import)
- Modify: `src/flab2bp/layout/freeform.py` -- insert `_port_approach` / `_port_approach_offset` before `_dock_input_lane` (`:5473`); `Strip.input_lane_tiles` (`:1147-1169`); `_dock_input_lane` (`:5498-5519`); `_feedable_by_port` (`:16472`)
- Modify (contingent, step 5 only): `src/flab2bp/layout/strip_variants.py:718-738`
- Test: `tests/layout/test_slots_ports.py`, `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `slots.belt_tile_hits_collider`, `slots.MAX_RESCUED_COLLIDER_TILES` (Task 1).
- Produces: `freeform._port_approach(machine: PlacedBuilding, dock: slots.PortDock, lane_y: int, lane_columns: Container[int], max_offset: int) -> tuple[list[tuple[int, int]], int] | None`
- Produces: `freeform._port_approach_offset(probe: PlacedBuilding, dock: slots.PortDock, pitch_w: int) -> int | None`

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_slots_ports.py`:

```python
from flab2bp.layout import freeform


def test_the_exchanger_approach_turns_outside_the_tower() -> None:
    """Dock at dx=+2, tower reach dx=+3: turn at +4, not +3.

    Turning at +3 puts the whole vertical run inside the collider (measured:
    five tiles, three rescued, two convicted).  Turning at +4 puts only
    (+3, dock row) and the dock inside -- two, one under the budget, and
    CONTIGUOUS with the port, which is what the rescue actually requires.
    """
    host = _host(cat.ENERGY_EXCHANGER_ID)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    result = freeform._port_approach(host, dock, 12, range(-4, 24), host.width + 2)
    assert result is not None
    cells, tap_x = result
    assert tap_x == dock.cell[0] + 2
    assert cells[-1] == dock.cell
    inside = [c for c in cells if slots.belt_tile_hits_collider(host, *c)]
    assert len(inside) == 2
    assert cells[-2:] == inside  # a SUFFIX, not merely few


def test_a_storage_tank_approach_still_taps_one_column_east() -> None:
    """A belt-port host whose dock clears its collider does not move at all."""
    host = _host(2106)  # Storage Tank, 3x3, east dock (2, 1)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    result = freeform._port_approach(host, dock, 6, range(-4, 20), host.width + 2)
    assert result is not None
    _cells, tap_x = result
    assert tap_x == dock.cell[0] + 1


def test_a_ray_receiver_east_dock_is_inside_its_own_collider() -> None:
    """2208's tap+1 is inside its collider at yaw 90; the rule generalises.

    Ray Receivers have no INPUT lanes today and no east dock at yaw 0, so
    _dock_input_lane never runs for one.  This pins the predicate's answer, not
    a behaviour change -- universe-matrix places 8-10 of them and nothing here
    may move that placement.
    """
    host = _host(cat.RAY_RECEIVER_ID, yaw=90.0)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    assert dock.cell == (4, 3)
    assert slots.belt_tile_hits_collider(host, dock.cell[0] + 1, dock.cell[1])
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/layout/test_slots_ports.py -q -k "approach or ray_receiver"; echo "exit=$?"`
Expected: non-zero, `AttributeError: module 'flab2bp.layout.freeform' has no attribute '_port_approach'`.

- [ ] **Step 3: Add `_port_approach` and `_port_approach_offset`**

`mcp__serena__insert_before_symbol` on `_dock_input_lane`:

```python
def _port_approach(
    machine: PlacedBuilding,
    dock: slots.PortDock,
    lane_y: int,
    lane_columns: Container[int],
    max_offset: int,
) -> tuple[list[tuple[int, int]], int] | None:
    """The branch cells from the input lane to ``dock``, and the column it taps.

    An L: down or up the tap column, then west along the dock's row into the
    port.  The tap column used to be fixed at ``dock.cell[0] + 1``, which is
    right for every host whose port pose clears its own build collider and
    WRONG for one whose does not.  An Energy Exchanger's east port sits two
    tiles from its centre inside a collider that reaches three, so the fixed
    column stood inside the collider for its whole length -- five tiles, of
    which the paste rescues three and convicts the rest.  That is the red belt
    in every Energy Exchanger paste.

    So the column is CHOSEN, with the paste's own predicate.  Two conditions,
    and the second is not redundant: the hits must be the run's SUFFIX, because
    ``CheckBuildConditions`` 147443 rescues by HOP DISTANCE from the host, so
    three hits scattered along a run are three convictions.
    """
    for offset in range(1, max_offset + 1):
        tap_x = dock.cell[0] + offset
        if tap_x not in lane_columns:
            continue
        cells: list[tuple[int, int]] = []
        if dock.cell[1] != lane_y:
            step = 1 if dock.cell[1] > lane_y else -1
            cells += [(tap_x, y) for y in range(lane_y + step, dock.cell[1] + step, step)]
        cells += [(x, dock.cell[1]) for x in range(tap_x - 1, dock.cell[0] - 1, -1)]
        if not cells or cells[-1] != dock.cell:
            continue
        hits = [
            i for i, (x, y) in enumerate(cells) if slots.belt_tile_hits_collider(machine, x, y)
        ]
        if hits and hits != list(range(len(cells) - len(hits), len(cells))):
            continue
        if len(hits) <= slots.MAX_RESCUED_COLLIDER_TILES:
            return cells, tap_x
    return None


def _port_approach_offset(
    probe: PlacedBuilding, dock: slots.PortDock, pitch_w: int
) -> int | None:
    """How far east of ``dock`` a lane must reach, in the PROBE frame.

    ``Strip.input_lane_tiles`` and ``_feedable_by_port`` both need the answer
    before any machine is placed, so they ask it of ``probe_building``'s
    origin-anchored copy.  ``probe.height + 1`` is the first row below the
    machine band -- a real lane row, not a width.  That distinction matters:
    the vertical leg's LENGTH changes the in-collider count, so passing a width
    here would answer a different question from the one the emitter asks and
    could pass a strip the emitter then refuses.
    """
    got = _port_approach(
        probe, dock, probe.height + 1, range(-pitch_w, 2 * pitch_w), pitch_w
    )
    return None if got is None else got[1] - dock.cell[0]
```

Change `freeform.py:69` from

```python
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence, Set
```

to

```python
from collections.abc import (
    Callable,
    Collection,
    Container,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Set,
)
```

- [ ] **Step 4: Make the input lane reach the chosen column**

In `Strip.input_lane_tiles` (`freeform.py:1147-1169`), replace

```python
            last_tap = (self.machines - 1) * self.pw + docks[lane_index].cell[0] + 1
            return min(self.width, last_tap + 1)
```

with

```python
            # The lane must reach the column the approach will TAP, which is no
            # longer always dock+1: a host whose port sits inside its own
            # collider taps further east (see _port_approach).  Trimming to
            # dock+1 left the LAST machine in a strip with no legal tap, which
            # turns the collision this fix removes into a refusal instead.
            probe = slots.probe_building(self.item_id, self.yaw)
            offset = _port_approach_offset(probe, docks[lane_index], self.pw)
            if offset is None:
                return self.width
            last_tap = (self.machines - 1) * self.pw + docks[lane_index].cell[0] + offset
            return min(self.width, last_tap + 1)
```

- [ ] **Step 5: Assert the reserved pitch already contains the tap column**

Add to `tests/layout/test_slots_ports.py`:

```python
def test_the_reserved_pitch_contains_the_tap_column_for_every_belt_port_host() -> None:
    """freeform.py:2216 buys one spare column for a port-input host.  Enough?

    An invariant, not two samples: this test is what licenses skipping the
    pitch work entirely, so it asks every belt-port host in the catalog at
    every yaw.  Measured on 688cbed it holds for all eight (2020 Splitter,
    2040 Automatic Piler, 2103/2104 Logistics Stations, 2106 Storage Tank,
    2208 Ray Receiver, 2209 Energy Exchanger, 2301/2306/2307/2314/2316), for
    every yaw with an east dock; the exchanger is yaw-invariant because its
    footprint is square.  If a future host ever needs more, this fails and the
    fix is MachinePlacementGeometry.with_minimum_pitch_x, not a wider lane trim.
    """
    hosts = [
        item_id
        for item_id in cat.every_building_item_id()  # confirm the real accessor
        if cat.building(item_id).port_poses and not cat.building(item_id).slot_poses
    ]
    assert cat.ENERGY_EXCHANGER_ID in hosts and 2106 in hosts, hosts
    checked = 0
    for item_id in hosts:
        for yaw in (0.0, 90.0, 180.0, 270.0):
            pitch_w = cat.clearance(item_id, yaw)[0] + 1  # the port_inputs column
            probe = slots.probe_building(item_id, yaw)
            for dock in slots.port_docks(probe).values():
                if dock.facing is not Facing.EAST:
                    continue
                offset = freeform._port_approach_offset(probe, dock, pitch_w)
                assert offset is not None, (item_id, yaw, dock)
                assert dock.cell[0] + offset < pitch_w, (item_id, yaw, dock, offset, pitch_w)
                checked += 1
    assert checked >= 8, checked  # not vacuous
```

`cat.every_building_item_id()` is a placeholder for whatever the catalog's real
enumeration is -- find it with `mcp__serena__get_symbols_overview` on
`src/flab2bp/dsp/catalog.py` and use the real name; if the catalog exposes no
enumeration, iterate the ids in `src/flab2bp/dsp/data/slot_poses.json` through
`catalog.item_id`. The `checked >= 8` floor is what stops a wrong accessor from
turning this into a vacuous pass.

If this fails for any host, add a step that applies
`geometry.with_minimum_pitch_x(dock.cell[0] + offset + 1)`
(`strip_variants.py:96-107`) inside `strip_variants.placement_geometry`
(`:718-738`) and raises `pitch_width` at `freeform.py:2216` to match, and add
`src/flab2bp/layout/strip_variants.py` to this task's `git add`. Measured on
`688cbed` it passes for 2209 and 2106, so no widening is expected.

- [ ] **Step 6: Make `_dock_input_lane` use the chosen approach**

Replace the dock filter (`freeform.py:5502-5503`)

```python
                and candidate.facing is Facing.EAST
                and candidate.cell[0] + 1 in lane_by_x
            ),
```

with

```python
                and candidate.facing is Facing.EAST
                and _port_approach(machine, candidate, lane_y, lane_by_x, machine.width + 2)
                is not None
            ),
```

and the refusal plus branch construction (`freeform.py:5507-5519`)

```python
        if dock is None:
            name = catalog.building(machine.item_id).name
            raise NoValidLayout(
                f"{name} cannot feed {item!r} from its east-running input lane "
                "through a distinct exact belt port"
            )

        tap_x = dock.cell[0] + 1
        step_y = 1 if dock.cell[1] > lane_y else -1
        branch_cells = (
            [(dock.cell[0], dock.cell[1])]
            if dock.cell[1] == lane_y
            else [(tap_x, y) for y in range(lane_y + step_y, dock.cell[1] + step_y, step_y)]
            + [(dock.cell[0], dock.cell[1])]
        )
```

with

```python
        if dock is None:
            name = catalog.building(machine.item_id).name
            raise NoValidLayout(
                f"{name} cannot feed {item!r} from its east-running input lane "
                "through a distinct exact belt port whose approach stays inside "
                f"the paste's {slots.MAX_RESCUED_COLLIDER_TILES}-tile collider rescue"
            )

        approach = _port_approach(machine, dock, lane_y, lane_by_x, machine.width + 2)
        assert approach is not None  # the dock filter above already asked
        branch_cells, tap_x = approach
```

Everything after -- the per-cell `facing` loop, the relinking, `excused` and the
`_tap_source` call -- is unchanged and already handles a branch of any length,
because each cell's facing is derived from the next.

`machine.width + 2` is the bound: an approach needing more than two columns past
the machine's own east edge would be crossing into the next machine's pitch,
which is a different bug. Do **not** use `catalog.SORTER_MAX_REACH`; a sorter
constant has nothing to do with a belt tap column.

- [ ] **Step 7: Match the feasibility capacity term**

`_feedable_by_port` (`freeform.py:16472`) reads

```python
    capacity = sum(dock.facing is Facing.EAST and dock.cell[0] + 1 < strip.pw for dock in docks)
```

Replace with

```python
    capacity = sum(
        dock.facing is Facing.EAST
        and _port_approach_offset(probe, dock, strip.pw) is not None
        for dock in docks
    )
```

`probe` is already bound on the line above. The old `strip.pw` was a width used
where a lane row belongs; `_port_approach_offset` uses the strip's own first
lane row instead, so the gate and the emitter now ask the same question.

- [ ] **Step 8: Run the two tests that were red without the lane trim**

```bash
uv run pytest \
  tests/layout/test_freeform.py::test_port_driven_family_remains_directly_routable_with_pitch_mapping \
  "tests/layout/test_freeform.py::TestModeDrivenMachines::test_empty_sorter_poses_use_exact_bidirectional_prefab_ports" \
  -q; echo "exit=$?"
```

Expected: `exit=0`. Measured green with exactly these edits; without step 4 both
fail with `NoValidLayout: Energy Exchanger cannot feed 'accumulator' ...`.

- [ ] **Step 9: Prove the emitted placement stops colliding**

Add to `tests/layout/test_freeform.py`, beside `mode_driven_spec()` and
`_assert_energy_exchanger_port_routing` (`test_freeform.py:9354`):

```python
def test_an_energy_exchanger_placement_pastes_without_collisions() -> None:
    """Two belts per exchanger used to be convicted and hidden by the exemption.

    Asked directly, with no LOW_CONFIDENCE filtering, the answer has to be none.
    """
    spec = mode_driven_spec()
    placement = FreeformLayout(band_policy=BandPolicy.parse("portable")).lay_out(
        spec, time_budget_s=4.0
    )
    ctx = validate._context(placement, spec, None, 0, Fraction(4), True)
    assert colliders.stable_belt_collisions(validate._paste_previews(ctx)) == []
```

`mode_driven_spec`, `FreeformLayout` and `BandPolicy` are already used together
at `test_freeform.py:9410-9414`. There is no preview helper in this module, so
build previews with `validate._paste_previews(validate._context(...))` exactly
as written.

Imports, checked rather than hedged: the module already imports `colliders`
(`:24`), `validate` (`:25`) and `BandPolicy` (`:26`), and it imports
`Fraction as F` (`:17`) -- **not** `Fraction`, so write `F(4)` in the snippet
above or add the plain import. Its neighbouring tests spell the policy
`BandPolicy("portable")` rather than `BandPolicy.parse("portable")`; both work,
so use the module's own idiom throughout the tests this plan adds.

- [ ] **Step 10: Pin the ray-receiver path byte-for-byte**

`universe-matrix` places 8-10 Ray Receivers on 6 of the 72 corpus cells. Nothing
in this task may move them. Add to `tests/layout/test_freeform.py`:

```python
def test_a_ray_receiver_strip_is_byte_identical_after_the_approach_change() -> None:
    """A Ray Receiver has no east dock at yaw 0 and no input lanes, so
    _dock_input_lane never runs for it and _port_approach is never consulted.
    Pin the emitted geometry so a future widening of the rule cannot drift it.
    """
    spec = _ray_receiver_spec()
    placement = FreeformLayout(band_policy=BandPolicy.parse("portable")).lay_out(
        spec, time_budget_s=4.0
    )
    shape = [
        (b.item_id, b.x, b.y, b.z, b.yaw, b.output_obj, b.input_obj)
        for b in placement.buildings
    ]
    assert shape == RAY_RECEIVER_SHAPE
```

`_ray_receiver_spec()` and `RAY_RECEIVER_SHAPE` are written in this commit.
Build `_ray_receiver_spec()` by copying `mode_driven_spec()` and swapping its
group to `recipe_id="critical-photon", machine_item_id="ray-receiver", count=2`;
read `mode_driven_spec` with `mcp__serena__find_symbol` and match its `BuildSpec`
construction exactly. Generate `RAY_RECEIVER_SHAPE` by running that layout **on
master, before any edit in this task**, and pasting the literal -- otherwise the
test is a tautology rather than a before/after.

A byte-for-byte literal pinned against a time-budgeted CP-SAT search would
normally be a wall-clock test in disguise, so both halves were measured before
this step was written. *Deterministic:* the layout gives 31 buildings at
`budget=4.0` twice and at `budget=8.0`, and the three shapes are equal.
*And the identity holds:* the same spec laid out on a pristine archive of
`688cbed` and on a copy with Tasks 1-3 applied gives 31 buildings that compare
equal on `(item_id, x, y, z, yaw, output_obj, input_obj)`. Record both in the
step when you regenerate the literal, so the next reader does not weaken the
test on a suspicion of flakiness.

- [ ] **Step 11: Suite, types, lint**

```bash
uv run pytest -q; echo "exit=$?"
uv run mypy src tests 2>&1 | tail -1
uv run ruff check . && uv run ruff format --check .
```

Expected: `exit=0`; `Found 184 errors in 16 files (checked 167 source files)`; ruff silent.

- [ ] **Step 12: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_slots_ports.py tests/layout/test_freeform.py
git commit -m "fix(layout): turn the port approach outside the host's collider

_dock_input_lane taps one column east of the dock and climbs to the dock row.
For a host whose port pose clears its collider that is right.  An Energy
Exchanger's east port is two tiles from its centre inside a collider that
reaches three, so the column stood inside the collider for its whole length:
five tiles, three rescued by the paste and two convicted, on every exchanger
in every blueprint.

The tap column is chosen now, with the paste's own predicate and its suffix
rule, and Strip.input_lane_tiles trims the lane to the column that is chosen
rather than to a hardcoded dock+1 -- without that half the last machine in a
strip has no legal tap and the collision becomes a refusal.  The reserved
pitch already covers it and a test says so rather than assuming it.  Nothing
moves for a host that was already clear, and the ray-receiver strip is pinned
byte-for-byte because universe-matrix places 8-10 of them.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 3: A belt-port host is planned one output lane per drain port

`_drainable_by_port` (`freeform.py:16460-16464`) demands one north-facing dock
per output lane; an Energy Exchanger has exactly one at every yaw. The
`output-products` candidate gives its charge exchangers two output lanes, both
carrying `accumulator-full`, one to the internal discharge machine and one to
the external output -- so the strip refuses in 1.5 s, before any search.

**The fix is to stop planning the second lane, not to fan a single port out to
it.** Four designs were built and measured in a throwaway copy; the first four
lines are why this task no longer contains a `_dock_cargo_lanes`:

| Design | Measured outcome |
| --- | --- |
| (a) Relax the count, then tap the lane tile the drawing column already feeds | `_tap_source` fails **12/12** with `['splitter-port']` -- that tile has two feeders (its west lane neighbour and `column[-1]`, `freeform.py:5661`) and `_tap_source`'s junction arm requires exactly one. Silent: the return was discarded, `certify ok=True`, 3 exchangers / 1 splitter, second lane joined to nothing. |
| (b) Tap one column east instead, where there IS exactly one feeder | Fails `['belt-keepout']`: the splitter's stack keep-out covers the next lane row's belt. |
| (c) As (b) plus an `excused` set, like `_dock_input_lane` | Taps attach (`placed=6`), but the emitted splitters are convicted by our OWN `game.belt_collide` as unstable merges -- the branch lane belt already has a west feeder, so a preview ordering can pick a non-rescuing one. The layout then refuses. |
| (d) As (a) but raising `NoValidLayout` on failure instead of skipping | `output-products` regresses to **REFUSED on both strategies**: `_emit_strip`'s only caller (`freeform.py:14146`) has no per-arrangement `try`, so the raise aborts the whole solve rather than moving to the merged arrangement. |
| **(e) Cap a belt-port host's planned `out_lanes` at its drain-dock count** | **All six pairs `ok=True errors=0 stable_belt_collisions=0`; `test_freeform.py` + `test_strip_variants.py` 646 passed; ray-receiver placement byte-identical to master.** |

(e) works because the machinery already exists. `strip_variants._logical_strip_plans`
computes `out_capacity` (`:1032-1038`) and hands it to `_shard_sinks(cap=...)`
(`:1061`) and `_merge_lanes(..., out_capacity, ...)` (`:1091`), and `_merge_lanes`
folds several destinations onto ONE lane by joining their group keys with
`DEST_SEP` -- the representation `Strip.out_lanes` already documents
(`freeform.py:864-871`) and `_dests` already reads (`freeform.py:1630`). Today
`out_capacity` is derived from the SORTER reach and the south face's attachable
columns, which is the wrong question for a host that drains through ports and
takes no sorter at all. Ask the right one and the two-lane strip is never
proposed, so `_drainable_by_port` passes unchanged and no lane can ship unwired.

`_port_variants` (`strip_variants.py:1296-1307`) is not touched: it returns `()`
whenever `input_lanes` is non-empty and the charge strip has an input lane.
`_drainable_by_port`, `_dock_lane` and the out-lane call site are not touched
either -- this task's only behavioural edit is the capacity, plus the refusal
message that blamed the wrong side.

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py:1040` (insert the cap just before `cargo_count = len(_cargo_keys(sinks))`)
- Modify: `src/flab2bp/layout/freeform.py:16559-16580` (the refusal chain's wrong-blame arm)
- Test: `tests/layout/test_strip_variants.py`, `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2 (independent in code; ordered after them only for greenness).
- Produces: no new symbol. `_logical_strip_plans` keeps its signature; `out_capacity` is a local.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_strip_variants.py`:

```python
def test_a_single_machine_belt_port_host_folds_its_sinks_onto_one_lane() -> None:
    """2209 has ONE north-facing dock, so it may be planned one output lane.

    Two accumulator-full sinks -- an internal discharge machine and the
    external output -- used to become two lane rows, which one port cannot
    drain, and the strip refused before any search.  With ONE machine there is
    no second shard to give, so the other axis moves: they become one lane
    whose destination field names both groups, which is what DEST_SEP is for.
    """
    plans = _plans_for(_two_sink_exchanger_spec(count=1))
    charge = [p for p in plans if p.recipe_id == "accumulator-full"]
    assert len(charge) == 1, charge
    assert len(charge[0].out_lanes) == 1, charge[0].out_lanes
    item, dest, _domain = charge[0].out_lanes[0]
    assert item == "accumulator-full"
    assert dest == "|accumulator-discharge#1"
    assert freeform._dests(dest) == ("", "accumulator-discharge#1")


def test_several_machines_shard_instead_of_folding_and_still_take_one_lane() -> None:
    """The cap is 'one lane per PLAN', which sharding satisfies too.

    With machines to spare the planner splits the destinations across STRIPS
    rather than folding them onto one lane -- `_shard_sinks` runs before
    `_merge_lanes`.  Either shape honours the cap; what must never come back is
    a single plan carrying two lanes for a host with one drain port.
    """
    plans = _plans_for(_two_sink_exchanger_spec(count=3))
    charge = [p for p in plans if p.recipe_id == "accumulator-full"]
    assert len(charge) == 2, charge
    assert {p.shard_index for p in charge} == {0, 1}
    assert all(len(p.out_lanes) == 1 for p in charge), charge
    assert {dest for p in charge for _i, dest, _c in p.out_lanes} == {
        "accumulator-discharge#1",
        "",
    }


def test_an_ordinary_producer_keeps_its_sorter_derived_lane_capacity() -> None:
    """The cap is asked only of a host that drains through PORTS.

    An assembler has no port poses at all, so its out_capacity must still come
    from the south face and the sorter reach -- otherwise every strip in the
    corpus loses lanes.
    """
    plans = _plans_for(_two_sink_assembler_spec())
    producer = next(p for p in plans if p.recipe_id == "gear")
    assert len(producer.out_lanes) == 2
```

Add to `tests/layout/test_freeform.py`:

```python
def test_a_two_sink_exchanger_lays_out_with_one_wired_lane() -> None:
    """The end of the class of bug, not a fan-out.

    Every accumulator-full sink is served by ONE drawn belt per machine, so a
    lane joined to nothing is not representable.  Measured: 4 exchangers, one
    drawing belt each, certify ok, zero collisions.
    """
    spec = _two_sink_exchanger_spec(count=3)  # count=1 does not route; see the fixture
    placement = FreeformLayout(band_policy=BandPolicy.parse("portable")).lay_out(
        spec, time_budget_s=4.0
    )
    bs = placement.buildings
    exchangers = [i for i, b in enumerate(bs) if b.item_id == catalog.ENERGY_EXCHANGER_ID]
    assert exchangers
    for i in exchangers:
        drawing = [j for j, b in enumerate(bs) if b.input_obj == i]
        assert len(drawing) == 1, (i, drawing)
    report = validate.certify(placement, spec, expect_power=True)
    assert report.ok, report.errors
    ctx = validate._context(placement, spec, None, 0, F(4), True)
    assert colliders.stable_belt_collisions(validate._paste_previews(ctx)) == []
```

`validate.certify(placement, spec, expect_power=True)` and **not**
`validate.validate(placement, spec, expect_power=True)`: without `ids` the
latter skips its spec-conformance and flow checks, so `report.ok` would be
weaker than it looks. `certify` is what this module's own exchanger helper uses
(`test_freeform.py:9392`).

Measured on `688cbed` with the cap applied: `count=1` gives one plan whose lane
destination is `'|accumulator-discharge#1'`; `count=2`, `3` and `4` each give
two shards of one lane each. One fixture cannot assert both shapes -- an earlier
draft asserted the DEST_SEP fold against a `count=3` fixture and would have
failed `1 != 2`.

`_two_sink_exchanger_spec(count)` is written in this commit and shared by both test
modules (put it wherever they already share fixtures; if they do not, duplicate
it and say so). Measured working:

```python
def _two_sink_exchanger_spec(count: int = 3) -> BuildSpec:
    """Charge exchangers whose product has an internal consumer AND an output.

    ``count`` selects the shape the planner produces: 1 folds both sinks onto
    ONE lane with DEST_SEP (no second shard to give), 2 or more shards them
    across two strips of one lane each.  Only ``count >= 2`` routes -- one
    charge machine cannot feed a discharge machine AND the external output --
    so ``count=1`` is a planner fixture and never reaches `lay_out`.
    """
    return BuildSpec(
        groups=(
            group("accumulator-full", "energy-exchanger", count,
                  {"accumulator": F(1)}, {"accumulator-full": F(1)}),
            group("accumulator-discharge", "energy-exchanger", 1,
                  {"accumulator-full": F(1)}, {"accumulator": F(1)}),
        ),
        external_inputs={"accumulator": F(2)},
        outputs={"accumulator-full": F(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label=f"two-sink-{count}",
    )
```

`group` and `BuildSpec` are already imported by `tests/layout/test_freeform.py`;
`F` is its alias for `Fraction` (`test_freeform.py:17`). `_plans_for` and
`_two_sink_assembler_spec` are written in this commit against
`strip_variants._logical_strip_plans` -- read it and the module's existing plan
tests with `mcp__serena__find_symbol` first and reuse whatever harness they
already have rather than inventing one; the assertions above are the behaviour.

- [ ] **Step 2: Run them to make sure they fail**

```bash
uv run pytest tests/layout/test_strip_variants.py -q -k "folds_its_sinks or shard_instead or sorter_derived"; echo "exit=$?"
uv run pytest tests/layout/test_freeform.py -q -k two_sink; echo "exit=$?"
```

Expected: non-zero for both. The `strip_variants` cases fail on
`assert len(...out_lanes) == 1` -- before the cap a single plan carries two
lanes. The `freeform` case fails earlier, when
`lay_out` raises `NoValidLayout: ... Energy Exchanger (accumulator-full): its
ingredient lanes cannot claim distinct east-facing input docks ...` -- the
misleading message Step 5 fixes.

- [ ] **Step 3: Cap the lanes**

In `src/flab2bp/layout/strip_variants.py`, immediately before
`cargo_count = len(_cargo_keys(sinks))` (`:1040`), insert:

```python
        building = catalog.building(group.item_id)
        if building.takes_belt_ports and not building.slot_poses:
            # A host with no insert pose drains through PORTS, not sorters, so
            # the sorter reach and the south face's attachable columns are the
            # wrong question: what bounds its lanes is how many ports face the
            # lane band, and an Energy Exchanger has exactly ONE at every yaw.
            #
            # Capping here is what removes the whole defect class rather than
            # coping with it downstream: `_merge_lanes` then folds this cargo's
            # destinations onto that one lane, joining their group keys with
            # DEST_SEP, and `_dock_lane` drains it exactly as it always has.
            # Fanning one port out across two lane rows instead was built and
            # measured four ways -- every one either failed to attach, emitted
            # splitters our own validator convicts, or turned the collision
            # into a refusal.
            out_capacity = min(
                out_capacity,
                sum(dock.facing.delta[1] > 0 for dock in slots.port_docks(probe).values()) or 1,
            )
```

`probe` is already bound above this point in `_logical_strip_plans` (it is what
`slots.attachable_columns(probe, group.pitch_h)` reads at `:1031`); confirm with
`mcp__serena__find_symbol` before inserting, and confirm `catalog` and `slots`
are already imported in the module (they are, and `_port_variants` uses both).

**Insert ABOVE the `_has_exact_two_face_seating` block, and check it after.**
Eight lines below this hunk (`:1042-1058`) sits an existing widening: when
`cargo_count > out_capacity` and `_has_exact_two_face_seating(...)` proves an
exact one-lane-per-cargo seating across both faces, `out_capacity` is raised
back to `cargo_count`. That path is for a SORTER-seated host and cannot apply to
one with no insert poses -- `_has_exact_two_face_seating` asks the slot matcher
for seatings a belt-port host has none of -- so the cap survives it today.
Verify that rather than assume it: after inserting, assert in the
`strip_variants` test that a 2209 plan's `out_lanes` is length 1 even when the
spec gives it two distinct cargoes, and if the widening ever does fire for a
belt-port host, guard it with the same `takes_belt_ports and not slot_poses`
test rather than moving the cap below it.
The `or 1` floor keeps a host with no drain-facing port from being capped to
zero, which `_shard_sinks` rejects with "no room left on the south side".

- [ ] **Step 4: Run the two new tests**

```bash
uv run pytest tests/layout/test_strip_variants.py -q -k "folds_its_sinks or shard_instead or sorter_derived"; echo "exit=$?"
uv run pytest tests/layout/test_freeform.py -q -k two_sink; echo "exit=$?"
```

Expected: `exit=0` for both. Measured: `count=1` folds to
`'|accumulator-discharge#1'`, `count=3` gives two shards of one lane each, and
the `count=3` layout gives 4 exchangers, one drawing belt each,
`certify ok=True errors=0`, `stable_belt_collisions=0`.

- [ ] **Step 5: Fix the refusal message, which names the wrong side**

`_drainable_by_port` is unchanged, so it can still refuse -- a host with two
DISTINCT cargoes and one drain port genuinely cannot be wired, and refusing is
right. What is wrong is the message: the chain at `freeform.py:16559-16580`
prints the *ingredient* text whenever `s.in_lanes` is non-empty, so a drain
failure sends the reader to `_dock_input_lane`, where nothing is wrong. That is
what cost this investigation its first day.

The chain has **four** arms. Insert one before the first and leave the other
three verbatim:

```python
            if s.takes_belt_ports and s.in_lanes and s.out_lanes and not _drainable_by_port(s):
                out.append(
                    f"{building.name} ({s.recipe_id}): its "
                    f"{len({(i, d) for i, _dest, d in s.out_lanes})} distinct output "
                    f"cargo(es) cannot claim distinct docks facing the lane band "
                    f"from its {len(building.port_poses)} belt port(s)"
                )
            elif s.takes_belt_ports and s.in_lanes:
                ...  # unchanged ingredient-dock message
            elif s.takes_belt_ports:
                ...  # unchanged "none of its N belt port(s) faces the output lane below"
            else:
                ...  # unchanged "cannot be assigned distinct legal sorter slots"
```

The `and s.out_lanes` guard is load-bearing: `_drainable_by_port` returns
`False` for a strip with **no** out-lanes (`freeform.py:16463`,
`bool(strip.out_lanes) and ...`), so without it an input-only strip failing for
an ingredient reason would get the drain message -- the same wrong-blame defect
this step exists to remove, in the other direction.

- [ ] **Step 6: Pin the ray-receiver path, which the corpus does exercise**

`universe-matrix` places 8-10 Ray Receivers on 6 of the 72 cells, and 2208 is a
belt-port host with no slot poses, so this task's cap applies to it. Its drain
capacity is 1 and it has one product, so nothing should move. Add to
`tests/layout/test_freeform.py`:

```python
def test_a_ray_receiver_drain_is_byte_identical_after_the_lane_cap() -> None:
    """2208 is capped too: one drain port, one product, so nothing may move."""
    spec = _ray_receiver_spec()  # from Task 2 step 10
    placement = FreeformLayout(band_policy=BandPolicy.parse("portable")).lay_out(
        spec, time_budget_s=4.0
    )
    shape = [
        (b.item_id, b.x, b.y, b.z, b.yaw, b.output_obj, b.input_obj)
        for b in placement.buildings
    ]
    assert shape == RAY_RECEIVER_SHAPE
```

Reuse the literal generated in Task 2 step 10. Measured against a pristine
archive of `688cbed`: 31 buildings, byte-identical with the cap applied.

- [ ] **Step 7: Run the two suites this task can move, then the whole one**

```bash
uv run pytest tests/layout/test_freeform.py tests/layout/test_strip_variants.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
uv run mypy src tests 2>&1 | tail -1
uv run ruff check . && uv run ruff format --check .
```

Expected: `exit=0` (measured: 646 passed for the two layout modules);
`Found 184 errors in 16 files (checked 167 source files)`; ruff silent. Under
load the full run can die inside CP-SAT on the pytest-timeout faulthandler kill
(`libortools ... VariablesShavingSolver`); that is the project's recorded quirk,
so judge by the failure list rather than by the absence of a summary line, and
re-run the killed module on its own.

- [ ] **Step 8: Commit**

```bash
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py tests/layout/test_strip_variants.py tests/layout/test_freeform.py
git commit -m "fix(layout): plan a belt-port host one output lane per drain port

An Energy Exchanger has one north-facing port at every yaw, and the strip
planner sized its output lanes from the SORTER reach and the south face --
the wrong question for a host that takes no sorter at all.  A spec whose
product has an internal consumer as well as an external one therefore got two
lane rows for one port and refused outright, in 1.5s, before any search.

Capped at the drain-dock count, _merge_lanes folds both destinations onto one
lane with DEST_SEP and _dock_lane drains it unchanged, so the second lane is
never planned and cannot ship unwired.  Fanning one port out across two lane
rows was built four ways and measured: tapping the lane tile the column feeds
fails 12/12 on splitter-port and silently; tapping one column east fails on
belt-keepout; excusing that keepout emits splitters our own game.belt_collide
convicts as unstable merges; and raising instead of skipping regresses
output-products to REFUSED on both strategies.

The refusal message blamed the ingredient docks for a drain failure; it names
the drain now, and the other three arms of that chain are untouched.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 4: The belt-collide exemption stops covering the machines we place

`catalog.LOW_CONFIDENCE_FOOTPRINTS` was justified (`catalog.py:690-697`) as
"none of them placed by the generator". `MODE_DRIVEN_MACHINE`
(`catalog.py:810-818`) made 2209 a machine we place, and the guard test
(`tests/dsp/test_catalog.py:418-424`) hardcodes a `generator_places` set that was
never updated, so it passed vacuously while `validate.py:2689` suppressed real
convictions -- 38 of them across the five buildable pairs of the reported URL.

**Safety case, stated because a reader cannot reconstruct it.**
`LOW_CONFIDENCE_FOOTPRINTS = {2101, 2104, 2203, 2205, 2209, 2210, 2212}`;
`MODE_DRIVEN_MACHINE_ITEM_IDS = {2208, 2209}`; the subtraction leaves
`{2101, 2104, 2203, 2205, 2210, 2212}` exempt and newly checks **exactly one
building, 2209**. 2208 was never in the set, so nothing changes for the Ray
Receiver. No corpus cell places a 2209, so **no currently-clean corpus cell can
turn INVALID from this task.** The corpus risk in this plan is Tasks 2 and 3.

This lands **after** Tasks 2 and 3 because on master it makes an Energy Exchanger
unbuildable: `_assert_energy_exchanger_port_routing` (`test_freeform.py:9354`,
called from `:5355` and `:9414`) ends with `assert validate.certify(...).ok`, and
`freeform` refuses a placement its own validator rejects (`freeform.py:17027`).

**Files:**
- Modify: `src/flab2bp/dsp/catalog.py` -- a pointer after `:697`, two constants after `:818`
- Modify: `src/flab2bp/dsp/registry.py:367`
- Modify: `src/flab2bp/layout/validate.py:2689`, and the docstring at `:2480-2500`
- Test: `tests/dsp/test_catalog.py:418-424`, `tests/layout/test_validate.py`

**Interfaces:**
- Consumes: nothing (independent of Tasks 1-3 in code).
- Produces: `catalog.MODE_DRIVEN_MACHINE_ITEM_IDS: frozenset[int]`,
  `catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS: frozenset[int]`.

- [ ] **Step 1: Write the failing guard tests**

Replace `test_low_confidence_footprints_are_not_production_buildings`
(`tests/dsp/test_catalog.py:418-424`) with:

```python
def test_the_exemption_never_covers_a_building_we_place() -> None:
    """A footprint we distrust is only exempt while we never place it.

    The set this replaces hardcoded thirteen assembler-ish item ids and was
    written before MODE_DRIVEN_MACHINE existed, so it passed vacuously while
    validate suppressed real belt collisions on an Energy Exchanger.  Derive
    the answer from the two places a MachineGroup's machine comes from: a
    recipe's producers, and the mode-driven table.

    NOT from Dataset's machine ids: the lab dataset lists Wind Turbines, Solar
    Panels, Artificial Stars, Satellite Substations and Interstellar Logistics
    Stations as machines, and the generator never places one as a producer, so
    that form fails on five buildings that are legitimately still exempt.
    """
    from flab2bp.lab.data import load_vendored

    data = load_vendored()
    placed = {driven.machine_item_id for driven in catalog.MODE_DRIVEN_MACHINE.values()}
    for recipe in data.recipes:
        for producer in recipe.producers:
            try:
                placed.add(catalog.item_id(producer))
            except KeyError:
                continue  # a lab producer with no DSP building is not one we place
    assert not (placed & catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS), sorted(
        placed & catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS
    )
    assert catalog.ENERGY_EXCHANGER_ID in placed
    assert catalog.ENERGY_EXCHANGER_ID in catalog.LOW_CONFIDENCE_FOOTPRINTS
    assert catalog.ENERGY_EXCHANGER_ID not in catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS


def test_only_the_energy_exchanger_becomes_newly_checked() -> None:
    """2208 was never exempt, so the Ray Receiver's behaviour does not move."""
    assert catalog.RAY_RECEIVER_ID not in catalog.LOW_CONFIDENCE_FOOTPRINTS
    newly_checked = (
        catalog.LOW_CONFIDENCE_FOOTPRINTS - catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS
    )
    assert newly_checked == {catalog.ENERGY_EXCHANGER_ID}
    assert catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS == {2101, 2104, 2203, 2205, 2210, 2212}


def test_the_mode_driven_ids_are_read_off_the_table() -> None:
    assert catalog.MODE_DRIVEN_MACHINE_ITEM_IDS == frozenset(
        driven.machine_item_id for driven in catalog.MODE_DRIVEN_MACHINE.values()
    )
    assert catalog.MODE_DRIVEN_MACHINE_ITEM_IDS == {
        catalog.ENERGY_EXCHANGER_ID,
        catalog.RAY_RECEIVER_ID,
    }
```

Measured green in a scratch copy: `placed & narrowed == []`, `2209 in placed`.

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/dsp/test_catalog.py::test_the_exemption_never_covers_a_building_we_place -x -q; echo "exit=$?"`
Expected: non-zero, `AttributeError: module 'flab2bp.dsp.catalog' has no attribute 'UNPLACED_LOW_CONFIDENCE_FOOTPRINTS'`.

- [ ] **Step 3: Find every consumer of the constant before changing what `validate` reads**

```bash
grep -rn '"LOW_CONFIDENCE_FOOTPRINTS"' src tests scripts docs
grep -rn "'LOW_CONFIDENCE_FOOTPRINTS'" src tests scripts docs
grep -rn "LOW_CONFIDENCE_FOOTPRINTS" src tests scripts docs
```

Expected on `688cbed`: `catalog.py:697`, `registry.py:364`, `validate.py:2495`
and `:2689`, `dsp/rules.py:54`, `tests/dsp/test_catalog.py:425`,
`tests/dsp/test_colliders.py:287` and `:326`,
`tests/dsp/test_local_offset.py:113` and `:122`, `docs/RULE_LEDGER.md:331`,
`docs/RULE_AUDIT.md:435`. Decide per hit whether it wants the raw set (a
statement about our evidence) or the narrowed one (a check skipping a building),
and list every hit and its verdict in the commit message.

- [ ] **Step 4: Implement**

`MODE_DRIVEN_MACHINE` is at `catalog.py:810`, *after*
`LOW_CONFIDENCE_FOOTPRINTS` at `:697`, so the constants go after its closing
brace (`:818`):

```python
#: DSP item ids of the mode-driven buildings, read off the table above.
#:
#: Listed nowhere: the hardcoded "buildings the generator places" set this
#: replaces was written before `MODE_DRIVEN_MACHINE` existed, so it did not
#: know we place an Energy Exchanger, and the guard that depended on it passed
#: vacuously while `validate` suppressed real belt collisions on one.
MODE_DRIVEN_MACHINE_ITEM_IDS: frozenset[int] = frozenset(
    driven.machine_item_id for driven in MODE_DRIVEN_MACHINE.values()
)

#: The belt/collider exemption, narrowed to what it always claimed to be.
#:
#: `LOW_CONFIDENCE_FOOTPRINTS` says "none of them placed by the generator".
#: That sentence is the whole justification for suppressing a conviction, and
#: the mode-driven feature falsified it for **2209** without touching the
#: sentence.  2208 was never in the distrusted set, and every other machine we
#: place was, and stays, absent from it -- so this subtraction newly checks
#: exactly one building.
UNPLACED_LOW_CONFIDENCE_FOOTPRINTS: frozenset[int] = (
    LOW_CONFIDENCE_FOOTPRINTS - MODE_DRIVEN_MACHINE_ITEM_IDS
)
```

Add a forward pointer after `catalog.py:697`:

```python
# Read UNPLACED_LOW_CONFIDENCE_FOOTPRINTS, not this, when the question is "may
# a check skip this building?".  This set is the raw distrust; that one is the
# distrust minus what we place, which is what the claim above means.
```

In `src/flab2bp/dsp/registry.py`, after
`_e("catalog.MODE_DRIVEN_MACHINE", Kind.DATA),` (`:367`):

```python
    _e(
        "catalog.MODE_DRIVEN_MACHINE_ITEM_IDS",
        Kind.DERIVED,
        projection_of="catalog.MODE_DRIVEN_MACHINE",
        note="The machines a MachineGroup can name that are not ordinary "
        "producers.  Derived so a new mode-driven building cannot silently "
        "keep a footprint exemption it should lose.",
    ),
    _e(
        "catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS",
        Kind.DERIVED,
        projection_of="catalog.LOW_CONFIDENCE_FOOTPRINTS",
        depends_on=("catalog.MODE_DRIVEN_MACHINE_ITEM_IDS",),
        note="The belt-collider exemption actually consulted by validate.  The "
        "unnarrowed set suppressed convictions on an Energy Exchanger we place.",
    ),
```

`tests/rules/test_rule_registry.py:120-124` requires a `DERIVED` entry's
`projection_of` to be itself declared; both are.

In `src/flab2bp/layout/validate.py:2689`:

```python
        if bs[ic].item_id in cat.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS:
```

- [ ] **Step 5: Say that this un-skips BOTH checks, and fix the docstring**

`_belt_collide_findings` (`validate.py:2673`) is called by `game.belt_crossing`
(`:2507`) and `game.belt_collide` (`:2670`). The membership test is shared, so
narrowing turns 2209 convictions on for **both**, and `OPT_IN` is empty
(`:747`), so both run by default and both are errors.

At `validate.py:2495`, replace the bullet

> * ``catalog.LOW_CONFIDENCE_FOOTPRINTS`` is left out, for the reason already
>   recorded there.

with

> * ``catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS`` is left out -- the distrusted
>   footprints we never place.  One we DO place is convicted here like any other
>   building: the exemption's own justification is "none of them placed by the
>   generator", and the mode-driven Energy Exchanger falsified it.
>   ``game.belt_collide`` consults the SAME narrowed set, so the sentence above
>   about it being "the same rule without this narrowing" still holds -- the two
>   differ only in the probe-inside restriction, never in the exemption.

Re-read the surrounding paragraph at `:2480-2490` after the edit and adjust the
sentence, not only the bullet.

- [ ] **Step 6: Add the positive control the exemption used to hide**

Add to `tests/layout/test_validate.py`, near the other `game.belt_collide` tests
(`:4624`):

```python
def test_belt_collide_convicts_an_energy_exchanger_approach() -> None:
    """A five-tile approach inside a 2209's collider is not excused.

    Three tiles are: the docking belt (147492) and the two behind it (147443).
    A run that turns beside the exchanger and climbs its collider column is
    four and five hops out and the game flags both, which is what
    /home/dannyb/full8.png shows on all three exchangers.  On master the
    exemption suppresses all of them and this set is empty.
    """
    info = cat.building(cat.ENERGY_EXCHANGER_ID)
    belt_model = cat.building(2002).model_index
    buildings = [
        PlacedBuilding(
            item_id=info.item_id,
            model_index=info.model_index,
            x=0,
            y=0,
            width=info.width,
            height=info.height,
        )
    ]
    buildings += [
        PlacedBuilding(item_id=2002, model_index=belt_model, x=7, y=y, width=1, height=1)
        for y in range(0, 5)
    ]
    buildings.append(
        PlacedBuilding(item_id=2002, model_index=belt_model, x=6, y=4, width=1, height=1)
    )
    for i in range(1, 6):
        buildings[i] = replace(buildings[i], output_obj=i + 1)
    buildings[6] = replace(buildings[6], output_obj=0)
    report = validate(Placement(buildings=tuple(buildings)), only={"game.belt_collide"})
    convicted = {f.buildings[0] for f in report.by_check("game.belt_collide")}
    assert convicted == {2, 3}, report.by_check("game.belt_collide")
```

`Finding` has fields `check, severity, message, buildings, detail` -- there is no
`indices`. `{2, 3}` and not `{1, 2}`: the belt at `(7, 0)` is at `dy=-4` and does
not overlap at all, so the run is six belts of which 4, 5 and 6 are rescued.
Both measured. Match this module's own `Placement`/`validate` construction --
read a neighbouring test with `mcp__serena__find_symbol` first.

- [ ] **Step 7: Record what each check reports on the reported URL**

```bash
uptime; vmstat 1 3
URL=$(head -1 /home/dannyb/broke6.txt)
uv run flab2bp "$URL" --strategy freeform --candidate-policy all-products --verbose 2>&1 | tail -20
```

Expected after Tasks 2-3: `errors 0`. Note in the commit message the counts
`game.belt_collide` and `game.belt_crossing` each report. Both must be zero; if
either is not, Task 2 or 3 is incomplete and this task must not be committed.

- [ ] **Step 8: Suite, types, lint**

```bash
uv run pytest -q; echo "exit=$?"
uv run mypy src tests 2>&1 | tail -1
uv run ruff check . && uv run ruff format --check .
```

Expected: `exit=0`; `Found 184 errors in 16 files (checked 167 source files)`; ruff silent.

- [ ] **Step 9: Commit**

```bash
git add src/flab2bp/dsp/catalog.py src/flab2bp/dsp/registry.py src/flab2bp/layout/validate.py tests/dsp/test_catalog.py tests/layout/test_validate.py
git commit -m "fix(validate): convict belts against the machines we actually place

LOW_CONFIDENCE_FOOTPRINTS was justified as 'none of them placed by the
generator'.  MODE_DRIVEN_MACHINE made 2209 a machine we place and nobody
updated the guard, whose generator_places set was hardcoded, so the exemption
silently suppressed real collisions on every Energy Exchanger blueprint --
38 of them across the five buildable pairs of the reported URL.

Both sets are derived now.  Exactly one building becomes newly checked, 2209:
2208 was never exempt, and no corpus cell places a 2209.  The narrowed set is
shared by game.belt_collide and game.belt_crossing, so both stop skipping it.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 5: The reported URL builds clean end to end

Both acceptance criteria in one deterministic test: all six strategy/candidate
pairs build, and no emitted placement carries a belt the paste would convict --
asserted on the raw primitive **and** on the two check ids, so a future exemption
regression is caught by name and not only by the primitive.

**Files:**
- Create: `tests/bench/test_broke6_url.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.

- [ ] **Step 1: Confirm `Build`'s fields before writing the test**

`mcp__serena__find_symbol` on `Build` in `src/flab2bp/pipeline.py` (`:443`) and
confirm `report`, `placement`, `spec`, `refused`. `Build.refused` is real
(`pipeline.py:383`) but is never populated on a single-policy call --
`pipeline.build` **raises** `NoValidLayout` instead, so the test must catch it or
it errors out of the loop instead of asserting.

- [ ] **Step 2: Write the test**

Create `tests/bench/test_broke6_url.py`:

```python
"""The URL from /home/dannyb/broke6.txt: two defects, one machine.

`freeform/output-products` refused because an Energy Exchanger's two
accumulator-full output lanes wanted two north-facing docks and it has one.
Every OTHER pair built and pasted with red belts -- 8, 6, 8, 6 and 10 of them --
because the approach column climbed the exchanger's collider and validate
skipped the building.

Not a wall-clock test: it asserts on verdicts, never on seconds.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp import pipeline
from flab2bp.dsp import colliders
from flab2bp.layout import validate
from flab2bp.layout.base import NoValidLayout
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, CandidatePolicy

pytestmark = pytest.mark.timeout(900)

URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNzD8PgjAUBPBv0-Gm1.pvestriJsRE5WOig"
    "wKhATB6NLPbhqldPtdLncdZzCkOpYSmgjQwY.EbvYGS6JYCBYxnLCmZG0mDzOlhFlN.oTtz0X4..uZ"
    "-JxYLjHcrxWL6qs37-FwQ40RsoMcIQWk9tLAbmFzbw-qbXt2Xnzmc.Virb9KujnI&v=11"
)


@pytest.mark.parametrize("strategy", ["freeform", "sequence-pair"])
@pytest.mark.parametrize("policy", DEFAULT_CANDIDATE_POLICIES, ids=lambda p: p.value)
def test_the_pair_builds_and_pastes_clean(strategy: str, policy: CandidatePolicy) -> None:
    try:
        build = pipeline.build(
            URL, strategy=strategy, candidate_policies=(policy,), time_budget_s=15.0
        )
    except NoValidLayout as exc:
        pytest.fail(f"{strategy}/{policy.value} refused: {exc}")
    assert build.report.ok, (strategy, policy.value, build.report.errors)
    ctx = validate._context(build.placement, build.spec, None, 0, Fraction(4), True)
    previews = validate._paste_previews(ctx)
    # The raw primitive, asked with NO exemption -- the game asks it that way.
    assert colliders.stable_belt_collisions(previews) == [], (strategy, policy.value)
    # And by check id, so a future exemption regression is caught by name.
    for cid in ("game.belt_collide", "game.belt_crossing"):
        assert not build.report.by_check(cid), (strategy, policy.value, cid)


def test_the_spec_really_contains_two_energy_exchanger_modes() -> None:
    """Guard the reproduction: output-products is the candidate with both."""
    build = pipeline.build(
        URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.OUTPUT_PRODUCTS,),
        time_budget_s=15.0,
    )
    recipes = {g.recipe_id for g in build.spec.groups}
    assert {"accumulator-full", "accumulator-discharge"} <= recipes
```

`CandidatePolicy.OUTPUT_PRODUCTS` is named, never indexed positionally.
`pyproject.toml:84` sets `timeout = 120`, which a single 15 s build plus
finalization would blow; the module mark raises it. Parametrising over policy as
well as strategy keeps each *test* to one build, so no single case approaches the
module timeout.

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/bench/test_broke6_url.py -q; echo "exit=$?"`
Expected: `exit=0`, **seven** passing cases -- 2 strategies x 3 policies from the
parametrised test, plus `test_the_spec_really_contains_two_energy_exchanger_modes`.
Measured after Tasks 1-3 in a scratch copy: all six pairs `errors=0`,
`stable_belt_collisions=0`, areas 1512 / 1785 / 1792 / 1568 / 1548 / 2262.

- [ ] **Step 4: Confirm the CLI agrees**

```bash
uptime; vmstat 1 3
URL=$(head -1 /home/dannyb/broke6.txt)
time timeout 900 uv run flab2bp "$URL" --verbose 2>&1 | tail -20
```

Expected: six rows in the candidate table, **no** "produced no layout" section,
`errors` column all `0`.

- [ ] **Step 5: Commit**

```bash
git add tests/bench/test_broke6_url.py
git commit -m "test: pin the broke6 URL on both acceptance criteria

All six strategy/candidate pairs build, and no emitted placement carries a
belt the paste would convict -- asserted on the raw primitive with no
exemption, and by check id so an exemption regression is caught by name.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 6: The 72-cell corpus gate, three rounds against fresh baselines

**The gate is load-bearing, not reassurance.** The earlier claim that no corpus
cell touches this path was wrong: `universe-matrix` places **8-10 Ray Receivers**
in all three candidates. The earlier measurement tested
`MachineGroup.machine_item_id` against the ints `{2208, 2209}`, but the field is
the FactorioLab string `"ray-receiver"` (`freeform.py:1857`,
`catalog.get_item_id(mg.machine_item_id)`), so the membership test was vacuously
empty. A Ray Receiver has no input lanes, so it reaches `_port_variants` and
`_dock_lane` on **6 of the 72 cells** (`universe-matrix` x 3 candidates x 2
strategies, tier STRESS). Task 4 remains corpus-inert because 2208 was never
exempt; Tasks 2 and 3 are not.

**Watched clause:** the three `universe-matrix` cells' strip counts and areas
must not move. Compare them explicitly, in addition to `audit_compare`'s verdict.

**Files:** no source changes. Evidence to `docs/superpowers/evidence/broke6/`,
which is tracked; `.superpowers/` is git-ignored and would lose it.

- [ ] **Step 1: Build two fresh baselines from a git archive of the merge-base**

```bash
MB=$(git -C /home/dannyb/sources/factorio-lab-to-blueprint merge-base HEAD master)
for n in 1 2; do
  BASE=/tmp/broke6-baseline-$n
  rm -rf "$BASE" && mkdir -p "$BASE"
  git -C /home/dannyb/sources/factorio-lab-to-blueprint archive "$MB" | tar -x -C "$BASE"
  cp /home/dannyb/sources/factorio-lab-to-blueprint/src/flab2bp/layout/_*.cpython-314-x86_64-linux-gnu.so \
     "$BASE/src/flab2bp/layout/"
done
```

Two baseline rounds, not one: "one round is a sample of one" applies to the
baseline as much as to the candidate, and step 5 uses the second to measure the
noise floor the candidate is judged against. A worktree or `git checkout` is
forbidden here; the archive is the baseline. Copying the checkout's `.so` is
sound only because no task edits `src/flab2bp/layout/_*.pyx` (Global
Constraints).

- [ ] **Step 2: Record the box before timing anything**

```bash
uptime; vmstat 1 3
```

Paste both outputs into `docs/superpowers/evidence/broke6/gate.md`. The box is
never idle and its load is I/O wait; do not wait for it to settle.

- [ ] **Step 3: Run the baseline audits**

```bash
for n in 1 2; do
  rm -f "/tmp/broke6-baseline-$n.jsonl"
  ( cd "/tmp/broke6-baseline-$n" && \
    /home/dannyb/sources/factorio-lab-to-blueprint/.venv/bin/python scripts/audit.py \
      --tier stress --budget 30 --jobs 16 --json "/tmp/broke6-baseline-$n.jsonl" )
done
```

`--json` **appends** (`audit.py:694`), hence the `rm -f`: a re-run into the same
path silently doubles the rows and `--expect-cells 72` would then pass on a
half-run file. `scripts/audit.py` inserts its own `src` at `sys.path[0]`, so the
copy's script under the checkout's interpreter audits the copy. `audit.py` prints
`NOT CLEAN` on any refusal including pre-existing ones; that is not the verdict
here, `audit_compare` is. Record the exit code and move on.

- [ ] **Step 4: Run the candidate audits three times**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint
for round in 1 2 3; do
  rm -f "/tmp/broke6-candidate-$round.jsonl"
  uv run python scripts/audit.py --tier stress --budget 30 --jobs 16 \
    --json "/tmp/broke6-candidate-$round.jsonl"
done
```

- [ ] **Step 5: Compare each round, plus the baseline self-check**

```bash
for round in 1 2 3; do
  echo "=== round $round ==="
  uv run python scripts/audit_compare.py \
    /tmp/broke6-baseline-1.jsonl "/tmp/broke6-candidate-$round.jsonl" \
    --regressions-only --expect-cells 72 --p95-seconds 31
  echo "exit=$?"
done
echo "=== baseline self-check (2 vs 1): the noise floor ==="
uv run python scripts/audit_compare.py \
  /tmp/broke6-baseline-1.jsonl /tmp/broke6-baseline-2.jsonl \
  --regressions-only --expect-cells 72 --p95-seconds 31
echo "exit=$?"
```

Expected: `exit=0` on all three candidate rounds. A non-zero exit names the
regressed cells; each is a bug in this branch until shown otherwise. If the
baseline self-check fails, the threshold is wrong rather than the branch, and
that must be said before any candidate verdict is believed.

- [ ] **Step 6: Check the watched universe-matrix clause**

```bash
uv run python - <<'PY'
import json
def cells(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("url_id") == "universe-matrix":
            out[(r["strategy"], r["spec_index"])] = (
                r.get("status"), r.get("area"), r.get("buildings")
            )
    return out
base = cells("/tmp/broke6-baseline-1.jsonl")
for round in (1, 2, 3):
    cand = cells(f"/tmp/broke6-candidate-{round}.jsonl")
    for key in sorted(set(base) | set(cand)):
        print(round, key, "base", base.get(key), "cand", cand.get(key))
PY
```

Read the real JSONL field names from `scripts/audit.py`'s `--json` writer
(`mcp__serena__find_symbol`, then the handling near `:694`) and use them; the
keys above are the expected shape, not a promise. Every `universe-matrix` cell
must keep its status, and its area must stay within the baseline self-check's
noise. A moved area on a ray-receiver cell is Task 3 touching a path it promised
not to.

- [ ] **Step 7: Record the evidence and commit it**

```bash
mkdir -p docs/superpowers/evidence/broke6
# append every command above, its full output, and the four verdicts to gate.md,
# then fill in the ## Status section of this plan
git add docs/superpowers/evidence/broke6/gate.md \
        docs/superpowers/plans/2026-09-03-energy-exchanger-input-docks.md
git commit -m "docs(gate): three-round corpus gate for the Energy Exchanger fix

Two baselines from git archives of the merge-base; three candidate rounds at
--budget 30 --jobs 16; audit_compare --regressions-only --expect-cells 72
--p95-seconds 31 passed on all three, plus the baseline self-check for the
noise floor and the universe-matrix ray-receiver watched clause.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

Evidence file size is not a concern; do not trim it.

---

## Status

> **Merged and gated.** Tasks 1-5 landed on `energy-exchanger` (final code commit `229c9a3`);
> Task 6's corpus gate ran three candidate rounds against two fresh baselines archived
> from the merge-base `3a10f21`, all `--tier stress --budget 30 --jobs 16`. `audit_compare`
> PASSED on all three candidate rounds (area ratios 0.9969/0.9984/0.9964) and the baseline
> self-check (0.9961, the noise floor every candidate round sits inside; the worst per-cell
> area delta, 0.1107, is the same cell in the baseline-vs-baseline comparison). The
> `universe-matrix` watched clause PASSED (zero cells moved status or area across 18
> comparisons) but is corpus-inert at this budget: all six cells refuse for reasons
> unrelated to this branch, and their refusal text is byte-identical before and after.
> The positive evidence for the fix is Task 5's end-to-end pin (`tests/bench/test_broke6_url.py`),
> whose seven tests fail on the merge-base and pass on the branch. Full evidence:
> `docs/superpowers/evidence/2026-09-03-energy-exchanger/broke6-gate/gate.md`.

---

## Self-Review

**1. Spec and review coverage.**

| Requirement | Task |
| --- | --- |
| Diagnosis 3.2 exemption is stale (Option 1 change 1) | 4 |
| Diagnosis 3.4 approach column climbs the collider (Option 1 change 2) | 1, 2 |
| Diagnosis 4 Option 1 change 2, second conjunct (the tap column is inside the strip box) | 2 steps 4-5. Measured: the **lane trim** at `freeform.py:1163`, not the pitch, was the blocker; step 5 asserts the pitch and names `with_minimum_pitch_x` as the contingent fix |
| Diagnosis 2.1 one drain dock, two lanes (Option 1 change 3) | 3 |
| Diagnosis 2.2 refusal text blames the wrong side | 3 step 6 |
| Acceptance 1-3 | 5 |
| Acceptance 4 (corpus gate) | 6 |
| Review A C1 (reserved pitch) | 2 step 5 |
| Review A C2 / B C3 (`_port_variants` is the wrong site) | 3 preamble: `_port_variants` returns `()` for this strip and is not edited. The fix is `_logical_strip_plans`' `out_capacity`, upstream of both. |
| Review A C3 / B C5 (fan-out had no code, wrong direction) | Superseded by re-review N1: the fan-out was built four ways and none works. Task 3 removes the need for one -- table in the preamble, cap in step 3. |
| Re-review N1 (fan-out fails 12/12, silently) | Task 3 rewritten: no `_dock_cargo_lanes`, no discarded return, no silent skip. The second lane is never planned. Measured: 646 tests pass, six pairs clean. |
| Re-review N2 (step-1 test would go red; `validate.validate` without `ids`) | Task 3 steps 1, 2 and 4 assert the measured shape (one lane, both destinations under `DEST_SEP`, one drawing belt per machine) and use `validate.certify` |
| Re-review N3 (snapshot licence) | Task 2 step 10, both determinism and identity measurements recorded |
| Re-review N4 (pitch test too narrow) | Task 2 step 5, every belt-port host at four yaws, with a non-vacuity floor |
| Re-review N5 (import drift) | Task 2 step 9, the module's real imports and `F` alias |
| Re-review N6 ("thirteen passing cases") | Task 5 step 3, seven |
| Re-review 2 N7 (fixture and assertion disagree) | Task 3 step 1 split in two: `count=1` asserts the DEST_SEP fold, `count=3` asserts the sharded shape it actually produces; the fixture takes `count` and the freeform test pins `count=3` |
| Re-review 2 N8 (+18.5% on sequence-pair/output-products) | Ground-truth table, "Two figures that need saying out loud" |
| Re-review 2 N9 (1785 vs 1505; the widening below the hunk) | Same table row; Task 3 step 3's "Insert ABOVE the `_has_exact_two_face_seating` block" paragraph |
| Review A I1 (count is a proxy; the rescue is a suffix rule) | 1 step 3 docstring; 2 step 3's `hits != suffix` guard; 2 step 1's `cells[-2:] == inside` |
| Review A I2 / B I9 (`belt_crossing` also un-skipped) | 4 step 5; 5 step 2 |
| Review A I3 (Self-Review named constants that exist nowhere) | this section, rewritten against the plan as it stands |
| Review A I4 / B I6 (`strip.pw` used as a lane row) | 2 step 3 (`probe.height + 1`, with the reason) and step 7 |
| Review A I5 (safety case unstated) | 4 preamble; `test_only_the_energy_exchanger_becomes_newly_checked` |
| Review A M1 (constant-vs-literal test) | 1 step 1, replaced by the diagnosis's own six-belt run |
| Review A M2 (vacuous 2208 assertion) | 4 step 1, made explicit in its own test |
| Review A M3 / B M4 (`SORTER_MAX_REACH` as a belt bound) | 2 step 6, bound is `machine.width + 2` with a stated reason |
| Review A M5 / B I7 (positional policy index; build raises) | 5 step 2 |
| Review A M6 (`Build` fields unverified) | 5 step 1 |
| Review A M7 (`.so` copy precondition) | Global Constraints, "No `.pyx` edits" |
| Review A M8 / B M6 (one baseline round; `--json` appends) | 6 steps 1, 3, 5 |
| Review A M9 / B M7 (no status section; evidence git-ignored) | `## Status`; evidence to `docs/superpowers/evidence/broke6/` |
| Review B C1 (Task 3 produced a refusal) | 2 step 4; step 8 runs the two tests that were red |
| Review B C2 (Task 1 alone reddens two tests) | task order; Global Constraints |
| Review B C4 (silently unwired lane) | 3 preamble; step 1's third test |
| Review B C6 (`load_vendored`, `Dataset.machines`, five clashing buildings) | 4 step 1, `recipe.producers` form, measured green |
| Review B I1 (corpus places Ray Receivers) | 6 preamble and watched clause; 2 step 10 and 3 step 7 byte-identity tests |
| Review B I2 (assembler control is vacuous) | 1 and 2, Storage Tank 2106 |
| Review B I3 (`Finding.buildings`, `{2, 3}`) | 4 step 6 |
| Review B I4 (`LogicalLane.items`) | no task uses `lane.item`; `_port_variants` is not edited at all |
| Review B I5 (refusal chain has four arms) | 3 step 6 |
| Review B I8 (test helpers that do not exist) | 2 step 9 and 3 step 1 name the real ones (`mode_driven_spec`, `FreeformLayout`, `BandPolicy`, `validate._paste_previews`) and declare which helpers this commit writes, with the class and fields to build them from |
| Review B M1 (`codec` import) | 1 step 3, the concrete line |
| Review B M5 (module timeout tight) | 5 step 2, `timeout(900)` and one build per test |
| Diagnosis 4 Option 3 (routing keep-out) | Deliberately not planned: belt-and-braces on a fix that already makes the validator the arbiter. Revisit if Task 6 shows another belt-port host producing convictable approaches. |

**2. Placeholder scan.** No `TBD`/`TODO`/`similar to Task N`. Seven steps
deliberately say "read the real name with Serena first" -- `colliders.Preview`'s
keywords (1 step 1), the catalog's building enumeration (2 step 5),
`mode_driven_spec`'s `BuildSpec` construction (2 step 10), `probe`'s binding in
`_logical_strip_plans` and that module's plan-test harness (3 steps 1 and 3),
`test_validate.py`'s own `Placement`/`validate` construction (4 step 6),
`Build`'s fields (5 step 1), and the audit JSONL field names (6 step 6). Each
names the exact lookup, what to do with the answer, and -- for 2 step 5 -- a
non-vacuity floor so a wrong accessor cannot turn the test green by finding
nothing. Four helpers (`_two_sink_exchanger_spec`, `_two_sink_assembler_spec`,
`_plans_for`, `_ray_receiver_spec` with `RAY_RECEIVER_SHAPE`) are declared as
written-in-this-commit; `_two_sink_exchanger_spec` is given verbatim as measured,
and the snapshot carries the instruction to generate it on master so the test is
not a tautology.

**3. Type consistency.**
`slots.belt_tile_hits_collider(host: PlacedBuilding, x: int, y: int, z: Fraction = Fraction(0)) -> bool`
and `slots.MAX_RESCUED_COLLIDER_TILES: int` are defined in Task 1 and used with
that arity in Tasks 1 and 2.
`freeform._port_approach(machine, dock, lane_y, lane_columns, max_offset)` and
`freeform._port_approach_offset(probe, dock, pitch_w)` are defined in Task 2
step 3 and called with those five and three arguments in steps 1, 4, 5, 6 and 7.
Task 3 introduces **no** new symbol: it narrows a local, `out_capacity`, inside
`strip_variants._logical_strip_plans`, and adds one arm to an existing message
chain. `_drainable_by_port(strip) -> bool` and `_feedable_by_port(strip) -> bool`
keep their signatures and, for `_drainable_by_port`, its body. `catalog.MODE_DRIVEN_MACHINE_ITEM_IDS` and
`catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS` are defined in Task 4 step 4 and
used under those names in Task 4's tests, its registry entries and the `validate`
call site. No `PLACED_MACHINE_ITEM_IDS` or `PRODUCER_ITEM_IDS` appears anywhere.

**4. Measured, not remembered.** Every number in "Measured ground truth" and
every line number cited was read or run against `688cbed` in a throwaway
`git archive` copy: `catalog.clearance(2209, 0.0) == (10, 10)`; strip machines at
`x=1, 12` with input lane `x=1..19` and `tap+2 = 20` absent; Tasks 1-3 applied
together turn all six pairs to `errors=0, collisions=0` and make both previously
red exchanger tests pass; the count-only drain relaxation gives one drawing belt
for two lanes with `ok=True`; `Finding` has `buildings` not `indices`;
`load_vendored` is in `flab2bp.lab.data`; the `recipe.producers` guard form gives
`clash == []` with `2209 in placed`; `universe-matrix` places 8-10 Ray Receivers;
`cat.building(2303).port_poses == ()`; Storage Tank 2106's east dock is `(2, 1)`
and its `tap+1` is outside its collider.
`uv run mypy src tests` on `688cbed` prints
`Found 184 errors in 16 files (checked 167 source files)`.

**5. What the re-review changed, and what is still open.** Task 3's original
design -- relax `_drainable_by_port`'s count and fan one drawing port out across
two lane rows -- was measured and does not work: the tap fails 12/12 with
`splitter-port`, silently, leaving a lane joined to nothing while `certify` says
ok. Three repairs were built and measured and each failed differently (tap one
column east: `belt-keepout`; excuse the keep-out: splitters our own
`game.belt_collide` convicts; raise instead of skip: `output-products` REFUSED on
both strategies, because `_emit_strip`'s caller has no per-arrangement `try`).
Task 3 now caps the planned lanes instead, which removes the case rather than
coping with it, and is measured green on all six pairs and on 646 layout tests.

Still open, and stated so nobody re-derives it: **a belt-port host cannot fan one
drain port out to several output lane rows in this strip model.** Output lane
rows are full-width belt runs on adjacent rows, so a junction on the served lane
has two feeders, a junction one column east has its keep-out over the next lane
row, and excusing that keep-out produces an unstable merge. If a future spec ever
needs a genuine multi-lane drain, the lane rows themselves have to change (a lane
that starts at the junction column has no west feeder) -- that is a separate
piece of work, not a tweak to this one. Until then the cap makes the case
unreachable, which is why Task 3 asserts one lane and one drawing belt rather
than two of either.
