# Power-tower measured gates (a)–(d)

**Overall: NOT READY.** Gate (a) has status parity and 12/12 deterministic byte parity, not full-corpus layout identity. Gate (b) loses 10 CLEAN cells. Gate (c) fails its six-CLEAN requirement. Gate (d) is unavailable. Refusing unsafe layouts is correct fail-closed behavior, not a successful requested build.

## Provenance and scope

- Authority: original `/home/dannyb/handoff-agents/briefs/power-tower-brief.md`, approved `docs/superpowers/plans/2026-09-07-power-tower.md`, and R8/R12/R13 in the existing progress ledger. This report adjudicates completed files; no build, test, comparator, benchmark, browser rerun, or source edit was performed for this report.
- Frozen baseline: `a140151893ad0d7bcf115e1b34b2aca8f2201ea4`. Frozen measured candidate: `632296de737a63d8bd0132f367a64802d1501327`, with formatting-only working-tree changes per Main's measurement provenance. The `commit` field records the commit, not those unstaged formatting bytes.
- Final source review range: `a1401518..cf4d16a4`. Main identifies the subsequent semantic change in `cf4d16a4` as parent hierarchical canvas clearance only; these measured freeform/sequence-pair arms do not exercise that parent change. This is not a claim that all gates ran at cf4d16a4, nor a substitute for independent final review.
- Immutable raw directory: [`parallel-gates-xUhQwvAA/`](parallel-gates-xUhQwvAA/). The three corpus JSONL files each contain 72 unique `(url_id,strategy,spec_index,budget)` keys, with identical key sets and budget 30. Policies 0/1/2 are no-proliferator/all-products/output-products. The logs record one cell at a time and **128 CP-SAT workers**, not the deterministic helper's workers=1. The arms ran concurrently under Main's orchestration; timings are not isolated serial measurements.
- Corpus driver: `scripts/audit.py`, both strategies, budget 30, jobs 1, cap 7200 seconds; substation selects `--power-tower substation`; candidate default records `power_tower=auto`. Full command/affinity and per-cell pressure are not embedded in corpus JSONL; do not invent them. The log totals are base 1325s, candidate 1289s, substation 1302s. Each log ends **EXIT=1 / NOT CLEAN**.
- Helper: `.superpowers/sdd/2026-09-07-power-tower/gate_power.py`. Deterministic mode uses iron-ingot and magnetic-coil × two strategies × three policies, one base round and two candidate rounds, workers=1, budget 30. Reported mode uses the embedded reported URL, six cells per arm, workers=1, budget 30. The helper re-certifies, directly checks the outward-rounded substation halo against other flat placement rectangles, and encodes with timestamp=0. It records per-cell CPU runnable mean; it does not retry invisibly.
- No generic comparator exit is used as gate PASS. Audit status, default layout parity, deterministic bytes, direct clearance, projected certification, deadlines, and actual game evidence are separate claims below.

## Rule-by-rule adjudication

