# Cut pressure: corridors in front of the packer, ordering in front of the router

Branch `exp-pressure` at master `4b51f81f`. Source switch commit
`feat(layout): default-off pressure-aware corridors and net order`; this
directory is the evidence for it.

The question: does making placement and routing aware of **cut pressure** — the
register-pressure analog, the number of belts that must cross a horizontal band
of the layout — turn refusals into layouts or cut routing time, at bounded area
cost?

**Short answer.** Arm B (router order) is the arm worth having: it cuts
`route_all` by 17–63 % on five of eight large cells and rip-up rounds from 21 to
12 and from 9 to 5, at **zero area cost**, and a reversed-order control shows
the ordering is carrying real information rather than shuffling. Arm A (packer
corridors) is not: it rescues no cell, is inert on the two cells whose pressure
never crosses the frozen floor, and its area effect is dominated by which
candidate height the sweep happens to land on — ±33 %, unsigned. Neither arm
turns a refusal into a layout, though A does move `belt3/no-proliferator` from a
**routing** refusal to a **belt-capacity** refusal, which is progress in kind
and a dead end in fact.

---

## 1. What the pipeline does today, before either switch

Two things had to be established before the arms meant anything.

**The vertical gap between strips is one row, uniform, and a constant.**
`_box` (`src/flab2bp/layout/freeform.py:1744`) is the single point of truth for
how much ground a strip costs — the height sweep, the greedy shelf seed and the
CP-SAT model all size a strip through it — and it returned
`(width + west_channel + tail_extension + MARGIN, height + MARGIN)` with
`MARGIN = 1` (`freeform.py:175`). Not a function of ports, of lanes, or of
anything else. `_greedy_pack` adds a further `route_clearance` of 0 or 1, again
uniform.

**And a uniform second row was already tried and is already known to be bad.**
The comment at `freeform.py:217-229` records it: widening the south corridor to
two rows measured **59/72 clean at 4 s against 60/72**, because a row costs
height on every strip, the canvas grows, A\* slows and the sweep reaches fewer
candidate heights inside the same deadline. Arm A is therefore not "try a wider
corridor" — that experiment is done. Arm A is the strictly narrower claim that
the row is worth buying **exactly where the pressure is, and nowhere else**.

**The packer does not order strips by depth, and there are no physical bands.**
`_pack_model` places strips as free rectangles under `add_no_overlap_2d`
(`freeform.py:4396`); x and y are independent integer variables bounded only by
the outline. Nothing in the model, the objective or the seed mentions depth. So
"the corridor rows between strip bands" **do not exist** in the freeform packer:
a cut is a fact about the recipe DAG, not about a row of the canvas. This is the
single most important thing this experiment found and it shapes everything
below — including why arm A had to be expressed per-strip rather than per-band,
and why question (d) cannot be answered by attributing A\* time to a row.

Ordering bands by depth was therefore *not* tried: it is not a tweak to a
band-ordered packer, it is the introduction of a band-ordered packer, which is a
different and much larger change than this spike. Said plainly rather than
skipped.

---

## 2. The two switches, with file:line

Both live in the new `src/flab2bp/layout/pressure.py`, whose cut definitions are
copied from `2026-09-06-exp-features/routing_features.py` (experiment 5) so the
evidence module and the shipped one cannot disagree about what a cut is. That
module is also copied into this directory unchanged, as `routing_features.py`.

### Arm A — `FLAB2BP_PRESSURE_CORRIDORS=1` (packer side)

| Where | What |
| --- | --- |
| `pressure.py:84-86` | `corridors_enabled()`, `@cache`d — read once per process |
| `pressure.py:295-301` | `extra_corridor_rows(p)`: `0` at or below the floor, else `ceil((p-floor)/per_row)` capped |
| `pressure.py:303-323` | `strip_corridor_rows`: a strip at depth *d* is charged for `max(lane_pressure[d-1], lane_pressure[d])` — the two bands that run along its own faces |
| `freeform.py:2694-2716` | `_apply_pressure_corridors`, called from the tail of `plan_strips` (`freeform.py:2691`) |
| `freeform.py:953` | `Strip.south_channel: int = 0` |
| `freeform.py:1744-1747` | `_box` adds it: `height + MARGIN + south_channel` |

