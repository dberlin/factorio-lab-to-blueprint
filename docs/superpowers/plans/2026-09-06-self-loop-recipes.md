# Self-Loop Recipes, Mixed Input Lanes and Coater Merges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop emitting blueprints that cannot run — a belt carrying several
different items into one machine, a Spray Coater seated over a belt merge, and
a self-consuming recipe whose loop nothing ever primes — and declare the
self-loop honestly instead of hiding it.

**Architecture:** Three independent corrections to existing machinery, no new
solver. (1) Ban mixed input lanes outright — the validator convicts every lane
carrying two distinct items with **no exemption** (spec §9 R1), the seating
ladder stops producing them, and the one machine family that used to need
mixing is fixed instead: moving a flanked output's drain row past sorter reach
frees the sixth input row a Matrix Lab was short of (spec §9 R2).
(2) Reject a coater seat over a belt merge or an ambiguous
supply area, and convict both in the validator. (3) Derive a `SelfLoopSeed`
from the recipe in the rates layer, carry it to the blueprint icon, the
description, the CLI and the web payload, and let a new check own the
"can this ever start" question. The strip planner's loop lane, built by the
2026-08-28 self-consuming-flow-feedback work, is already correct and is not
touched.

**Tech Stack:** Python 3.14, `uv run`, pytest, pydantic v2, OR-Tools CP-SAT.

**Spec:** `docs/superpowers/specs/2026-09-06-self-loop-recipes-design.md`
**Evidence:** `docs/superpowers/evidence/2026-09-06-selfloop/README.md`

## Global Constraints

- The reported URL, referred to below as `AMM_URL`, is exactly:
  `https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFiWUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DKloJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11`
- `UNIVERSE_MATRIX_URL` below is the corpus entry
  `flab2bp.bench.corpus.URL_CORPUS["universe-matrix"]` (tier STRESS), which is
  exactly:
  `https://factoriolab.github.io/dsp/list?o=universe-matrix*60&ibe=conveyor-belt-3&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11`
  Get it from the corpus rather than retyping it:
  ```bash
  UNIVERSE_MATRIX_URL=$(uv run python -c "from flab2bp.bench.corpus import URL_CORPUS; print(next(e.url for e in URL_CORPUS if e.url_id=='universe-matrix'))")
  ```
- Every production change follows red-green TDD: the failing test in the same
  task, run and seen to fail, before the implementation.
- **Belt SHARING between several consumers of the SAME item stays.**
  `freeform._merge_lanes` and `_merge_frontier` are not touched by any task
  here. Only MULTIPLE DISTINCT ITEMS on one input lane are banned.
- Rate solving's block-wide netting (`rates/solve.py:1306-1329`) is not changed.
  A self-consuming product remains an internal routing net and is never
  reclassified as an external input.
- No per-recipe special case. Every rule is stated over
  `inputs ∩ outputs` or over machine geometry, never over a recipe id.
- Two other agents run builds on this box: **at most ONE build at a time**,
  `--budget 30` for single builds, and record CPU PRESSURE beside every timing.
- **CPU pressure is measured with `vmstat`, never with `uptime` or load average**
  (user instruction, 2026-09-07). Load average on this box is mostly I/O wait and
  says nothing about CPU contention. The number to record is the five-second mean
  of runnable processes:

  ```bash
  cpu_pressure() { vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'; }
  ```

  Below 64 is fine on these 128 cores. **Never wait for it to fall** — record it
  beside the timing and carry on.
- Use Serena's symbolic tools to read and edit; `freeform.py` is 22k lines and
  `validate.py` is large, so read symbols, not files.
- **Mixed belts are given up, not made cleverer** (user note in spec §4 F1).
  The reported blueprint merged the three items onto one belt and still
  starved in game because interleaving is uncontrolled. No task adds
  port-filtered splitters or any other attempt to make a mixed belt work.
- **The user's rulings in spec §9 (2026-09-07) are binding and outrank every
  other paragraph in this plan and in the spec.** In particular:
  - **§9 R1 — the ban on mixed input lanes is ABSOLUTE.** No input lane ever
    carries two distinct items, forced or chosen. There is no
    `_lane_seating_is_forced`, no exemption, and no "the geometry left no
    alternative" argument. `flow.lane_single_item` convicts every mixed input
    lane, and `freeform._seat_inputs` stops producing them so the strategy
    refuses instead of emitting one for the validator to convict.
  - **§9 R2 — `universe-matrix` keeps building by moving the flanked output's
    drain row past sorter reach** (Task 3 below), which is what makes R1
    affordable. Task 3 lands BEFORE Tasks 4 and 5 for that reason.
  - **§9 R3 — priming is prime-once-and-warn** (Tasks 6-9 unchanged).
  - **§9 R4 — `belt.acyclic` stays absolute.** No self-loop exemption; no task
    touches it.
  - **§9 R5 — the Pile Sorter rule stays retracted** (spec §5.3a). No task
    touches `_pick_sorter`.
- No density, area or coverage argument from an implementer or a reviewer
  outranks §9 R1 or spec §4's standing rulings. Measure the cost and report
  it; do not relitigate the rule.

---

## Task 1: Convict a Spray Coater seated over a belt merge

**Files:**
- Modify: `tests/layout/test_validate.py`
- Modify: `src/flab2bp/layout/validate.py`

**Interfaces:**
- Consumes: `validate.Context`, `validate.Finding`, `validate.Severity`, `validate.check`, `validate._addon_rides`, `validate._coater_rides` (`validate.py:4898`), `catalog.SPRAY_COATER_ID`, `catalog.oriented_footprint`, `rules.ADDON_AREA_RADIUS`, `slots.addon_supply_position`.
- Produces: `@check("prolif.coater_rides_one_run", needs_spec=True)` yielding `Finding` at `Severity.ERROR`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_validate.py`:

```python
def test_coater_over_a_belt_merge_is_convicted() -> None:
    """Two belt runs merging on a tile the coater's body covers is not a lane.

    A Spray Coater is a belt addon that rides ONE belt.  Two chains pointing at
    a tile under its body is the geometry that reads in game as belts inserted
    into the coater, and it is exactly the interleaving hazard a mixed lane has.
    """
    placement = _coater_placement(merge_under_body=True)
    report = validate.validate(placement, _coater_spec(), expect_power=False)
    findings = [f for f in report.errors if f.check == "prolif.coater_rides_one_run"]
    assert findings, [f.check for f in report.errors]
    assert "merge" in findings[0].message


def test_coater_on_a_single_run_is_clean() -> None:
    placement = _coater_placement(merge_under_body=False)
    report = validate.validate(placement, _coater_spec(), expect_power=False)
    assert not [f for f in report.errors if f.check == "prolif.coater_rides_one_run"]


def test_coater_supply_area_with_two_belts_is_convicted() -> None:
    """Which belt supplies a coater must not depend on a rotation convention.

    Measured on the reported URL: coater#768's addon area 1 had the proliferator
    lane at (53,20,1) and a CARGO lane at (55,20,1), both exactly 0.250 from the
    area centre and both inside ADDON_AREA_RADIUS = 1.0.
    """
    placement = _coater_placement(merge_under_body=False, second_belt_in_supply_area=True)
    report = validate.validate(placement, _coater_spec(), expect_power=False)
    findings = [f for f in report.errors if f.check == "prolif.coater_rides_one_run"]
    assert findings
    assert "addon area 1" in findings[0].message
