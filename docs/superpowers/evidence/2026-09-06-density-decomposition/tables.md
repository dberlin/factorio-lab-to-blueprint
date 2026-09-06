## Status counts (all 72 cells, budget 30)

| arm | configuration | CLEAN | REFUSED | INVALID | other |
| --- | --- | --- | --- | --- | --- |
| freeform | baseline | 36 | 0 | 0 | 0 |
| freeform | no direct insert | 36 | 0 | 0 | 0 |
| freeform | no belt sharing | 24 | 12 | 0 | 0 |
| freeform | neither | 24 | 12 | 0 | 0 |
| sequence-pair | baseline | 35 | 1 | 0 | 0 |
| sequence-pair | no direct insert | 35 | 1 | 0 | 0 |
| sequence-pair | no belt sharing | 26 | 10 | 0 | 0 |
| sequence-pair | neither | 26 | 10 | 0 | 0 |

## Pairwise: each configuration against baseline on the cells BOTH build

| arm | configuration | cells clean in both | geomean area ratio | median | max | geomean belt_tiles ratio |
| --- | --- | --- | --- | --- | --- | --- |
| freeform | no direct insert | 36 | 0.9943 | 1.000 | 1.078 | 0.9923 |
| freeform | no belt sharing | 24 | 1.0036 | 1.000 | 1.091 | 1.0030 |
| freeform | neither | 24 | 1.0036 | 1.000 | 1.091 | 1.0089 |
| sequence-pair | no direct insert | 35 | 1.0103 | 1.000 | 1.201 | 0.9988 |
| sequence-pair | no belt sharing | 26 | 1.0137 | 1.000 | 1.378 | 1.0074 |
| sequence-pair | neither | 26 | 1.0124 | 1.000 | 1.378 | 1.0116 |

## Where direct insertion actually happens (baseline freeform, all 36 cells)

- 0/36 clean baseline cells REALIZE at least one direct insert (`direct_inserts` stat).
- 19/36 cells have at least one direct-insert CANDIDATE, 236 in total.

### Internal control for the direct-insert switch

| subset | cells | geomean area ratio (no direct / base) | cells whose area moved |
| --- | --- | --- | --- |
| candidates == 0 (switch cannot matter) | 17 | 0.9950 | 2 |
| candidates > 0 (switch can matter) | 19 | 0.9936 | 4 |

No baseline cell realizes a direct insert, so the per-cell table below is empty.

| url_id | spec | machines | direct_inserts | base area | nodirect area | ratio |
| --- | --- | --- | --- | --- | --- | --- |

## freeform: area ratio vs baseline, 24/36 cells clean in all four

| configuration | geomean area ratio | Q1 | median | Q3 | min | max |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| no direct insert | 0.9998 | 1.000 | 1.000 | 1.000 | 0.996 | 1.000 |
| no belt sharing | 1.0036 | 1.000 | 1.000 | 1.000 | 1.000 | 1.091 |
| neither | 1.0036 | 1.000 | 1.000 | 1.000 | 1.000 | 1.091 |

Interaction: geomean(neither) = 1.0036 vs geomean(no direct) x geomean(no sharing) = 1.0035 (neither - product = +0.0002)

### freeform: mechanism counters (means over the same cells)

| configuration | area | belt_tiles | direct_inserts | sorters | nets | routed | machines |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 777 | 356.4 | 0.00 | 30.8 | 7.8 | 7.8 | 11.2 |
| no direct insert | 776 | 346.2 | 0.00 | 30.8 | 7.8 | 7.8 | 11.2 |
| no belt sharing | 792 | 362.0 | 0.00 | 30.8 | 7.8 | 7.8 | 11.2 |
| neither | 792 | 362.4 | 0.00 | 30.8 | 7.8 | 7.8 | 11.2 |

### freeform: geomean area ratio by cell size

| class | cells | no direct insert | no belt sharing | neither |
| --- | --- | --- | --- | --- |
| tiny (<=10 machines) | 18 | 1.0000 | 1.0000 | 1.0000 |
| mid (11-60) | 6 | 0.9993 | 1.0146 | 1.0146 |

### freeform: cells whose status changed when a mechanism went off

| url_id | spec | machines | base | no direct | no sharing | neither |
| --- | --- | --- | --- | --- | --- | --- |
| information-matrix | no-proliferator | 97 | CLEAN | CLEAN | REFUSED | REFUSED |
| information-matrix | all-products | 56 | CLEAN | CLEAN | REFUSED | REFUSED |
| information-matrix | output-products | 84 | CLEAN | CLEAN | REFUSED | REFUSED |
| processor | no-proliferator | 21 | CLEAN | CLEAN | REFUSED | REFUSED |
| processor | output-products | 20 | CLEAN | CLEAN | REFUSED | REFUSED |
| quantum-chip | no-proliferator | 87 | CLEAN | CLEAN | REFUSED | REFUSED |
| quantum-chip | output-products | 76 | CLEAN | CLEAN | REFUSED | REFUSED |
| super-magnetic-ring | no-proliferator | 58 | CLEAN | CLEAN | REFUSED | REFUSED |
| super-magnetic-ring | output-products | 52 | CLEAN | CLEAN | REFUSED | REFUSED |
| universe-matrix | no-proliferator | 224 | CLEAN | CLEAN | REFUSED | REFUSED |
| universe-matrix | all-products | 113 | CLEAN | CLEAN | REFUSED | REFUSED |
| universe-matrix | output-products | 193 | CLEAN | CLEAN | REFUSED | REFUSED |

