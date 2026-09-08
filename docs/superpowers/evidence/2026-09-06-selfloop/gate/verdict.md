# Task 10 gate — measured verdict

Branch `selfloop` @ `3780840ca3985ac5299dfba0cacf305cb2f2a6f4`
vs master `0d88d247a5916b341926a6cf043536fcf2412d24`.
Every number below is measured on this box on 2026-09-07. Nothing is predicted,
estimated, or rounded toward a better answer.

CPU pressure is the five-second mean of runnable processes
(`vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`), never load average.
128 cores; below 64 is fine.

## Step verdicts

| step | what | verdict |
|---|---|---|
| 1 | reported AMM URL builds, no mixed lane, no coater merge, prime declared | **PASS** (condition 3 vacuous — see below) |
| 1a | `universe-matrix` builds CLEAN with six single-item lanes | **FAIL** (expected; ruling T3-B) |
| 2 | `reforming-refine` self-loop seed | **PASS** |
| 4 | candidate corpus round | ran, 72/72 cells, 66 CLEAN / 6 REFUSED |
| 5 | compare | `audit_compare` **FAIL** (verbatim below) |
| 6 | README `## Gate result` | appended |

## Step 1 — the reported URL

Command (from the worktree):

```
/usr/bin/time -v uv run flab2bp "<AMM-URL>" --budget 30 -v -o gate/bp-amm-after.txt
```

`cpu_pressure` before **6.4**, after **5.4**. Wall **2:31.21**, CPU **345%**, exit **0**.

| check | required | measured | verdict |
|---|---|---|---|
| 1 | `errors 0` for the winning cell | `no-proliferator sequence-pair 2760 0` | PASS |
| 2 | no `SHARED-INPUT-RUN` in the decode | `grep -c SHARED-INPUT-RUN decode-amm-after.txt` → **0** | PASS |
| 3 | no `MERGE POINT` under a coater body; one RUN per addon area 1 | `grep -c "MERGE POINT" coater-amm-after.txt` → **0**; the decode's `== spray coaters ==` section is **empty** | PASS, but **vacuous** |
| 4 | CLI line `prime once (self-loop): hydrogen 8 items` | present, verbatim below | PASS |

```
prime once (self-loop): hydrogen 8 items onto the marked belt at (23,19) -- x-ray-cracking consumes what it produces, so the block will not start until the loop has items in it
```

**Condition 3 is vacuous and must be read as such.** The winning candidate on
this branch is `no-proliferator`, which places **zero Spray Coaters**, so there
is no coater in the shipped artefact for the check to bite on. The check that
did bite is upstream: three of the four refused strategy/candidate pairs name
`prolif.coater_rides_one_run` in their refusal, e.g.

```
prolif.coater_rides_one_run (808, 0, 1, 2): coater 808 rides a belt merge under its body:
belt(s) [0] on its body tiles have two or more predecessors; a coater carries no connection
of its own and needs one lane, not a merge whose joined flows have no arrangement that keeps
its recipe's proportion ({'ride': 1, 'merged_belts': [0], 'distinct_runs': [0]})
```

### The same URL on master, at the same commit as the corpus baseline

Built for an apples-to-apples comparison (`build-amm-master.log`,
`bp-amm-master.txt`). `cpu_pressure` before **8.8**, after **11**. Wall
**2:18.73**, CPU **367%**, exit **0**.

| | master `0d88d247` | branch `3780840c` |
|---|---|---|
| winner | `sequence-pair / output-products`, 2652 tiles, 0 errors | `sequence-pair / no-proliferator`, **2760 tiles**, 0 errors |
| strategy/candidate pairs that built | **6 of 6**, all `errors 0` | **2 of 6** (`no-proliferator` on both strategies) |
| `SHARED-INPUT-RUN` machines in the shipped blueprint | **2** (`assembling-machine-2#30`, `#31`, both `advanced-mining-machine`) | **0** |
| `MERGE POINT` belts near a coater | **3**, one of them `belt#0 (53,20,0)` on coater#768's body | **0** (no coaters in the artefact) |
| prime line | absent | present |

