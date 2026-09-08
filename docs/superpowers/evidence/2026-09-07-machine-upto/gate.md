# Machine ranking gate — measured FAIL; serial information control PASS

## Operating point

```text
--budget 30  --jobs 8  --strategy both  --max-seconds 3600
72 cells = 12 URLs x 3 candidate policies x 2 strategies
```

Corpus chunks preserve six policy/placer cells per URL. Controls use
no-proliferator/freeform, budget 30, workers=1, twelve URLs per arm. The reported
antimatter URL uses three policies × two placers, budget 30, workers=32.
The user's later concurrency ruling supersedes the plan's global audit exclusion:
independent jobs ran concurrently; only failing scenarios are rerun serially.
The recorded host pressure is material context, not grounds to turn FAIL into PASS.

## Arms and provenance

All measured evidence below is immutable in
[`parallel-gates-h2vHbpn2/`](parallel-gates-h2vHbpn2/), abbreviated **E**.
The directory's provenance files record checkout and imported module paths as well
as the full revision. No original evidence was edited for this adjudication.

| Arm | Revision | Checkout/import provenance |
| --- | --- | --- |
| base | `ad8a6f80550e1fb91abe12d30e7efc379d2f8a8d` | `.claude/worktrees/machine-upto-base`; its own `src/flab2bp/__init__.py` |
| exact | `f148a4c3c6d662e3e19ba28f9a397507c1342220` | `.claude/worktrees/machine-upto`; its own `src/flab2bp/__init__.py` |
| up-to | `f148a4c3c6d662e3e19ba28f9a397507c1342220` | Same candidate checkout/import, distinct mode/arm metadata |

`candidate-provenance.json` binds the candidate identity. The controls, round,
and reported provenance files preserve their individual mode/arm identities.
This is evidence at those revisions, not certification of Main's later integrated
source. The complete original brief is
`/home/dannyb/handoff-agents/briefs/machine-upto-brief.md`; approved design and rules
are in `../../plans/2026-09-07-machine-upto.md`.

## Gate (a): base versus exact — FAIL

| Measure | base | exact | Verdict |
| --- | ---: | ---: | --- |
| Full corpus rows | 72 | 72 | Complete |
| CLEAN / REFUSED / INVALID / CRASHED | 66 / 6 / 0 / 0 | 66 / 6 / 0 / 0 | Named status agreement; not all CLEAN |
| CLEAN paired cells | — | 66 | PASS: no missing or named status regressions |
| Printed geometric-mean area ratio | — | 0.9968 | **FAIL**: required `1.0000` (F7) |
| Comparator p95 wall | — | 31.8 s | **FAIL** versus 30.0 s |
| `base-exact-compare.log` | — | EXIT=1, FAIL | Preserve actual comparator verdict |

The six refusals are universe-matrix under all three policies and both placers,
in all three corpus arms. The original producer-lane fan-out guard reports
`antimatter: mass-energy-storage#23 lane is 10 tile(s) wide` but must tap **15**
consumer lanes of `universe-matrix#37` for no-proliferator, or **12** for
all-products/output-products. Sequence-pair reports the same guard for all four
islands. These are inherited paired refusals, not newly INVALID layouts and not
CLEAN results. Both comparison logs print these as `FAIL REFUSED`; neither log's
FAIL is erased by the status-agreement subcriterion.

### Twelve complete-byte controls — saved-run FAIL; separate serial pair PASS

Both arms have 11 CLEAN and 1 REFUSED. `controls-compare.log` exits **1**.
Digests cover the entire encoded blueprint with only creation timestamp fixed to
zero; a refusal has no digest and cannot satisfy the twelve-byte-match rule.

| URL | base / exact | Complete blueprint comparison |
| --- | --- | --- |
| iron-ingot | CLEAN / CLEAN | Match |
| magnetic-coil | CLEAN / CLEAN | Match |
| graphene | CLEAN / CLEAN | Match |
| electromagnetic-matrix | CLEAN / CLEAN | Match |
| plastic | CLEAN / CLEAN | Match |
| processor | CLEAN / CLEAN | Match |
| energy-matrix | CLEAN / CLEAN | Match |
| super-magnetic-ring | CLEAN / CLEAN | Match |
| casimir-crystal | CLEAN / CLEAN | Match |
| information-matrix | CLEAN / CLEAN | **Original mismatch**; separate serial retry matches |
| quantum-chip | CLEAN / CLEAN | Match |
| universe-matrix | REFUSED / REFUSED | No digest; **unmet**, not a byte match |

