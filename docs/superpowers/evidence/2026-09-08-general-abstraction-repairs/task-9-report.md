# Task 9 — collector-owned publication closure

## State and baseline evidence

Implementation and regression scenarios prepared. Main reported focused GREEN: `trace-green.log`, exit 0, 93 Python cases across trace/jobs/server/observe_channel; `trace-client-green.log`, exit 0, 69 client cases across trace API/TracePanel/traceScene/beltGraph, with no warnings/errors. Main subsequently reported the actual healthy browser exercise GREEN before the interrupted-write review repair below. Remaining integration/static/re-review and throwaway-probe cleanup are Main-owned. This worker launched no validation command, browser, service, formatter or benchmark.

Main reported three pre-source semantic REDs in `trace-red.log`, exit 1. Task 9's two: timeout `stop()` returned `None`, not `False`; a terminal job's empty page reported `complete=True` while its reader was paused, followed by a reader exception because the queue was closed underneath it. Main authorized core source mutation only after these results.

Main separately confirmed the broken-queue expansion's OSError and ValueError REDs in `trace-queue-red.log`, exit 1: `collector.stop()` incorrectly returned true. After that authorization, `observe_channel.py`'s obsolete suppression was removed; its consumer-visible failure regression replaces the old helper suppression test.

## Source and publication contract

- `TraceCollector.closed` is a thread-safe Event observation, set only after successful final drain. Reader/projection failures publish `error` separately and never fabricate closure.
- `stop(*, timeout=2.0) -> bool` reports actual successful drain and reader termination. A timeout returns false without racing a second drain or closing the queue. `timeout=None` lets the resource owner wait for actual termination.
- `Builder._run` still publishes the solver's actual terminal state immediately. Its finally block retains ownership and waits after a timed-out stop before releasing the queue. It does not mark a completed solver running to hide trace work.
- Finished jobs with an unfinished collector are not evicted from lookup history while draining. Existing history/ring/drop limits remain unchanged.
- Final drain repeats the existing bounded passes until an empty pass, rather than losing a queue tail after one or two batches. Stage-1 loss, raced-leg loss and ring eviction remain separate and unchanged.
- `trace_page` reads collector closure before the ring snapshot: doing it in the opposite order could observe an empty snapshot immediately before final append/closure and incorrectly end polling. Healthy `complete` means closed publication AND no frames after this cursor. Pages containing final frames remain incomplete; the following closed/exhausted page completes.
- A failed collector's already published frames remain readable. Once that cursor is exhausted, the endpoint returns `{ "error": "trace collection failed: ..." }`, not a successful complete page. `pollTrace` recognizes that existing-style error envelope and uses the existing visible polling error path. Healthy TracePage schema, cursor semantics and ten-number rows are unchanged. No provider/document-generation changes.

## Caller inventory and queue failure expansion

LSP reference requests for `TraceCollector` and `drain_trace` both failed with `this._token.cancel is not a function`. Full fallback search across `src`/`tests` found one production `drain_trace` caller: `TraceCollector.drain_once`. Other callers are `tests/layout/test_observe_channel.py` and `tests/layout/test_strategy_race.py` (normal queue tuple consumption only). Task 7 race cleanup is untouched.

The old helper catches OSError/ValueError and returns partial/empty success, explicitly citing the old timeout-close race. Removing that suppression moves failure ownership to the collector, where it can be reported without disturbing solver success. Already published ring frames survive. The obsolete helper regression that demands silent broken-queue success is replaced by consumer-visible failure coverage rather than re-pinned to implementation text.

## Staged tests and proof still owned by Main

- `tests/web/test_trace.py::test_stop_timeout_leaves_publication_open_until_final_drain`: Event-gated reader plus immediate timed join; confirms false timeout, no premature frame, and successful final drain after release.
- `tests/web/test_trace.py::test_stop_drains_more_than_two_bounded_queue_batches`: retains the tail beyond two queue passes without stage-1 loss.
- `tests/web/test_jobs.py::test_terminal_job_keeps_polling_until_delayed_collector_drains_and_closes`: actual Builder and collector, gated final read, queue that detects premature closure; solver done -> empty/incomplete -> final frame/incomplete -> closed/exhausted complete.
- `tests/web/test_jobs.py::test_collector_failure_preserves_published_frames_then_reports_failure`: projection failure remains separate from solver done; published frame first, error envelope afterwards.
- `tests/web/test_jobs.py::test_broken_trace_queue_is_failure_not_successful_empty_completion`: OSError and ValueError failures cannot become complete; published frame remains readable.
- `web/tests/api/trace.test.ts`: collector error envelope preserves its actual diagnostic at the polling boundary.
- `web/tests/ui/TracePanel.test.tsx`: empty open page does not suppress delayed final frame; Home/End can select first/final frame after the complete handshake, and cursor repeats on the empty page.
- Existing startup-failure cleanup, ring eviction/drop, and server pagination cases are intentionally unchanged.

