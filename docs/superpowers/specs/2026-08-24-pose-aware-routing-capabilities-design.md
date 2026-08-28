# Pose-Aware Machine and Coater Routing Design

**Status:** Architecture approved; implementation not started
**Worktree:** `/home/dannyb/sources/factorio-lab-to-blueprint-sequence-pair-solver`
**Branch:** `sequence-pair-solver`

## 1. Decision

Extend the sequence-pair solver with three game-derived capabilities:

1. machine orientation is a placement decision over pose-valid strip variants;
2. lane seating and sorter reach are derived from exact machine slot poses rather than footprint-edge distance;
3. Spray Coater proliferator supply is an elevated belt routed directly to the coater addon supply pose, with no sorter.

The implementation must consume the authoritative game-rule data and helpers from the completed `game-rules` branch. It must not recreate building-name exceptions, refinery constants, Chemical Plant spacing constants, sorter slot inference, or coater serializer rules.

The prior 2,337-area result for the supplied FactorioLab URL is retracted as a game-feasible result. It passed the superseded model but can violate pose, slot-anchor, and coater-supply rules.

## 2. Current state and boundaries

The audit-only sequence-pair backend is implemented and correctness-tested against the repository's previous shared model. Production `FreeformLayout` remains unchanged.

The authoritative game-rule work is in the `game-rules` branch/worktree and includes:

- `src/flab2bp/dsp/data/slot_poses.json` extracted from game assets;
- catalog loading of real slot poses;
- `layout/slots.py` pose transforms, legal attachment selection, and sorter slot assignment;
- game-derived validation of sorter placement and fields;
- externally owned altitude/slope/ceiling and serializer corrections.

Only committed/finalized game-rule interfaces may be merged. Uncommitted integration code in another worktree is evidence and design context, not source to copy blindly.

## 3. Goals

- Rotate machines only through poses supported by authoritative pose geometry.
- Let sequence-pair SA choose orientation with rectangle dimensions, port geometry, and lane seating as one atomic variant.
- Separate catalog footprint from game-derived collider envelope and integer placement pitch; repeated machines and adjacent strips must not overlap world-space colliders.
- Preserve regular shared lanes by keeping every physical strip pose-homogeneous.
- Allow LNS to split a logical strip into pose-homogeneous child strips when one pose is insufficient or routing feedback implicates it.
- Determine every lane row and sorter anchor from actual attachable slot poses.
- Route elevated coater supply as an ordinary z-aware routing demand handled by both global and detailed routers.
- Reject candidates whose required pose, lane attachment, or coater supply cannot be detailed-routed and validated.
- Preserve exact machine counts, rates, net identities, shared budgets, detailed feedback, and validator-only acceptance.

## 4. Non-goals

- Do not infer a generic perimeter ring from footprint size.
- Do not special-case Oil Refinery or Chemical Plant names in search or emission.
- Do not permit mixed machine poses inside one physical strip.
- Do not add a second internal placer inside a strip.
- Do not feed Spray Coaters with a sorter.
- Do not lift a completed ground route after routing.
- Do not implement externally owned blueprint serializer, sorter-field, or altitude-rule fixes in this branch.
- Do not resume acceleration, Pareto claims, or production cutover as part of these capabilities.

## 5. Authoritative geometry interfaces

### 5.1 Slot poses

Catalog buildings expose immutable game-extracted slot poses. Pose transforms provide:

- local-to-world slot offset for a cardinal yaw;
- slot forward direction;
- legal machine-side sorter anchor for a far lane cell;
- actual sorter span;
- every attachable machine column for a lane row;
- whether a yaw exposes a usable north or south face.

Search, lane planning, emission, and validation consume the same helpers. No phase may independently reinterpret a pose.

### 5.2 Collider envelopes and placement pitch

The game-rule catalog exposes one authoritative world-to-grid placement geometry per building pose:

```python
@dataclass(frozen=True, slots=True)
class MachinePlacementGeometry:
    footprint_width: int
    footprint_height: int
    pitch_x: int
    pitch_y: int
    west_halo: int
    east_halo: int
    north_halo: int
    south_halo: int
```

