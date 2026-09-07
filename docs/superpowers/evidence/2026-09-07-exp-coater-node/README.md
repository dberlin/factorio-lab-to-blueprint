# EXPERIMENT: the Spray Coater as a real packable node — measured

Date: 2026-09-07. Branch `exp-coater-node`, cut from `master@332d34ca`, switches
committed at `c51d9a5e`.
**Status: MEASURED, not merged. This evidence is what is offered for merge; the
code switches stay on the branch.**

> "You should test making it a real packable machine or a separately placed
> coater node, and see what *actually* happens. It may be a horrible idea, but
> if so, the evidence you are making is a *really* weak case against it."

It is not a horrible idea, and the design's own recommendation is the arm that
loses. **The separately placed node (C) is a win: 72/72 clean in both rounds,
zero coater-merge findings against master's 5 and 9, at +2.7% area.** The
packed node (B) builds and is clean on everything it packs, but the packer runs
out of clock on the corpus's largest cell and it buys 50% more belt. The
design's seat fix (A) loses **24 of 72 cells**.

---

## 0. The four arms, three lines each

Selected by `FLAB2BP_COATER_NODE`, default `off`
(`src/flab2bp/layout/coater_mode.py`).

**`off` — master.** The addon rides the interior of the consumer strip's own
`_COATER_WEST_CHANNEL = 3` channel; `_coater_seats` offers `tiles[1:3]` and the
first candidate's 3x1 body covers the lane HEAD — the one cell of the lane a
router path can reach, so the cell every many-to-one merge lands on.

**`seat` — variant A, the design's fix (spec §5.1–§5.2).** Seats start at
`1 + half_span`, leaving one candidate at `ox - 1`; the body's own level and the
area-1 rival cell join `canvas.belt_ban`, which `_Canvas.free` already consults,
so a banned cell is a banned *goal* and `_merge_frontier` cannot offer one.

**`packed` — variant B, the coater as a real packed object.** One four-tile belt
run per sprayed input lane with the addon on its third tile, handed to CP-SAT as
its own 6x3 rectangle; three ports (item-in west, item-out east,
proliferator-in at the drop). The consumer's lane reverts to an ordinary
`WEST_CHANNEL = 1` lane with no addon and no keep-out.

**`placed` — variant C, the same node sited after the pack.** Identical node,
identical nets, identical ports; the site is a ring search on free ground beside
the consumer lane head instead of a CP-SAT rectangle, so the packer is untouched
and only the router sees the extra net.

---

## 1. The node, exactly

```
        n0            n1            n2            n3
   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
z=1│ approach │  │   DROP   │  │          │  │          │   ← proliferator-in
   ├──────────┤  ├──────────┤  ├──────────┤  ├──────────┤
z=0│  ITEM-IN │─▶│          │─▶│  ▣ SEAT  │─▶│ ITEM-OUT │
   └──────────┘  └──────────┘  └──────────┘  └──────────┘
        ▲         [ ────── 3x1 body, yaw 90 ────── ]    │
        │                                              ▼
   producer nets and external runs            one net to the consumer
   merge here, off the body                   strip's ordinary lane head
```

Four tiles is the minimum that gives the *ridden* belt a straight predecessor
and a straight successor while keeping both ports off the body:

* `rules.addon_ride_is_straight` and `game.addon_corner` read only the ridden
  belt's two neighbours (`GetBeltInputBeltPose` / `GetBeltOutputBeltPose`), so
  `n0` may be turned onto by a router path and `n3` may turn away — and both do,
  which is what makes the node routable at all;
* `slots.addon_supply_cell(SPRAY_COATER_ID, …, area=1)` at yaw 90 is one tile
  west of the seat and one level up, which is `n1` at `z = 1`; the permanent
  approach belt is one further west, which is `n0` at `z = 1`. **The node is
  self-contained: every cell the addon needs is inside its own footprint.**

