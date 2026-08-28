# Sequence-Pair Routing Solver Design

**Status:** Approved architecture; implementation not started  
**Worktree:** `/home/dannyb/sources/factorio-lab-to-blueprint-sequence-pair-solver`  
**Branch:** `sequence-pair-solver`

## 1. Decision

Build a parallel, audit-only freeform backend with this closed loop:

1. sequence-pair simulated annealing and targeted large-neighbourhood search;
2. a relaxed DSP-aware global router;
3. the existing detailed A* router at every temperature-stage boundary;
4. structured detailed-router feedback into net weights, congestion history, gap pressure, and the next LNS neighbourhood;
5. exact acceptance only after detailed routing and `validate.certify()`.

The current CP-SAT `FreeformLayout` remains the production default until the new backend passes the full promotion gate. After promotion, `FreeformLayout` cleanly switches to the new engine. CP-SAT leaves the production placement path and remains only as a benchmark/oracle.

The first implementation is typed Python. Hot kernels retain array-oriented boundaries so Numba and JAX can be evaluated independently. Rust or C++ is a third-line acceleration option, not an initial dependency.

## 2. Motivation and evidence

The current CP-SAT packer is not the dominant end-to-end scaling problem. On `quantum-chip/no-proliferator`, the measured CP-SAT model had 312 variables and 721 constraints; one candidate took about 0.51 seconds while detailed routing took 1–5 seconds depending on the arrangement.

Arrangement, not outline alone, determines routability. Randomized same-height CP-SAT candidates ranged from fully routed to deadline exhaustion. A previous pure PackingSolver experiment produced an equal-area pack whose final routed area was 44% worse because the placement ignored connectivity.

A disposable sequence-pair spike established enough headroom to justify the architecture:

- production freeform, power off: 9.95 seconds, area 10,877, 5,962 belt tiles;
- single-thread Python sequence-pair SA, 40,000 moves: 3.97 seconds;
- existing detailed router and validator: 0.51 seconds;
- total: 4.48 seconds, area 10,125, 5,247 belt tiles.

The powered version of the same compact candidate remained one net short. That result makes detailed-router feedback and power-aware global routing mandatory. A placement-only replacement is insufficient.

## 3. Goals

- Reduce end-to-end time to a fully detailed-routed, validator-clean placement.
- Preserve or improve exact final area and belt count.
- Make placement respond to the detailed router's actual stranded nets and blame walls.
- Evaluate many legal placements cheaply without making a proxy authoritative.
- Preserve the existing wall-clock deadline, deterministic expansion budget, refusal semantics, direct insertion, proliferation, external access, power, and validation contracts.
- Keep the solver deterministic for fixed seeds and deterministic budgets, aside from the existing hard wall-clock cutoff.
- Permit Python, Numba, JAX, and a future native implementation behind identical kernel contracts.

## 4. Non-goals

- Do not adapt OpenROAD's LEF/DEF interfaces or routing database.
- Do not make the relaxed global router emit belts, sorters, splitters, or junctions.
- Do not accept global-routable or partially detailed-routed candidates.
- Do not expose permanent user-selectable CP-SAT and sequence-pair modes.
- Do not rotate strips.
- Do not add a learned model or train from the corpus.
- Do not rewrite the existing detailed router before the new feedback contract is covered by tests.

## 5. Rollout boundary

During development:

- `FreeformLayout` remains unchanged as the production strategy.
- `SequencePairLayout` implements `LayoutStrategy` and is registered only in audit/benchmark tooling.
- Both backends use the same strip planner, exact routing-problem preparation, detailed router, validator, deadline, and expansion-budget semantics.
- A/B results identify the backend explicitly.

After the promotion gate:

- `FreeformLayout` delegates to the sequence-pair solver.
- The audit-only strategy name is removed rather than becoming a permanent alias.
- CP-SAT packing is moved out of the production call graph and retained only in benchmark/oracle code.

## 6. Module boundaries

### `layout/sequence_pair.py`

Owns placement search only:

- `SequencePair` state;
- `GapProfile`;
- deterministic decoder;
- SA moves and acceptance;
- multi-start state;
- targeted LNS destroy/repair;
- direct-insert opportunity score;
- Python reference kernels and accelerator protocol.

