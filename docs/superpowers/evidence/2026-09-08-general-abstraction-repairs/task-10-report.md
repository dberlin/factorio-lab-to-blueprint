# Task 10 — displayed-document authority

## Baseline and dependency

Main released Task10 source after the Task9 full-lifecycle and same-pass-prefix reviews passed. The atomic source/caller cutover is now frozen at Main's verification boundary. No build, test, lint, formatter, browser, service or commit launched by this worker. Main's actual built browser already proved late automatic sampled trace replaces a final artifact and synthetic trace shows a checksum warning; these are existing Task10 publication defects, not Task9 collector regressions.

Main reported initial `document-generation-red.log`: 20-second watchdog, 944KB Maximum update depth output from existing uncompiled provider callback recreation; InputPanel reached semantic RED before timeout (newer QuickStart-Step3-Oil-RedCube replaced by old 新蓝图). Main stopped owned orphan rstest descendants. Retain that evidence separately; no rerun merely to reconfirm it.

To make the two trace-transition baselines finite, test-local spies temporarily stabilized only the old real provider's loadSnapshot callback identity. Real provider state, parsing and UI remained exercised. Main reported corrected `document-generation-red-r2.log`: exit 1, two failures / 54 skipped. Late page changed final artifact title to empty; explicit trace after invalid parse left blueprint undefined rather than building 2001. Both temporary shims and their cleanup hooks were removed on stable-action source cutover.

## Implemented source contract

- Provider owns one DisplayState containing discriminated DisplayedDocument, selection, error and stale provenance. Artifact stores decoded blueprint, actual encoded text and import/build job provenance; trace stores synthetic blueprint, frame, label, job identity and generation. Readonly blueprint/snapshot/frame selectors derive from that document, not independent competing fields.
- Stable beginPublication assigns monotonic tokens. publishArtifact/publishTrace/failPublication/markStale admit only the current source. Admission uses a provider-owned ref synchronously, including same-batch manual selection versus older completion. Successful publication resets selection/error/stale in one state replacement. Invalid parsing preserves the previous contract of clearing invalid canvas data; fetch/read failures retain the current canvas with a document-local error.
- Final artifact closes automatic trace publication for its generation. Trace collection continues to the collector handshake. Deliberate Home/End/arrows/range/lane scrubbing and re-enabling Live tail acquire a new generation, even when selecting the same buffered frame. Older build/import completions cannot reclaim it.
- BuildPanel captures generation before async build start, keys the timeline by job, guards aborted completion, and exposes copy/string controls only when that selected build artifact is the displayed document. Selecting a report attempt deliberately publishes a new artifact generation. Stop watching still aborts client polling only.
- InputPanel captures ownership before dropped-file reads and URL fetches; stale success cannot overwrite text or canvas. Fetch/read diagnostics moved out of competing local error state into the same generation-aware provider. Synthetic documents never enter checksum validation.
- Toolbar provenance now consumes the union directly. InfoPanel, BlueprintCanvas and BomPanel remain intentionally unchanged readonly consumers of atomic derived blueprint/selection/frame selectors; no extra per-consumer repair or conversion. Their direct test load callers migrated to publishArtifact + beginPublication.

## Settled test migration and proof commands

TracePanel tests no longer mock provider publication: a real-provider observer reads the actual displayed trace document. The handed-off delayed-final-frame scenario retains its empty/open/final/closed pages, cursor sequence and Home/End assertions. Removed obsolete independent setter/default/identity tests and one exact-wording trace assertion rather than re-pinning implementation. No trace API/model/backend transport test or source changed.

Main targeted command from web: `bun run test tests/state/BlueprintProvider.test.tsx tests/ui/BuildPanel.test.tsx tests/ui/TracePanel.test.tsx tests/ui/InputPanel.test.tsx tests/ui/Toolbar.test.tsx tests/ui/InfoPanel.test.tsx tests/ui/BomPanel.test.tsx`. Then `bun run typecheck`, settled lint/format/build and actual-browser proof per Main's integration sequence. Worker has not run any of these; GREEN/runtime/static/review/commit remain unclaimed.

