# CaDiCaL SAT architecture note — semantic factors and exact conflict families

Date: 2026-09-09. Owner: SatArchitecture. Status: design only; not implemented or measured.

This note owns the SAT representation/refinement slice. GeometryArchitecture reviewed the proposal and owns the primitive-intersection proof detail. Main owns integration. Only this note was written; no solver, profiler, build, formatter, linter, test, VCS operation, dependency change, or production change was performed. Read-only calculations below use existing artifacts and source formulas.

## 1. Decision and falsifiable hypothesis

Recommend **semantic XY/height factors plus demand-driven exact primitive-conflict families**, retaining CaDiCaL and the existing original candidate universe. Replace flat candidate Booleans and collision-cell occupancy CNF, not physical emission, static legality, or acceptance checks.

**[INFERENCE; unmeasured hypothesis]** Much of the repeated work can be eliminated by teaching SAT that all choices containing the same geometric primitive obey the same forbidden height relation. The current encoding discovers a concrete collision cell, reconstructs its candidate occupancy masks, and emits an implication for every candidate bit in each new mask. A primitive family can express, for example, that two middle segments cannot choose equal heights, or a middle segment cannot lie inside another path's riser, across all XY combinations containing those primitives and all applicable original heights. Semantic factors also eliminate the Cartesian product of candidate variables.

This is not a claim that native solving is negligible or that geometry checking is the sole bottleneck. The hypothesis fails operationally if preprocessing, weak SAT propagation, family count, or retained final checks consume the saved work/time. It also fails immediately if any claimed family excludes an originally feasible candidate selection.

## 2. Evidence ledger and limits of attribution

Paths below are relative to this worktree. Let `E` denote `docs/superpowers/evidence/2026-09-06-feasibility-first/`. Each revision has a `report.json` and `reproduction.zip`. The ZIP members cited by suffix are `template-cases/unsprayed-mall/captured/solver-progress.json`, `template-cases/unsprayed-mall/result.json` where present, and `template-cases/admission/unsprayed-mall/result.json`.

| Revision under `E` | Control elapsed | Original mall outcome | Preparation / completed native solve | Last checkpoint rounds / collision cuts / clauses |
|---|---:|---|---:|---:|
| `cadical-product-domain` | 10.394 s | UNKNOWN, hard deadline during native call | 4.159 / 13.496 s | 71 / 7,337 / 6,397,927 |
| `cadical-mask-intern` | 10.219 s | UNKNOWN, hard deadline during native call | 4.777 / 14.029 s | 82 / 7,473 / 5,118,153 |
| `cadical-static-domain` | 11.370 s | POLICY_BOUND at 29.872 s | 4.426 / 5.438 s | 30 / 6,922 / 5,172,842 |
| `cadical-path-envelope` | 11.424 s | POLICY_BOUND at 36.984 s | 4.073 / 8.268 s | 46 / 8,776 / 6,223,699 |
| `cadical-height-order` | 11.030 s | POLICY_BOUND at 39.886 s | 4.395 / 8.566 s | 44 / 8,552 / 6,107,357 |

Sources: each `report.json` supplies authoritative outcome/control time; ZIP progress `stats` supplies preparation/native/CNF counters. Height-order also reproduces these fields in `report.json:mall.progress.stats`. Product-domain and mask-intern do not have a completed mall `result.json`; do not treat their last checkpoints as completion or as complete native-call timing.

Additional established evidence:

- All five admissions have 141 domains of 6,000 candidates and `domain_parameter_count=35,250`: 250 XY combinations and 24 legal heights per domain. Envelope `stats.candidate_variables=846000`; `static_rejected_candidates=107653`, including `entry_rejected_candidates=96000`.
- Envelope has 45,705 interned occupancy variables and 177,801 auxiliary variables at its last checkpoint. Height-order has 44,676 / 174,678 respectively. Both end at exactly 5,000,000 predicates and have zero lazy static cuts. Their progress work fields, 4,978,212 / 4,980,242 predicates, precede the final interrupted check and must not replace the final cap.
- Mask interning reduced occupancy variables from product-domain's 84,934 to 39,611 and total clauses from 6.398 M to 5.118 M, but did not cross the original mall gate. More rounds are not proof of better native inference or end-to-end acceptance.
- Plane-index regressed the actual-mall pair oracle from 6,764 to 12,609 predicates; no mall run followed. Height-order proved 10,240 canonical comparisons, including 8,352 repeated equivalence checks, but produced no mall improvement. Sources: `~/report4.md:92-101` and `docs/superpowers/plans/2026-09-08-constructive-composition.md:1480-1529`.
- GeometryArchitecture's read-only `captured/flights.json` analysis found all 141 global endpoint-height pairs equal to `(0,0)`. This simplifies the actual primitive formulas; it does not prove which primitive conflict type dominates. Global obligation ordinals are flight IDs, not assumed contiguous positions.

### What timing does and does not establish

In `.superpowers/sdd/2026-09-09-cadical-path-envelope/template_cadical.py`, `select()` sets `preparation_seconds` after domains, indexes, exact static exclusions, and initial CNF are built (lines 399–519). Its start is `SolveStats.started`, initialized with `TemplateRun.solve_stats` before `run()` in `template_experiment.execute()` (226–229), so this aggregate also includes pre-selection construction/capture within that attempt; it is not pure CNF compilation time. `solver_seconds` brackets only completed `solver.solve_limited()` calls (531–534). Model extraction, decoding, cell expansion, independent checks, occupancy-mask queries, refinement CNF insertion, checkpoints, and work between these boundaries are not separately timed. `template_experiment.execute()` starts the shared deadline before construction/topology attempts (206–229).

Arithmetic on completed envelope evidence gives `36.983578 - 4.072868 - 8.267846 = 24.642864 s` not assigned to those two aggregates; height-order gives `26.924654 s`. Completed native calls are about 22.36% / 21.48% of total elapsed. **These residuals are not function profiles or measurements of occupancy compilation alone.** They include multiple stages and checkpoint/report overhead. In hard-killed revisions the interrupted native call may not be added to `solver_seconds` at all.

The source does establish a structural amplification independently of timing: `occupancy_literal()` emits one clause per set candidate bit (495–513), while `select()` scans all selected domain pairs and learns a cell-keyed constraint (603–663). Equal masks are already interned. Another cache variant does not remove this representation.

## 3. Alternatives and tradeoffs

1. **Keep flat candidates; learn whole-pair height-order signature nogoods.** For fixed XY combinations, endpoint-height classes plus relative selected-height order define a sound equivalence family. Existing `height_classes()`/`height_order_key()` in height-order lines 389–421 supply a proof starting point. The constants must include all relevant pair endpoint heights, preserve equality classes, and retain relative order. Advantage: smaller geometric proof change. Disadvantage: keeps 846,000 candidate variables and learns only one XY-pair family; exposing class/order guards still requires large candidate implications unless semantic factors are introduced. Not selected as the main architecture.

2. **Semantic factors with exact primitive-family refinement — recommended.** Preserve XY combinations rather than further decomposing source-adapter/sink-adapter/shape selectors. This avoids new cross-factor reconstruction constraints. Share only identical full primitives within one domain, and forbid exact height relations between two primitive-membership guards. Advantage: compress both initial SAT choices and learned geometry across heights and XY choices. Risks: a larger primitive index, wider guarded clauses, potentially weaker propagation than a cell-wide AMO, and many distinct primitive pairs. These risks require a discriminator, not a speed claim.

