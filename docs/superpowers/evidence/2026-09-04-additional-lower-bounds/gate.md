# Additional solver lower-bound experiment results

## Exact case and method

All measurements used the exact URL:

`https://factoriolab.github.io/dsp/list?o=information-matrix*60&ibe=conveyor-belt-3&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11`

Configuration was `strategy="best"`, `time_budget_s=30`, `race=True`, `share=True`, and an aggregate `workers=16`. The canonical candidates were `no-proliferator`, `all-products`, and `output-products`; each raced Freeform and SequencePair. Candidate parallelism was 1 for the serial-candidate profile and 3 for the three-way profile. Raw records contain every progress event, attempt status/key, full placement stats, child CPU/RSS, candidate wall, configuration, URL, host, and commit.

Raw evidence:

- `experiment1-serial.json` at instrumentation commit `b51b6cb`
- `experiment1-three-way.json` at instrumentation commit `b51b6cb`
- `experiments2-4-three-way-audit.json` with audit prototypes at `d3e15d1`

The audit prototypes were subsequently reverted. No E2-E4 pruning or refusal path remains live.

## Experiment 1 — exact CPU and phase profile: STOP on preservation gate

Both baseline profiles produced all six expected attempts, all six were `CLEAN`, and neither had a refusal. The measured winners did not preserve a common key and did not reproduce the historical `(4176,2297)` key:

| mode | wall | summed child CPU | winner |
|---|---:|---:|---|
| serial candidates | 65.831 s | 90.992 s | all-products / SequencePair `(4453,2506)` |
| three-way candidates | 27.857 s | 97.700 s | all-products / SequencePair `(3960,2542)` |

Thus candidate concurrency overlapped work but did not establish CPU savings: wall fell 37.973 s while measured child CPU rose 6.709 s. The profile is useful, but the winner-preservation gate is not met.

Serial attempt evidence (wall, process CPU, peak RSS, dominant named phases):

| candidate / strategy | key | wall | CPU | peak RSS | named phases |
|---|---:|---:|---:|---:|---|
| no-proliferator / Freeform | `(8030,2983)` | 13.927 s | 3.811 s | 175.3 MiB | prep 1.723, detailed 0.715, finalize 0.841 s |
| no-proliferator / SequencePair | `(8030,2951)` | 13.908 s | 11.819 s | 195.1 MiB | prep 2.025, detailed 5.415, completion/validation 0.850 s |
| all-products / Freeform | `(5355,2869)` | 25.670 s | 11.448 s | 204.1 MiB | prep 7.233, detailed 1.092, finalize 2.334 s |
| all-products / SequencePair | `(4453,2506)` | 25.373 s | 23.303 s | 226.4 MiB | prep 14.232, global 2.094, detailed 0.992, completion/validation 1.961 s |
| output-products / Freeform | `(5856,2684)` | 25.046 s | 17.741 s | 204.7 MiB | prep 12.879, detailed 7.970, finalize 1.790 s |
| output-products / SequencePair | `(5394,2555)` | 25.094 s | 22.870 s | 251.4 MiB | prep 7.394, global 2.589, detailed 5.659, completion/validation 0.982 s |

The three-way record independently shows the same component gate: preparation exceeded one second in all six attempts; detailed routing exceeded one second in five attempts; SequencePair global routing exceeded one second in two attempts; Freeform finalization exceeded one second in all three attempts; and SequencePair completion/validation exceeded one second in one attempt. Freeform CP-SAT packing was only 0.186–0.532 s serial and 0.291–0.514 s three-way, below the component gate. Full CP deterministic time/status/objective/bound values are in the raw files. Pipeline compaction/finalization were zero because these placements arrived `COMPACTED_AND_FINALIZED`; pipeline validation and encoding are separately recorded. SequencePair's existing `validation_time_s` measures its atomic compact/finalize/certify adapter as one completion phase, so the record does not claim an internal split that was not observed.

Prepared-bound totals in the serial SequencePair attempts were 5/4/6 candidates, 0/1/0 hits, 0/1/0 skips, and zero accepted-placement violations. The three-way profile was 4/4/6 candidates, 0/1/0 hits, 0/1/0 skips, and zero violations.

## Experiment 2 — obstacle-aware prepared route floor: STOP

The audit-only graph retained immutable prepared occupancy, route bounds, levels, ramp run cells, reservations opened for relevant endpoint alternatives, and transitive sibling sharing; it ignored routed occupancy and inter-net conflicts. It was never used to prune.