The packed rectangle is 6x3 — the four tiles with one free cell on every side.
That ring is not padding: it is exactly what `_coater_keepout_hits` reserves (the
oriented 3x1 body plus one lateral cell), so a rectangle CP-SAT keeps clear is an
addon that clears every machine *by construction*. `placed` demands the same ring
from `canvas.free`, and that was not a free choice — see §5.2.

**Nothing about the game's rules is re-implemented for the node.** It is shaped
like a four-tile sprayed lane precisely so `_place_coaters` seats it with the
seat search, keepout, projected-static, addon-supply and splitter certification
it already runs for a strip channel. The only line that knows the difference is
the seat channel: `len(port.tiles) - 1` for a node instead of
`strip.west_channel`.

**No fake recipe was needed, and no rate-solve output moved.** The node is a
`Strip` with `coater_node=(consumer index, item)` set and `machines`
reinterpreted as its tile count; it never reaches `_emit_strip`, never appears in
`RateSolution.groups`, and `spec.spray_lanes`, `belt_required_edges` and the
proliferator external input are untouched. The user's point about `df-*` and
`orbital-collection-*` is conceded and turned out not to be needed: the layout
has its own object vocabulary and a rectangle in it costs no dataset fiction.

---

## 2. Verdict table

`--budget 30`, `scripts/audit.py --jobs 8` (eight cells at a time, sixteen CP-SAT
workers each). `audit.py` sizes workers as `cores // jobs`, so a run targets the
whole 128-core box whatever `--jobs` is: the parallelism trades workers-per-cell
against cells-in-flight and does not oversubscribe, which is why the ARMS still
run one after another and why every arm uses the same `--jobs`. CPU pressure
(five-second mean of runnable processes, `cpu_pressure.sh`) ran 3.6–31 through
the rounds, well under the 64 that would matter on this box.

`packed` is freeform-only — sequence-pair refuses a packed node before it packs
anything (§5.1) — so its cell count is 36, not 72.

**Round A**

| arm | cells | CLEAN | REFUSED | INVALID | CRASH | coater merges | coaters | route p50 | route p95 | rip-ups |
|---|---|---|---|---|---|---|---|---|---|---|
| `off` | 72 | **71** | 1 | 0 | 0 | **5** | 343 | 0.2 s | 6.5 s | 22 |
| `seat` | 72 | **48** | 24 | 0 | 0 | 0 | 85 | 0.1 s | 4.4 s | 24 |
| `packed` | 36 | **34** | 2 | 0 | 0 | 0 | 133 | 0.1 s | 5.6 s | 18 |
| `placed` | 72 | **72** | 0 | 0 | 0 | 0 | 428 | 0.1 s | 6.1 s | 24 |

**Round B**

| arm | cells | CLEAN | REFUSED | INVALID | CRASH | coater merges | coaters | route p50 | route p95 | rip-ups |
|---|---|---|---|---|---|---|---|---|---|---|
| `off` | 72 | **72** | 0 | 0 | 0 | **9** | 412 | 0.2 s | 5.9 s | 21 |
| `seat` | 72 | **48** | 24 | 0 | 0 | 0 | 85 | 0.1 s | 4.2 s | 21 |
| `packed` | 36 | **34** | 2 | 0 | 0 | 0 | 133 | 0.2 s | 4.5 s | 19 |
| `placed` | 72 | **72** | 0 | 0 | 0 | 0 | 428 | 0.1 s | 5.0 s | 22 |

Coater-merge findings and coater counts are totals over that arm's own cells;
routing seconds and rip-ups are over the seventeen cells clean in every arm.
`seat`'s coater count is low because two thirds of its proliferated cells refuse
and a refused cell places nothing.

**Proliferated cells only** (24 specs x 2 strategies = 48; `packed` 24):

| arm | round A | round B | coater-merge findings |
|---|---|---|---|
| `off` | 47/48 | 48/48 | 5 / 9 |
| `seat` | 24/48 | 24/48 | 0 / 0 |
| `packed` | 22/24 | 22/24 | 0 / 0 |
| `placed` | 48/48 | 48/48 | 0 / 0 |

