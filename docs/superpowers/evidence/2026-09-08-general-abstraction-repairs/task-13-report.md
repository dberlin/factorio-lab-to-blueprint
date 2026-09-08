# Task13: shared routing domain

## Gate and exact move map (before source edits)

Main reported the baseline gate PASS and authorized the frozen 234-symbol cutover. That source cutover is now applied and frozen for Main's replay/static/review gate. This worker ran no runtime validation, tests, builds, formatters, linters or commits. The approved change remains ownership-only; original transport/path/corridor/immutable snapshot and actual-Coater repairs remain authoritative.

`task-13-move-map.json` publishes the exact 234-symbol source/destination map, original line ranges, and incoming source/test/script references before edits. All symbols retain their current names; no rename or compatibility re-export is proposed. `_PreparedRoutingProblem`, `_PreparedNet`, `_RoutingWorkspace`, `_Canvas`, `_Grid`, `_Port`, port reservations, physical transition/detailed routing, preparation and required geometry move to `src/flab2bp/layout/routing_domain.py`.

The complete preparation/shared-geometry closure is ~15,360 declaration lines, not merely the three prepared dataclasses: preparation emits existing strips, staged Coaters/Pilers/power and source trunks. Moving only the router leaves a domain-to-Freeform dependency. Therefore the existing immutable `Strip`, `_Group`, `DirectInsertId`, `_Pack` input record, staged-static identities and exact refusal evidence move with their domain fact helpers. These are data/preparation facts, not placement/search selection. `_Pack` retains argument/result semantics and its selected coordinates; no alternative placement representation is introduced. The final inventory also includes shared staged-static proof/cache facades, the Piler-tail coordinate fact, commit belt-keepout helpers and cleanup-survivor bounds helper, so those mechanisms do not remain reachable through Freeform.

Freeform retains `FreeformLayout`, `plan_strips`, sharding/variant selection, direct candidate/alignment selection and memoization, CP-SAT packing/window models, pack budgets/objectives, arrangement/height sweep, ALNS, outer feedback/retry selection, `_build`/`_build_prepared` completion orchestration and fallback/refusal policy. Sequence-pair and global relaxed negotiation retain their algorithms. The existing CP-SAT corridor matcher DOES move: it assigns routing access, not strip placement; all rank/tie/cut budgets remain byte-for-byte unchanged.

LSP `references` was attempted on the actual worktree path for `_PreparedRoutingProblem` and failed with `-32603: this._token.cancel is not a function`. This tool failure is reported. Scoped AST declaration/dependency/import/attribute inventory is the fallback; no symbol rename is planned. Incoming inventory covers `src`, `tests`, and maintained `scripts`; historical experimental evidence is not a live consumer.

## Incoming consumers

Production: `freeform.py`, `sequence_solver.py`, `global_router.py`, `last_mile.py` (type), `strip_variants.py`, `geometry_memo.py`, and `hierarchy/compose.py`. In addition, `dsp/registry.py` now names `routing_domain` for its existing `_astar`/`_route_all` lint exceptions; numeric values and named-function scopes are unchanged, and all placement/search exceptions remain attached to Freeform.

Maintained tooling: `scripts/route_profile.py`, `route_bench.py`, `prepare_parity.py`, `last_mile_bench.py`. Route-profile monkeypatches must target the actual new owner and any consumer-bound imports, not a stale Freeform binding.

Tests: the exact map lists affected files under `tests` (including shared conftest, indexed/rules fixtures, route-profile probes and layout modules). Imports, module attributes, and monkeypatch strings must migrate coherently; no behavior assertions are to be changed just to preserve old ownership.

Composition retains `canvas_for`: it already constructs the actual composed building list without pretending blocks are strips. Its registration semantics (sorters, actual Coater bans/drop exemptions, belt-integrated buildings, Splitter guards, machine solids, tower halo, limits) remain intact and import the new neutral owner directly. No conversion through `Strip` or `_prepare_routing_problem` is added, and no duplicate snapshot/index is introduced there.

## Preserved boundaries and work

- `Buildings`, `MutableBuildings`, `Nets`, `StakedPaths` and `PortReservations` remain their current owners; no duplicates.
- `_with_sibling_groups` remains the one frozen compatibility grouping step; source/destination/cargo rules do not change.
- `new_workspace` keeps one fresh mutable building container and fresh attempt state sharing frozen building records; no deep copies.
- Prepared lower bounds and `routing_problem()` retain current identity and prelinked-Piler behavior.
- Relaxed overflow/capacity status never becomes a physical-legality certificate. The neutral validator keeps its independent rules and is not changed.
- Actual Coater frame bans, path commit/rip-up ownership, corridor allocation, power and boundary early/late order are preserved.
- No strategy callbacks, aliases, route/search policy changes, validator relaxations, cache additions or speed targets.

## Main-owned proof boundary

