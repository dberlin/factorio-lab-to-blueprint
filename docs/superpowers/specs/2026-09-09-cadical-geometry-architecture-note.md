# CaDiCaL geometry architecture: exact primitive conflict families

Date: 2026-09-09. Status: design only; no implementation or new experiment result.

This note owns geometry and soundness. The companion SAT note is `2026-09-09-cadical-sat-architecture-note.md`. The two authors exchanged proposals and substantive critiques while working concurrently; the agreed interface appears below. Main owns integration. No frozen source, specification, manifest, admission, physical interface, production code, or existing evidence was changed. Only this note was written. No solver, profiler, formatter, linter, build, test, dependency installation, or VCS operation was run. Calculations below only read existing JSON artifacts.

## 1. Diagnosis and evidence boundary

Abbreviations used for source citations:

- **P**: `.superpowers/sdd/2026-09-09-cadical-path-envelope/`.
- **H**: `.superpowers/sdd/2026-09-09-cadical-height-order/`.
- **E**: `docs/superpowers/evidence/2026-09-06-feasibility-first/`.

The authoritative history is `~/report4.md`, especially lines 92–101, and `docs/superpowers/plans/2026-09-08-constructive-composition.md:1320–1529`.

| Existing result | Observation; not a new run |
| --- | --- |
| Path-envelope control | Validator-complete geometry witness in 11.424 s / 30 s. |
| Path-envelope original mall | POLICY_BOUND in 36.984 s / 60 s; 46 rounds, 8,776 collision cuts, zero lazy static cuts, 5,000,000 predicates. |
| Height-order control | 11.030 s / 30 s, 67 registered checks, zero errors. |
| Height-order original mall | POLICY_BOUND in 39.886 s / 60 s; 44 rounds, 8,552 collision cuts, zero lazy static cuts, 5,000,000 predicates. |
| Plane-index oracle | Regressed 6,764 to 12,609 predicates; rejected before another mall run. |
| Mask-intern mall | Reached 82 rounds but remained UNKNOWN at its deadline. |

`P/template-cases/unsprayed-mall/result.json` and its `attempts[0].solver` report 846,000 candidate variables, 45,705 occupancy variables, 177,801 auxiliary variables, 6,223,699 clauses, 107,653 static exclusions, 96,000 entry exclusions, one self rejection, and an empty `selected_candidate_ids`. Final work is 852,486 candidates, 2,845,903 audit cells, 5,000,000 predicates, and 46 assignments. `captured/solver-progress.json` is an earlier checkpoint, not the authoritative final work count; its preparation is 4.073 s. This timer starts with `TemplateRun.solve_stats` creation before `run()` (`template_runtime.py:32–41`; `template_experiment.py:225–230`), so preparation includes preselection construction/capture, not just CNF compilation. Completed native solving is about 8.268 s. These aggregates do **not** locate predicate expenditure or runtime in a particular function. No function-level attribution is claimed.

The structural problem is visible in source without a profile: `P/template_cadical.py:495–513,604–663` translates a newly observed collision cell into exact candidate-occupancy masks and implications from each mask member, then repeats selected-model refinement. This is already stronger than a single candidate-pair nogood, and mask interning already eliminates identical occupancy propositions. Height-order reuses compatibility answers, but still discovers concrete collision cells and emits cell-based constraints. Neither a new cache nor a different spatial index changes that learning unit.

**Architectural hypothesis [INFERENCE]:** choose XY shape and height as separate exact coordinates of the original domain, and teach CaDiCaL a complete forbidden relation between two reusable geometric primitives when their collision is first encountered. This can express all equal-height, height-precedence, or unconditional collisions for that primitive pair without rediscovering each cell/height combination or introducing implications from thousands of Cartesian candidate literals. The original mall may then finish selection and all settlement checks within its unchanged gate. Existing artifacts do not establish that this hypothesis succeeds.

Repeated bounded failures are not infeasibility proofs. There is no original-mall witness, no cold-success repeat, and no reached held-out gate. Control is GEOMETRY_ONLY, not rated factory acceptance.

