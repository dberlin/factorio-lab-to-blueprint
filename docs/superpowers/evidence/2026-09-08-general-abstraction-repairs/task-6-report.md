# Task6 — job-owned audit accounting and process lifetime

Status: assigned Task6 repair is complete and independently approved. Main's ordinal-accounting, preparation/reverse-process and interrupted-result actual-interpreter-exit probes pass. Both original CLEAN and original ValueError/CRASH peers remain intact beside the interrupted writer's TERMINATED row. The new real-executor regression and Ruff/mypy over 14 source files pass. AuditTransportRepairReview approves spec and quality with no findings. All earlier failures remain preserved below; no validation or process run was performed by this worker. Main owns integration, commits and throwaway-proof cleanup.

## Main baseline evidence (preserved, not rewritten)

- Original real-clock probe: advertised 3-second cap returned after 9.688 seconds with zero rows; both strategies were assigned not_run=1. This proved lifetime overrun, but no fast result settled before the cutoff, so it did not prove attribution.
- Revised deterministic `reverse-red-r3`: the sequence-pair CLEAN result was actually published before the deliberately triggered deadline. Freeform's row disappeared; the summary incorrectly attributed sequence-pair 1/2 and freeform 0/0. Elapsed 17.0618 seconds, including 13.9171 seconds after the observed fast-result cutoff; verified survivors were empty after safe cleanup.
- `preparation-red-r2`: advertised 3-second cap returned after 23.7973 seconds with zero rows; verified survivors were empty after safe cleanup.
- Main's first revised runs were externally capped at 12 seconds, shorter than the probe's own 30-second safety supervisor, and exited 124 without semantic evidence. Those are preserved harness mistakes, not source failure/closure results. The completed baselines above used intact internal supervision.

The reverse probe uses Events to ensure real slow/nested work is present before the real fast future completes. Only the audit's deadline clock is then advanced; after-cutoff lifetime uses the unchanged real clock. The preparation probe uses the real advertised wall clock. Child safety waits and verified PID/start-time cleanup are bounded; no load-dependent sleep establishes ordering.

## Implemented ownership

`_run_jobs` owns an ordinal selected-job ledger, not a completed-row count interpreted as a submission prefix. Per-URL preparation futures and per-cell futures share one supervised pool, including jobs=1. Each resolved BeltAltitudeRules object is sent to every cell for that URL. Rate/spec preparation remains inside each capped cell; no layout search/completion budget changed.

The owner harvests ready cell futures at cutoff exactly once, including results that became terminal after the wait returned. Terminal preparation errors are retained as SPEC outcomes, without admitting new work past the deadline. Worker exceptions remain CRASH outcomes with original type/message; a mismatched returned job cannot credit another selected job. Every remaining selected ordinal gets TERMINATED if the worker actually entered it, otherwise NOT_RUN; unknown candidate identity is kept unknown rather than guessed from index. Such rows cannot qualify as Task5 exact evidence.

Every audit worker calls setsid before preparation or layout. The parent owns only groups registered by that initializer, and nested race/island/spawn children inherit those groups. TraceTransportLifecycle confirmed Task7 adds no setsid/setpgid detachment and preserves that inheritance. Shutdown kills the complete owned groups, calls Python3.14's public kill_workers lifecycle, and joins owned direct children with one shared one-second teardown bound. A second registered-group pass closes partial-initializer acquisition; an unreaped worker is an explicit failure, never fabricated successful closure. The result queue and manager are retained before force shutdown discards their executor references. After every producer exits, only the parent's result writer is closed, allowing the manager's still-owned reader to observe EOF on a partial frame; that manager is joined using the remainder of the same teardown bound. A live manager is an explicit failure, not ignored or hidden by a timeout. This follows the existing strategy_race ownership pattern without its unbounded join. No private executor-process table or generic scheduler/framework was added.

The advertised clock starts at main entry. The metadata subprocess timeout is clamped to remaining whole-audit time; cheap argument/selection preparation is included in that elapsed deadline, and expensive URL/rate preparation is supervised. Admission closes at the deadline. CLI summaries keep their existing parse shape for scripts/audit_ab.py while separately naming terminated versus unreached totals; every terminal row is persisted. Tally.not_run includes both explicit nonexecuted statuses, so selected totals cannot produce a false CLEAN arm. Repeated main calls clear their in-memory ledger instead of replaying prior rows.

## Matching regressions and exact Main commands

```sh
uv run pytest -q tests/test_audit.py tests/scripts/test_audit.py tests/bench/test_runner.py tests/scripts/test_ab_compare.py --tb=short
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-lifetime-probe.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-reverse-green reverse
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-lifetime-probe.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-preparation-green preparation
```

Each probe output directory must be new. Allow the probe's own 30-second bounded supervisor to execute; use an external cap of at least 40 seconds rather than interrupting its cleanup. Before any manual cleanup, use the recorded witness PID/start-time identity, never a guessed process ID. The probe's own cleanup kills only its owned session or verified witnesses and bounds joins.

Permanent tests exercise actual ledger behavior under controlled Future completion: fast second job settles first, outstanding first job is attributed to its own strategy, and an already-terminal result at cutoff is preserved instead of replaced with a timeout row. They do not claim process-lifetime proof; the Event-gated subprocess probes supply that separately. Superseded default-field/forwarding-only tests were removed, not re-pinned to new signatures.

Actual CLI smokes, with new JSONL outputs:

```sh
uv run python scripts/audit.py --only iron-ingot --strategy both --candidate-policy no-proliferator --budget 1 --jobs 1 --max-seconds 30 --json .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-serial-smoke.jsonl
uv run python scripts/audit.py --only iron-ingot --strategy both --candidate-policy no-proliferator --budget 1 --jobs 2 --max-seconds 30 --json .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-parallel-smoke.jsonl
uv run python scripts/audit.py --only iron-ingot --strategy both --candidate-policy no-proliferator --budget 30 --jobs 2 --max-seconds 0.1 --json .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-cap-smoke.jsonl
```

The last command must return a failing gate with two explicit terminal rows, not zero rows or an arm's imaginary CLEAN tally. Real low-budget layout refusals are legitimate outcomes and are not broadened into a solver-policy fix. These commands remain the explicit real-factory smoke handoff; the synthetic transport fixtures below do not claim factory success. Main owns remaining integration-wide proof, probe removal and commits.

Earlier green evidence is retained under `task-6-reverse-green/` and `task-6-preparation-green/`: reverse 3.245 seconds real total / 0.02364 seconds after the triggered cutoff, exactly sequence-pair CLEAN plus freeform TERMINATED; preparation 3.017 seconds and exactly two NOT_RUN rows, with empty verified survivor lists in both cases. The reverse CLI displays four seconds because that probe deliberately advances only its deadline clock; `elapsed.json` records the independent real measurement. Each audit invocation correctly exits 1 for a cap failure, while the enclosing behavioral probe passes for its exercised accounting/preparation/nested-process path.

## Scoped-review interrupted-result repair

`AuditLifetimeScopedReview` found that reaped workers alone did not establish actual CLI lifetime: CPython's executor manager could remain blocked on an incomplete result frame while the parent's result writer stayed open. Main's exact retained baselines confirm this, rather than inferring it from the implementation:

- `task-6-transport-clean-red/`: main returned in 3.133264 seconds, 0.021458 seconds after the driven cutoff, preserving sequence-pair CLEAN plus freeform TERMINATED. The actual interpreter remained blocked in `_python_exit` joining its result manager until the 30.517954-second supervisor kill. No children survived.
- `task-6-transport-error-red/`: main returned in 2.609653 seconds, 0.021592 seconds after cutoff, preserving sequence-pair CRASH with the original `ValueError: partial transport completed peer error` plus freeform TERMINATED. The interpreter again required the 30.518319-second supervisor kill. No children survived.

The worker read the retained return/process JSON and CLEAN-case stack showing the real manager inside connection `_recv` and the main thread inside `_python_exit`. These failures invalidate any claim that the earlier reverse/preparation proofs alone closed the full lifetime contract; their successful accounting evidence remains valid.

The new subprocess probe first publishes an actual completed peer outcome (CLEAN or a real worker ValueError), then writes an authentic large-result frame header and only a prefix. A reader-entry Event establishes that the real executor manager has entered the incomplete body receive before the audit deadline advances. Only the deadline clock is driven; parent exit and teardown timings use the real clock. The supervisor records every worker's PID birth identity before it can detach, captures actual hung-thread stacks, and bounds owned-session/verified-worker cleanup.

Exact Main green invocations, each with a new output directory and external cap of at least 40 seconds:

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-result-transport-probe.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-transport-clean-green clean
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-result-transport-probe.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-6-transport-error-green error
uv run pytest -q tests/test_audit.py -k interrupted_result_reader --tb=short
```

The permanent regression uses a real spawned executor, partial result writer and real manager reader. It requires bounded resource settlement, and independently retains/reaps its own owners in failure cleanup so a regression does not strand the test interpreter. The actual CLI subprocess probe additionally requires real parent exit and preservation of the previously published outcome/error; it does not mistake a returning `main()` for completed teardown.

## Final Main evidence and review

- `task-6-transport-clean-green/`: actual interpreter exits 1 in 4.887802 seconds, `timed_out=false`, no survivors. Main returns in 2.960575 seconds, 0.021287 seconds after the driven cutoff. The completed sequence-pair CLEAN row and freeform TERMINATED row are retained.
- `task-6-transport-error-green/`: actual interpreter exits 1 in 3.327110 seconds, `timed_out=false`, no survivors. Main returns in 2.099131 seconds, 0.019828 seconds after cutoff. The original sequence-pair CRASH detail remains exactly `ValueError: partial transport completed peer error`, beside freeform TERMINATED.
- Main reports the new `interrupted_result_reader` regression PASS and Ruff/mypy across 14 source files PASS. Earlier integrated accounting modules and Task5 exact-first controls also passed; the sole obsolete diagnostic-wording assertion was removed without weakening the failing-verdict contract.
- `AuditTransportRepairReview`: spec P1 addressed; quality approved with no actionable findings. The reviewer specifically confirms writer half-close after producer reaping, bounded manager settlement, and preservation of the already-published peer and terminal ledger.

The worker read both retained green process-exit/return JSON files and the original-error stdout, and read the final review. No red log, hung-stack evidence, fixture error or prior harness timeout was overwritten.

Scope limits remain explicit: Linux/POSIX Python3.14 was exercised; Windows was not. The inherited audit comparator's nonfinite-metric handling is excluded from these identity/lifetime repairs. Driven-deadline transport fixtures prove interruption ownership, original outcome preservation and real parent exit, not a universal real-clock startup bound or successful factory construction. No solver policy, numeric scoring engine, bounded metadata handling or completed result/error is changed by this transport repair.