| Requirement | Evidence and verdict |
|---|---|
| Default exact/Tesla and explicit > URL > default precedence | Browser artifacts show auto selecting URL Substation, explicit Tesla overriding it, and explicit Substation/Wireless. Public contract tests' recorded exit is 0. No default behavior is deliberately broadened. |
| Default corpus zero losing cells | **PASS for status parity only:** 66 CLEAN + 6 REFUSED on each side; zero status movers, INVALID or CRASH. All six universe-matrix fan-out refusals remain refusals. |
| Default byte identity | **PASS on prescribed deterministic controls only:** all 12 cells CLEAN in base and both candidate rounds; saved blueprint files and SHA256 match byte-for-byte. Full 72-cell byte identity is not proven; audit JSONL does not contain blueprints. |
| Default layout/area parity | **Not exact:** three area movers and three tower movers, over four distinct cells; see below. Two area increases warrant serial adjudication, not automatic dismissal as timing. |
| Substation corpus CLEAN count | **Regression:** 56 CLEAN + 16 REFUSED, zero INVALID/CRASH. Ten formerly CLEAN cells refuse. Six directly report power.coverage, three sequence cells report deadline exhaustion, one reports restart exhaustion. R8 remains observable, not closed. |
| Substation tower economy and area | On 56 mutually CLEAN cells: towers 556→152 (3.66× fewer, not 6×); 54 lower and 2 equal. Area 80349→95350 (+18.67%): 51 increases, 3 decreases, 2 unchanged. Refusals are excluded from these totals, never counted as zero-cost successful output. |
| Coverage, connectivity and PowerTooClose | Existing validator meaning remains authoritative; recorded substation validator tests exit 0. Six corpus coverage refusals and reported coverage failures are preserved. No missing connectivity/spacing finding is treated as independent physical proof. |
| Substation footprint and collider clearance | Catalog footprint 5×5, clearance 6×6, centred integer reservation 7×7 (`[-1,6)`). Flat halo tests exit 0; reported freeform/no-proliferator has zero direct halo overlaps. Item2212 remains low-confidence, so corpus CLEAN alone cannot certify belt clearance or physical paste safety. |
| Parent composition clearance | Main's true red/green proof shows old canvas leaves substation (-3,-3,0) free; fixed focused cases and full composer module exit 0. Separate real 15s hierarchical CLI attempt **REFUSED before composition**, exit3. It is not a successful parent end-to-end build. |
| Reported six-cell substation arm | **FAIL:** 1 CLEAN / 5 REFUSED versus default 2 CLEAN / 4 REFUSED. Projected collider, coating-one-run and exact flow failures remain visible in [gate-c-reported-urls.md](gate-c-reported-urls.md). |
| Absolute mixed-input ban, no belt cycles, one-run coating, FactorioLab rate authority | Certification remains the arbiter; no refusal is waived, no rate rewritten, no mixed input or cycle exception introduced. Reported coater and exact quantum-chip deficits explicitly fail. Passing cells mean the recorded certificate accepted them, not new standalone proofs of every invariant. |
| Deadline ≤30s | **Not strictly established:** all arms have atomic completion tails beyond 30s; every observed tail is listed below. No new runaway is demonstrated, but deadline/refusal and changed-area cells remain serial adjudication inputs for Main. |
| Web selector and viewer | Actual saved screenshots and job JSON show all four selection paths; Substation is a large plain box with no endpoint icon while endpoint icons are enabled. This is viewer evidence, not live game geometry. |
| .NET / game paste | **UNAVAILABLE, not PASS.** No power blueprint CheckBuildConditions dump or actual game paste evidence is supplied. The `oracle/` MatchInserter program is not a full paste validator. See [gate-d-dotnet.txt](gate-d-dotnet.txt). |

## Gate (a): default parity distinctions

All six universe-matrix cells refuse with the same producer-lane fan-out reason in baseline and candidate: mass-energy-storage#23 antimatter lane is 10 tiles wide versus 15 consumers for no-proliferator or 12 for either coated policy, targeting universe-matrix#37. Sequence-pair reports this for all four islands. These are inherited failures, not CLEAN and not new regressions.

| Cell | Base area → candidate | Base towers → candidate | Adjudication |
|---|---:|---:|---|
| information-matrix/freeform/all-products | 5369 → 5159 | 33 → 34 | Area improves, tower count differs; not identity |
| super-magnetic-ring/freeform/no-proliferator | 2220 → 2233 | 15 → 16 | Area +13 and tower +1; serial adjudication |
| super-magnetic-ring/freeform/output-products | 2052 → 2052 | 13 → 14 | Tower-only drift; not identity |
| plastic/freeform/all-products | 820 → 850 | 6 → 6 | Area +30; serial adjudication |

All other 62 mutually CLEAN cells match both area and tower count. Area alone matches 63/66. Tower total across all 66 CLEAN defaults is 671→674. Timing-sensitive 128-worker search may explain differences, but that is an inference, not a proved excuse. Deterministic small controls do not cover these movers.

The deterministic proof is recorded in [gate-a-determinism.txt](gate-a-determinism.txt), including all 12 hashes. All 36 saved files were read, compared, and checked against their recorded timestamp-normalized hashes; no layouts were rebuilt. Baseline iron-ingot/freeform/no-proliferator pressure was 80.4, so even that successful byte control is not low-pressure timing evidence.

## Gate (b): complete 72-cell table

