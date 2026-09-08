# Hierarchical v4 — Task 9 evidence gate

## 0. Rule and measured revision

**This is a retrospective report, not a preregistration.** The required rule-only
`gate.md` commit before measurement did not occur; this file was absent when the
report was assembled. The earlier actual rule is the approved plan at
`51d211c1:docs/superpowers/plans/2026-09-07-hierarchical-v4.md:1619–1620`,
also copied into `.superpowers/sdd/2026-09-07-hierarchical-v4/task-9-brief.md:24–25`.
It is reproduced verbatim, not rewritten to fit the outcome:

> **PASS** if all five hold: (a) `titanium-glass/all-products` at 60 s emits a blueprint whose `validate.certify` report has **zero errors**; (b) every OTHER cell that COMPOSES either emits a blueprint with zero `certify` errors, or its refusal NAMES the lever that would unlock it — Lever 1 if it refuses with `reservation_partial > 0` and unrouted cuts that are not `BUDGET`, Lever 2 if it refuses on `power.coverage`, Lever 3 if it refuses with blocks never placed; (c) both malls compose — every block placed, the build reaching `compose`; (d) `titanium-glass` builds at `--budget 15`, emitting a blueprint; (e) the default-unchanged corpus guard has zero regressions — no cell CLEAN on the merge base and not CLEAN on the branch, 0 INVALID, 0 CRASH.
> **FAIL** otherwise, naming the clause AND the lever that failed (1 the corridor matcher, 2 composition power, 3 the block solvers), and ranking the next three levers with the file:line and the number behind each, exactly as v3's §5 did.

G2's recorded interpretation is existential for (a), with **four original
rounds and their observed reliability** reported, not a requirement that all
four emit. Area is report-only, without a threshold: best-known belt3 12408,
zurl2 40905, titanium-glass 5727; no mall baseline. Wall is report-only against
budget plus `RACE_COMPLETION_GRACE_S = 6.0`.

Measured large-cell source/test freeze: **706ddb79aabcef2f2fd61b5861ccae1751791f34**
(`gate-measured-head.txt`). Final paired-guard candidate: **8b6b654a**; pinned
baseline: **1d2a790c**, not today's master. Those source/test trees are equal
(§8.1). The later master `ae26c487`-into-hierarchy integration **d53e58f3** is a
different source tree and is **not covered by these measurements**.

Procedure: the existing `verification-recipe.md` governs artifact separation,
certification rebuilds and missing-field treatment. Its original host-wide
serialization/audit-slot rule was superseded by the user's direction to run
independent gates concurrently and adjudicate failed scenarios serially
(recorded in the ledger). The two checkout halves of the final guard stayed
sequential. We do not claim the original empty-host audit-slot procedure ran.
No measurements, tests, builds, lint or formatting were run to assemble this report.

## 1. Verdict

**FAIL — coverage clauses (b), (c), (d) fail.** The original 18 records contain
**17 REFUSED, one emitted** (titanium@60 r4). Original titanium@60 reliability
is **1/4**, not 2/5 and not a rate recomputed after retries or certify rebuilds.

| clause | required | measured | verdict |
| --- | --- | --- | --- |
| (a), Lever 2 plus routing/finalization | titanium/all@60 emits with zero certify errors | r1/r2 router BUDGET; r3 finalization refusal; r4 emits. Its independent same-argv rebuild certifies with zero errors. Serial adjudication emits separately and its rebuild also has zero errors. | **PASS existentially**, reliability **1/4** original; no original file was decoded by the probe |
| (b), Levers 1/2/3 | every other composing cell emits cleanly or meets a named permitted refusal shape | belt3@60 both policies have partial reservations and non-BUDGET corridor/routing failures (Lever 1). zurl2's recorded prefix is BUDGET and cannot establish the required non-BUDGET exception. titanium@15 has partial=0 and spent-wall power pass, not a measured power.coverage conviction. | **FAIL**: permitted-refusal conditions not demonstrated for zurl2 or titanium@15; do not rename clock failures Lever 1 or claim Lever 2 coverage failure |
| (c), Lever 3 | both malls place every block and reach compose | all-products: 9 never placed in both original rounds and serial replay. No-proliferator: 55 never placed/unattempted in both originals, 58 in serial replay. | **FAIL**, block solvers/funding |
| (d), routing/settlement (Levers 1/2 boundary) | titanium/all@15 emits | REFUSED r1/r2 and serial; 4/3/3 unrouted cuts; infill did not run because wall was spent | **FAIL**; not proved to be a matcher partial defect or unpowerable geometry |
| (e), default guard | no CLEAN loss, 0 INVALID, 0 CRASH | baseline72/72 CLEAN; candidate72/72 CLEAN; zero losing, invalid or crash rows | **PASS** at 8b6b654a only |
| Step 1 provenance | §0 committed alone before any measurement | earlier approved rule exists, but no rule-only gate commit | **NOT MET**, disclosed rather than backdated |
| Step 2 freeze | no src/tests changes between large freeze and final guard | 706ddb79→8b6b654a diff empty | **MET for preintegration evidence only**; today's integration diff is nonempty |
| report-only area/wall | publish ratios and budget+6 comparisons | emitted area11297/5727 = 1.972586×; timing table below | no gate threshold applied |

## 2. The eight cells

Every JSON retains the actual URL and argv: `--strategy hierarchical --budget
<60|15> --band portable --candidate-policy <policy> -o <stem>.blueprint.txt`;
**no `--workers`**. `run_cell.py` calls the CLI without monkeypatching.
Names below are exact `large-<cell>-rN` stems. r1 is quoted, differing r2 values
are parenthesized. Wall values are seconds; shell wall is from each `.log`'s
`WALL_S`, not substituted for the JSON's in-process `wall_s`. Load is the
immediately preceding five-sample runnable mean, not load average.

| cell | original verdict | in-process wall | shell wall | runnable load | area / best-known | certify errors by class |
| --- | --- | --- | --- | --- | --- | --- |
| belt3-all-products-b60 | REFUSED (both) | 60.48 (60.97) | 62.279212675 (62.630305183) | 21.6 (21.8) | not emitted | not reached; see §2.2 |
| belt3-no-proliferator-b60 | REFUSED (both) | 43.82 (50.23) | 45.115767838 (51.931909075) | 36 (36.6) | not emitted | not reached; see §2.2 |
| zurl2-all-products-b60 | REFUSED (both) | 61.28 (62.63) | 63.074618632 (64.077381638) | 50.4 (38) | not emitted | not reached; see §2.2 |
| mall-all-products-b60 | REFUSED (both) | 37.0 (37.05) | 38.778718277 (38.864286786) | 24.4 (42.6) | not emitted | not reached; see §2.2 |
| mall-no-proliferator-b60 | REFUSED (both) | 18.11 (17.29) | 19.708348802 (18.898785843) | 30.4 (123) | not emitted | not reached; see §2.2 |
| titanium-glass-all-products-b60 | REFUSED (both) | 28.31 (28.17) | 29.645829292 (29.995961144) | 52.8 (28.2) | not emitted | not reached; see §2.2 |
| titanium-glass-all-products-b15 | REFUSED (both) | 15.5 (15.19) | 17.159173825 (16.486423576) | 19 (42.2) | not emitted | not reached; see §2.2 |
| belt3-all-products-b15 | REFUSED (both) | 11.2 (11.29) | 12.969016945 (13.043521542) | 25.2 (34.8) | not emitted | not reached; see §2.2 |

Titanium@60 additional required rounds (never merged into r1/r2):

| round | verdict | in-process wall | shell wall | load | area / best-known |
| --- | --- | --- | --- | --- | --- |
| r3 | REFUSED | 30.08 | 32.022222481 | 22.2 | not emitted |
| r4 | EMITTED | 27.29 | 28.940626504 | 27.2 | 11297 / 5727 = 1.972586× |

