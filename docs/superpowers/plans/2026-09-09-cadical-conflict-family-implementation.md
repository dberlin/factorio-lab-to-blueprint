# CaDiCaL Conflict Family Implementation Plan

> **Execution:** Inline using executing-plans. User approved the integrated design. No new subagents, commits, merges, pushes or production promotion.

**Goal:** Implement and evaluate exact XY/height factors with demand-driven primitive conflict families under the unchanged original gates.

**Architecture:** Fork path-envelope into `.superpowers/sdd/2026-09-09-cadical-conflict-family/`. A geometry module indexes exact G/M/R primitive memberships and produces lossless height rectangles. A CNF module encodes exact XY/height choices and rectangles. The selector retains original physical checks and uses these modules instead of flat candidate/cell-occupancy CNF.

**Tech Stack:** Existing Python 3.14 environment, python-sat/CaDiCaL195, existing Fraction geometry and work-budget contracts.

**Spec:** `docs/superpowers/specs/2026-09-09-cadical-conflict-family-design.md` and its linked geometry/SAT notes.

## Global constraints

Preserve original sources, specs, manifests and admissions. Preserve control30s/mall60s end-to-end gates; arcs100000, augmentations100000, candidates2000000, audit_cells5000000, predicates5000000, assignments100000; rounds2000, collision prohibitions20000, clauses20000000. Preserve CaDiCaL seed0, conflicts1000/decisions10000 per call. All new work inside original deadlines and charged; all original logical candidates charged. No profiling, tuning sweep, domain/geometry change, global router, fallback runtime, omitted checks, or rated acceptance claim. No permanent production tests; isolated proof witnesses and a throwaway discriminator only.

## Exact interfaces

- `family_geometry.Primitive(kind, lo, hi, endpoint_z)` is an immutable parametric closed segment. `kind` is G/M/R; lo/hi hold fixed XY bounds (and G z); R has actual fixed endpoint z. `at(height, budget)` returns the canonical `_Segment`.
- `PrimitiveIndex(domain, budget)` owns interned primitives, exact combo masks and reverse combo primitive IDs. `family(other, combo_i, combo_j, height_i, height_j, budget)` locates a canonical forbidden raw pair and returns `Family(left_mask, right_mask, rectangles)`; missing trigger is an invariant failure. `rectangles` contains disjoint `(left_lo,left_hi,right_lo,right_hi)` legal-height index ranges.
- `FactorCNF(domains, add_clause, budget)` allocates exact XY/height factors and thresholds; exposes `top_id`, `primary_variables`, `guard_count`, `rectangles`, `select(model)`, `exclude(di,ci)` and `forbid(i,j,family) -> int` newly emitted prohibitions. Original ID reconstruction is `combo*L+height_index`. CNF clause callback owns the unchanged global clause limit. FactorCNF owns normalized rectangle limit and deduplication. Constants simplify without optional truth values.

## Task 1: Isolate revision and establish rejecting witnesses

- [x] Copy only baseline Python sources, frozen inputs, and focused type config; no old policy/admission/results. Preserve known required capacity-first inputs if source references them.
- [x] Write isolated `family_witness.py` with explicit missing-module assertion, original canonical pair comparisons across ground/elevated endpoints, sparse heights, shared ownership and self-validity boundaries. Expected initial failure: approved family encoder not implemented.
- [x] Run that witness once and retain rejection evidence; do not rerun baseline mall.

## Task 2: Exact geometric conflict families

- [x] Implement `family_geometry.py` from `_adapter`/`_middle`: raw G/M/R descriptors, exact combo memberships and reverse provenance. No all-pair join.
- [x] Bind one left height; partition actual right levels at intersection/ownership critical constants with charged binary searches. Evaluate canonical closed intersections and `_owned` only for singleton intersections; merge identical row-run lists into rectangles.
- [x] Prove raw occupancy equality, exact masks, trigger inclusion, forbidden-pair soundness and whole pair coverage on deterministic small domains. Mutate upward-only risers and ownership to establish oracle sensitivity.

## Task 3: Exact SAT factors and selector integration

- [x] Implement `family_cnf.py`: reused two-product EO separately for XY and height, exact suffix thresholds and exact combo OR guards. Encode each normalized forbidden rectangle as the six-literal threshold clause, simplifying constants and deduplicating exact clauses.
- [x] Prove projection with solver assumptions over small original candidate domains and static/self exclusions. Preserve original logical candidate accounting.
- [x] Update `template_cadical.select` only at representation/refinement boundaries. Remove flat offsets, Cartesian model scan, dynamic occupancy literals and cell-keyed AMOs; retain static indexes, selected-cell/index checks, final Cartesian audit and unchanged return contract. Explicit stats distinguish logical candidates, primary selectors, auxiliary/guard variables, primitive occurrences, families and rectangles.
- [x] Update policy descriptors and existing affected witnesses/callers; LSP references before exported-symbol changes. No obsolete aliases.

## Task 4: Discriminator and original gates

- [x] Run one deterministic actual-mall pair discriminator with IDs chosen before costs: first self-valid candidate among 12 Random(19) samples per domain, first1000 unordered domain pairs. Compare canonical geometry, family membership/projection and point-versus-family CNF construction without a search run. Original numerical limits and a60s diagnostic deadline; no actual-gate state reuse.
- [x] Run focused Ruff/basedpyright and existing geometry/contract/audit witnesses once after integration; fix actual failures and keep evidence. New family oracle must reject deliberate semantic mutations.
- [x] Admit all original supported cases, freeze new policy, run original30s control. Only a full validator-complete witness opens the original60s mall. On mall success execute required cold repeats and eligible held-outs; otherwise preserve exact bounded outcome.
- [x] Update live report and existing experiment plan with actual commands/results. Verify all previous frozen identities and archive new revision with member hashes. No success claim from SAT alone or a compile-only discriminator.

## Plan review