There are **ten**, not eleven or twelve, complete-byte matches. The read-only
`MachineControlScout` analysis of the original records found the information
mismatch is actual layout/connectivity, not timestamp/description only: frame
73×110/band200 → 203×39/band160, buildings 3391→3884, belts 2951→3442,
splitters 7→6, towers 47→50. The 97 recipe/machine records match except
position/yaw, and all 59 headroom-rate values match as a multiset with different
run ordinals. Both digests match their saved blueprint files; timestamps are zero.
An unchanged wall-limited layout search is a plausible **unproven** cause; this
is not permission to dismiss a deterministic-control failure. Only Main owns
serial investigation; no later run or interpretation has been substituted here.

## Gate (b): exact versus up-to — mixed subcriteria; no overall PASS

| Rule / measure | Saved evidence | Verdict |
| --- | --- | --- |
| 72 rows each, CLEAN count not reduced | 66 CLEAN / 6 REFUSED / 0 INVALID / 0 CRASHED in each arm; same named cells; 66 clean pairs | PASS for status/non-regression subcriterion |
| Every spec's machine counts and rates equal | `moved.jsonl`: 36 policy/URL pairs, both modes (72 records), all `invariant_u=true`; `moved-table.log` EXIT=0 | PASS for independently solved rate/spec invariants, not a placed-count measurement |
| Area ratio within plan's 1.3% same-arm band | 1.0017 (+0.17%) | PASS for original Task 11(b)(3) |
| Recovery gate's stricter area ratio ≤1.00 | 1.0017 | **FAIL** for the recorded stricter rule; do not silently replace it |
| Non-empty moved-recipe list | 12 of 36 specs move; 19 recipe-move records, repeated across the two placers in the joined table | PASS: feature is not corpus-inert |
| Comparator p95 wall ≤30 s | 32.5 s | **FAIL** |
| Raw `exact-upto-compare.log` | EXIT=1, FAIL, six inherited `FAIL REFUSED` plus p95 failure | **FAIL**, not a source-review or coordinator PASS |

### Complete 72-cell measured table

The table below is the preserved stdout table from `E/moved-table.log` (EXIT=0),
not a new gate execution. Status/area/belts are **base/exact/up-to**, while machine
counts and power are **exact/up-to** rate-spec values joined by URL and policy.
Corpus audit rows do not record placed machine counts; the table must not be read
as independent proof of layout counts for all 72 cells. In particular refused
cells have rate specs, but no certified layout: their `0.0` area / `0` belts are
raw refusal placeholders, **not measurements of a zero-area factory**. `None`
power means unknown, never zero.