Main commands: `uv run pytest -q tests/web/test_trace.py tests/web/test_jobs.py tests/web/test_server.py tests/layout/test_observe_channel.py --tb=short`; from `web`, `bun run test tests/api/trace.test.ts tests/ui/TracePanel.test.tsx` (plus Task 8 graph cases). Main owns any broader race checks, integration checks, formatting and review.

## Actual-browser final-frame exercise

Use shared `trace-browser-probe.py` exactly as Task 8 report describes. It serves this worktree's built actual frontend at port 8019 using the small real build fixture. It is throwaway and unrun by this worker.

1. Submit one traced build and wait for `FINAL DRAIN PAUSED`. Observe normal build job `state=done`. Initial trace frame is seq 0 / candidate `sampled-links`.
2. Let the actual UI poll at least twice after consuming seq 0. Network `/trace?from=0` must return empty frames, next=0, complete=false while the collector remains gated. The existing 2-second stop timeout may elapse; polling must still continue and the queue must stay open.
3. Through the supervised process send stdin `release`. The probe queues a final stage-1 event before releasing the reader, with candidate `final-drain`, seq 1 and a visibly moved first belt (x=-2 instead of x=0). No sleeps choose the release timing.
4. Observe actual HTTP delivery of seq 1 while the job is still done, followed by empty from=1 / complete=true. The trace panel must stop only on this latter handshake.
5. Use Home then End on the actual scrubber. Inspect `sampled-links` then `final-drain` metadata and the changed first-belt location; capture screenshot showing selectable final frame, TRACE label and sampled notice. Check no browser console error. Do not substitute fetch/schema-only proof for this visual/selectable-surface exercise.
6. Send `quit`. Main removes the throwaway script after proof and records actual runtime observations here.

Focused green evidence above was supplied by Main. Browser/static/final review and probe removal remain pending Main; no claim is made for unexercised proof.

## Interrupted-write review repair

`CollectorLifecycleReview` found a P1 in the unbounded second collector join: `multiprocessing.Queue.get_nowait()` polls before entering a blocking framed receive. Killing a child feeder after its header or partial payload leaves that receive blocked because the parent still owns a writer. The sole Builder worker then cannot start its next queued job. Earlier healthy Python/client/browser proof does not cover this failure.

Main reported the corrected real-process baseline `general-lifetime-red-r2` exit 1 in 14.82 seconds. The trace case confirmed a healthy published frame, a real child feeder's partial payload, the collector's active receive, and the actual race deadline returning. The next build did not start within the probe observation. Safe cleanup subsequently reaped owned producers, half-closed only the parent writer, and settled the reader and Builder worker. The three associated Task 7 failures and the initial fixture cleanup timeouts are recorded in `task-7-report.md`.

Main then reported `general-lifetime-green` exit 0, seven cases in 16.96 seconds, for the initial forced-only recovery. That did not establish the full producer boundary: `trace-normal-exit-red` subsequently exited 1 in 12.20 seconds. Its normal `max_tasks_per_child=1` child delivered its solver result, but `TraceChannel.close` canceled its gated partial feeder and the sole Builder worker still could not advance. The already-failed-collector companion passed. The final repair below replaces the forced-only marker rather than treating an unmarked normal exit as proof of intact framing.

### Actual producer lifetime

The Builder creates one spawn-context Queue per traced job and shares it with every candidate race. `pipeline._solve_candidate_batches` owns a ThreadPoolExecutor that waits for its sibling candidate races; closing the trace writer per race would prematurely close a shared producer domain. The parent never puts serial events on this multiprocessing queue: they go through the collector observer's deque. Only spawned race legs own trace feeder threads. The parent therefore has no local feeder to flush before a write-end half-close.

Task 7 now establishes actual child and executor-reader termination on forced release, including partial acquisition and interrupted collection. Only after the solve has left that producer domain does `Builder._run` attempt final trace shutdown.

### Recovery contract

