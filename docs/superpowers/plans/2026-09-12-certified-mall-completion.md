# Certified Mall Completion Implementation Plan

> **For agentic workers:** Use `executing-plans` for the serial measurement/repair loop; use `subagent-driven-development` only for genuinely independent implementation slices. Main owns integration and timed verification. Checkbox completion is progress, not permission to stop before the acceptance gate.

**Goal:** Make both original mall requests emit complete certified factories under their unchanged allowances, with hierarchy also producing a valid result in every scheduled portfolio race.

**Architecture:** Continue from the merged production geometric-routing implementation. Establish a fresh whole-CLI baseline, repair its first demonstrated failing boundary, and repeat the complete fixed acceptance matrix after each causal change. Preserve the factored allocator as experimental evidence; neither a solved allocation model nor a locally connected layout substitutes for a certified factory.

**Tech Stack:** Python 3.14, existing Cython routing kernels, existing solver backends, pytest, Ruff, mypy, SHA-256-bound local evidence.

**Spec:** The acceptance contract below carries the user's original mall requirements and latest instruction to continue through completion. It supersedes the intermediate stopping language in `2026-09-10-hierarchy-critical-path.md` and `~/report.md`, not their physical or resource constraints. The authoritative retained command matrix is `.local-evidence/2026-09-12-portfolio-repairs/pre-redesign/comparison-final/plan.json`.

## Global Constraints

- Original CLI URL, recipe policy, 60-second budget, 32-worker request, case affinity, strategy and exact machine rank remain unchanged for acceptance.
- Do not add retries, pool capacity, solver budget, expansion allowances, recut limits or finalization grace; do not disable certification checks.
- Search allowance is not total process wall time. Record startup, search, settlement/certification and encoding separately without moving work outside its existing clock. The 150-second external watchdog is not a search allowance.
- Preserve exact rates, recipe/machine obligations, external inputs/outputs, researched belt policy, portable band, collision rules, ownership and link semantics.
- A deadline is a deadline, not proof of geometric impossibility. Keep genuine pre-deadline witnesses and spent-work accounting.
- Never reuse a report or certificate across changed placement, ownership, links, request/spec or policy. Full settlement remains mandatory.
- Feasibility first. Approximately 15 seconds is a desired fast-feasible milestone, not the original acceptance ceiling. The user's density preference is roughly 30 seconds for twice the density, not 120 seconds for a 5% gain; do not invent a fixed exchange rate.
- Python 3.14 is authoritative. Reuse existing concrete domain contracts; no new `Any`, unchecked casts, type ignores or redundant public abstraction.
- Run timed cases serially without concurrent tests/builds/benchmarks. Bound aggregate solver workers, not merely the number of pool objects. Process samples include coordinators and must not be equated blindly with solver-worker counts.
- Do not change `diff.external`, discard user work, delete retained evidence, or restore old source overlays. No push is authorized by this plan.
- Continue across hotspot and phase boundaries. Ask only if a genuinely necessary action would change the user's constraints; do not ask again whether an exposed in-scope bottleneck should be fixed.

## Integration checkpoint

Production repair commit `662cbf3f` was merged with master through `cc8ee6e9`, then root master was fast-forwarded to **`718d601a11299b0f1f89bc59e5e587bb71b716bd`**. All merges were conflict-free. The 22-file repair includes portfolio completion/provenance, hierarchy funding, routing admissibility and exact projected-power indexing. Experimental allocator code was not promoted.

Verification at this checkpoint:

- Native extension build succeeded before the final Python-only master merge.
- Ruff formatting/checks pass on all 20 changed Python files; mypy passes on all 10 changed production modules.
- Full serial run: **4,553 passed, one failed, 938.18 seconds**. The failure is the optional live-browser capture's 120-second timeout. The invocation mistakenly set `FLAB2BP_NETWORK_TESTS=0`; this nonempty string enabled the network tests. All non-network tests passed. This is not a clean full-suite exit.
- With that variable unset, both opt-in network tests skip as intended: exit 0, two skipped. No source/test suppression was introduced.
- Earlier combined source/test typing had 141 errors versus then-master's 150, with no new normalized error messages. This is inherited test-typing debt, not a whole-project typing pass.
- Two independent static reviews found no actionable patch-introduced defects in the portfolio/pipeline and geometry/bounds/power scopes.
- Logs and review JSON are in `.claude/worktrees/technology-routing/.superpowers/master-integration/`. Existing evidence, worktree, backups and safety stash remain retained.