3. **Eager complete incompatibility graph or all-primitive spatial join.** Reject. The actual all-XY-pair product is `choose(141,2)*250^2 = 616,875,000`, before height combinations. A full `24^2` expansion is 355,320,000,000 candidate pairs. Even a spatial join over all possible primitives can have large overlapping output. No eager global pair join, row-table sweep, tuning sweep, boundary alteration, or fallback global router belongs in the design. Static-domain evidence also shows that eliminating one lazy-cut class alone is not mall acceptance.

The recommendation changes the solver's represented variables and learned constraint units, not merely memoization. It does not assume a particular variable encoding necessarily helps CaDiCaL: guarded 4–6 literal clauses can propagate less strongly than binary occupancy clauses or a multi-domain AMO.

## 4. Exact cross-slice API and canonical identities

The protocol is solve-local and uses immutable domain metadata from the unchanged `template_paths.domains()` and `Domain._decode()` (path-envelope lines 239–354).

### Identity

- `DomainId`: original `Domain.obligation.ordinal`; maintain an explicit ordinal-to-dense-index map for SAT arrays.
- `CandidateRef(domain_id, combo, height_index)`; `0 <= combo < len(domain.lengths)`, `0 <= height_index < len(domain.levels)`.
- Original `candidate_id = combo * L + height_index`. Preserve the exact original sorted legal-height tuple and XY-combination order. Never treat physical z as an index or manufacture intermediate heights.
- `combo` already encodes source adapter, sink adapter, and middle shape via `_decode()`'s two `divmod` operations. Geometrically duplicate original IDs remain distinct choices.

### Primitive metadata

`Primitive(domain_id, kind, descriptor, combo_mask)`:

- `G`: fixed endpoint-adapter closed segment at its endpoint z.
- `M`: closed XY middle segment at the selected height.
- `R`: fixed XY column spanning the closed interval between endpoint z and selected height, including the degenerate point case.
- The descriptor is the **complete exact parametric segment**, not an envelope or union of similar segments. `combo_mask` contains precisely the original combinations containing that primitive. Ownership is attached to original domain endpoint/item metadata, not guessed from coordinates.

Build descriptors from consecutive raw template points before `_normal()`. Raw occupancy equals normalized occupancy: `_normal()` removes consecutive duplicates and merges continuations, never reversals (91–109). Identical primitive descriptors may be interned within a domain. Keep separate raw provenance as needed to certify a selected witness. Do not eager-create SAT membership guards or intersect all primitive pairs.

### Family record

`FamilyCut(left_domain, left_combo_mask, right_domain, right_combo_mask, row_blocks, provenance)`:

- Canonical domain order; masks nonempty, range-checked immutable bitsets.
- For every original left height index, producer gives the sorted disjoint maximal intervals of right height indices for which this primitive pair has a **forbidden** intersection.
- Canonical normalization groups consecutive left rows only when their **complete ordered right-run lists are identical**. A row block `[p0,p1]` plus each right run `[q0,q1]` is an exact disjoint rectangle. Empty rows emit nothing. This is lossless row-run serialization, not a convex-hull cover or heuristic rectangle search.
- `provenance` names both complete primitive descriptors, domain endpoint metadata, relation kind, and the concrete selected pair certified incompatible. Exact `_owned` singleton exemptions have already been subtracted.
- Every produced family must include the current rejected candidate pair. A family cannot return an empty/no-op relation for its advertised witness.

Normalization is deterministic and idempotent. If API domains arrive reversed, transpose the exact finite relation and then normalize; the recommended producer emits canonical order directly. Deduplicate complete logical rectangle prohibitions after canonicalization, not merely collision coordinates.

### Producer relation and ownership contract

For bound left height, partition the original right legal heights by critical z constants: both bounds of the bound left primitive, right riser endpoint z when present, and every pair-authorized singleton endpoint z. Separate equality from open intervals. The box-intersection result and singleton-ownership classification are constant within each such region for G/M/R descriptors. Evaluate one actual legal height per nonempty region and emit exact index runs. This avoids blindly enumerating `L_i*L_j`, and remains valid for gaps and descending risers.

