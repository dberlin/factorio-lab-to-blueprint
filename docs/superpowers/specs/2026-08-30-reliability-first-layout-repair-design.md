# Reliability-First Layout Repair

## Goal

Make the shipped Freeform and SequencePair strategies reliably produce validator-clean factories for the reported failure corpus without increasing deadlines, worker counts, routing budgets, stage counts, arrangement counts, archives, or islands.

Correctness outranks minimum area. The implementation may spend up to 10% geometric area relative to the current clean baseline when the extra space is needed for a legal result. Exact finalization and validation remain authoritative.

## Evidence and Failure Domains

The reported failures are independent contract breaks. One global clearance or one larger search budget would hide symptoms while leaving the violated contracts intact.

1. **Projected same-strip collisions.** Flat collider pitch can become illegal after longitude projection. Shared padded physical variants now exist and Freeform consumes exact pitch feedback; SequencePair still needs the same stage-boundary repair path.
2. **Projected staged-static collisions.** Spray Coaters and other ownerless staged statics can collide with already emitted machines after projection. Ownerless failures cannot map to strip-pitch or different-strip feedback, so their projected legality must be checked before staging.
3. **Spray Coater/Splitter clearance.** Coaters are placed before detailed routing creates Splitters. The existing prospective check snapshots an empty Splitter set, while the finalizer later rejects lateral projected keepout violations.
4. **Sprayed/unsprayed lane contamination.** Rate solving correctly identifies items that feed both proliferated and unproliferated consumers, but layout lane and net identities retain only the item. Sharding, merging, shortcuts, and island balancing can reunify flows that must remain separate.
5. **Power coverage outside the core.** Power planning covers `core`; routing may later create powered Splitters in the two-tile internal route ring. Those future receiver tiles are absent from the power demand set.
6. **Band-policy blindness.** The authoritative catalog has 12 band sizes. Existing data matches through band 160 but incorrectly models equator band 200 as 1000x161 instead of 1000x160. Separately, both strategies generate candidate heights without the requested band policy, so band 120's legal 600x25 orientation is never searched even when a 25-row frame is feasible.
7. **Freeform packing/router contract gap.** Detailed routing returns typed failures, walls, blockers, and stable net identities, then `_sweep` reduces that evidence to a failed-net count. `_pack` gives minimum width strict priority over routing proxies and rewards direct insertion that `_bridge` may not realize. Known inaccessible assignments are retried without a targeted repair.
8. **Separate candidate-selection UX defect.** The public API exposes a numeric candidate count even though the frontier has three named policies. The user requested named checkboxes, but this does not repair a layout failure and therefore remains a separate follow-up plan rather than part of the reliability critical path.

## Non-Negotiable Invariants

- `finalize_placement` remains the sole authority for projected band legality.
- `validate` remains the sole acceptance authority for flat mechanical and flow correctness.
- A failed or invalid placement never becomes an incumbent.
- No failure is suppressed, downgraded, or converted to success.
- Every feedback mechanism is derived from structured evidence and scoped to the implicated geometry.
- Every later phase that may emit a powered building is represented in the earlier power-demand envelope.
- Spray domain is part of cargo identity wherever lanes or nets can merge.
- Explicit band policy constrains search before expensive preparation; an empty frame-candidate set is infeasible, not vacuously unconstrained.
- Ordinary physical variants remain default. Extra clearance is reactive or proved necessary by a prospective exact check.
- The separate candidate-policy cutover uses named explicit policies and rejects an empty selection.
- No correctness task raises time budgets, expansion limits, stage counts, arrangement counts, worker counts, archives, or islands.
- The queued power-legality cache lands only after the correctness gate, with parity tests proving identical selected sites and first-failure evidence.

## Shared Geometry Feedback

### Same-strip pitch

Finish the existing projection-safe pitch design. SequencePair extends its current `StageBoundaryTransform`; it does not add a second callback or a parallel retry subsystem.

A stage observation carries the original ordered `projection_failures` and an optional `pitch_requirement`. At a stage boundary:

- regenerate the one implicated family/pose with the minimum required pitch;
- replace only the selected variant in the primary feedback state;
- expose the replacement in the shared immutable variant table;
- migrate states that reference a superseded padded variant;
- leave ordinary selections unchanged in sibling states;
- charge the transition to existing stage work.

### Different-strip and staged-static projection

Keep exact finalizer failures as evidence, but stop allowing unrelated strip movement to erase a learned relation. Freeform and SequencePair must both consume different-strip projection evidence through their existing feedback boundary. A smaller pair-scoped no-good is legal only when the exact projection predicate proves that pair relation independent of other geometry; otherwise use one shared immutable `ExactPackNoGood(height, outline, width, origins, evidence)` representing the full assignment.

