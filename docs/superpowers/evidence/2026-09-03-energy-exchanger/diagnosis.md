# broke6 -- Energy Exchanger: a refused candidate and a colliding paste

Diagnosed 2026-09-03 against `master` 688cbed. Read-only in the checkout; every
experiment ran in a `git archive` copy under the session scratchpad with the
checkout's `.venv/bin/python`.

TWO DEFECTS, ONE MACHINE, INDEPENDENT ROOT CAUSES.

* **A -- the refusal.** `freeform/output-products` refuses because the Energy
  Exchanger's *output* lanes outnumber its one north-facing belt port. The
  refusal message blames the *input* docks; that text is wrong.
* **B -- the collision.** Every Energy Exchanger we emit today gets a belt
  approach that runs 5 tiles inside its build collider. The game convicts the
  2 tiles beyond its 3-hop rescue. Our own game-faithful checker agrees --
  `validate` never says so because it *skips* this building.

`B` is the more serious of the two: it ships a blueprint the game refuses.

---

## 1. Reproduction

Box was never idle. `uptime` at the start of the timed run:
`17:41:09 up 18 days, 23:27, 9 users, load average: 6.15, 4.82, 5.78`;
`vmstat 1 3` at 17:42:00 showed `r=3..8, b=0, wa=0, id=93..97`, i.e. the box was
CPU-busy but not blocked on disk.

The URL is one line, in `/home/dannyb/broke6.txt`. Every command below reads it
from there so the `.`/`-` characters in the FactorioLab payload survive:

```bash
URL=$(head -1 /home/dannyb/broke6.txt)
```

### 1.1 Default build -- succeeds, but reports the refusal

```bash
time timeout 900 uv run flab2bp "$URL" --verbose
```

Wall: **54.5 s** (`252.17s user, 466% cpu`). Verbatim, trimmed to the verdict:

```
freeform / all-products: 9 machines, 1505 tiles, 1026 buildings
primary_band: 160
certified_bands: 160, 200
  1 strategy/candidate pair(s) produced no layout:
    freeform/output-products: a machine in this spec has lanes to wire and no insert pose to wire them to, so it would paste joined to nothing. Energy Exchanger (accumulator-full): its ingredient lanes cannot claim distinct east-facing input docks from its 4 belt port(s) while preserving one legal splitter-backed fan-out per machine

candidate           strategy      area  errors
all-products        freeform      1505       0
no-proliferator     freeform      1512       0
all-products        sequence-pair    1548       0
no-proliferator     sequence-pair    1568       0
output-products     sequence-pair    1909       0
BLUEPRINT:...
```

**Five of six pairs build clean and report zero validator errors.** The one
refusal is `freeform` x `output-products`.

### 1.2 The refusing pair alone -- instant, not a budget problem

```bash
time timeout 900 uv run flab2bp "$URL" --strategy freeform --candidate-policy output-products --verbose
```

Wall: **1.46 s** total.