## 2. What the retained actual mall establishes

A read-only calculation over `P/template-cases/unsprayed-mall/captured/flights.json` found:

- 196 flight records: 36 `local-source`, 19 `local-sink`, 112 `internal`, 20 `external`, and nine `output`.
- Excluding the 55 local transfers leaves 141 global obligations. All 141 saved global source/sink height pairs are `(0, 0)`.
- There are 64 coincident global endpoint positions, with maximum multiplicity three. Examples include `(34,44,0)` for flight IDs 56/57 and `(301,37,0)` for 62/143. Coincidence does **not** establish physical ownership.
- `captured/links.json` contains 110 fixed links and 1,097 distinct recorded fixed-link cells. Recorded cell-occurrence heights are `{0:619, 1:308, 2:105, 3:60, 4:13}`. These are the saved links, not a substituted complete body-reservation capture.

The result records 24 available heights. `template_runtime.py:193–208` supplies the original integer levels beginning at three. `template_paths.py:289–354` gives at most ten middle shapes and 25 adapter pairs, hence at most 250 XY combinations. The 846,000 total candidates saturate `141 × 250 × 24`; thus this actual mall has 250 combinations and 6,000 candidates per domain. Factored XY/height primary selectors would number `141 × (250 + 24) = 38,634`, while the admitted logical candidate count remains **846,000**.

An eager pair table is prohibited by scale:

- 9,870 domain pairs.
- `9,870 × 250² = 616,875,000` XY-combination pairs before heights.
- `9,870 × 6,000² = 355,320,000,000` complete candidate pairs.

The saved flight points and topology do not serialize all compiler-verified `Endpoint` identities, junction incidence, body reservations, tracks, and ownership exceptions of a complete `TemplateProblem`. They must not be used to invent those records. A later implementation obtains them through the unchanged real emitter and `TemplateConstructor.endpoint`, `_owns_blocked_endpoint`, and `finish`; no ownership is reconstructed from coordinates. This analysis cannot determine the complete primitive dictionary size, conflict-frequency distribution, family-reuse rate, propagation behavior, runtime, or mall feasibility from these files alone.

## 3. Preserve the exact candidate identity and geometry

The external identity is:

`(obligation_ordinal, combo, height_index)` with `candidate_id = combo * len(domain.levels) + height_index`.

Use the actual `Domain.obligation.ordinal`, not an assumption that IDs are consecutive topology-demand indices. Retain the original sorted `domain.levels`, shape sequence, all five adapters at both ends, and all original combinations, even when two happen to draw identical geometry. `Domain._ids` ordering and `Domain._decode` remain the authority for ordering and reconstruction (`P/template_paths.py:239–286`). Representation is not candidate pruning.

Reuse `_adapter` and `_middle`; do not introduce a second geometric recipe. For each combo, represent the consecutive raw template segments, before `_normal`, using only:

1. **G — fixed adapter segment:** a closed XY axis interval at the actual endpoint height. An adapter has one or two such segments.
2. **R — riser:** a fixed XY column with closed z interval `[min(endpoint_z,h), max(endpoint_z,h)]`.
3. **M — moving middle segment:** a closed XY axis interval at selected height `h`. A middle has at most three segments.

There are at most `2 + 2 + 2 + 3 = 9` primitive occurrences per combo. A zero-length riser or middle is a point primitive; it is not silently discarded if needed to preserve the union. The bound for the actual mall is 317,250 primitive occurrences before interning, not 846,000 decoded paths. This is a size bound, not measured memory consumption or a claim that a Python representation is cheap.

Intern only **identical complete parametric descriptors within one domain**. Each descriptor carries an exact combo bitset: precisely those original combos whose raw segment list contains it. Adapter membership can be generated directly from the existing combo decomposition. A middle descriptor includes its complete axis, fixed coordinate, and interval endpoints; an R includes both XY and endpoint z. Never replace several different segments by their bounding interval or by a union whose coverage depends on the chosen combo.

