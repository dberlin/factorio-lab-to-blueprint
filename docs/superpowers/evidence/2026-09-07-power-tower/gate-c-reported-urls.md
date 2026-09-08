# Gate (c): both reported six-cell arms

**FAIL:** default2 CLEAN/4 REFUSED; substation1 CLEAN/5 REFUSED. No INVALID or CRASH output row. These are six cells per arm, not six successful builds. Refused candidate validation findings remain failures and are not emitted blueprints.

Measured source: `632296de737a63d8bd0132f367a64802d1501327` with formatting-only working-tree changes per Main; later `cf4d16a4` changes parent hierarchy canvas, not these arms. Helper and corpus provenance, software/browser proof and missing physical evidence are adjudicated in [gate-b-table.md](gate-b-table.md). All raw inputs in `parallel-gates-xUhQwvAA/` are retained unchanged. No reruns were performed for this report.

Exact reported URL (identical in all12 raw rows):

`https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFiWUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DKloJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11`

Each row uses one candidate policy, budget30s, workers1, round0; CPU is the helper’s last-five-sample runnable mean immediately before that build. `—` means no accepted placement/count or independent clearance evidence, not zero towers/area. Times are total helper wall time including certification/encoding for returned outputs.

| Arm | Cell | Status | Towers | Area | Wall s | CPU mean | Direct halo overlaps | Certificate errors |
|---|---|---|---:|---:|---:|---:|---|---|
| reported-default | reported/freeform/no-proliferator | CLEAN | 26 | 4402 | 19.376674 | 32.6 | 0 | 0 |
| reported-default | reported/freeform/all-products | REFUSED | — | — | 26.859086 | 21.6 | — | — |
| reported-default | reported/freeform/output-products | REFUSED | — | — | 30.645989 | 27.2 | — | — |
| reported-default | reported/sequence-pair/no-proliferator | CLEAN | 28 | 4032 | 25.671781 | 55.0 | 0 | 0 |
| reported-default | reported/sequence-pair/all-products | REFUSED | — | — | 25.945185 | 63.2 | — | — |
| reported-default | reported/sequence-pair/output-products | REFUSED | — | — | 26.136735 | 49.2 | — | — |
| reported-substation | reported/freeform/no-proliferator | CLEAN | 7 | 5130 | 14.281802 | 24.6 | 0 | 0 |
| reported-substation | reported/freeform/all-products | REFUSED | — | — | 27.347503 | 30.6 | — | — |
| reported-substation | reported/freeform/output-products | REFUSED | — | — | 22.254638 | 35.8 | — | — |
| reported-substation | reported/sequence-pair/no-proliferator | REFUSED | — | — | 25.365533 | 50.2 | — | — |
| reported-substation | reported/sequence-pair/all-products | REFUSED | — | — | 21.485996 | 310.4 | — | — |
| reported-substation | reported/sequence-pair/output-products | REFUSED | — | — | 28.140674 | 27.8 | — | — |

## Pairwise interpretation

- Freeform/no-proliferator remains CLEAN: towers26→7 (3.71× fewer), area4402→5130 (+728,16.54%). Substation has seven sites, zero direct flat halo overlaps and no re-certification errors. Default’s zero substation halo overlaps are vacuous because it has no substations. The direct halo check is not spherical projection or live game proof.
- Sequence-pair/no-proliferator loses the default CLEAN result (28 towers,4032 tiles): the substation arm refuses after exact projected `geom.collide` at indices(538,2570), bands160 and200. It does **not** emit an INVALID blueprint. Treat this as a meaningful losing cell, not a deadline-only timing veto.
- All four coated cells refuse on both arms; reasons differ and are reproduced verbatim below. In particular substation freeform/all-products adds recorded `power.coverage` and retains coater/flow failures; no reason is normalized away as “known red.”
- Default freeform/output-products exact quantum-chip demand49/90 exceeds reachable43/90 by1/15; substation freeform/all-products demand49/90 exceeds281/540 by13/540. FactorioLab rate authority and one-run coating constraints are not relaxed to manufacture CLEAN.
- Substation sequence-pair/all-products ran under CPU runnable mean310.4; serial rerun attribution is Main’s responsibility. Its raw status remains REFUSED. Default freeform/output-products exceeds30 wall seconds (30.645989); the other11 rows do not, but deadline-exhaustion refusals below still fail to build.
- No explicit mixed-input or belt-cycle verdict appears in these refusal strings. Their absence is not a separately measured proof; no exception to either prohibition is authorized.

## Exact refusal evidence

### reported-default: reported/freeform/all-products

**REFUSED**

> no valid layout for all-products after 30s: freeform/all-products: every packing that wired was rejected by our own validator (geom.collide; findings: band 200 geom.collide (31, 809): build colliders intersect); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-default: reported/freeform/output-products

**REFUSED**