One grid tile is `2π/5` world units. Pitch is derived from the oriented collider dimensions, not from footprint tile count. The confirmed discriminator is an Arc Smelter with 3×3 footprint and pitch 3 versus an Assembling Machine Mk.I with the same 3×3 footprint but pitch 4 because its 3.82-world-unit collider exceeds three tiles (`3 × 2π/5 ≈ 3.770`).

The solver consumes a catalog/game-rule helper for this conversion. It does not copy collider constants or perform building-name checks.

For a uniform row of `n` machines, origins advance by `pitch_x`, not footprint width. The machine band and strip exclusion envelope include the pose-derived edge halos so machines in another strip and adjacent lane belts cannot enter the collider. Footprint remains the building record's occupied/anchor geometry; pitch/envelope is placement exclusion geometry.

### 5.3 Addon supply poses

Add an immutable catalog representation for game-extracted addon supply poses when the finalized game-rules branch does not already provide one:

```python
@dataclass(frozen=True, slots=True)
class AddonSupplyPose:
    dx: Fraction
    dy: Fraction
    dz: Fraction
    area: int
```

The Spray Coater proliferator input uses its authoritative addon area pose. The known game rule places the supply behind the coater and one altitude level above the host belt; implementation uses extracted pose data rather than embedding `(0, -1.25, 1)` in layout code.

## 6. Domain model

### 6.1 Logical strip family

`StripFamily` is the placement-independent statement of work:

```python
@dataclass(frozen=True, slots=True)
class StripFamily:
    family_id: StripFamilyId
    group_key: str
    recipe_id: str
    machine_item_id: int
    total_machine_count: int
    input_lanes: tuple[LogicalLane, ...]
    output_lanes: tuple[LogicalLane, ...]
    variants: tuple[StripVariant, ...]
```

`StripFamily` owns the immutable logical group/shard and its total machine count. Changing half-open machine ordinal ranges live only on `StripInstance`; active instance ranges must partition `0..total_machine_count` exactly once.

### 6.2 Pose-specific strip variant

`StripVariant` is an atomic physical choice:

```python
@dataclass(frozen=True, slots=True)
class StripVariant:
    variant_id: StripVariantId
    yaw: float
    footprint_width: int
    footprint_height: int
    pitch_x: int
    pitch_y: int
    placement_geometry: MachinePlacementGeometry
    lane_plan: LanePlan
    box_width: int
    box_height: int
    attachment_plan: tuple[LaneAttachmentPlan, ...]
```

Changing variant changes orientation, oriented footprint, lane rows, exact sorter anchors/spans, and sequence-pair rectangle dimensions together. A caller cannot combine the footprint from one pose with anchors from another.

Direct-insert targets are derived from the complete selected instance/variant set because their geometry depends on both producer and consumer variants. They are not intrinsic fields of either endpoint variant.

### 6.3 Physical strip instance

`StripInstance` binds one family range to one variant. Its stable identity is `(group_key, machine_start, machine_count)`. A split replaces one instance with two adjacent non-overlapping ranges; a merge is the exact inverse.

Physical routing `NetId`s include the current instance identity. Feedback net criticality remains keyed by logical recipe edge so it survives split/merge; physical wall ownership maps back to current instances for LNS.

## 7. Variant generation

For each strip family:

1. Evaluate cardinal yaws `0°, 90°, 180°, 270°` through authoritative pose transforms.
2. Compute the oriented footprint and collider-derived placement geometry.
3. Compute machine origins using oriented pitch and reserve the full collider envelope.
4. Enumerate feasible lane seating plans for the required logical lanes outside that envelope.
5. For every prospective lane row, compute legal attachments for a representative oriented machine.
6. Require enough distinct attachable columns for all items sharing that lane.
7. Require every attachment span to be inside sorter reach and choose sorter tier from the actual span.
8. Apply the same relative attachment plan and pitch to every machine in the uniform strip.
9. Reject any pose/seating combination that leaves a required lane or machine unattached or overlaps a collider envelope.
10. Deduplicate variants with identical yaw, placement geometry, lane rows, attachments, and box dimensions.
11. Sort variants deterministically by area, yaw, lane rows, and attachment fields.