It is applied **on the finished strip plan**, which is the last point every
downstream consumer shares. That is deliberate and it is the lesson from
`2026-09-06-exp-trunk`: that spike staked its corridor in
`_prepare_routing_problem`, after packing and *before* the second
`_reserve_port_access`, took its segment from the same `route_bounds` ring the
proliferator trunk had already staked, and broke five cells by eating the only
free neighbour of a `proliferator-3` tap. A row bought in `plan_strips` is a row
`add_no_overlap_2d` keeps free. Nothing is reserved after packing.

**Frozen tuning: floor 12, one row per 8 lanes above it, cap 1**
(`pressure.py:54-60`), overridable for reproduction through
`FLAB2BP_PRESSURE_{FLOOR,PER_ROW,MAX_ROWS}` (`pressure.py:64-81`). Tuned on
`um120` alone and then frozen; see §3. At the frozen floor the cap binds before
the slope does on every cell in this corpus, so the rule reduces to *one extra
row for a strip whose busiest adjacent cut carries more than 12 lanes* — stated
plainly rather than dressed up as a slope that never fires.

### Arm B — `FLAB2BP_PRESSURE_ORDER=1` (router side)

| Where | What |
| --- | --- |
| `pressure.py:90-92` | `order_enabled()`, `@cache`d |
| `pressure.py:325-361` | `net_pressures`: peak lane pressure over the cuts between a net's source depth and its sink depth |
| `pressure.py:363-372` | `family_pressure`: every member of a shared-source family takes the family maximum |
| `freeform.py:9213-9233` | `_net_cut_pressure`, returning `None` — not zeros — when the switch is off |
| `freeform.py:17646` | the one call site, in `_build_prepared` |
| `freeform.py:11096-11104` | `family_pressure`, all zeros when the caller passed `None` |
| `freeform.py:11131` | the key term: `-family_pressure[i]`, after the priority and proliferator terms and before source-family size |

The rip-up machinery is untouched. The **family** maximum rather than the net's
own is what enters the key, because splitting a shared-source family apart would
cost the first branch its siblings' merge frontier — a correctness property of
`_route_all`, not an ordering preference — and a per-net score would do exactly
that whenever two branches of one family reach different depths.

`tests/layout/test_pressure.py` pins the defaults at all three places the
switches reach (packed box, strip plan, net-order key), plus the cut semantics
and the family rule. `ruff check` 0, `ruff format` 0, `mypy src` 0,
`tests/layout/test_{freeform,strip_variants,compact_seed,pressure}.py` green.
`scripts/route_profile.py`'s `_route_all` shim gained the new keyword so the
profiling harness still measures the run the pipeline makes.

---

## 3. Tuning arm A, on one cell

`um120`, freeform, budget 30, one run per setting, two `off` runs as the
reference (`tune/`, and `um120-off*.json` beside them):

| floor / per row / cap | verdict | wall s | area | `route_all` s | rounds | expansions |
| --- | --- | --- | --- | --- | --- | --- |
| off | OK | 29.53 / 29.58 | 80442 | 6.70 / 6.71 | 3 | 7 390 306 |
| 4 / 4 / 3 | OK | 26.66 | 84250 | 5.36 | 2 | 6 847 605 |
| 8 / 6 / 2 | OK | 19.15 | 88033 | 5.21 | 2 | 6 549 830 |
| **12 / 8 / 1** | OK | **19.74** | **85657** | **5.21** | **2** | 5 768 633 |
| 15 / 8 / 1 | OK | 19.51 | 85657 | 5.11 | 2 | 5 730 928 |

