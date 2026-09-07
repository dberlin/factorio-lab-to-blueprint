# Spray Coater as a Placed Node — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "a Spray Coater rides exactly one belt run" and "merges land only
upstream of the coater" structural facts about where a coater is allowed to sit,
instead of properties a validator hopes to find, and make the node visible in the
code as a typed record with an in-port, a body and an out-port.

**Architecture:** The coater stays a belt addon on the consumer strip's own input
lane inside the strip's reserved west channel — no new nets, no new packed
objects, no rate-layer change. Two arithmetic changes carry the correctness:
the seat search starts at index `1 + half_span` so the 1x3 body can never cover
the lane head where producer nets merge, and the body's own level plus the
area-1 rival cell become router-banned. A `CoaterNode` record then states the
invariant in the type so no future strategy can reintroduce it.

**Tech Stack:** Python 3.14, pydantic v2 `BuildSpec`, OR-Tools CP-SAT packer,
pytest with a 120 s per-test backstop, `scripts/audit.py` as the gate.

**Spec:** `docs/superpowers/specs/2026-09-07-coater-node-design.md`

## Global Constants

Copied verbatim from the spec; every task's requirements include these.

- Branch: work on `design-coater-node`'s successor branch `coater-node`, cut
  from `master` **after** branch `selfloop` has merged. If `selfloop` has not
  merged when Task 1 starts, cut from `master` anyway — Task 1 is independent of
  it and Task 6 reconciles.
- `_COATER_WEST_CHANNEL = 3` (`src/flab2bp/layout/freeform.py:210`). Do not
  change its value in this plan. Task 7 measures whether it must become 4 and
  that is a user decision, not an implementation one.
- `catalog.SPRAY_COATER_ID = 2313`, oriented footprint `(3, 1)` at yaw 90 and
  `(1, 3)` at yaw 0. Body half-span along the lane axis is
  `(oriented_footprint(SPRAY_COATER_ID, yaw)[0] - 1) // 2`.
- Addon areas: area 0 at `(0, 0, 0)` (the ridden belt), area 1 at
  `(0, -1.25, 1)` (the proliferator drop), radius `rules.ADDON_AREA_RADIUS = 1.0`.
- A coater occupies no grid tile (`catalog.BuildingInfo.occupies_tiles` is
  `not is_belt_addon`). It must ride a belt; it can never be a free-standing
  packed object.
- Never commit anything under `.superpowers/`. Evidence goes under
  `docs/superpowers/evidence/2026-09-07-coater-node/`.
- Run **one** build at a time for measurement. Record `uptime` beside every
  timing. The pytest summary line does not print in this environment — use the
  exit code.
- Standing user rulings: no input lane carries two distinct items; a coater
  rides exactly one belt run; sprayed inputs arrive on a belt, never by direct
  insertion; density may be paid for correctness, even a lot; over-proliferating
  is acceptable if it makes life easier.

---

## File Structure

| File | Responsibility in this plan |
|---|---|
| `src/flab2bp/layout/freeform.py` | `_coater_body_half_span`, `_coater_seats`, `_reserve_staged_coater_belt_ban`, `CoaterNode`, `_place_coaters`, `_PreparedProblem`. All coater geometry lives here already; nothing new is split out. |
| `src/flab2bp/layout/validate.py` | `prolif.sprayed_cargo_reaches_machines` severity split (Task 6). |
| `src/flab2bp/cli.py` | Over-proliferated items named on the report (Task 6). |
| `tests/layout/test_freeform.py` | Every geometry test in this plan. It already has `proliferated_spec()`, `spray_domain_spec()`, `_greedy_pack`, `_height_seed` and `_coater_strip_with_variant`. |
| `tests/layout/test_validate.py` | The severity test (Task 6). |
| `docs/superpowers/evidence/2026-09-07-coater-node/` | Baseline and post-change gate output (Tasks 0 and 7). |

---

### Task 0: Baseline — capture the gate and the seat census before touching anything

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-coater-node/README.md`
- Create: `docs/superpowers/evidence/2026-09-07-coater-node/baseline.jsonl`
- Create: `docs/superpowers/evidence/2026-09-07-coater-node/baseline-audit.txt`
- Create: `docs/superpowers/evidence/2026-09-07-coater-node/seat-census.py`
- Create: `docs/superpowers/evidence/2026-09-07-coater-node/seat-census.txt`

**Interfaces:**
- Produces: `baseline.jsonl` (one JSON record per cell, the input
  `scripts/audit_compare.py` wants in Task 7) and `seat-census.txt` (which seat
  each coater takes today, and whether its body covers the lane head).

- [ ] **Step 1: Record the machine state and run the gate**

`--tier stress` means "stress and every tier below it" (`audit.py:757-758`), so
this is the full 72-cell run. `--strategy both` is the flag; there is no
`--strategies`.

```bash
mkdir -p docs/superpowers/evidence/2026-09-07-coater-node
uptime | tee docs/superpowers/evidence/2026-09-07-coater-node/baseline-audit.txt
python3 scripts/audit.py --tier stress --strategy both --budget 30 \
  --json docs/superpowers/evidence/2026-09-07-coater-node/baseline.jsonl \
  2>&1 | tee -a docs/superpowers/evidence/2026-09-07-coater-node/baseline-audit.txt