**No fresh original-request acceptance matrix has run on this integrated snapshot.** That is Task 1, not an inferred pass from regression tests.

## Evidence and decision

Evidence root: `.local-evidence/2026-09-12-portfolio-repairs/`.

| Evidence | Observed result | Decision supported |
|---|---|---|
| `pre-redesign/comparison-final/` | Earlier full CLI matrix: 7/8 valid; hierarchy valid in 3/4 races | Completion was not achieved; isolated passing commands are insufficient |
| `factored-allocation-spike/summary.json` | Rebased geometric control 6/6 valid on three frozen compositions; allocator 0/6 | Production geometry is the stronger current path; frozen inputs do not prove fresh CLI behavior |
| Same archive, larger no-proliferator models | Expire in preparation before a native solve | A final-projection-only optimization cannot close every allocator failure |
| `emitter-contract-repair/summary.json` | Real canvas bound omitted; 385 offending cells, no other clearance cause; bounds repaired | Keep the reusable correctness repair, independently of allocator promotion |
| `power-infill-index/summary.json` | Same 63,745-building input and 36 ordered tower sites: 35.770 to 7.061 seconds | Exact power reuse is useful; isolated 5.07x speedup is not factory completion |
| Same archive, final matched trials | Control 2/2 valid at 14.603/13.802 seconds, area 38,958; allocator 0/2 at 46.472 seconds, deadline during projection after 134/134 flows | Do not turn connectivity or raw area into a successful factory claim |

Master has meanwhile added canonical projected-belt reuse (`4af74ac4`), canonical link emission (`656915f1`), reservation-preserving repair (`d72dcd82`) and bounded lazy alternatives (`cc8ee6e9`), alongside earlier geometry/cache improvements. **The old projection profile is stale for the integrated implementation.** Do not implement another cache merely because it was the last observed hotspot before integration.

Selected direction: production-first, measured critical-path repair. Keep the allocator archives and its unmet certification/scaling gates visible; do not spend the main completion effort trying to vindicate that experiment. If production already passes the full gate, deliver those factories rather than requiring a new architecture for its own sake.

## Acceptance contract

One source-immutable matrix contains these eight runs, in this order:

1. `mall-all-r1-hierarchical`
2. `mall-all-r1-best`
3. `mall-all-r2-best`
4. `mall-all-r2-hierarchical`
5. `mall-none-r1-hierarchical`
6. `mall-none-r1-best`
7. `mall-none-r2-best`
8. `mall-none-r2-hierarchical`

Both cases use this exact URL:

```text
https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf.NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11
```

Common CLI options: `--budget 60 --band portable --workers 32 --machine-rank exact -v`. Use `--candidate-policy all-products` for `mall-all`, `no-proliferator` for `mall-none`; `--strategy hierarchical` or `--strategy best --race` according to the matrix.

- All-products affinity: `1,5,9,13,17,21,25,29,33,37,41,45,49,53,57,61,65,69,73,77,81,85,89,93,97,101,105,109,113,117,121,125`.
- No-proliferator affinity: `2,6,10,14,18,22,26,30,34,38,42,46,50,54,58,62,66,70,74,78,82,86,90,94,98,102,106,110,114,118,122,126`.
- Environment: current source `PYTHONPATH`, `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`, `FLAB2BP_COATER_NODE=placed`, `FLAB2BP_DIAGNOSTIC_SKIP_SHARED_FLOW=0`; unset `FLAB2BP_GEOMETRIC` and `FLAB2BP_GEOMETRIC_TRACE`.
- Watchdog 150 seconds, cleanup observation 5 seconds, process sampling 0.5 seconds; none adds solver time.

**Pass only when all eight CLI runs succeed and emit nonempty, exactly round-trippable payloads, with full production judgment and unchanged exact request obligations; hierarchy must also be valid in all four races.** A different portfolio winner cannot hide hierarchy's refusal. Do not require every other race arm to succeed unless its own contract requires that.

Every run must preserve source/native hashes, existing worker budgets and natural cleanup; watchdog or forced cleanup fails the gate. Record valid area, machines, buildings, first feasible time when available, total wall and refusal details. Invalid raw area is not an accepted density result. Keep every scheduled result, not just the best repeat.

## File and ownership map