So on the reported URL the branch **costs 4 of 6 candidate/strategy pairs and
+4.07 % area on the winner** (2652 → 2760 tiles), and in exchange the two
reported defects (F1 mixed lane, F2 coater over a merge) are gone from the
shipped blueprint and the F3 prime obligation is declared.

## Step 1a — `universe-matrix` — FAIL

```
/usr/bin/time -v uv run flab2bp "<universe-matrix*60 URL>" --budget 30 -v -o gate/bp-um-after.txt
```

`cpu_pressure` before **6**, after **6.6**. Wall **0:14.46**, CPU **1392%**,
**exit 3**. No blueprint was produced, so there is no `bp-um-after.txt` and no
`decode-um-after.txt`; conditions 2 and 3 cannot be evaluated on an artefact
that does not exist.

Refusal, verbatim (`build-um-after.log`, first clause of each of the six pairs):

```
flab2bp: no valid layout for no-proliferator, all-products, output-products after 30s:
freeform/no-proliferator: a producer lane has fewer tiles than the consumers it must tap,
so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is
10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37; ...
```

`no-proliferator` needs **15** consumer lanes; `all-products` and
`output-products` need **12**. The producer lane is **10** tiles wide in all
three.

**The seating half of ruling R2 worked exactly as designed — measured, not
assumed.** `gate/probe_flanked_rows.py` plans the strips directly (no packing,
no routing) and reports for every candidate:

```
universe-matrix#37 machines=1 box_height=12 width=6 drain_outermost=True
  in_above 3 lane(s): [['antimatter'], ['electromagnetic-matrix'], ['energy-matrix']]
  in_below 3 lane(s): [['gravity-matrix'], ['information-matrix'], ['structure-matrix']]
  out_lanes 1
```

Those are the six distinct single-item lanes Step 1a asked to see. They exist in
the plan; the block never reaches a blueprint because the producer lane cannot
fan out to 12–15 consumer strips. **Next lever: the producer-lane fan-out.**
That is a bus/junction problem, not strip geometry, and is out of this plan's
scope — spec §9 R2.

## Step 2 — the second self-loop recipe — PASS

```
uv run pytest tests/rates/test_candidates.py -k reforming_refine_self_loop_seeds -q
```

exit **0**, 1 test selected, 1 passed (pytest prints no summary line on this box;
the exit code is the result). `cpu_pressure` before **23.4**, after **10.4**.

`tests/rates/test_candidates.py:201` asserts all three PASS conditions for
`refined-oil`:

* `seed.net_per_craft == Fraction(1)`
* `seed.seed_items == seed.machines * 2` (machines = 20)
* `"refined-oil" not in spec.external_inputs`

