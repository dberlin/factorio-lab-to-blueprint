# Task15 — fixed-domain band packing baseline preparation

Status: Main ran all three baseline and all three integrated packing modes EXIT0. The mixed witness now selects an admissible physical box, routes all three cuts, projects, and passes the full researched-policy judgment. Source remains frozen for Main's focused regressions/static gate/independent review. **No test/build/lint/formatter/benchmark/runtime/proof command was executed by this worker.** Broader factory reliability remains outside what these concrete transport witnesses establish.

## Pre-cutover source contract

`hierarchy/compose.py::pack_blocks` currently enumerates the nine existing scale factors `(0.85, 1.0, 1.15, 1.3, 1.5, 1.8, 2.2, 2.8, 3.6)` through `_skyline`, retaining minimum area with stable first-on-equal ordering. It admits `min(width, height) <= BAND_MAX_ROWS` with `BAND_MAX_ROWS = 160`, irrespective of the requested explicit band or circumference. `_pack_at` calls it without the final requested policy. `pack_with_access` retains its finite `GAP_LADDER`, local/trunk reservation funding and partial/degraded distinctions. `compose` already receives `policy` and uses it for actual Coater junction preparation before `_route_all`.

The final requested policy is already passed by hierarchy strategy. Block-local policies remain portable because `_normalize` and translated composition clear/replace local frames. Nothing in Task15 authorizes changing child policy, width candidates, gaps/rungs, router funding, reservation tie-breaking, skyline placement, or final projection.

`BandPolicySearchEnvelope.frame_candidates(width, height)` owns both rotated extent feasibility and circumference admission. Its `perimeter` is added to both sides of the queried dimensions. `_pack_at` supplies complete normalized physical block bounding boxes, so **perimeter=0** is the honest envelope for this selection: the optional `_limit_margin` is free routing ground, not an emitted permanent rim. Actual belts, Splitters, power and colliders may enlarge the result after routing; a pre-route fit is not a final acceptance certificate.

## Exact staged witness

`task-15-packing-probe.py` constructs these fixed physical blocks:

- Mixed witness: `[(80,40), (80,20), (80,20), (80,20)]`.
- Requested policy: `BandPolicy("50x800")`.
- Gap floor: 2; all existing rungs and width candidates remain unchanged.
- Each block is one connected U-shaped iron-ingot belt run: a complete lower row, eastern connecting leg, and complete upper row. Both endpoints lie on real horizontal runs that the existing composer can tap. There are no sentinel buildings, fake padding belts disconnected from the lane, or invented routing-margin extent.
- Three actual `LaneFlow`s connect block tails to subsequent heads. A belt-only BuildSpec declares one iron-ingot external input and one output. This is a transport/geometry witness, not a representative production-factory benchmark.
- Native `_skyline`, `pack_blocks`, reservation, `_route_all`, power infill and finalizer all execute. Wrappers record inputs/results but never replace verdicts.
- Each packing rung records every real skyline candidate, target, offsets, physical width/height, area, and exact frame choices. The script requires at least one fitting and one non-fitting candidate, and observes the selected physical extent at the actual `_route_all` call.

Analytical expectation, **not measured**: the first narrow target can select the single-column `80x106` minimum-area packing, which has no 50-row orientation. The same finite domain also includes a wider, shallower fit (e.g. `244x42`) that the requested envelope admits. The source selection, not a reimplemented skyline, determines and records the actual result. If routing is never reached, or the real selected box does not reproduce the mismatch, the script fails and the payoff remains unproved.

Controls use the same concrete belt geometry and actual composition path:

- `--case rotated`: one `20x80` block. The exact requested envelope must offer only rotated frames.
- `--case overflow`: one `801x20` block. It passes the old 160-row surrogate in one axis but exceeds the requested band's 800-cell circumference; rotated latitude height also fails. The script requires no exact frame and a retained final projection refusal. No new packing algorithm is implied by that refusal.

The output reports reservation/routing status, routing entry budget, actual gap and pre-route physical box separately from `canvas.limit`, composed physical extent, final projection outcome, and the real Task4 `judge_placement` Report if projection succeeds. Routing or flow/power failures are preserved verbatim, not hidden to claim successful packing.

## Safe exact Main commands

From abstraction-general, with a finite outer subprocess timeout (e.g. 90 seconds), capturing stdout/stderr under distinct plan-directory log names:

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-15-packing-probe.py --case mixed --expect old --budget 30
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-15-packing-probe.py --case rotated --expect old --budget 30
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-15-packing-probe.py --case overflow --expect old --budget 30
```

After explicitly released source cutover, run the identical physical cases and budget with `--expect envelope` (the wrapper passes the real new keyword through; no signature inspection/compatibility translation):

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-15-packing-probe.py --case mixed --expect envelope --budget 30
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-15-packing-probe.py --case rotated --expect envelope --budget 30
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-15-packing-probe.py --case overflow --expect envelope --budget 30
```

Do not infer a reliability improvement merely from `frames` becoming nonempty. Compare actual selected routing shape, routed-cut count, final physical extent, projection and full Report findings under unchanged budgets. The script never asserts all cuts must route or final validation must pass merely because the pre-route envelope fits.