All 18 recorded in-process and shell walls are within their respective budget+6; this is report-only. No area exists for a refusal. All original JSON `validation_errors` maps are `{}`: on a refusal this means no parsed top-level validator error report, **not** zero certify errors. In particular r3 names two finalization findings (§2.2) without a certify report.

### 2.1. Complete CLI stats

The paired table contains every emitted stats key. `MISSING` on successful r4 means the CLI printed no stats line (`stats: {}`), not zero. Counters on refusal records are reported literally; power_uncovered_tiles=0 when infill **did not run** does not prove coverage.

| cell | arm_dispatch_both | arm_dispatch_freeform | arm_dispatch_sequence_pair | blocks | blocks_unattempted | compose_gap | cut_lanes | nogood_skips | player_fed | port_demands | power_infill_towers | power_uncovered_tiles | recut_rounds | reservation_degraded | reservation_missing | reservation_partial | resplits | unrouted_cuts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| belt3-all-products-b60 | 3 | 7 | 4 | 11 | 0 | 2 | 89 | 2 (3) | 0 | 102 | 0 | 0 | 2 | 4 | 5 | 4 (3) | 2 | 18 (23) |
| belt3-no-proliferator-b60 | 14 | 0 | 0 | 14 | 0 | 2 | 130 | 4 | 0 | 168 | 1 (0) | 0 | 0 | 4 | 1 | 4 (3) | 0 | 5 (6) |
| zurl2-all-products-b60 | 1 | 11 (14) | 6 | 17 (19) | 0 | 2 | 127 (135) | 0 | 1 | 144 (152) | 0 | 0 | 1 (2) | 1 | 0 | 1 | 1 (2) | 97 (108) |
| mall-all-products-b60 | 13 | 44 | 6 | 39 | 0 | 0 | 0 | 26 (25) | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 2 | 0 |
| mall-no-proliferator-b60 | 125 (128) | 0 | 0 | 83 (85) | 55 | 0 | 0 | 54 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 2 | 0 |
| titanium-glass-all-products-b60 | 0 | 5 | 1 | 6 | 0 | 2 | 26 | 0 | 0 | 31 | 2 | 0 | 0 | 1 | 0 | 1 | 0 | 2 |
| titanium-glass-all-products-b15 | 0 | 5 | 1 | 6 | 0 | 2 | 26 | 0 | 0 | 31 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 4 (3) |
| belt3-all-products-b15 | 1 | 4 | 4 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| titanium-glass-all-products-b60-r3 | 0 | 5 | 1 | 6 | 0 | 2 | 26 | 0 | 0 | 31 | 3 | 0 | 0 | 1 | 0 | 1 | 0 | 0 |
| titanium-glass-all-products-b60-r4 | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING |

Whole printed stats lines, preserving original ordering and values:

`large-belt3-all-products-b60-r1.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=3 arm_dispatch_freeform=7 arm_dispatch_sequence_pair=4 blocks=11 blocks_unattempted=0 compose_gap=2 cut_lanes=89 nogood_skips=2 player_fed=0 port_demands=102 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=4 reservation_missing=5 reservation_partial=4 resplits=2 unrouted_cuts=18
```

`large-belt3-all-products-b60-r2.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=3 arm_dispatch_freeform=7 arm_dispatch_sequence_pair=4 blocks=11 blocks_unattempted=0 compose_gap=2 cut_lanes=89 nogood_skips=3 player_fed=0 port_demands=102 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=4 reservation_missing=5 reservation_partial=3 resplits=2 unrouted_cuts=23
```

`large-belt3-no-proliferator-b60-r1.log`

```text
  stats hierarchical/no-proliferator: arm_dispatch_both=14 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=14 blocks_unattempted=0 compose_gap=2 cut_lanes=130 nogood_skips=4 player_fed=0 port_demands=168 power_infill_towers=1 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=4 reservation_missing=1 reservation_partial=4 resplits=0 unrouted_cuts=5
```

`large-belt3-no-proliferator-b60-r2.log`

```text
  stats hierarchical/no-proliferator: arm_dispatch_both=14 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=14 blocks_unattempted=0 compose_gap=2 cut_lanes=130 nogood_skips=4 player_fed=0 port_demands=168 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=4 reservation_missing=1 reservation_partial=3 resplits=0 unrouted_cuts=6
```

`large-zurl2-all-products-b60-r1.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=1 arm_dispatch_freeform=11 arm_dispatch_sequence_pair=6 blocks=17 blocks_unattempted=0 compose_gap=2 cut_lanes=127 nogood_skips=0 player_fed=1 port_demands=144 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=1 reservation_degraded=1 reservation_missing=0 reservation_partial=1 resplits=1 unrouted_cuts=97
```

`large-zurl2-all-products-b60-r2.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=1 arm_dispatch_freeform=14 arm_dispatch_sequence_pair=6 blocks=19 blocks_unattempted=0 compose_gap=2 cut_lanes=135 nogood_skips=0 player_fed=1 port_demands=152 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=1 reservation_missing=0 reservation_partial=1 resplits=2 unrouted_cuts=108
```

`large-mall-all-products-b60-r1.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=13 arm_dispatch_freeform=44 arm_dispatch_sequence_pair=6 blocks=39 blocks_unattempted=0 compose_gap=0 cut_lanes=0 nogood_skips=26 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=2 unrouted_cuts=0
```

`large-mall-all-products-b60-r2.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=13 arm_dispatch_freeform=44 arm_dispatch_sequence_pair=6 blocks=39 blocks_unattempted=0 compose_gap=0 cut_lanes=0 nogood_skips=25 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=2 unrouted_cuts=0
```

`large-mall-no-proliferator-b60-r1.log`

```text
  stats hierarchical/no-proliferator: arm_dispatch_both=125 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=83 blocks_unattempted=55 compose_gap=0 cut_lanes=0 nogood_skips=54 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=2 unrouted_cuts=0
```

`large-mall-no-proliferator-b60-r2.log`

```text
  stats hierarchical/no-proliferator: arm_dispatch_both=128 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=85 blocks_unattempted=55 compose_gap=0 cut_lanes=0 nogood_skips=54 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=2 unrouted_cuts=0
```

`large-titanium-glass-all-products-b60-r1.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5 arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26 nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=2 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=1 reservation_missing=0 reservation_partial=1 resplits=0 unrouted_cuts=2
```

`large-titanium-glass-all-products-b60-r2.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5 arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26 nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=2 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=1 reservation_missing=0 reservation_partial=1 resplits=0 unrouted_cuts=2
```

`large-titanium-glass-all-products-b15-r1.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5 arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26 nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=1 reservation_missing=0 reservation_partial=0 resplits=0 unrouted_cuts=4
```

`large-titanium-glass-all-products-b15-r2.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5 arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26 nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=1 reservation_missing=0 reservation_partial=0 resplits=0 unrouted_cuts=3
```

`large-belt3-all-products-b15-r1.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=1 arm_dispatch_freeform=4 arm_dispatch_sequence_pair=4 blocks=9 blocks_unattempted=0 compose_gap=0 cut_lanes=0 nogood_skips=0 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=0 unrouted_cuts=0
```

`large-belt3-all-products-b15-r2.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=1 arm_dispatch_freeform=4 arm_dispatch_sequence_pair=4 blocks=9 blocks_unattempted=0 compose_gap=0 cut_lanes=0 nogood_skips=0 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=0 unrouted_cuts=0
```

`large-titanium-glass-all-products-b60-r3.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5 arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26 nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=3 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=1 reservation_missing=0 reservation_partial=1 resplits=0 unrouted_cuts=0
```

`large-titanium-glass-all-products-b60-r4.log`

```text
MISSING: no CLI stats line
```

### 2.2. Verbatim recorded refusals

These are the complete **recorded CLI strings**, not reconstructed internal failure lists. The production 400-character composition-message cap can truncate a list; counts come from stats, and an unprinted failure-kind census is **unavailable**, not inferred from the prefix. Identical r1/r2 strings are shown once with both filenames.