`CLEAN` is the raw audit status. `REFUSED` emits no accepted placement: its tower/area cells are `—` (raw audit may contain zero sentinels), not a claimed reduction. Base towers come from `stats.towers`; candidate/substation towers come from explicit `power_towers`. Areas are tiles. Times below are JSONL `seconds`, displayed to 3 decimals; raw files retain full precision. Status is not replaced by a boolean that hides refusal.

| Cell | Base status | Default status | Substation status | Base towers | Default towers | Substation towers | Base area | Default area | Substation area | Base s | Default s | Substation s |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| quantum-chip/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 33 | 33 | 9 | 5610 | 5610 | 5610 | 11.298 | 11.120 | 16.033 |
| quantum-chip/freeform/all-products | CLEAN | CLEAN | CLEAN | 24 | 24 | 6 | 3840 | 3840 | 3850 | 27.656 | 27.021 | 23.729 |
| quantum-chip/freeform/output-products | CLEAN | CLEAN | CLEAN | 29 | 29 | 6 | 4290 | 4290 | 4556 | 18.102 | 16.704 | 22.015 |
| quantum-chip/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 25 | 25 | 6 | 3692 | 3692 | 4725 | 29.523 | 29.377 | 29.291 |
| quantum-chip/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 22 | 22 | 8 | 3300 | 3300 | 5520 | 27.379 | 28.663 | 27.103 |
| quantum-chip/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 22 | 22 | 6 | 3280 | 3280 | 4704 | 29.296 | 29.127 | 29.454 |
| universe-matrix/freeform/no-proliferator | REFUSED | REFUSED | REFUSED | — | — | — | — | — | — | 0.855 | 1.044 | 1.085 |
| universe-matrix/freeform/all-products | REFUSED | REFUSED | REFUSED | — | — | — | — | — | — | 0.333 | 0.453 | 0.358 |
| universe-matrix/freeform/output-products | REFUSED | REFUSED | REFUSED | — | — | — | — | — | — | 0.217 | 0.238 | 0.228 |
| universe-matrix/sequence-pair/no-proliferator | REFUSED | REFUSED | REFUSED | — | — | — | — | — | — | 4.315 | 3.834 | 3.713 |
| universe-matrix/sequence-pair/all-products | REFUSED | REFUSED | REFUSED | — | — | — | — | — | — | 4.395 | 3.644 | 3.491 |
| universe-matrix/sequence-pair/output-products | REFUSED | REFUSED | REFUSED | — | — | — | — | — | — | 3.862 | 3.840 | 3.353 |
| casimir-crystal/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 8 | 8 | 2 | 1107 | 1107 | 1080 | 4.541 | 3.794 | 4.018 |
| casimir-crystal/freeform/all-products | CLEAN | CLEAN | CLEAN | 8 | 8 | 2 | 1161 | 1161 | 1161 | 9.495 | 8.522 | 5.894 |
| casimir-crystal/freeform/output-products | CLEAN | CLEAN | CLEAN | 9 | 9 | 2 | 1100 | 1100 | 1176 | 8.843 | 11.116 | 7.635 |
| casimir-crystal/sequence-pair/no-proliferator | CLEAN | CLEAN | REFUSED | 9 | 9 | — | 1092 | 1092 | — | 31.559 | 31.532 | 30.662 |
| casimir-crystal/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 8 | 8 | 2 | 1100 | 1100 | 1161 | 28.233 | 28.615 | 29.513 |
| casimir-crystal/sequence-pair/output-products | CLEAN | CLEAN | REFUSED | 9 | 9 | — | 1100 | 1100 | — | 30.030 | 30.005 | 30.328 |
| information-matrix/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 50 | 50 | 9 | 7917 | 7917 | 8030 | 13.742 | 14.756 | 15.827 |
| information-matrix/freeform/all-products | CLEAN | CLEAN | CLEAN | 33 | 34 | 11 | 5369 | 5159 | 6254 | 30.048 | 28.217 | 29.485 |
| information-matrix/freeform/output-products | CLEAN | CLEAN | REFUSED | 34 | 34 | — | 5434 | 5434 | — | 26.997 | 26.500 | 28.787 |
| information-matrix/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 28 | 28 | 8 | 4560 | 4560 | 5700 | 30.006 | 28.155 | 29.029 |
| information-matrix/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 25 | 25 | 9 | 3944 | 3944 | 5408 | 27.119 | 27.804 | 26.311 |
| information-matrix/sequence-pair/output-products | CLEAN | CLEAN | REFUSED | 32 | 32 | — | 4905 | 4905 | — | 28.492 | 27.928 | 29.591 |
| processor/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 6 | 6 | 2 | 810 | 810 | 952 | 4.959 | 5.559 | 4.711 |
| processor/freeform/all-products | CLEAN | CLEAN | CLEAN | 7 | 7 | 3 | 918 | 918 | 1089 | 15.120 | 12.255 | 6.506 |
| processor/freeform/output-products | CLEAN | CLEAN | CLEAN | 7 | 7 | 2 | 896 | 896 | 1045 | 9.843 | 9.665 | 5.514 |
| processor/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 7 | 7 | 1 | 810 | 810 | 837 | 31.508 | 31.035 | 30.832 |
| processor/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 7 | 7 | 1 | 918 | 918 | 1050 | 28.686 | 28.797 | 28.784 |
| processor/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 7 | 7 | 2 | 810 | 810 | 899 | 30.081 | 29.911 | 29.986 |
| energy-matrix/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 5 | 5 | 1 | 616 | 616 | 630 | 1.017 | 1.315 | 1.626 |
| energy-matrix/freeform/all-products | CLEAN | CLEAN | CLEAN | 5 | 5 | 1 | 742 | 742 | 800 | 2.257 | 2.768 | 3.134 |
| energy-matrix/freeform/output-products | CLEAN | CLEAN | CLEAN | 5 | 5 | 1 | 572 | 572 | 800 | 1.970 | 2.510 | 2.758 |
| energy-matrix/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 5 | 5 | 1 | 504 | 504 | 672 | 31.259 | 31.662 | 31.558 |
| energy-matrix/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 5 | 5 | 1 | 756 | 756 | 800 | 30.852 | 30.851 | 31.102 |
| energy-matrix/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 5 | 5 | 1 | 572 | 572 | 800 | 31.158 | 32.155 | 30.390 |
| super-magnetic-ring/freeform/no-proliferator | CLEAN | CLEAN | REFUSED | 15 | 16 | — | 2220 | 2233 | — | 28.178 | 27.666 | 29.283 |
| super-magnetic-ring/freeform/all-products | CLEAN | CLEAN | REFUSED | 14 | 14 | — | 1880 | 1880 | — | 27.394 | 28.057 | 29.532 |
| super-magnetic-ring/freeform/output-products | CLEAN | CLEAN | CLEAN | 13 | 14 | 4 | 2052 | 2052 | 2600 | 28.071 | 25.388 | 27.728 |
| super-magnetic-ring/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 14 | 14 | 5 | 2294 | 2294 | 3120 | 29.506 | 30.692 | 29.704 |
| super-magnetic-ring/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 13 | 13 | 3 | 1886 | 1886 | 2340 | 34.995 | 29.141 | 29.690 |
| super-magnetic-ring/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 15 | 15 | 4 | 2016 | 2016 | 2296 | 28.853 | 30.966 | 30.012 |
| graphene/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 363 | 363 | 352 | 1.187 | 0.968 | 1.294 |
| graphene/freeform/all-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 504 | 504 | 520 | 2.436 | 2.508 | 2.364 |
| graphene/freeform/output-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 420 | 420 | 520 | 1.780 | 2.450 | 2.087 |
| graphene/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 363 | 363 | 374 | 31.719 | 31.503 | 31.633 |
| graphene/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 518 | 518 | 520 | 30.305 | 30.136 | 30.475 |
| graphene/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 420 | 420 | 468 | 30.005 | 30.890 | 30.418 |
| electromagnetic-matrix/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 4 | 4 | 1 | 609 | 609 | 1015 | 2.999 | 2.175 | 2.013 |
| electromagnetic-matrix/freeform/all-products | CLEAN | CLEAN | CLEAN | 7 | 7 | 1 | 756 | 756 | 1073 | 16.020 | 16.053 | 11.754 |
| electromagnetic-matrix/freeform/output-products | CLEAN | CLEAN | CLEAN | 4 | 4 | 1 | 576 | 576 | 1044 | 5.577 | 6.581 | 3.280 |
| electromagnetic-matrix/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 504 | 504 | 528 | 31.301 | 30.572 | 31.163 |
| electromagnetic-matrix/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 6 | 6 | 1 | 841 | 841 | 868 | 28.973 | 28.531 | 27.352 |
| electromagnetic-matrix/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 4 | 4 | 1 | 576 | 576 | 700 | 30.955 | 30.434 | 29.142 |
| plastic/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 7 | 7 | 3 | 760 | 760 | 1080 | 4.224 | 2.944 | 2.582 |
| plastic/freeform/all-products | CLEAN | CLEAN | CLEAN | 6 | 6 | 3 | 820 | 850 | 884 | 13.958 | 12.631 | 6.031 |
| plastic/freeform/output-products | CLEAN | CLEAN | CLEAN | 7 | 7 | 3 | 800 | 800 | 1116 | 6.075 | 12.784 | 3.812 |
| plastic/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 7 | 7 | 2 | 722 | 722 | 748 | 31.125 | 29.343 | 30.909 |
| plastic/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 6 | 6 | 1 | 850 | 850 | 816 | 30.697 | 28.902 | 27.887 |
| plastic/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 7 | 7 | 1 | 800 | 800 | 900 | 29.333 | 29.093 | 31.569 |
| iron-ingot/freeform/no-proliferator | CLEAN | CLEAN | REFUSED | 1 | 1 | — | 63 | 63 | — | 0.692 | 0.264 | 0.941 |
| iron-ingot/freeform/all-products | CLEAN | CLEAN | REFUSED | 1 | 1 | — | 104 | 104 | — | 1.761 | 1.107 | 0.485 |
| iron-ingot/freeform/output-products | CLEAN | CLEAN | REFUSED | 1 | 1 | — | 104 | 104 | — | 2.105 | 0.760 | 0.431 |
| iron-ingot/sequence-pair/no-proliferator | CLEAN | CLEAN | REFUSED | 1 | 1 | — | 63 | 63 | — | 19.597 | 10.486 | 28.466 |
| iron-ingot/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 1 | 1 | 1 | 104 | 104 | 169 | 31.789 | 24.417 | 26.730 |
| iron-ingot/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 1 | 1 | 1 | 104 | 104 | 169 | 30.068 | 23.102 | 30.506 |
| magnetic-coil/freeform/no-proliferator | CLEAN | CLEAN | CLEAN | 2 | 2 | 1 | 198 | 198 | 234 | 0.590 | 0.674 | 0.710 |
| magnetic-coil/freeform/all-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 323 | 323 | 342 | 3.545 | 2.737 | 3.222 |
| magnetic-coil/freeform/output-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 285 | 285 | 323 | 1.993 | 1.976 | 3.235 |
| magnetic-coil/sequence-pair/no-proliferator | CLEAN | CLEAN | CLEAN | 2 | 2 | 1 | 230 | 230 | 238 | 21.281 | 21.400 | 31.214 |
| magnetic-coil/sequence-pair/all-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 342 | 342 | 361 | 30.366 | 30.496 | 29.793 |
| magnetic-coil/sequence-pair/output-products | CLEAN | CLEAN | CLEAN | 3 | 3 | 1 | 299 | 299 | 323 | 30.832 | 30.618 | 30.454 |

