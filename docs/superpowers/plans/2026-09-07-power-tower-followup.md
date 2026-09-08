# Power-tower integration with hierarchical-v4

Implementation handoff, not a gate pass. Completed measurements are adjudicated in [gate-b-table.md](../evidence/2026-09-07-power-tower/gate-b-table.md); final independent review is separate and live paste evidence remains unavailable. Measured source is `632296de` plus formatting-only changes; later `cf4d16a4` changes parent hierarchical canvas only, not the measured freeform/sequence-pair arms.

- `BuildSpec.power_tower_item_id` is the single persisted choice, a FactorioLab item id.
- `catalog.power_tower_building(lab_id)` resolves the catalog record. `_Canvas.power_building` carries that record through one layout run. Read the canvas record inside routing scope; do not resolve repeatedly in hot loops.
- The existing `hierarchy.partition.sub_spec` and `composed_spec` rebuilds preserve the field. Every new `BuildSpec(...)` construction must preserve it too. Keep machine-rank plumbing when combining the branches.
- Hierarchical-v4's `plan_power_infill` must receive the chosen record from `catalog.power_tower_building(spec.power_tower_item_id)`, including every scratch/retry canvas. Do not retain a Tesla fallback inside a selected substation run.
- This branch's `_power_reservation(tower)` encloses catalog clearance symmetrically on the integer grid: 6x6 clearance about a 5x5 substation means offsets `[-1,6)` on each axis (7x7 occupied routing cells). The actual emitted building remains item 2212, model 68, footprint 5x5. Tesla remains 1x1.
- Parent composition routing must treat already emitted child substations' clearance halos as obstacles, not only their 5x5 solid footprints. `cf4d16a4` closes the parent `canvas_for` gap with a true substation halo red/green proof and a passing full composer module. This supersedes the approved plan D9 “no compose change” assumption. Preserve that reservation through the hierarchy merge and post-routing infill; include projected collision checks, not just flat reservations.
- Reuse the existing `TestALargePowerBuildingClaimsItsWholeFootprint` direct geometry checks at block boundaries. They now check the clearance halo as well as footprint; also retain the four-sided emitter refusal regression and no-clearance-hole regression.

## Explicit unresolved gates

R9's original acceptance is superseded by R12. Existing recovery halo tests and the later parent canvas red/green proof pass; this is software reservation evidence, not independent review approval or full physical safety. Item 2212 remains low-confidence; certification suppresses some substation/belt collision findings. Full paste evidence must use the game's live build-condition oracle or an actual paste, not infer safety from a clean Python certificate. Gate(b) records56/72 substation CLEAN versus66/72 default; gate(c) records1/6 versus2/6, so the six-CLEAN requirement fails. All refusals remain failures.

R8 is fixed in the integration with master `f162d9e1`: candidate sites and emitted buildings retain their anchors; coverage scoring, spreading, stamping and incremental removal use the actual footprint centre. The frozen pre-integration planner fails the east/west boundary regressions; the corrected planner passes all five centre/infill regressions. Tesla's 1x1 centre offset remains zero. These later source changes are outside the original gate measurements above.

The C# `oracle/` program exercises `MatchInserter`; it is not a full paste validator. `tools/dsp-oracle` is the in-game BepInEx build-condition oracle: hover a generated blueprint and press F9 to capture the next completed `CheckBuildConditions` verdict. Save that JSON alongside the exact blueprint, game version, band/anchor and screenshot.

Integration runtime evidence (Main's archived integration ledger):

- Hierarchical iron-ingot at 60/min with `--power-tower wireless` exits0: one machine, 70 tiles, 15 buildings, certified bands32/40/60. This exercises a non-default selected power building through actual composition.
- Hierarchical iron-ingot and titanium-ingot with substation still exit3 before composition. The direct iron-ingot diagnostic captures `_Unpowerable`: all63 demand tiles lack a legal tower site on the packed canvas. This is a 7x7-clearance standing-ground refusal, not an observed certificate rejection; the CLI's generic `power.coverage` summary does not distinguish them.
- All15 failures caused by the integration's incorrect `Buildings.of(sequence)` call pass serially after using the sequence constructor. The full affected-suite run also retains the inherited band160 and two-stage-alignment failures; it is not a clean full-suite result.

The selected-record infill and clearance regressions pass, but the failed substation CLI runs do not establish an end-to-end composed-substation build. Missing game/.NET prerequisites remain recorded in `gate-d-dotnet.txt`, not counted as PASS.