`large-belt3-all-products-b60` r1 / r2:

```text
no valid layout for all-products after 60s: hierarchical/all-products: unrouted cut(s): magnet: block 7 lane head 5251: no port access corridor (held=0 wants=1 options=0); magnetic-coil: block 8 lane head 7353: no port access corridor (held=0 wants=1 options=0); gear: block 8 lane head 7304: no port access corridor (held=0 wants=1 options=0); magnetic-coil: block 9 lane head 8324: no port access corridor (held=0 wants=1 options=0); gear: block 9 lane head 8275: no po. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-belt3-no-proliferator-b60` r1:

```text
no valid layout for no-proliferator after 60s: hierarchical/no-proliferator: unrouted cut(s): energetic-graphite: block 9 lane head 4819: no port access corridor (held=0 wants=1 options=0); energetic-graphite: block 1 -> block 9: DYNAMIC_ACCESS; gear: block 11 -> block 12: DYNAMIC_ACCESS; gear: block 11 -> block 13: DYNAMIC_ACCESS; iron-ingot: block 5 -> block 11: SEALED_POCKET. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-belt3-no-proliferator-b60` r2:

```text
no valid layout for no-proliferator after 60s: hierarchical/no-proliferator: unrouted cut(s): energetic-graphite: block 9 lane head 4819: no port access corridor (held=0 wants=1 options=0); electric-motor: block 12 -> block 10: DYNAMIC_ACCESS; electromagnetic-turbine: block 10 -> block 11: SEALED_POCKET; electromagnetic-turbine: block 10 -> block 11: SEALED_POCKET; energetic-graphite: block 1 -> block 9: DYNAMIC_ACCESS; gear: block 11 -> block 12: COMMIT_LINK. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-zurl2-all-products-b60` r1:

```text
no valid layout for all-products after 60s: hierarchical/all-products: unrouted cut(s): conveyor-belt-2: block 15 -> block 11: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; electric-motor: block 14 -> block 13: BUDGET; electric-motor: block 14 -> block 13: BUDGET; electric-motor: block 14 -> block 13: BUDGET; electric-motor: block . Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-zurl2-all-products-b60` r2:

```text
no valid layout for all-products after 60s: hierarchical/all-products: unrouted cut(s): conveyor-belt-2: block 16 -> block 18: BUDGET; copper-ingot: block 10 -> block 11: BUDGET; copper-ingot: block 10 -> block 11: BUDGET; copper-ingot: block 10 -> block 11: BUDGET; copper-ingot: block 10 -> block 11: BUDGET; electric-motor: block 12 -> block 13: BUDGET; electric-motor: block 12 -> block 13: BUDGET; electric-motor: block 12 -> block 13: BUDGET; electric-motor: block . Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-mall-all-products-b60` r1:

```text
no valid layout for all-products after 60s: hierarchical/all-products: 9 block(s) never placed, out of re-cut round(s) after 2 of 2 the 36.0s round wall allows: block 20 (steel, titanium-alloy): REFUSED: route evidence from 15 packs at candidate heights 12, 16, 21, 26, 33: failure kinds dynamic-access=6, static-access=9; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 26 (copper-ingot): REFUSED: route evidence from 15 packs at candidate heights 9, 12, 16, 20, 25: failure kinds dynamic-access=15; the same logical net copper-ore/internal failed in every retained pack; investigate that NET-LEVEL routing constraint, not a wholesale packing impossibility; block 27 (copper-ingot): REFUSED: route evidence from 15 packs at candidate heights 9, 12, 16, 20, 25: failure kinds dynamic-access=15; the same logical net copper-ore/internal failed in every retained pack; investigate that NET-LEVEL routing constraint, not a wholesale packing impossibility; block 28 (magnetic-coil): REFUSED: the 9.41201s deadline passed with no completed packing of 4 strips; 11 packs were routed in that time and the best of them still left 1 nets unrouted (worst 5), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec; block 29 (electric-motor): REFUSED: route evidence from 15 packs at candidate heights 15, 20, 26, 32, 41: failure kinds dynamic-access=4, static-access=13; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 30 (electric-motor): REFUSED: route evidence from 15 packs at candidate heights 15, 20, 26, 32, 41: failure kinds dynamic-access=4, static-access=13; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 31 (electric-motor): REFUSED: no pack was ever routed: 1 lane head could not obtain the belt approaches they need (proliferator-3 into ? at (26, 2, 0) (wants 1, held 0, 0 free side(s))); this is a PORT-SEATING defect independent of the packing -- every candidate height produced the same 1 failures; block 32 (conveyor-belt-1, conveyor-belt-2, electromagnetic-turbine): REFUSED: the 9.41201s deadline passed with no completed packing of 5 strips; 8 packs were routed in that time and the best of them still left 1 nets unrouted (worst 5), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec; block 33 (electromagnetic-turbine): REFUSED: route evidence from 15 packs at candidate heights 13, 18, 23, 28, 36: failure kinds dynamic-access=13, static-access=9; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-mall-all-products-b60` r2:

```text
no valid layout for all-products after 60s: hierarchical/all-products: 9 block(s) never placed, out of re-cut round(s) after 2 of 2 the 36.0s round wall allows: block 20 (steel, titanium-alloy): REFUSED: route evidence from 15 packs at candidate heights 12, 16, 21, 26, 33: failure kinds dynamic-access=6, static-access=9; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 26 (copper-ingot): REFUSED: route evidence from 15 packs at candidate heights 9, 12, 16, 20, 25: failure kinds dynamic-access=15; the same logical net copper-ore/internal failed in every retained pack; investigate that NET-LEVEL routing constraint, not a wholesale packing impossibility; block 27 (copper-ingot): REFUSED: route evidence from 15 packs at candidate heights 9, 12, 16, 20, 25: failure kinds dynamic-access=15; the same logical net copper-ore/internal failed in every retained pack; investigate that NET-LEVEL routing constraint, not a wholesale packing impossibility; block 28 (magnetic-coil): REFUSED: the 9.62265s deadline passed with no completed packing of 4 strips; 11 packs were routed in that time and the best of them still left 1 nets unrouted (worst 5), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec; block 29 (electric-motor): REFUSED: route evidence from 15 packs at candidate heights 15, 20, 26, 32, 41: failure kinds dynamic-access=4, static-access=13; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 30 (electric-motor): REFUSED: route evidence from 15 packs at candidate heights 15, 20, 26, 32, 41: failure kinds dynamic-access=4, static-access=13; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 31 (electric-motor): REFUSED: no pack was ever routed: 1 lane head could not obtain the belt approaches they need (proliferator-3 into ? at (26, 2, 0) (wants 1, held 0, 0 free side(s))); this is a PORT-SEATING defect independent of the packing -- every candidate height produced the same 1 failures; block 32 (conveyor-belt-1, conveyor-belt-2, electromagnetic-turbine): REFUSED: the 9.62265s deadline passed with no completed packing of 5 strips; 11 packs were routed in that time and the best of them still left 1 nets unrouted (worst 5), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec; block 33 (electromagnetic-turbine): REFUSED: route evidence from 15 packs at candidate heights 13, 18, 23, 28, 36: failure kinds dynamic-access=13, static-access=9; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-mall-no-proliferator-b60` r1:

```text
no valid layout for no-proliferator after 60s: hierarchical/no-proliferator: 55 block(s) never placed, 18.7s left over 4 wave(s) is under the 5s a block solve is given at all: block 2 (magnet): not attempted; block 3 (magnet): not attempted; block 4 (magnet): not attempted; block 5 (magnet): not attempted; block 6 (magnet): not attempted; block 7 (magnet): not attempted; block 8 (magnet): not attempted; block 9 (magnet): not attempted; block 10 (magnet): not attempted; block 11 (magnet): not attempted; block 12 (magnet): not attempted; block 13 (magnet): not attempted; block 14 (magnet): not attempted; block 15 (magnet): not attempted; block 16 (magnet): not attempted; block 17 (magnet): not attempted; block 18 (magnet): not attempted; block 19 (magnet): not attempted; block 20 (magnet): not attempted; block 21 (magnet): not attempted; block 22 (magnet): not attempted; block 23 (iron-ingot): not attempted; block 24 (iron-ingot): not attempted; block 25 (iron-ingot): not attempted; block 26 (iron-ingot): not attempted; block 27 (iron-ingot): not attempted; block 28 (iron-ingot): not attempted; block 29 (iron-ingot): not attempted; block 50 (magnetic-coil): not attempted; block 51 (magnetic-coil): not attempted; block 52 (magnetic-coil): not attempted; block 53 (magnetic-coil): not attempted; block 54 (electric-motor): not attempted; block 55 (electric-motor): not attempted; block 56 (electric-motor): not attempted; block 57 (electric-motor): not attempted; block 58 (electric-motor): not attempted; block 59 (electric-motor): not attempted; block 60 (electric-motor): not attempted; block 61 (electric-motor): not attempted; block 62 (electric-motor): not attempted; block 63 (electric-motor): not attempted; block 64 (electric-motor): not attempted; block 65 (electric-motor): not attempted; block 66 (electric-motor): not attempted; block 67 (electric-motor): not attempted; block 68 (electromagnetic-turbine): not attempted; block 69 (electromagnetic-turbine): not attempted; block 70 (electromagnetic-turbine): not attempted; block 71 (electromagnetic-turbine): not attempted; block 72 (electromagnetic-turbine): not attempted; block 74 (super-magnetic-ring): not attempted; block 75 (super-magnetic-ring): not attempted; block 76 (super-magnetic-ring): not attempted; block 77 (super-magnetic-ring): not attempted. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-mall-no-proliferator-b60` r2:

```text
no valid layout for no-proliferator after 60s: hierarchical/no-proliferator: 55 block(s) never placed, 19.5s left over 4 wave(s) is under the 5s a block solve is given at all: block 2 (magnet): not attempted; block 3 (magnet): not attempted; block 4 (magnet): not attempted; block 5 (magnet): not attempted; block 6 (magnet): not attempted; block 7 (magnet): not attempted; block 8 (magnet): not attempted; block 9 (magnet): not attempted; block 10 (magnet): not attempted; block 11 (magnet): not attempted; block 12 (magnet): not attempted; block 13 (magnet): not attempted; block 14 (magnet): not attempted; block 15 (magnet): not attempted; block 16 (magnet): not attempted; block 17 (magnet): not attempted; block 18 (magnet): not attempted; block 19 (magnet): not attempted; block 20 (magnet): not attempted; block 21 (magnet): not attempted; block 22 (magnet): not attempted; block 23 (iron-ingot): not attempted; block 24 (iron-ingot): not attempted; block 25 (iron-ingot): not attempted; block 26 (iron-ingot): not attempted; block 27 (iron-ingot): not attempted; block 28 (iron-ingot): not attempted; block 29 (iron-ingot): not attempted; block 50 (magnetic-coil): not attempted; block 51 (magnetic-coil): not attempted; block 52 (magnetic-coil): not attempted; block 53 (magnetic-coil): not attempted; block 54 (electric-motor): not attempted; block 55 (electric-motor): not attempted; block 56 (electric-motor): not attempted; block 57 (electric-motor): not attempted; block 58 (electric-motor): not attempted; block 59 (electric-motor): not attempted; block 60 (electric-motor): not attempted; block 61 (electric-motor): not attempted; block 62 (electric-motor): not attempted; block 63 (electric-motor): not attempted; block 64 (electric-motor): not attempted; block 65 (electric-motor): not attempted; block 66 (electric-motor): not attempted; block 67 (electric-motor): not attempted; block 68 (electromagnetic-turbine): not attempted; block 69 (electromagnetic-turbine): not attempted; block 70 (electromagnetic-turbine): not attempted; block 71 (electromagnetic-turbine): not attempted; block 72 (electromagnetic-turbine): not attempted; block 74 (super-magnetic-ring): not attempted; block 75 (super-magnetic-ring): not attempted; block 76 (super-magnetic-ring): not attempted; block 77 (super-magnetic-ring): not attempted. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-titanium-glass-all-products-b60` r1 / r2:

```text
no valid layout for all-products after 60s: hierarchical/all-products: unrouted cut(s): titanium-glass: block 2 -> block 5: BUDGET; titanium-glass: block 2 -> block 5: BUDGET. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-titanium-glass-all-products-b15` r1:

```text
no valid layout for all-products after 15s: hierarchical/all-products: unrouted cut(s): casimir-crystal: block 4 -> block 5: DYNAMIC_ACCESS; casimir-crystal: block 4 -> block 5: COMMIT_LINK; titanium-glass: block 2 -> block 5: DYNAMIC_ACCESS; titanium-glass: block 2 -> block 5: DYNAMIC_ACCESS; composition power infill: did not run, the composition's wall was already spent before it could start. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-titanium-glass-all-products-b15` r2:

```text
no valid layout for all-products after 15s: hierarchical/all-products: unrouted cut(s): casimir-crystal: block 4 -> block 5: DYNAMIC_ACCESS; titanium-glass: block 2 -> block 5: DYNAMIC_ACCESS; titanium-glass: block 2 -> block 5: DYNAMIC_ACCESS; composition power infill: did not run, the composition's wall was already spent before it could start. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-belt3-all-products-b15` r1 / r2:

```text
no valid layout for all-products after 15s: hierarchical/all-products: 2 block(s) never placed, out of re-cut round(s) after 0 of 0 the 9.0s round wall allows: block 6 (electromagnetic-turbine, magnetic-coil, super-magnetic-ring): REFUSED: deadline exhausted before finding an exact layout; block 7 (electric-motor, gear): REFUSED: deadline exhausted before finding an exact layout. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`large-titanium-glass-all-products-b60-r3.json`:

```text
no valid layout for all-products after 60s: hierarchical/all-products: composed placement refused finalization: no legal DSP latitude band/orientation accepts the final placement: band 200 game.addon_splitter_clearance (3558, 6000): Splitter connection body enters the Spray Coater projected lateral keepout; band 200 geom.collide (6016, 6019): build colliders intersect. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

r4 has no refusal.

### 2.3. The cell that got furthest; separate adjudication and certification

Titanium@60 r4 emitted 81,256 bytes, 5,994 buildings, 116 machines, area 11,297.
That is the first **original gate** emission; earlier Task5b already emitted at
an earlier source tree. r1/r2 still failed two BUDGET cuts each, and r3 routed
all cuts then refused DSP finalization on `game.addon_splitter_clearance` and
`geom.collide`. The original emit fraction remains **1/4**.

The user-requested serial adjudication replays the **eight distinct failed
scenarios**, not 17 individual failures. `serial-failures/original-failures.json`
preserves their mapping. Seven remain refused; only titanium@60 emits. These
are additional diagnosis, never replacements for the original table:

| serial stem | verdict | in-process wall | shell wall | load | never placed | unrouted | partial | missing |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| belt3-all-products-b60 | REFUSED | 61.27 | 63.452666328 | MISSING | none reported | 19 | 3 | 5 |
| belt3-no-proliferator-b60 | REFUSED | 49.27 | 51.113712999 | MISSING | none reported | 6 | 3 | 1 |
| zurl2-all-products-b60 | REFUSED | 60.61 | 62.459152005 | MISSING | none reported | 98 | 1 | 0 |
| mall-all-products-b60 | REFUSED | 37.02 | 38.790954836 | MISSING | 9 | 0 | 0 | 0 |
| mall-no-proliferator-b60 | REFUSED | 17.32 | 19.053795463 | MISSING | 58 | 0 | 0 | 0 |
| titanium-glass-all-products-b60 | EMITTED | 28.24 | 29.837105220 | MISSING | none reported | MISSING | MISSING | MISSING |
| titanium-glass-all-products-b15 | REFUSED | 15.27 | 16.988361705 | MISSING | none reported | 3 | 0 | 0 |
| belt3-all-products-b15 | REFUSED | 10.36 | 12.074269752 | MISSING | 2 | 0 | 0 | 0 |