```
flab2bp: no valid layout for output-products after 15s: freeform/output-products: a machine in this spec has lanes to wire and no insert pose to wire them to, so it would paste joined to nothing. Energy Exchanger (accumulator-full): its ingredient lanes cannot claim distinct east-facing input docks from its 4 belt port(s) while preserving one legal splitter-backed fan-out per machine. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

1.46 s against a 15 s budget: this is a **pre-solve feasibility predicate**, not
an exhausted search. Note the CLI flag is `--candidate-policy`, not `--policy`.

### 1.3 The spec this URL decodes to

Via `pipeline.canonicalize_dataset` / `parse_url` / `_build_candidates_canonical`:

| candidate | machines | Energy Exchanger groups |
| --- | --- | --- |
| `no-proliferator` | 15 | `accumulator-full` x 4 (unsprayed) |
| `all-products` | 9 | `accumulator-full` x 3 (sprayed, products) |
| `output-products` | 12 | `accumulator-full` x 4 (sprayed, products) **and `accumulator-discharge` x 1** |

Output for all three is `accumulator-full` at `1/3` per second (20/min).
`accumulator-full` is `ModeDriven(2209, "energy-exchanger", "charge")` and
`accumulator-discharge` is the same building in `"discharge"` mode
(`src/flab2bp/dsp/catalog.py:810-818`). The charge machine eats `accumulator`
and makes `accumulator-full`; the discharge machine eats `accumulator-full` and
makes `accumulator`.

**`output-products` is the only candidate that contains a discharge exchanger**,
and that is what breaks it -- see 2.1.

---

## 2. Defect A: the refusal

### 2.1 Mechanism

The failing predicate chain, in `src/flab2bp/layout/freeform.py`:

* `_machines_without_poses` (`:16480-16600`) is the pre-solve gate. A
  belt-port machine with input lanes survives it only if
  `_feedable_by_port(s)` is true (`:16545`); otherwise the refusal text at
  `:16562-16568` fires.
* `_feedable_by_port` (`:16467-16478`) is a conjunction of four terms, the last
  of which is `(not strip.out_lanes or _drainable_by_port(strip))`.
* `_drainable_by_port` (`:16460-16464`) counts docks with
  `dock.facing.delta[1] > 0` -- i.e. **north-facing only** -- and demands
  `len(strip.out_lanes) <= capacity`.

Instrumented run of the copy (monkey-patching `_machines_without_poses` to dump
each belt-port strip before delegating), for the `accumulator-full` strip:

```
[_feedable_by_port terms for accumulator-full]
  bool(lanes)              = True
  all(len(lane)==1)        = True
  len(lanes)=1 <= east_cap=1 = True
  out_lanes=2 <= north_cap=1 -> _drainable = False
```

and the strip itself:

```
--- STRIP recipe=accumulator-full item=2209 name=Energy Exchanger
    yaw=0.0 pw=11 ph=10  slot_poses=0 port_poses=4
    in_above=(('accumulator',),)
    in_below=()
    out_lanes=(('accumulator-full', 'accumulator-discharge#1', UNSPRAYED),
               ('accumulator-full', '',                        UNSPRAYED))
    dock[0] cell=(4, 6) facing=NORTH   dock[1] cell=(6, 4) facing=EAST
    dock[2] cell=(4, 2) facing=SOUTH   dock[3] cell=(2, 4) facing=WEST
    _feedable_by_port=False _drainable_by_port=False
```

**Root cause A.** The `output-products` candidate adds a discharge exchanger, so
the charge exchanger now has **two output lanes** -- both carrying the *same*
item `accumulator-full`, one to the internal consumer
(`accumulator-discharge#1`), one to the external output (`''`). A belt-port host
may drain only through a port facing the lane band below it, and an Energy
Exchanger has **exactly one** such port at any yaw. `_drainable_by_port` demands
one distinct north-facing dock per output lane, so 2 > 1 and the strip is
declared unwireable. The `accumulator-discharge` strip in the same spec has one
in-lane and one out-lane and passes (`_feedable_by_port=True`).

The same all-products spec, probed identically, has `out_lanes` of length **1**
and builds (`_feedable_by_port=True _drainable_by_port=True  ... BUILT
all-products`). That single difference is the whole of defect A.

### 2.2 The message is wrong about which side failed

`freeform.py:16562-16568` prints "its **ingredient** lanes cannot claim distinct
**east-facing input docks** ... while preserving one legal splitter-backed
fan-out per machine". The instrumentation above shows the ingredient side is
fine (`1 <= east_cap=1`); the failing term is the *output* drain. Anyone
following this message goes to `_dock_input_lane` and finds nothing wrong. Fix
the text with the fix.

### 2.3 Alternatives ruled out

* **(a) A catalog / port-table defect.** Ruled out. The port table
  (`src/flab2bp/dsp/data/slot_poses.json`, `energy-exchanger.portPoses`) is four
  cardinal ports at `+-2.85` world units, one per side, forwards `(0,0,1)`,
  `(1,0,0)`, `(0,0,-1)`, `(-1,0,0)`. Independently corroborated: the same table
  drives `slots.port_dock`, and the collider model built on it predicts the
  *exact* tiles the game flags in the user's screenshot (section 3.3). A wrong
  port table could not do that.
