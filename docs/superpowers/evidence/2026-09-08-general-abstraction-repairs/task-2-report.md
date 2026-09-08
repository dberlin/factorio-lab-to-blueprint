# Task2 implementation handoff

Status: confirmed baseline defect repaired in source; green/smoke and independent review remain Main-owned. This worker ran no validation or VCS commands.

## Boundary inventory and owner

- `pipeline.build` resolves/canonicalizes the request, pins an optional Flow, then builds candidates.
- Candidate admission previously included `frozenset(supplied_rates(data, request))` and the conditional existing external-proliferator allowance.
- Final selected-spec admission reconstructed only proliferator exemptions, losing declared Inputs. A partly supplied intermediate still crafted by Flow is not represented in `FlowSelection.external_items`.
- `lab.flow.unsupplied_inputs` already accepts an explicit immutable exemption set and optional precomputed Flow external map; it needs no new policy owner or implementation change.
- `rates.solve.supplied_rates` remains the declared-supply authority. Flow retains ownership of its external items.
- Fresh LSP references for `pipeline.build` failed with `-32603: this._token.cancel is not a function`; scoped fallback inventoried callers in CLI, web/jobs, pipeline/CLI/web/bench tests, trace_overhead and the existing internal uses. The build signature is unchanged, so those callers need no migration.

## Completed source edits

`src/flab2bp/pipeline.py` computes `authorized_extra_inputs = frozenset(request_supplies) | proliferator_allowance` once for a pinned flow and passes that identical immutable value to both admission calls. The no-flow path keeps its existing lack of Flow restrictions. The proliferator branch retains its existing conditional allowance; ordinary candidate requirements do not authorize themselves. Deleted the obsolete final selected-spec exemption construction and corrected its policy comment.

## Staged regression cases

- `tests/test_pipeline.py::test_partial_supplied_intermediate_is_admitted_through_build`: real two-machine gear build, 60/min output, 30/min declared iron-ingot supply, 30/min crafted remainder. Asserts actual BuildSpec input rates, recipe counts, output and pin result.
- Fixture derives the existing exact partial-intermediate netting case in `tests/rates/test_solve.py`; a compact CSV uses the same ordinary gear/iron-smelting chain with exact rates and explicit machine IDs.
- `test_undeclared_input_is_refused_despite_a_declared_partial_supply`: injects a stray stone belt into otherwise real candidate generation and observes the real admission refusal. Candidate injection now uses the existing Pydantic `model_copy` convention.
- `test_proliferator_input_admission_preserves_flow_policy`: real one-smelter build in no-flow, unsprayed-flow and sprayed-flow modes; preserves the intentional external-proliferator asymmetry.
- `tests/lab/test_flow.py::TestBoundaryRule::test_partial_supplied_crafted_item_does_not_authorize_a_stray_input`: existing pristine Flow fixture; an explicit crafted-item exemption removes only that boundary mismatch, leaving stone refused.

## Retained baseline and commands

Main reported `request-identity-red.log`: the real partial-supply build reaches final admission and fails at old `pipeline.py:1454` with `FlowError` naming iron-ingot. This is the intended production red.

The initial undeclared companion hit a test-setup `TypeError` because `dataclasses.replace` was used on Pydantic BuildSpec. That setup failure is retained separately, not counted as production red; the companion was corrected to `model_copy` during Main's explicitly permitted correction window.

Main focused command from worktree root:

```sh
uv run pytest -q tests/test_pipeline.py tests/lab/test_flow.py -k 'suppl or input or proliferator' --tb=short
```

The real-build case above is the small admission smoke target; no mocked layout substitutes for its outcome. Green, final actual Build outcome, independent review and integration/commit remain pending Main execution.