### freeform: biggest area movers (no belt sharing)

| url_id | spec | machines | base area | noshare area | ratio | base belts | noshare belts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| quantum-chip | all-products | 49 | 3840 | 4189 | 1.091 | 2602 | 2685 |
| casimir-crystal | no-proliferator | 23 | 1107 | 1107 | 1.000 | 398 | 398 |
| casimir-crystal | all-products | 17 | 1161 | 1161 | 1.000 | 494 | 494 |
| casimir-crystal | output-products | 21 | 1100 | 1100 | 1.000 | 437 | 437 |
| electromagnetic-matrix | no-proliferator | 9 | 609 | 609 | 1.000 | 166 | 166 |
| electromagnetic-matrix | all-products | 8 | 756 | 756 | 1.000 | 400 | 400 |
| electromagnetic-matrix | output-products | 9 | 576 | 576 | 1.000 | 220 | 220 |
| energy-matrix | no-proliferator | 10 | 616 | 616 | 1.000 | 139 | 139 |
| energy-matrix | all-products | 8 | 742 | 742 | 1.000 | 280 | 280 |
| energy-matrix | output-products | 9 | 572 | 572 | 1.000 | 183 | 183 |

## sequence-pair: area ratio vs baseline, 26/36 cells clean in all four

| configuration | geomean area ratio | Q1 | median | Q3 | min | max |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| no direct insert | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| no belt sharing | 1.0137 | 1.000 | 1.000 | 1.000 | 1.000 | 1.378 |
| neither | 1.0124 | 1.000 | 1.000 | 1.000 | 1.000 | 1.378 |

Interaction: geomean(neither) = 1.0124 vs geomean(no direct) x geomean(no sharing) = 1.0137 (neither - product = -0.0013)

### sequence-pair: mechanism counters (means over the same cells)

| configuration | area | belt_tiles | direct_inserts | sorters | nets | routed | machines |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 868 | 425.7 | 0.00 | 36.9 | 8.7 | 8.7 | 13.3 |
| no direct insert | 868 | 425.7 | 0.00 | 36.9 | 8.7 | 8.7 | 13.3 |
| no belt sharing | 884 | 420.4 | 0.00 | 36.9 | 8.7 | 8.7 | 13.3 |
| neither | 880 | 429.7 | 0.00 | 36.9 | 8.7 | 8.7 | 13.3 |

## Large cells (prof_harness, freeform)

| cell | configuration | verdict | area | ratio | belt_tiles | direct_inserts | wall s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| um60 | baseline | OK | 31898 | 1.000 | 11238.0 | 0.0 | 25 |
| um60 | no direct insert | OK | 31898 | 1.000 | 11238.0 | 0.0 | 25 |
| um60 | no belt sharing | REFUSED: no packing of 43 strips could b |  | - |  |  | 18 |
| um60 | neither | REFUSED: no packing of 43 strips could b |  | - |  |  | 16 |
| um120 | baseline | OK | 80496 | 1.000 | 19141.0 | 0.0 | 25 |
| um120 | no direct insert | OK | 80496 | 1.000 | 19141.0 | 0.0 | 24 |
| um120 | no belt sharing | REFUSED: no packing of 47 strips could b |  | - |  |  | 25 |
| um120 | neither | REFUSED: no packing of 47 strips could b |  | - |  |  | 26 |
| gm200 | baseline | OK | 48640 | 1.000 | 12455.0 | 0.0 | 29 |
| gm200 | no direct insert | OK | 48640 | 1.000 | 12455.0 | 0.0 | 28 |
| gm200 | no belt sharing | REFUSED: no packing of 33 strips could b |  | - |  |  | 24 |
| gm200 | neither | REFUSED: no packing of 33 strips could b |  | - |  |  | 24 |
| qc180 | baseline | OK | 14896 | 1.000 | 4902.0 | 0.0 | 25 |
| qc180 | no direct insert | OK | 16434 | 1.103 | 4466.0 | 0.0 | 28 |
| qc180 | no belt sharing | REFUSED: no packing of 20 strips could b |  | - |  |  | 21 |
| qc180 | neither | REFUSED: no packing of 20 strips could b |  | - |  |  | 21 |
| belt3 | baseline | OK | 15207 | 1.000 | 6618.0 | 0.0 | 48 |
| belt3 | no direct insert | OK | 15207 | 1.000 | 6618.0 | 0.0 | 60 |
| belt3 | no belt sharing | REFUSED: no packing of 18 strips could b |  | - |  |  | 45 |
| belt3 | neither | REFUSED: no packing of 18 strips could b |  | - |  |  | 48 |
