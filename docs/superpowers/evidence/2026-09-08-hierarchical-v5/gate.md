# Hierarchical v5 measured acceptance

Status: measured verification complete. Source repairs and the default no-regression guard pass; large factory targets **FAIL**. Candidate reservation replay emits no blueprint and supports no policy promotion. This report does not turn a repaired invariant or fully routed cut set into a certified factory.

## Source and protocol

Baseline production `bbc8889d`; candidate `.claude/worktrees/hierarchical-v5`. Full source/catalog/dependency hashes and commands are retained in [final-gate manifest](final-gates-is4gg8m4/manifest.json). The candidate is an isolated working tree, not merged or pushed.

- Large originals: PLACED, exact machine rank, portable band,32 workers, CPUs0–31, one cell at a time,15/60-second budgets and unchanged six-second completion grace.
- Eighteen originals per side: four titanium originals at each budget; one original for each other case/budget. Ten baseline originals are reused only after source/catalog/lock hashes match, with their JSON hashes recorded; eight remaining baseline originals are fresh. All18 candidate originals are fresh.
- Default guard: fresh72-cell before/after, PLACED,128 workers, CPUs0–127, jobs1, budget30, max7200. These audits are serial, not the historical jobs4 operating point.
- Candidate reservation replay waits for both audits; subsequent failed-cell adjudication waits for reservation replay. No benchmark CPU allocation overlaps another owned run.

Fresh before/after guards completed72/72 identities each:66 CLEAN and the same six universe-matrix REFUSED on both sides, zero status losses, zero INVALID/CRASH, zero recorded completion-grace overruns, no paired CLEAN area expansion above20%. Full source/catalog/dependency hashes stayed unchanged. All12 failure-only serial repeats also refuse, with no watchdog or recorded grace overrun; originals remain unchanged. See [adjudication summary](final-gates-is4gg8m4/adjudication-summary.json). The audit's generic NOT CLEAN footer is not evidence of an INVALID cell.

## Completed source proof

Changed production modules: `layout/hierarchy/strategy.py`, `layout/hierarchy/compose.py`, `layout/freeform.py`.

Funding builds one deduplicated shape/arm work plan and includes remembered-threshold breakpoints. A consumer counterexample with thresholds[-inf,10], width1 and remaining15 fails under the old7.5-second funding and passes with the actual10-second job. Existing seed/deadline/memo semantics remain covered.

Composition admission now shares committed coater geometry with freeform and checks ground support plus stacked junction supports in portable frames. Exact baseline titanium geometry routed26/26 but admitted a ground support that violated `game.addon_splitter_clearance` in finalization. The reduced illegal support is rejected; its nearby legal control remains admitted. All five causal regression cases pass. This is geometry-invariant proof, not factory completion.

Fresh final checks: Ruff, format check and mypy pass on the changed source; all95 tests in the three affected test modules pass. Results and commands are in `final-gates-is4gg8m4/{ruff,format,mypy,focused-tests}.*`. Independent funding, composition and integrated source reviews are retained in the SDD ledger; the integrated review reports no findings within its read-only scope.

Exact captured mall funding arithmetic also completed: [replay](funding-replay.json). Across four captures/six submitted round entries, all-products seed19 raw demands collapse to16 unique jobs, reducing funding waves3→2 and increasing5 seconds to5.866/5.891 seconds at the recorded solve-entry clock. Its retry26 demands collapse to20 keys, with3/5 remembered keys leaving17/15 jobs and3/2 waves instead of4. No-proliferator seed48 demands collapse to40 jobs, reducing6→5 waves but remaining at the5-second floor. Entries, offered arms and no-goods are held fixed; these are planned jobs, not newly executed block outcomes. Solve-entry timestamps follow the original funding calculation, so the replay does not claim bit-identical reconstruction of the earlier funding instant.

## Actual small hierarchy smoke

Tesla: CLI exit0,36 decoded buildings, one machine,112 tiles; same emitted bytes SHA256 `82f9a57f7c319fed2d508785db2c8801bdb48794261cd8dc9520d84ac9a30ae5`. CLI finalization/certification succeeded and the emitted file decodes. See [small Tesla result](final-gates-is4gg8m4/candidate-small-tesla.json) and its retained blueprint/decode output.

Substation: candidate CLI exit3; one iron block refuses `power.coverage` before composition. The exact baseline control also refuses on coverage, so this is not a new candidate regression. Both failed originals remain failures. Separate wireless smoke passes: CLI/decode exit0,37 buildings,112 tiles, including two item2202 Wireless Power Towers. See [wireless result](final-gates-is4gg8m4/candidate-small-wireless-control.json) and [decoded item counts](final-gates-is4gg8m4/candidate-small-wireless-control-decode.stdout.log). Wireless success does not replace the failed Substation gate.

