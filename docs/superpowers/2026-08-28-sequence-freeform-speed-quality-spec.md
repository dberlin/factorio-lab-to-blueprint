# SequencePair and Freeform Speed/Quality Specification

## Goal

Improve SequencePair and Freeform latency and valid-layout yield under the existing wall-clock budgets without weakening exact routing, validation, or spherical projection.

## Scope

1. Restore trustworthy routing profiling and preserve structured refusal evidence in audit results.
2. Remove SequencePair's duplicate final projection of the winning placement.
3. Reduce shared detailed-router allocation/reconstruction work while preserving exact route behavior.
4. Let one bounded, same-height Freeform arrangement rescue a strong routing near miss before the first valid incumbent.
5. Keep SequencePair route feedback active during quality exploitation and retain one topology-diverse archive candidate instead of redundant narrow candidates.

## Constraints

- Exact `(area, belt_tiles)` remains the only authoritative winner key.
- Exact detailed routing, `validate.certify`, and `finalize.finalize_placement` remain authoritative; no proxy may accept or reject a final layout.
- Performance changes must preserve route ordering, path digest, failure kind/wall, expansion accounting, and emitted buildings on deterministic tests.
- Freeform rescue work is fixed-work: it may replace a redundant candidate but must not increase the configured arrangement count or solver budget.
- A routing near miss means 1–3 non-budget failures. Budget exhaustion never triggers rescue work.
- SequencePair diversity is keyed by its existing exact relation/topology signature. It does not raise beam or archive capacity.
- Structured audit refusal output must include every `LayoutAttemptFailure` and `ProjectionFailureRecord`; human-readable summaries may remain compact.
- New observability must be observational and bounded. It must not add logging inside A* expansion loops.
- Python remains statically typed and Ruff/MyPy clean; avoid `Any` and new dependencies.

## Acceptance Criteria

- `scripts/route_profile.py` handles `_PathSearchResult` and a current `_Canvas`, and a focused smoke command completes without crashing.
- Audit JSON/result records retain typed attempt and projection evidence instead of only `("<refused>",)`.
- A successful SequencePair solve calls final projection once for the selected winner and returns that exact finalized `Placement`.
- Shared routing no longer allocates a new reservation flag buffer for every `_astar` invocation; deterministic route results remain byte-for-byte equivalent.
- Static prepared routing state is reused when a prepared candidate opens multiple workspaces; only attempt-local mutable state is copied.
- Freeform can try one later arrangement before an incumbent when the preceding same-height route result has 1–3 non-budget failures, and does not do so for budget failures or larger misses.
- SequencePair quality exploitation continues to consume detailed-route feedback and retains relation-signature diversity under the existing archive limit.
- Focused tests, the complete Python suite, Ruff, and MyPy pass.