Build membership in one bounded traversal of the original generators, with a reverse combo-to-descriptor list. Do not join all domain pairs or all primitive pairs up front. Existing static compilation/index construction remains part of preparation; building this representation is not a justification for moving work outside the gate.

### Why raw primitives survive normalization

`_normal` removes consecutive duplicates and merges only monotone continuations; it explicitly never erases reversals/retraces (`P/template_paths.py:91–109`). The union of raw closed segments equals the normalized path's occupancy. Each raw segment is contained in a normalized segment. A forbidden raw primitive overlap therefore witnesses a forbidden normalized overlap. Conversely, any positive-length overlap of normalized segments has a positive-length overlap in some pair of raw pieces, and a singleton overlap belongs to some raw pair. No raw-piece exception may allow positive-length sharing.

This argument concerns **cross-path occupancy**, not self-validity. `_path_error` uses normalized adjacency to distinguish legal corners from self-intersection/retrace. Keep its original selected-candidate check; do not apply cross-path ownership rules to two primitives of the same path.

## 4. Exact forbidden relations, including ownership

A family is produced only after the current selected paths fail the existing independent selected-cell/index comparison. Locate one actually conflicting raw primitive pair in those two combos. Query its prebuilt exact membership masks; derive its full height relation. There is no all-primitives spatial join and no scan of every combo pair to find family members.

For each primitive pair, first compute whether their fixed XY projections intersect. Then use these closed-interval rules:

| Pair | Geometric intersection condition after fixed XY test |
| --- | --- |
| G/G | Fixed z values equal. |
| G/M | Moving height equals G's fixed z. |
| M/M | `h_i = h_j`. |
| G/R | G's fixed z lies in `[min(e_j,h_j), max(e_j,h_j)]`. |
| M/R | `min(e_j,h_j) ≤ h_i ≤ max(e_j,h_j)`. |
| R/R | Same XY and `max(min(e_i,h_i),min(e_j,h_j)) ≤ min(max(e_i,h_i),max(e_j,h_j))`. |

The XY test distinguishes collinear overlap, perpendicular crossing, and point intervals. Compute the complete intersection box, not just existence. Interchanging i/j gives symmetric cases. All equalities are inclusive.

An intersecting primitive pair is forbidden **unless** its whole intersection is one point `c` and `_owned(representative_i, representative_j, c)` is true. Representatives retain the original path endpoints and item; no candidate-dependent owner inference is needed. `_owned` (`P/template_paths.py:162–181`) requires the same item and either:

- the same physical port ID, opposite source/sink roles, and opposite outward directions; or
- distinct port IDs at the same actual junction ID, with different outward directions.

Both participating endpoints must equal `c`. A shared endpoint does not authorize another crossing, a different item, the same junction direction, or a longer overlap. Two legitimate owners do not authorize a third foreign occupant. Do not introduce an AMO over all paths at a coordinate where some owners can share: the current foreign-crossing witness specifically requires retaining both legitimate owners while rerouting the third path (`P/template_cadical_witness.py:68–115`). Family constraints remain pair-specific.

**Physical identity preflight is mandatory before spatial rejection.** `P/template_cadical.py:_identity_conflict` and `select:405–423` reject reused inconsistent port IDs even at disjoint coordinates. Retain global/global and fixed/global preflight and the fixed-index consistency checks. A primitive spatial index cannot establish their absence.

**Body ownership and fixed paths remain distinct.** A blocked body cell may be exempt only through an exact compiler-verified record in `problem.owned_endpoints`; coordinate coincidence or mere path-endpoint status is insufficient. Fixed-path overlap uses `_owned` and must be singleton. Keep `entry_rejections`, `exclude_static_middles`, `_FixedIndex.error`, and their existing expanded-cell agreement checks. Do not use the dynamic pair exception to broaden static permissions. The observed 107,653 static exclusions become exact forbidden `(combo, height_index)` pairs under factoring, not bans on a whole combo unless all its original heights are genuinely excluded.