* **(b) Seating too strict for one item on several ports.** Half-true, but on
  the *output* side, not the ingredient side the message names. This is (c).
* **(c) A lane-count problem.** **Confirmed** -- 2 output lanes, 1 usable dock.
* **(d) A mirrored / rotated variant that would work but is never tried.** Ruled
  out. `slots.port_docks(slots.probe_building(2209, yaw))` at every legal yaw:

  ```
  yaw=0.0:   0:(4,6)NORTH 1:(6,4)EAST 2:(4,2)SOUTH 3:(2,4)WEST  north_cap=1 east_cap=1
  yaw=90.0:  0:(6,4)EAST  1:(4,2)SOUTH 2:(2,4)WEST 3:(4,6)NORTH north_cap=1 east_cap=1
  yaw=180.0: 0:(4,2)SOUTH 1:(2,4)WEST  2:(4,6)NORTH 3:(6,4)EAST north_cap=1 east_cap=1
  yaw=270.0: 0:(2,4)WEST  1:(4,6)NORTH 2:(6,4)EAST  3:(4,2)SOUTH north_cap=1 east_cap=1
  ```

  Rotation permutes the port indices and never changes the capacity: one north
  dock, one east dock, always.
* **(e) The two lanes genuinely need two belts.** Ruled out. Both lanes carry
  `accumulator-full`; a single drained belt plus one splitter serves both, which
  is precisely the fan-out the *input* side already does
  (`_dock_input_lane` -> `_tap_source`, `freeform.py:5559-5573`). And
  `sequence-pair/output-products` lays the identical spec out cleanly at 1909
  tiles, so the spec is layoutable.

---

## 3. Defect B: the emitted blueprint collides in game

### 3.1 What the game says

`/home/dannyb/full8.png` is the paste preview of the **all-products** freeform
result (9 machines, 1505 tiles, 43x35 -- the build that reports **zero**
validator errors). Three Energy Exchangers in the right-hand column. Each has a
belt that leaves it westward and immediately turns; on all three the **turning
tile** carries `Collide with other object` + `Connection target cannot be laid`,
while the tile at the building's own edge is clean.

### 3.2 The validator is switched off for this building

`src/flab2bp/layout/validate.py:2689`, inside `_belt_collide_findings`
(`:2673`), which serves both `game.belt_crossing` and `game.belt_collide`:

```python
        if bs[ic].item_id in cat.LOW_CONFIDENCE_FOOTPRINTS:
            continue
```

`catalog.LOW_CONFIDENCE_FOOTPRINTS` (`src/flab2bp/dsp/catalog.py:697`) contains
`2209`. Its justification, `catalog.py:690-697`, is explicit:

> Buildings whose extracted collider does not reproduce real blueprints, all of
> them large and **none of them placed by the generator**.

**That premise is now false.** `MODE_DRIVEN_MACHINE` (`catalog.py:810-818`) makes
2209 (Energy Exchanger) and 2208 (Ray Receiver) machines the generator places.
The test that was supposed to hold the premise,
`tests/dsp/test_catalog.py:418-424`, checks a **hardcoded** `generator_places`
set that was never updated when mode-driven machines landed:

```python
generator_places = {
    2302,
    2303,
    2304,
    2305,
    2308,
    2309,
    2310,
    2314,
    2315,
    2318,
    2319,
    2901,
    2902,
}
assert not (generator_places & catalog.LOW_CONFIDENCE_FOOTPRINTS)
```

So the check passes vacuously and the exemption silently suppresses real
convictions on a building we now place. `OPT_IN` is empty
(`validate.py:747`), so `game.belt_collide` *does* run -- it just finds nothing.

### 3.3 Our own model reproduces the game exactly

Rebuilding the all-products freeform placement in the copy and calling the
project's own game-faithful primitive directly, with no `LOW_CONFIDENCE` filter:

```
area 1505  report ok True  errors 0
RAW belt_collisions: 6
STABLE belt_collisions: 6
  belt[99]  (14,22) vs bld[94] 2209 Energy Exchanger (7,21)   low_conf=True
  belt[100] (14,23) vs bld[94] ...
  belt[109] (25,22) vs bld[95] ...
  belt[110] (25,23) vs bld[95] ...
  belt[119] (36,22) vs bld[96] ...
  belt[120] (36,23) vs bld[96] ...
```