It does not know about `PlacedBuilding`, detailed paths, validation, or time-budget policy.

### `layout/global_router.py`

Owns relaxed routing:

- exact tile/level movement graph derived from the prepared problem;
- provisional occupancy and compatible sharing;
- PathFinder-style present and historical congestion;
- deterministic routing rounds;
- `GlobalRouteResult` and per-net cost data.

It never mutates a production canvas or emits buildings.

### `layout/route_feedback.py`

Owns the contract between detailed routing and placement:

- stable `NetId` and strip ownership;
- detailed failure categories;
- `DetailedRouteResult`;
- net criticality and decay;
- blame-wall congestion updates;
- LNS-neighbourhood selection;
- outline-scoped cell history.

### `layout/sequence_solver.py`

Owns orchestration:

- candidate heights and restarts;
- temperature stages;
- global- and detailed-route cadence;
- shared deadline and expansion budget;
- exact incumbent selection;
- refusal behavior;
- solver statistics.

### `layout/freeform.py`

Initially remains authoritative for:

- strip planning and geometry;
- direct-insert definitions;
- exact canvas preparation and emission;
- the existing detailed router;
- power placement;
- final `Placement` construction.

Only the preparation and reporting seams needed by both engines are extracted. A wholesale detailed-router move is explicitly outside the first implementation.

## 7. Placement representation

### 7.1 Sequence pair

A state contains two permutations of every strip ID. For each pair of strips, their order in the two permutations determines whether one is left, right, above, or below the other. The decoder builds horizontal and vertical constraint graphs and computes integer coordinates by deterministic longest paths.

This representation guarantees non-overlap for fixed-orientation rectangles. Strip dimensions continue to come from `_box()`, including the existing west channel and reserved margins. Returned content origins retain the current `WEST_CHANNEL` convention.

The first decoder is allowed to be O(n²). The measured stress instance has roughly 40 strips, and the Python spike already generated useful throughput. A more complex incremental decoder requires profiling evidence.

### 7.2 Explicit whitespace

Pure bottom-left compaction is not a sufficient search space for power and routing. `GapProfile` stores bounded non-negative east and north slack per strip. Outgoing constraint-graph edges include this slack.

Initial bounds are 0–4 tiles per direction. The bounds are implementation constants, not user API. Corpus calibration may lower them but may not remove explicit whitespace without a replacement mechanism.

Gap cost is charged in the search energy. Detailed feedback may increase gap pressure for implicated strips; ordinary SA moves may also increase or decrease gaps.

### 7.3 Moves

The Python reference supports:

- swap two strips in the positive permutation;
- swap two strips in the negative permutation;
- swap the same pair in both;
- remove and reinsert one strip in either permutation;
- mutate one strip's east or north gap by one bounded step.

All moves preserve valid permutations. Move selection and acceptance are deterministic for a fixed derived seed.

### 7.4 Targeted LNS

A detailed failure creates an LNS neighbourhood containing:

1. source and destination strips of every genuinely stranded net;
2. endpoint strips of nets owning cells in the stranded net's blame wall;
3. immediate neighbours of those strips in both permutations;
4. strips whose explicit gaps overlap the hot region.

Every strip outside the neighbourhood keeps its relative order in both permutations. Destroy/repair removes the neighbourhood, reinserts it with weighted randomized ordering, then performs local gap moves. If a focused neighbourhood stagnates, it grows by one sequence-neighbour ring before control returns to broad SA.

Budget or deadline exhaustion does not create a neighbourhood because it is not evidence about geometry.

## 8. Direct insertion

Direct-insert eligibility remains defined by the existing freeform rules. Sequence search includes a cheap missed-opportunity penalty based on relative placement and lane overlap.

For globally routed stage elites, the decoder computes earliest and latest legal coordinates from the forward and reverse constraint graphs. A deterministic local alignment pass may shift eligible producer/consumer strips only inside those windows, while preserving every sequence-pair relation and rechecking non-overlap. It may improve a candidate or leave it unchanged; it cannot enlarge the outline or invalidate the placement.