| URL | policy | placer | base/exact/up-to status | area | belts | exact/up-to machines | machine kW | moves |
|---|---|---|---|---|---|---|---|---|
| casimir-crystal | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 1107.0/1107.0/1107.0 | 398/398/398 | 23/23 | 10800/10800 | none |
| casimir-crystal | all-products | freeform | CLEAN/CLEAN/CLEAN | 1161.0/1161.0/1161.0 | 488/488/492 | 17/17 | 8100/8100 | none |
| casimir-crystal | output-products | freeform | CLEAN/CLEAN/CLEAN | 1189.0/1189.0/1189.0 | 466/466/466 | 21/21 | 10080/10080 | none |
| electromagnetic-matrix | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 609.0/609.0/609.0 | 166/166/166 | 9/9 | 3960/3420 | circuit-board: assembling-machine-2 → assembling-machine-1; magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| electromagnetic-matrix | all-products | freeform | CLEAN/CLEAN/CLEAN | 783.0/783.0/783.0 | 413/413/413 | 8/8 | 3600/3060 | circuit-board: assembling-machine-2 → assembling-machine-1; magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| electromagnetic-matrix | output-products | freeform | CLEAN/CLEAN/CLEAN | 696.0/696.0/696.0 | 247/247/247 | 9/9 | 3960/3420 | circuit-board: assembling-machine-2 → assembling-machine-1; magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| energy-matrix | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 616.0/616.0/616.0 | 139/139/139 | 10/10 | 4320/4320 | none |
| energy-matrix | all-products | freeform | CLEAN/CLEAN/CLEAN | 780.0/780.0/780.0 | 204/204/204 | 8/8 | 3480/3480 | none |
| energy-matrix | output-products | freeform | CLEAN/CLEAN/CLEAN | 650.0/650.0/650.0 | 184/184/184 | 9/9 | 3840/3840 | none |
| graphene | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 363.0/363.0/363.0 | 70/70/70 | 5/5 | 2520/2520 | none |
| graphene | all-products | freeform | CLEAN/CLEAN/CLEAN | 525.0/525.0/525.0 | 148/148/148 | 4/4 | 2160/2160 | none |
| graphene | output-products | freeform | CLEAN/CLEAN/CLEAN | 429.0/429.0/429.0 | 127/127/127 | 5/5 | 2520/2520 | none |
| information-matrix | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 7917.0/7917.0/7917.0 | 3436/3436/3436 | 97/97 | 47160/47160 | none |
| information-matrix | all-products | freeform | CLEAN/CLEAN/CLEAN | 4292.0/4292.0/4292.0 | 2739/2739/2739 | 56/56 | 27900/27360 | circuit-board: assembling-machine-2 → assembling-machine-1 |
| information-matrix | output-products | freeform | CLEAN/CLEAN/CLEAN | 5734.0/5734.0/5734.0 | 2674/2674/2674 | 84/84 | 41340/41340 | none |
| iron-ingot | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 63.0/63.0/63.0 | 10/10/10 | 1/1 | 360/360 | none |
| iron-ingot | all-products | freeform | CLEAN/CLEAN/CLEAN | 112.0/112.0/112.0 | 28/28/28 | 1/1 | 360/360 | none |
| iron-ingot | output-products | freeform | CLEAN/CLEAN/CLEAN | 112.0/112.0/112.0 | 28/28/28 | 1/1 | 360/360 | none |
| magnetic-coil | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 198.0/198.0/198.0 | 50/50/50 | 4/4 | 1620/1350 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| magnetic-coil | all-products | freeform | CLEAN/CLEAN/CLEAN | 336.0/336.0/336.0 | 126/126/126 | 3/3 | 1260/990 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| magnetic-coil | output-products | freeform | CLEAN/CLEAN/CLEAN | 340.0/342.0/342.0 | 118/104/104 | 4/4 | 1620/1350 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| plastic | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 760.0/760.0/760.0 | 198/198/198 | 9/9 | 6720/6720 | none |
| plastic | all-products | freeform | CLEAN/CLEAN/CLEAN | 880.0/840.0/880.0 | 272/272/272 | 8/8 | 5760/5760 | none |
| plastic | output-products | freeform | CLEAN/CLEAN/CLEAN | 819.0/819.0/819.0 | 276/276/276 | 9/9 | 6720/6720 | none |
| processor | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 810.0/810.0/810.0 | 271/271/271 | 21/21 | 9000/9000 | none |
| processor | all-products | freeform | CLEAN/CLEAN/CLEAN | 960.0/960.0/960.0 | 571/571/571 | 16/16 | 7020/6750 | circuit-board: assembling-machine-2 → assembling-machine-1 |
| processor | output-products | freeform | CLEAN/CLEAN/CLEAN | 920.0/920.0/920.0 | 362/376/360 | 20/20 | 8640/8640 | none |
| quantum-chip | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 5610.0/5610.0/5610.0 | 2133/2133/2133 | 87/87 | 109080/108000 | circuit-board: assembling-machine-3 → assembling-machine-2 |
| quantum-chip | all-products | freeform | CLEAN/CLEAN/CLEAN | 4661.0/4661.0/4661.0 | 2922/2922/2922 | 49/49 | 60480/60480 | none |
| quantum-chip | output-products | freeform | CLEAN/CLEAN/CLEAN | 4070.0/4070.0/4070.0 | 1851/1851/1851 | 76/76 | 95760/94680 | circuit-board: assembling-machine-3 → assembling-machine-2 |
| super-magnetic-ring | no-proliferator | freeform | CLEAN/CLEAN/CLEAN | 2204.0/2166.0/2220.0 | 1103/1152/1248 | 58/58 | 25020/25020 | none |
| super-magnetic-ring | all-products | freeform | CLEAN/CLEAN/CLEAN | 1968.0/1845.0/1968.0 | 1316/1457/1316 | 35/35 | 15480/14670 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| super-magnetic-ring | output-products | freeform | CLEAN/CLEAN/CLEAN | 2162.0/2160.0/2120.0 | 1279/1319/1224 | 52/52 | 22680/22680 | none |
| universe-matrix | no-proliferator | freeform | REFUSED/REFUSED/REFUSED | 0.0/0.0/0.0 | 0/0/0 | 224/224 | None/None | none |
| universe-matrix | all-products | freeform | REFUSED/REFUSED/REFUSED | 0.0/0.0/0.0 | 0/0/0 | 113/113 | None/None | electric-motor: assembling-machine-3 → assembling-machine-2; gear: assembling-machine-3 → assembling-machine-1; graviton-lens: assembling-machine-3 → assembling-machine-2; quantum-chip: assembling-machine-3 → assembling-machine-2; titanium-glass: assembling-machine-3 → assembling-machine-2 |
| universe-matrix | output-products | freeform | REFUSED/REFUSED/REFUSED | 0.0/0.0/0.0 | 0/0/0 | 193/193 | None/None | none |
| casimir-crystal | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 1092.0/1092.0/1092.0 | 411/411/411 | 23/23 | 10800/10800 | none |
| casimir-crystal | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 1100.0/1100.0/1100.0 | 611/611/611 | 17/17 | 8100/8100 | none |
| casimir-crystal | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 1100.0/1100.0/1100.0 | 461/461/461 | 21/21 | 10080/10080 | none |
| electromagnetic-matrix | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 504.0/504.0/504.0 | 176/176/176 | 9/9 | 3960/3420 | circuit-board: assembling-machine-2 → assembling-machine-1; magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| electromagnetic-matrix | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 870.0/870.0/870.0 | 487/487/487 | 8/8 | 3600/3060 | circuit-board: assembling-machine-2 → assembling-machine-1; magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| electromagnetic-matrix | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 620.0/620.0/651.0 | 239/239/244 | 9/9 | 3960/3420 | circuit-board: assembling-machine-2 → assembling-machine-1; magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| energy-matrix | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 504.0/504.0/504.0 | 154/154/154 | 10/10 | 4320/4320 | none |
| energy-matrix | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 820.0/820.0/820.0 | 176/176/176 | 8/8 | 3480/3480 | none |
| energy-matrix | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 728.0/728.0/728.0 | 188/188/188 | 9/9 | 3840/3840 | none |
| graphene | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 363.0/363.0/363.0 | 69/69/69 | 5/5 | 2520/2520 | none |
| graphene | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 540.0/540.0/540.0 | 125/125/125 | 4/4 | 2160/2160 | none |
| graphene | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 455.0/455.0/455.0 | 130/130/130 | 5/5 | 2520/2520 | none |
| information-matrix | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 4560.0/4560.0/4560.0 | 2855/2855/2855 | 97/97 | 47160/47160 | none |
| information-matrix | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 3472.0/3472.0/3472.0 | 2457/2457/2457 | 56/56 | 27900/27360 | circuit-board: assembling-machine-2 → assembling-machine-1 |
| information-matrix | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 4800.0/4800.0/4800.0 | 2760/2760/2760 | 84/84 | 41340/41340 | none |
| iron-ingot | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 63.0/63.0/63.0 | 10/10/10 | 1/1 | 360/360 | none |
| iron-ingot | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 112.0/112.0/112.0 | 28/28/28 | 1/1 | 360/360 | none |
| iron-ingot | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 112.0/112.0/112.0 | 28/28/28 | 1/1 | 360/360 | none |
| magnetic-coil | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 230.0/230.0/230.0 | 51/51/51 | 4/4 | 1620/1350 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| magnetic-coil | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 345.0/345.0/345.0 | 117/117/117 | 3/3 | 1260/990 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| magnetic-coil | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 280.0/280.0/280.0 | 93/93/93 | 4/4 | 1620/1350 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| plastic | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 702.0/722.0/684.0 | 203/196/197 | 9/9 | 6720/6720 | none |
| plastic | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 875.0/875.0/875.0 | 261/261/261 | 8/8 | 5760/5760 | none |
| plastic | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 840.0/840.0/840.0 | 280/280/280 | 9/9 | 6720/6720 | none |
| processor | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 810.0/810.0/810.0 | 297/297/297 | 21/21 | 9000/9000 | none |
| processor | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 945.0/945.0/945.0 | 551/551/551 | 16/16 | 7020/6750 | circuit-board: assembling-machine-2 → assembling-machine-1 |
| processor | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 840.0/840.0/840.0 | 372/372/372 | 20/20 | 8640/8640 | none |
| quantum-chip | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 3692.0/3692.0/3692.0 | 2051/2051/2051 | 87/87 | 109080/108000 | circuit-board: assembling-machine-3 → assembling-machine-2 |
| quantum-chip | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 3300.0/3300.0/3300.0 | 2136/2136/2136 | 49/49 | 60480/60480 | none |
| quantum-chip | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 3680.0/3280.0/3280.0 | 2423/2052/2052 | 76/76 | 95760/94680 | circuit-board: assembling-machine-3 → assembling-machine-2 |
| super-magnetic-ring | no-proliferator | sequence-pair | CLEAN/CLEAN/CLEAN | 2294.0/2294.0/2294.0 | 1278/1278/1278 | 58/58 | 25020/25020 | none |
| super-magnetic-ring | all-products | sequence-pair | CLEAN/CLEAN/CLEAN | 1932.0/1932.0/1932.0 | 1238/1238/1238 | 35/35 | 15480/14670 | magnetic-coil: assembling-machine-2 → assembling-machine-1 |
| super-magnetic-ring | output-products | sequence-pair | CLEAN/CLEAN/CLEAN | 2016.0/2016.0/2016.0 | 1345/1345/1345 | 52/52 | 22680/22680 | none |
| universe-matrix | no-proliferator | sequence-pair | REFUSED/REFUSED/REFUSED | 0.0/0.0/0.0 | 0/0/0 | 224/224 | None/None | none |
| universe-matrix | all-products | sequence-pair | REFUSED/REFUSED/REFUSED | 0.0/0.0/0.0 | 0/0/0 | 113/113 | None/None | electric-motor: assembling-machine-3 → assembling-machine-2; gear: assembling-machine-3 → assembling-machine-1; graviton-lens: assembling-machine-3 → assembling-machine-2; quantum-chip: assembling-machine-3 → assembling-machine-2; titanium-glass: assembling-machine-3 → assembling-machine-2 |
| universe-matrix | output-products | sequence-pair | REFUSED/REFUSED/REFUSED | 0.0/0.0/0.0 | 0/0/0 | 193/193 | None/None | none |