The design's representation, primitive proof, ownership, rectangle normalization, progress, accounting, clean cutover and original-gate requirements are assigned above. The existing independent physical pipeline stays unchanged. New empirical failures are reported rather than rescued by relaxing budgets or checks.

## Execution outcome

Completed inline. LSP references failed with timeouts and a server cancellation
error; known callers were scoped directly and focused basedpyright passed.
Temporary module-existence red assertions were removed after the real proofs
passed. The frozen implementation contains no flat-candidate/occupancy aliases.

All15 retained verification commands pass. Proofs include7,500 primitive-height
comparisons,1,000 raw-normalized unions,1,550 canonical family comparisons and705
SAT projections; all four deliberate semantic mutations are rejected. The
1,000-pair actual-domain discriminator completes in1.199s within its original
limits. It is diagnostic only.

All five expanded admissions pass. Frozen rule:
`8376d2efb026c311a50377784a717b3ed8460d976d26bd2f46ad7e9f3c0d9049`.
Full control passes in12.034s/30s with all67 checks and zero errors.
Original mall ends POLICY_BOUND in4.547s/60s, during the first model check,
after656 families and15,744 rectangles. Retained predicates4,999,997;
the next charge would exceed5,000,000. No selected witness.

Actual prepared mall CNF is210,301 clauses and53,157 variables, including38,634
primary selectors. Original846,000 logical candidates remain charged.
Preparation takes3.902s and3,644,506 predicates; native solving takes0.008s.
Compression works, but the fixed-budget mall hypothesis fails for this revision.
No tuning, raised limits, omitted checks or promotion. Cold-success repeats
and held-outs are NOT_REACHED.

All20 frozen source/spec/manifest/admission identities verify intact.
Evidence: `docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-conflict-family/`.
The97-member ZIP, including the actual discriminator input, passes CRC and
all member SHA-256 checks. Archive SHA-256:
`cab123d13491c5a438c8a0b068d2166eecd7bc6382374508e5256a310e650637`.

## Approved compiler-ledger correction

Coarse phase accounting identified repeated generic binary-clause construction.
The isolated `2026-09-09-cadical-binary-clauses` revision avoids sets and sorting
for allocated integer binary literals, preserving canonical output and charging
four comparison/construction operations. No geometry or solver-policy changes.

The rejecting witness moves from42 to24 predicates for six exclusions.
The actual-domain proof preserves105,750 ordered clauses and53,298 variable IDs;
all36 duplicate/complement/order boundary pairs agree. Diagnostic preparation
saves554,763 predicates. The ledger is not an acceptance run.

All13 focused verification commands and five admissions pass. Frozen rule:
`96d58bda11daa232d53c209613a96dd883f389a5ece653a4e48635abf9005af2`.
Full original control passes in9.583s/30s, all67 checks, zero errors or skips.
Original mall remains POLICY_BOUND in4.422s/60s, now at the unchanged20,000
collision prohibition cap:833 families,234,728 clauses,4,766,907 predicates,
one native call/round and no selected witness. Both supervisors exit normally.
GEOMETRY_ONLY remains the acceptance scope; rated realization is unproved.

No tuning, budget raises, relaxed checks or promotion. Cold-success repeats
and held-outs remain NOT_REACHED. The correction exposes first-model cut volume;
it does not establish factory infeasibility.

All21 frozen identities verify intact. Evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-binary-clauses/`.
The100-member reproduction includes both ledgers and the actual proof input.
CRC and every member hash pass. Archive SHA-256:
`eda0e09180196e6f373e7ad2c5baaba8b5dacbe84a5dceb31171e5ae70b13dba`.

## Disjoint refinement continuation

The family census finds24 rectangles per family in the first834 events,738
equal-height diagonals. Rectangle hulls would remove legal unequal-height routes.
Instead, a canonical maximal vertex-disjoint family batch defers incident pairs
until a new model. Flags reset per round; deferral implies a real new cut;
the no-cut round and independent final Cartesian audit still check every pair.
No numerical limits, geometry semantics or domain changes.

The real saved-mall progress witness fails before the change at20,000 cuts;
afterward it requests its replacement model with67 families,1,608 prohibitions
and3,366,608 predicates. All14 focused checks and five admissions pass.
Frozen `2026-09-09-cadical-disjoint-refinement` rule:
`676297ef2ba608b799265b12e8a393d1f77d3a3fb58a1fd00be41f6a3b46c2b6`.

Full original control passes in9.117s/30s, all67 checks and zero errors/skips:
17 rounds,73 families,1,752 prohibitions,6,327 buildings and area38,784.
Original mall reaches eight rounds, then POLICY_BOUND at4.955s/60s:
5,000,000 predicates,413 families,9,889 prohibitions and227,614 clauses.
Both supervisors exit normally; no selected mall witness or global-router call.
GEOMETRY_ONLY remains the scope; rated realization is unproved.

Coarse diagnostic predicate ledger: preparation3,089,743; model decode736,168;
selected-path checks104,526; selected-pair checks152,238; family compilation917,325.
The ledger excludes emitter/settlement and is not an acceptance run.
First-round cut pressure is avoided, but aggregate compiler/checker work remains
over the original allowance. Cold-success repeats and held-outs are NOT_REACHED.

All22 frozen identities verify intact. Evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-disjoint-refinement/`.
The102-member reproduction passes CRC and every member hash. Archive SHA-256:
`106b8cee0fedb472797b021c3288eb0abafde5b211b17e385ca91041ca00f5b9`.

## Reusable primitive preparation continuation

Adapters/risers are constructed once per endpoint/adapter and interned lazily
in the original source/sink/shape traversal order. Their complete Cartesian
membership masks are merged once; ordered source/sink prefixes are reused
across shapes. Middle primitives and disjoint conflict scheduling are unchanged.
Mask operations, copies and scans remain charged; shared descriptors use the
wider mask operand for union cost.

