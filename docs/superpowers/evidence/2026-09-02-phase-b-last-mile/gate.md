# Phase B last-mile router — corpus gate record

## VERDICT: FAIL

## Commits

- Commit under test: `0d3fe6b` (branch `phase-b-last-mile`; code final at `6780df2`, plus the
  `B_MIN_SECONDS` re-derivation commit `0d3fe6b` made before the audit rounds).
- Task 1 baseline: rounds produced on `725c34e`, committed as `7b06968`.

## Environment

The box is never idle; its load average is dominated by disk I/O wait, not CPU (128 cores, 1 TB
RAM). Per amended Ruling R the timing steps run without waiting, recording `uptime` and
`vmstat 1 3` instead.

Before Step 6 (the three audit rounds):

```
 16:55:58 up 17 days, 22:42,  9 users,  load average: 6.13, 7.52, 7.66
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 1  0      0 1034979704  0 8063324   0    0 52133 15284 23671   4  5  2 93  0  0  0
 3  0      0 1034983944  0 8063324   0    0    20    25 16963 29499 3 1 96  0  0  0
 4  0      0 1034978812  0 8063332   0    0     0 20084 25324 43691 8 1 90  0  0  0
```

Before Step 7 (the two profiler runs):

```
 17:01:14 up 17 days, 22:47,  9 users,  load average: 23.77, 17.32, 11.83
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
11  0      0 1034390440  0 8012236   0    0 52128 15305 23672   4  5  2 93  0  0  0
 7  2      0 1034414392  0 8012236   0    0 66460 154059 24700 54567 1 3 94 1  0  0
 5  1      0 1034369500  0 8012236   0    0 49368 111376 23836 132008 4 3 92 1 0  0
```

## Digests (`digests-after.txt`, all four MATCH)

```
BEST 0.359s  912,831 expansions  0.393 us/exp  digest f4200322f44ef584
captured digest f4200322f44ef584   replay digest f4200322f44ef584   MATCH
BEST 0.128s  150,821 expansions  0.851 us/exp  digest 0b6c1cb650fedecd
captured digest 0b6c1cb650fedecd   replay digest 0b6c1cb650fedecd   MATCH
BEST 2.293s  5 clusters  (run1=5 run2=0, skipped 0 wall-bounded)  sizes 1-3  truncated 0  bounded=2  proved=3  solved=0  digest e04df120a11ae2ba
captured digest e04df120a11ae2ba   replay digest e04df120a11ae2ba   MATCH
BEST 0.022s  6 clusters  (run1=6 run2=0, skipped 0 wall-bounded)  sizes 2-2  truncated 0  bounded=0  proved=4  solved=2  digest 92db9a472fc14fa3
captured digest 92db9a472fc14fa3   replay digest 92db9a472fc14fa3   MATCH
```

The two ROUTE digests equal `digests-before.txt` (`f4200322f44ef584`, `0b6c1cb650fedecd`). The two
CLUSTER digests equal `cluster-bench.txt` (`e04df120a11ae2ba`, `92db9a472fc14fa3`), which changed
by design in the Ruling V round.

## `cluster-bench.txt` BEST lines and the wall floor

```
BEST 2.134s  5 clusters  (run1=5 run2=0, skipped 0 wall-bounded)  sizes 1-3  truncated 0  bounded=2  proved=3  solved=0  digest e04df120a11ae2ba
BEST 0.014s  6 clusters  (run1=6 run2=0, skipped 0 wall-bounded)  sizes 2-2  truncated 0  bounded=0  proved=4  solved=2  digest 92db9a472fc14fa3
```

Observed cluster-search wall seconds, final capture:
`universe-matrix/output-products` n=5 max=0.988s mean=0.307s;
`quantum-chip/all-products` n=6 max=0.003s mean=0.002s.

`B_MIN_SECONDS` derivation (rule: 2 x max, floor 0.35, two decimals):

- Task 9 derived 1.82 from a 0.909 s max.
- In tree before this gate: 1.82.
- Final capture max on this box: 0.988 s -> 2 x 0.988 = 1.976 -> **1.98**.
- Set to 1.98 in `src/flab2bp/layout/last_mile.py` in commit `0d3fe6b`, before the audit rounds,
  so the corpus measured the shipped value. `uv run pytest tests/rules -q` exit 0 (no new
  `LintException` needed: 1.98 coincides with no geometry constant) and
  `uv run pytest tests/layout/test_last_mile.py -q` exit 0.

