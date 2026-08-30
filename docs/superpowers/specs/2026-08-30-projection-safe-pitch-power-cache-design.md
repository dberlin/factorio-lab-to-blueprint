# Projection-Safe Strip Pitch and Power-Legality Cache

## Goal

Make exact projected same-strip machine collisions repairable by both production strategies, then remove repeated projection work from powered preparation without changing legality or evidence.

The first change is a quality fix with a measured speed benefit. The second is a parity-preserving speed optimization. They land and verify independently in that order.

## Measured Problem

At current head, `plastic` refuses under both Freeform and SequencePair even at the default 15-second budget. Every exact projection failure names adjacent Chemical Plants (`item_id=2309`, `model_index=64`) in `owner_strip=2`, separated by the flat collider pitch of seven tiles. Representative pairs are `(x=3, x=10)` and `(x=13, x=20)`. Required band projections make their build colliders overlap.

Existing `ProjectionNoGood` feedback deliberately handles only different owner strips. Repacking cannot alter two machines' relative positions inside one strip, so the failure repeats unchanged.

A throwaway Freeform experiment increased only Chemical Plant pitch from seven to eight. The `plastic/all-products` 4-second cell changed from `REFUSED` at about 4.21 seconds to validator-clean `OK` at 3.44 seconds, with area 750, 220 belt tiles, and 260 buildings. The same patch did not affect SequencePair because its authoritative pitch comes from `StripVariant.placement_geometry`; this confirms the fix belongs in shared physical variants rather than a Freeform-only `_Strip.pw` override.

Powered preparation is the next measured speed target. A profiled SequencePair `quantum-chip` run executed about 177,000 `projected_power_failure` calls and 354,000 projection-position conversions. cProfile inflated absolute wall time, but the call counts and concentration are real: each candidate tower repeatedly reprojects every accepted peer for every required projection.

## Constraints

- Exact `finalize_placement` projection checks remain the only acceptance authority.
- Normal collider pitch remains the default. Already-valid geometry does not become padded speculatively.
- Feedback changes only the implicated strip family, pose, and machine axis.
- No global machine clearance change, blanket inter-strip margin, candidate blacklist, larger search budget, larger archive, or hidden retry floor.
- Existing different-strip `ProjectionNoGood` behavior remains unchanged.
- Every retry stays inside the caller's existing deadline and configured candidate schedule.
- Failure order, band, building indices, and detail remain stable when no repair succeeds.
- Power-cache optimization must preserve selected tower sites and first-failure evidence exactly.

## Typed Intra-Strip Pitch Feedback

Add an immutable internal value representing one exact projected pitch failure:

```python
@dataclass(frozen=True, slots=True)
class ProjectionPitchRequirement:
    family_id: StripFamilyId
    instance_id: StripInstanceId
    variant_id: StripVariantId
    axis: Literal["x"]
    rejected_pitch: int
    required_pitch: int
    failure: ProjectionFailure
```

A `geom.collide` failure maps to this value only when all of the following hold:

1. exactly two valid building indices are present;
2. both buildings have the same integer `owner_strip`;
3. that owner maps to the selected strip instance for this attempt;
4. both buildings are machines belonging to that instance, with identical item, model, and yaw;
5. their machine ordinals are adjacent on the strip's local X axis;
6. their origin separation equals the selected variant's current `pitch_x`.

Anything else remains ordinary structured projection evidence. It does not create pitch feedback.

`required_pitch` is `rejected_pitch + 1`. If the next exact attempt fails the same typed relation, feedback advances by one again. Requirements deduplicate by family, pose, and rejected pitch. Only the latest required pitch for that family/pose is retained, so repeated evidence does not accumulate an unbounded variant set. The existing deadline bounds retries.

## Shared Padded Variants

`MachinePlacementGeometry` gains a constructor/helper that adds deterministic east-halo padding while preserving footprint and the invariant:

```text
west_halo + footprint_width + east_halo == pitch_x
```

Strip-variant generation accepts an explicit non-negative X padding. It regenerates:

- `MachinePlacementGeometry`;
- machine origins;
- box width;
- `StripVariantId` physical identity;
- lane extent;
- attachments and port docks through the existing pose-valid planning path.

The padding is part of variant identity. A padded variant is not an alias of the rejected ordinary variant.

Variants are generated on demand from typed feedback. Each family/pose exposes its ordinary variants plus at most one currently required padded variant. Ordinary variants remain the deterministic default and the only variants eligible before feedback. If repeated evidence raises the required pitch, states that still reference the superseded padded variant are migrated to the replacement variant before the next move; the superseded identity is no longer selectable.

## Freeform Integration