| SequencePair candidate | helper wall excluding E4 separator scan | end-to-end share | detailed-route share | floor gain | extra hits | accepted violations |
|---|---:|---:|---:|---:|---:|---:|
| no-proliferator | 2.112 s | 6.51% | 169.29% | 43 | 0 | 0 |
| all-products | 2.709 s | 12.67% | 367.32% | 453 | 0 | 0 |
| output-products | 6.593 s | 25.97% | 144.26% | 130 | 0 | 0 |

This misses every promotion threshold: overhead is above 2% end-to-end and 10% of detailed routing, and additional hits cover 0% of detailed-route wall rather than at least 10%. Worse, the relaxation reported 2/3/5 disconnected prepared states even though the attempts emitted validator-clean placements. Those false disconnections show the prototype did not permissively model every legal sibling/junction endpoint evolution. It cannot support `STRANDED` or pruning. The prototype was reverted.

The audit run remained 6/6 `CLEAN` with no refusals, but its winner `(4453,2506)` differed from the three-way Experiment 1 winner `(3960,2542)`, independently failing winner preservation.

## Experiment 3 — incumbent rectangle feasibility: STOP

Only no-proliferator reached an eligible incumbent-improving rectangle audit. It enumerated 81 rectangles, found no permissively feasible rectangle, and produced one nominal additional area-dominance hit with zero observed accepted-placement violations. The audit consumed 23.434 s, or 72.25% of that attempt's 32.435 s wall, versus the required sub-percent overhead. The other two SequencePair attempts were ineligible against their incumbent when audited and tested zero rectangles. The sole hit is therefore not economically usable, and it also depended on the E2 connectivity model that produced false disconnections. The prototype was reverted.

## Experiment 4 — cheap separator certificates: STOP before ILP

The audit checked relaxed connectivity plus selected x/y and obstacle-boundary cuts across all three legal levels. Sibling-sharing nets were collapsed into transitive components before demand was counted; cut capacity counted passable cells across every level.

- selected cuts tested: 293 + 432 + 748 = **1,473**;
- overloaded cuts: **0**;
- separator scan wall: 0.127 + 0.157 + 0.278 = **0.562 s**;
- relaxed-connectivity false disconnections on accepted attempts: **2 + 3 + 5**.

The capacity relaxations always retained the candidates, while the connectivity arm was unsound for production because accepted layouts contradicted its disconnection result. No cheap certificate was observed before an expensive detailed call. Per the gate, no multi-commodity ILP was attempted and all E4 code was reverted.

## Experiment 5 — exact local CP-SAT outcomes: retain instrumentation; STOP memoization

`_pack_result` now returns a typed CP-SAT outcome carrying status, optional incumbent, objective value, best objective bound, wall time, deterministic time, and (for local windows) a SHA-256 fingerprint of the concrete serialized model text. `_pack_window` no longer collapses `INFEASIBLE`, `MODEL_INVALID`, or `UNKNOWN` into the same `None`. SequencePair and Freeform stats count each status and exact repeated fingerprints.

Across both exact Experiment 1 profiles, all six attempts reported **zero repeated identical local submodels and 0.000 s repeated-submodel wall**. The ≥1 s memoization gate therefore fails. No cache or pruning behavior was added. Best bounds remain scoped only to the exact encoded CP objective and are not claimed as finalized area or belt-count bounds.

## Retained mechanisms ranked by measured value

1. **Per-child resource and named phase instrumentation.** Highest value: it distinguishes the 37.973 s concurrency wall overlap from aggregate CPU, identifies preparation/routing/completion as the components passing the experiment-entry threshold, and records 175–251 MiB child peak RSS.
2. **Typed local CP-SAT outcome and fingerprint instrumentation.** Retained because it removes status ambiguity at negligible observed workload impact and directly falsified the memoization hypothesis (zero repeats). It does not alter acceptance or pruning.
3. **Existing Manhattan prepared lower bound.** Unchanged production behavior; it retained zero accepted violations and one real exact-case skip in each baseline mode. No stronger experimental path survived.

## Stopped mechanisms

- **Obstacle-aware prepared floor:** zero extra hits, excessive overhead, and false disconnection claims on accepted placements.
- **Incumbent rectangle feasibility:** one nominal hit at 72.25% attempt overhead and dependent on the failed connectivity model.
- **Cheap reachability/separators:** reachability contradicted accepted placements; 1,473 capacity cuts produced zero overloads.
- **Multi-commodity ILP:** deliberately not started because the cheap E4 gate failed.
- **Exact-window memoization:** zero repeated identical local submodels and zero repeated wall, below the 1 s gate.

No CP-SAT, graph, rectangle, or separator result in this evidence is claimed beyond the concrete prepared or encoded subproblem it audited.
