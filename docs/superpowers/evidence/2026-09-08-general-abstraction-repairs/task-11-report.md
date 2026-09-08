# Task 11 — attempt-local operational facts

## Boundary and evidence

Source and discriminating consumer regression prepared; GREEN/static/browser/review/commit remain Main-owned and unrun by this worker. Main reported pre-source `display-facts-bounds-red.log`: exit 1, two failures / 20 passes, including missing PRIME ONCE region after real `pollBuild` decoding. No tests, build, lint, formatter, browser, service or commit was launched by this worker.

Main subsequently reported `display-facts-bounds-green.log`: exit 0, 59 cases across API/report/layout/camera selected modules. Typecheck found only two Task10 baseline cleanup callbacks returning RstestUtilities; these test-only callbacks were changed to return void. Browser/static final review remain Main-owned.

## Cutover

`web/src/api/build.ts` now composes one AttemptFacts schema into both the winner and each attempt detail. It includes exact existing `self_loop_seeds` records (including per-recipe instructions and nullable heads) and `belt_tiers.entry_lanes`. Head z and economic rate exact values remain strings. Unknown response fields remain stripped rather than globally rejected. `BuildReport` directly consumes selected detail or result instead of manually copying winner fields. It shows every recipe's seed count, machine count and available head coordinate under PRIME ONCE, separately from ongoing Belt in, and selected entry lanes versus lanes needed. No-seed results emit no priming warning. Invalid artifact withholding remains unchanged.

The Python payload already owns `_self_loop_seeds`, `_belt_tiers` and `_report_block` for winner and attempts; no competing Python facts construction justified a backend change. All backend files remain untouched.

## Inventory and checks for Main

LSP references for AttemptDetail failed: No language server found for this action. Complete fallback search across web/src and web/tests found only api/build.ts, BuildReport.tsx and tests/support/build.ts as type consumers. AttemptDetail type was removed, not aliased. Fixture helpers now supply required empty seed/lane fields; existing shape overrides retain these fields.

Run from web: `bun run test tests/api/build.test.ts tests/ui/BuildReport.test.tsx tests/ui/BuildPanel.test.tsx`; from worktree: existing `tests/web/test_payload.py` remains intentionally unchanged. The retained test `decoded winner and losing attempt retain their own priming and entry-lane instructions` feeds actual-shaped wire data through pollBuild then the real report. Winner has 7 hydrogen seeds / winner-loop / 2 machines / (3,5,1/2), 2 lanes / 1 needed; losing attempt has 11 / losing-loop / 4 / (-9,8,3/2), 3 lanes / 2 needed. It then selects a no-seed result. This catches Zod stripping, winner-copy omission, selected-attempt leakage and ongoing-supply confusion.

Browser proof: exercise the same winner/loser/no-seed fixtures on the actual BuildPanel, select the losing attempt through its report button, verify its own priming and lane instructions, return to winner, then no-seed result. Preserve invalid withheld attempts as non-selectable. Main records observed browser evidence and removes throwaway scenario tooling after proof.
