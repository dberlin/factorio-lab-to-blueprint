# Task 8 — sampled trace graph ownership

## State and evidence

Implementation and discriminating regressions prepared. Main reported focused GREEN: `trace-green.log`, exit 0, 93 Python cases across trace/jobs/server/observe_channel; `trace-client-green.log`, exit 0, 69 client cases across trace API/TracePanel/traceScene/beltGraph, with no warnings/errors. Browser/static/review and throwaway-probe removal remain Main-owned and are not claimed complete. No test, build, browser, service, formatter or benchmark was launched by this worker.

Main reported the pre-source baseline in `trace-red.log` (exit 1): `test_sampled_frame_links_resolve_to_retained_buildings_not_dense_aliases` reconstructed x=4 for a link whose original target is x=2. Source mutation started only after Main authorized it from that RED.

## Source contract

`src/flab2bp/web/trace.py::frame_json` owns sampling and connection remapping. It iterates original indexes with a uniform stride, without slicing/copying the building sequence or allocating an index map. Each retained input/output points at `original_target // step` only when that target is nonnegative, in bounds and retained; otherwise the wire target is `-1`. Standalone `building_row` remains literal encoding. Unsampled links are unchanged. Ten positional numbers, existing cap and `truncated` label are unchanged.

`web/src/api/trace.ts` documents dense sampled indexes. No adapter, renderer, topology, placement-index or provider changes are needed: `traceFrameToBlueprint`, `beltSuccessors` and sorter consumers already use dense scene indexes.

LSP references for `frame_json` and `TraceCollector` failed with the persistent `this._token.cancel is not a function` server error. Complete narrow fallback inventory covered web source, server tests and trace client files: production encoding is owned by `TraceCollector.drain_once`; standalone row calls are confined to the encoder/tests.

## Staged and existing proof to run

- New `tests/web/test_trace.py::test_sampled_frame_links_resolve_to_retained_buildings_not_dense_aliases`: above the real cap, retained belt successor, omitted aliasing successor, retained sorter input/output, omitted and out-of-range sorter endpoints; reconstructs destination coordinates rather than testing tuple lengths alone.
- New `web/tests/model/traceScene.test.ts`: `sampled dense links reconstruct the retained chain and disconnected sorter endpoints`; runs actual graph reconstruction over the dense wire contract.
- Existing `tests/web/test_trace.py` row/metadata/cap cases intentionally retained to defend literal unsampled protocol.
- Existing `web/tests/model/beltGraph.test.ts` requires no edits; run alongside the new adapter/graph case.

Main commands from worktree: `uv run pytest -q tests/web/test_trace.py --tb=short`; from `web`: `bun run test tests/model/traceScene.test.ts tests/model/beltGraph.test.ts`.

## Actual-browser fixture and exercise

Shared throwaway fixture: `trace-browser-probe.py` in this report directory. It uses the actual HTTP server, the actual collector/encoder and the existing web fixture's small real pipeline build. Only final-drain scheduling is Event-gated; it does not mock frontend modules or substitute wire rows. It has not been launched here.

1. Main builds this worktree's frontend once, then starts via supervised process: `uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/trace-browser-probe.py`, cwd this worktree. Readiness: `TRACE PROBE READY` and port 8019. Fixture precomputes the existing small build; it never builds the frontend itself.
2. Open actual browser `http://127.0.0.1:8019`. Enter `https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11`, enable Record search trace, submit exactly one build.
3. Wait for `FINAL DRAIN PAUSED`. The normal job is `done`, with the sampled initial frame available. Select the initial frame explicitly using the timeline to avoid confusing the real build-result canvas with trace selection.
4. Inspect the branch near (0,0), away from filler around (100,100). Dense rows represent original indexes 0,2,4,6,8: belt 0 at (0,0) feeds belt 1 at (1,0); belt 1's omitted original target 3 must be disconnected. Sorter dense 2 at (2,0) connects input dense 1 to output dense 4, the machine at (3,0). Belt dense 3 at (0,3) also has omitted original target 3 and must be disconnected, not self-linked.
5. Network frame rows 0..4 must have output/input fields `[1,-1]`, `[-1,-1]`, `[4,1]`, `[-1,-1]`, `[-1,-1]`. Inspect renderer/selection links and capture a screenshot. Sampling must remain visibly labeled; no link may alias a different retained object.
6. Continue Task 9 instructions to release/select the final frame. Send `quit` through the supervised process when finished. Remove this throwaway probe after Main captures runtime evidence; keep the regression tests.

Browser observations, static checks, integration review and final cleanup remain unrun/unclaimed here. Focused green evidence above was supplied by Main.