Every setting beat `off` on wall and rounds on this cell, and the aggressive
`4/4/3` setting bought 239 rows against `12/8/1`'s 75 for no further gain. The
two `off` runs are identical to 0.05 s, so the spread across settings is real on
this cell even though §5 shows it does not survive to other cells. `12/8/1` was
frozen and every number below uses it.

**What the frozen rule costs, before any layout runs** (`arm-a-cost.json`,
`pressure_report.py`): "rows" is the total extra reserved rows over all strips,
"+area" is those rows as a fraction of the packed strip-box area.

| cell | depth | max lane pressure | lane pressure by cut | strips widened | rows | +box area |
| --- | --- | --- | --- | --- | --- | --- |
| um60 | 8 | 17 | 13 16 17 13 10 8 7 6 | 50/57 | 50 | 9.47 % |
| um120 | 8 | 20 | 17 20 19 15 11 8 7 6 | 75/87 | 75 | 9.38 % |
| gm200 | 7 | 15 | 15 15 11 9 6 3 2 | 50/73 | 50 | 7.37 % |
| qc180 | 4 | 12 | 12 8 3 2 | **0/45** | 0 | 0.00 % |
| belt3 all-products | 5 | 11 | 9 11 9 7 3 | **0/52** | 0 | 0.00 % |
| belt3 no-proliferator | 5 | 15 | 12 15 11 7 3 | 26/90 | 26 | 4.13 % |
| mall | 5 | 20 | 13 19 20 14 11 | 91/95 | 91 | 11.71 % |
| zurl2 | 5 | 24 | 19 24 18 14 8 | 83/85 | 83 | 11.74 % |

Arm A is **structurally inert on `qc180` and `belt3/all-products`** — their peak
pressure never exceeds the floor — so wherever those two cells move under A in
§4, that movement is measurement noise with a known cause, and it is a useful
zero-point for reading the rest.

---

## 4. The grid

`prof_harness.py`, freeform, single process, two replicates per (cell, arm),
at most two layouts running at once, `uptime` recorded beside every run
(`results-large.jsonl` carries `load_before`/`load_after`; `analysis.txt` prints
the 1-minute figure in its last column, 2.7–8.6 throughout). Budget 30 s for
`um60`/`um120`/`gm200`/`qc180`, 60 s for `belt3` (both policies), `mall`,
`zurl2`. Per-run JSON and log in `runs-large/`. `analysis.txt` is authoritative;
this table is the median-of-two summary it prints.

Deltas are against that cell's own `off`.