GeometryArchitecture owns the complete case proof. Representative relations are MM equality, MR `min(e_j,h_j) <= h_i <= max(e_j,h_j)`, and RR closed interval overlap, with the symmetric and fixed-ground cases. Nonempty XY intersection is also required. A positive-length overlap remains forbidden even when an endpoint is owned. Only an overlap that is exactly one cell and satisfies `_owned()` is permitted. Physical port-identity conflicts are checked before every spatial rejection, as in current `_identity_conflict()` and `_compatible()`.

## 5. SAT encoding

### Semantic choices and reconstruction

For each domain d allocate:

- `X[d,c]`: one-hot original XY combination.
- `H[d,p]`: one-hot original legal-height index.
- Reuse the existing two-product exactly-one helper independently on X and H; retain at-least-one clauses and both axis AMOs.

There are no primary Cartesian candidate Booleans. Each model must contain exactly one true X and one true H per domain. Reconstruct `ci = c*L+p`, call unchanged `Domain._decode(ci,budget)`, and emit original ordinal-keyed paths. No geometry is reconstructed from auxiliary guards or symbolic primitives.

An exact static exclusion of old candidate `(c,p)` becomes `not X[d,c] or not H[d,p]`. Initially retain the current `entry_rejections()` and `exclude_static_middles()` masks and translate every set bit. This deliberately leaves their proven geometry unchanged and retains their index cost; future removal is not silently included. A selected `_path_error()` failure produces the same binary exact-candidate exclusion. Keeping all originally invalid raw choices representable until a sound exclusion is learned is harmless; removing arbitrary valid choices is not.

### Exact height thresholds

Define `T[d,k] <-> (height_index >= k)`; `T[d,0]=true`, `T[d,L]=false`. Internal suffix thresholds use `T[k] <-> (H[k] or T[k+1])` with the standard three Tseitin clauses and constant simplification:

- `not H[k] or T[k]`;
- `not T[k+1] or T[k]`;
- `not T[k] or H[k] or T[k+1]`.

Threshold truth is exact, not optional. A height index lies in `[a,b]` iff `T[a] and not T[b+1]`. Physical heights need not be consecutive.

### Exact primitive-membership guards

For combo set S, `G[d,S] <-> OR(X[d,c] for c in S)`:

- For each `c in S`, add `not X[d,c] or G[d,S]`.
- Add `not G[d,S] or X[d,c1] or ... or X[d,cm]`.
- A singleton uses X directly; the full domain uses true. Intern by `(domain_id, exact combo_mask)`.

Full equivalence gives a unique auxiliary truth and avoids optional-guard model ambiguity. The reverse clause may be wide; its memory and inference effects are measured, not assumed beneficial.

### Forbidden rectangle clause

For combo guards Gi/Gj and forbidden height rectangle `[p0,p1] x [q0,q1]`, add:

`not Gi or not Gj or not T[i,p0] or T[i,p1+1] or not T[j,q0] or T[j,q1+1]`.

Simplify constants, remove duplicate literals, reject tautological/no-op output for an advertised forbidden witness, and canonicalize before deduplication. Full-height intervals remove height literals. Freeze the threshold form above, including singleton intervals; do not tune between equivalent clause forms.

The exact non-generalizing case is the same protocol with singleton combo masks and singleton height intervals, logically equivalent to `not X_i,c or not H_i,p or not X_j,c' or not H_j,q`. It is justified by the original incompatible selected pair, not by an approximate descriptor. This is the explicit exact fallback representation for an intentionally non-generalizing producer; the only such branch needed in the present scope is the throwaway discriminating baseline. Future descriptor support or a runtime fallback subsystem is not implementation scope. **Missing G/M/R provenance, an empty advertised family, a relation/witness disagreement, or exhausted work/deadline is an assertion/refusal, never silently hidden by this fallback.** The recommended G/M/R runtime must return a covering primitive family.

## 6. Incremental lifecycle and migration boundary