Full serial stats and verbatim refusals (same missing-field/truncation discipline as originals):

`serial-failures/belt3-all-products-b60.json` / `.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=3 arm_dispatch_freeform=7 arm_dispatch_sequence_pair=4 blocks=11 blocks_unattempted=0 compose_gap=2 cut_lanes=89 nogood_skips=2 player_fed=0 port_demands=102 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=4 reservation_missing=5 reservation_partial=3 resplits=2 unrouted_cuts=19
no valid layout for all-products after 60s: hierarchical/all-products: unrouted cut(s): magnet: block 7 lane head 5251: no port access corridor (held=0 wants=1 options=0); magnetic-coil: block 8 lane head 7353: no port access corridor (held=0 wants=1 options=0); gear: block 8 lane head 7304: no port access corridor (held=0 wants=1 options=0); magnetic-coil: block 9 lane head 8324: no port access corridor (held=0 wants=1 options=0); gear: block 9 lane head 8275: no po. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`serial-failures/belt3-no-proliferator-b60.json` / `.log`

```text
  stats hierarchical/no-proliferator: arm_dispatch_both=14 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=14 blocks_unattempted=0 compose_gap=2 cut_lanes=130 nogood_skips=4 player_fed=0 port_demands=168 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=4 reservation_missing=1 reservation_partial=3 resplits=0 unrouted_cuts=6
no valid layout for no-proliferator after 60s: hierarchical/no-proliferator: unrouted cut(s): energetic-graphite: block 9 lane head 4819: no port access corridor (held=0 wants=1 options=0); electric-motor: block 12 -> block 10: DYNAMIC_ACCESS; electromagnetic-turbine: block 10 -> block 11: SEALED_POCKET; electromagnetic-turbine: block 10 -> block 11: SEALED_POCKET; energetic-graphite: block 1 -> block 9: DYNAMIC_ACCESS; gear: block 11 -> block 12: COMMIT_LINK. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`serial-failures/zurl2-all-products-b60.json` / `.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=1 arm_dispatch_freeform=11 arm_dispatch_sequence_pair=6 blocks=17 blocks_unattempted=0 compose_gap=2 cut_lanes=127 nogood_skips=0 player_fed=1 port_demands=144 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=1 reservation_degraded=1 reservation_missing=0 reservation_partial=1 resplits=1 unrouted_cuts=98
no valid layout for all-products after 60s: hierarchical/all-products: unrouted cut(s): conveyor-belt-2: block 15 -> block 11: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; copper-ingot: block 10 -> block 13: BUDGET; electric-motor: block 14 -> block 13: BUDGET; electric-motor: block 14 -> block 13: BUDGET; electric-motor: block 14 -> block 13: BUDGET; electric-motor: block . Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`serial-failures/mall-all-products-b60.json` / `.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=13 arm_dispatch_freeform=44 arm_dispatch_sequence_pair=6 blocks=39 blocks_unattempted=0 compose_gap=0 cut_lanes=0 nogood_skips=25 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=2 unrouted_cuts=0
no valid layout for all-products after 60s: hierarchical/all-products: 9 block(s) never placed, out of re-cut round(s) after 2 of 2 the 36.0s round wall allows: block 20 (steel, titanium-alloy): REFUSED: route evidence from 15 packs at candidate heights 12, 16, 21, 26, 33: failure kinds dynamic-access=6, static-access=9; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 26 (copper-ingot): REFUSED: route evidence from 15 packs at candidate heights 9, 12, 16, 20, 25: failure kinds dynamic-access=15; the same logical net copper-ore/internal failed in every retained pack; investigate that NET-LEVEL routing constraint, not a wholesale packing impossibility; block 27 (copper-ingot): REFUSED: route evidence from 15 packs at candidate heights 9, 12, 16, 20, 25: failure kinds dynamic-access=15; the same logical net copper-ore/internal failed in every retained pack; investigate that NET-LEVEL routing constraint, not a wholesale packing impossibility; block 28 (magnetic-coil): REFUSED: route evidence from 12 packs at candidate heights 16, 22, 28, 35, 44: failure kinds dynamic-access=22, sealed-pocket=4, static-access=10; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 29 (electric-motor): REFUSED: route evidence from 15 packs at candidate heights 15, 20, 26, 32, 41: failure kinds dynamic-access=4, static-access=13; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 30 (electric-motor): REFUSED: route evidence from 15 packs at candidate heights 15, 20, 26, 32, 41: failure kinds dynamic-access=4, static-access=13; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility; block 31 (electric-motor): REFUSED: no pack was ever routed: 1 lane head could not obtain the belt approaches they need (proliferator-3 into ? at (26, 2, 0) (wants 1, held 0, 0 free side(s))); this is a PORT-SEATING defect independent of the packing -- every candidate height produced the same 1 failures; block 32 (conveyor-belt-1, conveyor-belt-2, electromagnetic-turbine): REFUSED: the 9.03298s deadline passed with no completed packing of 5 strips; 11 packs were routed in that time and the best of them still left 1 nets unrouted (worst 5), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec; block 33 (electromagnetic-turbine): REFUSED: route evidence from 15 packs at candidate heights 13, 18, 23, 28, 36: failure kinds dynamic-access=12, static-access=9; no logical net failed in every retained pack; investigate the DENSITY/SEARCH-SPACE explored, not a proved impossibility. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`serial-failures/mall-no-proliferator-b60.json` / `.log`

```text
  stats hierarchical/no-proliferator: arm_dispatch_both=131 arm_dispatch_freeform=0 arm_dispatch_sequence_pair=0 blocks=87 blocks_unattempted=58 compose_gap=0 cut_lanes=0 nogood_skips=54 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=2 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=2 unrouted_cuts=0
no valid layout for no-proliferator after 60s: hierarchical/no-proliferator: 58 block(s) never placed, 19.6s left over 4 wave(s) is under the 5s a block solve is given at all: block 2 (magnet): not attempted; block 3 (magnet): not attempted; block 4 (magnet): not attempted; block 5 (magnet): not attempted; block 6 (magnet): not attempted; block 7 (magnet): not attempted; block 8 (magnet): not attempted; block 9 (magnet): not attempted; block 10 (magnet): not attempted; block 11 (magnet): not attempted; block 12 (magnet): not attempted; block 13 (magnet): not attempted; block 14 (magnet): not attempted; block 15 (magnet): not attempted; block 16 (magnet): not attempted; block 17 (magnet): not attempted; block 18 (magnet): not attempted; block 19 (magnet): not attempted; block 20 (magnet): not attempted; block 21 (magnet): not attempted; block 22 (magnet): not attempted; block 23 (iron-ingot): not attempted; block 24 (iron-ingot): not attempted; block 25 (iron-ingot): not attempted; block 26 (iron-ingot): not attempted; block 27 (iron-ingot): not attempted; block 28 (iron-ingot): not attempted; block 29 (iron-ingot): not attempted; block 50 (magnetic-coil): not attempted; block 51 (magnetic-coil): not attempted; block 52 (magnetic-coil): not attempted; block 53 (magnetic-coil): not attempted; block 54 (electric-motor): not attempted; block 55 (electric-motor): not attempted; block 56 (electric-motor): not attempted; block 57 (electric-motor): not attempted; block 58 (electric-motor): not attempted; block 59 (electric-motor): not attempted; block 60 (electric-motor): not attempted; block 61 (electric-motor): not attempted; block 62 (electric-motor): not attempted; block 63 (electric-motor): not attempted; block 64 (electric-motor): not attempted; block 65 (electric-motor): not attempted; block 66 (electric-motor): not attempted; block 67 (electric-motor): not attempted; block 68 (electromagnetic-turbine): not attempted; block 69 (electromagnetic-turbine): not attempted; block 70 (electromagnetic-turbine): not attempted; block 71 (electromagnetic-turbine): not attempted; block 72 (electromagnetic-turbine): not attempted; block 74 (super-magnetic-ring): not attempted; block 75 (super-magnetic-ring): not attempted; block 76 (super-magnetic-ring): not attempted; block 77 (super-magnetic-ring): not attempted; block 78 (circuit-board): not attempted; block 79 (circuit-board): not attempted; block 80 (sorter-1, sorter-2): not attempted. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`serial-failures/titanium-glass-all-products-b60.json` / `.log`

```text
EMITTED; CLI stats MISSING
```

`serial-failures/titanium-glass-all-products-b15.json` / `.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=0 arm_dispatch_freeform=5 arm_dispatch_sequence_pair=1 blocks=6 blocks_unattempted=0 compose_gap=2 cut_lanes=26 nogood_skips=0 player_fed=0 port_demands=31 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=1 reservation_missing=0 reservation_partial=0 resplits=0 unrouted_cuts=3
no valid layout for all-products after 15s: hierarchical/all-products: unrouted cut(s): casimir-crystal: block 4 -> block 5: DYNAMIC_ACCESS; titanium-glass: block 2 -> block 5: DYNAMIC_ACCESS; titanium-glass: block 2 -> block 5: DYNAMIC_ACCESS; composition power infill: did not run, the composition's wall was already spent before it could start. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