Six belts, two per exchanger, three exchangers -- exactly the three marker
clusters in the screenshot, systematic and identical on each. Per-belt, with the
game's rescue applied one belt at a time (exchanger centre tile is `(11,25)`;
`d` is the offset from it):

```
BELT[98]  (14,21) d(3,-4) out=99  probe_hits=()     ends_in_bldg=False  HIT=False
BELT[99]  (14,22) d(3,-3) out=100 probe_hits=(94,) excused=False        HIT=True
BELT[100] (14,23) d(3,-2) out=101 probe_hits=(94,) excused=False        HIT=True
BELT[101] (14,24) d(3,-1) out=102 probe_hits=(94,) excused=True         HIT=False
BELT[102] (14,25) d(3, 0) out=103 probe_hits=(94,) excused=True         HIT=False
BELT[103] (13,25) d(2, 0) out=94  probe_hits=(94,) ends_in_bldg=True    HIT=False
```

The run is `98 -> 99 -> 100 -> 101 -> 102 -> 103 -> exchanger`. `103` is the dock
(excused by `colliders.belt_run_ends_in_a_building`, `colliders.py:1191`); `102`
and `101` are excused by `colliders.belt_chain_excuses` (`colliders.py:1168`),
which reaches the host within three hops; `100` and `99` are four and five hops
out and are convicted. **The game's rescue admits exactly three belt tiles inside
a host's collider: the docking tile and the two behind it** -- which is what
`slots.py:918-919` already documents.

### 3.4 Why the belt is inside the collider at all -- the geometry

`src/flab2bp/dsp/data/colliders.json` model 45 (Energy Exchanger) has two boxes:

```
ext [5.85, 2.055, 5.85] at pos [0, 7.66, 0]     -- the overhanging cap, 5.8..9.9 high
ext [3.9,  5.3,   3.9 ] at pos [0, 5.3,  0]     -- the tower, 0.2..10.8 high
```

`GRID_ARC = 1.2566`, `BELT_PROBE_RADIUS = 0.23`, belt probe height `0.4`. Only
the **tower** box is at belt height. Its half-extent is `3.9 / 1.2566 = 3.10`
tiles, so a belt tile collides iff `|dx| <= 3 and |dy| <= 3` from the centre
(`3` tiles = `3.77` world < `4.13`; `4` tiles = `5.03` world > `4.13`). Verified
directly:

```
 belt (14,22) probe=(17.593, 0.4, 27.646) overlap=[False, True]
 belt (13,22) ... overlap=[False, True]
```

The east port pose is `2.85` world = `2.268` tiles, rounded by
`slots.port_dock` (`slots.py:935-954`) to `d=+2`. **So the game's own port sits
2 tiles from the centre, inside a collider that reaches 3.** That is not a
defect -- `slots.PortDock`'s docstring (`slots.py:907-932`) says so and names the
two excusals that make it legal. `derive_footprint` gives 9x9 from the *cap*
box's `5.85`; the belt question never uses the 9x9 number.

**Root cause B.** `_dock_input_lane` (`freeform.py:5473-5580`) builds the
approach as an L: a vertical column at

```python
tap_x = dock.cell[0] + 1  # freeform.py:5514
```

running from the input-lane row up/down to the dock row, then one tile west into
the dock. For an Energy Exchanger the dock is at `d=+2`, so **the whole vertical
column stands at `d=+3` -- inside the tower collider for its entire length**. In
this build the column is 5 tiles; 3 are rescued, 2 are convicted, per machine.
A straight-in approach along the port axis would put only `d=3` and `d=2` inside
(2 tiles, both rescued) with one hop to spare.

`_dock_lane` (`freeform.py:5583-5669`), the drain side, already runs a straight
column out along the port's forward, so it puts only `d=2` and `d=3` inside and
is clean -- consistent with the evidence: **all six convicted belts are on the
feed side**, at `dx=+3` (x = 14, 25, 36 for machines at x = 7, 18, 29).