The pre-change cost witness rejects1,250,388 versus1,250,388 predicates.
The replacement uses724,740, saving525,648 (42%). All141 actual mall domains
and four coincident/overlapping/elevated-port edge domains match exactly:
ordered descriptor IDs, full masks, per-candidate provenance and logical counts.
All15 focused verification commands and five admissions pass.
Frozen `2026-09-09-cadical-primitive-preparation` rule:
`f5ad6892e1a5cd65d40993302cd0e11a85e8f44fa6aee788fc73030179ed7aef`.

Full original control passes in9.487s/30s,67 checks, zero errors/skips,
6,327 buildings and area38,784. Original mall enters11 rounds/12 limited
native calls, then POLICY_BOUND at5.000s/60s:4,988,890 predicates before
the next charge would exceed5,000,000;527 completed families,12,579 prohibitions
and232,057 clauses. No selected mall witness. Supervisors exit normally.
No numerical limits, candidate domains, geometry or acceptance checks changed.

Diagnostic predicate ledger: preparation2,564,095; model decode920,528;
selected-path checks125,243; selected-pair checks219,129; family compilation
1,159,895. The ledger excludes emitter/settlement and is not acceptance.
More refinement headroom is demonstrated, not an end-to-end speedup.
GEOMETRY_ONLY remains the scope; rated realization is unproved.
No promotion; cold-success repeats and held-outs remain NOT_REACHED.

All23 frozen identities verify intact. Evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-primitive-preparation/`.
The102-member reproduction passes CRC and every member hash. Archive SHA-256:
`603167875620b27f048e51de142f6890768806daffb05d3d8041759edb74930c`.

## Joint family compilation and model decoding continuation

User approved both targets; independent agents edited geometry and decoding,
with Main owning integration and all validation. M/M relations use one planar
intersection and a sorted-height merge. Fixed rows/columns compile once;
other primitive cases retain generic critical-height partitioning.
Decoder uses one signed-model pass and charged compact group-boundary search,
without model-order assumptions, selector rescans or per-primary lookup tables.

Both old-code work regressions reject. New geometry preserves20,480 ordered
small relations,62,720 independent cell comparisons and all527 captured real
relations. Real relation work drops589,472 to254,158 predicates.
Decode proofs cover50 valid comparisons and30 rejections over ten native
models, permutations, duplicates and auxiliaries. The real141-domain model
and four variants preserve IDs; decode work drops420,324 to281,568 with282
added preparation predicates. All102,648 ordered initial clauses and variable
IDs remain identical. All18 verification commands and two final style checks pass.

All five admissions complete. Frozen `2026-09-09-cadical-family-decode` rule:
`026106b174fb30e13ecbd4e64295bd3adf43face89ba64ab8facf384704838ff`.
Full control passes in12.153s/30s,67 checks, zero errors/skips.
Original mall reaches15 rounds/16 limited native calls, then POLICY_BOUND in
5.807s/60s:5,000,000 predicates,682 families,16,253 prohibitions and238,179
clauses. No selected mall witness. Both supervisors exit normally.

Diagnostic predicates: preparation2,564,377; model decode851,836;
selected paths169,234; selected pairs352,572; family compilation1,061,981.
The ledger excludes emitter/settlement. More refinement is demonstrated,
not an end-to-end speedup or original-mall acceptance. GEOMETRY_ONLY remains
the scope; rated realization is unproved. No promotion or relaxed limits/checks.
Cold-success repeats and held-outs remain NOT_REACHED.

All24 frozen identities verify intact. Evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-family-decode/`.
The110-member reproduction passes CRC and every member hash. Archive SHA-256:
`867f1b6cd9a3a1bb94ef196c52c62c5377fdcb3ca455b171a635302f44e600a7`.

## Canonical family clause construction continuation

Explicit stage accounting identifies395,663 predicates in rectangle CNF,
334,018 in height relations and162,423 in guards. The next isolated correction
reuses guard ordering per family and assembles threshold literals in canonical
allocation order, removing repeated general set-building and sorting.
It preserves exact ordered clauses, duplicate keys, variables and quota accounting.

The old-code work witness rejects558,099 versus558,099 predicates. New assembly
uses438,225 for683 captured family calls, saving119,874. All130,527 ordered
clauses agree;1,080 guard/interval/allocation-order cases, duplicate insertion
and collision quota refusal pass. All19 integrated verification commands,
two final style checks and five admissions complete successfully.

Frozen `2026-09-09-cadical-canonical-cuts` rule:
`163208124d305a82650cd5c0ac9dc676af1c3f3cc2b725e80b5669c6c808419c`.
Full original control passes in9.549s/30s,67 checks, zero errors/skips.
Mall reaches16 rounds/17 limited native calls, then POLICY_BOUND in5.578s/60s:
5,000,000 predicates,708 families,16,854 prohibitions and239,240 clauses.
No selected mall witness. Supervisors exit normally; no global-router calls.

This buys one additional round. With only3,146 prohibitions below the fixed
20,000 cap, the next recommended investigation is refinement effectiveness,
not another unmeasured compiler tweak. GEOMETRY_ONLY remains the scope;
rated realization and factory infeasibility are unproved. No promotion or
relaxed budgets/checks; cold-success repeats and held-outs remain NOT_REACHED.