| Boundary | Existing source owner | Existing regression scope |
|---|---|---|
| Block scheduling, funded rounds, cuts | `src/flab2bp/layout/hierarchy/strategy.py`: `HierarchicalLayout.lay_out`, `_solve_round`, `_pool_width`, `_RoundPlan` | `tests/layout/hierarchy/test_strategy.py` |
| Packing, global composition, settlement handoff | `src/flab2bp/layout/hierarchy/compose.py`: `pack_with_access`, `compose`, `_CompositionSettlement` | `tests/layout/hierarchy/test_compose.py` |
| Geometric routing, admission, repair workspace | `src/flab2bp/layout/routing_domain.py`; `src/flab2bp/layout/transport_routing/{paths,routing,solver}.py` | `tests/layout/test_transport_routing.py`, `tests/layout/test_transport_routing_spray.py`, `tests/layout/test_transport_power.py` |
| Power and exact final projection | `src/flab2bp/layout/finalize.py`: `prepare_placement_completion`, `_certify_frame`, `_ProjectionCache`, `_CleanupSurvivorGraph` | `tests/layout/test_finalize.py` |
| Portfolio funding, completion ownership, reports | `src/flab2bp/layout/strategy_race.py`; `src/flab2bp/pipeline.py`: `Build`, `Attempt`, `build` | `tests/layout/test_strategy_race.py`, `tests/test_pipeline.py`, `tests/test_pipeline_cli_strategy.py` |
| Independent final judgment | `src/flab2bp/layout/validate.py`: `judge_placement`, `id_map` | `tests/layout/test_validate.py` |

No production file is pre-authorized for a speculative rewrite. Main selects one causal owner from Task 2's witness. LSP references are required before exported-contract changes. Concurrent writers never share `routing_domain.py` or `finalize.py`; timed verification starts only after all writers finish.

## Task 1: Establish the integrated original-request baseline

**Files:** read the retained `pre-redesign/compare.py` and reference JSON; create only disposable `.superpowers/certified-mall-completion/compare.py` and its evidence directories. No production changes.

**Interfaces:** The retained runner consumes the original reference commands and writes `plan.json`, `source-manifest.json`, eight case directories with `cli.log`, `process-samples.json`, `result.json`, payloads, and aggregate `results.json`.

- [ ] Confirm current master ancestry and preserve any newer user commits. Build native extensions from the actual execution tree with `.venv/bin/python -B setup.py build_ext --inplace`; retain exit and log before timing anything.
- [ ] Restore the runner to its intended two-level staging depth. Do not execute it directly inside the archive: `ROOT = Path(__file__).resolve().parents[2]` would resolve incorrectly there.

```python
from pathlib import Path
import shutil

root = Path.cwd()
archive = root / '.local-evidence/2026-09-12-portfolio-repairs/pre-redesign'
stage = root / '.superpowers/certified-mall-completion'
stage.mkdir(exist_ok=True)
runner = stage / 'compare.py'
assert not runner.exists(), 'preserve any existing staged runner before reuse'
shutil.copy2(archive / 'compare.py', runner)
assert runner.resolve().parents[2] == root.resolve()
```

- [ ] Run the complete uninstrumented matrix through a supervised process with persistent output:

```text
.venv/bin/python -B .superpowers/certified-mall-completion/compare.py integrated-baseline
```

Expected readiness: `READY: fixed 8-run matrix`. Expected end: all eight scheduled rows retained, even if some CLI cases fail. Runner exit alone is not acceptance; inspect each row and race attempt table.

- [ ] Compare each generated command against the authoritative matrix after normalizing only executable/source and output paths. Check the fixed environment, workers, affinity, policy, band, rank and original budget.
- [ ] Summarize all eight rows and hierarchy's four race outcomes. The runner verifies emitted payload roundtrips but does not independently rejudge captured `Build` objects; do not claim that additional check yet.

**Gate:** A trustworthy current baseline and a concrete list of failed acceptance clauses. If none fail, go directly to Task 4's independent audit. Otherwise continue immediately to Task 2.

## Task 2: Capture the first causal production failure

**Files:** disposable copies of `pre-redesign/composition_probe.py` and `settlement_cost_probe.py` in the same stage; read only the source boundary implicated by the baseline.

**Interfaces:** The composition probe captures real composition arguments, available deadline, packed geometry, rounds and routing outcomes. The settlement probe adds phase durations and a finalizer profile. These diagnostics are not acceptance runs.