## Substation refusal findings (all 16 cells)

These are REFUSED, not emitted INVALID outputs. Full raw details are reproduced to avoid relabeling validator rejection as a success. Six universe-matrix rows are inherited; every other row is a losing cell versus default.

### universe-matrix/freeform/no-proliferator

Status: **REFUSED**, wall 1.084602s.

> a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37

### universe-matrix/freeform/all-products

Status: **REFUSED**, wall 0.357954s.

> a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37

### universe-matrix/freeform/output-products

Status: **REFUSED**, wall 0.228110s.

> a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37

### universe-matrix/sequence-pair/no-proliferator

Status: **REFUSED**, wall 3.713314s.

> all 4 sequence islands refused: island 0: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37; island 1: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37; island 2: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37; island 3: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37

### universe-matrix/sequence-pair/all-products

Status: **REFUSED**, wall 3.490874s.

> all 4 sequence islands refused: island 0: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 1: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 2: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 3: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37

### universe-matrix/sequence-pair/output-products

Status: **REFUSED**, wall 3.352547s.

> all 4 sequence islands refused: island 0: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 1: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 2: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 3: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37

### casimir-crystal/sequence-pair/no-proliferator

Status: **REFUSED**, wall 30.662136s.

> all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout

### casimir-crystal/sequence-pair/output-products

