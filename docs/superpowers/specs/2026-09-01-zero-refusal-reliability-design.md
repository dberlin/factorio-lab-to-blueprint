# Zero-Refusal Solver Reliability Design

## Goal

Make every feasible request in the supported corpus produce an exact, detailed-routed, projection-legal, validator-clean blueprint while preserving honest refusal for impossible requests and preserving `(area, belt_tiles)` as the authoritative quality key.

The program targets three increasingly strong contracts:

1. A user requesting `best` receives a valid blueprint whenever either production strategy can solve the request within the configured reliability envelope.
2. Freeform and SequencePair each complete the 72-cell supported corpus under repeated production-concurrency audits.
3. A deterministic feasibility fallback handles supported instances that stochastic search still misses, at deliberately lower density.

“No refusal” never means emitting an invalid blueprint or claiming an impossible DSP area is feasible.

## Current Evidence

Measurements were taken on `master` at `f214b78` with powered emission and all three candidate policies:

| Run | Clean | Refused | Invalid | Crashed |
|---|---:|---:|---:|---:|
| Both strategies, 15 seconds | 63/72 | 9 | 0 | 0 |
| Freeform, 30 seconds | 36/36 | 0 | 0 | 0 |
| SequencePair, 30 seconds | 32/36 | 4 | 0 | 0 |
| SequencePair, 60 seconds | 34/36 | 2 | 0 | 0 |
| SequencePair quantum-chip/no-proliferator, 120 seconds | 1/1, in 97 seconds | 0 | 0 | 0 |
| SequencePair graphene/output-products, 120 seconds | 0/1, terminated in 2.7 seconds | 1 | 0 | 0 |

The two remaining SequencePair mechanisms differ:

- `quantum-chip/no-proliferator` is genuinely time-bound; 60 seconds refuses and 120 seconds succeeds.
- `graphene/output-products` is stage-bound; it exhausts the fixed schedule in 2.7 seconds regardless of a 60- or 120-second wall.

Longer time alone is therefore necessary but insufficient.

## Non-Negotiable Invariants

- `finalize.finalize_placement` remains authoritative for spherical projection and legal DSP bands.
- `validate.validate` and `validate.certify` remain authoritative for mechanical, flow, power, and stable-link correctness.
- Only an exact detailed-routed and validator-clean placement is a success.
- Safe refusal remains preferable to invalid output.
- Freeform and SequencePair remain distinct complete production strategies.
- Existing stable `NetId`, `NetFailure`, `FeedbackState`, `ExactPackNoGood`, `StageObservation`, and archive models are reused; no parallel failure vocabulary is introduced.
- Exact winner ordering remains `(area, belt_tiles)`. Feasibility metrics only rank candidates while no exact incumbent exists.
- Explicit `max_stages` remains a hard deterministic cap for tests and diagnostic probes.
- Search seeds and operator selection remain replayable.
- PyTorch, PyTorch Geometric, and other training dependencies do not enter the production package during the classical reliability phases.
- The user’s existing `--budget` remains an explicit per-layout upper bound. The default may rise only after the repeated corpus gate passes.

## Architecture

### Feasibility-first SequencePair continuation

`SequenceSolver.search(max_stages=None)` currently derives a finite stage limit from `config.stages × config.restarts_per_height × heights`. When that schedule ends without an incumbent, it returns `no scheduled stage produced an exact layout` even if most of the deadline remains.

Change only the implicit production path:

- `max_stages is not None`: preserve the exact existing hard cap.
- `max_stages is None` and no exact incumbent exists: when every current restart has consumed its configured stages, append one deterministic feasibility restart per height and continue while stage admission, the expansion ledger, and the wall deadline allow it.
- New restart seeds derive from `(config.seed, height, restart ordinal)` and never depend on completion order.
- A continuation restart begins from the best available route-feedback or archive state for its height; otherwise it uses the original anneal seed.
- Once an exact incumbent exists, existing quality/stability termination rules apply. Continuation does not buy unbounded density optimization.

The production result records `feasibility_restart_batches` and `termination` in observational stats.

### Reliability budgets

The first behavioral default change is conservative:

- Raise CLI and web default per-layout budget from 15 to 30 seconds only after the repeated 30-second Freeform gate is green.
- Do not set a universal 120-second default.
- Expose the existing SequencePair island count to `best` and the web API. Default web/`best` reliability remains one island until equal-CPU measurements approve four.
- Preserve explicit strategy behavior: an explicit `--budget 120 --strategy sequence-pair` grants the complete 120-second search envelope.