### Actual-mall structural implication, not a frequency claim

Because saved global endpoints are all at zero and legal heights are positive, an intersecting M/R pair is forbidden when `h_middle ≤ h_riser`; avoiding that particular primitive intersection imposes the reverse strict order. Two selected nonzero risers on the same column have a positive-length common interval independent of their chosen heights. G/G and some G/R families are also height-independent. M/M crossing is equal-height exclusion. These relations explain why a geometry-family constraint can be stronger than learning one collision cell. The artifacts do not reveal how often these cases occur in the failed run.

## 5. Producer/consumer contract agreed with SAT

The geometry producer emits an immutable certificate:

- original domain IDs and their exact ordered level arrays;
- two primitive descriptors and exact combo membership masks `S_i`, `S_j`;
- selected original IDs that triggered discovery and their actual forbidden intersection;
- endpoint/ownership provenance, tied to the unchanged problem;
- the exact forbidden height relation as row runs, normalized into rectangles below.

For every `(q_i,q_j) ∈ S_i × S_j`, the emitted relation is the same primitive-pair forbidden relation. The certificate says this pair of selected primitives collides; it does not claim to enumerate every reason those two complete paths might be incompatible.

### Construct rows without a height-pair table

For each actual legal height `levels_i[p]`, bind primitive i. Partition j's original legal heights at the following critical constants:

- both z bounds of bound primitive i;
- j's fixed endpoint z when j is R (and its fixed z when j is G);
- z coordinates of all pair-authorized singleton endpoint contacts.

Separate equality classes from open intervals. Map them to nonempty index ranges using the actual sorted level array. An R endpoint is always `min/max(e_j,h_j)`; an M endpoint is `h_j`; a G endpoint is constant. Intersection emptiness, positive length, and singleton ownership can therefore change only at these constants. Evaluate one **actual legal height** in each nonempty class using the exact rules above, then emit maximal consecutive forbidden j-index intervals. Never manufacture an intermediate legal height, approximate a strict inequality, or iterate every integer between sparse legal levels.

Coalesce consecutive i rows **only when their complete ordered lists of j runs are identical**. For every run in such a row block emit one rectangle:

`(domain_i, S_i, domain_j, S_j, [p0,p1], [a,b])`.

Rectangles within a family are disjoint and exactly cover its relation. No arbitrary rectangle-cover search and no convex hull over unequal rows. A constant-height-independent relation becomes one rectangle; an equal-height diagonal with 24 common heights uses 24; a triangular precedence relation uses at most 24. This normalization is representation only.

### SAT interpretation

SAT owns exact one-hot selectors `X_d,q` for combos and `H_d,p` for original height indices. Define exact membership guards `G_d,S ↔ OR(q∈S) X_d,q`, and exact thresholds `T_d,k ↔ (height_index_d ≥ k)` with constants `T_d,0=true`, `T_d,L=false`. Membership/threshold equivalences must not leave their truth optional in a way that defeats a prohibition.

Each forbidden rectangle consumes the clause:

`¬G_i ∨ ¬G_j ∨ ¬T_i,p0 ∨ T_i,p1+1 ∨ ¬T_j,a ∨ T_j,b+1`.

Simplify constants; singleton masks can use X directly. The clause bans exactly that rectangle under those combo memberships. Never ban either combo independently. The solver must choose one combo and one original height per domain; reconstruction computes the original candidate ID and invokes unchanged `Domain._decode`. Static and self-invalid original candidates are exact binary bans `¬X_d,q ∨ ¬H_d,p` unless a separately proven equivalent compression is used.

The consumer requires that the just-rejected selected pair belongs to at least one newly emitted prohibition. Already-installed family identities cannot permit the same forbidden selection again under exact auxiliary definitions. Missing provenance, contradictory selected-cell/index answers, or a relation disagreeing with its actual trigger is an assertion/refusal, not a way to continue optimistically.

## 6. Preservation argument and completeness boundary