Status: **REFUSED**, wall 30.328166s.

> all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout

### information-matrix/freeform/output-products

Status: **REFUSED**, wall 28.786561s.

> every packing that wired was rejected by our own validator (power.coverage); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run

### information-matrix/sequence-pair/output-products

Status: **REFUSED**, wall 29.591078s.

> all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout

### super-magnetic-ring/freeform/no-proliferator

Status: **REFUSED**, wall 29.283178s.

> every packing that wired was rejected by our own validator (power.coverage); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run

### super-magnetic-ring/freeform/all-products

Status: **REFUSED**, wall 29.531552s.

> every packing that wired was rejected by our own validator (power.coverage); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run

### iron-ingot/freeform/no-proliferator

Status: **REFUSED**, wall 0.941180s.

> every packing that wired was rejected by our own validator (power.coverage); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run

### iron-ingot/freeform/all-products

Status: **REFUSED**, wall 0.484927s.

> every packing that wired was rejected by our own validator (power.coverage); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run

### iron-ingot/freeform/output-products

Status: **REFUSED**, wall 0.431082s.

> every packing that wired was rejected by our own validator (power.coverage); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run

### iron-ingot/sequence-pair/no-proliferator

Status: **REFUSED**, wall 28.465761s.

> all 4 sequence islands refused: island 0: feasibility continuation exhausted its restart budget after 8 batches before an exact layout; island 1: feasibility continuation exhausted its restart budget after 8 batches before an exact layout; island 2: feasibility continuation exhausted its restart budget after 8 batches before an exact layout; island 3: feasibility continuation exhausted its restart budget after 8 batches before an exact layout