```

Add the two builders beside the existing coater fixtures in the same file:

```python
def _coater_spec() -> BuildSpec:
    """One proliferated group whose single ingredient rides a sprayed lane."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="gear",
                machine_item_id="assembling-machine-2",
                count=1,
                proliferator_mode=ProliferatorMode.PRODUCTS,
                inputs_per_machine={"iron-ingot": Fraction(1)},
                outputs_per_machine={"gear": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ingot": Fraction(1), "proliferator-2": Fraction(1, 10)},
        outputs={"gear": Fraction(1)},
        spray_lanes={"iron-ingot": True},
    )


def _coater_placement(
    *,
    merge_under_body: bool,
    second_belt_in_supply_area: bool = False,
) -> Placement:
    """A coater at yaw 90 riding a straight lane, optionally spoiled.

    ``merge_under_body`` adds a second belt chain whose tail points at the tile
    one step upstream of the coater origin -- a tile the 1x3 body covers.
    ``second_belt_in_supply_area`` puts a cargo belt on the mirror side of addon
    area 1, at the same distance as the proliferator belt.
    """
```

- [ ] **Step 2: Run them and see them fail**

```bash
uv run pytest tests/layout/test_validate.py -k coater_over_a_belt_merge -x -q
uv run pytest tests/layout/test_validate.py -k coater_supply_area_with_two_belts -x -q
```

Expected: both FAIL — no such check exists, so `report.errors` holds nothing
with that name. (The pytest summary line never prints in this repo; read the
exit code.)

- [ ] **Step 3: Add the check**

Insert after `_coater_rides` in `src/flab2bp/layout/validate.py` (around line
4918):

```python
def _coater_body_tiles(ctx: Context, index: int) -> set[tuple[float, float, float]]:
    """The tiles a Spray Coater's 1x3 body covers, at its own altitude."""
    b = ctx.placement.buildings[index]
    width, height = cat.oriented_footprint(cat.SPRAY_COATER_ID, b.yaw)
    return {
        (b.x + dx, b.y + dy, b.z)
        for dx in range(-(width // 2), width // 2 + 1)
        for dy in range(-(height // 2), height // 2 + 1)
    }


@check("prolif.coater_rides_one_run", needs_spec=True)
def _coater_rides_one_run(ctx: Context) -> Iterable[Finding]:
    """A Spray Coater rides one belt run, with no merge under its body.

    A coater carries no connection of its own -- the game finds its belts by
    position (``game.addon_supply``) -- so nothing in the record says which lane
    it is on beyond where the belts are.  Two chains pointing at one tile is a
    legal DSP merge in general (``belt.acyclic`` says so), but under a coater it
    is not a lane: the three flows it joins must arrive interleaved in the
    recipe's exact proportion or one of them fills the belt and starves the
    others, and nothing arranges that.

    Measured on the reporting URL: belt#0 at (53,20,0) had predecessors
    [817, 1872] and sat under coater#768's body; belt#19 at (53,26,0) had
    predecessors [830, 2037] under coater#771.  Both blueprints validated clean.

    The second clause is narrower and just as unfixable downstream: two belts
    inside ``rules.ADDON_AREA_RADIUS`` of addon area 1 means which one supplies
    the coater is decided by a rotation convention rather than by the geometry
    we emitted.
    """
```

Body: for each coater index in `_coater_rides(ctx).values()`, compute
`_coater_body_tiles`, find the belts on those tiles, and yield
`Severity.ERROR` when any of them has two or more belt predecessors
(`ctx.pred` restricted to `Kind.BELT`), or when belts of two distinct
`ctx.run_of` values sit on them. Then resolve `slots.addon_supply_position(...,
area=1)` and yield `Severity.ERROR` when more than one belt lies within
`rules.ADDON_AREA_RADIUS` of it.

- [ ] **Step 4: Re-run and see them pass, plus the whole validator suite**

```bash
uv run pytest tests/layout/test_validate.py -q
```

Expected: exit 0.

---

## Task 2: Stop the emitter seating a coater over a merge

**Files:**
- Modify: `tests/layout/test_freeform.py`
- Modify: `src/flab2bp/layout/freeform.py`

**Interfaces:**
- Consumes: `freeform._coater_seats` (`freeform.py:18018`), `freeform._coater_seat` (`freeform.py:18039`), `freeform._place_coaters` (`freeform.py:18140`), `freeform._Canvas`, `freeform._Port`.
- Produces: `freeform._coater_seat` returns `None` for a seat whose covered tiles carry a belt merge or whose area-1 position has two belts; signature unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_freeform.py`:

```python
def test_coater_seat_rejects_a_tile_with_a_belt_merge() -> None:
    """A seat whose body covers a merge is not a seat, however short the lane.

    `_coater_seat` used to answer only "is this drop cell free and is the lane
    long enough".  The reporting URL seated two coaters over 2-into-1 merges
    that way, and `prolif.coater_rides_one_run` now convicts every such
    placement -- so the seat chooser has to agree with the validator or the
    strategy refuses at the last step instead of choosing a legal seat.
    """
    canvas, port = _canvas_with_lane_merge_at(x=53, y=20, z=0)
    assert freeform._coater_seat(canvas, port) is None

    clean_canvas, clean_port = _canvas_with_straight_lane_at(x=53, y=20, z=0)
    assert freeform._coater_seat(clean_canvas, clean_port) is not None
```

- [ ] **Step 2: Run it and see it fail**

```bash
uv run pytest tests/layout/test_freeform.py -k coater_seat_rejects -x -q
```

Expected: FAIL — `_coater_seat` returns a seat for the merged canvas.

- [ ] **Step 3: Add the predicate**

In `freeform._coater_seat`, before returning a candidate `(x, y)`, reject it
when any belt on the tiles the coater body would cover has more than one belt
predecessor on the canvas, or when the area-1 position resolves to more than
one belt within `rules.ADDON_AREA_RADIUS`. Keep the existing `continue` /
`None` contract so `_place_coaters` handles it exactly as it handles a taken
drop cell today; `prolif.sprayed_cargo_reaches_machines`
(`validate.py:5011`) remains the backstop that turns a silently skipped coater
into a refusal.

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/layout/test_freeform.py -q
```

Expected: exit 0.

---

## Task 3: Move a flanked output's drain row past sorter reach

**This task exists to make spec §9 R1 affordable, and it must land BEFORE
Tasks 4 and 5.** Without it, banning mixed lanes makes `universe-matrix` — the
corpus's deepest chain — refuse.

**Files:**
- Modify: `tests/layout/test_strip_variants.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/strip_variants.py`

**Interfaces:**
- Consumes: `freeform._seat_inputs` (`freeform.py:2171`), `freeform._side_lane_caps` (`freeform.py:2093`), `freeform.Strip.first_row_below_band` (`freeform.py:996`), `Strip.row_of_output` (`freeform.py:1174`), `Strip.row_of_input` (`freeform.py:1171`), `Strip._input_attachment_plan` (`freeform.py:1114`), `strip_variants._legacy_side_lane_caps` (`strip_variants.py:1642`), `strip_variants._seat_both_fed_outermost` (`strip_variants.py:1137`), `catalog.SORTER_MAX_REACH` (`catalog.py:299`), `slots.attachable_columns` (`slots.py:374`).
- Produces: a flanked strip whose output drain lane sits on the OUTERMOST south row — past sorter reach — **only when the input lanes need the row it used to occupy**; today's seating otherwise, byte-identical.

### The measurement this task is built on

Run in-tree on master for the Matrix Lab (`item_id 2901`, yaw `0.0`, probe
`5x5`):

```
_side_lane_caps(2901, 0.0, 5)          -> (3, 3)
attachable_columns at lane_y -1/-2/-3  -> 3 columns each;  lane_y -4 -> 0
attachable_columns at lane_y  5/ 6/ 7  -> 3 columns each;  lane_y  8 -> 0
catalog.SORTER_MAX_REACH               -> 3
```

and on `_seat_inputs` with six items, `n_sinks=1`, `max_per_lane=5`,
`columns=3`:

```
caps (3,3), flank_outputs=True   -> ((('a','b','c'),), (('d','e','f'),))   # two MIXED lanes
caps (3,3), flank_outputs=False  -> ValueError "6 ingredients cannot be seated"
caps (3,4), flank_outputs=True   -> ((('a',),('b',),('c',)), (('d',),('e',),('f',)))  # SIX single lanes
```

So one more usable south row is exactly and only what is missing. The reason we
may take it: **the drain lane carries no sorter.** `freeform._flank_lane`
(`freeform.py:6745-6851`, docstring 6768-6770) builds the flanked output as "a
sorter runs from the machine's lowest free east pose into that belt; the belt
runs SOUTH to the output lane under the band and joins it" — the only sorter is
the east one, and the gap belt simply runs one tile further. A row with zero
`attachable_columns` is therefore fine for the drain and useless for an input.
`Strip.sorter_span` (`freeform.py:998-1032`) returns `0` for such a row, and
`_machines_without_poses` already skips flanked strips
(`freeform.py:19230-19232`).

Only **one** plan in the whole corpus is flanked today:

```
FLANK universe-matrix#37 item_id=2901
  above (('antimatter','electromagnetic-matrix','energy-matrix'),)
  below (('gravity-matrix','information-matrix','structure-matrix'),)
  out   (('universe-matrix','',CargoDomain.UNSPRAYED),)
```

`_logical_strip_plans` emits 43 plans for `universe-matrix` and this is the only
one with `flank_outputs`. Everything else in the corpus must stay byte-identical.

### The five expressions involved (verified against master)

| # | file:line | today | what it must become |
|---|---|---|---|
| 1 | `freeform.py:2268` | `if n_sinks and below_cap - len(below) <= 0: continue` | the drain-row reservation. Must stop binding when `flank_outputs` — equivalently, the flanked search may use `below_cap + 1` rows below while line 2266's `len(below) > below_cap` still binds at `below_cap` (an input lane may never sit past reach). |
| 2 | `strip_variants.py:1504-1506` | `out_capacity = below_cap - len(in_below)` then `if flank: out_capacity = min(out_capacity, 1)` | **hard blocker if left alone**: with `len(in_below) == below_cap == 3` this is `0`, and `freeform._shard_sinks` (`freeform.py:1824-1826`) raises `ValueError("no room left on the south side for any output lane")`. On the flank branch it must be `1`. |
| 3 | `strip_variants.py:1205` | `south_output_rows = 1 if n_sinks else 0` inside `_seat_both_fed_outermost.fits` | a third copy of the same charge. Must be `0` when `flank_outputs`, or the both-fed normalisation rejects the wider seating. (`fits` is invariant under reordering — the lane counts do not change — so relaxing it cannot invent a seating `_seat_inputs` did not already produce.) |
| 4 | `freeform.py:1114`, `1171`, `1187` | `first_row_below_band + len(self.out_lanes) + index` (inputs) and `first_row_below_band + k` (output) | the actual row map: the drain must move to the outermost south row and the south inputs must start at offset 0. **Gate on `self.flank_outputs` only** — `1187` is `if self.flank_outputs or self.takes_belt_ports`, and the belt-port case must not move. |
| 5 | `freeform.py:2602-2608` | `box_height = len(inputs_above) + … + len(outputs) + len(inputs_below)` | **no edit** — the extra row falls out of `len(inputs_below)`. |

`freeform.py:2240` (`out_columns = 0 if flank_outputs else …`) already waives the
COLUMN charge and is not touched.

### "Only when the input count needs the freed row"

The user's ruling is explicit that a spec which never needed the row keeps
today's seating so no other area moves. Derive the mode rather than guessing it:

```python
#: True when the flanked output's drain lane has been pushed to the outermost
#: south row because the south INPUT lanes filled every sorter-reachable row.
#: False keeps the pre-2026-09-07 map exactly: drain innermost, inputs after it.
drain_outermost = flank_outputs and len(in_below) == below_cap
```

`below_cap` is the count of contiguous sorter-reachable rows below the band
(`_side_lane_caps`), so `len(in_below) == below_cap` says the inputs already
occupy every row a sorter can reach and the drain has nowhere left inside.
`len(in_below) < below_cap` reproduces today's arithmetic exactly, which is what
keeps `test_the_seating_rule_changes_no_strip_dimension` (`(8, 12)` and
`(8, 36)`) green.

Carry `drain_outermost` on the strip plan and on `Strip` (read the real
dataclasses before writing it — do not invent field names), and make the row map
read:

```python
# Strip.row_of_output, flanked branch
drain_offset = len(self.in_below) if self.drain_outermost else 0
return self.first_row_below_band + drain_offset + k

# Strip.row_of_input / _input_attachment_plan, below-band branch
lane_offset = 0 if self.drain_outermost else len(self.out_lanes)
return self.first_row_below_band + lane_offset + index
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_strip_variants.py`:

```python
def test_a_matrix_lab_seats_six_ingredients_as_six_single_item_lanes() -> None:
    """`universe-matrix` stops needing a mixed belt (spec §9 R2).

    A Matrix Lab is 5x5 with three insert columns per face, and
    `_side_lane_caps` returns (3, 3) at its band height: six reachable rows for
    six ingredients.  The seating was one row short only because the flanked
    output's drain lane was charged a row INSIDE sorter reach, even though the
    drain carries no sorter -- `_flank_lane` puts the only sorter on the east
    face and runs a gap belt south into the lane.  Moving the drain to the
    outermost south row costs one strip row on this family and frees the third
    south row for an input.

    Measured on master before this change: `(('antimatter',
    'electromagnetic-matrix', 'energy-matrix'),)` above and `(('gravity-matrix',
    'information-matrix', 'structure-matrix'),)` below -- two mixed belts, which
    spec §9 R1 bans outright.
    """
    plans = _logical_strip_plans(_universe_matrix_spec())
    (plan,) = [p for p in plans if p.flank_outputs]
    lanes = (*plan.in_above, *plan.in_below)
    assert len(lanes) == 6, lanes
    assert all(len(lane) == 1 for lane in lanes), lanes


def test_the_flanked_drain_lane_sits_past_sorter_reach_when_it_moved() -> None:
    """The row it moved to is one no sorter could have used anyway.

    `_side_lane_caps` counts CONTIGUOUS reachable rows outward from the band, so
    row `below_cap` is the first row with no `attachable_columns` at all.  That
    is precisely why the drain may have it and an input may not.
    """
    strip = _flanked_strip_for(_universe_matrix_spec())
    assert strip.drain_outermost
    drain_row = strip.row_of_output(0)
    assert strip.sorter_span(drain_row) == 0
    for lane in strip.in_below:
        row = strip.row_of_input(lane)
        assert 1 <= strip.sorter_span(row) <= catalog.SORTER_MAX_REACH


def test_a_flanked_strip_that_never_needed_the_row_is_unchanged() -> None:
    """No other spec's area moves (the user's ruling, spec §9 R2).

    A flanked group whose south inputs do not fill every reachable row keeps the
    pre-2026-09-07 map exactly: drain innermost, inputs pushed out by
    `len(out_lanes)`.  Pinned as byte-identical row indices, not as a shrug.
    """
    strip = _flanked_strip_for(_two_ingredient_flanked_spec())
    assert not strip.drain_outermost
    assert strip.row_of_output(0) == strip.first_row_below_band
    assert strip.row_of_input(strip.in_below[0]) == strip.first_row_below_band + 1
```

Add to `tests/layout/test_freeform.py`, beside the existing flanked-seating
tests at `test_freeform.py:2927-2966`:

```python
def test_seat_inputs_uses_the_freed_south_row_only_when_flanked() -> None:
    """The drain-row waiver is scoped to the flanked path and nothing else.

    Unflanked, the output lane really does need a sorter-reachable row under the
    band, so the reservation at freeform.py:2268 still binds.
    """
    six = ("a", "b", "c", "d", "e", "f")
    above, below = freeform._seat_inputs(
        six, 1, 3, 3, max_per_lane=5, columns=3, flank_outputs=True
    )
    assert [len(lane) for lane in (*above, *below)] == [1, 1, 1, 1, 1, 1]
    with pytest.raises(ValueError, match="cannot be seated"):
        freeform._seat_inputs(six, 1, 3, 3, max_per_lane=5, columns=3)
```

Read `_seat_inputs`' real signature (`freeform.py:2171-2184`) and match it —
the arguments above are positional in the current code and that may change
under Task 5.

- [ ] **Step 2: Run them and see them fail**

```bash
uv run pytest tests/layout/test_strip_variants.py -k "six_single_item_lanes or past_sorter_reach or never_needed_the_row" -q; echo "exit=$?"
uv run pytest tests/layout/test_freeform.py -k seat_inputs_uses_the_freed_south_row -q; echo "exit=$?"
```

Expected: non-zero. The first test sees two mixed lanes; the second sees a
`ValueError` from the flanked call too. (The pytest summary line never prints in
this repo — read the exit code.)

- [ ] **Step 3: Implement the five change points**

Work through the table above in order 1, 2, 3, 4. Everything is gated on
`flank_outputs` / `drain_outermost`; nothing changes for an unflanked strip.
Update the docstrings that now describe the old behaviour:

- `freeform.py:2238-2240` — the comment "The output lane still needs its ROW
  under the band even when flanked -- the gap belts drain into it -- so only the
  column charge goes away" is now wrong. It still needs a row; what changed is
  that the row need not be one a sorter can reach.
- `freeform.py:2209-2224` — the `universe-matrix` note ends "three ingredients
  mixed onto one lane above, three onto one below, and the product out east."
  That seating is now banned by spec §9 R1. Rewrite it to say the lab seats six
  single-item lanes because the drain row moved outward, and cite §9 R2.
- `strip_variants.py:1169-1171` — `_seat_both_fed_outermost`'s "including the
  one south output row and column where applicable" needs the flanked exception.

- [ ] **Step 4: Re-run, plus every suite that touches this geometry**

```bash
uv run pytest tests/layout/test_strip_variants.py tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest tests/test_pipeline.py -k universe_matrix -q; echo "exit=$?"
uv run pytest tests/layout -q; echo "exit=$?"
```

Expected: exit 0 everywhere. Tests known to be in the blast radius, all of which
must be reasoned about rather than merely re-run green:

- `tests/layout/test_freeform.py:11070`
  `test_a_six_ingredient_recipe_builds_with_its_product_leaving_east` — the real
  Matrix Lab spec through the full validator. **The primary functional gate.**
- `tests/layout/test_freeform.py:11096`
  `test_the_seventh_connection_lands_on_a_face_no_lane_can_reach` — still 7
  distinct slot ids per lab. **Must stay green unchanged**; it is the invariant
  that says we did not silently drop a connection.
- `tests/layout/test_strip_variants.py:1821`
  `test_the_seating_rule_changes_no_strip_dimension` — pins `(8, 12)` and
  `(8, 36)` on NON-flanked groups. If these move, the change leaked out of the
  flanked path; fix the gating rather than the numbers.
- `tests/layout/test_strip_variants.py:1832`
  `test_every_both_fed_ingredient_is_seated_on_its_side_s_outermost_row` — runs
  corpus-wide and therefore over the flanked plan.
- `tests/test_pipeline.py:1118`
  `test_universe_matrix_at_90_per_minute_never_crashes_strip_planning`.
- `tests/layout/test_freeform.py:3004` helper `_unreachable` asserts
  `1 <= sorter_span(row)` over `row_of_output(k)`. It is used today only on
  unflanked specs (`organic-crystal`, an assembler). **Do not point it at a
  flanked strip** — a drain past reach gives span 0 by design, which is the
  whole point of this task.
- `tests/layout/test_last_mile.py:134,158` pin captured
  `universe-matrix/output-products` clusters and may need their fixtures
  refreshed. If a fixture must be re-captured, say so explicitly in the report
  and show the before/after, rather than editing numbers quietly.

- [ ] **Step 5: Build `universe-matrix` through the CLI and decode it**

ONE build at a time; the `cpu_pressure` number beside the timing.

```bash
E=docs/superpowers/evidence/2026-09-06-selfloop/task3
mkdir -p "$E"
UNIVERSE_MATRIX_URL=$(uv run python -c "from flab2bp.bench.corpus import URL_CORPUS; print(next(e.url for e in URL_CORPUS if e.url_id=='universe-matrix'))")
cpu_pressure | tee "$E/cpu-pressure.txt"
/usr/bin/time -v uv run flab2bp "$UNIVERSE_MATRIX_URL" --budget 30 -v \
  -o "$E/bp-um.txt" 2>&1 | tee "$E/build-um.log"
cpu_pressure | tee -a "$E/cpu-pressure.txt"
uv run python docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_decode.py \
  "$E/bp-um.txt" > "$E/decode-um.txt"
```

PASS requires:

1. the build is CLEAN — `errors 0` on the winning cell, and in particular **no
   `flow.lane_single_item` finding** (the check does not exist until Task 4, so
   at this point the requirement is only that the geometry is there);
2. `decode-um.txt`'s `== machines and their sorters ==` section shows each
   Matrix Lab with **six `from run R: [...]` lines each holding exactly one
   item**, and **no `<<< SHARED-INPUT-RUN` flag**. Quote those lines in the task
   report.

Record the flanked family's `box_height` before and after in the report.
Measured on master it is `1 + 5 + 1 + 1 = 8`; with six single lanes and the
drain moved out it is `3 + 5 + 1 + 3 = 12`. **Report the real number, whatever
it is.** Note honestly that only one of those four rows is the drain move — the
other three are the cost of un-mixing, which Tasks 4 and 5 are what the user
asked for; do not net them together and do not present +4 as +1.

---

## Task 4: Convict a mixed-item input lane (absolutely, no exemption)

**Files:**
- Modify: `tests/layout/test_validate.py`
- Modify: `src/flab2bp/layout/validate.py`

**Interfaces:**
- Consumes: `validate.Context`, `validate._sorter_items`, `validate.Kind`, `catalog.get_item_id`.
- Produces: `@check("flow.lane_single_item", needs_spec=True, needs_groups=True)`.

**Spec §9 R1 applies to this whole task: the check is ABSOLUTE.** There is no
`_lane_seating_is_forced` helper, no geometry exemption, and nothing consumed
from `freeform._side_lane_caps` or `slots.attachable_columns` — an earlier draft
of this plan had all three and they are deleted by the ruling. A mixed input
lane is an ERROR however it came to be.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_validate.py`:

```python
def test_mixed_item_input_lane_is_convicted() -> None:
    """One input belt carries one item.

    Measured on the reporting URL: belt run 7 carried frame-material,
    optical-grating-crystal AND super-magnetic-ring into the same two
    advanced-mining-machine assemblers, and run 16 carried two more.  A native
    DSP merge is first-come, not proportional, so whichever source runs ahead
    fills the belt and the others back up.  `flow.belt_capacity` already sums
    across items and was satisfied; nothing asked whether they could interleave.
    """
    placement = _two_items_on_one_input_lane()
    report = validate.validate(placement, _two_ingredient_spec(), expect_power=False)
    findings = [f for f in report.errors if f.check == "flow.lane_single_item"]
    assert findings, [f.check for f in report.errors]
    assert findings[0].detail["items"] == ["copper-ingot", "iron-ingot"]


def test_same_item_shared_lane_is_not_a_mixed_lane() -> None:
    """Two consumers of ONE item off one lane is belt sharing, and it stays.

    `_merge_lanes` / `_merge_frontier` fold a producer's destinations onto one
    lane; that sharing is load-bearing for feasibility on 12 of 36 corpus cells.
    This check counts DISTINCT ITEMS on a run, never taps.
    """
    placement = _one_item_two_consumers_on_one_lane()
    report = validate.validate(placement, _one_ingredient_two_groups_spec(), expect_power=False)
    assert not [f for f in report.errors if f.check == "flow.lane_single_item"]


def test_forced_mixed_lane_is_still_convicted() -> None:
    """"The machine's faces left no alternative" is not a defence (spec §9 R1).

    A Matrix Lab offers three insert columns per face, and before Task 3 that
    made `freeform._seat_inputs` seat `universe-matrix`'s six ingredients as
    three items per lane above and three below (freeform.py:2208-2223).  The
    user's ruling is that such a lane starves in game exactly like a chosen one
    -- whichever item the machines are not short of fills the belt -- so the
    check has NO exemption.  Task 3 is what keeps `universe-matrix` building:
    it frees a sixth input row so the lab seats one item per lane on the merits.
    """
    placement = _matrix_lab_three_items_on_one_lane_placement()
    report = validate.validate(placement, _matrix_lab_six_ingredient_spec(), expect_power=False)
    findings = [f for f in report.errors if f.check == "flow.lane_single_item"]
    assert findings, [f.check for f in report.errors]
    assert len(findings[0].detail["items"]) == 3
```

- [ ] **Step 2: Run them and see two fail**

```bash
uv run pytest tests/layout/test_validate.py -k lane_single_item -x -q
uv run pytest tests/layout/test_validate.py -k "mixed_item_input_lane or same_item_shared_lane or forced_mixed_lane" -q
```

Expected: `test_mixed_item_input_lane_is_convicted` and
`test_forced_mixed_lane_is_still_convicted` FAIL (no such check yet);
`test_same_item_shared_lane_is_not_a_mixed_lane` passes vacuously and must
still pass at the end.

- [ ] **Step 3: Add the check**

Insert in `src/flab2bp/layout/validate.py` beside the other flow checks:

```python
@check("flow.lane_single_item", needs_spec=True, needs_groups=True)
def _lane_single_item(ctx: Context) -> Iterable[Finding]:
    """One input belt carries one item.  No exemption (spec §9 R1).

    A run whose sorters draw two or more DISTINCT items into machines is an
    ERROR, full stop.  There is deliberately no forced-geometry exemption: a
    lane whose items must interleave in the recipe's exact proportion to avoid
    starving each other is not a build we emit, and "the machine's own faces
    left no alternative" describes a seating we must not ship rather than one we
    must tolerate.  Where a machine family really cannot be seated
    one-item-per-lane the answer is a planner change -- Task 3 moved the flanked
    output's drain row past sorter reach so a Matrix Lab seats six ingredients
    as six lanes -- or an honest refusal, never a permitted mixed belt.

    Detail carries ``run``, sorted ``items`` and the machines, so the finding
    names what to un-mix.

    This counts distinct ITEMS, never taps: several consumers of ONE item off
    one lane is belt sharing, which is a different mechanism and stays.
    """
```

Body: build `items_by_run: dict[int, set[str]]` from every sorter whose
`input_obj` is a belt and whose `output_obj` is a machine, using
`_sorter_items(ctx)`; for each run with two or more distinct items, yield
`Severity.ERROR`. No exemption branch exists.

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/layout/test_validate.py -q
```

Expected: exit 0.

---

## Task 5: Stop the emitter producing any mixed input lane

**Files:**
- Modify: `tests/layout/test_strip_variants.py`
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py`

**Interfaces:**
- Consumes: `strip_variants._logical_strip_plans(spec)`, `strip_variants.generate_strip_families(spec)`, `freeform._seat_inputs(items, n_sinks, above_cap, below_cap, max_per_lane, columns, *, flank_outputs=False, lane_fits=None, seating_fits=None)`.
- Produces: `prefer_shared_proliferation` and `prefer_shared` are gone from all three call sites; `lane_fits` is passed unconditionally; `_seat_inputs` seats one item per lane or fails to seat.

**Spec §9 R1 applies: the emitter must agree with the validator, not race it.**
Removing only the *preference* would leave the ladder still escalating to a
mixed lane whenever one-per-lane does not fit — and Task 4 now convicts that
lane, so the cell would come back INVALID after paying a full routing pass
instead of REFUSED. The ladder therefore collapses to one item per lane. This
is the same discipline Task 2 applies to the coater seat chooser.

**Task 3 must be complete before this task runs**, or `universe-matrix` loses
its sixth input row and refuses.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_strip_variants.py`:

```python
def test_proliferated_group_does_not_mix_ingredients_onto_one_lane() -> None:
    """Fewer coaters is not worth a belt whose items must interleave exactly.

    `prefer_shared_proliferation` reversed `_seat_inputs`' mixing ladder for any
    proliferated group with three or more ingredients, so it mixed AS HARD AS
    POSSIBLE and gated only on the rate sum (`input_lane_fits`).  On the
    reporting URL that put three items on one lane into the two
    advanced-mining-machine assemblers, and two on another.  One item per lane
    is now the rule; mixing survives only where the machine's faces force it.
    """
    (plan,) = [p for p in _logical_strip_plans(_five_ingredient_proliferated_spec())]
    lanes = (*plan.in_above, *plan.in_below)
    assert all(len(lane) == 1 for lane in lanes), lanes
```

- [ ] **Step 2: Run it and see it fail**

```bash
uv run pytest tests/layout/test_strip_variants.py -k does_not_mix_ingredients -x -q
```

Expected: FAIL — lanes hold three and two items.

- [ ] **Step 3: Delete the preference**

- `src/flab2bp/layout/strip_variants.py:1255` — drop the
  `prefer_shared_proliferation: bool = False` parameter from
  `_logical_strip_plans`.
- `strip_variants.py:1358-1360` — delete `prefer_shared_inputs`.
- `strip_variants.py:1449-1450` and `1466-1467` — drop `prefer_shared=`, and
  pass `lane_fits=input_lane_fits` unconditionally (a forced mixed lane still
  has to fit the belt).
- `strip_variants.py:1985,1996` — drop the parameter from
  `generate_strip_families` and its forwarding.
- `src/flab2bp/layout/freeform.py:2179` — drop `prefer_shared` from
  `_seat_inputs`; at `freeform.py:2243-2245` reduce the ladder to a single
  rung, `mix_sizes = (1,)`, so a seating that cannot fit one item per lane
  simply does not seat and the caller refuses. Rewrite the docstring paragraph
  at `freeform.py:2186-2189` and the `universe-matrix` note at
  `freeform.py:2208-2223`: the lab now fits six single-item lanes because
  Task 3 freed the drain row, and a mixed lane is no longer a fallback but an
  impossibility — cite spec §9 R1 and `flow.lane_single_item`.
- Add a second failing test in the same task pinning the refusal, so the new
  behaviour is asserted rather than assumed:

```python
def test_seat_inputs_refuses_rather_than_mixing_when_one_per_lane_will_not_fit() -> None:
    """No lane is better than a mixed lane (spec §9 R1).

    The ladder used to escalate to two, then three items per lane.  It no
    longer does: a spec whose ingredients outnumber the reachable rows fails to
    seat, the strategy refuses, and the audit says REFUSED -- which is the
    truth -- instead of emitting a belt `flow.lane_single_item` convicts.
    """
    seating = freeform._seat_inputs(
        items=("a", "b", "c"),
        n_sinks=1,
        above_cap=1,
        below_cap=1,
        max_per_lane=3,
        columns=3,
    )
    assert seating is None
```

Adjust the argument names and the `None`/empty contract to whatever
`_seat_inputs` actually returns on failure today — read the symbol before
writing the test, and keep the existing contract rather than inventing one.

Then update every caller and test that passes the flag:

```bash
uv run python - <<'PY'
import subprocess
print(subprocess.run(["grep","-rn","prefer_shared","src","tests"],capture_output=True,text=True).stdout)
PY
```

Expected after the change: no hits.

- [ ] **Step 4: Re-run the layout suites**

```bash
uv run pytest tests/layout -q
```

Expected: exit 0. `universe-matrix`-shaped seatings do **not** mix any more:
Task 3 freed the sixth input row, so the lab seats six single-item lanes. Any
layout test that pinned a mixed seating is now asserting behaviour the ruling
forbids — update it to the single-item seating and say so in the diff, do not
delete it and do not add an exemption.

Two tests are known to assert mixing directly and must be dealt with in this
task, in the open, with the reason in the commit message:

- `tests/layout/test_freeform.py:11147`
  `test_a_five_ingredient_recipe_still_mixes_and_validates` asserts
  `max(len(lane) ...) > 1`. Under §9 R1 that is the forbidden outcome. Establish
  first whether the five-ingredient spec now seats one-per-lane (caps `(3,3)`
  give five single lanes plus an output row on most machine families) or
  refuses, then rewrite the test to assert whichever it is **and rename it** so
  the name stops advertising the old rule.
- `tests/layout/test_freeform.py:11162`
  `test_every_sorter_on_a_mixed_lane_is_filtered` loses its subject if no mixed
  lane exists. Do not delete it: repurpose it to assert that every sorter on an
  input lane is filtered, which is the property that actually mattered, and note
  the change.

Neither is licence to weaken an assertion to make a suite pass. If a test
cannot be rewritten honestly, report it as a blocker rather than deleting it.

---

## Task 6: Enumerate self-loop recipes and carry the seed on the spec

**Files:**
- Modify: `tests/lab/test_data.py`
- Modify: `tests/test_spec.py`
- Modify: `src/flab2bp/spec.py`

**Interfaces:**
- Consumes: `flab2bp.lab.data.load_vendored`, pydantic `Field`, `model_validator`.
- Produces: `spec.SelfLoopSeed` and `BuildSpec.self_loop_seeds: tuple[SelfLoopSeed, ...] = ()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/lab/test_data.py`:

```python
def test_only_two_vendored_recipes_consume_what_they_produce() -> None:
    """The self-loop set is exactly two recipes, and a dataset bump must say so.

    Both are net-POSITIVE oil-refinery recipes, which is what makes a one-off
    prime sufficient: after the first craft the loop sustains itself.
    """
    ds = load_vendored()
    loops = {
        r.id: sorted(set(r.inputs) & set(r.outputs))
        for r in ds.recipes
        if set(r.inputs) & set(r.outputs)
    }
    assert loops == {
        "x-ray-cracking": ["hydrogen"],
        "reforming-refine": ["refined-oil"],
    }
    assert ds.recipe("x-ray-cracking").outputs["hydrogen"] == Fraction(3)
    assert ds.recipe("x-ray-cracking").inputs["hydrogen"] == Fraction(2)
    assert ds.recipe("reforming-refine").outputs["refined-oil"] == Fraction(3)
    assert ds.recipe("reforming-refine").inputs["refined-oil"] == Fraction(2)
```

Add to `tests/test_spec.py`:

```python
def test_self_loop_seed_arithmetic_cannot_lie() -> None:
    with pytest.raises(ValidationError):
        SelfLoopSeed(
            item_id="hydrogen",
            recipe_id="x-ray-cracking",
            machine_item_id="oil-refinery",
            machines=4,
            consumed_per_craft=Fraction(2),
            produced_per_craft=Fraction(3),
            net_per_craft=Fraction(2),  # wrong: 3 - 2 = 1
            seed_items=8,
        )
    with pytest.raises(ValidationError):
        SelfLoopSeed(
            item_id="hydrogen",
            recipe_id="x-ray-cracking",
            machine_item_id="oil-refinery",
            machines=4,
            consumed_per_craft=Fraction(2),
            produced_per_craft=Fraction(3),
            net_per_craft=Fraction(1),
            seed_items=4,  # wrong: ceil(4 * 2) = 8
        )
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/lab/test_data.py -k consume_what_they_produce -x -q
uv run pytest tests/test_spec.py -k self_loop_seed_arithmetic -x -q
```

Expected: the first passes if the dataset is as measured (it is — keep it as
the guard); the second FAILS with `ImportError`/`NameError` because
`SelfLoopSeed` does not exist.

- [ ] **Step 3: Add the model**

In `src/flab2bp/spec.py`, after `CoproductBufferProof` (line 119):

```python
class SelfLoopSeed(_Frozen):
    """A recipe that consumes an item it also produces, and its one-off prime.

    DSP machines paste EMPTY and a blueprint carries no inventory --
    ``dsp.records.BlueprintBuilding`` has no inventory field -- so a loop whose
    only source is itself holds zero items at t=0 and the block never starts.
    The rates layer is right to net the loop away (``rates/solve.py:1306-1329``)
    and the strip planner is right to build the recirculating lane; what neither
    can express is that the lane must be filled once by hand.

    ``seed_items`` is one full input batch per machine, so every machine in the
    group can start its first craft at once.  It is sufficient because
    ``net_per_craft`` is positive: the loop gains items from then on.
    """

    item_id: str
    recipe_id: str
    machine_item_id: str
    machines: int = Field(gt=0)
    consumed_per_craft: Fraction = Field(gt=0)
    produced_per_craft: Fraction = Field(gt=0)
    net_per_craft: Fraction = Field(gt=0)
    seed_items: int = Field(gt=0)

    @model_validator(mode="after")
    def _arithmetic_holds(self) -> SelfLoopSeed:
        if self.net_per_craft != self.produced_per_craft - self.consumed_per_craft:
            raise ValueError(
                f"{self.recipe_id}: net_per_craft {self.net_per_craft} is not "
                f"{self.produced_per_craft} - {self.consumed_per_craft}"
            )
        need = self.machines * self.consumed_per_craft
        exact = -((-need.numerator) // need.denominator)
        if self.seed_items != exact:
            raise ValueError(
                f"{self.recipe_id}: seed_items {self.seed_items} is not the "
                f"{exact} whole items {self.machines} machine(s) need to start"
            )
        return self
```

and on `BuildSpec`, after `coproduct_buffer_proofs` (line 199):

```python
    #: Items a group both consumes and produces.  Steady-state correct and dead
    #: on paste until primed; see :class:`SelfLoopSeed`.
    self_loop_seeds: tuple[SelfLoopSeed, ...] = ()
```

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/test_spec.py tests/lab/test_data.py -q
```

Expected: exit 0.

---

## Task 7: Derive the seed in the rates layer

**Files:**
- Modify: `tests/rates/test_candidates.py`
- Modify: `src/flab2bp/rates/candidates.py`
- Modify: `src/flab2bp/layout/hierarchy/partition.py`

**Interfaces:**
- Consumes: `rates.candidates._to_build_spec(data, request, solution, label)`, `Dataset.recipe`, `RateSolution.groups`.
- Produces: `rates.candidates._self_loop_seeds(data: Dataset, solution: RateSolution) -> tuple[SelfLoopSeed, ...]`, wired at `candidates.py:216`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/rates/test_candidates.py`:

```python
AMM_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi"
    "WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK"
    "loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"
)


def test_self_loop_seed_is_derived_for_x_ray_cracking(data: Dataset) -> None:
    """The reported URL's hydrogen loop is declared, exactly and in whole items.

    Measured: the output-products candidate runs four oil refineries on
    x-ray-cracking, consuming 149/90 hydrogen/s and producing 149/60, with
    149/180 leaving as surplus.  No hydrogen is an external input, so the loop
    starts empty and the block deadlocks until someone drops eight in.
    """
    specs = build_candidates(data, parse_url(AMM_URL))
    (spec,) = [s for s in specs.candidates if s.label == "output-products"]
    (seed,) = spec.self_loop_seeds
    assert seed.item_id == "hydrogen"
    assert seed.recipe_id == "x-ray-cracking"
    assert seed.machine_item_id == "oil-refinery"
    assert seed.machines == 4
    assert seed.consumed_per_craft == Fraction(2)
    assert seed.produced_per_craft == Fraction(3)
    assert seed.net_per_craft == Fraction(1)
    assert seed.seed_items == 8
    assert "hydrogen" not in spec.external_inputs
    assert spec.surplus_outputs["hydrogen"] == Fraction(149, 180)


def test_self_loop_seed_absent_when_net_is_not_positive() -> None:
    """A loop that loses items is an external input, not a prime.

    ``rates/solve.py:1306-1318`` already turns the shortfall into an external
    input; declaring a seed there would promise a self-sustaining loop that is
    not one.
    """
    solution = _solution_with_group(
        recipe_id="lossy-loop",
        inputs_per_craft={"x": Fraction(3)},
        outputs_per_craft={"x": Fraction(2), "y": Fraction(1)},
    )
    assert _self_loop_seeds(_dataset_with_lossy_loop(), solution) == ()
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/rates/test_candidates.py -k self_loop_seed -x -q
```

Expected: FAIL — `_self_loop_seeds` does not exist.

- [ ] **Step 3: Implement**

In `src/flab2bp/rates/candidates.py`, after `_coproduct_buffer_proofs`
(line 149):

```python
def _self_loop_seeds(data: Dataset, solution: RateSolution) -> tuple[SelfLoopSeed, ...]:
    """Every group whose recipe consumes an item it also produces.

    Stated over ``inputs & outputs`` rather than over a recipe id, so the two
    recipes the vendored dataset has today (``x-ray-cracking`` for hydrogen and
    ``reforming-refine`` for refined oil) and any third one a dataset bump adds
    are covered by the same rule.  A non-positive net is deliberately skipped:
    the shortfall arithmetic in :mod:`flab2bp.rates.solve` already makes it an
    external input, which is the right answer for a loop that loses items.
    """
    seeds: list[SelfLoopSeed] = []
    for group in solution.groups:
        recipe = data.recipe(group.recipe_id)
        for item_id in sorted(set(recipe.inputs) & set(recipe.outputs)):
            consumed = recipe.inputs[item_id]
            produced = recipe.outputs[item_id]
            if produced <= consumed:
                continue
            need = group.machines * consumed
            seeds.append(
                SelfLoopSeed(
                    item_id=item_id,
                    recipe_id=group.recipe_id,
                    machine_item_id=group.machine_item_id,
                    machines=group.machines,
                    consumed_per_craft=consumed,
                    produced_per_craft=produced,
                    net_per_craft=produced - consumed,
                    seed_items=-((-need.numerator) // need.denominator),
                )
            )
    return tuple(seeds)
```

Wire it at `candidates.py:216`, beside `coproduct_buffer_proofs`:

```python
        self_loop_seeds=_self_loop_seeds(data, solution),
```

In `src/flab2bp/layout/hierarchy/partition.py`, propagate it exactly as
`coproduct_buffer_proofs` is propagated at lines 349-351 and 419, filtered to
the recipe ids the sub-spec keeps.

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/rates tests/layout/hierarchy -q
```

Expected: exit 0.

---

## Task 8: Mark, describe and report the prime

**Files:**
- Modify: `tests/layout/test_markers.py`
- Modify: `tests/test_cli.py`
- Modify: `src/flab2bp/layout/markers.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/cli.py`
- Modify: `src/flab2bp/web/payload.py`

**Interfaces:**
- Consumes: `markers.input_belt_heads(placement)`, `catalog.belt_marker(dsp_item_id)`, `catalog.get_item_id(item)`, `PlacedBuilding.carries_item`.
- Produces:
  - `markers.self_loop_prime_heads(placement: Placement, spec: BuildSpec) -> dict[str, int]`
  - `markers.mark_external_belts(placement, spec)` additionally marks those heads
  - `pipeline._prime_note(spec: BuildSpec, placement: Placement) -> str`
  - `cli` prints `prime once (self-loop): …`
  - `web/payload` gains `"self_loop_seeds"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_markers.py`:

```python
def test_self_loop_lane_head_is_marked() -> None:
    """The tile the player drops the seed on carries the item's icon.

    `mark_external_belts` marked only heads whose item is in
    `spec.external_inputs`, and a self-loop item never is -- so the reporting
    URL's 107-tile hydrogen lane began at an unlabelled belt at (3,21) that
    looked exactly like a forgotten input.
    """
    placement = _self_loop_placement()  # hydrogen loop, head at (3, 21)
    spec = _self_loop_spec()
    heads = markers.self_loop_prime_heads(placement, spec)
    assert set(heads) == {"hydrogen"}
    marked = markers.mark_external_belts(placement, spec)
    assert marked.buildings[heads["hydrogen"]].parameters == catalog.belt_marker(
        catalog.item_id("hydrogen")
    )
```

Add to `tests/test_cli.py`:

```python
def test_cli_reports_the_self_loop_prime(capsys) -> None:
    build = _build_with_self_loop_seed()
    cli._report(build, out=sys.stdout)
    out = capsys.readouterr().out
    assert "prime once (self-loop): hydrogen 8 items" in out
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/layout/test_markers.py -k self_loop_lane_head -x -q
uv run pytest tests/test_cli.py -k reports_the_self_loop_prime -x -q
```

Expected: both FAIL (`AttributeError` on `self_loop_prime_heads`, missing line).

- [ ] **Step 3: Implement**

`src/flab2bp/layout/markers.py`:

```python
def self_loop_prime_heads(placement: Placement, spec: BuildSpec) -> dict[str, int]:
    """Loop-lane head belt index per self-loop item, for the prime icon.

    The loop lane is the run that both RECEIVES the item from a group's output
    sorter and DELIVERS it to that same group's input sorters.  Its head is
    where a hand or a temporary belt puts the seed in, so that is the tile that
    gets the icon -- and unlike an external input it is not in
    ``spec.external_inputs``, which is exactly why nothing marked it before.
    """
```

Extend `mark_external_belts` (`markers.py:96-140`) to mark those heads too, and
count them in `stats["self_loop_prime_markers"]`.

`src/flab2bp/pipeline.py`, beside `_generated_title` (line 440):

```python
def _prime_note(spec: BuildSpec, placement: Placement) -> str:
    """`; PRIME ONCE: 8 hydrogen onto the marked belt at (3,21)`, or ``''``."""
```

and append it to the `description=` at `pipeline.py:1172-1175`.

`src/flab2bp/cli.py`, after the `inputs to belt in:` block (lines 42-50):

```python
    for seed in build.spec.self_loop_seeds:
        head = prime_heads.get(seed.item_id)
        where = f" at ({head.x},{head.y})" if head is not None else ""
        print(
            f"prime once (self-loop): {seed.item_id} {seed.seed_items} items"
            f" onto the marked belt{where}"
            f" -- {seed.recipe_id} consumes what it produces, so the block will"
            f" not start until the loop has items in it",
            file=out,
        )
```

`src/flab2bp/web/payload.py`, beside `"external_inputs"` at lines 124 and 212:

```python
        "self_loop_seeds": {
            s.item_id: {
                "seed_items": s.seed_items,
                "recipe": s.recipe_id,
                "machines": s.machines,
            }
            for s in spec.self_loop_seeds
        },
```

- [ ] **Step 4: Re-run**

```bash
uv run pytest tests/layout/test_markers.py tests/test_cli.py tests/web -q
```

Expected: exit 0.

---

## Task 9: Make the validator the arbiter of the prime

**Files:**
- Modify: `tests/layout/test_validate.py`
- Modify: `src/flab2bp/layout/validate.py`

**Interfaces:**
- Consumes: `validate.Context`, `validate._reachable_from_outside(ctx, z)`, `validate._internal_seeds`, `validate.Kind`, `BuildSpec.self_loop_seeds`.
- Produces: `@check("flow.self_loop_primed", needs_spec=True, needs_groups=True)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_validate.py`:

```python
def test_self_loop_lane_that_cannot_be_reached_is_an_error() -> None:
    """You cannot prime what no belt and no hand can reach.

    An unreachable loop lane is the same class of defect as
    `flow.external_entry_reachable`'s walled-in input: nothing about the
    blueprint looks wrong, and it simply never starts.
    """
    placement = _self_loop_placement(walled_in=True)
    report = validate.validate(placement, _self_loop_spec(), expect_power=False)
    assert [f for f in report.errors if f.check == "flow.self_loop_primed"]


def test_self_loop_lane_that_can_be_reached_is_a_warning_naming_the_seed() -> None:
    placement = _self_loop_placement(walled_in=False)
    report = validate.validate(placement, _self_loop_spec(), expect_power=False)
    assert not [f for f in report.errors if f.check == "flow.self_loop_primed"]
    (finding,) = [f for f in report.warnings if f.check == "flow.self_loop_primed"]
    assert finding.detail["item"] == "hydrogen"
    assert finding.detail["seed_items"] == 8


def test_self_loop_lane_that_does_not_close_is_an_error() -> None:
    """A declared loop whose output never reaches its own input is not a loop."""
    placement = _self_loop_placement(closed=False)
    report = validate.validate(placement, _self_loop_spec(), expect_power=False)
    assert [f for f in report.errors if f.check == "flow.self_loop_primed"]
```

- [ ] **Step 2: Run and see them fail**

```bash
uv run pytest tests/layout/test_validate.py -k self_loop -x -q
```

Expected: all three FAIL — no such check.

- [ ] **Step 3: Add the check**

In `src/flab2bp/layout/validate.py`, beside `_coproduct_buffer`
(line 4632):

```python
@check("flow.self_loop_primed", needs_spec=True, needs_groups=True)
def _self_loop_primed(ctx: Context) -> Iterable[Finding]:
    """A loop that feeds itself must close, be reachable, and be priced.

    ``flow.conservation`` answers the steady-state question and answers it
    correctly: a self-loop item nets to zero and the produced item does reach
    the taps.  Neither of its clauses has any notion of an INITIAL FILL, and
    ``flow.coproduct_buffer`` is a certificate verifier that yields nothing when
    no certificate exists -- so a block whose only hydrogen source is itself
    passed every check and deadlocked on paste.

    ERROR when the loop lane does not physically close (the group's own output
    sorter does not reach its own input pickups), and ERROR when every tile of
    that lane is walled in, which is the same defect
    ``flow.external_entry_reachable`` catches for an ordinary input.  WARNING
    otherwise, naming item, ``seed_items`` and the marked tile, so the
    obligation reaches the report, the CLI and the web payload rather than
    living only in the blueprint description.
    """
```

- [ ] **Step 4: Re-run the whole suite**

```bash
uv run pytest -q
```

Expected: exit 0. The 120 s `pytest-timeout` backstop hard-kills a run, so if a
slow layout test is near it, run `tests/layout` on its own.

---

## Task 10: Gate — the reported URL, both self-loop recipes, and a paired corpus round

**Files:**
- Create: `docs/superpowers/evidence/2026-09-06-selfloop/gate/` (logs and JSONL)
- Modify: `docs/superpowers/evidence/2026-09-06-selfloop/README.md` (append the result)

**Interfaces:**
- Consumes: `uv run flab2bp`, `scripts/audit.py`, `scripts/audit_compare.py`, `docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_decode.py`, `probe_coater.py`.
- Produces: a PASS/FAIL verdict with area geomean, CLEAN counts and routing seconds per arm.

**ONE BUILD AT A TIME. Record the `cpu_pressure` number beside every timing —
never `uptime`, never load average.**

- [ ] **Step 1: The reported URL builds and no longer emits a mixed lane or a coater merge**

```bash
E=docs/superpowers/evidence/2026-09-06-selfloop/gate
mkdir -p "$E"
cpu_pressure | tee "$E/cpu-pressure-amm.txt"
/usr/bin/time -v uv run flab2bp "$AMM_URL" --budget 30 -v \
  -o "$E/bp-amm-after.txt" 2>&1 | tee "$E/build-amm-after.log"
cpu_pressure | tee -a "$E/cpu-pressure-amm.txt"
uv run python docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_decode.py \
  "$E/bp-amm-after.txt" > "$E/decode-amm-after.txt"
uv run python docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_coater.py \
  "$E/bp-amm-after.txt" > "$E/coater-amm-after.txt"
```

PASS requires all four:

1. `build-amm-after.log` reports `errors 0` for the winning cell.
2. `decode-amm-after.txt` contains **no** `SHARED-INPUT-RUN` line.
3. `coater-amm-after.txt` contains **no** `MERGE POINT` line on a tile the
   coater body covers, and each coater's addon area 1 resolves to belts of
   **exactly one run** within `ADDON_AREA_RADIUS`. (Amended per spec §9 R6:
   "exactly one belt" was the original wording and is unsatisfiable — every
   coater `_place_coaters` emits has its own approach and supply belts inside
   that radius, at 0.942 and 0.314 world units. One run is the property that
   actually removes the ambiguity.)
4. `build-amm-after.log` contains
   `prime once (self-loop): hydrogen 8 items`.

- [ ] **Step 1a: `universe-matrix` builds CLEAN with six single-item lanes**

This is the PASS condition spec §9 R2 exists for, and it is checked by decoding
the blueprint, not by reading the planner's intentions.

```bash
cpu_pressure | tee "$E/cpu-pressure-um.txt"
/usr/bin/time -v uv run flab2bp "$UNIVERSE_MATRIX_URL" --budget 30 -v \
  -o "$E/bp-um-after.txt" 2>&1 | tee "$E/build-um-after.log"
cpu_pressure | tee -a "$E/cpu-pressure-um.txt"
uv run python docs/superpowers/evidence/2026-09-06-selfloop/probes/probe_decode.py \
  "$E/bp-um-after.txt" > "$E/decode-um-after.txt"
```

PASS requires all three:

1. `build-um-after.log` reports `errors 0` for the winning cell — in
   particular **no `flow.lane_single_item` finding at any severity**.
2. `decode-um-after.txt`'s `== machines and their sorters ==` section shows,
   for each Matrix Lab, **six distinct `from run R: [...]` lines each holding
   exactly one item**, and **no `<<< SHARED-INPUT-RUN` flag**. Quote the six
   lines verbatim in the verdict — a claim without them is not a check.
3. The build is CLEAN, not REFUSED and not INVALID.

If `universe-matrix` refuses or is convicted, **that is a FAIL and it is
reported as a FAIL**: spec §9 R1 is absolute, so the answer is not to
re-introduce an exemption. Say plainly that the drain-row move did not free the
row, name what `_side_lane_caps` actually returned, and leave the decision with
the user.

- [ ] **Step 2: The second self-loop recipe**

`reforming-refine` is not activated by any corpus URL (`tests/rates/test_solve.py:596`),
so drive it from the existing pinned fixture, with hydrogen NOT externally
supplied so the loop is the only source:

```bash
uv run pytest tests/rates/test_candidates.py -k reforming_refine_self_loop_seeds -q
```

with the test from spec §6 T12 added in Task 7. PASS requires
`seed_items == machines * 2` and `net_per_craft == 1` for `refined-oil`.

- [ ] **Step 3: Baseline the corpus on master**

From a clean master checkout of this worktree's parent commit:

```bash
cpu_pressure | tee "$E/cpu-pressure-baseline.txt"
/usr/bin/time -v uv run python scripts/audit.py --tier stress --budget 30 \
  --strategy both --json "$E/audit-baseline.jsonl" 2>&1 | tee "$E/audit-baseline.log"
cpu_pressure | tee -a "$E/cpu-pressure-baseline.txt"
```

- [ ] **Step 4: The candidate round**

```bash
cpu_pressure | tee "$E/cpu-pressure-candidate.txt"
/usr/bin/time -v uv run python scripts/audit.py --tier stress --budget 30 \
  --strategy both --json "$E/audit-candidate.jsonl" 2>&1 | tee "$E/audit-candidate.log"
cpu_pressure | tee -a "$E/cpu-pressure-candidate.txt"
```

- [ ] **Step 5: Compare, and report all three axes**

```bash
uv run python scripts/audit_compare.py "$E/audit-baseline.jsonl" "$E/audit-candidate.jsonl" \
  --expect-cells 72 | tee "$E/audit-compare.txt"
```

Then, from the two JSONL files, write `"$E/verdict.md"` reporting **per arm**
(`freeform`, `sequence-pair`):

| axis | why it is here |
|---|---|
| geometric mean area ratio over cells clean in BOTH files | the density cost of one item per lane |
| CLEAN / REFUSED / INVALID counts, and the named cells that moved either way | **a cell that starts building because its lanes stopped being coupled is a WIN for the rule, not a cost** |
| routing seconds and rip-up rounds per cell where the JSONL exposes them, p50 and p95 | a mixed lane couples strips that would otherwise be independent, so the rule may pay for itself here |
| the count of specs whose strip count grew | the direct structural consequence of un-mixing |
| the count of cells that gained a strip ROW from the Task 3 drain-row move, and their area delta | spec §9 R2 costs one strip row on every `flank_outputs` spec that trips the condition — measured, `universe-matrix#37` grows from `box_height` 8 to 12, of which **one** row is the drain move and **three** are the un-mixing R1 asked for. **Report both numbers per arm as measured. Do not argue them away, do not net them together, and do not report +4 as +1.** |

**The ruling stands whatever the area number says.** Report it plainly:

* If coverage or route time improves, say so — the rule paid for itself.
* If area costs with no coverage gain, quantify it exactly and leave the number
  in front of the user rather than arguing it away.
* `universe-matrix` is expected to be **CLEAN with six single-item lanes**
  (Step 1a), because Task 3 freed the row — not because it was exempted.
  Spec §8 question 1 is closed by §9 R1; if the cell refuses or is convicted,
  it is a FAIL on the record and the user decides what happens next. Nobody
  reinstates the exemption to make the gate green.

- [ ] **Step 6: Append the verdict to the evidence README**

Add a `## Gate result` section to
`docs/superpowers/evidence/2026-09-06-selfloop/README.md` with the four Step-1
checks, the three Step-1a `universe-matrix` checks (including the six decoded
single-item lane lines), the per-arm table above, the `audit_compare` verdict
line, and the `cpu_pressure` readings beside every timing. Every number is as
measured; nothing is predicted.

---

## Task 11: Commit

- [ ] **Step 1: Run the full suite and the linters**

```bash
uv run pytest -q; echo "pytest exit=$?"
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "fix: one item per input lane, no coater merges, primed self-loops

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```