Ownerless or non-strip staged statics are not repairable by strip-pitch feedback. Before commit, enumerate their existing deterministic seat/offset alternatives and test each against existing statics over the same reachable projection envelope used by finalization. Choose the first projection-safe seat. If every seat fails and the relation depends on the pack, emit `ExactPackNoGood` so repacking cannot repeat it unchanged. If the relation is invariant inside one strip, derive a typed staged-static clearance requirement and regenerate an on-demand physical lane/attachment variant with the next deterministic seat offset or one-tile lane extension; its geometry is part of variant identity and uses the existing strategy feedback paths. Exhausting those bounded physical alternatives produces an explicit terminal structured projection refusal. Do not assign fake strip owners, and do not merely move an invariant failure earlier.

## Prospective Spray Coater/Splitter Legality

After coater seats are fixed and before routing begins, compute the projection-aware set of forbidden Splitter junction tiles. Use `finalize.projected_coater_splitter_failure` over every reachable frame/projection and merge those cells into `_prepared_junction_ban`.

Every route path that can create a Splitter already consumes `_prepared_junction_ban`, including merge-frontier construction and source tapping. This makes the precomputed ban the single prospective contract. The finalizer remains the backstop.

## Cargo Spray Domain

Introduce one immutable domain:

```python
class CargoDomain(Enum):
    UNSPRAYED = "unsprayed"
    REQUIRES_SPRAY = "requires-spray"
```

Determine cargo domain from each actual destination before sharding. An internal machine consumer uses `REQUIRES_SPRAY` exactly when its proliferation mode requires sprayed input; otherwise it uses `UNSPRAYED`. A requested-output/boundary sink has no recipe proliferation mode and is explicitly `UNSPRAYED` unless a future authoritative `BuildSpec` field says otherwise. Thus an item that is both an external output and an internal proliferated input has both domains. `BuildSpec.lanes_requiring_split` records that coexistence; it is not the authority that decides whether uniform cargo needs spraying.
Carry `(item_id, cargo_domain)` through:

- logical strip plans and logical lanes;
- emitted strip input/output lanes;
- ports and nets;
- shard grouping and lane merging;
- sibling/join/shortcut keys;
- island balance and cross-island net construction.

Rules:

- different domains never merge or share a net;
- direct insertion is legal only for `UNSPRAYED` cargo;
- Spray Coaters are placed only on `REQUIRES_SPRAY` lanes;
- validation/reporting still names the physical item, with domain used only as internal routing identity.

The structural partition may add one lane or shard when a mixed item previously shared one. That cost is intentional and bounded by the 10% quality gate.

## Power Demand Envelope

Define the route-capable powered-emission envelope once:

```text
power demand = grow(core, ROUTE_RING)
tower standing capacity = canvas.limit
```

Pass the explicit demand bounds to `_power_plan`. Mark every tile in that envelope as potentially dark because a later source tap may create a powered Splitter there. The outer entry ring remains belt-only and does not require power.

This reuses the current anticipatory power-plan contract instead of adding post-routing tower repair. Tower sites are still reserved before routing and emitted afterward. Projected power-node spacing remains unchanged.

## Band-Aware Search

Use packaged `src/flab2bp/dsp/data/latitude_bands.json` as the one authoritative catalog imported and validated by both Python and TypeScript. Migrate `planet.py`, `band_policy.py`, CLI parsing, web option parsing, the Zod request schema, and UI labels together:

```text
5x20, 5x40, 5x80, 5x100,
10x160, 10x200,
15x300, 15x400,
25x500, 25x600,
50x800, 160x1000
```

Band 120 remains 600x25. Correcting band 200 does not solve the reported band-120 refusals.

Add a shared band-policy search envelope derived from `BandPolicy`, `planet.Band`, and the existing perimeter constants. It supplies legal core-height boundaries to both strategies. For an explicit fixed 25-row band with a three-tile entry perimeter, the boundary core height is 19 and must be considered.

Keep the existing candidate-count bound. For an explicit fixed band, reserve at most one boundary slot: replace the first existing height that the exact fixed-band frame-capacity predicate proves infeasible, then retain every other existing height in its current relative order. If no existing height is proved infeasible, do not alter the schedule. For `portable` or another multi-band policy, preserve the existing schedule; only the exact early extent gate is policy-aware. Any dropped fixed-band height must have an actual layout regression control, not only an orientation/capacity assertion.

Before power planning or detailed routing:

- reject extents whose exact frame candidate set is empty;
- apply the same orientation semantics as finalization;
- retain exact finalization as the final proof.

No rotated placement is accepted merely because its area fits; width and height must fit one exact permitted orientation.

## Feedback-Driven Freeform Packing

First retain a typed `PackAttempt` instead of reducing each failed build to an integer. It contains:

- packed origins, compact width, height, and outline;
- full `DetailedRouteResult`;
- typed static-access failures;
- promised and realized direct-insert keys.

Make direct insertion truthful before using routing feedback. A direct-insert reward is valid only if emitted geometry can realize it. Encode the occupied-lane and sorter-collider preconditions when structurally provable; otherwise remove that reward. `_bridge` reports promised-versus-realized identity and never silently restores a rewarded net.

### Evidence consumption and proof rules

Reuse `route_feedback.py`, stable net IDs, failed endpoint relations, hot walls, and blockers as weights for the next pack. Evidence changes the objective only for the implicated nets.

No-goods require a proof:

- `STATIC_ACCESS` and a structurally impossible promised direct insert may exclude their proved local relation;
- a non-budget detailed-route result explicitly marked exhaustive may exclude the full exact `(height, outline, width, all origins)` assignment;
- a smaller pair/port relation is excluded only when its exact predicate proves independence from other routes and obstacles;
- budget exhaustion and non-exhaustive routing never create a no-good.

When no smaller proof exists, retain the full exact assignment fallback identified by the current projection no-good pattern. Do not describe a heuristic route miss as proof of geometric impossibility.

### Width and final-area allowance

At each height, first establish compact width `W*`. Evidence-driven repairs may use `width <= ceil(1.10 * W*)`; this is an internal bound, not the final quality denominator. It is not granted for budget-only failures and does not add arrangements.

The authoritative quality gate is per external scenario `(URL, strategy, candidate policy, requested band)` against a frozen pre-reliability baseline artifact. Each candidate repetition is paired with the immediately preceding baseline repetition under identical budget, jobs, worker allocation, and repeat ordinal. Every paired final clean result must have final-frame area at most `1.10 * paired_baseline_area`, including cumulative pitch, lane, tower, and packing changes. Previously refused baseline repetitions have no percentage denominator; record their absolute resulting area separately. Aggregate paired geometric-mean area must also remain at or below 1.10.

Do not restore the previously rejected global backward-edge penalty. Use failed-net-specific exact port relations under the bounded width envelope.

## Separate Named Candidate Policy Follow-up

The user-requested numeric-candidate replacement is specified separately in `docs/superpowers/plans/2026-08-30-named-candidate-policies-web.md`. It uses `no-proliferator`, `all-products`, and `output-products`, all checked by default, with a non-empty explicit subset passed through web/API/rates. It is not a prerequisite for any reliability repair or gate.

## Delivery Order

1. Complete projection-safe pitch in SequencePair and pass its focused quality gate.
2. Add spray cargo domains.
3. Expand the power demand envelope.
4. Add prospective coater/Splitter bans and projection-safe staged-static seat selection.
5. Make both strategies band-policy-aware and add the exact early extent gate.
6. Strengthen different-strip projection feedback in both strategies.
7. Retain typed Freeform attempts and make direct-insert promises truthful.
8. Add proof-scoped routing feedback and bounded width slack.
9. Run the reliability and quality gates.
10. Only then implement and verify the projected power-legality cache.

The authoritative band catalog/UI correction is an independently completed prerequisite and may integrate before this order. The named candidate-policy UI is a separate follow-up. The reliability order addresses silent flow corruption and deterministic mechanical invalidity before search quality; each task lands with focused tests and can be reverted independently.

## Verification Gates

### Focused contract gate

Every reported failure gets a deterministic regression test at the earliest violated boundary:

- same-strip projected pitch in both strategies;
- an illegal staged-static seat advances to a projection-safe alternate, rather than only refusing earlier;
- coater `(26,15,yaw=90)` forbids Splitter `(25,17,z=1)` at band 160 and allows the control at y=18;
- uniform sprayed, uniform unsprayed, and mixed consumers retain the correct disjoint cargo domains;
- a route-ring Splitter at the old power boundary is covered, with an in-radius control;
- band 120 includes boundary core height 19, preserves candidate schedule cardinality/order rules, and rejects impossible extents before preparation;
- different-strip exact feedback cannot recur unchanged in either strategy;
- only proof-complete failures create no-goods, and full-assignment fallback is used when no smaller proof exists;
- every rewarded direct insertion is realized.

### Reported-scenario gate

Run three repetitions with one audit job for every supplied external `(URL, strategy, candidate policy, requested band)` request at its unchanged production budget. Report `CLEAN / total external requests`; an honest refusal is non-clean for this reliability metric. Require:

- zero crashes and zero invalid emitted placements;
- zero flow-domain contamination;
- every selected result passes exact finalization and validation;
- every refusal retains ordered structured evidence;
- no attempt repeats an identical proof-complete rejected assignment after feedback.

### Corpus gate

Run `URL_CORPUS × 2 strategies × 3 policies × 3 paired repetitions` at budget 15 with 16 audit jobs: 216 external layout requests per arm. Execute each baseline run immediately before its candidate run and pair by repeat ordinal. Require:

- exactly 216/216 `CLEAN` candidate requests; `REFUSED`, `INVALID`, `CRASH`, and `NOT RUN` are non-clean;
- zero `INVALID` and `CRASH`;
- no baseline-clean paired request loses coverage and no candidate identity disappears;
- every paired final clean result has area ratio at most 1.10; paired geometric-mean area ratio is at most 1.10; non-clean baseline repetitions report absolute candidate area while the paired candidate must still be `CLEAN`;

### Static and full-suite gate

Run focused pytest during each task, then once at the end run Ruff, strict MyPy, Python tests, web tests, Biome, TypeScript typecheck, production web build, and production CLI smoke scenarios. The final report records exact commands, pass counts, elapsed time, the 216-request clean rate, per-scenario area ratios, absolute areas for formerly refused scenarios, and the explicit work-bound manifest.