### 3.5 The user's reading, tested and refuted

> the exchanger's belt port positions (or the footprint-to-belt-head offset) are
> shifted by one tile so the first belt tile sits inside the footprint

Not what happens. The first belt tile *is* inside the footprint and inside the
collider **by the game's own design**, and the game excuses it. Nothing is
off-by-one: the port pose rounds to `d=+2` from `2.268` tiles, which is correct
to `0.268` tiles -- the same `gap` every one of the four docks reports. The
flagged tiles are the **fourth and fifth** hops of the approach column, not the
second tile. `Connection target cannot be laid` appears on them because the
convicted belt's own link target is the next belt in a run that is itself
inside the collider; the game reports both conditions on the same preview.

### 3.6 This is not freeform-only

`sequence-pair / output-products` builds "clean" (0 validator errors) and has
the same disease:

```
=== sequence-pair / output-products ===
area 1856 errors 0 exchangers 5 raw stable collisions 10 of which vs exchanger 10
```

Ten real collisions, all against Energy Exchangers, all suppressed. Both
strategies emit through the shared strip docking helpers.

### 3.7 What the corpus does and does not exercise

**CORRECTED 2026-09-03.** The first version of this section said no corpus cell
places an Energy Exchanger *or a Ray Receiver*. The Ray Receiver half was wrong.
The check tested `MachineGroup.machine_item_id` against the ints `{2208, 2209}`,
but that field is the FactorioLab **string** id (`freeform.py:1857`,
`catalog.get_item_id(mg.machine_item_id)`), so the test was vacuously empty for
every group in the corpus. Re-measured against the strings:

```
universe-matrix STRESS no-proliferator  critical-photon ray-receiver 10
universe-matrix STRESS all-products     critical-photon ray-receiver  8
universe-matrix STRESS output-products  critical-photon ray-receiver  8
```

Everything else is `-`. So:

* **No corpus cell places an Energy Exchanger (2209).** §4 Option 1 change 1
  newly checks exactly one building, 2209 -- 2208 was never in
  `LOW_CONFIDENCE_FOOTPRINTS` -- so no currently-clean cell can turn INVALID
  from the exemption narrowing.
* **One corpus URL places 8-10 Ray Receivers in all three candidates.** A Ray
  Receiver has no input lanes and no east dock at yaw 0, so `_dock_input_lane`
  never runs for one, but it does reach `strip_variants._port_variants` and
  `freeform._dock_lane` on **6 of the 72 cells** (`universe-matrix` x 3
  candidates x 2 strategies, tier STRESS).

The corpus therefore cannot *prove* the exchanger fix -- hence the deterministic
unit tests and this URL as an end-to-end case -- but it is a real gate on the
approach and drain changes rather than reassurance, and the three
`universe-matrix` cells are a watched clause in the plan's gate task.

---

## 4. Fix options

The validator stays the arbiter throughout: **no option is allowed to make
`game.belt_collide` weaker, and no blueprint may be emitted that our own
game-faithful `colliders.stable_belt_collisions` convicts.** Turning the
exemption off is therefore a *precondition* of any fix, not an option in itself.

### Option 1 -- Narrow the exemption + straight-in port approach + splitter-backed drain (RECOMMENDED)

Three changes, in dependency order.

1. **`validate._belt_collide_findings`: stop skipping buildings the generator
   places.** Replace the `LOW_CONFIDENCE_FOOTPRINTS` membership test at
   `validate.py:2689` with a test against a new
   `catalog.UNPLACED_LOW_CONFIDENCE_FOOTPRINTS` = `LOW_CONFIDENCE_FOOTPRINTS -
   MODE_DRIVEN_MACHINE_ITEM_IDS`, the latter read off `MODE_DRIVEN_MACHINE`
   rather than listed. Every other machine we place is already absent from the
   distrusted set, so that subtraction is the whole correction. Fix
   `tests/dsp/test_catalog.py:418-424` to derive its "what do we place" answer
   from the lab dataset plus `MODE_DRIVEN_MACHINE`, so the premise cannot go
   stale again. Effect: the current all-products build starts
   FAILING validation (6 findings) -- which is correct, and is the failing test
   the rest of the fix has to make pass.