| cell | arm | verdict | wall s | Δwall | area | Δarea | belt tiles | Δbelt | `route_all` s | Δrt | rounds | expansions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| um60 | off | OK | 24.79 | | 31898 | | 11238 | | 5.28 | | 4 | 5.35 M |
| | A | OK | 27.81 | +12.2 % | 28795 | −9.7 % | 12658 | +12.6 % | 6.37 | +20.7 % | 5 | 6.18 M |
| | B | OK | 24.47 | −1.3 % | 31898 | 0 | 11170 | −0.6 % | 6.64 | +25.8 % | 5 | 7.52 M |
| | AB | OK | 27.56 | +11.2 % | 33534 | +5.1 % | 12325 | +9.7 % | 8.64 | +63.7 % | 6.5 | 7.73 M |
| um120 | off | OK | 30.43 | | 80442 | | 21899 | | 6.91 | | 3 | 7.39 M |
| | A | OK | 18.90 | **−37.9 %** | 85657 | +6.5 % | 20940 | −4.4 % | 4.84 | −30.0 % | 2 | 5.77 M |
| | B | OK | 24.91 | −18.1 % | 80469 | +0.03 % | 20477 | −6.5 % | 5.75 | −16.8 % | 2.5 | 6.30 M |
| | AB | OK | 20.98 | −31.0 % | 85657 | +6.5 % | 20992 | −4.1 % | 5.58 | −19.2 % | 2 | 5.69 M |
| gm200 | off | OK | 23.75 | | 48640 | | 12455 | | 7.80 | | 5 | 6.44 M |
| | A | OK | 26.84 | +13.0 % | 32718 | **−32.7 %** | 9335 | −25.1 % | 6.58 | −15.6 % | 6 | 7.30 M |
| | B | OK | 23.13 | −2.6 % | 48640 | 0 | 12465 | +0.1 % | 7.40 | −5.2 % | 5 | 6.77 M |
| | AB | OK | 26.74 | +12.6 % | 32718 | **−32.7 %** | 9329 | −25.1 % | 6.54 | −16.1 % | 6 | 7.31 M |
| qc180 | off | OK | 22.84 | | 14896 | | 4902 | | 5.13 | | 9 | 6.06 M |
| | A | OK | 21.77 | −4.7 % | 14896 | 0 | 4902 | 0 | 5.03 | −1.9 % | 9 | 6.06 M |
| | B | OK | 16.66 | **−27.0 %** | 14820 | −0.5 % | 4933 | +0.6 % | 1.91 | **−62.8 %** | **5** | 3.23 M |
| | AB | OK | 16.68 | −27.0 % | 14820 | −0.5 % | 4933 | +0.6 % | 1.93 | −62.3 % | 5 | 3.23 M |
| belt3 all | off | OK | 43.17 | | 15207 | | 6618 | | 16.32 | | 21 | 20.0 M |
| | A | OK | 42.76 | −1.0 % | 15207 | 0 | 6618 | 0 | 16.14 | −1.1 % | 21 | 20.0 M |
| | B | OK | 36.07 | **−16.5 %** | 15207 | 0 | 6691 | +1.1 % | 10.64 | **−34.8 %** | **12** | 14.9 M |
| | AB | OK | 36.51 | −15.4 % | 15207 | 0 | 6691 | +1.1 % | 10.44 | −36.0 % | 12 | 14.9 M |
| belt3 no-prolif | off | REFUSED *packer* | 37.34 | | — | | — | | 18.33 | | 20 | 29.8 M |
| | A | REFUSED *validator* | 44.39 | +18.9 % | — | | — | | 21.54 | +17.5 % | 16 | 29.2 M |
| | B | REFUSED *packer* | 38.75 | +3.8 % | — | | — | | 21.65 | +18.1 % | 18 | 28.5 M |
| | AB | REFUSED *validator* | 47.23 | +26.5 % | — | | — | | 24.14 | +31.7 % | 18 | 29.8 M |
| mall | off | REFUSED *packer* | 37.73 | | — | | — | | 18.44 | | 2 | 16.5 M |
| | A | REFUSED *packer* | 50.94 | +35.0 % | — | | — | | 30.45 | +65.1 % | 4 | 17.8 M |
| | B | REFUSED *packer* | 29.79 | −21.1 % | — | | — | | 10.26 | **−44.4 %** | 2 | 15.5 M |
| | AB | REFUSED *packer* | 41.70 | +10.5 % | — | | — | | 22.51 | +22.0 % | 4 | 16.3 M |
| zurl2 | off | REFUSED *validator* | 56.60 | | — | | — | | 18.67 | | 5 | 23.5 M |
| | A | REFUSED *validator* | 56.78 | +0.3 % | — | | — | | 19.19 | +2.8 % | 5 | 21.2 M |
| | B | REFUSED *validator* | 55.68 | −1.6 % | — | | — | | 15.38 | −17.6 % | 4 | 19.6 M |
| | AB | REFUSED *validator* | 56.25 | −0.6 % | — | | — | | 18.78 | +0.6 % | 5 | 21.2 M |

Replicate spread is tight everywhere except `um120` under B, where the two runs
landed 31.0 s / 3 rounds and 18.8 s / 2 rounds — the same bimodality the
tuning table's `off` pair does *not* show, and the reason `um120` is the one
cell whose B numbers should not be leaned on.

### Refusal reasons, in the pipeline's own words