- `prepare_trace_queue` installs `_TraceReceiver` once on the parent connection, before collector startup or producer spawn. It observes the native receiver's successful read steps without copying its framing decoder. Connection reduction sends only handles and flags to spawned children; the parent's hooks do not cross that boundary.
- POSIX `Connection._recv` marks successful header consumption. A true boundary EOF before that first read becomes ordinary queue exhaustion; EOF after the header becomes an explicit truncated-message error. Native partial-header/body OSError and EOFError during subsequent unpickling still propagate. Windows message-pipe `_get_more_data` records the analogous started-message boundary; that platform branch is not claimed exercised on this Linux host.
- At the actual all-producers-ended boundary, Builder half-closes every real trace queue's parent writer before waiting for its collector. This covers normal recycled-child exits as well as forced termination, without waiting for elapsed time to infer transport integrity.
- No child feeder-join or solver-result policy changed. Optional trace failure cannot block a child before it returns its already computed solver result. The intermediate forced-only marker, recovery helper and every caller were removed.
- A healthy delayed drain retains its live read endpoint and can still read its final complete frame after parent writer closure. Clean native boundary EOF then ends publication successfully. Header-only, partial-header/payload or unpickle failures never become false completion. The existing timed stop and subsequent actual join remain; no new elapsed cap or blanket timeout failure was introduced.
- `close_trace_queue` releases both parent endpoints only after reader termination. `Queue.close()` by itself merely wakes a local feeder; the read-only parent has none.
- Solver terminal state and its original error remain truthful and independent. Published frames still precede the trace error envelope. The healthy page contract remains closed AND cursor-exhausted. Sampled remapping, ring accounting, provider and client publication are unchanged.
- `drain_trace` now yields each valid dequeue incrementally within its existing GET bound. `TraceCollector.drain_once` publishes its sole existing stage-1 buffer in `finally`, so a later transport failure cannot discard either queued valid events or already retained serial events. Existing maxlen overflow/drop accounting and event timestamp/order remain unchanged. The two length-based tests and real-race batch truthiness consumer were migrated explicitly to tuple consumption; no second production buffer or legacy tuple-return adapter remains.

### Expanded focused proof

```text
uv run pytest -q -s -o faulthandler_timeout=12 tests/web/test_jobs.py::test_interrupted_trace_write_reports_failure_and_next_build_starts tests/web/test_jobs.py::test_clean_trace_stays_complete_when_a_producer_is_terminated tests/web/test_jobs.py::test_terminal_job_keeps_polling_until_delayed_collector_drains_and_closes tests/web/test_jobs.py::test_normal_trace_producer_exit_keeps_result_and_advances_next_build tests/web/test_jobs.py::test_real_trace_queue_keeps_delayed_final_frame_after_normal_producer_exit --tb=short
```

The interrupted transport case covers partial header, header-only, partial payload and a complete transport frame with an invalid empty pickle. These exercise different native framing/unpickling failure boundaries. Every case uses a real multiprocessing feeder and actual expired-clock race deadline, requires the default single-worker Builder's queued job to advance, preserves the solver error and published frame, reports explicit trace failure, and leaves no owned process, manager or reader alive.

Normal-return cases preserve the received race result and actual successful build, both for an interrupted reader and an already-failed collector. Complete-frame controls preserve successful trace closure after forced termination and after a normal exit with the real Queue reader paused beyond the existing timed stop. The latter must still publish its final frame after release rather than converting writer closure into a trace error.

Main reported `trace-native-lifetime-green` exit 0, 11 cases in 20.07 seconds. Its actual selectors covered all four corruption boundaries, both normal-return cases, both delayed-drain cases and Task 7's three cases. The clean-forced companion was not in that particular command and was identified to Main for the next focused run; it is not counted as post-adapter proof here.

The native lifecycle review then found a separate same-pass loss: a valid event accumulated in the old `drain_trace` tuple disappeared if the next receive raised before the tuple returned. Main confirmed RED in `trace-prefix-red.log`: the error envelope appeared before either the serial-pending or complete queued frame could be read. The consumer regression is `tests/web/test_jobs.py::test_collector_failure_keeps_complete_frames_from_the_same_queue_pass`, using one real complete transport message followed by an invalid empty pickle in the same pass. The incremental-drain/finally-publication repair is implemented.

Main reported the post-prefix integrated module run with 350 passes and one unrelated audit wording assertion failure, which Main removed. The next selected run included this trace regression and 31 audit cases and passed all 32 cases. Same-pass retention is therefore GREEN; no aggregate pass count is inferred by adding overlapping runs.

Main explicitly owns remaining validation, diagnostic phase-print removal, narrow type corrections for the private native receiver/queue fields and final scoped re-review. Diagnostic prints remain at Main's request until review completes. This worker's source/test work is frozen and handed off; no validation command was run here. The Windows message-pipe branch remains explicitly unexercised on this Linux host.
