# General abstraction repairs: algorithm-facing contracts and state ownership

Status: approved for execution by the user on2026-09-08. The [original abstraction repair plan](../plans/2026-09-08-abstraction-repairs.md) remains the first separate tranche. Independent general work starts in `.claude/worktrees/abstraction-general`; original-owner and v5 reconciliation still precede shared routing extraction.

## Purpose and selection rule

This work is not aesthetic cleanup. A retained abstraction must do at least one of the following:

1. Let an algorithm change behind a stable domain contract rather than requiring edits to competing strategies.
2. Give one owner authority over an invariant or mutable lifecycle that currently drifts across consumers.
3. Remove repeated conversion, indexing, resolution or state synchronization between two components.
4. Make correctness-preserving performance changes possible without duplicating policy or introducing stale caches.

Each implementation task must name the owner, its consumers, what duplicated work/state/boilerplate disappears, and an observable acceptance check. A forwarding wrapper, new name, arbitrary file split, or generic framework with no such benefit is rejected. Small concrete bugs can be repaired at their existing owner without inventing an abstraction.

## Review evidence and limits

Source: `bbc8889d`. [General review bundle](../evidence/2026-09-08-abstraction-review/general-review.json) preserves four independent read-only reviews and their exact section-level coverage/gaps:

- Domain: URL/typed requests, flow identity, rates/machine choice, DSP catalog/geometry/encoding and rule ownership.
- Layout: prepared routing, strategy consumers, completion, band envelope, feedback and selected indexed contracts.
- Orchestration/tooling: pipeline/CLI, races, benchmark judgments/identity and audit lifecycle.
- Web: HTTP/job/trace lifecycle, displayed state, payload contracts, parsing/model/render seams.

This is general codebase coverage by representative seams, **not an exhaustive line-by-line audit**. Unexamined search operators, codec branches, frontend render details, script internals and algebraic solver proofs remain listed in the bundle. The older Buildings/indexed-scans review was narrower.

Main additionally reproduced the public URL parser defect: `https://factoriolab.github.io/dsp/?o=iron-ore*0*0*3&v=11` parses an explicit Items Limit=0 as Limit=1. `zero-objective-probe.log` records the executed result. Other new findings are source-backed defects/inconsistencies or explicitly unproven runtime risks; do not upgrade their evidence status without a probe.

## Selected workstreams

### Request intent and domain identity

Keep optional scalar parsing in `lab.params`; default absent values only at the typed request adapter. Resolve explicitly permitted external inputs once and reuse that immutable answer in candidate filtering and final admission. Resolve physical machine footprint through the existing DSP catalog rather than a second ambient dataset/name cache. These changes remove contradictory policy and ambient work, not merely repeated syntax.

Per-objective/per-recipe machine overrides and deep alias canonicalization are not mixed into this initial cutover: their effective precedence and interaction with exact/up-to selection require authoritative semantic fixtures first. Their omissions remain explicit deferred findings.

### Save-specific judgment and algorithm completion

Use the existing immutable `catalog.BeltAltitudeRules` as the save-policy contract. All production-equivalent constructors and judges must consume the same resolved object; no caller silently judges fully researched defaults after constructing for restricted technology. Generic arbitrary-placement diagnostics may keep their documented defaults.

The existing certification/finalization modules remain the owners. Do not introduce a second validation framework. Preserve distinct skip policies and benchmark timing scopes. Later consolidate the three strategy completion mechanisms beside the existing boundary-compaction result, with explicit caller-owned phase windows, reusable reports only under the existing exact validity contract, and no silent extension/unification of search budgets.

### Strategy-neutral prepared routing

This is a selected **algorithm-enabling** extraction, not a file-size cleanup. `_PreparedNet`, `_PreparedRoutingProblem`, fresh `_RoutingWorkspace`, shared movement/eligibility facts and detailed-routing entry points already form a real domain consumed by Freeform, SequencePair, global relaxed routing and hierarchy. Make that existing boundary independent of the Freeform search strategy.

Perform the extraction only after the original path/corridor owners and in-flight v5 Coater owner are reconciled. Move actual owners and migrate consumers together; no re-export shims. A routing domain must not import the search strategies that consume it. Keep relaxed capacity negotiation, detailed physical routing, CP-SAT, sequence-pair search and strategy feedback as separate algorithms. Do not create parallel copies of prepared state or add a solved-block cache.