All25 frozen identities verify intact. Evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-canonical-cuts/`.
The113-member reproduction passes CRC and every member hash. Archive SHA-256:
`4dd487385729319972bc63d5c82d945d2f7acc09d31612b069e7692984ac1297`.

## Refinement-effectiveness investigation

User requested meaningful convergence improvement rather than additional
compiler micro-optimization. This is a completed diagnostic, not a new solver
implementation or acceptance run.

Complete graphs over16 saved models show1,673 initial conflicts (all141 paths
at height26), declining to107. The last transition removes58 and creates58.
All learned families are satisfied; every completed matching batch touches
every conflict edge. This does not imply edge-level fairness:79 final conflicting
pairs have never been directly learned; pair79/128 remains conflicting throughout
all16 models without selection. Failed exclusion is ruled out, starvation is not.

An exact fixed-XY greedy height counterfactual reduces initial conflicts to117,
but29 remaining pairs admit no compatible legal heights. Phase hints do not
adopt that proposal. Temporary first-round assumptions do adopt it; even with
proposal generation supplied for free, refinement still reaches the5,000,000
predicate cap after17 rounds. Warm-start-only is not supported as the solution.
An oldest-continuous-conflict-first scheduling probe also refuses:17 rounds,
17,265 cuts and129 conflicts in its last fully audited model. The solve stops at
4,968,861 predicates before the next charge exceeds the cap, even excluding graph
construction/sorting overhead. Thus a priority-only change is not supported either.

Joint geometric explanation is genuinely stronger in57 events across42 XY
pairs: opposite riser/middle constraints prohibit every height pair. Independent
cell expansion validates45 distinct two-relation proofs across25,920 height
pairs. Intersected primitive membership guards are mandatory; a joint full-height
exclusion is not globally equivalent to two broader individual families.

Recommended next architectural experiment: incumbent-preserving geometric
neighborhood refinement. Hold a compatible subset using temporary assumptions;
repair conflicting paths against retained geometry; release retained paths from
UNSAT cores and widen to the full original problem when needed. Never convert
restricted UNSAT into global infeasibility or temporary obstacles into unguarded
global exclusions. Measure joint explanations as a separate controlled addition.
Original full control/mall gates, budgets and validators remain authoritative.

Evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-refinement-effectiveness/`.
All39 frozen source-file hashes remain unchanged. The64-member archive passes
CRC/member hashes and the independent proof reruns from its restored contents.
No production change, accepted original mall, or eligible cold/held-out run.

## Approved geometric neighborhood implementation

User approved the structural experiment. Main owns inline implementation in
`2026-09-09-cadical-neighborhood`; every frozen predecessor stays untouched.

1. Add `neighborhood.py`: typed retained-path assumptions and best-conflict-count
   incumbent. `consider(selected, conflicts, factors)` updates only on strict
   improvement. A deterministic low-degree-first maximal compatible subset is
   retained; each held path fixes its XY and height literals temporarily.
2. `relax(core)` releases entire retained paths implicated by a native assumption
   core. Missing/empty cores conservatively release all. Every restricted-UNSAT
   retry strictly shrinks assumptions; only unrestricted UNSAT can reach the
   existing full-domain refusal. No global exclusion comes from temporary holds.
3. In `template_cadical.select`, compute the complete checked conflict graph
   before selecting the existing disjoint family batch. Preserve expanded/canonical
   pair agreement, full final audit, ownership rules and exact family exclusions.
   Use retained assumptions for native calls; keep original native-call settings.
   Charge graph, sorting, masks, assumption arrays, core lookup and release work.
4. Prove compatibility, actual retained-model stability, restricted UNSAT recovery,
   full release and conditional exclusions using real CaDiCaL models. Run existing
   geometry/ownership/representation proofs and focused type/style checks. Freeze
   only after proof; execute original30s control then original60s mall.
5. Create a separate descendant for joint explanations. Exact opposite
   riser/middle relations may add a full-height exclusion ONLY under intersected
   primitive guards and a proof that their union covers every original legal
   height pair. Keep broader original family clauses; this is an additional sound
   exclusion, not equivalent replacement. Measure the addition separately.

No reduced domains, raised budgets, reset deadlines, uncharged preparation,
relaxed validators or production promotion. Reproduce any rejected outcome,
preserve both arms and update the live report. Cold repeats and held-outs remain
conditional on original mall acceptance.

### Executed result: both arms NO_GO

Implemented all five approved steps in isolated, separately frozen revisions.
No production selector was changed.

| Arm | Original control /30s | Original mall /60s | Last complete mall conflicts |
| --- | --- | --- | --- |
| Canonical baseline | VALIDATOR_COMPLETE_WITNESS,9.549s | POLICY_BOUND,5.578s | 107 |
| Neighborhood | VALIDATOR_COMPLETE_WITNESS,10.445s | POLICY_BOUND,5.820s | 81 |
| Neighborhood + joint | VALIDATOR_COMPLETE_WITNESS,10.809s | POLICY_BOUND,6.209s | 136 |

Both new controls pass all67 checks with zero errors/skips. Both new malls reach
the unchanged5,000,000-predicate cap, not a witness or global UNSAT. Neighborhood
uses14 rounds/15 native calls/13,446 cuts; joint uses13/14/13,409 and emits36 joint
exclusions. Each mall exercises one real core recovery, releasing one retained
path. All four supervisors exit normally without hard-deadline termination or
global-router calls. Geometry-only control completion is not rated acceptance.

Verification:19 neighborhood commands and20 joint commands pass, including focused
basedpyright and existing geometry/ownership/representation proofs. New native
proofs cover64 conflict graphs, compatible retention, restricted UNSAT recovery,
full release and genuine unrestricted UNSAT. Joint explanations pass45 actual
proofs/25,920 canonical height pairs plus54 boundary pairs. Final read-only Ruff
checks pass. LSP references remain unavailable after reload; focused CLI typing
provides the type-check evidence instead.

Neighborhood-only improves the residual conflict diagnostic, not the gate.
Joint explanations reduce control rounds38→24 but worsen the mall residual to136.
Neither arm qualifies for promotion; cold-success repeats and held-outs remain
NOT_REACHED. No budgets, legal domains, ownership rules or acceptance checks were
relaxed. No function-level profiling was introduced.

Evidence: `docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-neighborhood/`.
The264-member reproduction includes both frozen implementations, admissions,
gate records, proof results and captured inputs. CRC/member hashes and restored
new proofs pass; both restored rule/source/manifest identities pass. All27 frozen
source/spec/manifest/admission identities remain intact. Archive SHA-256:
`abca3a32ac1fdf977d573b7d6245266de1efa7eed311d8e9cb971774c4dc112d`.
Temporary extraction removed; live report updated at `~/report4.md`.

## Approved geometry-complete local repair diagnostic