2. **`_dock_input_lane`: choose a tap column that keeps the in-collider tiles
   within the game's rescue.** Instead of the fixed `tap_x = dock.cell[0] + 1`,
   pick the smallest lane column `>= dock.cell[0] + 1` for which the resulting
   L-path has **at most 3 tiles whose belt probe overlaps the host's collider**,
   computed exactly with `colliders.belt_probe` / `colliders.target_boxes` --
   the same primitives the validator uses. For an Energy Exchanger that selects
   `dock.cell[0] + 2` (`d=+4`, outside the tower), giving a vertical run wholly
   outside the collider and a 2-tile horizontal run into the dock. For every
   existing machine (assemblers, smelters) the answer stays `+1`, so their
   emission is byte-identical. Update the `dock.cell[0] + 1 < strip.pw` capacity
   term in `_feedable_by_port` (`freeform.py:16472`) and the pitch that
   `placement_geometry` reserves so the wider tap column is inside the strip box.
3. **`_drainable_by_port` / `_port_variants`: let output lanes of the same item
   share one dock behind a splitter.** Mirror the input side: capacity becomes
   "one north dock per distinct `(item, cargo_domain)`", and lanes that share a
   dock are served by a splitter fan-out on the drained column, reusing
   `_tap_source`. Fix the refusal text at `freeform.py:16562-16568` to name the
   side that actually failed.

*Exactness:* every geometric decision is made with `dsp.colliders`, which is the
transcription of `CheckBuildConditions`; the validator is not weakened anywhere
and gains coverage of two buildings it had lost.
*Risk to the 72-cell corpus:* low. No corpus cell places 2208/2209 (3.7), and
change 2 is a no-op for every machine whose dock already sits outside its
collider (assert this with a catalogue-wide test). Change 3 touches
`strip_variants`, which every strip uses, so it needs the three-round audit.
*Deterministic tests:* a unit test that the emitted approach for a 2209 strip
has <= 3 in-collider tiles; a unit test that `stable_belt_collisions` is empty
for a synthetic 2209 + feed-lane placement; a `validate` test that a placement
with a 5-tile in-collider approach IS convicted (the exemption is gone); a
`_drainable_by_port` unit test with two same-item output lanes; the end-to-end
build of this URL with 0 errors on all six pairs.

### Option 2 -- Emitter-only: straight-in approach, leave the exemption alone

Do change 2 above and nothing else. Cheaper, and it fixes the *paste*. But
nothing in CI would ever catch a regression, because `validate` still skips
2209, and defect A stays refused. **Rejected**: it leaves the arbiter blind,
which is how this shipped in the first place.

### Option 3 -- Refuse rather than emit: forbid belt runs inside a belt-port host

Add a routing keep-out that forbids any belt inside a belt-port host's collider
except the three rescued tiles, enforced at route time by `_junction_belt_clear`'s
sibling. Correct and conservative, but a keep-out with no matching *approach*
rule makes the exchanger unroutable in tight strips and converts today's silent
collision into a refusal -- a better failure, not a fix. Worth adding as a
belt-and-braces assertion **after** Option 1, not instead of it.

**Recommendation: Option 1.** It is the only one that leaves the validator as
the arbiter, fixes both symptoms, and satisfies both acceptance criteria: this
URL's all-products blueprint pastes with zero collisions AND the
output-products candidate builds.

---

## 5. Acceptance criteria

1. `uv run flab2bp "$URL" --strategy freeform --candidate-policy output-products`
   builds, with `report.ok` and zero validator errors.
2. `uv run flab2bp "$URL" --verbose` reports **six** clean pairs and zero
   refusals.
3. `colliders.stable_belt_collisions` on every emitted placement for this URL is
   **empty**, with no `LOW_CONFIDENCE_FOOTPRINTS` filtering.
4. `scripts/audit.py --budget 30 --jobs 16`, three rounds against a fresh
   baseline, shows no regression under
   `scripts/audit_compare.py --regressions-only --expect-cells 72 --p95-seconds 31`.