`serial-failures/belt3-all-products-b15.json` / `.log`

```text
  stats hierarchical/all-products: arm_dispatch_both=1 arm_dispatch_freeform=4 arm_dispatch_sequence_pair=4 blocks=9 blocks_unattempted=0 compose_gap=0 cut_lanes=0 nogood_skips=0 player_fed=0 port_demands=0 power_infill_towers=0 power_uncovered_tiles=0 recut_rounds=0 reservation_degraded=0 reservation_missing=0 reservation_partial=0 resplits=0 unrouted_cuts=0
no valid layout for all-products after 15s: hierarchical/all-products: 2 block(s) never placed, out of re-cut round(s) after 0 of 0 the 9.0s round wall allows: block 6 (electromagnetic-turbine, magnetic-coil, super-magnetic-ring): REFUSED: deadline exhausted before finding an exact layout; block 7 (electric-motor, gear): REFUSED: deadline exhausted before finding an exact layout. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.
```

**Two independent certify rebuilds, not two extra original rounds:**

| original emitted case | separate certify record | exit / ok | errors_total / full errors_by_check | buildings / area | Tesla towers (2201) / splitters (2020) |
| --- | --- | --- | --- | --- | --- |
| large titanium@60 r4 | `large-titanium-glass-all-products-b60-r4-certify.json` | 0 / true | 0 / `{}` | 5994 / 11297 | 62 / 80 |
| serial titanium@60 | `serial-failures/titanium-glass-all-products-b60-certify.json` | 0 / true | 0 / `{}` | 5994 / 11297 | 62 / 80 |

Both reports also record `power_coverage_findings=0`, `convicted=[]`, and
`convicted_item_ids={}`. Their argv preserve the same URL, policy, budget and
strategy with a new output stem. The probe **rebuilds** and certifies its own
placement; it does not decode or certify the bytes emitted by the earlier CLI
run. Thus the evidence demonstrates zero-error same-argv rebuilds, not a bytewise
certification of those two earlier files. Their `.blueprint.txt`, `.json`, `.log`,
`-load.txt` and `.shellwall.txt` are preserved separately.

| certify stem | shell wall | load |
| --- | --- | --- |
| large-titanium-glass-all-products-b60-r4-certify | 29.251257120 | MISSING |
| serial-failures/titanium-glass-all-products-b60-certify | 28.872547117 | MISSING |

## 3. Where the strategy dies, in production order

These are comparisons to each implementer's **own earlier measurements**, not
claims that a task's test proof measured the whole final build. Immutable source
locations throughout §§3–7 refer to **706ddb79**, before integration.

1. **Block funding / exact preparation (Tasks6–7, Lever3).** Task6's
   `exact-floor.md` measured all **25/25** block-budget sweep cells refusing:
   15 expansion-budget failures (blocks1/4/17, walls roughly2.0–3.7s), ten
   deadline failures (blocks20/21). Its selected **21.0s** floor exceeds the
   production20.0s cap, so no-proliferator blocks race both arms. The deadline
   experiment selected budget1.0s, observed success ceiling1.25s; this report
   does not re-run it or infer a new ceiling. Task7's `arm-rule.md` post-fix r5–r8
   left six unplaced in3/4 and starved70 in1/4; its redundant-arm-list fix did
   **not** remove starvation. Final original mall/no-proliferator instead
   starves55/55 (serial58): agreement that abstention and its failure mode are
   live, **not agreement with a stable six-unplaced outcome**. Task7's
   mall/all-products nine-unplaced result repeats9/9 (serial9), and final
   dispatch44/6/13 agrees with theirs. `hierarchy/strategy.py:652–713` owns the
   shared arms list, jobs/waves, funding refusal and block-budget assignment;
   no new starvation threshold was introduced.
2. **Remaining pack search (Task8, Lever3).** `packer-defect.md` measured the
   captured recut steel/titanium-alloy block20, not a guessed initial block.
   Its60s replay refused in**5.329457168933004s**:15 packs, heights12/16/21/26/33,
   static-access9/dynamic-access6, no skipped height, no BUDGET and no logical
   net common to every failure. The exact10.12666118494235s allocated-budget
   replay refused in**7.328826766926795s**, same bound. The final mall/all-products
   refusal repeats that exact15-pack/9+6 diagnostic. Task8 therefore delivered
   its permitted **density/search-space bound**, not a packer repair or a
   proof of geometric impossibility (`freeform.py:19912`). The original60s
   replay's runnable load remains missing; the corroborating replay owns5.6.
3. **Reservation and top-up (Tasks1–3 plus4b, Lever1).** Task1's tested partial
   match and Task2's degraded/partial telemetry are visibly live: final belt3/all
   partial4(3), degraded4, missing5; belt3/no-proliferator partial4(3),
   degraded4, missing1; zurl2 partial1, degraded1, missing0. This confirms the
   payload, not the premise that every partial is better routing ground.
   Task3's `oracle-vs-router.md` at ca72fc6d measured belt3 missing0→16,
   unrouted18→32, partial5; zurl2 missing0→11, unrouted71→100, partial3,
   with non-BUDGET2→11 and BUDGET69→89. It documented a **regression** before
   top-up, despite lower after-load. Final belt3 missing5 and cuts18(23),
   zurl2 missing0 and cuts97(108), are post-top-up observations, **not a replay
   of Task3's earlier source**. Task4b's held-corridor-safe top-up is at
   `compose.py:810`; `reservation.complete` stops the ladder at1137. Degraded
   or partial counts falling to1 can mean an earlier complete topped-up rung,
   not increased matcher convergence. Final missing0 in zurl2 does not imply
   routability; its prefix is BUDGET and the full kind census is unavailable.
4. **Cut routing, then composition power (Tasks4–5/5b, Levers1–2).**
   `compose.py:1238` routes;1278 runs power infill afterwards. Task5's two
   `power.md` pre-top-up runs had missing3, cuts4, partial/degraded5/5,
   infill1 and uncovered0, but refused before certify: three held=0 cuts
   numerically matched missing3 (consistent with, not proof of a per-demand
   bijection). Task5b repaired that earlier regression: two originals emitted,
   and across its two originals plus two rebuilds three emitted and one
   failed finalization. Its successful certify rebuild had5994 buildings,
   area11297,62 towers,80 splitters and zero errors versus v3's
   `{power.coverage: 4}`. Final Task9 reproduces zero-error certification on
   **two separate rebuilds**, and refused titanium60 r1/r2/r3 show missing0,
   infill2/2/3, uncovered0. Successful r4 has **no printed stats**; borrowing
   earlier infill counts would be false. Titanium15 runs out of composition
   wall before infill; its zero counters cannot confirm Task4's coverage
   payload at that budget. No final power.coverage conviction was recorded.
