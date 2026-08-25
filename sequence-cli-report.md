# Sequence-pair CLI capability report

## Scope

Expose the completed `SequencePairLayout` only as the explicit `sequence-pair` pipeline/CLI strategy. Keep the production `best` strategy restricted to `spine` and `freeform`; do not alias, replace, promote, or otherwise change either production backend.

## SDD evidence

RED was established with focused tests for these observable contracts:

- explicit `sequence-pair` resolves only to `sequence-pair`;
- `best` resolves exactly to `spine` and `freeform`;
- explicit construction returns `SequencePairLayout` and preserves the power choice;
- the CLI accepts and passes the exact `sequence-pair` name and `--no-power` value;
- CLI help identifies sequence-pair as an explicit experimental/audit backend and names the two `best` defaults.

Before implementation, all five tests failed because the strategy helper/constructor were absent, the parser rejected `sequence-pair`, and the help contract was absent. After implementation:

```text
uv run pytest -q tests/test_pipeline_cli_strategy.py
.....                                                                    [100%]
```

Touched-file static checks:

```text
uv run ruff check src/flab2bp/pipeline.py src/flab2bp/cli.py tests/test_pipeline_cli_strategy.py
All checks passed!

uv run mypy src/flab2bp/pipeline.py src/flab2bp/cli.py tests/test_pipeline_cli_strategy.py
Success: no issues found in 3 source files
```

## Real CLI smoke

The `iron-ingot` corpus URL was run through the actual console entry point with `--strategy sequence-pair --no-power` and the default layout budget. It exited 0 and reported:

```text
sequence-pair / no-proliferator: 1 machines, 30 tiles, 10 buildings
inputs to belt in: iron-ore  (1 marked with icons)
2 check(s) could not run: power.connectivity, power.coverage
```

The emitted stdout was decoded with `flab2bp.dsp.codec.decode`:

```text
hash_valid=True buildings=10 areas=1
```

The current-model pipeline validator accepted the selected attempt; the two skipped checks are the expected power-only checks under `--no-power`.

## Result

`sequence-pair` is available only by explicit request. The centralized production tuple remains exactly `("spine", "freeform")`, and `best` resolves through that tuple rather than through all registered backends. Audit backend registration remains present without changing production selection defaults.