User approved the bounded diagnostic, not production integration. Main runs it
inline in `2026-09-10-cadical-local-repair`, using unchanged neighborhood-only
source copies. Capture the strictly best incumbent and its retained paths from
the saved actual mall problem; verify the whole graph independently.

Compile exact free/retained constraints using temporary activation literals and
original primitive membership/height relations, then all free/free constraints.
Use conservative primitive envelopes to reject nonintersections before relation
construction. Compile unary self/static legality before any SAT call. SAT is
eligible only after every stage completes; independently audit its whole assembled
selection. Restricted UNSAT releases whole retained paths named by the assumption
core, then rebuilds with those paths' full original domains. Missing cores release
all; only the fully unrestricted complete problem can establish domain UNSAT.

The local diagnostic receives at most one60s/5,000,000-predicate allowance, shared
across construction, solving, auditing and every widening rebuild. Original
20,000 collision-prohibition, clause and native-call settings remain unchanged.
Capture cost is recorded separately: granting this local allowance after capture
is an explicitly optimistic diagnostic, NOT an integrated original-budget run.
Construction refusal is a valid negative result for this compiler, not proof that
the neighborhood or factory is infeasible. No reduced domains or joint addition.

### Executed diagnostic: construction cap before SAT

Capture reproduces13 improving incumbents; the best has141 paths,116 retained
and81 conflicts. Independent canonical graph, self/static and retained-pair
checks agree. The full-domain local compiler is implemented, including guarded
retained boundaries, free/free relations, unary legality, core-driven rebuilds
and final whole-selection audit.

600 boundary and20,000 mutual candidate projections pass against canonical
geometry, including shared ownership and inactive-boundary safety. A real
geometric obstruction exercises restricted UNSAT, releases its held path, rebuilds
the full domains and returns a valid repair. Global static UNSAT remains UNSAT.

The actual mall diagnostic ends POLICY_BOUND after3.440s:

| Measurement | Result |
| --- | ---: |
| Completed free-path boundary domains | 7/25 |
| Collision prohibitions | 20,000 |
| Clauses | 45,529 |
| Predicates | 4,656,119 |
| Exact boundary relations attempted | 21,469 |
| Broad-phase probes | 567,081 |
| Native SAT calls | 0 |
| Retained paths released | 0 |

The refusal occurs in the eighth free path's retained-boundary compilation.
Free/free and unary completion, native solving and widening are NOT_REACHED for
the actual mall. Domain/retained audit uses345,479 predicates; factor/primitive
preparation brings the total to715,535. This optimistic diagnostic excludes
capture cost; it cannot be reported as an original-budget solve.

Decision: NO_GO for this eager expansion strategy. Neighborhood feasibility is
still unknown; compact or statically simplified encodings are not ruled out.
No integrated original-gate run or production change follows from this result.

Five verification commands and final Ruff checks pass; focused basedpyright is
clean. All27 frozen source/spec/manifest/admission identities remain intact.
Evidence: `docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-local-repair/`.
The100-member archive passes CRC/member hashes. Restored capture/native proofs
pass and the restored refusal matches every work counter and stage, in3.355s.
SHA-256: `3a2b643befdb1d914bd75c0fcb815b81df8129e1e448f905a84464597a7b278e`.
Temporary extraction removed; `~/report4.md` updated.

## Approved compact retained-boundary diagnostic

User approved a bounded representation spike in
`2026-09-10-cadical-compact-local-repair`. Reuse the verified141-path capture;
preserve the eager compiler and every frozen predecessor unchanged.

1. Apply existing exact entry/middle static exclusions before retained-boundary
   emission. Keep original XY/height factors and exclude only proved-illegal
   candidates. Convert exclusions into per-height legal-XY masks.
2. Union primitive collision intervals per retained path before emitting CNF.
   Use transposed height/XY masks to accumulate the same forbidden candidate set
   without a clause per primitive explanation.
3. Partition XY choices by their identical forbidden-height sets; emit merged
   height intervals under one shared XY guard per group. Preserve each retained
   path's own activation literal and existing assumption-core widening.
4. Charge mask construction, transposition, intersections, unions, grouping and
   output by performed work, including bigint widths. Do not relabel raw work
   as one operation or change numeric limits. Keep free/free, remaining unary,
   native solve, widening rebuilds and final audit in the same local allowance.

Prove set equivalence, static filtering, exact CNF projection, independent retained
activations and deactivation safety. Run the entire local repair after proof.
Fewer clauses alone cannot qualify this diagnostic for integration. Capture cost
remains explicitly excluded from the optimistic local-only diagnostic; original
control/mall integration requires a complete independently valid local repair.

### Executed compact diagnostic: predicate cap before SAT

Implemented all four approved changes. Six verification commands pass, including
64 set-equivalence cases, 800 static/independent-activation projections, the existing
600 boundary/20,000 mutual projections, and actual geometric core-driven release
followed by an independently valid repair. The initial independent-case proof
budget ownership error is preserved; no actual diagnostic allowance was raised
or reset. Final Ruff/focused basedpyright checks pass.

| Measurement | Eager local | Compact local |
| --- | ---: | ---: |
| Terminal allowance | 20,000 prohibitions | 5,000,000 predicates |
| Elapsed diagnostic seconds | 3.440 | 2.637 |
| Completed static domains | Not reached | 25/25 |
| Static candidate exclusions | Not reached | 17,613 |
| Completed boundary domains | 7/25 | 4/25 |
| Emitted boundary prohibitions | 20,000 | 245 |
| Total clauses | 45,529 | 47,260 |
| Native calls | 0 | 0 |

The compact run refuses in retained-boundary construction. Its phase totals are
345,479 predicates after retained/domain audit, 716,235 after factors/primitives,
2,324,253 after exact static filtering/legal masks, and 5,000,000 at refusal.
All later stages remain NOT_REACHED for the actual mall. The table compares
different incomplete prefixes; it is not a full-problem compression ratio or
end-to-end speedup.