## Deadline tails and serial adjudication inputs

The budget is the requested search deadline, not an independently proved hard bound on complete audit wall time. Raw logs explicitly say emission, detailed routing in flight, and validation finish atomically. JSONL `wall_overshoot_s` is 0 for emitted rows even when `seconds`/`attempt_wall_s` exceed 30; some refusals omit that field. The zero field is **not** used to erase the measured tail. Across all corpus cells, base has 21 >30s (max34.994612s), default15 (max32.154545s), substation16 (max31.633244s). No multi-minute overrun is present. No serial rerun was performed by this documentation task.

All cells exceeding 30 in any corpus arm follow (not merely a p95 or a success headline):

| Cell | Base s | Default s | Substation s |
|---|---:|---:|---:|

| casimir-crystal/sequence-pair/no-proliferator | 31.559269 | 31.532306 | 30.662136 |
| casimir-crystal/sequence-pair/output-products | 30.029987 | 30.005202 | 30.328166 |
| information-matrix/freeform/all-products | 30.048060 | 28.216882 | 29.484602 |
| information-matrix/sequence-pair/no-proliferator | 30.006089 | 28.154566 | 29.029293 |
| processor/sequence-pair/no-proliferator | 31.507550 | 31.035433 | 30.831882 |
| processor/sequence-pair/output-products | 30.080932 | 29.910777 | 29.985982 |
| energy-matrix/sequence-pair/no-proliferator | 31.258505 | 31.662361 | 31.557712 |
| energy-matrix/sequence-pair/all-products | 30.851571 | 30.851159 | 31.101877 |
| energy-matrix/sequence-pair/output-products | 31.158216 | 32.154545 | 30.389762 |
| super-magnetic-ring/sequence-pair/no-proliferator | 29.506113 | 30.692234 | 29.704060 |
| super-magnetic-ring/sequence-pair/all-products | 34.994612 | 29.141298 | 29.690419 |
| super-magnetic-ring/sequence-pair/output-products | 28.853272 | 30.966169 | 30.011598 |
| graphene/sequence-pair/no-proliferator | 31.719367 | 31.503279 | 31.633244 |
| graphene/sequence-pair/all-products | 30.305290 | 30.135892 | 30.475263 |
| graphene/sequence-pair/output-products | 30.005020 | 30.889882 | 30.417601 |
| electromagnetic-matrix/sequence-pair/no-proliferator | 31.300910 | 30.572404 | 31.162687 |
| electromagnetic-matrix/sequence-pair/output-products | 30.955074 | 30.434448 | 29.142135 |
| plastic/sequence-pair/no-proliferator | 31.125490 | 29.343428 | 30.908617 |
| plastic/sequence-pair/all-products | 30.697098 | 28.902347 | 27.886822 |
| plastic/sequence-pair/output-products | 29.332732 | 29.093228 | 31.569179 |
| iron-ingot/sequence-pair/all-products | 31.789174 | 24.416948 | 26.729863 |
| iron-ingot/sequence-pair/output-products | 30.068360 | 23.101994 | 30.505707 |
| magnetic-coil/sequence-pair/no-proliferator | 21.280567 | 21.399556 | 31.214013 |
| magnetic-coil/sequence-pair/all-products | 30.366442 | 30.496481 | 29.792520 |
| magnetic-coil/sequence-pair/output-products | 30.832464 | 30.617821 | 30.453829 |