> no valid layout for output-products after 30s: freeform/output-products: every packing that wired was rejected by our own validator (geom.collide, prolif.coater_rides_one_run, flow.conservation; findings: band 200 geom.collide (31, 814): build colliders intersect; prolif.coater_rides_one_run (808, 0, 1, 2): coater 808 rides a belt merge under its body: belt(s) [0] on its body tiles have two or more predecessors; a coater carries no connection of its own and needs one lane, not a merge whose joined flows have no arrangement that keeps its recipe's proportion ({'ride': 1, 'merged_belts': [0], 'distinct_runs': [0]}); prolif.coater_rides_one_run (823, 42, 43, 44): coater 823 rides a belt merge under its body: belt(s) [42] on its body tiles have two or more predecessors; a coater carries no connection of its own and needs one lane, not a merge whose joined flows have no arrangement that keeps its recipe's proportion ({'ride': 43, 'merged_belts': [42], 'distinct_runs': [4]}); flow.conservation (31, 73, 116, 621): 4 machine(s) consume 49/90 items/s of quantum-chip but only 43/90 items/s of it can reach them in flow order (lanes [23, 24, 25, 26]); short by 1/15 items/s ({'item': 'quantum-chip', 'demand': '49/90', 'supply': '43/90', 'shortfall': '1/15', 'consumers': 4, 'lanes': [23, 24, 25, 26]})); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-default: reported/sequence-pair/all-products

**REFUSED**

> no valid layout for all-products after 30s: sequence-pair/all-products: deadline exhausted before finding an exact layout; exact validation failures: flow.conservation, prolif.coater_rides_one_run. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-default: reported/sequence-pair/output-products

**REFUSED**

> no valid layout for output-products after 30s: sequence-pair/output-products: deadline exhausted before finding an exact layout; exact validation failures: flow.conservation, prolif.coater_rides_one_run. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-substation: reported/freeform/all-products

**REFUSED**

> no valid layout for all-products after 30s: freeform/all-products: every packing that wired was rejected by our own validator (geom.collide, prolif.coater_rides_one_run, flow.conservation, power.coverage; findings: band 200 geom.collide (31, 809): build colliders intersect; prolif.coater_rides_one_run (803, 0, 1, 2): coater 803 rides a belt merge under its body: belt(s) [0] on its body tiles have two or more predecessors; a coater carries no connection of its own and needs one lane, not a merge whose joined flows have no arrangement that keeps its recipe's proportion ({'ride': 1, 'merged_belts': [0], 'distinct_runs': [0]}); prolif.coater_rides_one_run (818, 42, 43, 44): coater 818 rides a belt merge under its body: belt(s) [42] on its body tiles have two or more predecessors; a coater carries no connection of its own and needs one lane, not a merge whose joined flows have no arrangement that keeps its recipe's proportion ({'ride': 43, 'merged_belts': [42], 'distinct_runs': [4]}); flow.conservation (31, 73, 133, 640): 4 machine(s) consume 49/90 items/s of quantum-chip but only 281/540 items/s of it can reach them in flow order (lanes [22, 23, 24, 25]); short by 13/540 items/s ({'item': 'quantum-chip', 'demand': '49/90', 'supply': '281/540', 'shortfall': '13/540', 'consumers': 4, 'lanes': [22, 23, 24, 25]})); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-substation: reported/freeform/output-products

**REFUSED**

> no valid layout for output-products after 30s: freeform/output-products: every packing that wired was rejected by our own validator (geom.collide, power.coverage; findings: band 200 geom.collide (31, 814): build colliders intersect); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-substation: reported/sequence-pair/no-proliferator

**REFUSED**

> no valid layout for no-proliferator after 30s: sequence-pair/no-proliferator: deadline exhausted before finding an exact layout; exact validation failures: geom.collide; no legal DSP latitude band/orientation accepts the final placement: band 160 geom.collide (538, 2570): build colliders intersect; band 200 geom.collide (538, 2570): build colliders intersect. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-substation: reported/sequence-pair/all-products

**REFUSED**

> no valid layout for all-products after 30s: sequence-pair/all-products: deadline exhausted before finding an exact layout. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

### reported-substation: reported/sequence-pair/output-products

**REFUSED**

> no valid layout for output-products after 30s: sequence-pair/output-products: deadline exhausted before finding an exact layout. Treat a spec that cannot be laid out in the requested budget as a layout-model defect until shown otherwise.

## Accepted blueprint identities

Timestamp was normalized to0 by the helper. These identities are software artifacts, not game paste certificates.

| Arm/cell | SHA256 |
|---|---|
| reported-default/reported/freeform/no-proliferator | `4b81beb2084cbccd4927d1577b53c4e5075abb3ae367df591e5cf6afdeed5534` |
| reported-default/reported/sequence-pair/no-proliferator | `967ad69eb03a704a2e222ce4124581691b55580ce00c2f87434e675394c55858` |
| reported-substation/reported/freeform/no-proliferator | `52a0e7eda3477cd8d2909a109ff29885c336c04a7c98ecd98b2f1e1f88bc8f5f` |