CP-SAT remains the comparison oracle for direct-insert opportunity during rollout. The promotion gate covers exact final belt count, so a weaker local aligner cannot be hidden by area improvements.

## 9. Acceleration ladder

### 9.1 Python reference

Every kernel first has a readable, deterministic Python implementation. It defines semantics and remains the parity oracle.

Hot kernels accept integer array-like inputs and return plain immutable result objects. Search orchestration and error handling remain ordinary Python.

### 9.2 Numba and JAX

Numba is evaluated for branch-heavy kernels:

- sequence moves and decoding;
- constraint-graph longest paths;
- flat-grid A* and congestion updates.

JAX is evaluated for static, batched kernels:

- decoding batches of sequence pairs;
- batched cheap-score calculation;
- dense or bucketed global-congestion scoring where control flow is static.

Dynamic A* heaps are not distorted merely to fit JAX. CPU execution is measured first. Accelerator-device execution is considered only when compilation and transfer costs amortize within one normal `lay_out()` call.

An accelerated kernel is adopted only when it has exact output parity and improves end-to-end cold-call latency, CPU time, and memory on the matched corpus. Warm-only microbenchmark wins are insufficient.

### 9.3 Native code

Rust or C++ is considered only after profiling shows a kernel that neither Numba nor JAX accelerates adequately. A native implementation must satisfy the same parity fixtures and cannot own orchestration or acceptance semantics.

## 10. Shared routing-problem preparation

Refactor placement preparation into an immutable `PreparedRoutingProblem` consumed by both global and detailed routing. It contains:

- exact strip solids, lanes, sorter keep-outs, coaters, and direct inserts;
- fixed route bounds and three routing levels;
- exact source and destination port cells;
- stable net identity and owning source/destination strip IDs;
- sibling branch/merge groups;
- external-input boundary goals;
- proliferator entry/drop topology;
- power sites, keep-outs, and reserved cells;
- the catalog movement constants needed by both routers.

Preparation is the single interpretation of geometry. The global router may relax path capacity but may not reconstruct ports or obstacles differently.

Each routing attempt creates a fresh mutable workspace from the prepared problem. Provisional occupancy, path ownership, reservations spent during a search, and congestion history never leak between candidate attempts except through the explicit `FeedbackState`.

Unpowerable preparation or a port with no statically legal access cell is a hard placement rejection and returns a structured cause before routing begins. Access lost later because provisional or detailed paths occupy the available cells is a dynamic routing failure and participates in feedback.

## 11. Relaxed DSP-aware global router

### 11.1 Movement and obstacles

Use the same tile cells, three levels, step directions, ramp spans, route bounds, hard solids, port reservations, and ground/level tolls as the detailed router.

Hard obstacles remain impassable. Provisional paths may share route cells and create overflow. Compatible sibling branches or merges share capacity only when the prepared problem's existing grouping rules permit it; matching item IDs alone never permits sharing.

### 11.2 Negotiated congestion

Each route cell tracks integer occupancy. Search cost is:

`movement + level/ramp toll + present congestion + historical congestion`.

After every global-routing round, overflow cells increase historical congestion. All nets are ripped up and rerouted until overflow reaches zero, the deterministic round cap is reached, or the assigned expansion budget is consumed.

The initial global router reroutes the whole prepared problem. Incremental rerouting after local placement moves is deferred until profiling proves whole-problem global routing is a bottleneck.

### 11.3 Result

`GlobalRouteResult` contains:

- hard preparation failure, if any;
- unreachable port count;
- overflow cell count;
- total and maximum overflow;
- total route length and level changes;
- per-net length, overflow contribution, and expansion count;
- hot cells and compact hot-region boxes;
- deterministic rounds and total expansions.

It contains no buildings and cannot establish validity.

## 12. Detailed-router reporting

Give each prepared net a stable `NetId` derived from its source strip, destination strip, item, lane role, and deterministic ordinal.

At the end of every temperature stage, run the existing detailed router on the selected stage incumbent with a deterministic expansion allocation. Return `DetailedRouteResult` with:

- status: `ROUTED`, `STRANDED`, `UNPOWERABLE`, `BUDGET`, or `INVALID`;
- routed and stranded `NetId`s;
- per-net path length and expansions;
- failure cause: dynamic access loss, sealed pocket, congestion wall, commit/link failure, or budget exhaustion;
- blame-wall cells and owning `NetId`s;
- best partial paths;
- rip-up/repair iteration count;
- exact power or validation failures when reached.

`_astar()` records detailed diagnostics only on failure. The hot path does not allocate per-expanded-node trace objects.

## 13. Feedback update

For sealed-pocket, congestion-wall, dynamic-access, and commit/link failures:

1. Increase each stranded net's criticality by 1.0, capped at 8.0.
2. Increase blame-wall cell history by the detailed router's existing blame weight.
3. Build the next LNS neighbourhood from stranded and blocking net endpoints.
4. Increase local gap-mutation probability for implicated strips.
5. Multiply all prior net and cell feedback by 0.85 at the next stage boundary.

The exact numeric values are initial deterministic constants and are subject to matched corpus calibration; their monotonic meaning is fixed by this design.

Budget/deadline exhaustion is `UNKNOWN`: it creates no hard cut, net-weight increase, or cell-history increase.

Cell history persists only for one fixed outline and is reset when height changes. Net criticality persists across heights because logical connectivity does not change.

A detailed-routed, validator-clean candidate becomes an exact incumbent immediately. Its successful result may be cached by placement hash, prepared-topology hash, and power mode. Partial failures are not cached as permanent verdicts because they depend on budget and routing history.

## 14. Search orchestration

### 14.1 Height coverage

Create deterministic multi-start states for every candidate height. Discovery reserves an equal deterministic expansion slice for one temperature stage at each height before any height receives a second stage. Unused discovery expansions return to the shared pool. This removes expansion-budget starvation; only the hard wall-clock deadline may prevent a height's first stage.

After discovery, schedule the next stage using this ordered key:

1. whether the height has a valid exact incumbent;
2. fewest detailed stranded nets;
3. least global overflow;
4. smallest exact or estimated area;
5. least budget already spent.

### 14.2 Temperature stages

A stage:

1. runs a fixed deterministic block of cheap SA moves;
2. retains a small distinct elite set by placement hash;
3. global-routes the elites;
4. chooses the best stage incumbent by the stage ordering;
5. detailed-routes that incumbent with its expansion slice;
6. records an exact incumbent or updates feedback;
7. enters focused LNS when the stranded set is small.

The initial reference uses six temperature stages, 2,000 moves per stage, and two restarts per height. These are benchmark constants, not public configuration. The shared deadline may stop before every scheduled stage, but discovery cannot spend another height's reserved expansion slice.

### 14.3 Objective separation

Cheap SA energy combines normalized:

- outline overflow;
- area;
- feedback-weighted HPWL;
- global/history congestion approximation;
- missed direct inserts;
- explicit gap area.

Hard outline overflow dominates the scalar energy. Other weights are bounded and calibrated on the corpus.

The per-move history approximation integrates the outline-scoped congestion map over each net's rectilinear bounding box using a summed-area table. It is only a cheap ranking term. Global routing replaces it for stage elites, and detailed routing replaces both for feedback and acceptance.

Stage-incumbent ordering is lexicographic:

1. hard preparation failures;
2. detailed stranded count, when available;
3. global total overflow;
4. area;
5. weighted route cost;
6. missed direct inserts.

Exact validated incumbents compare only `(placement.area, belt_tiles)`. A proxy-improved candidate cannot replace a worse exact incumbent.

Once a valid incumbent exists, quality mode constrains candidate area not to exceed it and continues searching for smaller valid placements while budget remains.

## 15. Budget and failure semantics

One wall-clock deadline covers planning, placement, global routing, detailed routing, power, validation, and final emission. No phase starts an unbudgeted retry.

One deterministic expansion budget covers every global and detailed search. Twenty-five percent is reserved for final detailed polish. The remaining discovery/search budget is first divided equally across candidate heights for their initial stages; after discovery, unused expansions return to the shared best-first pool. A validated incumbent does not need rerouting to be returned, so unused final reserve may be spent on quality mode.

If the wall deadline or expansion budget expires:

- return the best already detailed-routed and validator-clean incumbent;
- otherwise raise `NoValidLayout` with the existing distinction between deadline exhaustion and exhausted candidates.

Partial paths, global-routable candidates, unpowered candidates, and validator failures never escape.

## 16. Observability

Record in `Placement.stats` and audit output:

- backend and accelerator;
- seeds, heights, restarts, stages, accepted moves, and decoded candidates;
- global and detailed route counts;
- best global overflow and detailed stranded count;
- LNS invocation and neighbourhood sizes;
- feedback net/cell counts and decay stages;
- placement, preparation, global-route, detailed-route, validation, compilation, and total wall times;
- expansion-budget consumption by phase;
- cache hits;
- direct-insert candidates and realized inserts;
- exact area, belt tiles, power mode, solver termination cause, and validation status.

Stats are observational and cannot alter ordering or acceptance.

## 17. Verification

### 17.1 Unit contracts

- Every sequence-pair relative-order case decodes correctly.
- Decoded rectangles never overlap.
- Gap changes preserve non-overlap and coordinate conventions.
- Every move preserves both permutations.
- Targeted LNS preserves all locked relative orders.
- Fixed seeds and expansion budgets reproduce coordinates, scores, and diagnostics.
- Global routing matches detailed movement legality and hard obstacles.
- Compatible sharing and incompatible collisions are distinguished.
- Overflow and history update exactly.
- Stable `NetId` ownership survives preparation and both routers.
- Budget failures create no geometric feedback.
- Cell history resets across outlines; net history persists.
- Detailed-route reports preserve current route/commit behavior.
- Every orchestrator action charges the shared budget.
- Exact incumbents cannot be displaced by proxies.
- Python, Numba, JAX, and any native kernel have exact parity.

### 17.2 Behavioral verification

Run existing freeform contracts unchanged against both backends:

- direct insertion;
- proliferation and coater supply;
- fan-out, sharding, and mixed lanes;
- external-input accessibility;
- sorter reach/capacity;
- power coverage and connectivity;
- deterministic refusal;
- full `validate.certify()`.

Add focused fixtures for:

- the compact no-power sequence-pair success;
- the powered one-net miss;
- same-outline placements with different detailed outcomes;
- a blame wall selecting blocking strip endpoints;
- detailed feedback repairing a one-net miss without changing locked strips;
- a deadline failure that creates no placement penalty.

## 18. Promotion gate

Run the parallel backend over every URL corpus entry, every generated candidate, both power modes, configured time budgets, matched core allocation, and repeated fixed seeds.

Promotion requires:

- zero invalid outputs;
- no additional refusal in any matched cell;
- no worse per-cell median final area;
- no worse per-cell median belt count;
- a statistically stable geometric-mean wall-time improvement, with the bootstrap 95% upper confidence bound for `new/current` below 1.0;
- non-worse p95 wall time, CPU time, and peak RSS;
- accelerator cold-call compilation included in measured latency.

This is a strict Pareto gate: no fixed minimum speedup is required, but the improvement must exceed measured noise while every reliability and quality measure remains non-worse.

Promotion is a separate clean-cutover change after the evidence is recorded. Failure to pass leaves production on CP-SAT and produces measurements, not a partial rollout.

## 19. Risks and controls

### Proxy misranking

Control: detailed route every temperature-stage incumbent; exact incumbents only.

### Tight packs fail power or access

Control: shared preparation, hard power/access rejection, explicit gap genes, feedback-driven gap pressure.

### Detailed routing dominates every stage

Control: deterministic per-stage expansion slices, global elite screening, shared budget, final reserve. Measure before adding incremental routing.

### Feedback overfits one arrangement

Control: bounded weights, 0.85 stage decay, outline-scoped cell history, multi-height discovery.

### Sequence-pair misses direct insertion

Control: opportunity score, local alignment, exact belt-count gate, CP-SAT oracle.

### Accelerator semantic drift

Control: Python reference and exact parity fixtures; no approximate floating-point placement or routing decisions.

### Permanent duplicate solvers

Control: audit-only rollout and explicit post-gate removal from the production CP-SAT placement path.