1. Keep `template_experiment.execute()`'s original specification/frozen identity checks, topology order, shared `WorkBudget`, absolute deadline, admission gate, and no-router guard. Create a new isolated revision only after design approval; never overwrite a frozen revision or its admissions.
2. `TemplateConstructor.finish()` still captures actual physical ports/blocked geometry/fixed paths, builds the same `TemplateProblem`, and emits fixed transfers. `select()` still performs physical identity preflight and exact static compilation. Charge the full original logical candidate count even though it is not allocated as SAT variables.
3. Build domain factors and bounded primitive metadata; no primitive-pair join. Add exact X/H constraints, thresholds, and translated static exclusions. Coarse counters distinguish logical candidates, SAT primary/auxiliary variables, and clauses; do not rename fewer Booleans into fewer admitted candidates.
4. Keep `Cadical195`, seed 0, 1,000 conflicts / 10,000 decisions per limited call, and existing interruptible native-call loop. Extract original candidate IDs and independently decode them after every SAT model.
5. Retain current selected-path self checks, expanded occupancy validation against static geometry, selected-pair cell/index comparison, and final independent Cartesian `_compatible()` audit. The retained checks are an important possible residual bottleneck. Primitive metadata does not certify a model as accepted.
6. For each actually rejected cross-domain pair, find a concrete raw primitive-pair witness using exact segment relations. Produce its combo-set/height family on demand, check witness inclusion, normalize, and add each new prohibition. Do not inspect every possible XY/primitive pair in anticipation. Existing last-choice/last-pair checks may stay unchanged; do not add another cache experiment.
7. Every invalid selected assignment receives at least one newly effective exact exclusion. If a supposedly learned clause already exists yet the same choice survives, fail the encoding invariant. If the current budget cannot finish producing/adding a sound exclusion, return its existing bounded failure, never an accepted partial selection.
8. When no invalid paths/pairs remain, run unchanged final Cartesian compatibility, reconstruct `selected_candidate_ids`, return original paths, and let `TemplateConstructor.finish()` perform unchanged real emission. Retain physical ownership, settlement/capacity, registered validator, projected/decoded geometry and codec checks. GEOMETRY_ONLY is not rated acceptance.

Clean cutover in the future experimental `select()` removes flat candidate offsets/model scanning, dynamic occupancy propositions, cell-query refinement, and cell-keyed collision AMOs. It does not remove `CellIndex`/`DomainIndex` while static exclusion still depends on them. `template_runtime.py` keeps its selected-path return contract; only stats serialization can gain explicit factor/family counts. `template_experiment.py` changes its new revision's representation policy/admission identity, not specs, supported cases, budgets, or acceptance states. Height-order's Boolean cache is not carried forward as a claimed architectural benefit.

## 7. Soundness, completeness, and progress argument

**Domain bijection.** Current `Domain.count=K*L` and `_decode()` uses `divmod(ci,L)`. Independent exact-one X and H assignments correspond bijectively to every original `ci` in each domain; duplicate geometry IDs remain distinct. Product-EO auxiliary assignments exist for each singleton exactly as in the current proof. Thus factoring alone neither admits a new candidate geometry nor loses an old candidate ID.

**Auxiliary extension.** For any original candidate selection, choose the corresponding X/H singleton assignment, valid product-EO axis/counter extension, exact suffix-threshold truth, and exact OR-membership truth. Every definition is satisfied. Conversely every satisfying definition assignment determines those same choices and truthful guards/thresholds. No auxiliary can evade a forbidden rectangle.

**Cut soundness.** For any candidate pair satisfying both combo masks and a forbidden height rectangle, both paths contain the certified primitives. Their intersection is not an authorized singleton; therefore the original pair is incompatible. A forbidden rectangle clause removes only incompatible candidate selections. Exact static and self exclusions retain their existing proofs. Two masks must remain conjunctive: independently banning their members would be unsound.