Hierarchy packing should consume the existing band search envelope, not a second hardcoded extent rule. Admit that behavior change only with a fixed candidate-domain witness showing why the existing envelope selects a feasible aspect ratio; do not enlarge the pack/rung domain.

### Execution and measurement authority

Use a typed semantic cell identity and duplicate-rejecting indexing for compatible audit artifacts. Comparison must preserve budget/power/candidate identity and explicitly declare which metadata differ as the treatment. Preserve distinct legacy regression, projection and promotion scopes; no universal benchmark verdict.

An audit owns a job-keyed terminal ledger, not an out-of-order completion count treated as a prefix. Its outer timeout must have an explicit process-lifetime contract. Race acquisition/release must be exception safe, including partial submission and interrupted waiting. Use Python3.14's supported executor lifecycle and existing domain cleanup helpers, not a new scheduler framework.

### Web publication and operational facts

- Trace encoding owns an internally consistent sampled graph. Prefer dense remapping at the encoder, disconnecting references to omitted nodes, rather than changing backend placement identity or inventing a second scene graph.
- Trace collection owns drained/closed state; job completion and cursor exhaustion cannot substitute for it.
- BlueprintProvider owns which document is displayed. Publish a real result/import or an explicit trace selection atomically, guarded by source generation. Late automatic work cannot replace a newer user choice.
- One client attempt-facts schema/view supplies both winner and selected-attempt operational instructions. Priming is a one-time action, not a permanent external input. Server/client types remain distinct serialization contracts, but actionable fields cannot disappear between them.
- Correct rotated render bounds locally in the existing model owner. This is a small geometry correctness repair, not a new geometry abstraction or an attempt to unify visual and physical dimensions.

## Ordering and mutation contracts

The first approved plan is not absorbed into this one. Its transport/path/corridor owners land before the shared routing extraction. Request/measurement work and web work can proceed independently in isolated branches; shared pipeline/freeform files serialize at named integration boundaries.

Recommended order:

1. Original approved repairs and small general request-policy/judgment fixes.
2. Independent measurement/lifecycle and web publication workstreams.
3. Shared routing-domain extraction and completion/band-envelope consumers on the reconciled source.

Review semantic batches, not one review per trivial file; commit coherent changes without accumulating enormous unreviewable diffs. Freeze an integrated source before final release checks. Do not repeatedly run whole suites/corpora while one contract probe is unresolved.

## Non-goals and deferred findings

- No recipe-specific topology fixes, mixed lanes, validator weakening, raised work bounds, new backend or persistent cache.
- No generic settings object, universal graph/transaction/scheduler abstraction, schema generation project, arbitrary file-size split or cosmetic rename campaign.
- Do not merge physical collision/projection with render dimensions or FactorioLab economic machine-size costs with DSP footprint area.
- Machine override precedence and nested alias normalization remain deferred until an authoritative semantic fixture determines behavior; then execute a dedicated request-resolution plan, not scattered per-caller patches.
- Do not normalize serial versus raced exception behavior, all-skipped versus power-skipped benchmark policies, or hierarchy versus atomic-strategy clock windows as incidental refactoring.
- Ordinary diagnostic script repetition and optional tie-breaking differences are not selected without an actual shared contract.

## Verification policy

Probe the named failure or phase first. Keep a permanent regression only where a plausible future defect would violate an observable contract. Use throwaway instrumentation for allocation/work evidence instead of tests that pin wiring or source text.

For algorithm extraction, freeze a small prepared-input set covering internal/boundary/early-output/cargo-incompatible cases. Compare real relaxed and detailed results, not helper invocation counts; verify fresh attempts are isolated. Record preparation/retention cost and avoid duplicate index/snapshot construction. No percentage speedup is required to retain a justified ownership cutover, but correctness and deadline regressions are not waved away.

For web changes, exercise the actual browser surface for document selection, late results, trace drain, priming instructions and framing. Targeted component/schema checks complement that proof; they do not replace it.

Run affected static/module checks once per settled integration batch under the150-second suite ceiling. Independent cases may run in parallel; serially adjudicate failures, retaining the originals. The user's especially focused topology experiment policy remains topology-specific. A general repair does not claim the topology or hierarchical factory gates have passed.
