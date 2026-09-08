# Task 7 — race acquisition and collection ownership

## Evidence and scope

Main reported `general-lifetime-red-r2` exit 1 in 14.82 seconds with four semantic failures before these production edits: interrupted trace pinned the sole Builder worker, second submission left its real started child alive, interrupted parent waiting left two children alive, and a deadline interrupted during executor result publication returned while its child was still alive. The probes confirmed partial payload plus active reader and deadline return; their corrected cleanup completed producer reaping, writer half-close and reader/manager/Builder joins.

The earlier trace/result probe runs exited at their outer watchdogs (60 and 45 seconds). Those are retained as unclassified fixture cleanup timeouts, not semantic RED. Their cleanup attempted `Event.set()` after killing children that could hold its condition lock. The corrected kill-only gates never reacquire child synchronization during cleanup, and Builder cleanup uses bounded owned-thread joins.

This worker ran no tests, build, formatter, lint, browser, service, benchmark or VCS command. Main owns post-edit proof and independent review. Production files changed: `src/flab2bp/layout/strategy_race.py`; Task 9's companion changes are in `observe_channel.py` and `web/jobs.py`. No pipeline, island, solver strategy, client or sampled encoder edit.

## Ownership and implementation

- `_pool_submit` retains its constructed executor through both submissions. Any `BaseException` terminates acquired work before the original exception is re-raised. A cleanup exception is attached as a note, not substituted for the initiating failure.
- `run_strategy_race` constructs its requests before acquiring channels. Every actual queue acquisition enters an owned list immediately; second-queue failure is therefore covered as well as submit and collection failure.
- One finalizer releases the executor, then sharing channels and their actual parent endpoints. Normal fully collected work keeps graceful shutdown; deadline and collection-interruption paths use the existing termination helper. A graceful shutdown interruption also enters forced release.
- `_terminate_executor` retains the actual process-map, manager and result-queue owners before Python 3.14's supported force-shutdown API discards the executor references. It waits for child exit, closes only the parent's result writer, and then joins the manager. This avoids replacing a trace-reader hang with a manager hang on an interrupted result payload. The original map is retained rather than taking an early process snapshot that could omit a replacement spawned while shutdown acquired its lock.
- The supported terminate/kill fallback remains. Retained process handles provide kill fallback if a failed force-shutdown operation has already cleared the executor's own map.
- Deterministic arm order, valid-peer/refused-peer survival, timed-out outcomes and first-in-strategy-order all-arm crash rethrow remain unchanged. No serial pipeline exception normalization.
- One Builder trace queue is shared across candidate races; only the Builder's all-producers-ended boundary releases its parent writer. Task 9 now distinguishes actual receive integrity, not an arm's termination status. The intermediate forced-only marker and all of its callers were removed. See Task 9 report.

## Staged proof

From `.claude/worktrees/abstraction-general`:

```text
uv run pytest -q -s -o faulthandler_timeout=12 tests/layout/test_strategy_race.py::test_real_race_fault_reaps_children_before_channels_and_preserves_failure tests/layout/test_strategy_race.py::test_race_deadline_reaps_a_worker_interrupted_during_result_write --tb=short
uv run pytest -q tests/layout/test_strategy_race.py --tb=short
```

The acquisition/collection test has second-submit and interrupted-wait cases. It starts real spawn-context workers, checks original exception identity, absence of live workers/managers and child-before-channel ordering. The result-write case Event-gates a real executor writer after a message header plus one payload byte and confirms its manager entered the partial receive before the race deadline.

Safe RED cleanup is restricted to recorded owned process handles. It kills without touching a killed child's Event, waits for producer exit, half-closes the retained result writer if necessary, and bounds manager joins. The trace integration probe similarly closes only the verified parent write endpoint before joining its still-live reader. Main explicitly retains diagnostic phase markers until final review and owns their removal.

## Verification state

Main reported `general-lifetime-green` exit 0: seven cases in 16.96 seconds, covering forced header-only/partial payload, clean forced exit, delayed final drain, second submission, interrupted wait and interrupted executor result writing. This is specific evidence for the first repair, not proof of the later normal-exit expansion.

Main subsequently reported `trace-normal-exit-red` exit 1 in 12.20 seconds: a normal recycled child returned its solver result but left the sole Builder worker pinned by its canceled partial feeder. The companion with an already failed collector passed. Task 9's receive-state adapter addresses this same root failure without changing child feeder cancellation or solver-result delivery policy. The final expanded proof and independent review remain Main-owned and pending.

## Final worker handoff

Main reported the post-prefix integrated module run with 350 passes and one unrelated audit wording assertion failure, which Main removed. A subsequent selection containing the same-pass trace regression and 31 audit cases passed all 32 cases. This establishes the same-pass preservation fix as GREEN; it is not a claim that every integrated check has completed.

Main has explicitly taken ownership of remaining validation, diagnostic cleanup, final scoped re-review and narrow type corrections around native/private queue hooks. No further source or test mutation is active in this worker. The reports retain the exact observed proof counts rather than summing overlapping runs. No commit, VCS operation or validation command was run here.