The pipeline continues evaluating requested candidate/strategy pairs so the candidate table remains complete. A later latency optimization may stream the first valid attempt, but that is not part of this reliability program.

### Production-concurrency islands

`SequencePairLayout` and `sequence_islands.run_sequence_islands` remain the one island implementation. Extend the audit so it can measure the same island count used by CLI/web.

Island evaluation must compare:

- equal wall time,
- equal total CPU budget,
- refusal rate,
- p50/p95 wall time,
- exact `(area, belt_tiles)`.

Four islands become the `best`/web default only if they reduce repeated refusals without losing the equal-CPU comparison or introducing invalid output.

### Classical ALNS

SequencePair already has LNS neighborhoods, routing-feedback substitution, archives, and detailed stage observations. Add a focused module rather than growing `sequence_solver.py` further:

`src/flab2bp/layout/sequence_alns.py` owns:

- operator identities,
- immutable operator context and outcome records,
- deterministic selection,
- discounted reward accounting,
- operator-scale selection.

The initial operator portfolio is fixed and evidence-backed.

Destroy operators:

1. `FAILED_ENDPOINTS`: strips incident to failed-net endpoints.
2. `BLOCKER_COMPONENT`: failed nets plus strips named by blocking nets.
3. `CONGESTED_CUT`: strips touching the hottest failed routing wall/cut.
4. `RELATED_CARGO`: strips sharing cargo, spray domain, or direct-insertion dependencies.
5. `BAND_BOUNDARY`: strips contributing most to overflow or the narrowest legal band boundary.
6. `DIVERSIFY`: deterministic pseudo-random related neighborhood.

Repair operators:

1. `ROUTING_REGRET`: reinsert by regret in incremental global-route congestion.
2. `SEQUENCE_REINSERT`: sequence-pair reinsertion using the existing energy model.
3. `LOCAL_EXACT_PACK`: local CP-SAT repack inside the destroyed envelope.

The selector begins as a deterministic discounted-UCB policy. It receives an `OperatorContext` containing strip/net counts, spray and direct-insertion density, failed-net class counts, blocker count, objective mode, remaining budget fraction, and neighborhood scale. It emits an `OperatorChoice` and later observes an `OperatorOutcome`.

Reward is lexicographic, not a scalar trade that can exchange validity for area:

1. exact validator-clean placement,
2. reduction in failed-net count,
3. reduction in projection/band overflow,
4. reduction in stranded/congestion measures,
5. exact area/belt improvement after feasibility.

Within one lexicographic rank, divide improvement by measured detailed-routing seconds before updating operator credit.

### Generalized pack-routing cuts

Exact assignment no-goods remain valid but are often too narrow. Add generalized evidence only when the detailed router proves the relation independently of unrelated geometry:

- endpoint-face separation,
- blocker-component relocation,
- corridor reservation across a failed cut,
- relative-order exclusion for a conflicting strip subset,
- height/topology exclusion when the same owned failure repeats across independent restarts.

Unproved relations remain scoped to the exact assignment. Budget failures never create geometry cuts.

### Deterministic feasibility fallback

A hard guarantee requires a separately testable feasibility constructor. It is not mixed into ALNS.

The fallback design spike must prove a canonical corridor template against the supported corpus before production implementation:

- widest legal portable band,
- canonical strip ordering,
- explicit trunk and crossing corridors reserved before placement,
- routing tracks/levels assigned before detailed emission,
- existing emitters, finalizer, and validator retained.

The spike succeeds only if every supported corpus spec fits a legal area and certifies. If any feasible corpus spec cannot fit the one-area template, the next design must choose between a stronger local exact track assignment and multiple blueprint areas; the fallback must not ship partially.

### Learned guidance gate

Learning is guidance for classical search, never an acceptance authority.

Data is collected from classical ALNS first. Each JSONL observation contains:

- stable instance fingerprint and held-out family,
- `OperatorContext`,
- selected operator pair and scale,
- detailed-route wall/expansion cost,
- lexicographic before/after outcome,
- exact/invalid/refused terminal state,
- deterministic seed.

Evaluation order:

1. static best operator,
2. classical discounted UCB,
3. supervised tree/MLP operator ranking outside production dependencies,
4. contextual bandit,
5. GNN operator selector,
6. RL fine-tuning.

A learned selector may enter production only if it beats classical ALNS on held-out recipe families and sizes by at least one of:

- 50% fewer refusals at equal wall and CPU,
- 25% lower p95 wall time at equal refusal count,
- 25% lower total CPU at equal refusal count and p95 wall.

