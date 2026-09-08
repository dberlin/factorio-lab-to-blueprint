# Task1 implementation handoff

Status: implementation and consumer regressions staged; Main-owned green/smoke and independent review pending. No commands, tests, builds, lint, formatting or VCS operations were run by this worker.

## Contract and edits

- `src/flab2bp/lab/url.py:_parse_objectives` now applies the default `Fraction(1)` only when `parse_rational` returns `None`. Explicit zero survives every objective type.
- `src/flab2bp/lab/params.py:parse_rational` inspected and intentionally unchanged: its optional exact-Fraction contract already distinguishes missing from zero.
- `src/flab2bp/rates/solve.py:supplied_rates` documentation corrected: an explicit zero is now reachable from a URL. No supply-domain behavior changed. In particular, its legacy nonpositive-input semantics were not reinterpreted.
- No global truthiness sweep, numeric wrapper or deferred override/alias change.

## Staged consumer regressions

- `tests/lab/test_url.py::TestObjectiveFields::test_explicit_zero_is_not_a_missing_value`: bare/compressed Output, Input, Maximize and Limit retain zero and objective type.
- Existing absent/trailing-field case renamed `test_missing_value_defaults_when_trailing_fields_stripped` so the required focused selector includes the independent missing-value boundary.
- `tests/rates/test_solve.py::test_parsed_zero_limit_reaches_rate_constraint`: bare/compressed ordinary gear output plus iron-ingot Items Limit=0 reaches the real solve, retains output, forbids iron-ingot boundary input.
- `test_parsed_zero_output_and_input_do_not_become_positive_rates`: actual parser to exact rate maps.
- `test_parsed_zero_maximize_is_refused_by_rate_domain`: codec retains unsupported mode; rate domain refuses it.

## Evidence and exact commands

Red: retained Main `zero-objective-probe.log` already demonstrated zero becoming one. It was not rerun by this worker.

Main green command (worktree root):

```sh
uv run pytest -q tests/lab/test_url.py tests/rates/test_solve.py -k 'zero or limit or missing' --tb=short
```

Real parse-to-rate smoke remains Main-owned; the staged `test_parsed_zero_limit_reaches_rate_constraint` exercises that complete consumer path for both URL encodings, but no execution/pass is claimed here.

## Inventory and intentional nonchanges

The only lossy conversion repaired was `_parse_objectives`' `parse_rational(...) or Fraction(1)`. `Objective`, `LabRequest`, URL encoding helpers and rate-domain refusal/constraint algorithms keep their interfaces. `target_rates`, `supplied_rates`, `forbidden_inputs`/`RateSolution.forbidden_inputs` are the affected consumer boundaries. Exact arithmetic and economic machine-size costs remain unchanged.

Pending: Main green/runtime smoke, independent review, any resulting fixes and Main-owned integration/commit.

## Independent review fix round1: completed boundary enforcement

Review traced an auxiliary-demand gap exposed by preserving parsed Limit=0: `solve` checked forbidden items while assembling recipe-input shortfalls, then appended spray consumption afterward. An ALL_PRODUCTS candidate could therefore require an input that the exact request prohibited.

Before source changes, two real parse-to-candidate cases were staged in `tests/rates/test_candidates.py`. Main executed them and retained `zero-spray-red.log`: `test_parsed_zero_limit_refuses_required_spray_input` failed because the forbidden-spray candidate did not raise; `test_parsed_zero_limit_allows_a_policy_without_the_forbidden_input` passed. The first case also exercises an ordinary unlimited ALL_PRODUCTS candidate to establish that spray demand is actually positive. The second admits the same limited request under NO_PROLIFERATOR and asserts actual ore-input/output rates.

After Main's red confirmation, `src/flab2bp/rates/solve.py` moved the forbidden-item gate to the completed `external_inputs` map, after all demand sources have contributed, and removed the earlier incomplete duplicate gate. It rejects any forbidden positive external demand, regardless of source. There is no proliferator-ID special case, policy fallback, suppressed exception or validator bypass. Exact Fraction/positive-demand semantics and all physical-identity edits remain unchanged. The new regression asserts the typed refusal, not error-message wording.

Exact Main proof command from the worktree:

```sh
uv run pytest -q tests/rates/test_candidates.py tests/rates/test_solve.py -k 'parsed_zero_limit or zero_limit' --tb=short
```

Round1 source/test writes are settled. Main green and independent re-review remain pending; this worker ran no validation.