## `audit_compare` — baseline round 1 vs each candidate round (verbatim)

Name correction: the brief's Step 6 literal `--require-clean` strings
(`freeform/quantum-chip/quantum-chip/all-products`,
`freeform/universe-matrix/universe-matrix/output-products`) do not match the `spec_label` values in
the JSONL. The brief's own confirmation script (Step 6) prints the real names, which are
`freeform/quantum-chip/all-products` and `freeform/universe-matrix/output-products`. Those are the
names used below.

### Round 1

```
clean 65  refused 7  invalid 0  crashed 0  paired 64  area ratio 1.0053  p95 30.9s
  FAIL NOT CLEAN: freeform quantum-chip/all-products: no packing of 28 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  FAIL NOT CLEAN: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 37), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 planet: it needs 131 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.
  note CARRIED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  note CARRIED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  note CARRIED: sequence-pair quantum-chip/no-proliferator: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair graphene/output-products: no scheduled stage produced an exact layout
FAIL
```

### Round 2

```
clean 65  refused 7  invalid 0  crashed 0  paired 64  area ratio 1.0055  p95 31.6s
  FAIL NOT CLEAN: freeform quantum-chip/all-products: no packing of 28 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  FAIL NOT CLEAN: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL p95 wall 31.6s exceeds 31.0s
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 planet: it needs 131 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.
  note CARRIED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  note CARRIED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  note CARRIED: sequence-pair quantum-chip/no-proliferator: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair graphene/output-products: no scheduled stage produced an exact layout
FAIL
```

### Round 3

```
clean 65  refused 7  invalid 0  crashed 0  paired 64  area ratio 1.0040  p95 31.8s
  FAIL NOT CLEAN: freeform quantum-chip/all-products: the 30s deadline passed with no completed packing of 28 strips; 6 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL NOT CLEAN: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 4 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL p95 wall 31.8s exceeds 31.0s
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 planet: it needs 131 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.
  note CARRIED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  note CARRIED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  note CARRIED: sequence-pair quantum-chip/no-proliferator: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair graphene/output-products: no scheduled stage produced an exact layout
FAIL
```

## `audit_compare` — round-paired (baseline round N vs candidate round N), `note` lines elided

```
### PAIRED baseline-round1 vs candidate-round1
clean 65  refused 7  invalid 0  crashed 0  paired 64  area ratio 1.0053  p95 30.9s
  FAIL NOT CLEAN: freeform quantum-chip/all-products: no packing of 28 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  FAIL NOT CLEAN: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 37), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
FAIL
### PAIRED baseline-round2 vs candidate-round2
clean 65  refused 7  invalid 0  crashed 0  paired 65  area ratio 1.0068  p95 31.6s
  FAIL NOT CLEAN: freeform quantum-chip/all-products: no packing of 28 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  FAIL NOT CLEAN: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL p95 wall 31.6s exceeds 31.0s
FAIL
### PAIRED baseline-round3 vs candidate-round3
clean 65  refused 7  invalid 0  crashed 0  paired 65  area ratio 1.0048  p95 31.8s
  FAIL NOT CLEAN: freeform quantum-chip/all-products: the 30s deadline passed with no completed packing of 28 strips; 6 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL NOT CLEAN: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 4 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL p95 wall 31.8s exceeds 31.0s
FAIL
```

## Coverage counts

| round | baseline | candidate |
| --- | --- | --- |
| 1 | 64 CLEAN / 72 (8 REFUSED) | 65 CLEAN / 72 (7 REFUSED) |
| 2 | 65 CLEAN / 72 (7 REFUSED) | 65 CLEAN / 72 (7 REFUSED) |
| 3 | 65 CLEAN / 72 (7 REFUSED) | 65 CLEAN / 72 (7 REFUSED) |