* **`mall`, all four arms**: *"no packing of 46 strips could be wired at any
  candidate height; every pack the sweep produced left nets unrouted. That is a
  PACKER defect."* Identical string in every arm. Packing succeeds, routing
  fails, and neither a wider corridor nor a better net order changes that.
* **`zurl2`, all four arms**: validator, `flow.conservation` on `magnetic-coil`
  (76 machines want 6404/125 items/s, 132536/2625 can reach them) plus
  `flow.belt_capacity` — *"belt run 94 must carry 35222/875 items/s but its tier
  sustains only 30"*. 40.25 against 30 is a physics refusal; no placement arm
  can touch it.
* **`belt3/no-proliferator`**: this is the one that moves. `off` and `B` refuse
  with the **packer-defect** string (26 strips, nets left unrouted). `A` and
  `AB` get past routing entirely and refuse at the **validator**, with
  `flow.belt_capacity`: *"belt run 67 must carry 42 items/s but its tier
  sustains only 30"* (iron-ingot) and *"belt run 74 must carry 45 items/s"*
  (magnet). The corridor did what it was supposed to do — the router wired a
  pack it could not wire before — and the cell is unbuildable for a reason that
  has nothing to do with corridors.

---

## 5. Corpus sanity: the eight highest-pressure corpus cells, off vs A+B

The eight corpus cells with the largest `max_lane_pressure` in
`2026-09-06-exp-features/features.jsonl`: `universe-matrix` and `quantum-chip`
at all three policies, `information-matrix` at the two that tie at 8. Freeform,
30 s, one run per side (`results-corpus.jsonl`, `runs-corpus/`).

| cell | max lane pressure | off → A+B verdict | Δarea | Δ`route_all` | rounds off → A+B |
| --- | --- | --- | --- | --- | --- |
| universe-matrix / all-products | 18 | OK → OK | 0 | +5.8 % | 4 → 4 |
| universe-matrix / output-products | 18 | OK → OK | −4.7 % | +5.2 % | 8 → 8 |
| universe-matrix / no-proliferator | 17 | OK → OK | +7.6 % | +48.6 % | 5 → 7 |
| quantum-chip / all-products | 11 | OK → OK | 0 | +17.6 % | 14 → 16 |
| quantum-chip / output-products | 11 | OK → OK | 0 | **−44.4 %** | 26 → 14 |
| quantum-chip / no-proliferator | 10 | OK → OK | 0 | +63.5 % | 7 → 14 |
| information-matrix / all-products | 8 | OK → OK | 0 | −1.4 % | 15 → 12 |
| information-matrix / output-products | 8 | OK → OK | +0.7 % | **−42.1 %** | 25 → 17 |

**No verdict regressions: eight OK, eight OK.** Area identical on five, −4.7 %
on one, +0.7 % and +7.6 % on the other two. `route_all` moves in both
directions by large factors with no pattern the pressure column explains, on
one run per side. Arm A is inert on five of these eight (pressure ≤ 12), so
those five are pure B — and pure B on them is +17.6 %, −44.4 %, +63.5 %, −1.4 %,
−42.1 %. On small cells with few nets per band, B is a coin flip.

---

## 6. Is "pressure is hard" visible within one spec?

A\* time cannot be attributed to a band, because §1: the freeform pack has no
bands. What *can* be done is to run arm B's exact machinery with its ordering
**reversed** — lowest pressure first — by negating `family_pressure` in a
monkeypatch (`reverse_order.py`), leaving the key, the family grouping, the
proliferator rule and everything else bit-for-bit identical. If cut pressure
orders these nets in a way the search cares about, B and its reverse separate;
if it does not, they measure the same.