### Concrete per-cell contradictions, not only p95

* Base→exact fails the explicit area-identity rule: e.g. quantum-chip /
  output-products / sequence-pair is **3680→3280** area and **2423→2052** belts;
  super-magnetic-ring / all-products / freeform is **1968→1845**, belts
  **1316→1457**. Aggregate status equality does not repair geometric identity.
* Exact→up-to has individual growth hidden by the +0.17% geometric mean:
  super-magnetic-ring / all-products / freeform **1845→1968** (+6.67%);
  electromagnetic-matrix / output-products / sequence-pair **620→651** (+5%);
  plastic / all-products / freeform **840→880** (+4.76%). The last has **no
  machine moves**, so attributing every layout delta to this feature is unsound.
  These are real saved per-cell differences; the original 1.3% rule is an
  aggregate ratio, not an independently met 1.3% bound on each cell.
* No count or item-flow contradiction was found in the 36 paired rate specs:
  the executed `moved.py` assertions check per-recipe counts, modes, inputs and
  outputs, plus whole-spec external/output/surplus rates. This does **not** imply
  every routed layout conserves flow: gate (c) has the explicit shortage below.

## Gate (c): reported antimatter URL — FAIL

Six rows per arm are present; **2 CLEAN / 4 REFUSED** in each, not six green.
The full inherited URL and reproduction settings are in `run_gate.py`.
A CLEAN row has no ERROR findings but still has informational/warning findings;
the original literal requirement of **zero validator findings** is not met.