- [ ] Select the earliest failing matrix row. Preserve its complete CLI log, source/native manifest, original command and genuine refusal/deadline evidence before running a diagnostic.
- [ ] For a hierarchy failure, adapt the disposable probe's case selection to that exact row. Preserve `workers=32`; remove the optional `_BLOCK_WORKERS` override from the disposable copy rather than using it. Recheck current function signatures before installing wrappers.
- [ ] First collect monotonic phase boundaries without cProfile: block rounds, `pack_with_access`, `_route_all`, power planning, `prepare_placement_completion`, final judgment/encoding. Record nested spans so cumulative timings are not summed as exclusive work. Capture remaining time at each boundary; charge snapshot overhead to the original clock without compensation.
- [ ] Capture the exact failed input once, with its source/native identity and original remaining allowance. Use the existing hierarchy-specific runner; **do not use `scripts/route_profile.py --strategy hierarchical`**, whose current strategy dispatch falls through to SequencePair.
- [ ] Use cProfile only on the captured dominant phase if the coarse timing does not identify redundant work. Keep profiled cost separate from normal CLI latency. Do not replay a changed layout under an old report or substitute an old frozen composition for current request provenance.
- [ ] Classify the failure using this decision table and produce a repair packet containing the command, input hash, earliest witness, spent/remaining budgets, affected symbol and observable before/after criterion.

| Observation | Next action | Evidence required before changing code |
|---|---|---|
| Unsolved local blocks | Trace funded `_solve_round` offers, shared-shape fanout and useful cuts | Which required shape remained unsolved; work already spent; legal funded action delayed or lost |
| Global route refusal | Trace real canvas admission and repair ownership | Exact flow/rate, actual cells/links/owners and authoritative failed predicate; distinguish work cap from contradiction |
| Deadline after all routes connect | Measure preparation, infill, projection and judgment on the current source | Exact completed obligations, remaining clock, dominant exclusive work, repeated identical inputs if reuse is proposed |
| Standalone passes but race hierarchy fails | Compare allocated workers, absolute deadlines and completion/report ownership | Actual funded share and dispatch/settlement transitions, not just wall-time differences |
| Payload/report/codec disagreement | Trace `Build`/`Attempt` ownership through parent consumption | Exact request, placement identity, report policy and payload responsible for disagreement |
| Watchdog or worker leak | Trace cancellation and process ownership | Owned process group, worker accounting and missing lifecycle transition |

**Gate:** One causal repair packet, not a list of guessed optimizations. If the latest profile disproves the old hypothesis, discard that hypothesis and follow the observed boundary without seeking a new scope approval.

## Task 3: Repair that boundary and prove the effect

**Files:** only the causal source owner and existing regression scope in the ownership map; update affected callers together. The packet fixes the exact symbol and test node before edits begin.

**Interfaces:** Preserve existing `Placement`/`BuildSpec`/request-policy contracts and existing completion/refusal types. The intended change is a real legal completion becoming reachable under the same allowance, or removal of demonstrated duplicate work with identical physical decisions.

- [ ] Reduce a physical or lifecycle defect to a deterministic behavioral regression: a bound-violating route must be rejected; a changed owner/link/policy must invalidate prior proof; cancellation must not publish partial success; a funded required result must not disappear. Reproduce the captured defect on the pre-change source. For pure performance work, prefer a throwaway exact-input equivalence replay over a permanent wall-time threshold test.
- [ ] State the concrete failing assertion and expected corrected behavior in the repair packet, then implement the smallest source correction. Do not add new search retries/capacity, silently shrink the request, or skip finalization to obtain a pass.
- [ ] For an exact cache/index change, bind keys to every authoritative input; preserve predicate ordering where observable, boundary behavior, cancellation and invalidation. Exercise changed geometry, rotation/latitude, ownership or policy as applicable. No generic cross-build cache without measured necessity and a complete invalidation contract.
- [ ] Run the packet's exact reproduction, then the relevant existing test files from the ownership map. For a performance intervention, replay the identical input before/after under its captured allowance; compare physical decisions and full accepted output, not helper call counts alone.
- [ ] Rerun the entire fixed eight-case matrix under a new immutable label after the source change. Keep failures and compare every row; do not rerun unchanged source until favorable stochastic results replace bad ones.
- [ ] Review the change and its evidence, commit only the causal repair and justified regression, and update the report. If acceptance still fails, return immediately to Task 2 with the new failing boundary. A faster phase is not an end state.