**Selection completeness.** Take any globally feasible original selection. The bijection gives X/H, and the auxiliary extension above exists. It violates no exact static/self exclusion or certified family clause, so every incremental SAT formula retains an extension. Hence an UNSAT result on sound clauses is still exhaustion of the original finite template family, not general factory infeasibility. This proof is about feasible candidate selections, not preservation of the old relaxation's intermediate invalid models or solver order.

**Monotone progress.** Each rejected selected model either gets an exact unary candidate ban or a family clause containing its exact pair; that clause is false under its truthful guards/thresholds. The same invalid selection cannot return. The finite-domain refinement is therefore complete with unbounded resources and exhaustive checking, but the actual fixed work/deadline/round/cut limits can still stop it without a witness.

**Proof obligations before execution:** raw/normalized occupancy equivalence including degenerate segments; complete selected raw-pair provenance; exact primitive mask membership; all G/M/R intersection cases including equality/gaps/descending risers; ownership subtraction with foreign third paths and positive-length overlaps; exact critical-height partitions; row-block normalization equality; SAT existential projection; and unchanged final reconstruction. Existing height-order equivalence evidence supports only a narrower premise, not these new obligations automatically.

## 8. Complexity, memory, and unchanged work accounting

Let N be domains, K XY combinations/domain, L legal heights, S raw segments/combination, F discovered primitive pairs, and R normalized forbidden rectangles.

- Base semantic SAT work is `O(sum(K+L))`; static-mask translation remains `O(number of rejected original IDs)`. Original logical-domain admission is still `sum(K*L)`.
- Primitive extraction is `O(sum(K*S))` occurrences, with charged comparisons/index normalization. Membership guards are built only when used. No `sum(K_i*K_j)` or all-primitive-pair prepass is permitted.
- G/M/R critical-partition row generation is `O(L_i * B * log L_j)` in a binary-search implementation, where B is the small number of exact critical constants; emitted output and membership processing are additional work. Any sort/search/comparison work is charged. Do not claim O(1) for arbitrary Python big-integer masks.
- Family clauses are `O(R)` with at most six literals before simplification. Guard forward clauses cost the size of each newly used combo mask, not its Cartesian candidate mask. Worst-case many masks/families or a pathological forbidden relation can still erase this saving.
- At most nine raw primitive occurrences per actual combination gives `141*250*9=317,250` occurrences before interning. Python object/dictionary overhead may dominate packed bitsets; no process-RSS estimate is established. Do not materialize occurrence lists, full candidate masks, or all height tables solely to compute diagnostics. Memory lifetime is one solve/topology; cleanup on refusal is required.

### Derived sizes, not performance measurements

Reusing current two-product EO, a size-n domain uses `1+2n+(3r-4)+(3c-4)` clauses and `r+c+(r-1)+(c-1)` auxiliaries for the actual axis sizes here. Original n=6,000 gives r=77,c=78: 12,458 clauses/domain and 308 auxiliaries. Across 141 domains initial EO is 1,756,578 clauses; adding 107,653 static bans gives 1,864,231. Envelope's 6,223,699 terminal clauses therefore include another **4,359,468** clauses added after that preparation (not solely one timed function).

For K=250 and L=24, the reused helper gives 589 and 71 clauses respectively, 62 and 18 auxiliaries. Primary selectors are `141*(250+24)=38,634`. Including at most three clauses for each of 23 suffix thresholds gives **at most 102,789 base clauses and 53,157 total variables**. Keeping every current static ban gives **at most 210,442 prepared clauses**. Constant simplification can reduce these upper bounds. These figures exclude primitive guards, learned family clauses, later self exclusions, and native learned clauses; they are formula-derived, not observed compiler output or a promise of fast solving.

### Counter contract

