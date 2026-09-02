# Task 11 gate record

Commit under test: 7fe5d78 (evaluation-throughput)
Baseline commit (Task 1): d4f7d99

Controller ruling: the Step 2 per-phase profile goals are the plan's
argument, not the acceptance gate. The binding gate is the 30 s corpus
audit (72/72 CLEAN, INVALID 0, CRASH 0, wall p95 <= 30 s, paired area no
worse than baseline beyond the noise floor). Step 2's result stands as a
recorded miss below; it is not a gate condition.

## Step 1: corpus-wide preparation parity

Last line of `prepare-parity.txt`:

```
PARITY 36 specs
```

Exit code 0. 36/36 corpus specs produced structurally identical
`_PreparedRoutingProblem` values from a cold private cache and from the
shared `geometry_memo` cache, across two repeats each.

## Step 2: before/after profile (recorded miss, not a gate condition)

Task 2 Step 5 loop re-run unchanged, written to `profile-after.jsonl`.
Comparison table (one line per `(url_id, strategy, budget_s)` key; the key
omits candidate policy, so each line reflects the last policy iterated for
that strategy -- `output-products` for `universe-matrix`):

```
('universe-matrix', 'freeform', 15.0) prepare first 2.04 -> 1.95 astar 7.06 -> 1.56 wall 15.0 -> 16.1 REFUSED: -> REFUSED:
('universe-matrix', 'sequence-pair', 15.0) prepare first 1.96 -> 1.87 astar 2.73 -> 0.51 wall 15.2 -> 12.8 REFUSED: -> REFUSED:
('quantum-chip', 'freeform', 15.0) prepare first 1.14 -> 1.03 astar 3.03 -> 0.92 wall 14.7 -> 13.8 OK -> OK
('plastic', 'freeform', 15.0) prepare first 1.17 -> 1.15 astar 0.02 -> 0.00 wall 7.8 -> 8.4 OK -> OK
```

Goal: first-candidate `prepare` on `universe-matrix` <= 1.0 s, `astar_s`
<= 0.2 s. FAIL: measured first-candidate `prepare` 1.87 s - 4.62 s
(all 6 `universe-matrix` rows, both before and after) against the 1.0 s
goal; measured `astar_s` 0.42 s - 7.06 s against the 0.2 s goal. Later
candidates in the SAME run warm through the shared `geometry_memo` cache:
in most rows the second (and third) candidate's `prepare` drops to
roughly 0.5 s - 1.7 s (e.g. `profile-after.jsonl` universe-matrix
freeform/no-proliferator: `[2.19, 1.66, 0.53]`; universe-matrix
sequence-pair/no-proliferator: `[2.19, 1.25]`; universe-matrix
freeform/output-products: `[1.95, 1.43, 1.57]`; universe-matrix
sequence-pair/output-products: `[1.87, 1.11]`). One row does not warm that
far: universe-matrix sequence-pair/all-products stays at 2.46 s (before)
/ 3.95 s (after) on its second candidate, driven by `coater_frame_bans`
(2.41 s / 3.72 s), not a memo miss.

## Step 3: three-round 30 s corpus audit

Ran `scripts/audit.py --budget 30 --jobs 16 --json` three times, one at a
time, foreground, nothing else running.

| round | clean | refused | invalid | crashed | wall p95 | wall max |
|---|---|---|---|---|---|---|
| 1 | 65/72 | 7 | 0 | 0 | 30.5 s | 34.77 s |
| 2 | 65/72 | 7 | 0 | 0 | 30.7 s | 38.97 s |
| 3 | 65/72 | 7 | 0 | 0 | 30.4 s | 40.29 s |

The same 7 cells refused in every round:

- `sequence-pair universe-matrix/no-proliferator` -- deadline exhausted; no legal DSP latitude band/orientation accepts the final placement (band 0 game.blueprint_area: 1334x131 extent needs 131 latitude rows, tallest band holds 160 -- `EBuildCondition.BlueprintAreaCrossTropic`)
- `sequence-pair universe-matrix/all-products` -- deadline exhausted before finding an exact layout
- `freeform universe-matrix/no-proliferator` -- every packing that wired was rejected by the validator (game.blueprint_area: 507x163 extent needs 163 latitude rows, tallest band holds 160)
- `freeform quantum-chip/all-products` -- 30 s deadline passed with no completed packing of 28 strips (7-8 packs routed, best left 1-2 nets unrouted)
- `freeform universe-matrix/output-products` -- 30 s deadline passed with no completed packing of 46 strips (5 packs routed, best left 1 net unrouted)
- `sequence-pair quantum-chip/no-proliferator` -- deadline exhausted before finding an exact layout
- `sequence-pair graphene/output-products` -- no scheduled stage produced an exact layout

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

`--noise-area 0.013` (default). Area ratio across all three rounds
(1.0018, 0.9985, 0.9986) is inside the noise floor -- paired area did not
regress. `audit_compare.py` exits non-zero (1) on all three rounds.

## route_bench BEST lines (idle box, 3 rounds each, `--budget 8` captures)

```
universe-matrix  python  BEST 0.658s  237,755 expansions  2.766 us/exp  digest 28ab321d7b69428d  MATCH
universe-matrix  cython  BEST 0.076s  237,755 expansions  0.322 us/exp  digest 28ab321d7b69428d  MATCH
quantum-chip     python  BEST 0.091s   33,239 expansions  2.730 us/exp  digest 458e3edb4e0b2e2b  MATCH
quantum-chip     cython  BEST 0.011s   33,239 expansions  0.341 us/exp  digest 458e3edb4e0b2e2b  MATCH
plastic          python  BEST 0.002s      374 expansions  5.000 us/exp  digest ca93f81ed612cdd7  MATCH
plastic          cython  BEST 0.000s      374 expansions  0.376 us/exp  digest ca93f81ed612cdd7  MATCH
```

Compiled backend is 8.0x-13.3x lower us/exp than Python across the three
corpora (universe-matrix 8.6x, quantum-chip 8.0x, plastic ~13.3x); digest
MATCH on every corpus/backend pair.

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
| Step 2 profile goal (informational, not a gate condition): first-candidate `prepare` <= 1.0 s | FAIL (1.87 s - 4.62 s) |
| Step 2 profile goal (informational, not a gate condition): `astar_s` <= 0.2 s | FAIL (0.42 s - 7.06 s) |

Overall gate: FAIL. 72/72 CLEAN, wall p95 <= 30 s, and `audit_compare.py`
PASS all fail in all three rounds on the same 7 cells; INVALID, CRASH, and
paired area all pass.
