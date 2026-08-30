# Always-Powered Builds and Deadline Cancellation Specification

## Goal

Remove power-off as a public or production mode and eliminate expensive emission work for detailed-routing attempts already classified as deadline-budget failures.

## Product Contract

- Every production build is powered. A successful placement contains a legal connected Tesla Tower network covering every powered consumer.
- CLI, Python pipeline, strategy constructors, web request schemas, UI, audit, promotion, and benchmark runners expose no power selector.
- Legacy CLI `--no-power` is an argument error. A legacy web `power` key is rejected rather than silently ignored.
- `FreeformLayout` and `SequencePairLayout` public constructors accept no `power` argument.
- Production compaction, validation, and certification explicitly use `expect_power=True`.
- Lower-level private routing helpers and `validate(..., expect_power=False)` may retain the boolean only for synthetic unit fixtures; no production/public caller reaches the false branch.
- Persisted benchmark `power` metadata may remain for historical JSON compatibility but every newly generated record is constant `true` and no current run plan creates a false arm.

## Deadline Contract

- A detailed-routing result classified `DetailedRouteStatus.BUDGET` is never committed or emitted as a `Placement` because both strategies already discard it.
- Bottom-of-round deadline expiry returns typed all-budget routing evidence directly instead of calling `_finish`/`_commit_paths`.
- `_build_prepared` returns `placement=None` immediately for a budget result, before power placement, sorter-slot assignment, placement/stat construction, validation, or projection.
- `ROUTED` candidates retain atomic emission, exact validation, and portable projection. No deadline can weaken legality or discard the only candidate capable of establishing an exact incumbent.
- Route order, path digest, non-budget failure kind/wall, expansion accounting, winner ordering, validation, and projection remain unchanged.

## Acceptance Criteria

- CLI help contains no `--no-power`; passing it exits 2.
- `pipeline.build`, `_new_layout`, `FreeformLayout`, `SequencePairLayout`, and sequence-island production APIs have no public power parameter.
- Web UI sends no `power` member, displays no power checkbox, and the server rejects legacy `power` input.
- Current audit/benchmark/promotion plans generate one powered arm and no false arm.
- Powered end-to-end tests for both strategies pass `power.coverage` and `power.connectivity` after final projection.
- A deterministic bottom-of-round expiry test proves `_commit_paths` is not called and returns BUDGET failures with unchanged expansion accounting.
- A prepared-build budget test proves power placement, sorter-slot assignment, and Placement construction are skipped and `placement is None`.
- SequencePair and Freeform callers discard the cancelled attempt while preserving any prior exact incumbent.
- Focused tests, full Python tests, web tests, Ruff, MyPy, TypeScript typecheck, lint, and production build pass.