Decision: NO_GO for integration. The run stops on predicate work rather than
cut count, without reaching a complete local repair. Neighborhood
feasibility is still unknown. No production changes, raised limits, joint
explanations, original gate reruns, cold-success repeats or held-outs.

All 27 frozen identities and the eager diagnostic's source hashes remain intact.
Evidence: `docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-compact-local-repair/`.
The 104-member archive passes CRC/member hashes. Restored proofs and capture
audit pass; every refusal work counter and stage reproduces exactly, in 2.340s.
SHA-256: `b71f14dc7e703ea7959cb020491bff4a5b3265b1054f7c1ad420ab8f8b9c36c8`.
Temporary extraction removed; live report updated at `~/report4.md`.

## Authorized one-run wall-budget diagnostic

The user approved the two-agent recommendation: stop compiler changes and run
the unchanged frozen neighborhood-only selector once with an explicit numerical
policy exception. This is not an original-policy gate rerun or an algorithm
promotion. The historical 180-second witness was the 26-domain control, not the
141-domain full mall.

Predeclared before execution: 100,000,000 predicates, 200,000 collision
prohibitions, 4 GiB sampled child-process RSS cutoff (20ms polling), and the
original 60 seconds from layout/capture through complete settlement. The external
supervisor permits the original 30-second bootstrap, then adopts the child's
fixed deadline once. Its exclusive launch record prevents implicit retries.
The 20,000,000-clause cap and every other work limit remain unchanged.

Use the captured topology only, CaDiCaL's unchanged seed/settings, frozen
specification/domains/ownership/geometry, and all 41 baseline Python modules
byte-identically. No free incumbent, second topology, retry, threshold sweep,
new search algorithm or automatic limit escalation is authorized.
Source: `.superpowers/sdd/2026-09-10-cadical-wall-budget/`.

Before the single mall run: verify the original source/policy/admission/control
identities, exercise the supervisor with synthetic children, run focused wrapper
format/lint/type checks, and freeze the wrapper/policy hashes. Afterwards preserve
the terminal result, last solver checkpoint, resource measurements and source
archive. Archive restoration must not rerun the mall. A completed geometry
witness would remain diagnostic only: neither original-work-policy acceptance
nor rated-factory acceptance. A deadline/resource refusal remains UNKNOWN
feasibility, not UNSAT.

### Executed wall-budget diagnostic: geometry selected, ownership refused

The single authorized full-mall run terminates in31.983s/60s with
`EMISSION_OR_AUDIT_FAILURE`. The selector completes141 paths with zero remaining
pair conflicts after137 rounds/139 native calls,30,466 collision prohibitions,
254,821 clauses and two assumption-core relaxations. Aggregate preparation
is3.156s; native solving is0.440s. Final work uses17,571,623 predicates,
865,317 candidates and1,781,637 audit cells. No declared work cap is reached.

The emitted audit reports exactly four endpoint-ownership failures: belts14306,
14331,14798 and14823 each have two feeders without an explicit junction.
It records97,241 buildings,91,674 belt links,489,289 expanded cells and39
mechanical probes. These are not the full67-check validator. The first emitted
audit refuses before rate assessment, final projection, projected audit, full
validation, codec round-trip and decoded audit. No complete mall witness exists.

The external supervisor exits normally in37.833s including bootstrap, with peak
sampled RSS581,079,040 bytes and no hard-deadline or RSS termination. An initial
outer launch snippet fails to parse before any process starts. The corrected
launcher starts exactly once; an MCP30-second RPC timeout does not trigger a
relaunch, and the same process writes durable successful-exit records.

Decision: stop this diagnostic here. The existing selector converges on modeled
geometry under the wall deadline, but the emitted result is invalid. The next
investigation should trace the four actual feeder relationships to distinguish
endpoint-model constraints from junction-emission behavior; no root cause or
fix is claimed. No compiler pivot, cap sweep, repeat, held-out or promotion
was performed. This remains an explicit work-policy exception, not official
original-policy acceptance or rated-factory evidence.

All41 baseline source files and all27 frozen source/spec/manifest/admission
identities remain intact. Wrapper Ruff/type checks and synthetic supervisor
cutoff/one-shot proofs pass. Evidence is preserved in
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-wall-budget/`.
The178-member archive passes CRC/every member hash. Restored preflight and
supervisor proofs pass; the mall is deliberately not rerun during restoration.
Archive SHA-256:
`3011748376cf296888f6b3a1fdbc85b05416895014b06af12c865aa163016d17`.
Temporary extraction removed; report updated at `~/report4.md`.

## Authorized endpoint diagnosis: fixed flank drains, not SAT

The user approved tracing the four actual feeder relationships. The isolated
investigation in `.superpowers/sdd/2026-09-10-cadical-endpoint-trace/` reconstructs
emission from the saved141 paths without native solving. It verifies matching
endpoints and reproduces the original topology, emitted links and four findings
in25.573s. This replay is not a second numerical-policy mall solve or acceptance
gate. No function-level profile is collected.

All four pairs already exist before fixed/global flight emission and remain
unchanged through slot binding:

| Strip | Manufactured item | Rejected belt | Feeders | Unused prefix |
| --- | --- | ---: | --- | --- |
| 38 | Miniature Particle Collider | 14306 | 14305,14314 | 14302–14305 |
| 39 | Miniature Particle Collider | 14331 | 14330,14339 | 14327–14330 |
| 45 | Ray Receiver | 14798 | 14797,14806 | 14794–14797 |
| 46 | Ray Receiver | 14823 | 14822,14831 | 14819–14822 |

Direct instrumentation during inventory capture proves `_flank_lane` creates
exactly these four merges. The other52 strips do not. `_emit_strip` creates a
full-width drain at `routing_domain.py:3462-3493`; `_flank_lane` links its east
product column into that drain at3740-3742. Its documented native-belt merge
semantics differ from the experimental audit's universal multi-feeder refusal
at `template_audit.py:239-243`. SAT receives these strips as fixed geometry and
does not control their internal predecessor graph.

Each affected strip has one machine. The horizontal feeder has four belt-only
ancestors, all inside the same strip, with no producer/sorter input or declared
endpoint. A diagnostic counterfactual removes only those16 unused records and
remaps every surviving reference. The unchanged emitted audit then passes with
zero findings:97,225 buildings,91,658 belt links,489,225 expanded cells and39
mechanical probes. The separate-coincident-vertex negative fixture still refuses.
Full validation, projection, codec and rate realization are not run.

Diagnosis complete; no source fix or promotion. Recommended next source change:
start the strip's output drain at its first productive ingress, consistently in
geometry and emission. Do not special-case these IDs or waive native merges in
the audit. Removing a dead prefix does not resolve genuine live merges in
multi-machine strips; those require separate contract analysis.

Final Ruff/focused basedpyright pass. All41 copied algorithm files, prior
diagnostic hashes,117 recorded production-source files and all27 frozen
identities remain unchanged. Two recorder serialization failures are preserved;
the corrected replay and causal proof exit0. Evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-endpoint-trace/`.
The95-member archive passes CRC/member hashes. Restored causal/counterfactual
proof reproduces the complete result exactly with no SAT or full replay.
SHA-256:`c33d8aecf5eae7a82e2da01e119092763e558ee1136433c429d04c471673b068`.
Temporary extraction removed; `~/report4.md` updated.