1. **Domain bijection:** exactly one original combo and one original height identify exactly one old candidate ID. All original IDs remain representable; logical admission is unchanged.
2. **Membership:** every selected combo in a family mask contains that exact raw parametric primitive. No envelope inclusion is mistaken for guaranteed occupancy.
3. **Relation exactness:** min/max intersection formulas plus the original singleton `_owned` predicate are the original cross-path conflict rule for those primitives. Critical-constant partitions and lossless row-block conversion do not change that Boolean relation.
4. **No spurious exclusion:** every emitted forbidden rectangle entails an actual forbidden primitive overlap for every guarded combo pair. Therefore no physically compatible complete candidate selection is removed. Exact static/self bans preserve their original rejected IDs.
5. **SAT projection:** auxiliary membership and threshold definitions have the actual selected combo/height assignment as an extension. Every safe original selection satisfies every emitted prohibition; every prohibited rectangle fails its clause.
6. **Progress:** the current incompatible pair has a raw conflicting primitive pair and belongs to its certificate. The emitted prohibition removes it and all certified equivalent combinations. The method does not rely on a memoized Boolean being fresh enough to supply a current collision cell.
7. **Completion:** under exhaustive finite refinement, no unchecked incompatible pair can be accepted. Under the actual finite budgets this is only a conditional completeness statement: the implementation may still return POLICY_BOUND or UNKNOWN. A final accepted model must pass the existing complete checks, regardless of what the learned formula appears to prove.

Keep the expanded selected-path cell sequence/set checks, `_path_error`, static cell versus `_FixedIndex.error` agreement, selected-pair expanded-cell versus indexed-path agreement, and final Cartesian `_compatible` audit (`P/template_cadical.py:552–629,666–676`). Keep construction, physical ownership/incidence and rate assessment, emitted/projected placement checks, registered validation, and decoded codec checks. `template_audit.py` explicitly audits full links and decoded physical intersections; geometry-family SAT is not a substitute. Physical/rated acceptance remains a separate unproved obligation.

## 7. Edge cases that must discriminate an implementation

- **Descending risers:** endpoints at seven with legal heights three/five/eight require both `[h,7]` and `[7,h]`. An upward-only threshold is unsound. Existing occupancy witnesses cover endpoints `(7,3)`, `(3,7)`, `(7,7)` and levels `(3,5,8)`.
- **Nonconsecutive heights:** comparisons use numeric heights; interval serialization uses indices. `height ≤ 7` over `(3,5,8)` means indices `[0,1]`, not an invented level seven.
- **Endpoint equality:** height equal to an endpoint can collapse an R to a point. Equality classes must remain separate; deleting only relative-order distinctions was already caught by the height-order witness.
- **All four endpoint constants:** a whole-path height-order alternative must classify each chosen height against both paths' source and sink z values, not only its own endpoints. H's `height_classes` uses all global endpoints, a sufficient refinement.
- **Relative chosen-height order:** identical endpoint-height classes alone do not preserve an M/R crossing; `<`, `=`, `>` must remain distinct in the whole-pair alternative.
- **Shared endpoints and foreign crossings:** two valid junction owners may coexist at one point while a third path crossing that point is forbidden. Preserve item, role, direction, port identity, and actual junction incidence.
- **Non-singleton overlap:** two owned endpoints at the ends of an overlap do not authorize the intervening shared segment. Exemption applies to the whole intersection being one point, not to its endpoints individually.
- **Collinear retraces/zero segments:** primitive union must not XOR away overlap or normalize a reversal into a legal continuation. Self validity is checked independently.
- **Static body versus fixed link:** compiler-owned body contact and same-item fixed-path incidence are different proofs; masks must not conflate them.
- **Disjoint reused port identity:** reject before path-envelope checks. Spatial disjointness is not sufficient compatibility.