| cell | arm | wall s | `route_all` s | rip-up rounds | expansions |
| --- | --- | --- | --- | --- | --- |
| belt3 all-products | off | 43.17 | 16.32 | 21 | 20.0 M |
| | **B (high pressure first)** | 39.90 | **11.19** | **12** | 14.9 M |
| | B reversed (low first) | 47.50 | 16.77 | 20 | 18.2 M |
| qc180 | off | 22.84 | 5.13 | 9 | 6.06 M |
| | **B** | 17.51 | **1.93** | **5** | 3.23 M |
| | B reversed | 16.80 | 3.44 | 7 | 4.24 M |
| um120 | off | 30.43 | 6.91 | 3 | 7.39 M |
| | B | 31.71 | 7.20 | 3 | 7.22 M |
| | B reversed | 19.03 | 4.75 | 2 | 5.39 M |

**On `belt3` the signal is unambiguous**: reversed lands on `off` (20 rounds vs
21, 16.77 s vs 16.32 s) while B halves the rounds. Routing the high-pressure
nets last is exactly as good as not knowing about pressure at all; routing them
first is worth 9 rip-up rounds. **On `qc180` the ordering carries information in
both directions** — B 5 rounds, reversed 7, off 9 — so even the reversed
ordering beats the incumbent key, which says part of qc180's gain is "any
consistent global reordering" rather than pressure specifically, and part of it
(5 vs 7) is pressure. **On `um120` there is no signal**: reversed beats B, and
that is the cell whose two B replicates already disagreed by 12 s. The
within-spec claim holds where a cell has many nets crossing a genuinely busy
band and fails where it does not.

---

## 7. Answers

**(a) Does either arm rescue a freeform refusal (mall, belt3/no-proliferator,
zurl2)?** No. All three still refuse under every arm. `mall` returns the
identical packer-defect string in all four arms; `zurl2` returns the identical
validator findings (`flow.conservation` on magnetic-coil, `flow.belt_capacity`
at 40.25 items/s against a 30 tier). The one real movement is
`belt3/no-proliferator`, where arm A converts a **routing** refusal into a
**validator** refusal: the router wires a pack it could not wire before, and the
result is then rejected for belt capacity (iron-ingot 42/s, magnet 45/s, tier
30/s) — a demand no corridor can carry. Arm A cleared the obstacle it was aimed
at and found a different one behind it.

**(b) Does B cut `route_all` or rip-up rounds?** Yes, on most cells and
substantially on some: `qc180` `route_all` −62.8 % and rounds 9 → 5;
`belt3/all-products` −34.8 % and 21 → 12; `mall` −44.4 %; `zurl2` −17.6 % and
5 → 4; `um120` −16.8 %; `gm200` −5.2 %. It costs on two: `um60` +25.8 % (rounds
4 → 5) and `belt3/no-proliferator` +18.1 %. Area is untouched — identical on
five of six OK cells, −0.5 % on `qc180`. The reversed-order control (§6) says
the `belt3` gain is pressure and not shuffling.

**(c) What does A cost in area, and does the extra corridor get used?** The
reservation itself costs 7.4–11.7 % of packed strip-box area on the cells where
it fires and nothing at all on `qc180` and `belt3/all-products`. **The realized
area does not follow it**: `gm200` −32.7 %, `um60` −9.7 %, `um120` +6.5 %,
`qc180`/`belt3` 0. Taller boxes change which candidate height the sweep lands
on, and that effect is several times the reservation and unsigned — the −32.7 %
on `gm200` is a better landing, not a smaller corridor. As for use: belt tiles
move −25.1 % (`gm200`), −4.4 % (`um120`), +12.6 % (`um60`) — never in proportion
to the 50–75 reserved rows, and mostly in the wrong direction. **There is no
evidence the extra corridor is being used as a corridor.** Tile-level
attribution of belts to the reserved rows was not instrumented (see caveats), so
this is inference from the aggregate, but the aggregate does not support the
mechanism.

**(d) Is "pressure is hard" visible within a spec?** Partly, and only where the
spec is big enough for a band to be crowded. Per-cut A\* attribution is not
available — the freeform packer has no bands (§1) — so the reversed-order
control stands in for it. On `belt3` the answer is a clean yes: reversed = off
(20 vs 21 rounds), B = half (12). On `qc180` it is a qualified yes: B 5 rounds,
reversed 7, off 9 — pressure explains the 7 → 5, and *any* consistent
reordering explains the 9 → 7. On `um120` it is no, on a cell that is bimodal
across replicates anyway.