Priority serial inputs for Main (failed scenarios only, retain these original results):

1. Default area regressions: super-magnetic-ring/freeform/no-proliferator and plastic/freeform/all-products; the other two default parity movers above are named rather than silently accepted.
2. All ten new substation corpus refusals above: six coverage, three deadlines, one restart exhaustion. Do not rerun inherited universe fan-out as if newly introduced.
3. New substation reported sequence-pair/no-proliferator projected collision; all four coated reported policies on both arms remain failed. Reported substation sequence-pair/all-products has CPU runnable mean **310.4**, so its deadline-only failure especially requires serial attribution; pressure does not make it CLEAN.
4. New default >30 cells vs baseline: super-magnetic-ring/sequence-pair/no-proliferator (30.692234s) and /output-products (30.966169s). New substation >30 vs candidate-default: plastic/sequence-pair/no-proliferator (30.908617s), plastic/sequence-pair/output-products (31.569179s), iron-ingot/sequence-pair/output-products (30.505707s), magnetic-coil/sequence-pair/no-proliferator (31.214013s). Of these, plastic/output-products and magnetic-coil/no-proliferator also exceed 30 where baseline does not. These bounded tails are preserved, not claimed as confirmed power-induced regressions.
5. Reported default/freeform/output-products wall30.645989s is both a refused correctness case and a tail; the substation counterpart refuses at22.254638s, not a performance win that resolves correctness.

## Available software and browser evidence

These are existing Main-run artifacts, not fresh executions by this report author. Logs live under `.superpowers/sdd/2026-09-07-power-tower/` unless linked otherwise.

- `recovery-halo.log`:20 passing indicators, exit0. `recovery-validator.log`:3, exit0. `recovery-public.log`:9, exit0. `recovery-web.log`:115, exit0. `recovery-metrics-tests.log`:10, exit0; `recovery-review-green.log`:2, exit0. These are scoped recovery checks, not a full suite at the final source.
- `parent-clearance-red-centered.log`: real pre-fix substation halo assertion fails at (-3,-3,0), Tesla control passes, exit1. Earlier malformed/incorrect-fixture red attempts in the same directory are archival troubleshooting, not the proof used here. `parent-clearance-green.log`:3 passing indicators, exit0. `settled-compose.log`:full composer module30 passing indicators, exit0.
- `settled-ruff.log`:all checks passed, exit0. `settled-format.log`:220 files already formatted, exit0. `settled-mypy.log`:no issues in89 source files, exit0. These reflect Main's settled source after parent fix, distinct from corpus provenance.
- `parallel-full-suite.log`:exit1, only named failure `tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`; `serial-failed-nodes.log` retains that failure, exit1. It is the brief's known red, not a green suite. The other predeclared known red `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline` is not listed as failed in that recorded full-suite output. This is not a newly run full suite at cf4d16a4.
- Web `recovery-web-typecheck.log`, `recovery-web-lint.log`, `recovery-web-test.log`, `recovery-web-build.log` all exit0; test log records39 files/400 tests passed. Existing build output is not committed or regenerated here.

Actual browser artifacts were inspected, not inferred from implementation:

| Artifact | Recorded request/option | Observed result | Area | Status |
|---|---|---|---:|---|
| [auto JSON](recovery-ui-auto.json), [auto screenshot](recovery-ui-auto-solid.png) | auto / URL selection | Satellite Substation |1015|done, valid=true, report.ok=true|
| [Tesla JSON](recovery-ui-tesla.json), [Tesla screenshot](recovery-ui-tesla.png) | explicit tesla | Tesla Tower |609|done, valid=true, report.ok=true|
| [Substation JSON](recovery-ui-substation.json), [Substation screenshot](recovery-ui-substation.png) | explicit substation | Satellite Substation |1015|done, valid=true, report.ok=true|
| [Wireless JSON](recovery-ui-wireless.json), [Wireless screenshot](recovery-ui-wireless.png) | explicit wireless | Wireless Power Tower |609|done, valid=true, report.ok=true|

The shared hashed URL is in [task7-url.txt](task7-url.txt); all use freeform/no-proliferator and30s. Auto and explicit Substation descriptions name Satellite Substation; explicit Wireless names Wireless Power Tower; Tesla retains the prior description without an added power suffix. Auto screenshot identifies a plain large substation box with no icon while endpoint icons are checked; explicit Substation screenshot shows one substation and the same icon-free box. This demonstrates viewer geometry/UI behavior, not a detailed game mesh or collision certification. The JSON contains encoded blueprints, not a separately captured decoded item/model/footprint assertion; this adjudication does not claim it decoded them. Catalog authority remains item2212/model68/5×5, wireless2202/model71/1×1, Tesla2201/model44/1×1. Coverage/link radii are26.5/53.5,6.5/45.5,10.5/22.5 tiles respectively.

## Parent path and remaining integration seam

[recovery-parent-substation.log](recovery-parent-substation.log) records the actual15s hierarchical/no-proliferator CLI attempt: exit3, two blocks never placed, zero composition gap/cut lanes. Block0 (copper-ingot, magnet) and block1 (magnetic-coil) both exhaust exact-layout time before composition. This cannot validate the parent route or post-composition infill.

`cf4d16a4` closes the parent canvas reservation gap with direct red/green software evidence; approved plan D9's original “no compose change” assumption and the earlier R9 accepted deferral are superseded, not silently retained as current safety claims. Preserve `BuildSpec.power_tower_item_id` through every partition/rebuild. After hierarchy merge, `plan_power_infill` must read the same selected record through `catalog.power_tower_building(spec.power_tower_item_id)` and carry it into all scratch/retry canvases; no in-run Tesla fallback. Main owns source integration and the resulting end-to-end proof. See [the seam note](../../plans/2026-09-07-power-tower-followup.md).

## Immutable source manifest

SHA256 values identify the exact completed inputs used to render this report. Raw files and helper were not modified.

| Input | SHA256 |
|---|---|

| parallel-gates-xUhQwvAA/default-base.jsonl | `6d5d6cf755a3377d407e928dc3d163d9b57826fe10ef53135ee4074bfd2f8c7e` |
| parallel-gates-xUhQwvAA/default-head.jsonl | `9243c216fe3d5368fe9e95286f84495be8189454a174549da906461814f9c082` |
| parallel-gates-xUhQwvAA/substation.jsonl | `340bb4089573a1d3db8a7ec2ce11f3f19cee4fa828d8d037b3b347bbef248c40` |
| parallel-gates-xUhQwvAA/deterministic-base/cells.jsonl | `e634b2289645990b2287622868fb62f44f8bd48201dc9255c0bfbb137b08066a` |
| parallel-gates-xUhQwvAA/deterministic-head/cells.jsonl | `6b1479c4258fe347ece2e1ed643658673c62734541beda7c0aa32584cab57727` |
| parallel-gates-xUhQwvAA/reported-default/cells.jsonl | `d8348357000dfd6303975678a89f65ca68575fd799657f19d20886967c933502` |
| parallel-gates-xUhQwvAA/reported-substation/cells.jsonl | `a1a609e30a404f0380a3a2481ecaa57537a515f67b444c5541281cd12f0e7913` |
| .superpowers/sdd/2026-09-07-power-tower/gate_power.py | `504d39ecc377eeb8890d687897387e29404042a7bd191dc7bdb2b7420af979c7` |