Preserve original 30 s control / 60 s mall absolute end-to-end deadlines and `WorkLimits`: arcs 100,000; augmentations 100,000; candidates 2,000,000; audit_cells 5,000,000; predicates 5,000,000; assignments 100,000. Preserve 2,000 rounds, 20,000 collision prohibitions, 20,000,000 added clauses and existing native-call limits.

- Charge all original logical candidates before solving: the mall remains 846,000 admitted choices, plus unchanged candidate-decode charges. Fewer variables do not authorize a smaller candidate charge.
- Charge every performed primitive/comparison/partition/mask-membership/normalization/index step to predicates; every enumerated physical cell remains audit_cells. This is conservative explicit new-operation accounting, not moving work into an uncharged prepass. Bulk mask operations must expose/document their processed representation-word work rather than hide unbounded scans.
- Every distinct emitted normalized rectangle prohibition consumes one collision-cut unit. This **supersedes the draft per-row-run granularity** after lossless identical-row coalescing. There is no allowance increase. Deduplicate identical logical clauses before charging/emitting, but charge normalization/dedup work. A duplicate is not a new progress event.
- Every auxiliary definition, guard clause, exact static/self ban and family clause counts toward the unchanged clause cap. Deadline checks surround solver calls and occur during all extraction, sorting, mask, normalization, model decoding, and final-audit loops, including reuse hits. No phase resets deadlines or counters.
- Clause insertion and threshold creation also have explicit charged construction steps; do not describe removed geometry work as savings while performing an equivalent uncounted compiler loop.

The 20,000 normalized-rectangle cap is a genuine early rejection risk. A constant family may use one prohibition; equality over 24 heights uses 24, and a triangular order relation approximately 24. Ten thousand discovered families are not automatically permitted just because their representation is compact in memory.

## 9. Predictions and minimal discriminating experiment

**[INFERENCE; unmeasured prediction]** The initial added-CNF count should be below 211,000 on the original mall before primitive guards/refinement, under the stated unchanged static masks. This is a sharp implementation check against the derived bound, not a runtime forecast.

**[INFERENCE; unmeasured performance hypothesis]** The representation change will permit the full original-mall gate to complete within its unchanged 60 s deadline and numerical limits, after the unchanged 30 s control gate passes. Existing evidence does not support an additional selection-time, predicate, or learned-CNF target. The discriminator reports those quantities to explain the tradeoff, without rejecting a legitimate full original-budget success for missing an invented intermediate target. Smaller formulas or faster local compilation alone do not accept a mall.

**[INFERENCE; unmeasured failure risks]** Mostly singleton primitive masks, normalized-rectangle pressure near the 20,000 cap, or increased native solve cost could leave this architecture bounded. These are diagnostic explanations to evaluate, not independent numerical rejection gates. Only the derived representation invariants, semantic/proof obligations, unchanged original caps, and full original end-to-end gates govern rejection.

A future minimal discriminator, before a new original-mall solve:

1. Freeze one isolated candidate revision and one deterministic, solver-free list of actual-domain `CandidateRef` pairs. Use the archived actual-mall oracle's candidate-generation rule where recoverable; otherwise explicitly record the canonical ID rule before inspecting results. Scalar `solver-progress.json` does not contain a selected trace and must not be treated as one. No alternate rule/seed sweep after seeing costs.
2. On that one list, compare the original Cartesian comparator with primitive-family truth, including selected witnesses and additional original heights/combos covered by masks. Tiny exhaustive synthetic domains establish SAT projection and ownership boundaries; actual-domain checks exercise the real primitive shapes. Keep the current external safety/control witnesses and add only proof-bearing new cases. This is prospective work, not tests performed for this note.
3. Compile the same finite discovered conflicts into (a) exact point-pair nogoods over semantic factors and (b) primitive-family rectangles in a throwaway, solver-free discriminator. Report initial clauses, logical choices, variables, guard membership sizes, rectangles, charged predicates, and coarse compile elapsed; verify each claimed family contains its witness and no known compatible pair. This isolates family generalization from variable reduction without rerunning the old full solver or claiming a compile-only result is acceptance. Do not retain a second runtime/fallback architecture merely to benchmark it.
4. Reject before a mall run on any equivalence disagreement, advertised missing witness, eager pair expansion, cap exhaustion, or failure of the derived prepared-CNF bound under identical inputs. Otherwise run exactly one original control, then one original mall only if control passes. Coarse preparation/native/model-check-refinement/settlement boundaries are allowed future measurements; no function-level profiler or tuning sweep.