| Policy | Placer | exact → up-to | Machines | Area | Belts | Wall seconds | ERROR / WARNING / INFO exact → up-to |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no-proliferator | freeform | CLEAN → CLEAN | 38 → 38 | 4480 → 5130 | 2783 → 2311 | 31.739 → 32.475 | 0/18/77 → 0/17/77 |
| all-products | freeform | REFUSED → REFUSED | unavailable | unavailable | unavailable | 30.322 → 28.970 | No returned certified result |
| output-products | freeform | REFUSED → REFUSED | unavailable | unavailable | unavailable | 25.382 → 29.945 | Flow-conservation rejection |
| no-proliferator | sequence-pair | CLEAN → CLEAN | 38 → 38 | 4032 → 3224 | 1936 → 1851 | 24.720 → 26.226 | 0/18/77 → 0/18/77 |
| all-products | sequence-pair | REFUSED → REFUSED | unavailable | unavailable | unavailable | 22.545 → 18.291 | Flow-conservation rejection/deadline |
| output-products | sequence-pair | REFUSED → REFUSED | unavailable | unavailable | unavailable | 24.121 → 24.607 | Flow-conservation rejection/deadline |

Named refusal mechanisms in **both** arms:

* **freeform/all-products:** no packing of 19 strips could be wired at any
  candidate height; every generated pack left nets unrouted. The refusal calls
  this a PACKER defect, not a success within budget.
* **freeform/output-products:** every wired packing was rejected by
  `flow.conservation`. Four machines demand **49/90 items/s of quantum-chip**,
  but only **43/90 items/s** can reach them in flow order: shortfall **1/15
  items/s**, lanes **[21, 22, 23, 24]**, finding entities **(14, 39, 82, 587)**.
  This is a concrete physical flow contradiction, not a generic p95 warning or
  evidence that the rate-stage chooser changed demand. The invalid placement
  was correctly refused rather than emitted.
