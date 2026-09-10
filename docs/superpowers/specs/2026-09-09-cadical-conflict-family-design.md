# CaDiCaL semantic factors and conflict families

Status: proposed design, not implemented. Prepared from two collaborating design agents and Main's integration review. No new solver result or performance improvement is claimed.

## Decision

Replace flat Cartesian candidate Booleans and collision-cell learning with **separate XY/height choices and demand-driven exact primitive-conflict families**. Keep CaDiCaL, the original finite candidate universe, physical emission, static legality, independent validation, and every original budget.

This is one new experimental architecture, not production promotion. Implementation requires approval of this design.

Detailed, mutually reviewed specifications:

- [SAT representation, encoding and lifecycle](2026-09-09-cadical-sat-architecture-note.md)
- [Geometry, ownership and conflict-family proof](2026-09-09-cadical-geometry-architecture-note.md)

This integration document resolves scope and acceptance policy if the detailed notes differ.

## Evidence and hypothesis

The path-envelope mall reached its 5,000,000-predicate cap at 36.984 seconds, after 46 rounds and 8,776 collision cuts. Height-order reached the same cap at 39.886 seconds, after 44 rounds and 8,552 cuts. Both had zero lazy static cuts and no selected witness. Their controls passed. These are bounded failures, not infeasibility proofs.

The current source creates one Boolean for every `(XY combination, height)` candidate. `occupancy_literal()` then adds a candidate-to-occupancy implication for every member of each newly encountered occupancy mask. Existing mask interning already removes identical masks; more caching does not change this representation or learning unit.

**Hypothesis [INFERENCE]:** semantic factors remove Cartesian selector duplication, while a learned primitive family excludes unvisited conflicting heights and XY choices at first discovery. Together they may leave enough of the unchanged original gate for selection and complete settlement. Whether weaker propagation, primitive preprocessing, retained model checking, or rectangle volume defeats this is unmeasured.

The retained aggregate timings do not identify a particular function as the bottleneck. In particular, `preparation_seconds` starts before selection and includes construction/capture; subtracting preparation and completed native calls from total elapsed is not an occupancy-compilation profile.

## Architecture

```text
Unchanged emitter and exact TemplateProblem
                 |
        Original finite domains
                 |
       XY selectors + height selectors
       Exact original static exclusions
                 |
              CaDiCaL
                 |
       Original candidate-ID reconstruction
                 |
       Unchanged independent model checks
           /                         \
     forbidden pair                  clean model
           |                             |
     raw primitive witness        final Cartesian audit
           |                      emission / settlement
     exact combo memberships      physical / codec checks
     + forbidden height relation         |
           |                      existing gate outcome
     normalized rectangles
           |
     guarded CNF constraints --------> CaDiCaL
```

### Choice representation

For every original domain, choose exactly one XY combination `X[c]` and exactly one legal-height index `H[p]`. Preserve the exact original ordering and all IDs, including geometrically duplicate choices.

Reconstruct `candidate_id = c * len(levels) + p`, then invoke unchanged `Domain._decode`. Original obligation ordinals remain the external keys; do not assume contiguous IDs.

An existing rejected candidate becomes the exact binary exclusion `not X[c] or not H[p]`. Keep the proven static exclusion machinery and selected-path self checks rather than redesigning them in this change.

### Geometry producer

Represent raw template segments using the existing `_adapter` and `_middle` generators:

- **G:** fixed adapter segment at endpoint height.
- **M:** middle segment at the selected height.
- **R:** riser between a fixed endpoint height and the selected height.

Intern only identical complete parametric descriptors within a domain. Associate each with the exact XY-combination mask containing that primitive. Keep reverse combo-to-primitive provenance. Do not build a global primitive-pair or XY-pair join.

When the existing checks find an incompatible selected pair, locate a concrete conflicting raw primitive pair. Derive its exact forbidden height relation using closed intervals and actual legal heights. This relation generalizes only across combinations guaranteed to contain those exact primitives.

For example, middle/middle intersections forbid equal heights; middle/riser intersections forbid heights inside the riser's closed vertical interval. These are general formulas, not rules specialized to the observed all-ground mall endpoints.

Ownership is exempt only when the **entire intersection is a singleton** allowed by the original `_owned` predicate. Coincidence alone is insufficient. Keep item, physical port, direction, source/sink role and junction identity. Keep physical port-identity preflight before spatial rejection. Compiler-owned body contacts remain separate from path-sharing permissions.

### Constraint protocol

Geometry emits domain IDs, exact primitive/combo memberships, selected-witness provenance and a forbidden relation over original legal-height indices.

For each left height, partition right heights at exact intersection/ownership critical constants, preserving equality classes and gaps. Produce maximal forbidden index runs. Merge adjacent left rows only if their complete ordered right-run lists are identical. The resulting rectangles are a lossless representation, never a bounding-box approximation.

SAT defines exact combo-membership guards `G[d,S]` and exact suffix thresholds `T[d,k] = (height_index >= k)`. A forbidden rectangle `[a,b] × [c,e]` under guards `Gi,Gj` becomes:

`not Gi or not Gj or not Ti[a] or Ti[b+1] or not Tj[c] or Tj[e+1]`.

Every family must contain the currently rejected pair. Every invalid model must receive a newly effective exact prohibition. Missing provenance, inconsistent oracles, empty advertised families, and exhausted budgets are failures/refusals—not reasons to silently fall back. Exact point nogoods exist only as a throwaway diagnostic baseline, not a second runtime backend.

## Preservation obligations

The required proof chain is:

1. Exactly-one XY and height choices are bijective with original candidate IDs.
2. Every combo in a primitive mask actually contains that complete primitive.
3. Raw-segment occupancy equals normalized-path occupancy, including degenerate segments and retraces; self-validity remains independently checked.
4. Height partitions and normalized rectangles exactly express forbidden intersections, including descending risers, nonconsecutive heights, equal endpoints and singleton ownership.
5. Truthful auxiliary guard/threshold assignments exist for every original feasible selection. No family clause excludes one.
6. Every rejected selected pair is excluded by its own certified constraint.

The unchanged selected-cell/index disagreement checks, final Cartesian comparator, physical audits, registered validation and codec round trip remain mandatory. A smaller SAT model is not acceptance. Geometry-only success is not rated-factory acceptance.

## Derived size and principal risks

The retained mall has 141 domains, each with 250 XY choices and 24 heights:

| Quantity | Derived count |
| --- | ---: |
| Original logical candidates, still admitted and charged | 846,000 |
| Factored primary choice variables | 38,634 |
| Base variables including reused exactly-one auxiliaries and thresholds | at most 53,157 |
| Base clauses including thresholds | at most 102,789 |
| Clauses after retaining all 107,653 original static bans, before family guards/cuts | at most 210,442 |

These are arithmetic bounds for the specified encoding, **not observed compiler output, total final CNF, memory measurements or speed forecasts**.

Up to nine raw primitives per XY combination means at most 317,250 occurrences before interning. Conversely, eager enumeration of all cross-domain XY pairs would mean 616,875,000 pairs before heights; it is outside this design.

Principal risks are primitive/membership storage and preprocessing, wide guard clauses with weaker propagation than cell-wide AMOs, many distinct families, retained checking cost, and cut-cap pressure. Equal-height exclusion across 24 common heights can require 24 rectangles; the unchanged 20,000-cut allowance can therefore still stop refinement early.

## Accounting and scope

- Original 30-second control and 60-second mall layout-through-settlement deadlines remain authoritative. All new preparation runs inside the gate.
- Preserve every existing work limit, native-call setting, topology order, round cap and clause cap. Preserve shared accounting across topology attempts.
- Charge the full original logical candidate-domain size despite fewer SAT variables.
- Charge performed primitive, partition, mask, normalization, indexing and construction work; retain deadline checks on reuse paths. No uncharged preprocessing or work relabeling.
- Each distinct normalized rectangle prohibition consumes one of the existing 20,000 collision-cut units. Every auxiliary/guard/static/self/family clause consumes the existing 20,000,000-clause allowance. Deduplication work itself is accounted.
- Implement only in a new isolated revision branching from path-envelope. Preserve every frozen predecessor. No geometry changes, tuning sweep, new router, spec/boundary changes, budget increases or production integration.

## Discriminating experiment and acceptance

After approval, establish the family/projection proof on deterministic small domains and one predeclared actual-domain pair sample. Compare independent expanded/canonical geometry with family truth in both directions. Include mutations targeting ownership, descending risers, endpoint equalities, incorrect masks and lossy rectangle merging.

A throwaway solver-free comparison may compile the same sampled conflicts as semantic-factor point nogoods and family rectangles. This separates generalization from selector reduction. Use bounded, accounted computation and record structural counts; do not treat sample speed, coverage or compile size as mall success.

After correctness and cost admission, freeze one revision and run:

1. Original complete control within 30 seconds and all unchanged caps.
2. Only on control acceptance, original complete mall within 60 seconds and all unchanged caps.
3. Only on mall acceptance, required cold-success repeats and then eligible held-outs.

The performance hypothesis is falsified for that revision if it still cannot complete the original mall gate. No arbitrary additional clause/predicate/selection-time target may reject a valid full-budget success or accept an incomplete one. Semantic disagreements, hidden domain restrictions, missing checks and altered effective limits reject the design independently of runtime.

## Collaboration and review

Both agents worked concurrently and exchanged proposals and substantive critiques. SAT moved from narrower whole-XY-pair height-order learning to geometric primitive families. Geometry addressed normalized-path provenance, ownership and eager-expansion concerns. They agreed on exact factor identities, critical-height partitions, rectangle serialization, guard/threshold CNF, monotone progress and conservative cut accounting.

Main reviewed both notes against the current selector and domain implementation, confirmed the derived encoding arithmetic, excluded speculative runtime fallback scope, and rejected unsupported extra numeric performance gates. There is no remaining design disagreement; feasibility, cost and the new proof obligations remain unverified. No implementation or solver run was performed for this design task.
