# Task 11 gate record

Commit under test: 7fe5d78 (evaluation-throughput)
Baseline commit (Task 1): d4f7d99

## Step 1: corpus-wide preparation parity

```
PARITY 36 specs
```

## Step 2: before/after profile

```
('universe-matrix', 'freeform', 15.0) prepare first 2.04 -> 1.95 astar 7.06 -> 1.56 wall 15.0 -> 16.1 REFUSED: -> REFUSED:
('universe-matrix', 'sequence-pair', 15.0) prepare first 1.96 -> 1.87 astar 2.73 -> 0.51 wall 15.2 -> 12.8 REFUSED: -> REFUSED:
('quantum-chip', 'freeform', 15.0) prepare first 1.14 -> 1.03 astar 3.03 -> 0.92 wall 14.7 -> 13.8 OK -> OK
('plastic', 'freeform', 15.0) prepare first 1.17 -> 1.15 astar 0.02 -> 0.00 wall 7.8 -> 8.4 OK -> OK
```

## Step 3: three-round 30 s corpus audit

| round | clean | refused | invalid | crashed | wall p95 | wall max |
|---|---|---|---|---|---|---|
| 1 | 65/72 | 7 | 0 | 0 | 30.5 s | 34.77 s |
| 2 | 65/72 | 7 | 0 | 0 | 30.7 s | 38.97 s |
| 3 | 65/72 | 7 | 0 | 0 | 30.4 s | 40.29 s |

## Step 4: audit_compare vs baseline-budget30.jsonl

```
round 1: clean 65  refused 7  invalid 0  crashed 0  paired 63  area ratio 1.0018  p95 30.5s
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 planet: it needs 131 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.
  FAIL REFUSED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  FAIL REFUSED: freeform quantum-chip/all-products: the 30s deadline passed with no completed packing of 28 strips; 8 packs were routed in that time and the best of them still left 1 nets unrouted (worst 2), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: sequence-pair quantum-chip/no-proliferator: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair graphene/output-products: no scheduled stage produced an exact layout
  FAIL p95 wall 30.5s exceeds 30.0s
FAIL

round 2: clean 65  refused 7  invalid 0  crashed 0  paired 63  area ratio 0.9985  p95 30.7s
  FAIL REFUSED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 planet: it needs 131 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.
  FAIL REFUSED: freeform quantum-chip/all-products: the 30s deadline passed with no completed packing of 28 strips; 8 packs were routed in that time and the best of them still left 1 nets unrouted (worst 2), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  FAIL REFUSED: sequence-pair quantum-chip/no-proliferator: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair graphene/output-products: no scheduled stage produced an exact layout
  FAIL p95 wall 30.7s exceeds 30.0s
FAIL

round 3: clean 65  refused 7  invalid 0  crashed 0  paired 63  area ratio 0.9986  p95 30.4s
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 planet: it needs 131 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.
  FAIL REFUSED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: freeform quantum-chip/all-products: the 30s deadline passed with no completed packing of 28 strips; 7 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  FAIL REFUSED: sequence-pair quantum-chip/no-proliferator: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair graphene/output-products: no scheduled stage produced an exact layout
  FAIL p95 wall 30.4s exceeds 30.0s
FAIL
```

## route_bench BEST lines

```
universe-matrix  python  BEST 0.658s  237,755 expansions  2.766 us/exp  digest 28ab321d7b69428d  MATCH
universe-matrix  cython  BEST 0.076s  237,755 expansions  0.322 us/exp  digest 28ab321d7b69428d  MATCH
quantum-chip     python  BEST 0.091s   33,239 expansions  2.730 us/exp  digest 458e3edb4e0b2e2b  MATCH
quantum-chip     cython  BEST 0.011s   33,239 expansions  0.341 us/exp  digest 458e3edb4e0b2e2b  MATCH
plastic          python  BEST 0.002s      374 expansions  5.000 us/exp  digest ca93f81ed612cdd7  MATCH
plastic          cython  BEST 0.000s      374 expansions  0.376 us/exp  digest ca93f81ed612cdd7  MATCH
```

## Gate conditions

| Condition | Result |
|---|---|
| Step 1 parity: `PARITY 36 specs`, exit 0 | PASS |
| 72/72 CLEAN, three rounds | FAIL (65/72 every round; 7 REFUSED cells, same set each round) |
| INVALID 0, three rounds | PASS (0 every round) |
| CRASH 0, three rounds | PASS (0 every round) |
| wall p95 per cell <= 30 s, three rounds | FAIL (30.5s, 30.7s, 30.4s) |
| paired area no worse than baseline beyond noise floor (`--noise-area 0.013`), three rounds | PASS (area ratio 1.0018, 0.9985, 0.9986) |
| `audit_compare.py` PASS, three rounds | FAIL (exit 1, `FAIL`, all three rounds) |
| Step 2 profile goal: first-candidate `prepare` on `universe-matrix` <= 1.0 s | FAIL (1.87 s - 4.62 s) |
| Step 2 profile goal: `astar_s` on `universe-matrix` <= 0.2 s | FAIL (0.42 s - 7.06 s) |