* **sequence-pair/all-products** and **sequence-pair/output-products:** deadline
  exhausted before an exact layout; exact validation failures `flow.conservation`.

The two CLEAN up-to layouts each report the same ten recipe moves, all
`assembling-machine-2 → assembling-machine-1`: `arc-smelter` 1→1,
`assembling-machine-3` 1→1, `circuit-board` 1→1, `electric-motor` 2→2,
`electromagnetic-turbine` 1→1, `gear` 1→1, `magnetic-coil` 1→1,
`plane-smelter` 1→1, `re-composing-assembler` 1→1,
`super-magnetic-ring` 1→1. These names are **recipes being manufactured**, not
claims that a smelting operation uses an assembler. Refused pairs have no
returned move list; missing lists are not “no moves.” No zero-collision or
all-six certification claim is made for the refused arms.

## Rates, moved recipes, and installed machine power

Two-phase design remains in force: exact craft rates are recovered first; the
chooser considers eligible unlocked/placeable producers at or below the ranked
ceiling, minimizes exact-Fraction ceil machine count, then ties by speed/dataset
order. It does not revisit recipe support or item flow. CSV pins stay exact;
requested mode and attempt-local move provenance still report honestly.
**Default remains exact** in Python, CLI, HTTP and UI. No missing-rank preset fix
was added (D5): absent `mmr`, the first producer remains the ceiling and up-to is
inert. The unrelated Dark Fog footprint alias defect remains outside this change
(D6); the gate uses physical placement area, not rates-layer footprint aliases.

The complete corpus move list, shared by both placers, is below. All counts are
before→after, not “machines saved.” Names/directions match `E/moved.jsonl`.

| URL / policies | Recipe | From → to | Count |
| --- | --- | --- | --- |
| magnetic-coil / all three | magnetic-coil | assembling-machine-2 → assembling-machine-1 | 1→1 each |
| electromagnetic-matrix / all three | circuit-board; magnetic-coil | assembling-machine-2 → assembling-machine-1 | 1→1 each recipe/policy |
| processor / all-products | circuit-board | assembling-machine-2 → assembling-machine-1 | 1→1 |
| super-magnetic-ring / all-products | magnetic-coil | assembling-machine-2 → assembling-machine-1 | 3→3 |
| information-matrix / all-products | circuit-board | assembling-machine-2 → assembling-machine-1 | 2→2 |
| quantum-chip / no-proliferator, output-products | circuit-board | assembling-machine-3 → assembling-machine-2 | 2→2 each |
| universe-matrix / all-products | electric-motor; graviton-lens; quantum-chip; titanium-glass | assembling-machine-3 → assembling-machine-2 | 2→2 each |
| universe-matrix / all-products | gear | assembling-machine-3 → assembling-machine-1 | 1→1 |

Other corpus policy/URL specs have no moves. Installed machine power is the exact
Fraction sum of `count × dataset machine usage`, in **kW**. It is nameplate
machine usage, not measured/throttled factory consumption and not sorter, coater,
or tower consumption. Among the **33 specs with complete usage data**, the
subtotal is **553,680→547,470 kW**, a **6,210 kW** reduction; each policy spec is
counted once, not twice for the two placers. This is not a complete-corpus total.
All three universe-matrix specs have missing `ray-receiver` usage, so total power
is **null/None in both modes**, with that machine ID recorded. No zero is
fabricated, and universe's five moves do not justify inventing a total saving.

## Recorded host operating point

Values are five-sample `vmstat` runnable-process means, not load averages. These
are the original before/after samples, not a claim of a quiet host (<64).
Artifact timestamps are UTC 2026-09-08; keep their original clock values.

| Run | Before UTC / runnable mean | After UTC / runnable mean |
| --- | --- | --- |
| controls-base | 01:17:15.862697 / 78.2 | 01:20:01.282642 / 65.4 |
| controls-exact | 01:17:15.874816 / 83.6 | 01:19:43.306791 / 246.2 |
| round-base | 01:19:08.990896 / 168.2 | 01:25:55.482547 / 161.8 |
| round-exact | 01:19:09.134336 / 181.0 | 01:25:51.575333 / 134.4 |
| round-up-to | 01:19:08.970292 / 167.2 | 01:25:55.966246 / 178.2 |
| reported-exact | 01:19:08.825626 / 169.0 | 01:22:05.390067 / 98.0 |
| reported-up-to | 01:19:08.836018 / 152.4 | 01:22:07.443171 / 57.2 |