## Authorized continuation through factory settlement

The user authorized continuing until the full factory works. Subsequent
revisions retain the separately labeled100m-predicate/200k-cut diagnostic
allowance, original30s/60s deadlines,100,000 arcs,4GiB sampled RSS and all
acceptance checks. Frozen prior revisions are not overwritten.

- Production `Strip.output_lane_start` and `_emit_strip` omit the unused
  flanked drain prefix generally. A permanent one-/three-machine regression
  fails before and passes after the fix, preserving every producer-to-port path.
- `2026-09-10-cadical-productive-drain`: control completes in9.835s; mall
  passes emitted audit but refuses at100,000 arcs in37.640s.
- `2026-09-10-cadical-capacity-runs`: exact series-belt contraction preserves
  minimum capacities, sorter/junction boundaries and all belt provenance.
  Reference/cut fixtures pass; mall uses20,105 arcs, then fails1550x186 extent.
- `2026-09-10-cadical-west-boundary`: imports move beside the banks without
  reducing clearance. Mall routes and passes emitted audit in54.232s but
  its1555x120 extent exceeds the1000-column planet circumference.
- `2026-09-10-cadical-band-packing`: width-ordered first-fit shelves retain
  strip/access/bank clearances. Fixed geometry fits881x139. Control completes
  in7.896s; mall selects141 conflict-free paths after87 rounds, then the
  supervisor terminates at60s without a final report: UNKNOWN.
- `2026-09-10-cadical-settlement-trace`: saved-ID replay identifies24.956s
  in capacity assessment. Projection and projected audit pass; full validation
  reaches the diagnostic deadline. This excludes original solving cost.
- `2026-09-10-cadical-blocking-flow`: exact integer blocking flow replaces
  repeated BFS.64 random value/cut/conservation comparisons pass; a1500-branch
  witness reduces search checks5,663,250→49,502. Existing physical resource
  fixtures and focused Ruff/basedpyright pass.

Latest full control completes all67 checks and codec in7.521s. Latest mall
reaches all67 checks in56.014s,0skips, with emitted/projected audits passing
and final897x139 extent. Three `flow.belt_capacity` errors remain, for iron
ingot, magnet and magnetic coil. No codec/decoded mall witness or promotion.

The user suggested a much easier routing problem if routing remains blocked.
Routing now completes; a10-record flow-only counterexample instead isolates
the capacity verdict. Feasible18+6→24 flow is rejected because the equal-share
estimate charges12/s to the6/s branch. This proves the validator estimate is
unsound, not that all three mall findings are false positives.

**Approval boundary:** the user asked how the validator would be repaired.
The proposed design uses shared directed physical-flow feasibility with
simultaneous capacities, producer pools, item identity and real overload
negatives; estimates are not acceptance bounds. Validator source remains
unchanged pending approval. No clamping, severity downgrade or omitted check
is authorized or implemented.

Verification limits:6 focused strip-variant tests pass. Broader selection:
22pass/1failure in an untouched freeform routing-budget test. Focused
production typing reports three possibly-unbound variables in untouched
sections; changed experimental files type-check cleanly. A whole-file test
invocation has no terminal result record and is not counted as passing.