## Large original outcomes

All36 baseline/candidate originals refuse. No successful paired blueprint exists for a large-case area comparison. No fresh original exceeds budget plus six seconds in the recorded CLI wall, and no150-second process watchdog expires. Process startup wall is retained separately from CLI wall.

| Case | Baseline15 | Candidate15 | Baseline60 | Candidate60 | Candidate60 boundary |
|---|---:|---:|---:|---:|---|
| Titanium |0/4 emitted|0/4 emitted|0/4 emitted|0/4 emitted|25/26 cuts routed; one unresolved cut in each original|
| Mall/all-products |refused|refused|refused|refused|37/43 final blocks unattempted; no compose|
| Mall/no-proliferator |refused|refused|refused|refused|46/52 final blocks unattempted; no compose|
| Belt3/all-products |refused|refused|refused|refused|17/95 cuts unresolved|
| Belt3/no-proliferator |refused|refused|refused|refused|6/130 cuts unresolved|
| Zurl2/all-products |refused|refused|refused|refused|39/138 cuts unresolved|

Titanium candidate60 CLI walls:29.66,26.23,30.52,25.92 seconds. These stop before the parent wall because search can exhaust its intentional work bound. The exact saved-input recomposition identifies the remaining casimir-crystal block4→5 cut as BUDGET at2,000,000 expansions with34.2107 seconds of parent wall still available. No bound or routing allowance was increased.

Mall/all60 baseline also leaves37/43 unattempted. Mall/none60 baseline leaves44/51; candidate46/52. Deduplicated funding is a proven accounting repair, not a demonstrated solution to mall placement coverage.

All full refusal text, scalar stats, actual commands and timing are in original per-cell JSON/stdout/stderr, not truncated prefixes. Belt3/all60 baseline has12 unresolved cuts versus17 candidate; belt3/none60 has11 versus6; zurl2/all60 has12 versus39. These are refused whole factories on both sides, not CLEAN-to-failure regressions or successful performance gains.

## Reservation selection experiment

Frozen baseline Task4 completed42/42: six exact solved-block captures × control and existing rungs2,4,6,8,12,16. All764 snapshot hashes verified; no missing snapshot or integrity failure. No certified blueprint emitted. No transfer rung fully routed. Missing=0 and convergence are therefore not accepted as success scores.

A retained goal-held witness on energetic-graphite block9/belt4819 has five local/two reachable options before141 held assignments, then zero/zero. That distinguishes reservation-induced loss from an intrinsically inaccessible port; it does not establish a successful general selection rule.

Current candidate replay completed42/42 over the same six trusted captures and original phase allowances:38 composition refusals and four explicit `ProjectionRefusal` outcomes, zero emitted bytes and no process watchdog. Each rung is an independent diagnostic, not a six-times-larger shipping clock; wall comparisons to baseline are not claimed. Full per-net, reservation, phase and failure evidence is in the [candidate manifest](candidate-task4-sqey32nd/manifest.json).

| Capture | Control unresolved cuts | Best observed candidate boundary |
|---|---:|---|
| Belt3/all60 |17|gap12 leaves8; missing reservations remain0|
| Belt3/none60 |9|gap12/16 leave6; missing remains1|
| Zurl2/all60 |38|every wider rung worsens routing; missing rises3→5 at12/16|
| Titanium60 |1|gaps4/8/12/16 route26/26, then physical projection refuses|
| Titanium15 r1 |26|gap16 leaves10|
| Titanium15 r2 |14|gap16 routes26/26, but captured6.196-second composition wall is spent before power infill|

The four fully routed titanium60 cases fail `geom.collide`; gap4 also fails `game.power_too_close`. These are physical finalization refusals, not harness setup failures or emitted INVALID blueprints. Zero missing reservations is not a sufficient routability score, and complete cut routing is not final certification. No measured general discriminator satisfies the accepted transfer criterion; production rung selection remains unchanged.

## Final measured acceptance

- Funding mechanism: **PASS**, bounded by behavioral tests and independent review.
- Reproduced coater/junction admission invariant: **PASS**, causal red/green and exact retained geometry.
- Titanium60 4/4 and titanium15 at least1/4: **FAIL**.
- Both malls place all blocks and reach compose60: **FAIL**.
- Small Tesla and separately named wireless emission/decode: **PASS**; Substation original and baseline control: **FAIL**.
- Default72-cell no-loss/invalid/crash/grace gate: **PASS**,66 CLEAN/same six REFUSED on each side; serial repeats preserve all12 refusals.
- Candidate reservation experiment: **COMPLETE**,42/42; accepted policy discriminator **NOT ESTABLISHED**, zero certified emissions, no promotion.

Original failures remain failures even if a later serial adjudication succeeds. No all-CLEAN, full factory reliability, general topology repair or game-paste proof is claimed.