echo "exit=$?" | tee -a docs/superpowers/evidence/2026-09-07-coater-node/baseline-audit.txt
uptime | tee -a docs/superpowers/evidence/2026-09-07-coater-node/baseline-audit.txt
```

Expected: the last line reports `N/72 cells`. Record the clean count. The
`audit.py` report says NOT CLEAN on any refusal; that is normal — what matters
is the **count** and **which** cells, because Task 7 compares those, not the
verdict. Delete `baseline.jsonl` before re-running: `--json` **appends**.

- [ ] **Step 2: Write the seat census script**

`docs/superpowers/evidence/2026-09-07-coater-node/seat-census.py`:

```python
"""Which seat index does each Spray Coater take today, and is the head covered?

Read-only.  For every candidate spec of every audit-corpus URL, plan strips,
greedily pack them, prepare the routing problem, and report for each committed
coater the offset of its seat from its lane head and whether its 1x3 body covers
that head.  The head is where producer nets merge, so a body that covers it is
the defect `docs/superpowers/specs/2026-09-07-coater-node-design.md` removes.
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "src")

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import (
    _greedy_pack,
    _height_seed,
    _prepare_routing_problem,
    plan_strips,
)
from flab2bp.rates.candidates import build_candidates

data = load_vendored()
rows = []
for entry in URL_CORPUS:
    for spec in build_candidates(data, parse_url(entry.url)).candidates:
        if not spec.spray_lanes:
            continue
        started = time.time()
        try:
            strips = plan_strips(spec)
            pack = _greedy_pack(strips, _height_seed(strips))
            prepared = _prepare_routing_problem(
                spec, strips, pack, policy=BandPolicy("portable"), power=False
            )
        except Exception as exc:  # noqa: BLE001 -- a refusal is a datum here
            rows.append({"url": entry.url_id, "label": spec.label, "refused": str(exc)[:200]})
            continue
        width = catalog.oriented_footprint(catalog.SPRAY_COATER_ID, 90.0)[0]
        half = (width - 1) // 2
        for port in prepared.coater_supply_ports:
            rows.append(
                {
                    "url": entry.url_id,
                    "label": spec.label,
                    "item": port.item,
                    "seat": [port.host_x, port.host_y],
                    "body_x": [port.host_x - half, port.host_x + half],
                    "seconds": round(time.time() - started, 1),
                }
            )
print(json.dumps(rows, indent=1))
```

- [ ] **Step 3: Run the census**

```bash
uptime
python3 docs/superpowers/evidence/2026-09-07-coater-node/seat-census.py \
  > docs/superpowers/evidence/2026-09-07-coater-node/seat-census.txt
uptime
python3 - <<'PY'
import json
rows = json.load(open("docs/superpowers/evidence/2026-09-07-coater-node/seat-census.txt"))
seated = [r for r in rows if "seat" in r]
print("coaters seated:", len(seated), "specs refused:", len(rows) - len(seated))
PY
```

Expected: a non-zero coater count. The count is the denominator Task 7 uses.

- [ ] **Step 4: Write the evidence README**

`docs/superpowers/evidence/2026-09-07-coater-node/README.md` states, in prose:
what was run, the `uptime` load before and after, the baseline clean-cell count
from Step 1, the seated-coater count from Step 3, and the sentence "Task 7
compares against these two numbers." Leave the post-change section empty with
the heading `## After` so Task 7 fills it.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/evidence/2026-09-07-coater-node
git commit -m "evidence: baseline gate and coater seat census before the node change"
```

---

### Task 1: The body may not cover the lane head

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:18019-18037` (`_coater_seats`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: `freeform._coater_body_half_span(yaw: float) -> int` and a
  `_coater_seats(canvas, port, *, west_channel, yaw=Facing.EAST.value)` whose
  returned seats never place the 1x3 body over `port.tiles[0]`. Tasks 2, 3 and 4
  all call `_coater_body_half_span`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_freeform.py`:

```python
def _lane_canvas(head_x: int, y: int, length: int) -> tuple[freeform._Canvas, freeform._Port]:
    """A straight east-running belt lane and the port at its west end."""
    canvas = freeform._Canvas()
    indices = [
        canvas.add(
            PlacedBuilding(
                item_id=catalog.item_id("conveyor-belt-2"),
                model_index=catalog.building(catalog.item_id("conveyor-belt-2")).model_index,
                x=head_x + k,
                y=y,
                width=1,
                height=1,
                yaw=Facing.EAST.value,
                owner_strip=0,
            )
        )
        for k in range(length)
    ]
    port = freeform._Port(
        indices[0],
        head_x,
        y,
        head_x,
        head_x + length - 1,
        tuple(indices),
        1,
        cargo_domain=CargoDomain.REQUIRES_SPRAY,
    )
    return canvas, port


def test_coater_body_half_span_is_one_along_an_east_west_lane() -> None:
    assert freeform._coater_body_half_span(Facing.EAST.value) == 1
    # At yaw 0 the 1x3 body stands across the lane, not along it, so it reaches
    # no tile east or west of its seat.  `addon_ride_is_straight` is what
    # forbids that pose on an east-running belt, not this function.
    assert freeform._coater_body_half_span(Facing.NORTH.value) == 0


def test_coater_seat_never_covers_the_lane_head() -> None:
    """The head is where producer nets merge; a body over it is the defect.

    Reproduces the reported geometry: coater#768 at (54, 20) with a 3-tile body
    covering 53..55, and belt#0 at (53, 20) -- the lane head -- carrying two
    belt predecessors.  With `west_channel = 3` the head is at 53, so 54 must
    not be offered at all.
    """
    canvas, port = _lane_canvas(53, 20, 5)
    half = freeform._coater_body_half_span(Facing.EAST.value)

    seats = freeform._coater_seats(canvas, port, west_channel=3)

    assert seats, "a 5-tile lane in a 3-wide channel must still offer one seat"
    head_x = canvas.buildings[port.tiles[0]].x
    for seat_x, _seat_y in seats:
        assert seat_x - half > head_x, (
            f"seat {seat_x} puts the body over the head at {head_x}"
        )
    assert seats == ((55, 20),)


def test_coater_seat_stays_upstream_of_the_machine_facing_lane() -> None:
    """The east bound is unchanged: no seat at or past `west_channel`."""
    canvas, port = _lane_canvas(53, 20, 8)

    seats = freeform._coater_seats(canvas, port, west_channel=4)

    assert seats == ((55, 20), (56, 20))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "coater_body_half_span or coater_seat_never or coater_seat_stays" -v; echo "exit=$?"
```

Expected: FAIL. `_coater_body_half_span` does not exist, and
`test_coater_seat_never_covers_the_lane_head` fails with
`seats == ((54, 20), (55, 20))` — seat 54 puts the body over head 53.

- [ ] **Step 3: Implement**

Replace `src/flab2bp/layout/freeform.py:18019-18037` with:

```python
def _coater_body_half_span(yaw: float) -> int:
    """Tiles the Coater's body reaches either side of its seat, along the lane.

    A lane runs east-west, so the body's reach along it is the x half-extent of
    its ORIENTED footprint: 1 at yaw 90, where the 1x3 body lies along the belt,
    and 0 at yaw 0, where it stands across it.  Derived rather than written as
    the constant 1, because ``_coater_keepout_hits`` derives the same box the
    same way (``freeform.py:5226-5233``) and the two must not drift.
    """
    return (catalog.oriented_footprint(catalog.SPRAY_COATER_ID, yaw)[0] - 1) // 2


def _coater_seats(
    canvas: _Canvas,
    port: _Port,
    *,
    west_channel: int,
    yaw: float = Facing.EAST.value,
) -> tuple[tuple[int, int], ...]:
    """Straight seats before the first possible machine pickup, in flow order.

    Sprayed input lanes start ``west_channel`` cells west of the strip.  The
    machine-facing lane begins at index ``west_channel``, so that tile and every
    later one may already feed a machine.  Seating there would let that consumer
    take unsprayed cargo before it reaches the Coater.  That is the EAST bound
    and it is unchanged.

    THE WEST BOUND IS ``1 + half_span``, NOT 1, and that is what makes this a
    node rather than a decoration.  Index 0 is the lane head: the one cell of
    the lane a router path can reach, and therefore the cell every producer net
    into this lane merges at -- ``connect_lanes`` appends one net per producer
    to the same sink port (``freeform.py:16416-16464``) and ``_merge_frontier``
    (``freeform.py:8935``) offers its free neighbours as goals.  A body reaching
    ``half_span`` tiles west of its seat therefore covers the head whenever the
    seat is at index ``half_span`` or less, and a two-predecessor belt under a
    Coater's body is exactly the defect measured on the blueprint the user
    pasted: coater#768 at ``(54, 20, 0)``, body ``53..55``,
    ``belt#0 (53, 20, 0) pred=[817, 1872]``.

    Moving the west bound east by one is the whole of the fix.  The head stays
    where merges belong, west of the body, by arithmetic rather than by check.
    """
    stop = min(len(port.tiles) - 1, west_channel)
    return tuple(
        (canvas.buildings[index].x, canvas.buildings[index].y)
        for index in port.tiles[1 + _coater_body_half_span(yaw) : stop]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "coater_body_half_span or coater_seat_never or coater_seat_stays" -v; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 5: Run the coater suite for regressions**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "coater or spray or prolif" -q; echo "exit=$?"
```

Expected: `exit=0`. If a test asserts a specific seat coordinate that has moved
one tile east, update the expectation and say so in the commit body — that is
the intended change, not a broken test. If a test now reports `_Unseatable`
where it did not, **stop and report**: that is Risk 1 in the spec landing early
and it needs the Task 7 measurement before it is papered over.

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "fix: a Spray Coater's body may never cover its lane head

The head is the one reachable cell of a sprayed lane and so the cell every
producer net merges at. Seating the 1x3 body at channel index 1 put it over
that merge -- measured as belt#0 (53,20,0) pred=[817, 1872] under coater#768.
The seat search now starts at 1 + half_span."
```

---

### Task 2: The body's own level and the area-1 rival are un-routable

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:18100-18138` (`_reserve_staged_coater_belt_ban`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform._coater_body_half_span` from Task 1.
- Produces: after `_place_coaters` returns, `canvas.belt_ban` contains the
  seat's own level for every body tile except the head, and the drop's level for
  the cell mirroring the drop across the seat.

- [ ] **Step 1: Write the failing test**

```python
def test_committed_coater_bans_its_body_level_and_its_area_one_rival() -> None:
    """Nothing may join the run under the body, or claim area 1 beside the drop.

    The body cells are occupied belts, so A* could never STEP onto them; what
    the ban removes is `_merge_frontier` offering one as a merge goal, which is
    the only remaining way a body tile gains a second predecessor.  The rival
    cell is the one the self-loop evidence names: coater#768's area 1 held the
    proliferator drop at (53,20,1) AND a cargo lane at (55,20,1), on opposite
    sides of the seat, with only the yaw convention separating them.
    """
    spec = proliferated_spec()
    strips = plan_strips(spec)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec, strips, pack, policy=BandPolicy("portable"), power=False
    )

    assert prepared.coater_supply_ports
    # `_PreparedProblem.belt_ban` (freeform.py:8703) is the frozen form of
    # `_Canvas.belt_ban`: a tuple of ((x, y), frozenset(levels)) pairs.
    bans = dict(prepared.belt_ban)
    half = freeform._coater_body_half_span(Facing.EAST.value)
    for port in prepared.coater_supply_ports:
        for dx in range(-half, half + 1):
            cell = (port.host_x + dx, port.host_y)
            if cell == (port.x, port.y):
                continue  # the drop is a legitimate destination
            assert port.host_z in bans.get(cell, frozenset()), (
                f"body cell {cell} is routable at level {port.host_z}"
            )
        rival = (2 * port.host_x - port.x, 2 * port.host_y - port.y)
        assert port.z in bans.get(rival, frozenset()), (
            f"area-1 rival {rival} is routable at level {port.z}"
        )
```

`_place_coaters`'s tail pops the ban on each committed *drop* cell
(`freeform.py:18768-18769`) — that is why the drop is skipped above and why the
rival, which is a different cell, survives.

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 -m pytest tests/layout/test_freeform.py::test_committed_coater_bans_its_body_level_and_its_area_one_rival -v; echo "exit=$?"
```

Expected: FAIL — `body cell (…) is routable at level 0`.

- [ ] **Step 3: Implement**

In `_reserve_staged_coater_belt_ban` (`freeform.py:18100`), immediately after
`drop = (staged.port.x, staged.port.y)` and before the existing
`need = colliders.belt_crossing_height(...)` line, insert:

```python
    # THE BODY'S OWN LEVEL, AND THE AREA-1 RIVAL.
    #
    # The loop below prices levels ABOVE the body, where a crossing belt would
    # clip the addon.  These two bans are about the body's own plane instead,
    # and they are about GOALS rather than cells: every body tile is an occupied
    # lane belt, so no path can step onto one, but `_merge_frontier` may still
    # offer it as a merge point -- which is the one remaining way a body tile
    # gains a second predecessor after `_coater_seats` stopped covering the head.
    #
    # The rival is the cell mirroring the drop across the seat.  The self-loop
    # evidence measured coater#768's area 1 resolving between the proliferator
    # drop at (53,20,1) and a cargo lane at (55,20,1) on the yaw convention
    # alone; denying the mirror makes the resolution unambiguous by geometry.
    body_half = _coater_body_half_span(staged.port.yaw)
    for dx in range(-body_half, body_half + 1):
        body_cell = (cx + dx, cy)
        if body_cell == drop:
            continue
        canvas.belt_ban.setdefault(body_cell, set()).add(staged.port.host_z)
    rival = (2 * cx - staged.port.x, 2 * cy - staged.port.y)
    canvas.belt_ban.setdefault(rival, set()).add(staged.port.z)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python3 -m pytest tests/layout/test_freeform.py::test_committed_coater_bans_its_body_level_and_its_area_one_rival -v; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 5: Check the ban is not so wide the router starves**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "coater or spray or prolif or route" -q; echo "exit=$?"
python3 -m pytest tests/layout/test_validate.py -q; echo "exit=$?"
```

Expected: `exit=0` for both. `_place_coaters`'s tail already pops the ban on
each committed drop (`freeform.py:18768-18769`) — confirm that still runs after
your insert by checking `prolif.coaters_are_supplied` is green in the validate
suite.

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "fix: ban the Coater body's own level and its area-1 rival cell

A body tile is an occupied belt, so no path steps onto it -- but
_merge_frontier could still offer it as a merge goal, which is the one
remaining route to a two-predecessor tile under the addon. The rival ban
makes area-1 resolution independent of the yaw convention."
```

---

### Task 3: Delete `_coater_seat` and pin the west-channel floor

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:18040-18097` (delete `_coater_seat`)
- Modify: `src/flab2bp/layout/freeform.py:207-210` (comment on `_COATER_WEST_CHANNEL`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: nothing new. Removes `freeform._coater_seat`.

- [ ] **Step 1: Write the failing test**

```python
def test_coater_west_channel_leaves_at_least_one_legal_seat() -> None:
    """`_COATER_WEST_CHANNEL` is a floor, not a comfortable default.

    A seat must sit at index >= 1 + half_span and strictly below `west_channel`,
    so a channel narrower than 2 + half_span offers nothing and every sprayed
    lane raises `_Unseatable`.  Pinning it here means a future narrowing is a
    failing test rather than a corpus-wide refusal.
    """
    half = freeform._coater_body_half_span(Facing.EAST.value)
    assert freeform._COATER_WEST_CHANNEL >= 2 + half

    canvas, port = _lane_canvas(0, 0, freeform._COATER_WEST_CHANNEL + 2)
    assert freeform._coater_seats(
        canvas, port, west_channel=freeform._COATER_WEST_CHANNEL
    )


def test_coater_seat_helper_is_gone() -> None:
    """`_coater_seat` documented a second-tile rule `_coater_seats` now forbids."""
    assert not hasattr(freeform, "_coater_seat")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "west_channel_leaves or seat_helper_is_gone" -v; echo "exit=$?"
```

Expected: `test_coater_seat_helper_is_gone` FAILs (the attribute exists);
`test_coater_west_channel_leaves_at_least_one_legal_seat` should already pass
and is a guard, not a red test — that is fine and expected for this one.

- [ ] **Step 3: Delete `_coater_seat` and document the floor**

Remove the whole of `def _coater_seat(...)` at `freeform.py:18040-18097`.
Confirm nothing references it:

```bash
grep -rn "_coater_seat\b" src tests scripts docs/superpowers/specs docs/superpowers/plans
```

Expected: only this plan and the design spec mention it, and only in prose.

Then extend the comment at `freeform.py:208-210`:

```python
#: Sprayed lanes need two additional west cells so the 3x1 coater body clears
#: the machine footprint while retaining a straight predecessor and successor.
#:
#: IT IS ALSO A FLOOR.  `_coater_seats` offers indices
#: `1 + half_span .. west_channel - 1`, so a channel below `2 + half_span`
#: offers no seat at all and every sprayed lane refuses.  With the 1x3 body's
#: half-span of 1 that floor is 3, which is this value exactly.
_COATER_WEST_CHANNEL = 3
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "west_channel_leaves or seat_helper_is_gone" -v; echo "exit=$?"
python3 -m pytest tests/layout/test_freeform.py -q; echo "exit=$?"
```

Expected: `exit=0` for both.

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "refactor: delete _coater_seat and pin _COATER_WEST_CHANNEL as a floor"
```

---

### Task 4: `CoaterNode` — the invariant stated in the type

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (add `CoaterNode` beside
  `CoaterSupplyPort` at `6096`; return it from `_place_coaters` at `18141`;
  carry it on `_PreparedProblem` at `8700`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_coater_body_half_span` (Task 1), the `_StagedCoater` list
  `_place_coaters` already builds.
- Produces: `freeform.CoaterNode` with fields `item: str`,
  `strip_index: int`, `in_belt: int`, `body: tuple[int, ...]`,
  `out_belt: int`, `seat: tuple[int, int, int]`, `yaw: float`,
  `drop: tuple[int, int, int]`, `approach: tuple[int, int, int]`; and
  `_PreparedProblem.coater_nodes: tuple[CoaterNode, ...] = ()`.
  `_place_coaters` returns `tuple[list[CoaterSupplyPort], list[CoaterNode]]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_coater_node_refuses_a_body_over_its_own_in_port() -> None:
    with pytest.raises(ValueError, match="may not cover its own in-port"):
        freeform.CoaterNode(
            item="iron-ingot",
            strip_index=0,
            in_belt=7,
            body=(7, 8, 9),
            out_belt=10,
            seat=(8, 20, 0),
            yaw=Facing.EAST.value,
            drop=(7, 20, 1),
            approach=(6, 20, 1),
        )


def test_prepared_problem_carries_one_coater_node_per_supply_port() -> None:
    spec = proliferated_spec()
    strips = plan_strips(spec)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec, strips, pack, policy=BandPolicy("portable"), power=False
    )

    assert len(prepared.coater_nodes) == len(prepared.coater_supply_ports)
    for node, port in zip(prepared.coater_nodes, prepared.coater_supply_ports, strict=True):
        assert node.seat == (port.host_x, port.host_y, port.host_z)
        assert node.item == port.item
        assert node.in_belt not in node.body
        assert node.out_belt not in node.body
        # The in-port is the lane head: west of every body cell.
        # `_PreparedProblem.building_templates` (freeform.py:8677) is the frozen
        # building list; `_PreparedProblem` has no `canvas` attribute.
        templates = prepared.building_templates
        head = templates[node.in_belt]
        assert all(head.x < templates[b].x for b in node.body)
        assert templates[node.out_belt].x > max(templates[b].x for b in node.body)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "coater_node_refuses or prepared_problem_carries" -v; echo "exit=$?"
```

Expected: FAIL — `module 'flab2bp.layout.freeform' has no attribute 'CoaterNode'`.

- [ ] **Step 3: Add the record**

Immediately after `class CoaterSupplyPort` (`freeform.py:6096-6113`):

```python
@dataclass(frozen=True, slots=True)
class CoaterNode:
    """One Spray Coater as a placed node: in-port, body, out-port, supply.

    A coater is a belt addon -- ``catalog.BuildingInfo.occupies_tiles`` is
    ``not is_belt_addon`` -- so it can never be a free-standing packed object.
    Its "ports" are positions on the lane it rides: the head it is fed through,
    the tiles its 1x3 body covers, and the first tile east of them, from which
    every sorter on the strip draws sprayed cargo.

    The ``__post_init__`` below is the whole point of this class.  It states,
    once and in the type, the invariant Tasks 1 and 2 make true by arithmetic,
    so a future strategy that seats a coater some other way fails loudly instead
    of shipping a blueprint that pastes, runs, and quietly misses its rate.
    """

    item: str
    strip_index: int
    #: Lane belt index of the in-port: the lane HEAD, and the only cell of this
    #: lane a router path can reach, so the cell every producer net merges at.
    in_belt: int
    #: Lane belt indices the body covers, west to east, at the seat's level.
    body: tuple[int, ...]
    #: First lane belt east of the body; the out-port sorters draw from.
    out_belt: int
    seat: tuple[int, int, int]
    yaw: float
    drop: tuple[int, int, int]
    approach: tuple[int, int, int]

    def __post_init__(self) -> None:
        if self.in_belt in self.body:
            raise ValueError(
                "a Spray Coater's body may not cover its own in-port: the head "
                "is where producer nets merge, and a merge under the body is "
                "the defect this node exists to make impossible"
            )
        if self.out_belt in self.body:
            raise ValueError(
                "a Spray Coater's out-port must lie east of its body, or the "
                "cargo a sorter draws has not passed through the addon"
            )
```

- [ ] **Step 4: Build one node per committed coater**

In `_place_coaters`, the commit loop (`freeform.py:18749-18764`) already walks
`staged` and appends `candidate.port` to `out`. Beside it, build the node from
the same candidate. The lane's belt indices are `port.tiles` on the
`_Port` the loop already holds; find the body by x-offset from the seat:

```python
    nodes: list[CoaterNode] = []
    for candidate in staged:
        ...  # existing canvas.add calls for approach, supply and the coater
        lane = candidate.lane_port          # the `_Port` this seat came from
        half = _coater_body_half_span(candidate.port.yaw)
        seat_x = candidate.port.host_x
        body = tuple(
            index
            for index in lane.tiles
            if abs(canvas.buildings[index].x - seat_x) <= half
        )
        east = [
            index
            for index in lane.tiles
            if canvas.buildings[index].x > seat_x + half
        ]
        nodes.append(
            CoaterNode(
                item=candidate.port.item,
                strip_index=canvas.buildings[candidate.port.host_belt].owner_strip or 0,
                in_belt=lane.tiles[0],
                body=body,
                out_belt=east[0] if east else lane.tiles[-1],
                seat=(seat_x, candidate.port.host_y, candidate.port.host_z),
                yaw=candidate.port.yaw,
                drop=(candidate.port.x, candidate.port.y, candidate.port.z),
                approach=(
                    candidate.approach.x,
                    candidate.approach.y,
                    int(candidate.approach.z),
                ),
            )
        )
    return out, nodes
```

`_StagedCoater` (`freeform.py:6114-6122`) does not carry the `_Port` the seat
came from. Add one field to it:

```python
    #: The lane port this seat was chosen on, so the committed node can name its
    #: in-port and out-port without re-deriving them from coordinates.
    lane_port: _Port
```

and pass `port` when the candidate is built at `freeform.py:18482-18491`.

- [ ] **Step 5: Thread it to the prepared problem**

`_PreparedProblem` (`freeform.py:8700`) gains, beside `coater_supply_ports`:

```python
    coater_nodes: tuple[CoaterNode, ...] = ()
```

The two `_place_coaters` call sites at `freeform.py:16723` and `16733` become

```python
            coater_list, coater_nodes = _place_coaters(...)
```

with `coater_nodes: list[CoaterNode] = []` initialised beside
`coater_list` at `freeform.py:16715`, and the construction at
`freeform.py:17200` gains `coater_nodes=tuple(coater_nodes)`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python3 -m pytest tests/layout/test_freeform.py -k "coater_node_refuses or prepared_problem_carries" -v; echo "exit=$?"
python3 -m pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q; echo "exit=$?"
```

Expected: `exit=0` for both. `sequence_solver.py:5536` reads
`len(candidate.prepared.coater_supply_ports)` and is untouched by this change —
if it errors, the tuple unpacking at a call site was missed.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat: CoaterNode states the in-port/body/out-port invariant in the type"
```

---

### Task 5: The hierarchical composer sees the node

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/compose.py:318-363` (`_coater_belt_ban`)
- Test: `tests/layout/hierarchy/test_compose.py`

**Interfaces:**
- Consumes: `freeform._coater_body_half_span` (Task 1) and the enlarged
  `_reserve_staged_coater_belt_ban` (Task 2).

- [ ] **Step 1: Write the failing test**

`tests/layout/hierarchy/test_compose.py` imports only
`PortAccessEvidence, PortAccessKind, PortAccessReservation` from `freeform`
today. Add to its import block:

```python
from flab2bp.layout import freeform
from flab2bp.layout.freeform import _Canvas
```

Then:

```python
def test_composed_coater_bans_its_body_level_like_a_seated_one() -> None:
    """A composed block's coater must be priced exactly like a seated one.

    `_coater_belt_ban` rebuilds a `_StagedCoater` from the committed building
    alone.  Task 2 added two bans that read `staged.port.host_z`,
    `staged.port.yaw` and the drop -- all of which that reconstruction already
    supplies -- so the composed canvas must show the same bans.
    """
    canvas = _Canvas()
    coater = PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
        x=10,
        y=4,
        z=Fraction(0),
        width=1,
        height=1,
        yaw=Facing.EAST.value,
        owner_strip=0,
    )
    index = len(canvas.buildings)
    canvas.buildings.append(coater)

    compose._coater_belt_ban(canvas, index, catalog.building(2001).model_index)

    half = freeform._coater_body_half_span(Facing.EAST.value)
    drop = slots.addon_supply_cell(
        catalog.SPRAY_COATER_ID, x=10, y=4, z=Fraction(0), yaw=Facing.EAST.value, area=1
    )
    for dx in range(-half, half + 1):
        cell = (10 + dx, 4)
        if cell == (drop[0], drop[1]):
            continue
        assert 0 in canvas.belt_ban.get(cell, set())
    rival = (2 * 10 - drop[0], 2 * 4 - drop[1])
    assert drop[2] in canvas.belt_ban.get(rival, set())
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python3 -m pytest tests/layout/hierarchy/test_compose.py::test_composed_coater_bans_its_body_level_like_a_seated_one -v; echo "exit=$?"
```

Expected: FAIL if the reconstruction does not carry `host_z` or `z` correctly;
PASS immediately if Task 2's insert already covers it — in which case record
that in the commit body and move on, the test is the guard.

- [ ] **Step 3: Fix the reconstruction if it fails**

`compose._coater_belt_ban` fills `host_z=int(coater.z)` and `z=drop[2]`
(`compose.py:356-359`), which is what the Task 2 bans read. If the test fails,
the cause is `port.yaw` or the drop, both already on the building — correct the
field, do not weaken the test.

- [ ] **Step 4: Run the test and the hierarchy suite**

```bash
python3 -m pytest tests/layout/hierarchy -q; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/hierarchy/compose.py tests/layout/hierarchy/test_compose.py
git commit -m "test: a composed Coater is priced with the same body and area-1 bans"
```

---

### Task 6: Apply the over-proliferation ruling

**Files:**
- Modify: `src/flab2bp/layout/validate.py:5011-5106`
  (`prolif.sprayed_cargo_reaches_machines`)
- Modify: `src/flab2bp/cli.py`
- Test: `tests/layout/test_validate.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `prolif.sprayed_cargo_reaches_machines` yields `Severity.ERROR` for
  the `requires_spray` half and `Severity.WARNING` for the `forbids_spray` half.

**Ruling being applied (user, verbatim):** "Over-proliferating is actually fine
if it makes life easier." Measured consequence, from the design spec §6.5: only
2 of 36 corpus specs draw an item in both cargo domains, and 0 output lanes are
duplicated by the split — so this removes a refusal class, not lanes. Do **not**
remove `CargoDomain`; do **not** remove `BuildSpec.lanes_requiring_split`, which
becomes the report of what got over-proliferated.

- [ ] **Step 1: Write the failing tests**

```python
def test_unproliferated_consumer_downstream_of_a_coater_is_a_warning() -> None:
    """Over-proliferation is accepted: the build over-produces, on purpose.

    User ruling 2026-09-07. The finding stays -- the player is told which items
    got sprayed that the rates did not price -- but it no longer refuses a
    placement.
    """
    report = _report_for(_shared_lane_both_domains_placement())

    findings = [
        f
        for f in report.findings
        if f.check == "prolif.sprayed_cargo_reaches_machines"
        and "passed a Spray Coater" in f.message
    ]
    assert findings
    assert all(f.severity is Severity.WARNING for f in findings)
    assert not [f for f in report.errors if f.check == "prolif.sprayed_cargo_reaches_machines"]


def test_proliferated_consumer_fed_unsprayed_is_still_an_error() -> None:
    """The other half is untouched: missing spray still silently misses rate."""
    report = _report_for(_proliferated_machine_fed_unsprayed_placement())

    findings = [f for f in report.errors if f.check == "prolif.sprayed_cargo_reaches_machines"]
    assert findings
    assert all(f.severity is Severity.ERROR for f in findings)
```

Build `_shared_lane_both_domains_placement` and
`_proliferated_machine_fed_unsprayed_placement` as hand-built placements in the
style `tests/layout/test_validate.py` already uses for coater checks: one belt
run, a coater on it, and two sorters into two machines whose `MachineGroup`s
differ in `proliferator_mode`, with `spec.spray_lanes` naming the item and
`spec.lanes_requiring_split` containing it.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/layout/test_validate.py -k "downstream_of_a_coater_is_a_warning or fed_unsprayed_is_still_an_error" -v; echo "exit=$?"
```

Expected: the first FAILs (severity is ERROR), the second PASSes.

- [ ] **Step 3: Split the severity**

At `validate.py:5100-5106`, replace the single `yield Finding(...)` with a
severity chosen by which half fired:

```python
                yield Finding(
                    "prolif.sprayed_cargo_reaches_machines",
                    Severity.ERROR if requires_spray else Severity.WARNING,
                    message,
                    (i, m, src),
                    {"item": item, "machine": m, "belt": src},
                )
```

and extend the `forbids_spray` message at `validate.py:5092-5099`:

```python
                    message = (
                        f"sorter {i} feeds unproliferated machine {m} with {item} "
                        f"from belt {src} at ({bs[src].x}, {bs[src].y}) after it "
                        "passed a Spray Coater, so this machine over-produces "
                        "against the rates. Accepted by user ruling 2026-09-07: "
                        "over-proliferating is fine if it makes life easier"
                    )
```

Update the check's docstring at `validate.py:5013-5039` so the second paragraph
states that the `forbids_spray` half is a WARNING and why. Do not delete the
paragraph — the reason the split existed is still the reason the warning exists.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/layout/test_validate.py -k "downstream_of_a_coater_is_a_warning or fed_unsprayed_is_still_an_error" -v; echo "exit=$?"
python3 -m pytest tests/layout/test_validate.py -q; echo "exit=$?"
```

Expected: `exit=0` for both.

- [ ] **Step 5: Name the over-proliferated items on the CLI report**

In `src/flab2bp/cli.py`, wherever the belt-in summary is printed, add one line
when `spec.lanes_requiring_split` is non-empty:

```python
    if spec.lanes_requiring_split:
        print(
            "over-proliferated (shared sprayed lane): "
            + ", ".join(sorted(spec.lanes_requiring_split))
        )
```

Add a `tests/test_cli.py` case asserting the line appears for a spec with a
non-empty `lanes_requiring_split` and does not appear for one without.

- [ ] **Step 6: Run the CLI suite**

```bash
python3 -m pytest tests/test_cli.py -q; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/layout/validate.py src/flab2bp/cli.py tests/layout/test_validate.py tests/test_cli.py
git commit -m "feat: over-proliferation is a warning, not a refusal

User ruling 2026-09-07. A sprayed lane reaching an unproliferated consumer
over-produces on purpose; the finding stays so the player is told which items,
and the CLI names them. The missing-spray half is untouched and still an
ERROR: that one silently MISSES rate rather than exceeding it."
```

---

### Task 7: Gate, reconcile with `selfloop`, and write the evidence

**Files:**
- Modify: `docs/superpowers/evidence/2026-09-07-coater-node/README.md`
- Create: `docs/superpowers/evidence/2026-09-07-coater-node/after-audit.txt`
- Create: `docs/superpowers/evidence/2026-09-07-coater-node/after-seat-census.txt`
- Modify: `src/flab2bp/layout/freeform.py` (only if `selfloop`'s seat predicate
  landed and is now vacuous)
- Modify: `docs/speedup-idea-backlog.md:184-185`

- [ ] **Step 1: Reconcile with `selfloop`**

```bash
grep -rn "coater_rides_one_run" src tests
```

If `prolif.coater_rides_one_run` exists in `src/flab2bp/layout/validate.py`:
it **stays**, unchanged, as the regression arbiter — confirm it is green:

```bash
python3 -m pytest tests/layout/test_validate.py -k coater_rides_one_run -q; echo "exit=$?"
```

If `selfloop` also added a merge-rejecting predicate inside `_coater_seats` or
`_place_coaters`, it is now vacuous — Tasks 1 and 2 make the geometry it rejects
unreachable. Delete the predicate, keep the check, and add to
`_coater_seats`'s docstring: "the merge predicate this used to carry is gone;
the west bound above makes the geometry it rejected unbuildable."

If `prolif.coater_rides_one_run` does **not** exist, add it now from the code
block at `docs/superpowers/specs/2026-09-06-self-loop-recipes-design.md:439-452`,
with tests T9 and T10 from that spec's §6 table. It is the arbiter this plan's
structural work is measured against and shipping without it leaves nothing to
catch a regression.

- [ ] **Step 2: Run the seat census again**

```bash
uptime
python3 docs/superpowers/evidence/2026-09-07-coater-node/seat-census.py \
  > docs/superpowers/evidence/2026-09-07-coater-node/after-seat-census.txt
uptime
python3 - <<'PY'
import json
base = json.load(open("docs/superpowers/evidence/2026-09-07-coater-node/seat-census.txt"))
after = json.load(open("docs/superpowers/evidence/2026-09-07-coater-node/after-seat-census.txt"))
def seated(rows): return [r for r in rows if "seat" in r]
def covers_head(rows):
    return sum(1 for r in seated(rows) if r["body_x"][0] <= r["seat"][0] - 2)
print("coaters seated  before", len(seated(base)), "after", len(seated(after)))
print("specs refused   before", len(base) - len(seated(base)),
      "after", len(after) - len(seated(after)))
PY
```

Expected: the seated count is unchanged or lower; every lost coater is a spec
that now refuses. **Any drop is Risk 1 in the design spec** — record the exact
URL/label pairs.

- [ ] **Step 3: Run the gate**

Same flags and the same budget as Task 0, or the comparison is meaningless.

```bash
rm -f docs/superpowers/evidence/2026-09-07-coater-node/after.jsonl
uptime | tee docs/superpowers/evidence/2026-09-07-coater-node/after-audit.txt
python3 scripts/audit.py --tier stress --strategy both --budget 30 \
  --json docs/superpowers/evidence/2026-09-07-coater-node/after.jsonl \
  2>&1 | tee -a docs/superpowers/evidence/2026-09-07-coater-node/after-audit.txt
echo "exit=$?" | tee -a docs/superpowers/evidence/2026-09-07-coater-node/after-audit.txt
uptime | tee -a docs/superpowers/evidence/2026-09-07-coater-node/after-audit.txt
```

Then compare cell by cell. `audit_compare.py` pairs on
`(strategy, url_id, spec_index)` and fails on any cell the candidate did not
run, so pass `--expect-cells 72`:

```bash
python3 scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-07-coater-node/baseline.jsonl \
  docs/superpowers/evidence/2026-09-07-coater-node/after.jsonl \
  --expect-cells 72
echo "exit=$?"
```

`audit.py` says NOT CLEAN on any refusal, so read the comparison's **counts and
differing cells**, never either run's own verdict.

**Gate criterion:** no cell that was clean at baseline may be non-clean now. A
cell that becomes `unseatable` is the one regression this design predicted; if
any appear, do not paper over them — Step 5 reports them to the user, because
the fix (`_COATER_WEST_CHANNEL` 3 → 4) is open question 3 in the design spec and
is the user's call.

- [ ] **Step 4: Write the `## After` section of the evidence README**

State: the `uptime` load before and after each run; the before/after clean-cell
counts; the before/after seated-coater counts; the list of cells that changed
state, with the `preparation_error` for each; and one sentence per differing
cell saying whether it is the predicted seat loss or something else.

- [ ] **Step 5: Update the backlog and commit**

Replace `docs/speedup-idea-backlog.md:184-185`:

```markdown
- ~~Coater-composite strips: treat spray coater plus strip as one unit so the
  placer never sees the keep-out problem (all-products class).~~ **Delivered
  2026-09-07** by `docs/superpowers/specs/2026-09-07-coater-node-design.md`:
  the coater was already inside the strip's reserved west channel; what was
  missing was that its body could cover the lane head where nets merge. See
  that spec §3 Option C for why a separately packed coater is rejected
  (+233 nets, +233 CP-SAT objects on the corpus).
```

```bash
git add docs/superpowers/evidence/2026-09-07-coater-node docs/speedup-idea-backlog.md src tests
git commit -m "evidence: coater-node gate, and mark the composite-strip backlog item delivered"
```

- [ ] **Step 6: Report to the user**

Report, in this order: the before/after clean-cell counts; any cell that
regressed and its `preparation_error`; the answer to open question 3 if a
regression appeared (`_COATER_WEST_CHANNEL` 3 → 4 costs one column on 118
proliferated strips corpus-wide); and the three open questions from the design
spec §8 that remain unanswered.

---

## Self-Review

**Spec coverage.**

| Spec section | Task |
|---|---|
| §2.2 "rides exactly one run" structural — seat index | Task 1 |
| §2.2 "rides exactly one run" structural — body ban | Task 2 |
| §2.2 area-1 ambiguity | Task 2 |
| §2.2 "merges only upstream" | Tasks 1+2 (same mechanism) |
| §2.1 no rate-layer node | Nothing to do — the plan deliberately touches no file under `src/flab2bp/rates/`. |
| §5.1 `_coater_seats` | Task 1 |
| §5.2 `_reserve_staged_coater_belt_ban` | Task 2 |
| §5.3 `CoaterNode` | Task 4 |
| §5.4 over-proliferation ruling | Task 6 |
| §4 migration table — `_coater_seat` deleted, west channel pinned | Task 3 |
| §4 migration table — composer | Task 5 |
| §4 relationship to `selfloop` | Task 7 Step 1 |
| §6 costs measured | Tasks 0 and 7 (census + gate) |
| §7 Risk 1 counted | Task 7 Steps 2-3 |
| §8 open question 3 answered with a number | Task 7 Step 6 |

**Placeholder scan.** Task 2 Step 1 offers a fallback if `_PreparedProblem` has
no `canvas` attribute and Task 6 Step 1 asks for two hand-built placements
without giving their bodies; both are named precisely enough to build from the
existing suite, and both are guarded by an exact assertion. Task 5 Step 3 is
conditional on a test outcome, which is deliberate. Everything else carries the
code it needs.

**Type consistency.** `_coater_body_half_span(yaw: float) -> int` is defined in
Task 1 and used with that signature in Tasks 2, 3, 4 and 5. `CoaterNode`'s nine
fields are defined in Task 4 Step 3 and used with the same names in Task 4
Step 1's tests and Step 4's construction. `_place_coaters` returns
`tuple[list[CoaterSupplyPort], list[CoaterNode]]` from Task 4 Step 4 onward and
both call sites are updated in Step 5. `_StagedCoater.lane_port: _Port` is added
in Task 4 Step 4 and read in the same step.