An upright Oil Refinery variant with no north-facing pose is rejected when north service is required. Rotated variants are admitted only when their transformed poses provide every required attachment.

## 8. Exact lane seating

Generic rules such as `lane_count <= SORTER_MAX_REACH` are removed from feasibility decisions.

For each variant side and lane offset, a `LaneReachProfile` records:

- lane y relative to the oriented machine origin;
- attachable columns;
- selected anchor cell per column;
- selected slot index;
- actual sorter span;
- alignment/reach validity.

Lane seating assigns logical lanes to profile entries. Shared-item lanes require distinct usable columns for their simultaneous sorters. Output and input ordering remains deterministic but cannot override pose feasibility.

A Chemical Plant's inner slot anchor consumes reach automatically: a lane row whose footprint-edge distance appears legal is rejected when the real anchor makes `Attachment.span > SORTER_MAX_REACH`. A closer row succeeds without a Chemical Plant-specific spacing constant.

Emission consumes the precomputed `LaneAttachmentPlan`. It does not recompute a nearest edge, clamp a column, or choose a different slot. Validation verifies that emitted anchors match a legal game pose.

## 9. Sequence-pair search changes

`PlacementProblem` stores one variant table per physical strip instance. `AnnealState` gains a variant index per sequence-pair member.

Within a fixed-cardinality temperature stage, moves are:

- change one strip to another pose-valid variant;
- existing permutation, insertion, gap, and local LNS moves.

Split and merge are stage-boundary LNS transformations. They rebuild the `PlacementProblem`, both permutations, physical nets, prepared geometry inputs, and feedback endpoint mapping before the next fixed-cardinality SA stage. They never change cardinality inside `anneal_stage`.

The decoder reads dimensions from the selected variant. `PlacementKey`, cache identity, elite identity, and exact state equality include instance ranges and variant indices.

A variant move is rejected before decoding when it cannot serve required lanes. It may change width/height and therefore participates in ordinary SA energy and outline overflow.

## 10. Pose-homogeneous split LNS

Uniform pose per strip is the normal representation. Split LNS provides per-machine flexibility without irregular strips.

A split:

- chooses one internal machine ordinal boundary;
- partitions the parent's exact machine range;
- preserves all machines exactly once;
- creates two child families with independently selected pose-valid variants;
- partitions lane demand/supply deterministically by machine count and existing shard rules;
- replaces the parent in both sequence permutations at a deterministic insertion point;
- rebuilds physical nets while retaining logical edge weights.

A merge is legal only for adjacent ranges of the same logical group whose variants and lane plans are compatible. One-machine strips are allowed when independent orientation is necessary.

Feedback selects split candidates when:

- no single variant serves all required faces;
- a stranded net or blocking wall implicates the strip;
- focused variant LNS stagnates.

Split growth remains bounded by machine count and the existing strip-length policy. It cannot create empty ranges or duplicate/drop machines.

## 11. Elevated coater supply

### 11.1 Topology

The sprayed-item belt remains the coater host. The proliferator supply is a separate elevated belt routed directly to the coater addon supply pose.

```text
external proliferator entry
→ z-aware global route
→ z-aware detailed route
→ elevated coater supply port
```

There is no sorter between proliferator belt and coater. No sorter may name a Spray Coater as input/output.

### 11.2 Prepared routing problem

Preparation creates one `CoaterSupplyPort` per coater from:

- coater world position and yaw;
- host belt altitude;
- transformed authoritative addon supply pose;
- exact elevated target cell/anchor;
- owning coater and sprayed lane identity.

The target cell and necessary approach footprint are reserved before any route. The proliferator logical net terminates at this elevated port. Compatible coater supply segments may share a trunk only when the detailed emitter can commit the same topology.

### 11.3 Routing and emission

Both global and detailed routers receive the same elevated target. The router must produce the level transition and elevated final segment through shared movement helpers. The layout does not rewrite z after routing.

Detailed emission commits the elevated supply belt and positional addon connection. Serializer slot/addon fields remain supplied by the authoritative game-rules integration.

A candidate is stranded/refused when the elevated port cannot be reached. A ground-only supply cannot be counted as connected.

## 12. Closed-loop scoring correctness

Before capability work, fix the final whole-branch review findings:

1. make routing-history cost candidate-dependent by evaluating spatial history against each proposed decoded placement;
2. compute missed direct-insert opportunities from each candidate rather than leaving the production context at zero;
3. require successful independent cross-validation for every valid persisted blueprint before promotion eligibility;
4. reject fractional, negative, non-finite, or coerced persisted integer metrics.

These are correctness fixes, not performance work.

## 13. Integration sequence

1. Commit/verify current sequence-pair branch state.
2. Merge the finalized authoritative game-rules branch into this worktree.
3. Resolve conflicts by preserving shared pose/serializer/altitude interfaces and sequence solver contracts; never duplicate either implementation.
4. Apply final-review correctness fixes.
5. Introduce strip family/variant state and variant SA moves.
6. Replace generic lane seating/emission with pose-derived plans.
7. Add split/merge LNS and machine-range conservation.
8. Replace ground coater drops/sorters with elevated supply ports/routes.
9. Run focused game-rule regressions, full tests, modeled audit, and supplied URL.
10. Keep acceleration, Pareto performance conclusions, and production cutover deferred.

## 14. Verification

### Pose and rotation

- Pose data loads for all catalog buildings covered by the extracted table.
- Oil Refinery upright pose cannot serve a north lane when no pose faces it.
- A rotated pose-valid refinery variant serves required lanes and swaps oriented footprint dimensions.
- Variant moves update dimensions, lane plans, attachments, and placement key atomically.
- No emitted sorter uses geometry from a different variant.
- Arc Smelter 3×3 rows retain pitch 3; Assembling Machine Mk.I 3×3 rows use pitch 4 from collider geometry.
- Repeated machine origins advance by pitch, and strip/lane exclusion respects pose-derived collider halos.
- A footprint-equal but collider-overlapping arrangement is rejected before routing.

### Lane reach

- Chemical Plant lane at the previously assumed three-clear row is rejected when its real anchor exceeds reach.
- A closer row produces legal `Attachment.span` and slot geometry.
- Shared lanes receive enough distinct attachable columns.
- Every planned attachment is reproduced exactly during emission.
- Generic 3×3 behavior remains valid through the same pose API.

### Split/merge

- Split children partition parent machine ordinals exactly.
- Merge is inverse only for compatible adjacent ranges.
- Repeated split/merge cannot duplicate or drop machines, rates, lanes, or logical edges.
- Feedback and stable logical net weights survive physical instance changes.
- One-machine terminal strips remain legal.

### Coaters

- Coater supply target is transformed from authoritative addon pose.
- Supply target is elevated relative to host belt as required by game data.
- Global and detailed routes terminate at the same elevated port.
- No sorter targets a Spray Coater.
- Ground-only supply is rejected.
- Unreachable elevated supply produces structured stranded feedback and no placement.
- Validator confirms addon supply and host-lane association.

### End-to-end

- Existing sequence/freeform tests remain green after game-rule merge.
- Full Ruff lint, mypy, and pytest pass, excluding inherited repository-wide formatter drift already present at merge base.
- Broad sequence audit has zero INVALID and CRASH outcomes under the merged game rules.
- The refinery pose regression URL (`https://factoriolab.github.io/dsp/list?z=eJxFyrEKwkAQRdG.meJVM0GxmuYtxk4SQXFbdRGJSyCgaDPfLqJod7jc0XmGqYzOI2ZzBezt598LNPrlDs3vyLBPLo5WqhMq1TNULofilKk8vEPGCQNu4BrcgntwCF6R2kgrpD7SRmqdPAdjGb3c3ewFUJ8mgA__&v=11`) produces a game-rule-valid Freeform and SequencePair result rather than the current master refusal; Spine remains a comparison oracle.
- The earlier Chemical/coater URL is solved across all candidates; only game-rule-aware, detailed-routed, independently cross-validated output is reported.
- The old 2,337-area blueprint is not reused or compared as valid evidence.

## 15. Rollout

The enhanced `SequencePairLayout` remains explicitly selectable in audit/A-B tooling. It does not replace production `FreeformLayout` in this change.

Numba/JAX selection, Pareto speed claims, and production cutover remain blocked until the merged game model and these capabilities pass the full correctness gate.