Target was 67/72. Every candidate round refuses the same seven cells:
`sequence-pair/universe-matrix/no-proliferator`, `sequence-pair/universe-matrix/all-products`,
`sequence-pair/quantum-chip/no-proliferator`, `sequence-pair/graphene/output-products`,
`freeform/universe-matrix/no-proliferator`, `freeform/universe-matrix/output-products`,
`freeform/quantum-chip/all-products`.

`freeform/casimir-crystal/all-products` is REFUSED in baseline round 1 and CLEAN in all three
candidate rounds; it is CLEAN in baseline rounds 2 and 3, so it is round-1 noise, not a change.

## Measured wall p95 per round

```
baseline   round 1 31.30s   round 2 30.98s   round 3 30.40s
candidate  round 1 30.91s   round 2 31.57s   round 3 31.81s
```

wall p95 inherited from Phase A, owned by Phase D

## `last_mile_stats` profiler rows (Step 7)

```
universe-matrix | REFUSED: the 30s deadline passed with no completed packing o | NO LAST-MILE STATS
quantum-chip | REFUSED: the 30s deadline passed with no completed packing o | NO LAST-MILE STATS
```

Both rows print `NO LAST-MILE STATS`: **the phase's observational claims are unsupported by this
gate's own measurement.** The counters are unmeasured here, not zero.

Mechanism: `scripts/route_profile.py` emits `"last_mile_stats": {} if placement is None else
_last_mile_row(placement.stats)`. The stats travel on the returned `Placement`, and both cells
refuse (`NoValidLayout`), so no `Placement` is returned and the field is `{}`. This is a
refusal that carries no stats — it is not evidence that the pass never ran.

The last recorded direct measurement of these counters is the Ruling V instrumented round in
`cluster-bench.txt` (taken at `B_MIN_SECONDS` 1.82, one instrumented 30 s run per cell, NOT this
gate's runs):

```
universe-matrix output-products: invocations=5 solved=0 proved=3 bounded=2
    commit_rejected=0 restore_mismatch=0 relation_skipped_siblings=3
    same_source_dropped=3 nodes=125 expansions=4,052,918 seconds=1.403
quantum-chip all-products:       invocations=6 solved=0 proved=4 bounded=2
    commit_rejected=2 restore_mismatch=0 relation_skipped_siblings=4
    same_source_dropped=0 nodes=14  expansions=13,969  seconds=0.019
```

`last_mile_relation_skipped_siblings` against `last_mile_proved`, from that recorded round:
3 skips / 3 proofs on `universe-matrix`, 4 skips / 4 proofs on `quantum-chip` — 100 % of proofs on
both cells are turned away by the sibling gate, so run 2 never fires on this corpus. This is the
measurement the spec's §5.2 follow-ups are gated on. Not acted on in this phase (Ruling W).

`last_mile_same_source_dropped` is not a stats key; it lives only on the report and is therefore
not listed as a stats counter above.

## Gate conditions (Global Constraints, corpus gate)

- `scripts/audit.py --budget 30 --jobs 16`, both strategies, three rounds against Task 1 baselines — **PASS** (three rounds run, 72 cells each).
- 72 cells per round — **PASS** (72/72 in all three rounds).
- freeform `quantum-chip/all-products` CLEAN in every round — **FAIL** (REFUSED in rounds 1, 2 and 3).
- freeform `universe-matrix/output-products` CLEAN in every round — **FAIL** (REFUSED in rounds 1, 2 and 3).
- No cell CLEAN in the baseline non-CLEAN in a candidate round — **PASS** (no `REGRESSION:` line in any comparison, baseline-round-1 or round-paired).
- INVALID 0 — **PASS** (0 in all three rounds).
- CRASH 0 — **PASS** (0 in all three rounds).
- Paired area ratio at most 1.013 — **PASS** (1.0053, 1.0055, 1.0040 vs baseline round 1; 1.0053, 1.0068, 1.0048 round-paired).
- Wall p95 per cell at or under 31 s — **FAIL** (round 1 30.9 s PASS; round 2 31.6 s and round 3 31.8 s exceed 31.0 s). wall p95 inherited from Phase A, owned by Phase D.
- Target 67/72 or better — **FAIL** (65/72 in all three rounds).
- Replay digests unchanged where required — **PASS** (both ROUTE digests MATCH `digests-before.txt`; both CLUSTER digests MATCH `cluster-bench.txt`).