One deviation from the brief's prose, recorded rather than absorbed: hydrogen
**is** an external input in this fixture. For `reforming-refine` the self-loop
item is `refined-oil`; hydrogen is an ordinary ingredient and is correctly
external (ruling T7-A, and the test's own docstring says so).

## Steps 4 and 5 — the paired corpus round

Both arms, `--tier stress --budget 30 --strategy both`, 72 cells each.

| | baseline (master `0d88d247`) | candidate (branch `3780840c`) |
|---|---|---|
| wall | 3:19.27 | **2:57.95** |
| `cpu_pressure` before / after | 6.4 / 6.6 | 7.4 / 5.2 |
| cells | 72/72 | 72/72 |
| route backend | cython | cython |
| exit | 0 | 1 |

### `audit_compare` verdict line, verbatim as measured

```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0022  p95 31.1s
```

…followed by six `FAIL REFUSED:` lines (all `universe-matrix`), one
`FAIL p95 wall 31.1s exceeds 30.0s`, and the final line:

```
FAIL
```

`--regressions-only` lists the same six cells as `FAIL REGRESSION:` and nothing
else. As carry-forward note 5 predicted, the single red word is driven entirely
by `universe-matrix`; the per-arm table below is where the real cost is legible.

### Per arm, three axes

| axis | freeform | sequence-pair |
|---|---|---|
| CLEAN / REFUSED / INVALID — baseline | 36 / 0 / 0 | 36 / 0 / 0 |
| CLEAN / REFUSED / INVALID — candidate | **33 / 3 / 0** | **33 / 3 / 0** |
| cells CLEAN → not CLEAN | `universe-matrix/{no-proliferator, all-products, output-products}` | `universe-matrix/{no-proliferator, all-products, output-products}` |
| cells not CLEAN → CLEAN | **none** | **none** |
| geomean area ratio over cells CLEAN in BOTH (n=33) | **1.005848** (+0.585 %) | **0.998654** (−0.135 %) |
| cells whose area moved at all | 5 of 33 (all up) | 1 of 33 (down) |
| sum of areas over the paired cells | 52598 → 53181 | 44237 → 44224 |
| `detailed_route_time_s` p50 / p95 | 0.145 / 5.018 → **0.130 / 5.194** | 0.874 / 3.294 → **0.874 / 3.161** |
| `global_route_time_s` p50 / p95 | **not exposed for this arm** (0 of 33 rows carry the field) | 0.226 / 5.404 → **0.208 / 4.996** |
| wall seconds p50 / p95 | 5.468 / 28.767 → **5.053 / 27.638** | 29.729 / 31.323 → **29.977 / 31.241** |
| rip-up rounds (`stats.repair_iterations`) p50 / p95 | 1.0 / 3.0 → **1.0 / 2.4** | 1.0 / 1.4 → **1.0 / 2.0** |
| specs whose strip count grew (`stats.strips`, paired cells) | **0 of 33** | **0 of 33** |

The five freeform cells that moved:

| cell | area | strips | machines | sorters | belt tiles |
|---|---|---|---|---|---|
| `information-matrix/all-products` | 4760 → 5159 (+8.38 %) | 17 → 17 | 56 → 56 | 168 → 168 | 2704 → 2793 |
| `super-magnetic-ring/all-products` | 1880 → 1960 (+4.26 %) | 10 → 10 | 35 → 35 | 110 → 110 | 1230 → 1374 |
| `plastic/all-products` | 820 → 850 (+3.66 %) | 3 → 3 | 8 → 8 | 22 → 22 | 272 → 264 |
| `super-magnetic-ring/no-proliferator` | 2220 → 2262 (+1.89 %) | 13 → 13 | 58 → 58 | 179 → 179 | 1109 → 1233 |
| `super-magnetic-ring/output-products` | 2040 → 2072 (+1.57 %) | 13 → 13 | 52 → 52 | 160 → 160 | 1315 → 1177 |

and the one sequence-pair cell: `magnetic-coil/output-products` 299 → 286
(−4.35 %), strips 3 → 3.

**None of those six is a lane-seating change.** `gate/probe_strip_rows.py` plans
every stress-corpus spec on both trees and diffs six plan-level metrics
(`strip-rows-master.csv` vs `strip-rows-branch.csv`): **`universe-matrix` is the
only spec in the corpus whose strip plan changed at all.** Every other spec is
identical in strips, flanked strips, total `box_height`, tallest `box_height`,
input-lane count and mixed-lane count. All six moved cells are budget-limited
searches whose `hit_time_budget` and/or ALNS evaluation counts differ between
the two runs (e.g. `super-magnetic-ring/output-products` 9 → 7 evaluations,
`plastic/all-products` `hit_time_budget` 0 → 1) — **consistent with** deadline
driven search variation rather than any change this branch made, but I did not
run a repeat baseline to prove that, so it is stated as consistency and not as
a measured cause.

Corpus-wide mixed input lanes at plan time: **master 14** (all on
`universe-matrix`'s three candidates), **branch 0**. That is R1 landing.

### The drain-row move, reported SEPARATELY from the un-mixing

Measured from `plan_strips` on both trees, for `universe-matrix#37` — the only
flanked plan in the whole corpus:

| | master `0d88d247` | branch `3780840c` |
|---|---|---|
| `drain_outermost` | field absent | **True** |
| machines per flanked strip | 5 (`no-proliferator`) / 6 (other two) | **1** |
| flanked strips | 3 / 2 / 2 | **15 / 12 / 12** |
| `in_above` | 1 lane of 3 items | **3 lanes of 1 item** |
| `in_below` | 1 lane of 3 items | **3 lanes of 1 item** |
| `out_lanes` | 1 | 1 |
| `box_height` | **8** (1 above + 5 band + 1 out + 1 below) | **12** (3 + 5 + 1 + 3) |

Whole-spec effect (`strip-rows-*.csv`):

| candidate | strips | total `box_height` | tallest `box_height` | input lanes | mixed lanes |
|---|---|---|---|---|---|
| `no-proliferator` | 57 → **69** | 409 → **565** | 10 → **12** | 93 → **177** | 6 → **0** |
| `all-products` | 46 → **56** | 338 → **466** | 10 → **12** | 77 → **145** | 4 → **0** |
| `output-products` | 53 → **63** | 384 → **512** | 10 → **12** | 88 → **156** | 4 → **0** |

**The +4 rows split 1 / 3, and the split is measured, not argued.**
`gate/probe_flanked_rows.py`'s counterfactual calls `_seat_inputs` directly on
the Matrix Lab's six ingredients at the measured caps:

```
_side_lane_caps(2901, 0.0, 5) = (3, 3)
drain OUTERMOST (branch): below_cap=3 -> above 3 lane(s), below 3 lane(s), mixed lanes 0
drain innermost (master's rationing): below_cap=2 -> REFUSES:
  6 ingredients cannot be seated with the product leaving east: 3 lane(s) above and 2 below,
  each carrying ONE item, over a face that offers 3 insert pose(s) per side, leaves no room
  for 6 ingredient sorter(s) and the output lane. ...
```

* **The drain-row move's own row: +1.** `out_capacity = below_cap - len(in_below)`
  (`strip_variants.py:1532`), so with the drain innermost the inputs get
  `below_cap − 1 = 2` south rows. Moving the drain past sorter reach returns the
  third south row to the inputs. That is one row, and it is the row without
  which the seating refuses outright.
* **The un-mixing's rows: +3.** `in_above` 1 → 3 is two of them, `in_below` 1 → 2
  is the third. These are the price of six single-item lanes replacing two mixed
  ones — the price of R1, which is what was asked for.
* **+4 total. Not +1.** They are not netted anywhere in this document.

**Cells that gained a strip ROW in the corpus audit: 0 in both arms.** Not
because the drain move is free, but because the only spec it applies to
(`universe-matrix`) refuses before it reaches a blueprint, so its extra rows
never appear in a JSONL area. The rows above are the direct plan-level
measurement that the audit cannot show.

## Reading

* Coverage: **72/72 → 66/72**. Six cells lost, all `universe-matrix`, all
  REFUSED (not INVALID — nothing pastes and fails). Zero cells gained.
* Density: essentially flat on paired cells — freeform +0.585 %, sequence-pair
  −0.135 % — and the corpus evidence says none of that movement is this branch's
  doing.
* Route time: no arm got worse in any percentile that matters. freeform p95 wall
  fell 28.8 s → 27.6 s; sequence-pair `global_route_time_s` p95 fell 5.40 s →
  5.00 s. The rule did not pay for itself in coverage, and it did not cost
  anything measurable in route time either.
* On the reported URL, the shipped blueprint went from carrying both reported
  defects to carrying neither, at the cost of 4 of its 6 candidate/strategy
  pairs and +4.07 % area on the winner.

The ruling stands whatever the area number says (§9 R1). The number is above.