All discriminator computation must itself use the original numerical limits and a declared original-sized deadline; it does not supply extra time to the subsequent fresh end-to-end gate. Its results must be labeled diagnostic. Repeat/held-out execution remains prerequisite-gated.

## 10. End-to-end acceptance and rejection

- No implementation authorization or successful run is implied by this note. Freeze new sources/policy/admissions separately; all 19 earlier source/spec/manifest/admission identities remain immutable.
- Full original control must complete within 30 s, including independent Cartesian checks, actual emission, physical ownership/capacity audits, registered validation and codec. Existing latest evidence is 67 registered checks and zero errors, not permission to remove checks or substitute a smaller control.
- Original unsprayed mall must complete the same full geometry/physical/codec gate within 60 s and every unchanged numerical cap, with zero global-router calls and actual original candidate reconstruction. No timeout, POLICY_BOUND, missing selection, or merely SAT model counts as acceptance.
- `TEMPLATE_FAMILY_EXHAUSTED` is justified only by an actual UNSAT on complete original choices and sound cuts; it is not unrestricted factory infeasibility. Budget/deadline failures remain bounded failures.
- A successful geometry-only control or mall is not `RATED_ORIGINAL_ACCEPTED`. Exact rates, physical ownership and all original rated acceptance conditions remain separate and unchanged.
- Cold-success repeats and held-outs remain NOT_REACHED until their original-mall prerequisite succeeds; no production promotion follows one successful local or original run.
- A regression in soundness/projection, hidden domain restriction, changed boundary geometry, uncharged work, incomplete final audit, or a bounded original-mall outcome rejects this candidate revision. Do not rescue it by raising budgets, changing topology/specs, omitting checks, or continuing the closed cache/index tuning line.

## 11. Peer-review outcomes and unresolved risks

GeometryArchitecture challenged the initial whole-pair signature proposal: it required endpoint classes relative to all relevant fixed endpoint heights and explicit relative h order; unary height classes alone miss moving riser crossings. I accepted the critique and moved the recommendation to primitive relations, which also generalize across XY combinations.

I challenged primitive ownership grouping and eager compilation. Resolution: raw exact full descriptors only, never geometric envelopes/unions; `_normal()` occupancy preservation supplies the bridge; singleton exemptions retain domain endpoint/item identity; positive-length overlap is never excused; build an occurrence index but no all-pairs join. GeometryArchitecture accepted exact X/H/threshold/guard encoding and row-run API. I reviewed its critical-constant partition: bound primitive endpoints, riser endpoint, and authorized singleton heights cover changes in closed-interval intersection/ownership truth for the supported G/M/R grammar.

Both agents accepted deterministic coalescing only of adjacent rows with identical complete run lists, exact rectangle clauses, original ordinal identity, full logical-candidate charges, and conservative normalized-rectangle cut accounting. Main approved the accounting contract. GeometryArchitecture correctly rejected silent singleton fallback after missing provenance or a contradictory family; that prohibition is explicit above.

There is no unresolved semantic disagreement between the two slice proposals. **Unresolved empirical/proof risks remain:** actual primitive interning/membership sizes, Python memory cost, family frequency and cut-cap pressure, guarded-clause inference strength versus cell-wide AMOs, how much retained checking still costs, and the new primitive/partition/projection proof obligations. Agreement is not evidence that these risks are solved or that the mall is feasible. The recommendation is a falsifiable next architecture, not a success claim.