Checkpoint evidence:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-settlement-progress/`.
The911-member archive passes CRC and every member SHA-256. All five gate
source manifests match;116 of117 previously recorded production source files
remain unchanged, with only the intended drain fix differing. Restored
blocking-flow and resource-capacity proofs, the minimal validator counterexample
and both productive-drain regressions pass. No real gate rerun during restoration.
SHA-256:`57e53c79aea8b7b07be0ff7fe01ab5258e89a12d224401892d9801316b10299c`.
Temporary extraction removed; `~/report4.md` updated. The validator-design
decision recorded at this historical checkpoint was subsequently approved.

## Approved shared capacity model and native solver comparison

The user approved correcting the validator and requested consideration of
LP or SAT rather than rebuilding a general solver behind `_lane_balance`.
The comparison now uses Z3 exact rational linear arithmetic and existing
OR-Tools GLOP. PySAT is not treated as a native rational-arithmetic solver.
Z3 fresh construction and incremental `push`/`pop` queries are both measured.
No new handwritten simplex or general-purpose constraint solver is planned.

### Shared model contract

One immutable, typed physical model owns flow variables, sparse conservation
equalities, supply/demand bounds and shared resource inequalities. Rates remain
`Fraction`; item identity is part of every transport variable. Machine
input/output pools remain distinct. Each producer pool is shared across its
attachments; consumers and declared exports retain their required rates.
Mixed cargo shares one physical belt capacity, rather than getting a full
allowance per item. Real roots/tails alone are boundary connections.

Compaction may eliminate only uninterrupted, unattached series-belt segments,
retaining their minimum capacity and all physical IDs. Sorter pickup/injection
order, junctions, piler boundaries and item identities remain explicit.
Existing partial-spec capacity fixtures remain capacity-only diagnostics;
undeclared import rates cannot become a claim of frozen external supply.

`validate.py` builds/caches this model per `Context`; a small dedicated module
owns native-solver encoding/results, not a second geometry interpreter.
Separate conservation, belt-capacity and sorter-capacity queries enable their
respective constraint groups on the same structural model. A joint query
checks simultaneous resource feasibility. Exact infeasibility certificates
name implicated resources; unknown/timeout is not accepted as either feasible
or impossible. Returned flows are checked against the rational constraints.
Estimated headroom must not serve as an acceptance bound.

### Execution and verification

- [x] Add the asymmetric18+6→24 pass case and the genuine17+7→24
  six-capacity branch failure. Keep shared-trunk, mixed-cargo, producer-pool,
  backpressure and pickup-before-injection regression contracts.
- [x] Freeze one common sparse linear model and compare exact existing
  single-item flow, Z3 rational satisfaction/model extraction, and GLOP on
  identical fixtures plus the captured real mall network. Include construction,
  solve, extraction/certificate cost, cold cost and incremental query cost.
- [x] Select the simplest measured backend satisfying correctness/deadline
  requirements; add a production dependency only if selected. Z3 is currently
  isolated under `.superpowers/sdd/2026-09-10-physical-flow/deps`.
- [x] Integrate through the shared validator model, migrate acceptance
  consumers, and preserve all67 registered checks. No estimate clamping,
  error downgrade, missed mixed-resource coupling or rate-realization claim.
- [x] Run affected regression tests and the complete original-deadline control
  and mall diagnostics. Continue to projection, codec and decoded audit.
  Preserve backend comparisons, actual failures and final source identities.

The first permanent regression is meaningful red: the valid six-capacity
branch is charged12/s and rejected; the genuine seven-on-six negative passes.

Initial comparison selects existing GLOP: fresh-model construction, first
solve and exact flow extraction take 0.374s on the captured mall, versus
7.980s for Z3. The complete three-query SAT/UNSAT/restored-SAT sequence takes
0.698s versus 15.453s. Process startup and common graph extraction are excluded
from these figures. The user notes that faster LP backends should be tried
before rejecting LP, or for further optimization if the end-to-end gate needs
it; no other backend is being tested up front.

The production solve uses exact primal verification and an independently
computed weak-duality bound for refusal, not native floating-point status.
360 randomized projected/shared-resource comparisons agree with exact Z3:
157 feasible, 203 infeasible. The saved mall's four flow checks pass in 3.155s.
78 focused flow regressions pass. The complete validator/solver test selection
passes 418 and has two coater failures reproduced against the archived
pre-change validator. Focused production Ruff/basedpyright pass.

The final `2026-09-10-integer-audit-grid` gates complete under the retained
diagnostic work policy and unchanged deadlines:

| Case | Elapsed / deadline | Buildings | Validation |
| --- | --- | ---: | --- |
| Three-output control | 6.352s / 30s | 7,850 | 67 checks, zero errors, none skipped |
| Unsprayed mall | 57.997s / 60s | 60,489 | 67 checks, zero errors, none skipped |

Both pass emitted, projected and decoded audits and write codec artifacts.
The mall frame is 897×139. Both remain `VALIDATOR_COMPLETE_WITNESS`, with
`RATE_REALIZATION_UNPROVED` and `official_acceptance=false`: no promotion to
the original-work policy and no in-game startup/throughput proof.

Completion required correcting a real encoder boundary: `atan2` returns
principal longitude, but a wide blueprint uses an unwrapped chart.
`blueprint_port_anchor` now restores the host's chart before outward-offset
scoring. A codec round-trip regression fails before this fix; all 16 splitter
port tests pass afterward. The decoded audit likewise preserves continuous
longitude without rounding away physical port offsets.

Audit speedups retain the same checks and work accounting. Conservative AABBs
match 1,360 findings over 200 comparisons; exact integer-grid interpolation
matches 1,034 probe sequences and 966 refusals. Complete saved-mall geometry
reports and work counts match the frozen reference. No function-level profile
or deadline increase was used.

The expanded bounded regression selection passes 463 tests and reproduces the
two existing coater failures. A broader selection including the full pipeline
suite reached its 150-second timeout; it is not a successful suite run.

Final evidence directory:
`docs/superpowers/evidence/2026-09-06-feasibility-first/cadical-physical-flow/`.
All earlier failed/deadline revisions remain preserved separately from the
final witness.

Final combined verification after the codec correction: 493 passed and the
same two baseline coater failures in 40.23s. The selection also includes
splitter-port and splitter-route-primitive regressions. Focused Ruff and
basedpyright pass; no project-wide clean-suite claim is made.

The reproduction archive is restored and verified: all 1,068 member hashes
match; seven restored-source/runtime proof commands pass. This includes 20
focused regressions, 2,000 exact-grid comparisons, 200 decoded-geometry
comparisons, the 360-case exact Z3 oracle, both expected baseline coater
failures, and a passing saved-mall decoded audit. Temporary restoration was
removed. This is not a fresh full-factory or clean-environment-install gate.

At the user's request, only `layout/validate.py`, `layout/physical_flow.py`
and their two regression files were committed to master as `27483797`.
Routing, codec, experimental audits and all docs/evidence remain outside
that commit. Master-source validation: 427 passing validator/flow/belt-tier
tests with the same two baseline coater failures; 360/360 oracle agreement;
Ruff passes; direct basedpyright has zero errors and 221 warnings.
Supplemental commit/verification records are preserved alongside the frozen
archive. No push or promotion of the experimental factory strategy occurred.