## Staged discriminating consumer selectors

From web:
- `tests/ui/BuildPanel.test.tsx`: final artifact resists late trace and can be restored after scrubbing or newer import.
- `tests/ui/InputPanel.test.tsx`: a newer manual paste wins over a slow URL import.
- `tests/state/BlueprintProvider.test.tsx`: explicit trace selection atomically clears prior parse error and entity selection without checksum warning.

The handed-off delayed-final-frame case in TracePanel.test.tsx remains untouched. Collection and display are separate responsibilities; final artifact must close only automatic display authority, never discard the delayed transport frame.

## Caller inventory

TypeScript LSP references unavailable: No language server found for this action. Complete web/src and web/tests fallback inventory: producers BuildPanel, InputPanel, TracePanel; provenance Toolbar/InputPanel; selection InfoPanel and BlueprintCanvas; read-only blueprint consumers BomPanel. Provider tests plus BomPanel, InfoPanel, BuildPanel, InputPanel, Toolbar, TracePanel suites consume the context. Canvas resize and coverage suites contain reader-only mocks. No api/trace, trace API tests, traceScene tests, trace backend/jobs/channel files touched.

## Runnable actual-browser scenario (unrun)

`document-browser-scenario.mjs` is temporary and uses request interception against the actual already-loaded built UI, real Blueprint decoding, report rendering and WebGL scene. After the settled frontend is rebuilt by Main, open the actual application and wait for catalog/assets. Inside one browser tab.run callback import its absolute path and call `runDocumentScenario(page, absoluteWorktreePath)`. Returns plain evidence; interception is cleaned up in finally. No callbacks need cross the tool bridge.

The script gates late trace publication after final artifact, deliberately scrubs to three separated rectangular plants at 0/90/37 degrees, captures winner/loser/rotated screenshots, selects losing then winner facts, clears an invalid parse through explicit trace, gates a slow URL import behind a newer paste, and builds the no-seed case. Exact coordinates use 1/2 and 3/2 unchanged.

Main additionally clicks a rendered plant and scrubs to confirm the real inspector disappears, uses Q/E/O to visually inspect framing, and exercises Stop watching during an actual running traced build: collection UI unmounts while solver ownership stays server-side, no cancel-solving request. Inspect all three rotated boxes in the screenshots; a screenshot path alone is not visual proof. Worker has not run this scenario. Main records runtime evidence and removes script/screenshots or retains appropriate proof artifacts after verification.

## Review repair — reselect a completed artifact

Main reported the initial integrated 93 cases/static/build and seven browser transitions PASS, including real inspector clearing and Q/E/O framing, after Main restored the still-used traceFrameLabel import and corrected report row keys. Final review then found P2: a single-attempt completed artifact had no deliberate reselection control after trace/import displaced it, because the multi-attempt table was absent.

Expanded the existing real-provider late-trace test to restore the exact completed artifact and copy control, then perform a newer real InputPanel import and restore it again. Main observed `document-restore-red.log`: exit 1, one failed / 42 skipped, missing restoration action at the expected assertion. After Main's release, BuildPanel now offers **Show completed blueprint** only when an existing selected artifact is not displayed; it invokes the existing selectAttempt path, acquiring a new generation. This works for the single result and whichever attempt is currently selected in a multi-attempt job. It neither copies a trace nor automatically overwrites a newer selection, and it does not rebuild.

Source is frozen again. Main owns focused rerun and actual-browser restoration proof; this worker ran no validation. Browser follow-on: complete a single-attempt build, scrub trace, confirm copy remains absent, choose Show completed blueprint and verify exact artifact/copyability; repeat after a newer manual import. Repeat with a selected losing attempt in a multi-attempt result to verify restoration uses that selected result.