5. **Finalization (Task5b residual, not a new fix).** Final titanium60 r3 again
   reaches `strategy.py:854–858` and refuses DSP projection despite cuts0,
   missing0, uncovered0. This agrees with Task5b's newly reachable keepout
   residual but not its earlier3/4 emit rate: the original gate measures1/4,
   with the other two failures earlier at BUDGET cuts. No source review is
   reopened and no new geometry repair is claimed.

Task1 changed the **default freeform path** as well as hierarchy. Its safety
is not inferred from hierarchy-only unit tests: Task8's unconditional guard
and the separate final guard (§4) supply the paired corpus observations.

## 4. The paired default-unchanged corpus guard

Final `judge-round1.txt` identifies baseline1d2a790 and candidate8b6b654:

| observation | baseline | candidate |
| --- | --- | --- |
| distinct cells / CLEAN | 72 / 72 | 72 / 72 |
| freeform CLEAN | 36 | 36 |
| sequence-pair CLEAN | 36 | 36 |
| REFUSED / INVALID / CRASH | 0 / 0 / 0 | 0 / 0 / 0 |
| CLEAN→not-CLEAN | — | 0 |
| p95 build wall | 31.66s | 31.48s |
| total build wall | 1482.0s | 1455.2s |
| wall_overshoot_s rows / max / over-allowance | 72 / 0.000s / 0 | 72 / 0.000s / 0 |
| preceding runnable load | 10.6 | 15.2 |

No status moved, so there is **no status-movement both-trees control to run or
claim**. Six areas moved, report-only: universe-matrix/output-products freeform
32616→22464 and sequence-pair15480→19458; universe-matrix/no-proliferator
freeform31898→39312 and sequence-pair21420→17836; plastic/no-proliferator
sequence-pair722→684; super-magnetic-ring/no-proliferator freeform2257→2183.
Geometric mean candidate/base area ratio0.99715 (freeform0.99454,
sequence-pair0.99976). No marginal-speed claim follows from this one round.

The generic comparator's result remains verbatim:

```text
clean 72  refused 0  invalid 0  crashed 0  paired 72  area ratio 0.9971  p95 31.5s
  FAIL p95 wall 31.5s exceeds 30.0s
FAIL
```

That absolute30s p95 failure is **not erased or relabeled**. Clause(e) instead
asks for status regressions, INVALID and CRASH; both trees exceed the generic
absolute timing threshold and neither has an over-allowance wall tail.

The earlier Task8 guard is separate: `task8-guard/` has baseline1d2a790c and
candidateb4e3f513,72/72 CLEAN each, zero losses/invalid/crash/over-allowance,
p95 baseline31.98s / candidate31.57s, raw comparator FAIL. It satisfies the
unconditional default-path exposure obligation; it is not substituted for the
final8b6b654a guard. The final execution transcript records clean8b6b654a at
start/return, both72-row halves and restoration to8b6b654a; its transcript is
in the ignored ledger directory (provenance table below). The final script no
longer claims a host-wide empty audit slot under the user's revised rule.

## 5. Next three measured levers, ranked

Rank balances **distance to a repeatable first blueprint** with the number of
blocked outcomes; raw cut counts are not commensurate with unplaced blocks.
These are measurement-backed residual locations, not an additional plan or a
claim that a proposed fix is already proved. All `src/flab2bp/layout/` paths
below are pinned to **706ddb79**, not the postintegration working file's line
numbers. Task1's default-path exposure remains protected by the paired guard;
changing its matcher again cannot be called hierarchy-only.

| rank | measured lever and immutable source location | number and distance |
| --- | --- | --- |
| 1 | Titanium reliability at the composition/finalization boundary: `706ddb79:src/flab2bp/layout/hierarchy/compose.py:1238,1278`; `706ddb79:src/flab2bp/layout/hierarchy/strategy.py:854–858` | Nearest existing blueprint: original60s succeeds only1/4; r1/r2 have2 BUDGET cuts each, r3 has0 unrouted but finalization keepout/collision.15s fails2/2 originals plus serial with4/3/3 cuts and infill not run. Successful rebuilds prove coverage can be clean; they do not eliminate either failure stage. |
| 2 | Mall block funding and bounded search (Lever3): `706ddb79:src/flab2bp/layout/hierarchy/strategy.py:680–703,1198`; `706ddb79:src/flab2bp/layout/freeform.py:19912` | No-proliferator55/55 unattempted,58 serial (83/85 original total blocks); all-products9/9/9 never placed. Earlier post-fix3/4 six-unplaced versus1/4 starvation70 remains a warning, not a stable outcome. The named block20 exhausts15 packs (static9/dynamic6) in5.329s even at60s. Both malls are still before compose. |
| 3 | Post-top-up corridor/routing completion (Lever1 where non-BUDGET evidence permits): `706ddb79:src/flab2bp/layout/freeform.py:11790`; `706ddb79:src/flab2bp/layout/hierarchy/compose.py:810,1137,1238` | Largest cut count: zurl2 unrouted97/108 (serial98) despite missing0 and partial1, but its truncated BUDGET prefix does not convict matcher geometry. Belt3/all has missing5 and cuts18/23 (serial19); no-proliferator missing1, cuts5/6 (serial6), named held=0/DYNAMIC_ACCESS/SEALED_POCKET. Partial return is delivered; full routability is not. |

## 6. Residuals still open

- Cross-build solved-block cache: not planned here; the related background
  compound block cache already has its own plan (`42c9e0e`).
- Outcome-driven strip cap: `_ShapeNoGood` is within-build `(shape, arm)`
  memory consulted before solves; per-cut router outcomes arrive afterwards.
  This remains a cross-build-memory question, not closed by Task7's arms cache.
- Pre-placed bus corridor (design§4E): killed by measurement twice; revisit
  only if a gate measures a rung rejected for a sealed-trunk reason. A cut's
  `SEALED_POCKET` router refusal is not evidence of that rung condition.
- Task8 packer defect: only the permitted density/search-space diagnostic
  bound landed. No common failing logical net, no skipped-height proof of a
  local repair, and no claim that more wall rescues its15 packs.
- Titanium reliability,15s coverage and both mall composition clauses remain
  open (§§1,5). Task7's one-of-four post-fix funding starvation remains recorded.
- Successful CLI stats are missing; composition refusals are truncated and
  not full per-cut kind censuses. Zero power counters can mean infill did not
  run. These are evidence limits, not extra work initiated by this report.
- The premeasurement rule-only commit was missed. The freeze held through the
  measured guard, but integration is a new source tree, not an inert doc wave.
- Inherited sequence-alignment known-red from the plan is not repaired or
  suppressed here. Existing completed recovery verification is ledger evidence,
  not a new whole-project test result attributed to Task9.

## 7. As-shipped constants and behavior (measured tree706ddb79)

This supersedes v3's constants for the measured candidate only; it does not
claim the later integration was measured.