`P/template_cadical_witness.py`, `P/entry_oracle.py`, `P/static_oracle.py`, and `H/height_order_witness.py` document relevant existing oracles. H's saved proof covers 10,240 canonical comparisons and 8,352 equivalence revisits. These are supporting evidence for the underlying geometry, not tests of the proposed new family compiler. The requested `template_contract.py` is not present in these revisions; actual budget-contract witnesses are in `template_contract_witness.py:26–53` and implementation is `template_budget.py`.

## 8. Alternatives, cost risks, and unchanged accounting

### Alternatives considered

1. **Recommended: demand-driven primitive families.** Generalizes across all heights and every combo containing a certified primitive, with a direct min/max proof. Risks are new descriptor/mask preparation, threshold/guard CNF, weak mask reuse, and many rectangles.
2. **Whole-XY-pair height-order families.** Guard one selected combo on each side and the endpoint-height classes plus relative order from H. Existing monotone-z proof is especially simple and handles full-path interactions. It learns across heights but not across combo masks; all-combo-pair precompilation remains unacceptable. This is a viable smaller design, but potentially much weaker reuse than primitive families. Runtime superiority is unknown.
3. **Eager cell resources or all candidate/combo pair conflicts.** Exact with ownership-aware exceptions, but either retains the cell discovery/materialization burden or incurs the 616.875-million XY-pair table before heights. Reject as the proposed architecture. Neither an AMO at every coordinate nor another mask cache is a substitute.

### Asymptotics and risks

Let K be total XY combinations, S≤9 primitives/combo, F discovered distinct primitive families, and L maximum legal-height count. A streaming primitive dictionary takes O(KS) occurrences and exact membership storage; it avoids both cell-length expansion and the O(K²) inter-domain join. Deterministic interning/sorting and bitset operations still cost time and memory. In the actual mall, a per-domain combo mask is at most 250 bits, but the number of distinct masks/descriptors has not been measured.

After a selected incompatible pair is known, extracting a witnessing raw primitive pair takes at most S² exact intersection attempts for that pair, not all combos. Row extraction costs O(L times a bounded number of critical regions and legal-level searches), plus emitted runs, rather than an L² truth table. General arbitrary relations could require L_i·ceil(L_j/2) runs; G/M/R geometry has far fewer critical regions, but correctness and accounting must not assume a favorable relation. Family storage and SAT clauses scale with encountered families, not with a proven small global total.

An equal-height relation may cost 24 rectangles. Under a 20,000-cut limit, only 833 entirely distinct 24-rectangle families fit if they do not simplify or deduplicate; this is a real rejection risk. Conversely, unconditional co-column-riser conflicts simplify to one rectangle. A single family can be stronger than one existing cell cut but also more expensive. Broad learning alone does not establish solver progress or end-to-end improvement.

### Accounting contract

- Original end-to-end control 30 s and original mall 60 s; preserve the frozen gate start and supervisor semantics. All new preparation is inside that gate. No preprocessing admission is treated as free solver preparation.
- Preserve arcs 100,000; augmentations 100,000; candidates 2,000,000; audit cells 5,000,000; predicates 5,000,000; assignments 100,000 (`template_budget.py:22–50`). Keep sharing of work/deadline across topology attempts.
- Preserve the original logical `budget.charge("candidates", d.count)` even when no Cartesian candidate SAT variables are allocated; actual decoding continues to charge candidates. Domain admission is not replaced by selector count.
- Every actually performed new primitive membership/intersection/height-bound/ownership comparison is budgeted as predicate work; retain existing charges for retained algorithms. Every actual expanded audit cell remains charged. Check the absolute deadline on dictionary hits, descriptor traversal, partition searches, deduplication, model decoding, and clause construction, not only on misses or solver calls. Sorting/bitset operations are real preprocessing, not excluded from elapsed time.
- Preserve 2,000 rounds, 20,000 collision prohibitions, 20,000,000 CNF clauses, CaDiCaL195, seed zero, and the existing 1,000-conflict/10,000-decision native-call limits. Charge each distinct normalized emitted rectangle prohibition against the existing 20,000 collision-cut cap, **not** one token for a family that emits many rectangles. Deduplicate canonical simplified prohibitions; every generated auxiliary/definition/prohibition clause is also charged to the clause cap. Static/self bans retain their original clause accounting.
- Eliminate charges only for operations genuinely no longer performed, such as expansion of removed Cartesian candidate-to-occupancy implications. Do not relabel geometry predicates as uncharged Boolean bookkeeping. A cap reached during family construction is POLICY_BOUND, not a signal to skip a check or hide remaining work in a cache.