## Source review, executed verification, and unmet acceptance

`MachineFinalReview` returned **source/spec PASS / quality PASS**, no findings,
for `ad8a6f80..f148a4c3`. It ran no validation and explicitly did **not** declare
the controls, reported arms, or overall gate PASS. This documentation-only
adjudication likewise ran no tests, builds, gates, probes or browser actions.

Main's already executed evidence in
`.superpowers/sdd/2026-09-07-machine-upto/`:

| Evidence | Recorded result |
| --- | --- |
| `recovery-review-red.log`, `recovery-review-green.log` | Unknown-producer regression fails pre-fix, passes fixed predicate; independent Batch A re-review PASS/PASS |
| `recovery-gate-provenance-tests.log` | Ten real entrypoint provenance scenarios EXIT=0; scoped fix review PASS/PASS |
| `recovery-ruff.log`, `recovery-format.log`, `recovery-mypy.log` | EXIT=0 each |
| `recovery-rates.log`, `recovery-surfaces.log` | EXIT=0 each |
| `recovery-web-typecheck.log`, `recovery-web-lint.log`, `recovery-web-test.log`, `recovery-web-build.log` | EXIT=0 each |
| `parallel-full-suite.log` | **EXIT=1**, inherited band160 cold-proof and two-stage alignment failures |
| `serial-failed-nodes.log` | **EXIT=1**, same two failures when rerun serially |

Exact failed node names:
`tests/layout/test_freeform.py::test_all_products_band_160_cold_proof_reaches_a_valid_layout`
and
`tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`.
Do not replace these actual outcomes with only the original brief's known-red
list or claim a passing full suite.

Main also exercised **actual** web exact/up-to builds using native keyboard input
and a browser, not mocked HTTP: electromagnetic-matrix60 with Plane Smelter /
Assembler III ceilings yielded 8 machines in both modes, all three candidates
certified without errors. The winner showed four up-to moves; selecting the
non-winning all-products result showed its own five moves, including its distinct
magnet downgrade. Saved proof: `recovery-ui-exact.json/.png`,
`recovery-ui-up-to.json/.png`, and
`recovery-ui-nonwinning-all-products.txt/.png`. A controlled-input helper failure
was overcome with native typing, not an application workaround. This proves the
changed UI surface and selected-attempt provenance; it does not certify the
separate reported antimatter URL or the corpus controls.

**Unmet / postintegration:** gate (a) geometry and twelve-control byte identity;
gate (b) raw comparator and
stricter ≤1.00 area criterion; gate (c) all-six/no-findings certification; full
suite green. Main owns integrated verification and `~/report.md`. Any integrated
revision needs separately attributed evidence, not relabeling this directory.

## Durable controller rulings

Ruling F1: omit the unused `ALL_UNLOCKED` sentinel — existing helpers already supply the set — cost if wrong: trivial test edit.

Ruling F2: retain the exact `AdjustedRecipe` type check — extraction subclasses must not become plain production columns — cost if wrong: extraction misclassification or review churn.

Ruling F3: create the evidence directory in pre-flight — Task 4 precedes Task 11 — cost if wrong: missing early evidence destination.

Ruling F4: adapt to actual test helpers without changing their signatures — plan helper names are not authoritative APIs — cost if wrong: test churn.

Ruling F5: prepare and sync the pinned base checkout in pre-flight — early identity evidence needs it — cost if wrong: wrong/missing comparison baseline.

Ruling F6: call `build_jobs` using its actual signature — the plan's ellipsis is shorthand — cost if wrong: invalid test invocation.

Ruling F7: exact area identity means printed ratio `1.0000`; twelve single-worker complete-byte controls are the stronger identity proof — multiworker wall-clock search is not reproducible against itself — cost if wrong: weaker-than-requested identity, caught by controls. The measured ratio and controls both remain failed here.

Ruling F8 (historical, superseded by R7): the original controller neutralized `diff.external` in the worktrees for readable review packages — difftastic output obscured patches — cost if wrong: unreadable review evidence. This is a historical record, not authorization to mutate shared configuration now.

Ruling R1: preserve landed Batch A and regenerate its incomplete review package before further edits — the recovered package lacked an actual patch/result — cost if wrong: independent review has no source evidence.

Ruling R2: distinguish inherited implementer lint claims from returned controller evidence — the former controller checks had no recovered result — cost if wrong: false verification claims. Later returned Main logs are separately recorded above.