| surface | shipped value / behavior | immutable file:line under src/flab2bp/layout/ |
| --- | --- | --- |
| exact sequence-pair floor | 21.0s, selected fallback20+1 after25/25 refusals; not an observed success threshold | `706ddb79:hierarchy/dispatch.py:81` |
| arm thresholds | small strips6; uncovered items-above-one-belt8; uncovered strips85; coater-free with budget below21 races both | `706ddb79:hierarchy/dispatch.py:41–43,170–180` |
| block budgets | min5.0 / max20.0; share remaining / rounds_left / waves, clamped; underfunded round can refuse | `706ddb79:hierarchy/strategy.py:168–169,680–703` |
| settlement reserve | min5.0 / max40.0 / share0.4 | `706ddb79:hierarchy/strategy.py:191–193` |
| recuts/resplits | MAX_RECUT_ROUNDS2, MAX_RESPLIT_ATTEMPTS4; allowed recuts min(2,max(0,int(round-wall//5)-1));15s total leaves9s round wall and0 recuts | `706ddb79:hierarchy/strategy.py:198–205` |
| block pool / worker share | _BLOCK_WORKERS4, _POOL_CAP32; CLI passes workers=None unchanged | `706ddb79:hierarchy/strategy.py:213–223` |
| compose gap / band | DEFAULT_GAP2, MIN_GAP2; portable band rows160 | `706ddb79:hierarchy/strategy.py:208`; `706ddb79:hierarchy/compose.py:64,71` |
| ladder | (2,4,6,8,12,16); ladder wall share0.4; reservation share0.25 | `706ddb79:hierarchy/compose.py:90,106,118` |
| matcher | _ACCESS_CUT_ROUNDS8; preserve surveyed safe partial with converged=False rather than assert complete; degraded and partial remain distinct | `706ddb79:freeform.py:376,11790` |
| held top-up / rung acceptance | top up missing demands without unstaking held corridors; report remaining missing; first complete topped-up rung can stop ladder, not proof of convergence | `706ddb79:hierarchy/compose.py:810,1137` |
| composition power | linked legal infill after cut routing; power_uncovered distinct from unrouted_cuts; named spent-wall refusal when pass cannot start | `706ddb79:hierarchy/compose.py:1238,1278–1295`; `706ddb79:freeform.py:16033` |
| final settlement | compact, finalize, certify composed placement, not per-block certificates | `706ddb79:hierarchy/strategy.py:851–858` |
| wall allowance | RACE_COMPLETION_GRACE_S6.0, report-only for large gate | `pipeline.py` / approved rule §0 |

## 8. Files and provenance

Evidence paths in this report are relative to
`docs/superpowers/evidence/2026-09-07-hierarchical-v4/` unless qualified.

- `gate-measured-head.txt`; unchanged raw `large-*-r[1234].{json,log,stdout.txt}`,
  per-run `-load.txt`, and the single original r4 blueprint. Shell walls live in
  the corresponding logs; separate certify runs own shellwall sidecars.
- `serial-failures/original-failures.json`, eight scenario JSON/log/load/wall
  sets, its titanium blueprint and its separate certify output set.
- The two `*-certify.json` records in§2.3 and their own blueprints/logs/loads/walls.
- `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`, load sidecars,
  `judge-round1.txt`, `compare-round1.txt`; separate `task8-guard/` artifacts.
- `run_cell.py`, `run_large.sh`, `run_guard.sh`, `judge.py`, `certify_probe.py`
  and the existing `verification-recipe.md` preserve the established harness.
  The recipe is a procedure, not proof that every original instruction ran.
- Earlier task evidence: `oracle-vs-router.md`, `power.md`, `exact-floor.md`,
  `arm-rule.md`, `packer-defect.md` and their named sidecars. These are earlier
  sources, not replacements for Task9 observations.
- This reporting change touches only `gate.md`, `docs/speedup-idea-backlog.md`
  and the ignored `.superpowers/sdd/2026-09-07-hierarchical-v4/progress.md`.
  No raw artifacts or production behavior change.

### Figures / required facts without a committed raw measurement carrier

Ordinary gate figures above are derivable from the named raw artifacts; the
following exceptions and unavailable fields are explicit. A missing value is
never filled with zero or borrowed from a neighboring run.

| fact / missing field | tree / authority | cited here | availability / repeatability |
| --- | --- | --- | --- |
| rule-only preregistration commit | before706ddb79; rule actually present in approved51d211c1 plan | §0 / §1 | unavailable because not performed; cannot be retroactively recreated |
| original successful r4 stats; serial successful stats |706ddb79 / final source-equivalent candidate | §2.1–2.3 | CLI did not print them; new instrumentation/run would be new evidence, not recover the missing line |
| full internal kind census of truncated composition refusals |706ddb79 originals and serial scenarios | §1 / §2.2 / §5 | unavailable from400-character CLI prefix; raw stats retain totals, not identities |
| certification of the original emitted byte strings themselves |706ddb79 | §2.3 | not performed by rebuild probe; only separate rebuilt placements certified |
| block20 original60s replay runnable load | Task8 `block-20-b60-r2.json` source stage documented by packer-defect.md | §3 | not recorded; a new run cannot recover historical load |
| clean-start/restore transcript and user concurrency override; prior review verdicts | ignored `.superpowers/.../task9-final-guard.log` and progress ledger, source8b6b654a | §0 / §4 | not a committed raw log; final JSONLs independently identify measured revisions/counts; rule change is recorded session authority, not a timing measurement |
| preintegration source-diff emptiness; integration diff totals | immutable Git objects706ddb79,8b6b654a,d53e58f3 | §8.1 | reproduced by read-only object comparison while assembling this report; commands/output below; no build measurement |

### 8.1. Did src/tests change after measurement?

**Between the large-cell freeze and final paired guard: NO.** Read-only
comparison of the immutable revisions returned exactly empty stdout:

```text
git diff --no-ext-diff --stat 706ddb79 8b6b654a -- src tests
```

Output: **EMPTY (zero bytes)**. The evidence-only guard candidate is therefore
source/test-equivalent to the declared large-cell freeze. This closes the
preintegration version of v3's source-drift residual, not the missing
preregistration step.

**By today's master-into-hierarchy integration: YES.** Main's integration
revision isd53e58f3 (masterae26c487 merged into hierarchy), outside the measured
coverage above. The same comparison to that immutable integration revision:

```text
git diff --no-ext-diff --stat 706ddb79 d53e58f3 -- src tests
 src/flab2bp/cli.py                        |   35 +-
 src/flab2bp/layout/base.py                |    1 +
 src/flab2bp/layout/coater_mode.py         |   62 ++
 src/flab2bp/layout/freeform.py            | 1033 +++++++++++++++++++++++------
 src/flab2bp/layout/hierarchy/compose.py   |    4 +
 src/flab2bp/layout/hierarchy/partition.py |    2 +
 src/flab2bp/layout/markers.py             |  128 +++-
 src/flab2bp/layout/sequence_solver.py     |   10 -
 src/flab2bp/layout/strip_variants.py      |  196 ++++--
 src/flab2bp/layout/validate.py            |  484 +++++++++++++-
 src/flab2bp/pipeline.py                   |   24 +
 src/flab2bp/rates/candidates.py           |   52 +-
 src/flab2bp/spec.py                       |   58 +-
 src/flab2bp/web/payload.py                |   49 ++
 tests/conftest.py                         |   32 +
 tests/lab/test_data.py                    |   22 +
 tests/layout/hierarchy/test_compose.py    |   20 +
 tests/layout/test_coater_node.py          |  430 ++++++++++++
 tests/layout/test_freeform.py             |  672 ++++++++++++++++---
 tests/layout/test_markers.py              |  120 +++-
 tests/layout/test_sequence_solver.py      |  198 +++++-
 tests/layout/test_strip_variants.py       |  234 ++++++-
 tests/layout/test_validate.py             |  682 ++++++++++++++++++-
 tests/rates/test_candidates.py            |  135 +++-
 tests/scripts/test_item_sweep.py          |  196 ++++++
 tests/test_cli.py                         |   37 ++
 tests/test_spec.py                        |   28 +-
 27 files changed, 4522 insertions(+), 422 deletions(-)
```

The literal plan requirement for an empty diff to the **live integration HEAD**
is therefore **not met by this old evidence**. No claim that the integration
changes are inert, no relabeling of measured revisions, and no new measurements
are made here. Main owns integration verification and merge decisions.

**Document review boundary:** Task9/P2 review is confined to these evidence
claims, their arithmetic/provenance, prescribed sections and backlog/ledger
accounting. Earlier completed source reviews are not restarted. This report
neither approves master integration nor requests another source-fix wave; any
later source behavior claim needs its own correctly identified evidence.