## 9. Minimal discriminating experiment, not executed here

After separate approval for implementation, create one new isolated revision from path-envelope, preserving all frozen predecessors. Keep original candidate geometry, static checks, physical checks, CaDiCaL policy, and budgets; no tuning sweep, geometry/interface change, fallback global router, or production promotion.

First establish the exact family compiler contract on deterministic small finite examples. Compare family membership/forbidden pairs in both directions against independently expanded geometry and canonical Cartesian comparison; include every edge case above. Check reconstruction and SAT existential projection on the same small domains. Mutations must fail for upward-only risers, merged equality classes, dropped relative order, coordinate-only ownership, broad AMO sharing, a convex hull across unequal row lists, and a membership mask containing a combo without the primitive. These are correctness admission requirements, not evidence already obtained.

Then run exactly the original full control gate at 30 s. On success, run the original mall at 60 s; do not spend the mall gate comparing a tuning grid. Record only aggregate structural counters: logical candidates versus actual primary/auxiliary variables, primitive descriptors/membership entries, families, rectangles, clauses, represented forbidden combinations, static/self rejections, selected-model rounds, all original work counters, coarse preparation/native/settlement times, and actual terminal outcomes. Count represented combinations arithmetically without expanding them; do not mistake overlapping certificates for unique eliminated candidate pairs.

The narrow mechanism prediction is fewer Cartesian selector/occupancy implications and first-discovery constraints that cover unvisited heights/combos. The operational hypothesis is validator-complete original-mall geometry within all original caps. Reject the revision for any oracle mismatch, missing trigger coverage, changed candidate/ownership acceptance, suppressed independent check, hidden preprocessing, or increased effective limit. A failed full control stops the mall gate. A failed original mall rejects promotion and leaves repeats/held-outs NOT_REACHED; it does not prove infeasibility. Only original-mall success opens required cold repeats and then held-outs. A geometry witness alone never establishes rated acceptance.

## 10. Peer review outcome

Geometry's early proposal was G/M/R primitive conflict relations with exact combo masks. SAT initially proposed whole-XY-pair height-order classes. Geometry challenged missing cross-endpoint constants, height equality/relative order, independently banning guarded combos, and ownership-based overgeneralization. SAT accepted those concerns and proposed exact height row-runs with X/H/threshold CNF.

SAT challenged whether normalized/retraced paths invalidate broad primitive masks, and whether an eager primitive spatial join hides an O(K²) preparation step. Geometry answered with the raw-to-normalized occupancy-union proof, identical-descriptor-only membership, unchanged self checks, and discovery only from actual selected conflicting primitives. SAT reviewed the critical-constant partition and confirmed it includes both bound-i z endpoints, R's fixed endpoint, and all authorized singleton heights. Both accepted lossless identical-row coalescing, exact membership/threshold definitions, reconstruction by original ID, preserved selected-cell/index and final Cartesian gates, and rectangle-level cut accounting.

There is no unresolved disagreement on the recommended current G/M/R architecture. SAT initially considered a separately certified current-pair singleton nogood for unsupported future descriptors; integration explicitly limits runtime to the current G/M/R descriptors and removes that fallback subsystem. Exact singleton/no-generalization nogoods may serve only as a throwaway discriminating baseline, not a runtime escape. Failure to find the promised primitive certificate is a correctness failure; neither budget exhaustion nor oracle disagreement permits silent weakening. No consensus about speedup or mall feasibility is claimed; those remain unmeasured hypotheses.
