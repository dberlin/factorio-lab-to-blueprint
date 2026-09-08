# Task 2 — Piler-aware producer boundaries

Status: implementation staged and ready for Main's proof/review; NOT a PASS or committed completion. No validation command or physical smoke was run by this implementer.

## Changed files and symbols

- `src/flab2bp/layout/markers.py`: `input_belt_heads` uses indexed transport predecessors, retaining intentional Splitter-port exclusion; `output_belt_tails` walks indexed transport adjacency through Pilers, stops at Splitters/attached Splitter belts, retains original sorter-fed root selection and sorted unique terminal-belt results.
- `tests/layout/test_markers.py`: exact retained five-record real-catalog fixture `_piler_output_placement`; confirmed output/input boundary regression; serial-Piler/shared-producer-tail/external-input regression. The shared producers merge on an ordinary belt before the single Piler input, not two invalid Piler input attachments.
- `tests/layout/hierarchy/test_contracts.py`: exact retained rated boundary regression with `BuildSpec(groups=(), outputs={"gear": Fraction(1)})`; two producers sharing the piled tail plus an independent output tail assert exact2/3 and1/3 rate attribution, no duplicate tail and no fictitious input.
- `src/flab2bp/layout/hierarchy/contracts.py` intentionally unchanged: `boundary_lanes` already consumes marker endpoints and owns sorter-fed/drawn exclusions and exact `_apportion` policy. Its source needed no duplicate Piler branch. `_machines_on_lane` already crosses Pilers through `belt_run` with its deliberate broader host policy.
- Freeform `_output_tail_nets` is the actual additional endpoint consumer, migrated in Task1 and documented there. It retains its distinct item-specific output-selection/Splitter traversal policy.
- New handoff-only `.superpowers/sdd/2026-09-08-abstraction-repairs/piler-transfer-smoke.py` prepares physical proof for Main.

## Complete caller inventory and preserved policy

| Boundary owner | Direct consumers | Policy |
|---|---|---|
| `input_belt_heads` | `mark_external_belts`, `unmarked_external_inputs`, hierarchy `boundary_lanes` | No incoming belt or host transport edge; existing Splitter port exclusion remains; no ownership inference from item labels |
| `output_belt_tails` | `mark_external_belts`, hierarchy `boundary_lanes` | Original sorter-fed belt roots, transit through serial Pilers, intentional Splitter boundary stopping, sorted unique tails; malformed/nontransport outgoing link is not declared an exposed tail |
| hierarchy `boundary_lanes` | `hierarchy/strategy.py` endpoint collection (original line780) | Sorter-fed/drawn exclusions and exact per-item total apportionment remain in hierarchy |
| `_machines_on_lane` / `_apportion` | hierarchy `boundary_lanes` | Machine weighting and strip fallback unchanged; no whole-deficit assignment per lane |
| freeform `_output_tail_nets` | `_build_prepared` | Cargo-filtered late-tail selection; unlike marker policy, intentional router traversal may cross Splitters |
| `_links_splitter` | marker input/output discovery | Retained deliberately: this is boundary policy, not an obsolete adjacency walker |

Fresh LSP references attempt failed as recorded in task-1-report.md; scoped full source/test inventory supplied the fallback. No alias/shim or second transport helper was retained.

## Confirmed baseline evidence

Read-only root evidence is `docs/superpowers/evidence/2026-09-08-abstraction-review/flab-abstraction-review-probe.py` and `.log` at baseline `bbc8889d`.

The exact five records are assembling-machine-1(recipe1), sorter-1(input0/output2/gear), belt2(output3/gear), automatic-piler3, belt4(input3/gear). Retained output: marker tails `[]`, marker heads `[2,4]`, hierarchy tails `[]`, hierarchy heads `[4]`. Expected corrected tail is4 at exact rate1, never external input4. This fixture is explicitly logical, not physical paste proof.

## Selectors

```sh
uv run --locked pytest -q tests/layout/test_markers.py tests/layout/hierarchy/test_contracts.py
```

Key new regressions:

- `tests/layout/test_markers.py::test_piler_transit_preserves_producer_boundary`
- `tests/layout/test_markers.py::test_serial_pilers_preserve_shared_tail_and_external_input`
- `tests/layout/hierarchy/test_contracts.py::test_piler_transit_preserves_rated_producer_boundary`
- `tests/layout/hierarchy/test_contracts.py::test_shared_piled_tail_is_counted_once_and_keeps_exact_machine_weight`

Existing `test_marks_external_input_heads_and_output_tails_without_touching_other_belts`, `test_splitter_port_belts_are_not_encoded_as_external_endpoints`, hierarchy `test_boundary_lanes_rates_tails_and_heads_and_excludes_the_internal_lane`, strip-weighted tails, stripless docked tails/heads and port-host supply tests remain the ordinary-lane/Splitter/external-input/exact-rate controls. Run Tasks1+2 together using Task1's focused command, then Main's touched-test batch.

## Small real piled transfer prepared for Main

```sh
uv run --locked python .superpowers/sdd/2026-09-08-abstraction-repairs/piler-transfer-smoke.py
```

The script constructs a real one-machine arc-smelter `BuildSpec`, consuming1 iron-ore/s and producing1 iron-ingot/s, stacks unlocked. Explicit legal Pile Sorter research is pick2/place1 and only that tier is selected; canvas tiers, sorter stacks and lane stacks are derived from the spec using the production preparation helpers. It uses `plan_strips`, assigns one explicit valid low-throughput `PilerPlan` to the output lane, and materializes with the existing `_emit_strip`/`junction.make_piler` owners. It does NOT inflate rates to force automatic piling or claim automatic selection is proven. This avoids the existing40/s single loose-lane fixture's pre-Piler bottleneck as physical evidence.

Observed path on Main's successful rerun: real layout emission -> shared `slots.assign_sorter_slots` completion (also assigns belt slots, exactly as `_build_prepared` does) -> portable `finalize_placement` -> `mark_external_belts` -> full validator with `expect_power=False` -> rated `boundary_lanes` -> deterministic codec encode(timestamp0) -> decode/hash/host-link/slot/icon assertions. Power is intentionally outside this fragment's contract; no other validator subset or waiver is used.

Expected observables: exactly one prelinked Piler transition, one rated iron-ingot tail with supply1, one true iron-ore head with demand1, no Piler output counted as input, decoded output belt names the Piler at input slot0 and retains its product marker. Finalized frame must exist. The decoder building count and envelope hash are checked.

The run retains exact spec, raw and slot-completed materialized records, validator findings, emitted `blueprint.txt`, and result/sha256/frame summary under `.superpowers/sdd/2026-09-08-abstraction-repairs/piler-transfer-evidence/`. Main's first run EXIT1 is retained in `piler-transfer-smoke.log`: this fixture omitted the mandatory slot-completion pass and used a default Mk.I sorter against stack2 input. The repaired fixture invokes actual shared completion and derives researched Pile Sorter/lane capabilities from its explicit spec. No production or validator change was made for those setup failures.

Main reported r2 EXIT0 in `piler-transfer-smoke-r2.log`:9 decoded buildings; Piler6 feeds output tail7; supply1 iron-ingot/s; external demand1 iron-ore/s on head0. The finalized portable7x5 frame is certified for bands4/8/16. Full validator without power is clean. Encoded bytes:348; SHA256 `68bcbf7b549617ace3c2b82281c0f8c94d4ae2bb6b79c26cdf78cc87addc0858`. The successful run reached every decode/hash/slot/icon/boundary assertion in the retained script. This is physical materialization/finalization/encoding evidence, not an in-game paste or automatic pile-selection claim.

## Pending proof / integration risks

- Physical smoke evidence is retained above; no broader solver or factory success follows from it.
- Main must run green tests and independent review before accepting/committing Tasks1/2.
- Exact shared-tail weights preserve the existing broader hierarchy host policy; changing `belt_run` behavior is out of this batch.
- The fixture proves explicit real piling materialization, not the factory planner deciding to pile, an in-game paste, or any topology/hierarchy release gate.
- A late editor diagnostic on the smoke could not see new inherited Buildings methods (workspace resolver/server issue); actual current-worktree runtime/type proof remains Main-owned. Its separate nullable-frame warning was addressed with an explicit frame assertion. No diagnostics command was run here.