## Implemented bounded source cutover

After Main's baseline proof and explicit release, serialized with Task14:

1. Resolve `band_policy_search_envelope(policy, perimeter=0)` once at final composition entry, while hierarchy retains the requested policy and portable child behavior.
2. Require/thread that concrete envelope through `pack_with_access` and `_pack_at` into `pack_blocks`.
3. Replace only candidate admission `min(width,height) <= 160` with `bool(envelope.frame_candidates(width,height))`. Keep the current candidate loop, fallback, area key and tie-breaking exactly.
4. Remove `BAND_MAX_ROWS` as a production authority if the complete consumer inventory finds no legitimate remaining use. Update the now-obsolete packing/GAP_LADDER prose rather than retaining a second feasibility explanation.
5. Migrate actual direct callers and tests to explicit envelopes; no old-signature aliases/introspection/default fallback. Keep final projection and all reservation/router failure paths intact.
6. Main runs exact old/new routing witnesses plus focused existing hierarchy/finalizer cases, reviews and commits. These disposable scripts are removed only after that proof.

Domain consumer requirements were sent to RoutingDomainImplementation: Task15 consumes the existing envelope only; it must not reintroduce Freeform private policy ownership or convert the optional routing margin into permanent geometry. Main retains mutation sequencing.

## Main-run baseline evidence

Main reports these exact observations from retained logs:

- `task-15-mixed-baseline.log`: the existing finite domain contains fitting `244x42` and `326x40` packings, but selects `80x106`. That actual physical box reaches the unchanged router, all **3/3** flows route, and final projection refuses the requested narrow band. This is a discriminating packing→routing witness, not just a policy argument echoed by a stub.
- `task-15-rotated-baseline.log`: physical `20x80` becomes `80x20` through real projection and validates cleanly.
- `task-15-overflow-baseline.log`: physical `801x20` retains the final projection refusal.

All three commands exited zero. These observations establish the pre-cutover mismatch and controls only. The same inputs/budget must run after envelope threading before any improvement in final output is claimed. No width/gap/rung expansion is authorized or needed by this witness.

## Frozen scope and Main proof handoff

Only `layout/hierarchy/compose.py` production packing behavior changes: one `perimeter=0` exact requested envelope is resolved by `compose`, required through `pack_with_access` and `_pack_at`, and consulted by `pack_blocks` in place of the 160-row surrogate. The obsolete constant and its `__all__` entry are removed. The nine targets, skyline implementation, area/stable-tie ordering, fallback, gap ladder, reservation/router funding, portable children, and final projection remain intact.

`tests/layout/hierarchy/test_compose.py` direct calls now pass concrete envelopes. The retained gap/non-overlap test asserts actual envelope admission; the former 160-row test now uses the discriminating 80×40 + three 80×20 candidate set under `50x800`, rejecting the smaller-area but inadmissible shape. No source-text or argument-copy assertion was added.

Main ran the three `--expect envelope` commands above into distinct `task-15-*-integrated.log` files successfully. The focused regression command remains Main-owned:

```sh
uv run pytest -q tests/layout/hierarchy/test_compose.py::test_pack_blocks_keeps_a_two_tile_gap_and_prefers_a_band_legal_shape tests/layout/hierarchy/test_compose.py::test_pack_blocks_rejects_smaller_area_outside_selected_band_envelope
```

Those commands remain unexecuted by this worker. Preserve routing failures/collision evidence rather than weakening the report to claim success. The separately approved v6 collision/mall work is outside this source cutover.

## Main-run integrated evidence

Read from the retained integrated logs; Main reports EXIT0 for all three:

| Case | Selected physical box | Actual router entry | Final outcome |
|---|---|---|---|
| Mixed | 244×42, gap 2, one packing selection | 244×42, 3 nets, 3/3 routed, no failures | Physical 244×42; projected frame 244×42, band 160, unrotated; full Report clean |
| Rotated control | 20×80, gap 2, one packing selection | 20×80, zero cut nets | Physical 80×20 after rotation; frame 80×20, band 160; full Report clean |
| Circumference overflow | 801×20, gap 2, one packing selection, no exact frame | 801×20, zero cut nets | Retained `game.blueprint_area` refusal: 801×20 exceeds requested 800×50 capacity |

The mixed baseline selected 80×106 and routed 3/3 before final projection refused. On the identical physical inputs and 30-second budget, the integrated run selects the existing 244×42 candidate, routes the same three cuts, reports no composition failures, and passes real final projection and judgment. This is the bounded observed payoff of exact-envelope admission; no extra width/gap/rung search was added.

Router canvas limits remain separate from physical geometry: mixed `[-8,-8,251,49]`, rotated `[-8,-8,27,87]`, overflow `[-8,-8,808,27]`. The free routing margin was not counted as a permanent rim. The rotated and overflow controls retain their baseline dispositions. Measured single-run elapsed values are not a runtime benchmark, and success of this connected-belt witness is not a claim that the separately scoped titanium collision/mall cases are fixed.