**(e) Recommendation.** **Send arm B to a gated batch; drop arm A.** B is free
in area, is a two-line change to a sort key with the rip-up machinery untouched,
wins large on the two slowest OK cells in the set and on the corpus introduces
no verdict regressions, and its reversed control shows the ordering is real. It
should go to the gate **default-off behind the env switch**, because two cells
(`um60`, `belt3/no-proliferator`) get slower and the eight-cell corpus sample
splits its `route_all` deltas evenly — a three-round gate over all 72 cells is
exactly the instrument needed to decide whether the default flips, and this
eight-cell sample is not. Arm A should not go to a gate: it rescues nothing,
its area effect is sweep-landing noise of larger magnitude than the thing it
buys, it is inert on the cells whose pressure sits under the floor, and it costs
+35 % wall on `mall` for that. Keep both switches in the tree default-off; keep
A as the recorded negative result rather than deleting it, since it is the only
thing that has ever moved `belt3/no-proliferator` off its packer defect.

---

## 8. Caveats

* **Two replicates**, and on refusing cells no area or belt-tile numbers exist
  at all, so those rows compare wall and router counters only. `um120` under B
  is visibly bimodal (31.0 s / 3 rounds vs 18.8 s / 2 rounds); treat its B row
  as one sample, not two.
* **The corpus sanity is one run per side over eight cells**, chosen by
  `max_lane_pressure` and therefore not a random sample, and `off` vs `A+B`
  only — it cannot separate the arms. It is a no-regression check, not a gate.
  `scripts/audit.py` was not run.
* **Arm A is structurally inert** on `qc180`, `belt3/all-products` and five of
  the eight corpus cells at the frozen floor of 12. Their A rows are a
  measurement zero-point, not evidence that A is harmless.
* **`LANES_PER_EXTRA_ROW` never fires** at the frozen floor on this corpus: the
  cap of 1 binds first everywhere. The tuned "slope" is really a threshold.
* **No tile-level attribution of belts to the reserved rows.** Question (c) is
  answered from packed-box arithmetic, realized area and total belt tiles, not
  from counting belts inside the widened bands. A stronger answer needs the
  emitted placement inspected against each strip's box, which was not built.
* **The reversed-order control is a monkeypatch in an evidence script**
  (`reverse_order.py`), not a switch in `src`; it asserts that `freeform`
  resolves `family_pressure` through the module object, so the patch cannot
  silently measure arm B twice.
* **Ordering bands by depth was not tried**, because the freeform packer has no
  bands to order (§1). Whether a band-ordered packer would make cut pressure a
  physical quantity rather than a DAG statistic is open, and is a much larger
  change than either arm here.
* **One other experiment shared the box.** At most two layouts ran at once; the
  1-minute load beside every run was 2.7–8.6 and is carried in
  `results-*.jsonl` and printed in `analysis.txt`.

## 9. Files

| File | What |
| --- | --- |
| `run_arms.py` | Drives `prof_harness.py` over the four arms, two at a time, recording load |
| `pressure_report.py` | What arm A buys per cell with no layout run → `arm-a-cost.json` |
| `reverse_order.py` | Arm B and arm B with its ordering reversed, for §6 |
| `analyze.py` | `results-*.jsonl` → `analysis.txt` (authoritative; the README quotes it) |
| `routing_features.py` | Experiment 5's feature module, copied unchanged, as the definition of record |
| `results-large.jsonl`, `runs-large/` | 64 runs: 8 cells x 4 arms x 2 reps |
| `results-corpus.jsonl`, `runs-corpus/` | 16 runs: 8 corpus cells x {off, A+B} |
| `tune/` | The arm-A tuning sweep on `um120` (§3) |
| `rev/` | The reversed-order control runs (§6) |
| `arm-a-cost.json`, `analysis.txt` | Derived tables |