`task-13-probe.py` is staged and NOT executed by this worker. It freezes four actual cases: existing `two_stage_spec`, source-sharding/external-arrival preparation, existing mixed-cargo/boundary-output preparation, and the existing supported plasma-refining→plastic shared-surplus fixture. Frozen JSON contains exact spec, selected strip/pack and prepared snapshots; replay decodes those snapshots using the declared owner, then separately checks re-preparation from the same selected inputs. No production import-path shim is installed. The surplus case uses `surplus_outputs={"refined-oil": 1}` so it actually exercises a late output sharing the internal consumer lane.

The probe exercises actual `route_global` and `_build_prepared` (the existing four-phase detailed order), records exact routed/failure/overflow facts, emitted links and neutral-validator findings/skips, and checks one expired attempt plus independently mutated workspaces cannot contaminate another attempt. The neutral validator runs even on stranded emitted diagnostics, without planner acceptance and with explicit fixture-only `expect_power=False`; no `IdMap` is invented, so spec checks requiring one remain explicitly skipped. Baseline coverage is asserted; Main should report any fixture failure rather than weakening it.

Run from the approved worktree with its normal `uv` environment:

```sh
PYTHONHASHSEED=0 uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-13-probe.py freeze
PYTHONHASHSEED=0 uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-13-probe.py replay --output .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-13-baseline.json
```

The source migration is frozen. Main's post-cutover commands:

```sh
PYTHONHASHSEED=0 uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-13-probe.py replay --owner routing_domain --output .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-13-after.json
PYTHONHASHSEED=0 uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-13-probe.py compare
```

Throwaway instrumentation records constructor calls for snapshot/building/index/grid/workspace/net/reservation types, sibling grouping, grid flags/transitions, copy/deepcopy calls, and phase-local traced allocation peaks/times. Compare enforces identical constructor/copy counts and exact routing observations, not arbitrary timing percentages. Traced peak is not a count of every transient allocation: the remaining per-transition proof is unchanged moved function bodies plus Main's review of import-only consumers; no new transition wrapper is planned.

Main owns all execution, frozen observations, affected-module/static checks, disposable-probe cleanup approval and commits. No topology/factory outcome is promoted by this extraction.

## Baseline evidence and landed handoff

Main's reported pre-cutover evidence: freeze/replay EXIT0, four cases routed, each with overflow 0, unreachable 0 and detailed failures 0. Cumulative coverage: source-sharing 4, external arrivals 8, early outputs 9, late outputs 1, incompatible cargo 1, interrupted attempts 4. The first three frozen digests were preserved when the late-surplus case (`9ce450f6` prefix) was appended. Setup corrections were confined to the disposable serializer (actual Pydantic models) and missing late-output fixture; no domain behavior or acceptance assertion was weakened.

Applied: one new `routing_domain.py`, the 234-symbol removal from `freeform.py`, and 28 mapped consumer files. Freeform references its moved dependencies through the `routing_domain` module instead of importing/re-exporting their names. Other production strategies and composed canvases import the neutral definitions directly. Existing private/public spellings remain unchanged. Original moved function bodies, constants, dataclass fields, workspace copying, compatibility grouping and detailed transition/commit policy were transplanted rather than redesigned.

Maintained profiler owners, direct imports, module-attribute references, monkeypatch owner tuples/strings, shared fixture imports and current type/documentation links migrated together. Obsolete imports and duplicate newly-added module imports were removed as part of the cutover. Main retains the sole formatter run; regenerated multi-symbol import blocks need that standard formatting pass.

Source boundary: `freeform.py`, `sequence_solver.py`, `hierarchy/compose.py` and all mapped consumers are no longer being edited by Task13. Tasks14/15 must remain behind Main's replay/review authorization; no completion deadline, BeltAltitudeRules constructor, band envelope or packing-policy changes were made here. No trace/channel/race/web source or corresponding tests were touched.

Main-owned remaining proof:

1. Run the two post-cutover replay/compare commands above against `task-13-fixtures.json` and `task-13-baseline.json`; do not regenerate controls.
2. Run the standard source formatter/static checks once settled. Review the moved-body equivalence and absence of domain→strategy imports/re-export paths; the exact original module/ranges are in the frozen map.
3. Run affected modules once settled: `tests/layout/test_global_router.py`, `test_route_kernel.py`, `test_last_mile.py`, `test_geometry_memo.py`, `test_freeform.py`, `test_sequence_solver.py`, `test_strip_variants.py`, `test_coater_node.py`, `test_finalize.py`, `test_slots_ports.py`, `tests/layout/hierarchy/test_compose.py`, `tests/indexed/test_nets.py`, `tests/bench/test_route_profile.py`, `tests/scripts/test_route_profile.py`, and `tests/test_pipeline.py`; include the existing rules tests consuming `tests/rules/probes.py` and registry lint ownership.
4. Retain independent physical-legality evidence: the probe records neutral validator findings/skips, but intentionally does not invent IdMap/spec-flow certification, production power, or a final projected factory certificate. Existing original proof modules/factory baselines remain required and unchanged.
5. Compare constructor/copy profiles exactly; instrumented wall/peak values include observer overhead and are not speed claims. Main reviews that no new wrapper/allocation entered the verbatim detailed transition bodies.
6. Main owns disposable probe/evidence cleanup, review and commit. Post-cutover behavior, static cleanliness and factory success are not claimed by this worker.