### Area, and the rest of the cost

Geometric mean over the cells clean in BOTH that arm and `off` — a wider and
fairer set than the seventeen clean everywhere, which are dominated by easy
cells.

| arm | round A | round B | round B split |
|---|---|---|---|
| `seat` | +4.67% (n=48) | +3.97% (n=48) | 14 larger, 4 smaller |
| `packed` | +4.08% (n=34) | +4.85% (n=34) | 16 larger, 8 smaller |
| `placed` | +2.89% (n=71) | **+2.74%** (n=72) | 37 larger, 7 smaller |

Nets and belt tiles, over the **proliferated** cells clean in both that arm and
`off` — this is where the node's real price shows:

| arm | round | cells | nets | belt tiles |
|---|---|---|---|---|
| `placed` | A | 47 | 890 → 1257 (**+41.2%**) | 66 552 → 69 123 (+3.9%) |
| `placed` | B | 48 | 1027 → 1471 (**+43.2%**) | 80 682 → 81 778 (**+1.4%**) |
| `packed` | A | 22 | 313 → 433 (**+38.3%**) | 16 634 → 24 946 (**+50.0%**) |
| `packed` | B | 22 | 313 → 433 (**+38.3%**) | 16 516 → 24 963 (**+51.1%**) |

The net cost is the one the design predicted (§6.2: +55% input-side nets on
proliferated specs, +35% against all input lanes). Measured: **+38–43%**, and it
is the same for both node arms because it is the same node and the same nets.

**The belt cost is not the same, and the difference is the whole story of B
versus C.** See §5.3.

---

## 3. Movers, named

**`seat` — 23 cells lost in round A, 24 in round B, 0 gained. Identical set
both rounds bar one flake.**

Freeform (19 cells, every proliferated freeform cell but two):
`casimir-crystal/all-products`, `electromagnetic-matrix/all-products`,
`electromagnetic-matrix/output-products`, `energy-matrix/all-products`,
`energy-matrix/output-products`, `graphene/all-products`,
`graphene/output-products`, `information-matrix/all-products`,
`information-matrix/output-products`, `iron-ingot/all-products`,
`iron-ingot/output-products`, `magnetic-coil/all-products`,
`plastic/all-products`, `plastic/output-products`, `processor/all-products`,
`quantum-chip/all-products`, `super-magnetic-ring/all-products`,
`universe-matrix/all-products`, `universe-matrix/output-products`.

Sequence-pair (4 in round A, 5 in round B): `casimir-crystal/all-products`,
`information-matrix/all-products`, `quantum-chip/all-products`,
`universe-matrix/output-products`, and in round B also
`universe-matrix/all-products`.

**Why, exactly.** The refusal reads `prolif.sprayed_cargo_reaches_machines`
because that is the label `_Unseatable` is retained under
(`freeform.py:21136`), but the mechanism is the seat search, and with
`FLAB2BP_COATER_TRACE=1` it names itself:

```
UNSEATABLE the copper-ore coater at (2, 0, z=0) has a full-body keepout
           intersecting Arc Smelter at (3, 1, z=0)
```

With `west_channel = 3` the narrowed rule leaves exactly one candidate, `ox - 1`,
whose body is `{ox-2, ox-1, ox}` — and `ox` is the strip's own column 0, so the
body now reaches into the machine band and `_coater_keepout_hits` convicts it.
The seat the rule removes was the *only* one that cleared the machines.

