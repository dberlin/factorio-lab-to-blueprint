# Task4 — required save-policy judgment

Status: complete four-consumer cutover implemented after Main reproduced the two benchmark omissions and released pipeline source following 361 request-domain cases plus five targeted pipeline admission cases. Main's equal-spec policy smoke passed all four seams (EXIT0); affected audit/bench/AB modules passed within Main's integrated run. Independent Tasks4/5 approval stands in AuditLifetimeScopedReview. The separate Task6 interrupted-result lifetime repair remains independently gated. This worker ran no validation, formatter, build, service, browser or VCS command.

## Contract and scope

`layout.validate.judge_placement(placement, spec, *, ids, belt_rules, expect_power) -> Report` now owns complete resolved save-policy adaptation. `validate` keeps its diagnostic defaults; `certify` and strategy completion remain deliberately unchanged for Task14.

`bench.runner.available_strategies` and `_run_cell` now require the complete rules; the benchmark builds one IdMap per candidate and reuses it for each strategy. Its obsolete private `_id_map` forwarding wrapper is removed. `ab_compare._LayoutCall` carries complete rules, and `judge_with` requires them. AB resolves rules per URL and IdMaps per candidate outside repeat/budget loops. Audit factories and `run_cell(job, *, belt_rules)` require the same resolved object. Job remains pre-result identity; the rules travel explicitly through executor submission. No optional policy fallback, second context owner or solver policy change was added.

Pipeline's existing final validation now calls the same required boundary with its already-resolved rules. Its request resolution, race construction, verdict and timing semantics remain unchanged.

Benchmark/audit keep their existing power-skip strictness. AB still rejects every skipped check. Timing, codec and completion scopes are intentionally unchanged.

## Main baseline evidence

- `task-4-policy-red-r2.log`: restricted production and audit reported `geom.altitude_range` and `geom.altitude_step`; bench/AB reported only the height failure. Unrestricted production and audit honored the URL, while bench/AB still incorrectly reported the default ceiling failure.
- The first direct probe lacked the worktree root in PYTHONPATH and failed importing `scripts`; Main retained it and reran with the correct environment.
- The original probe used an empty spec outside production, so production also reported an unrelated `spec.machine_counts`. The revised throwaway probe obtains the same real no-proliferator candidate for every seam. This is a probe-fixture correction, not a newly discovered production defect.
- Production already passed researched rules before this change. No new production-emission bug is claimed.

## Matching tests and inventory

`tests/test_audit.py::test_judges_reject_save_restricted_belt_geometry` compares real physical height and vertical-link findings through audit, benchmark and AB, retaining unrestricted controls and unrelated findings. Existing runner/AB/audit tests were migrated to required policy inputs. Superseded forwarding/default-only benchmark and audit factory tests were removed instead of re-pinned to new arguments.

LSP references were attempted for audit run_cell, benchmark available_strategies and AB judge_with; each failed with the known cancellation error, reported through report_issue. Scoped fallback inventory covered src/tests/scripts, including all audit direct workers, bench `_run_cell`, AB `_LayoutCall`/judge tests, and pipeline's final validation block.

## Exact Main proof commands

From abstraction-general:

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-4-policy-probe.py
uv run pytest -q tests/test_audit.py tests/bench/test_runner.py tests/scripts/test_audit.py tests/scripts/test_ab_compare.py --tb=short
uv run pytest -q tests/layout/test_validate.py -k 'altitude or vertical' --tb=short
```

Main confirmed the equal-spec four-seam policy probe EXIT0. Its integrated 351-case audit/trace run passed 350 cases; the sole failure was Task5's obsolete exact diagnostic wording assertion, removed without weakening the failing-verdict check, followed by 32 focused passing cases. No Task4 behavior failed that run. Main owns remaining real CLI smokes, integration-wide proof, throwaway removal and commit.

Actual CLI smoke commands (use new output paths; do not overwrite baseline evidence):

```sh
uv run python scripts/audit.py --only iron-ingot --strategy both --candidate-policy no-proliferator --budget 1 --jobs 2 --max-seconds 30 --json .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-4-audit-smoke.jsonl
uv run python scripts/ab_compare.py --only iron-ingot --tier trivial --candidate-policy no-proliferator --budget 1 --repeat 1 --json .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-4-ab-smoke.json
uv run python -m flab2bp.bench --time-budget 0.2 --candidate-policy no-proliferator
```

The benchmark CLI writes its existing bench/results outputs and intentionally includes all default tiers; its small budget may honestly refuse cells. Its legacy per-URL regression contract is deliberately not converted to Task5 exact-audit identity.