Ruling R3: reject catalog lookups returning `None` and use an eligible unknown-producer regression — non-raising lookup does not prove placeability — cost if wrong: chooser admits an unplaceable machine. Fix commits `db70cd8a`, `bc038dc7`; Main's pre/post regression and re-review closed this finding.

Ruling R4: pinned CSV recipes keep exact machines while reporting the requested mode; every attempt owns its move provenance — selecting a losing alternative must not display winner moves — cost if wrong: misleading machine/pin or selected-result reporting.

Ruling R5: hash the complete blueprint with timestamp zero, using the same external probe in both checkouts — placement-only digests omit public encoded changes — cost if wrong: false byte-identity acceptance. A refused control cannot pass.

Ruling R6: preserve completed chunks and reject partial chunks, mixed provenance, or interrupted logs — no hidden retry may select a better result — cost if wrong: mixed/incomplete evidence masquerades as a round.

Ruling R7: use explicit `--no-ext-diff`, superseding F8 — shared Git configuration must not be mutated by resumed reviews — cost if wrong: cross-worktree interference or unreadable patches.

Ruling R8: bind all non-base arms in one output directory to one candidate identity, and check joined layout SHAs before rate solving/table emission — mode-local identity alone allowed mixed revisions — cost if wrong: invalid measured comparison. Fixes `76eaaa3d`, `59954950`, `5b013dc5`; Main's scoped re-review and ten provenance cases passed.

Ruling R9: remove only host-wide audit exclusion under the user's later concurrency instruction — independent jobs may overlap; only failures rerun serially — cost if wrong: timing contention must remain visible, never explain away correctness/deadline FAILs. Main's saved `parallel-exclusion-red-giXkB8Bz/launch.log` demonstrates the old refusal; `parallel-exclusion-green-5jevvMZ6/launch.log` demonstrates one successful concurrent iron-ingot control, not twelve-control acceptance. Shared provenance, chunk completeness, interrupted-log protection and baseline/import checks remain.

Ruling D5: retain first-producer fallback when `mmr` is absent — honoring preset min/max ranks changes existing bare-URL builds and breaks the exact guard — cost if wrong: up-to is inert without explicit ranks; no default-rank fix is claimed.

Ruling D6: leave the unrelated Dark Fog footprint-alias defect unchanged — correcting rates-layer footprints would move the exact arm — cost if wrong: those rates-layer areas remain understated; physical placed area is authoritative here.

## Reproduction commands and final disposition

These are command recipes, **not commands run by this documentation worker**.
Use a fresh output directory for new evidence; never overwrite E to obtain better
numbers. Wrappers preserve the complete reported URL and approved operating
point. Main uses supervised processes and owns execution/exit capture.

```sh
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto
BASE=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto-base
E=$ROOT/docs/superpowers/evidence/2026-09-07-machine-upto
OUT="$E/fresh-output-directory"
sh "$E/run_controls.sh" base "$BASE" --out "$OUT"
sh "$E/run_controls.sh" exact "$ROOT" --out "$OUT"
python3 "$E/compare_controls.py" "$OUT"
sh "$E/run_round.sh" base "$BASE" --out "$OUT"
sh "$E/run_round.sh" exact "$ROOT" --out "$OUT"
sh "$E/run_round.sh" up-to "$ROOT" --out "$OUT"
uv run python scripts/audit_compare.py "$OUT/base.jsonl" "$OUT/exact.jsonl" --expect-cells 72
uv run python scripts/audit_compare.py "$OUT/exact.jsonl" "$OUT/up-to.jsonl" --expect-cells 72
sh "$E/run_reported.sh" exact "$ROOT" --out "$OUT"
sh "$E/run_reported.sh" up-to "$ROOT" --out "$OUT"
uv run python "$E/moved.py" --out "$OUT/moved.jsonl" --layouts "$OUT"
```

Independent arms may run concurrently; the lines do not reinstate host-wide
serialization. Capture stdout/exit codes separately. The observed comparator
commands did not use `--regressions-only`, so their refused/p95 failures remain
part of the actual results; a different invocation cannot retroactively pass
them. Coordinator launch EXIT=0 means the requested chunks completed, not that
their statuses passed acceptance.

**Final measured disposition: FAIL / not gate-approved.** Source review and the
actual exact/up-to UI proof passed their own scopes. The original information
control mismatch remains recorded. Main reran only its base/exact pair serially
into `E/serial-information-matrix/`: both CLEAN, and `cmp` of their complete
fixed-timestamp blueprint files exits0. This failure did not reproduce serially;
it does not rewrite the original ten-match aggregate or prove a unique cause.
Default remains **exact**. No original raw evidence was removed or modified.