This is the design's Risk 1, and the design's estimate of it was wrong by an
order of magnitude: it called the loss a thing that "must be counted, not
discovered" and expected the clearance lift to 4 to absorb it. Measured, it is
**half the corpus**. Raising `_COATER_WEST_CHANNEL` to 4 unconditionally
(the design's open question 3) is not a fallback for this — it is a
precondition, and it was never measured.

**`packed` — 2 cells lost, both rounds, both the same cells, both `universe-matrix`:**

* `freeform/universe-matrix/all-products` — *"the 30s deadline passed with no
  completed packing of **115 strips**"* (32 real strips plus 83 nodes);
* `freeform/universe-matrix/output-products` — *"no packing of **49 strips**
  could be wired at any candidate height"*.

Not a crash and not a validator rejection: the packer runs out of clock, and it
runs out of clock because the node arm hands it 3.6x the rectangles. The
design's §6.3 prediction (+233 packed objects corpus-wide, +42 on this cell) is
confirmed in exactly the shape the packer feels it.

**`placed` — 0 cells lost in either round; +1 gained in round A**
(`sequence-pair/universe-matrix/all-products`, which `off` refused in that round
and built in the next — i.e. a flake in `off`, not a real gain, and it is
reported as such).

---

## 4. The reported URL

`AMM_URL` from `docs/superpowers/plans/2026-09-06-self-loop-recipes.md`, three
candidate policies x two strategies, `--budget 30`. Identical in both rounds.

| arm | builds | coater bodies over a belt merge |
|---|---|---|
| `off` | 6 / 6 | **6** |
| `seat` | 4 / 6 | 0 |
| `placed` | **6 / 6** | **0** |
| `packed` | 2 / 3 (freeform only) | 0 |

Master reproduces the reported defect exactly, on the same building indices the
self-loop evidence named:

```
freeform/output-products:
  coater#768 @ (104, 4, 0)  belt#0  @ (103,  4, 0)  pred=[787, 1655]
  coater#771 @ (104,10, 0)  belt#19 @ (103, 10, 0)  pred=[799, 1106]
sequence-pair/output-products:
  coater#768 @ ( 50, 3, 0)  belt#0  @ ( 49,  3, 0)  pred=[785, 1612]
  coater#771 @ ( 50, 9, 0)  belt#19 @ ( 49,  9, 0)  pred=[796, 1789]
freeform/all-products:
  coater#763 @ ( 14,28, 0)  belt#0  @ ( 13, 28, 0)  pred=[1086, 2936]
  coater#766 @ ( 14,34, 0)  belt#19 @ ( 13, 34, 0)  pred=[1118, 3311]
```

— `belt#0`, `belt#19`, `coater#768` and `coater#771` are the very indices in
`docs/superpowers/evidence/2026-09-06-selfloop/README.md:250-272`. The two node
arms and the seat arm all take it to zero; only `placed` takes it to zero
*while still building every cell*.

`seat` refuses `all-products` on both strategies. `packed` refuses
`freeform/all-products` (*"no packing of 53 strips could be wired at any
candidate height"*).

---

## 5. What the build taught, with the file and line

### 5.1 B cannot reach sequence-pair without a second packer change

```
ValueError: physical strip plan contains unmatched compatibility strips
```

`sequence_solver._variant_search_inputs` (`sequence_solver.py:3695-3740`) walks
`generate_strip_families(spec)` and demands **one physical `Strip` per
`StripVariant` instance, in order**; a coater node has no family, no variant and
no pose, so the walk ends with strips left over and raises at `:3740` before
anything is packed. Carrying B into sequence-pair needs three things, and they
are all in that file:

1. `_variant_search_inputs` to pass node strips through with an empty variant
   table instead of counting them;
2. `_selected_strips` (`:3791`) and `_sequence_reservation_strips` (`:3744`) to
   leave them alone — the latter currently lifts any `REQUIRES_SPRAY` strip with
   a `physical_variant` to `_COATER_WEST_CHANNEL + 1`, which a node neither has
   nor wants;
3. the sequence-pair encoding to carry them as fixed-size boxes with no pose
   choice.

**C needs none of this**: it lives entirely inside the shared
`_prepare_routing_problem`, and it was clean on sequence-pair from the first run.

### 5.2 A post-pack node needs the packed node's whole free ring

The first `placed` implementation demanded only the four belt tiles and the two
level-1 cells. `information-matrix/all-products` then refused:

```
geom.collide; band 200 geom.collide (94, 1025); band 200 (607, 1067);
band 160 (717, 1076): build colliders intersect
```

— node belts standing against a machine, convicted by the spherical projection
at high bands. Requiring the full 6x3 ring fixed it and the same cell went CLEAN
at **area 4292 against `off`'s 4760**. The addon's collider, not the belts', is
what sets the node's footprint.

### 5.3 CP-SAT has no reason to put a node near the consumer it feeds

This is why B buys **+50% belt tiles** where C buys +1.4%.

`_pack_model`'s wirelength term is built from `_nets_between(strips)`
(`freeform.py:3979-3991`), which derives strip pairs from
`strip.out_lanes` → destination `group_key`. A coater node has
`out_lanes = ()` and its consumer is not reachable from it, so **a node
contributes zero HPWL terms**. Width is lexicographically above HPWL anyway
(`freeform.py:4658-4678`), so the packer fits each node wherever the width
objective is happiest and the router then pays for a long out-net.

To make B competitive one would have to put the node→consumer relation into
`_nets_between` (or a parallel term), which is a change to the pack objective
and not merely to the object model. **That is the specific missing piece, and
it is a smaller change than the sequence-pair one.**

### 5.4 The packer's object model *can* express a three-port belt object

Stated plainly because the design assumed otherwise and rejected Option C partly
on it. `_box(s)` already sizes an arbitrary rectangle
(`machines * pw + west_channel + tail + MARGIN`, `box_height + MARGIN`) and
`add_no_overlap_2d` already does the whole seating argument; `_Port` already
carries `z` (for a drop one level up) and `cargo_domain`. The three ports needed
no new type. The whole of B is one `Strip` field, one branch in the emission
loop, one net rewiring, and one line in `_place_coaters`.

The domain transition was the part that looked like a blocker and was not:
`_Net.__post_init__` refuses a net whose ports disagree about `CargoDomain`, but
a producer feeding a proliferated consumer **already** emits a `REQUIRES_SPRAY`
output lane, so the whole path is uniformly labelled and the coater is the
physical transition inside it. The node inherits the label at both ports.

The validator needed **no change at all**:
`prolif.sprayed_cargo_reaches_machines` asks its question over the belt graph
(`_unsprayed_belts` is forward reachability stopped at each ridden belt,
`validate.py:4920-5008`), not over lane geometry, so a coater on a separate run
that routes into the consumer lane is judged exactly as an inline one.

### 5.5 The `no-proliferator` controls PASS, and the harness had to be fixed to show it

The brief makes byte-identical controls a PASS condition for the harness. At
`--jobs 8` it *fails* — and so does master against itself:

> **Two runs of the SAME `off` arm, round A against round B, differ on 8 of 72
> cells**, two of them `no-proliferator` controls
> (`super-magnetic-ring`, `plastic`), and one cell
> (`sequence-pair/universe-matrix/all-products`) moves REFUSED → CLEAN.

CP-SAT with more than one worker under a wall-clock limit is not reproducible,
which `base.DEFAULT_SEARCH_WORKERS`'s own docstring says. An arm-versus-arm
digest comparison at that operating point measures the solver's variance, not
the switch — and the round-A and round-B "leaks" name the same two cells with
the arms shuffled between rounds, which is the signature of noise rather than a
leak.

Asked properly, at `base.DETERMINISTIC_WORKERS` (`--workers 1`,
`run_controls.sh`, `controls/controls.log`):

**11 of 12 control specs are byte-identical across all four arms on the first
attempt; the twelfth (`super-magnetic-ring`) disagreed once under `placed` and
then agreed with `off` on 3 of 3 repeats, and on a further round of all four
arms x 3 — 12 of 12 identical digests. Controls: PASS.**

That is also what the code says: on a spec with no `REQUIRES_SPRAY` strip, every
switch site is behind a `cargo_domain is REQUIRES_SPRAY` guard, so all four arms
execute the same instructions.

### 5.6 An audit that writes its JSONL only at the end can lose an hour

The first serial `seat` run died of `SIGSEGV` at cell 13 of 72 and took twelve
completed cells with it, because `scripts/audit.py` appends `_JSONL` in `main`
after the loop. The runners here chunk by URL and skip URLs already recorded, so
a native crash costs one URL and a re-run finishes the arm. Worth fixing in
`audit.py` itself if this pattern recurs.

---

## 6. Verdict against the brief's kill criteria

> B is a WIN if it is CLEAN on at least as many cells as master and A, with zero
> coater-merge findings, at any area cost.
> B is a LOSS if it loses clean cells that A keeps, or crashes the packer.

**B (`packed`) is neither, and is reported as measured.** It has zero
coater-merge findings and it is clean on 34 of the 36 freeform cells. It does
**not** crash the packer. It loses two cells master keeps —
`freeform/universe-matrix/{all,output}-products` — and it does **not** lose a
cell A keeps: A loses both of those too, and seventeen more besides. So B beats
A decisively and loses to master by two cells, at +4.9% area and +50% belt.
Its two failures share one cause (the packer's clock against 115 rectangles) and
one fix that is *not* the object model (§5.3).

**A (`seat`) is a clear LOSS**: 48/72 in both rounds, 24 named cells, zero
gained, and the mechanism is a seat rule that removes the only candidate that
clears the machine band.

**C (`placed`) is a WIN on every clause of B's criterion** — clean on at least
as many cells as master (72/72 vs 71 and 72) and as A (72 vs 48), zero
coater-merge findings against master's 5 and 9, on both strategies, at +2.74%
area and +1.4% belt tiles. It builds the reported URL 6/6 with zero merges where
master builds it 6/6 with six.

## 7. Recommendation

**Ship variant C — the separately placed coater node — and do not ship the
design's seat fix.**

The number that drives it: **`placed` is 72/72 with zero coater bodies over a
belt merge; `off` is 71–72/72 with 5 and 9; `seat` is 48/72.** The price is
+2.74% area and +1.4% belt tiles, which the "density may be paid for
correctness" ruling covers many times over.

Two things follow from that and should be decided rather than assumed:

1. **C makes the defect structural, not checked.** The merge cell is the node's
   in-port, one tile west of the body, by construction and not by a seat index —
   so `prolif.coater_rides_one_run` becomes a regression test rather than the
   fix, which is what the design wanted from A and did not get.
2. **B is worth one more measurement, not a rewrite.** Its only real cost is
   §5.3: the node contributes no HPWL term, so CP-SAT scatters the nodes. Adding
   the node→consumer pair to `_nets_between` is a small change with a specific
   prediction (belt tiles falling from +50% toward C's +1.4%), and if it also
   clears `universe-matrix` then B beats C on area (+4.9% is measured against
   `off` on a 34-cell set that excludes exactly the cells B refuses, so the two
   are not directly comparable until B is clean on the same set). The
   sequence-pair work in §5.1 should not be started before that measurement.

---

## 8. Reproducing

```
git checkout exp-coater-node
cd docs/superpowers/evidence/2026-09-07-exp-coater-node
./run_round.sh roundA          # every arm, 72 cells, --budget 30 --jobs 8
./run_round.sh roundB          # the second round, for flake detection
./run_controls.sh              # the harness's own PASS condition, --workers 1
uv run python analyse.py roundB/*.jsonl
```

`FLAB2BP_COATER_TRACE=1` prints every `_Unseatable` message to stderr, which is
how §3's seat-refusal mechanism was named; the sweep otherwise swallows them and
reports only the check name.

Files: `roundA/`, `roundB/` (per-arm JSONL, audit log, reported-URL log),
`controls/controls.log`, `serial-partial-jobs1/` (the first, abandoned
`--jobs 1` attempt: `off` at 72/72 with 128 workers per cell, and the `seat`
SIGSEGV of §5.6), `probes/probe_cell.py`, `analyse.py`, `cpu_pressure.sh`.
