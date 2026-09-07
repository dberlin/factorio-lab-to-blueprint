# Power-tower integration with hierarchical-v4

Implementation handoff, not a gate pass. Measurements, independent review, and live paste evidence remain pending.

- `BuildSpec.power_tower_item_id` is the single persisted choice, a FactorioLab item id.
- `catalog.power_tower_building(lab_id)` resolves the catalog record. `_Canvas.power_building` carries that record through one layout run. Read the canvas record inside routing scope; do not resolve repeatedly in hot loops.
- The existing `hierarchy.partition.sub_spec` and `composed_spec` rebuilds preserve the field. Every new `BuildSpec(...)` construction must preserve it too. Keep machine-rank plumbing when combining the branches.
- Hierarchical-v4's `plan_power_infill` must receive the chosen record from `catalog.power_tower_building(spec.power_tower_item_id)`, including every scratch/retry canvas. Do not retain a Tesla fallback inside a selected substation run.
- This branch's `_power_reservation(tower)` encloses catalog clearance symmetrically on the integer grid: 6x6 clearance about a 5x5 substation means offsets `[-1,6)` on each axis (7x7 occupied routing cells). The actual emitted building remains item 2212, model 68, footprint 5x5. Tesla remains 1x1.
- Parent composition routing must treat already emitted child substations' clearance halos as obstacles, not only their 5x5 solid footprints. Existing `canvas_for` generic `solid=True` insertion alone does not guarantee this halo. Carry the reservation through parent route preparation and post-routing infill; include projected collision checks, not just flat reservations.
- Reuse the existing `TestALargePowerBuildingClaimsItsWholeFootprint` direct geometry checks at block boundaries. They now check the clearance halo as well as footprint; also retain the four-sided emitter refusal regression and no-clearance-hole regression.

## Explicit unresolved gates

R9's original acceptance is superseded by R12: the named flat-grid reservation gap has an implementation, but is not verified and is not an independent review approval. Item 2212 remains low-confidence; certification suppresses some substation/belt collision findings. Full paste evidence must use the game's live build-condition oracle or an actual paste, not infer safety from a clean Python certificate.

R8 is unchanged: `_power_plan`'s coverage scoring/stamping is anchor-centred, while emitted substation coverage is centred on the actual footprint. This can cause false refusals or `power.coverage` rejection. It cannot justify accepting a dark layout; classify each gate refusal explicitly. Default Tesla scoring and tie-breaking remain untouched.

The C# `oracle/` program exercises `MatchInserter`; it is not a full paste validator. `tools/dsp-oracle` is the in-game BepInEx build-condition oracle: hover a generated blueprint and press F9 to capture the next completed `CheckBuildConditions` verdict. Save that JSON alongside the exact blueprint, game version, band/anchor and screenshot.