Freeform records pitch requirements beside existing different-strip projection no-goods.

When finalization returns a typed same-strip requirement:

1. retain the original structured refusal;
2. update the implicated family/pose's required pitch;
3. regenerate that strip from the shared padded variant path;
4. insert one retry of the same height and arrangement at the current candidate position;
5. keep all other strips, packing rules, routing rules, deadline checks, and winner ordering unchanged.

The retry is a replacement for an otherwise repeated impossible candidate, not an additional arrangement allowance. If the padded strip changes width, CP-SAT repacks under the existing height and current projection no-goods.

## SequencePair Integration

SequencePair maps `owner_strip` through the attempt's `instance_ids` and selected variant IDs. On typed same-strip evidence it enables the on-demand padded variant only for the implicated family/pose.

The next feedback-driven state substitutes that variant through the existing variant-move/LNS path. The move counts against existing stage work and preserves family machine conservation, instance ranges, restart state, expansion accounting, and exact incumbent ordering. A validation failure never establishes an incumbent.

Stage observations retain the original `projection_failures` and additionally identify whether a pitch requirement was learned and which variant became eligible. Terminal refusal reporting remains based on authoritative projection failures, not the derived repair hint.

## Power-Legality Cache

After pitch feedback passes its quality gate, optimize `_power_plan` without changing its decisions.

Create one attempt-local prepared evaluator for the existing projection tuple. For each projection it stores projected positions for accepted power nodes in the same order as `power_nodes`.

For a candidate tower:

1. project the candidate once per projection;
2. compare it with cached peer positions in the existing projection-outer, peer-inner order;
3. call the existing `_power_pair_condition` with the exact squared distance;
4. return the same first `ProjectionFailure` fields as `projected_power_failure`;
5. append candidate positions to the cache only after the tower is accepted.

The pre-existing-node legality check continues to call the existing exact `projected_power_failure` once. The cache optimizes only repeated candidate-versus-peer evaluation.

After the candidate evaluator passes its parity and speed gate, benchmark `_projection_envelope` separately. Add immutable memoization only when it materially improves the same cases. Its key must include occupied bounds, capacity bounds, and complete `BandPolicy` identity.

No persistent or cross-build cache is added. Attempt-local state avoids stale catalog, policy, or geometry data and requires no invalidation protocol.

## Verification

### Pitch feedback contracts

- A focused regression reproduces the adjacent pitch-seven Chemical Plant collision and fails before feedback.
- Mapping rejects different-strip, non-adjacent, different-model, different-yaw, sorter, belt, tower, missing-owner, and malformed-index controls.
- Padded variant identity, geometry, machine origins, box width, lanes, slots, and instance partition remain internally consistent.
- Freeform retries only the implicated family/pose and produces a validator-clean `plastic` placement.
- SequencePair enables and selects the padded shared variant through its existing feedback path and produces a validator-clean `plastic` placement.
- Existing different-strip no-good tests and exact path/placement determinism remain green.

### Pitch quality and speed gate

At the existing 4-second audit budget:

- `plastic` must be 18/18 clean over three interleaved repeats: three proliferation policies times two strategies times three repeats;
- no `INVALID` or `CRASH` result is permitted;
- no configured budget, arrangement count, stage count, archive capacity, or island count increases.

At the default 15-second budget, all six strategy/policy cells must be clean. Compare the paired current corpus at the same worker count and seeds:

- already-clean cells may not lose coverage over three paired repeats;
- deterministic ordinary-variant fixtures retain exact selected geometry;
- padded cells compare by exact `(area, belt_tiles)` and may grow only when the unpadded result is invalid/refused;
- paired geometric-mean area on already-clean corpus cells may not regress by more than 1%;
- median wall time must not regress by more than 5% on already-clean cells.

### Power-cache parity and speed gate

Reference and cached evaluators must match exactly for fixed and randomized node/projection sets:

- accepted/rejected result;
- first failure check, band, building indices, and detail;
- selected tower-site sequence from `_power_plan`;
- final placement, path digest, and validation result.

Benchmark `plastic`, `super-magnetic-ring`, and `quantum-chip` under both strategies with two repeats at the existing 4-second profile budget. Keep the cache only if it reduces median powered-preparation time by at least 20% in two cases or end-to-end median wall time by at least 5% in one case, with no quality regression. Otherwise retain the pitch work and discard the cache change.

## Rollout

1. Land typed pitch feedback and shared padded variants with focused tests.
2. Run the `plastic` 4-second and 15-second gates, then the paired corpus quality gate.
3. Land the attempt-local power evaluator as a separate commit.
4. Run exact parity, focused benchmarks, full Python tests, Ruff, MyPy, and whole-branch review.
