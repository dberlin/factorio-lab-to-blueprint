# Transport-First Construction Experiment Plan

> **Execution:** Approved by the user in this conversation. Execute inline using the executing-plans workflow; no subagents, commits, merges, pushes or production promotion. This is an architectural experiment, not a new production strategy.

**Goal:** Determine whether a concrete capacity/access-planned transport topology removes the large-factory coverage obstacle without unacceptable band or footprint cost.

**Architecture:** Reuse canonical production candidates, physical strip variants, exact directed flow allocation, belt mechanics and global settlement. Plan technology-aware access and capacity before packing. First prove compact risers and fully serviced strip interfaces; do not price every connection as a low-altitude ramp. Reject a specific topology at its first demonstrated physical or integration gate; do not confuse its failure with geometric infeasibility of the original factory.

**Tech Stack:** Existing Python 3.14 environment, exact Fraction rates, current DSP catalog, Cython/Python routing kernels, existing finalization/validation/encoding. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md`, sections 1 and 5D, plus the user-approved strategic reassessment in this conversation. The focused joint-repair plan is an optional diagnostic, not a prerequisite.

## Prior checkpoint and upstream ownership

- The seven canonical comparison cases are frozen under `.superpowers/sdd/2026-09-08-transport-first/frozen/`.
- The original channel preflight assumed the router's four levels and ramp-like access. That is not a necessary geometric bound: the original requests permit vertical construction and belts up to 26.55 tiles high. Its footprint estimates describe that restricted construction only, not the required transport-first footprint.
- `mechanics.py` emitted same-column vertical transitions and overhead crossings. The selected physical checks reported zero errors with vertical construction enabled and four `geom.altitude_step` errors in the locked control. This is a mechanics witness, not original-factory acceptance.
- Before the ownership change, one process-local `vertical_probe.py` ablation on the original unsprayed mall offered overhead macros ahead of the existing search. It found 50 macro paths but refused with three failed nets after 24.68 seconds. A found macro is not a committed, validated connection. This does not establish a successful topology or justify another sweep.
- **User assignment, now resolved:** another agent fixed the routing-capability issue on master. This experiment resumed in `.claude/worktrees/transport-first-current` at `f93f84b609d61efb54b6c52212e4f1a4ac4195d0`; no duplicate vertical-router change was made.
- Independent work continues on local spray-service specimens and concrete strip connection interfaces. Any derived one-recipe specimen is explicitly outside original-factory acceptance and cannot substitute for composition.
- `serviced_strip.py` then exercised two explicitly derived local requests using unchanged production machinery. One ray-receiver machine with five input items and five spray coaters settled in 1.77 seconds: area 256, 272 decoded buildings, all 67 checks, zero errors or skips. The twelve-machine universe-matrix specimen (six inputs) exhausted its 25-second construction allowance. Both results are retained; neither is original-factory coverage, a precomputed reusable strip implementation, or a composition proof. Do not repeat the failed specimen with guessed configurations.
- The upstream correction is present in the current isolated experiment. The results below supersede the old four-level footprint estimates, not the frozen requests or original-spec acceptance contract.

## Executed decision: central-bank topology is NO-GO

The experiment reached a decisive construction refusal, not original-factory
coverage. No production integration, commits, merges, pushes, broad suite or
parameter sweep followed.

### Concrete construction and evidence

- `transport_first.py` captures the existing directed flow allocation before
  admission, retaining endpoint ownership, cargo domains, prelinked obligations
  and shared-root membership. It reserves coater sites before placement, keeps
  node-to-machine service links local, allocates three-column-pitch access bays,
  and colors trunk intervals across twelve even/odd altitude pairs within the
  original 27-level technology domain.
- `channel_probe.py` restricts detailed searches to the allocated module,
  access-leg, boundary-comb and trunk cells. Admission's non-emitting probes are
  separate. The boundary straight-line shortcut is forced through the constrained
  search; sparse connector shortcuts are disabled because endpoint-only edges
  cannot certify that intermediate geometry stays on this graph.
- `planned_service.py` proved complete one-strip local factories: ray receiver
  1.6865 s, area 380, 231 decoded buildings; universe-matrix lab 1.8687 s,
  area 460, 290 decoded buildings. Each ran all 67 checks with zero errors/skips.
  The earlier twelve-machine specimen is twelve strips, not one strip.
- `channel_mechanics.py` emitted orthogonal channel pairs reaching level 26:
  all 20 selected physical checks passed. Locked technology produced 12
  altitude-step errors. A two-consumer shared-source route passed the same 20
  checks after the existing canonical slot-binding post-pass. These are
  component witnesses, not factory certificates.

| Frozen case | Planned core frame | First applicable outcome |
| --- | ---: | --- |
| Original unsprayed mall | 1081 × 154 | Band refusal |
| Original coated mall | 1073 × 154 | Band refusal |
| Original three-output | 270 × 154 | Physical routing refused |
| Original universe-matrix | 1374 × 154 | Band refusal |
| Held-out mall, demand 3/4 | 889 × 154 | Band admits; downstream not run |
| Held-out mall, demand 5/4 | 1233 × 154 | Band refusal |
| Held-out unsprayed universe | 963 × 151 | Band admits; downstream not run |

The unchanged three-output integration attempt completed in 25.0191 s, including
7.2947 s preparation and 17.4369 s detailed routing. It retained 13 routed
obligations and 14 failures out of 27. There were 66 constrained queries,
19 returned paths, 2,910 checked path cells and no unmapped endpoint queries.
Settlement was not reached. Its bounded refusal is not geometric infeasibility.
The 30-second total allowance retained five seconds for settlement; it was not
raised. No successful original mall exists to cold-repeat.

Held-outs used the same frozen construction rules after the primary topology
was fixed. Only their upstream geometry gates ran: downstream full-factory runs
would not repair the already-failed primary integration gate.

### Measured next investment

Access width, not the four-level router ceiling, dominates this construction.
Sharing proliferator service locally reduces the coated mall's priced frame to
959 × 154, which fits, but leaves universe-matrix at 1054 × 154, which does not.
The complete original spray rates themselves fit one 30/s lane, so the per-strip
service-capacity price is conservative without allocating spray by machine count.
These are cost-only projections; physical module service-root composition was
not implemented or claimed.

Optimistically multiplexing dedicated access columns across altitude pairs
reduces the priced widths of the original unsprayed mall/coated mall/universe
to 523/401/417. This is not an admitted geometry: cross-layer transitions and
shared-column conflicts remain unproved. It identifies the resource a redesign
must address rather than justifying another global search or spacing sweep.

**Decision:** reject this central-bank, dedicated-access-column topology.
Retain transport-first serviced units as a research direction. The next
architectural gate must be a physically compiled shared/distributed access
interface with exact capacity and boundary ownership, connected between units
and judged against the unchanged combined spec before attempting another mall.
Do not implement a new backend or general hierarchy from these results.

### Reproduction and retained artifacts

Working directory: `.claude/worktrees/transport-first-current`.

```sh
PYTHONPATH=.superpowers/sdd .venv/bin/python -m 2026-09-08-transport-first.analyze_topology
PYTHONPATH=.superpowers/sdd .venv/bin/python -m 2026-09-08-transport-first.channel_mechanics
PYTHONPATH=.superpowers/sdd .venv/bin/python -m 2026-09-08-transport-first.run_experiment three-output .superpowers/sdd/2026-09-08-transport-first/control-reproduction.json
```

Evidence lives under `docs/superpowers/evidence/2026-09-06-feasibility-first/transport-first/`.
The isolated `.superpowers/sdd/2026-09-08-transport-first/` directory retains the
throwaway scripts, unchanged frozen specs, local blueprints/reports, full plans
and the refused original-control result. Early adapter failures and the raw
pre-slot-binding mechanics report are diagnostic history, not topology verdicts.
No permanent production code or tests were added.

The checklist below records the original acceptance contract. Unchecked
downstream completion requirements were not passed; the decision rule explicitly
allows rejecting a construction at its first demonstrated gate.

## Global constraints

- Preserve original recipes, counts, rates, technology, cargo domains, output and drainage obligations, liveness, allowed external supply and band policy.
- One complete blueprint; no player loops, independently re-solved blocks, partial-result-derived specs or relaxed validation.
- Preserve existing successful solver behavior and all retained diagnostics. Keep experimental adapters outside `src/`.
- Compare cold layout-through-settlement time under 60 seconds for malls and universe-matrix, 30 seconds for the three-output control, eight workers where the existing machinery uses them. Record request preparation separately.
- Complete original-spec settlement, all registered checks without skips/errors, and decode are required for a CLEAN result. A physical or band preflight is never CLEAN.
- A topology refusal is not a factory infeasibility proof. Report the exact limitation and whether it is an upper-bound cost of this construction or a necessary bound.
- No repeated parameter family, raised search limits or full suite during architecture selection.

## Frozen experiment cases

Before topology tuning, freeze canonical requests and SHA-256 spec identities for:

1. Original mall, no-proliferator.
2. Original mall, all-products.
3. Original three-output control, no-proliferator.
4. Universe-matrix, all-products.
5. Held-out mall at 3/4 requested demand, no-proliferator.
6. Held-out mall at 5/4 requested demand, no-proliferator.
7. Held-out universe-matrix, no-proliferator.

Demand variants must modify typed request objectives before canonical rate solving; never scale emitted machines or alter a canonical spec after solving. Keep variants unexamined until the primary topology is fixed. Retain the already-measured original solver results as baseline evidence; do not rerun the failed configuration family.

## Files and ownership

- Create `.superpowers/sdd/2026-09-08-transport-first/transport_first.py`: experimental transport extraction, channel plan and physical probe. Temporary, not production API.
- Create `.superpowers/sdd/2026-09-08-transport-first/run_experiment.py`: cold worker driver, frozen manifest, outcomes and artifact verification.
- Record results in `docs/superpowers/evidence/2026-09-06-feasibility-first/transport-first/` after the experiment.
- Read-only reuse on the corrected baseline: `layout/freeform.py` (`plan_strips`, `_build_prepared`), `layout/routing_domain.py` (emission, exact flow preparation, admission, detailed routing), `layout/slots.py`, `layout/finalize.py`, `layout/validate.py`, canonical candidate APIs and blueprint codec. The old `pipeline.settle_attempt` API is absent; settlement follows the current pipeline's compaction, finalization, original-spec judgment, marking and encoding sequence.

## Task 1: Freeze requests and extract physical transport demands

- [x] Load the four primary canonical candidates through `load_case(case, (CandidatePolicy(policy),))` and save their unmodified `model_dump_json()` values and original URLs.
- [x] Freeze held-out request variations using `dataclasses.replace` on parsed typed objectives, then canonicalize and solve once. Save exact objective rates and canonical specs.
- [x] Use `plan_strips(spec, strip_len=48, band_policy=BandPolicy('portable'))`. The limit is fixed for this experiment; intrinsic capacity/geometry partitioning remains authoritative.
- [x] Capture the existing preparation's transport inventory before admission chooses roots/port corridors. Reuse its directed flow repair and shared-external grouping instead of deriving connectivity from recipe balances. A process-local capture wrapper must restore the original function on every exit.
- [x] Record lane endpoint identity, item/domain, source/sink strip ownership, physical offset and shared-root membership. Preserve prelinked piler transitions as fixed, not route demand.

## Task 2: Construct and price an explicit channel topology

- [ ] Implement immutable `TransportDemand`, `AccessBay`, `TrunkTrack` and `ChannelPlan` records in the experimental module.
- [ ] Allocate access space from endpoint multiplicity and legal ramp/junction footprints, not a uniform extra-clearance parameter.
- [ ] Place strip banks around those access bays. Assign horizontal trunk intervals to non-overlapping tracks with deterministic interval coloring. Separate incompatible cargo; never collapse distinct capacity obligations merely because the item matches.
- [ ] Account for full machine boxes, input/output access, junction/ramp turning room and reserved trunk space in the frame. Use the current band envelope for admission.
- [ ] Independently verify track overlaps, endpoint assignment completeness and physical dimensions in the executable probe. Report the planned topology's area, port count, maximum simultaneous trunk demand and band-fit outcome.
- [ ] If the concrete topology cannot fit, retain its explicit geometry and classify that construction as refused. Inspect whether sharing or distributed channels removes the specific overhead before considering any larger architectural implementation; do not route a known out-of-band plan.

## Task 3: Prove physical mechanics and full completion where admitted

- [ ] Materialize representative crossings, access ramps and branch/merge structures through current belt/junction primitives. Check actual emitted geometry, not only lattice disjointness; retain counterexamples.
- [ ] Exercise modern high-fan-in strip access, multiple capacity lanes and coater service. A failed mechanics witness is a NO-GO for that topology until redesigned, not permission to omit the mechanic.
- [ ] For a band-admitted mechanically supported plan, prepare with the planned frame/access allocation and constrain route queries to its allocated channel graph. Do not allow unrestricted global routing to masquerade as a topology success.
- [ ] Route/complete with the existing ledger and completion machinery, then settle against the original saved candidate using the current pipeline sequence. Verify all checks and decoded building count; retain every refusal and phase duration. **Not reached:** the original control refused during physical routing.
- [ ] Stop launching downstream routing runs if the upstream topology or mechanics gate has already rejected that case. Record downstream gates as not reached, not passing.

## Task 4: Measure generalization and decide the next investment

- [ ] Exercise the frozen held-out demand/policy cases after fixing the topology, with the same geometry rules and budgets.
- [ ] Cold-repeat a successful original mall three times before claiming repeatable new coverage. Compare the coated mall/control against recorded baseline latency, dimensions and area; report absolute as well as relative overhead.
- [ ] Produce an evidence-backed verdict: continue this topology, redesign its demonstrated bottleneck, or reject it. A new backend/general hierarchy implementation requires successful original-spec integration, not a promising packing result.
- [ ] Update this plan with actual commands, outcomes and which gates were not reached. No broad suite is warranted if only the isolated experiment changed.

## Decision rule

The hypothesis is supported only by complete original-spec factories that use the allocated transport structure and show useful generalization. A band rejection or physical counterexample can reject the specific channel construction cheaply and decisively. Neither result justifies rebuilding the whole application. The next architecture must address the measured limiting resource—track demand, endpoint interfaces, junction geometry, band shape or completion coupling—rather than hiding it behind more retries.