**Gate:** The causal failure is corrected without lost legality or resource accounting; all remaining failures stay active. This task is a bounded-change loop, not a promise that one speculative optimization will solve every case.

## Task 4: Audit actual factories and finish the original goal

**Files:** disposable capture/audit scripts in the stage; read canonical `pipeline.Build`, `pipeline.Attempt`, `validate.judge_placement` and codec APIs. Update this plan and `~/report.md` with final evidence.

**Interfaces:** `Build` contains `spec`, `placement`, `report`, `strategy`, `blueprint`, `attempts`, `refused` and resolved `belt_rules`. Each `Attempt` has its own `spec`, `placement`, `report`, `blueprint`, strategy and candidate; never validate a losing attempt against the winner's spec.

- [ ] At the actual `cli.main` to `pipeline.build` boundary, preserve the returned canonical `Build` without changing its result or clock. Use a separate evidence run for this capture so serialization overhead is not hidden inside the uninstrumented timing matrix. Save and hash the exact emitted payload with it. If capture changes an outcome, retain that fact and do not attribute its placement to a different successful run.
- [ ] Independently judge each captured winner and hierarchy race attempt against its own exact spec and the original resolved belt rules. These original commands require power. The core audit is:

```python
from flab2bp.dsp.codec import build_payload, decode, encode_blueprint
from flab2bp.layout import validate
from flab2bp.pipeline import Build


def audit(build: Build) -> None:
    assert build.belt_rules is not None
    targets = [build, *(a for a in build.attempts if a.strategy == 'hierarchical')]
    for target in targets:
        report = validate.judge_placement(
            target.placement,
            target.spec,
            ids=validate.id_map(target.spec),
            belt_rules=build.belt_rules,
            expect_power=True,
        )
        assert report.ok, report.errors
        assert target.report.ok
        blueprint = decode(target.blueprint)
        assert build_payload(decode(encode_blueprint(blueprint))) == build_payload(blueprint)
```

This audit is deliberately not a replacement for checking required hierarchy-attempt presence, original request obligations, production finalization/projection completion, source identity and captured-payload equality. Compare each exact machine/recipe/rate/external contract against the original resolved request, not merely against another derived object from the same faulty path. Full judgment must retain every required check; unexpected skipped checks fail the audit.

- [ ] Retain complete payloads and audits for both policies, standalone hierarchy and hierarchy inside all four races. Validate required hierarchy presence explicitly; a missing target cannot pass through an empty loop.
- [ ] On the final source, run focused checks and then the full default **serial** suite with `FLAB2BP_NETWORK_TESTS` unset, not the string `0`. Preserve all output and exit codes. Optional live-site verification is reported separately; do not weaken it or claim it passed when it did not.

```text
env -u FLAB2BP_NETWORK_TESTS PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest
```

Run Ruff format/check and mypy on affected production files; compare any test-typing failures against the baseline rather than adding suppressions. Rebuild native code if changed, before the final matrix.

- [ ] Obtain independent correctness reviews of geometry/certification and scheduling/provenance changes. Apply any necessary corrections, then rerun affected proofs and the fixed final matrix on the resulting source.
- [ ] Archive source/native manifests, original commands, all matrix rows, captures, complete judgments, payloads, profiles, tests and review results under `.local-evidence/2026-09-12-certified-mall-completion/`; verify every copied digest before removing only disposable scripts created by this work. Preserve older archives and the recovery worktree/stash.
- [ ] Update user-facing documentation only for actual changed behavior. Record final commit, all eight statuses, hierarchy's four race results, worker/cleanup evidence, exact accepted areas and latency, and direct artifact paths in this plan and the report.

**Final stopping condition:** all original acceptance clauses are proved on the final source and usable certified blueprints are delivered. A merged patch, clean unit tests, faster power plan, solved model, 134 connected flows, one successful repeat or a completed plan task is not that condition.

## Reopening the allocator experiment

The allocator remains unintegrated and its certification goal remains unmet. Reopen it only after the production acceptance work, or if fresh causal evidence shows production cannot resolve the required failure within the unchanged policy and the allocator offers a concrete alternative. Before promotion it must complete all three frozen compositions at their original remaining allowances, preserve every exact obligation, pass real emission and full settlement/judgment, and then pass the original whole-CLI matrix. Compare accepted density and latency against current production; raw unvalidated area and model optimality do not qualify. No architecture is mandatory merely because effort has already been spent on it.