It must produce zero invalid outputs, and disabling the model must restore deterministic classical ALNS without changing request or result schemas.

## Public Interfaces

- `SequenceSolver.search(*, max_stages: int | None = None) -> SequenceSearchResult` retains its signature.
- `SequencePairLayout(..., islands: int = 1)` retains its signature.
- `pipeline.build(..., sequence_islands: int = 1)` retains its signature but permits islands for `strategy="best"` as well as explicit SequencePair.
- CLI `--sequence-islands N` permits `best` and `sequence-pair`, range 1–16.
- Web `BuildOptions` adds `sequence_islands: number` with integer range 1–16 and default 1 until the island gate approves another value.
- `scripts/audit.py` adds `--sequence-islands N`, default 1, and records it in every JSONL row.

Classical ALNS introduces internal interfaces:

```python
class DestroyOperator(StrEnum): ...


class RepairOperator(StrEnum): ...


@dataclass(frozen=True, slots=True)
class OperatorContext: ...


@dataclass(frozen=True, slots=True)
class OperatorChoice:
    destroy: DestroyOperator
    repair: RepairOperator
    scale: int


@dataclass(frozen=True, slots=True)
class OperatorOutcome: ...


class AdaptiveOperatorSelector:
    def select(self, context: OperatorContext) -> OperatorChoice: ...
    def observe(
        self,
        context: OperatorContext,
        choice: OperatorChoice,
        outcome: OperatorOutcome,
    ) -> None: ...
```

## Verification Gates

### Stage-continuation gate

- Deterministic unit tests prove implicit production search extends exhausted restarts while explicit `max_stages` does not.
- `graphene/output-products`, SequencePair, one island, budget 120: clean in three consecutive serial runs.
- No invalid output.

### Budget gate

- Freeform at 30 seconds: 36/36 clean in ten complete repetitions.
- Full 72-cell audit at production concurrency: 720/720 clean before changing the default from 15 to 30.
- Record p50/p95 wall and completion tails.

### SequencePair gate

- Previously refusing SequencePair cells each pass 20 serial repetitions at budget 120.
- Full 36-cell SequencePair audit passes ten repetitions with zero refusals, invalids, or crashes.
- Compare one and four islands at equal wall and equal total CPU.

### ALNS gate

- Paired baseline and ALNS runs use identical specs, seeds, wall ceilings, and CPU affinity.
- Zero invalid output.
- ALNS must reduce refusals or p95 wall under the learned-guidance thresholds before replacing the fixed selector.
- Area regression is reported separately and may not hide feasibility regression.

### Final repository gate

- Full Python suite.
- Ruff.
- Mypy compared to the locked baseline; no new diagnostic.
- Package build including the Cython sequence kernel.
- Frozen web install, lint, TypeScript typecheck, full web tests, and production build.
- Live CLI and browser smoke for the reliable path.
- Whole-branch review before landing.

## Delivery Order

1. Capture and codify the 15/30/60/120 evidence.
2. Continue implicit SequencePair feasibility schedules to the deadline.
3. Add audit and web island controls; measure one versus four islands.
4. Run repeated gates and only then raise the default budget to 30 seconds.
5. Add the classical ALNS operator model and fixed portfolio.
6. Add generalized, proof-scoped routing cuts.
7. Re-run repeated reliability and quality gates.
8. Complete the deterministic fallback design spike and implement it only if the template proves complete for the supported corpus.
9. Collect ALNS training data and evaluate supervised/contextual guidance.
10. Attempt GNN/RL only after the classical and supervised gates justify it.

## Research Basis

- Liu, Lyu, and Fang, “Integrated packing and routing: A model and its solutions,” *Computers & Operations Research* 172 (2024), 106790. The transferable result is integrated decision-making and ANN algorithm selection, not its vehicle/pallet formulation.
- Johnn et al., “A Graph Reinforcement Learning Framework for Neural Adaptive Large Neighbourhood Search,” *Computers & Operations Research* 172 (2024), 106791. This is the directly relevant GNN operator-selection architecture.
- Hottung and Tierney, “Neural Large Neighborhood Search for the Capacitated Vehicle Routing Problem,” arXiv:1911.09539. The neural policy guides LNS rather than replacing exact acceptance.
- Xin et al., “NeuroLKH,” arXiv:2110.07983. Learned edge guidance improves a strong classical heuristic.
- Reijnen et al., “Online Control of Adaptive Large Neighborhood Search using Deep Reinforcement Learning,” arXiv:2211.00759. RL controls operators and acceptance within ALNS.
