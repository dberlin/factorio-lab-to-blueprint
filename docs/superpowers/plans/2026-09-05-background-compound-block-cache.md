# Background Compound Block Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to execute this plan task-by-task. Use TDD for every behavior change. Steps use checkbox syntax for tracking.

**Goal:** Reuse exact, validated compound production blocks across builds without spending a user request's solve budget on discovering, improving, or persisting those blocks.

**Decision:** The synchronous path may perform a bounded cache lookup and may intentionally construct a required specialized topology such as `FractionatorLoop` or `MatrixLabBlock`. It must never mine arbitrary subgraphs, refine the block library, or write persistent cache artifacts. A server-owned background coordinator consumes immutable successful-build snapshots, waits for the server to be idle, performs identification/refinement in a preemptible worker process, validates candidates, and publishes them atomically. The CLI may read the same library but does no opportunistic mining or writing; an explicit future cache-warm command is the only acceptable CLI writer.

**Architecture:** Introduce one sealed, data-only compound fragment representation shared by Freeform and SequencePair. Concrete planners produce fragments; the background miner may later extract and refine additional ingredient/rate blocks from validator-clean builds. `Builder` owns foreground activity state but does not understand block geometry. `CacheWorker` owns the bounded opportunity queue and background process. A shared idle gate prevents CPU-heavy background work from overlapping a foreground solve. Cache hits remain candidates: outer placement, inter-block routing, power, compaction, latitude projection, full validation, and encoding run on every request.

**Tech stack:** Python 3.14, frozen dataclasses/Pydantic wire schemas, exact `Fraction`, `ThreadPoolExecutor` for existing request coordination, a single supervised child process for CPU-heavy cache generation, atomic content-addressed files, pytest, Ruff, strict MyPy, `uv run`.

## Non-negotiable constraints

- **Request isolation.** Cache discovery, decomposition, refinement, validation, and persistence never execute in an HTTP build worker or consume its layout deadline.
- **Reads only on the hot path.** A request may canonicalize a small lookup key, read a bounded immutable entry, and inject retained fragments as candidates. Cache failure is a miss.
- **Intentional topology exception.** If a requested recipe is operationally defined by a specialized block, its concrete planner runs synchronously because that is the requested solve, not cache mining. Publication remains asynchronous in the server.
- **No CPU overlap.** Background generation holds an idle lease available only when there are no queued/running foreground builds. A new submission revokes the lease before its solve starts.
- **Hard preemption.** CPU-heavy mining/refinement runs in a child process. Cooperative cancellation is attempted first; the coordinator may terminate a child that does not stop within the bounded preemption interval. Do not rely on a Python thread to interrupt CP-SAT or routing.
- **Correctness without cache.** Empty, disabled, corrupt, stale, full, read-only, or unavailable caches preserve existing behavior.
- **Validation authority unchanged.** A local certificate is evidence. Only final whole-frame compaction, projection, `validate`, and pipeline selection can ship a blueprint.
- **Positive first.** Persistent negative proofs are a later phase with an independent feature flag and proof firewall. Ordinary refusals are never cached.
- **Small frontier.** Retain at most four nondominated fragments per exact request. Never eager-product frontiers across blocks.
- **Exact identity.** Canonical reduced rationals and semantic digests only. No raw URL, `repr`, `id(spec)`, Python `hash()`, timestamps, deadlines, insertion order, or process-local strip ordinals in persistent keys.
- **Bounded resources.** Queue, child count, decoded entry bytes, entries per key, proof count, and total persistent bytes all have hard limits.
- **No current Matrix inference.** A deadline refusal or forced-topology miss is performance evidence, not an impossibility proof and not a persistent negative.

## Target module boundaries

### New shared layout modules

- `src/flab2bp/layout/compound.py`
  - `CompoundRequest`
  - `CompoundBoundaryPort`
  - `CompoundFragment`
  - `CompoundVariantId`
  - normalization, translation, and exact local invariants
- `src/flab2bp/layout/compound_library.py`
  - canonical wire schemas
  - content digests
  - in-memory frontier
  - persistent positive store
  - later, separate negative-proof namespace
- `src/flab2bp/layout/compound_mining.py`
  - successful-build opportunity extraction
  - repeated-demand counting
  - background-only decomposition/refinement
  - no server/thread/process concerns

### New server module

- `src/flab2bp/web/cache_worker.py`
  - bounded `CacheOpportunity` queue
  - foreground/idle arbitration
  - one coordinator thread
  - one disposable child generation process
  - cancellation, shutdown, and telemetry

### Existing integration seams

- `src/flab2bp/web/jobs.py`
  - foreground activity accounting
  - enqueue immutable completed `pipeline.Build` references after the response result is determined
- `src/flab2bp/web/server.py`
  - create/start/stop the cache worker with server lifecycle
- `src/flab2bp/pipeline.py`
  - bounded positive lookup and cache-hit candidate injection
  - expose complete successful `Attempt`/`Build` artifacts to the background sink without mining them
- `src/flab2bp/layout/strip_variants.py`
  - shared outer placeable representation for compound variants
- `src/flab2bp/layout/freeform.py` and `sequence_solver.py`
  - translate frozen local fragments and route declared boundary ports only
- `src/flab2bp/layout/finalize.py` and `validate.py`
  - remain final authorities; add only exact compound-instance boundary checks

## Shared contracts

### Foreground activity gate

```python
@dataclass(frozen=True, slots=True)
class IdleLease:
    generation: int
    cancelled: threading.Event

class ForegroundGate:
    def foreground_submitted(self) -> None: ...
    def foreground_finished(self) -> None: ...
    def acquire_idle(self) -> IdleLease | None: ...
    def release_idle(self, lease: IdleLease) -> None: ...
```

Invariants:

1. `foreground_submitted` happens before a job can enter the build executor.
2. A foreground submission sets the current background cancellation event.
3. A foreground solve does not enter `pipeline.build` until the background child has acknowledged exit or been terminated.
4. Multiple queued/running foreground jobs keep the gate closed until the last finishes.
5. Shutdown revokes the lease and never waits for queued cache opportunities to finish.

### Opportunity handoff

```python
@dataclass(frozen=True, slots=True)
class CacheOpportunity:
    build: pipeline.Build
    observed_at_ns: int
```

The first version deliberately enqueues the already immutable `Build` by reference. The request worker performs no graph decomposition, block identification, digest construction, serialization, or disk I/O. The queue is small; when full, drop an old opportunity rather than delay a response or retain unbounded placements.

The background worker is responsible for selecting only validator-clean attempts and deriving canonical block requests. `NoValidLayout`, exceptions, invalid attempts, and request cancellation publish nothing.

### Cache lookup contract

```python
class CompoundBlockLibrary:
    def lookup(self, request: CompoundRequest) -> tuple[CompoundFragment, ...]: ...
    def publish(self, request: CompoundRequest, fragments: Sequence[CompoundFragment]) -> None: ...
```

`lookup` is side-effect-free except in-memory hit counters. It is byte/time bounded and returns `()` on disabled storage, absence, corruption, stale schema, incompatible ABI/assets, or lock contention. It does not repair, migrate, mine, validate a whole placement, or update a shared manifest.

`publish` is called only by the background worker or an explicit offline warm command. It recomputes digests, validates the local artifact, merges a maximum-four Pareto frontier, and uses atomic replacement.

---

## Phase 0 — Measure eligibility before building the cache

**Purpose:** Prove that repeated local work exists and define the cold baseline without changing request behavior.

**Files:**

- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/bench/metrics.py`
- Modify: `scripts/audit.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/scripts/test_audit.py`

- [ ] Add typed timing/counter fields for eligible local planning, internal routing, outer routing, finalization, and validation. Do not add a cache or change candidate order.
- [ ] Add a deterministic semantic demand fingerprint used only for measurement. Assert equal specs produce equal fingerprints across process/hash seeds; it is not yet a production cache key.
- [ ] Record repeated eligible demand counts across Matrix-heavy, Fractionator-heavy, mixed, and noncompound control cells.
- [ ] Separate internal-block work from outer/global work. If attribution cannot distinguish them, stop and improve instrumentation rather than claiming cacheable savings.
- [ ] Capture at least five interleaved cold runs under identical workers, affinity, load, commit, assets, and budgets.

**Gate 0:** Continue only if at least two exact demand fingerprints recur across independent builds/specs and eligible repeated local work is at least 20% of wall time on the repeat-heavy corpus. If it is below 10%, stop persistent-cache work; the abstraction may still be useful for specialized correctness.

**Verification:**

```bash
uv run pytest -q tests/test_pipeline.py tests/scripts/test_audit.py
uv run ruff check src/flab2bp/pipeline.py src/flab2bp/layout/freeform.py \
  src/flab2bp/layout/sequence_solver.py src/flab2bp/bench/metrics.py \
  scripts/audit.py tests/test_pipeline.py tests/scripts/test_audit.py
uv run mypy
```

---

## Phase 1 — Introduce the sealed fragment boundary with no caching

**Purpose:** Make compound construction reusable without persistence or server changes.

**Files:**

- Create: `src/flab2bp/layout/compound.py`
- Create: `tests/layout/test_compound.py`
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `src/flab2bp/layout/validate.py`

- [ ] Write failing tests for canonical local origin, exact building/link preservation, duplicate/invalid port rejection, boundary-only escape, frozen internal records, physical counts, exact rational capacities, and owner propagation.
- [ ] Define immutable `CompoundBoundaryPort`, `CompoundFragment`, and variant identity types. Keep the protocol data-only.
- [ ] Implement one translation/index-remapping function used by both strategies. Initially support translation only; no duplicated strategy adapters.
- [ ] Adapt one ordinary strip fixture through the fragment translator and prove equivalent emitted records and validation behavior.
- [ ] Teach both outer engines to treat the fragment as one rectangle and to prepare nets only for declared ports. Internal links never enter the global router.
- [ ] Protect internal records and boundary access from compaction while retaining full collision/projection visibility.
- [ ] Add compound-instance validation that requires the full local spec/id map and fails on any unexpected skipped check.

**Gate 1:** Existing noncompound placements remain structurally unchanged; translated fixtures preserve every record/link/port/count; both strategies can place and externally route one test fragment; full final validation still decides success.

**Verification:**

```bash
uv run pytest -q tests/layout/test_compound.py tests/layout/test_freeform.py \
  tests/layout/test_sequence_solver.py tests/layout/test_validate.py
uv run ruff check src/flab2bp/layout tests/layout
uv run mypy
```

---

## Phase 2 — Add server lifecycle and foreground isolation

**Purpose:** Establish the background execution boundary before implementing mining.

**Files:**

- Create: `src/flab2bp/web/cache_worker.py`
- Create: `tests/web/test_cache_worker.py`
- Modify: `src/flab2bp/web/jobs.py`
- Modify: `src/flab2bp/web/server.py`
- Modify: `tests/web/test_jobs.py`
- Modify: `tests/web/test_server.py`

- [ ] Write event-driven tests proving a cache worker starts with the server, sleeps while foreground work exists, and stops without orphaning a thread/process.
- [ ] Implement `ForegroundGate`. `Builder.submit` increments foreground demand before executor submission; `_run` decrements it in one `finally` path for success, refusal, and error.
- [ ] Implement a bounded in-memory opportunity queue. Submission is nonblocking and never changes the build response.
- [ ] Implement a coordinator thread with an injectable no-op miner. Do not add real decomposition or disk writes yet.
- [ ] Run CPU work in one supervised child process. A fake blocking miner proves a new foreground submission signals cancellation and hard-terminates a noncooperative child within the configured interval.
- [ ] Hold a foreground job in `queued` state until background CPU work has exited. The HTTP POST still returns immediately; request parsing never waits for cache cleanup.
- [ ] Make cache-worker exceptions observable in counters/logging but unable to change job state or server health.
- [ ] Shut down in this order: stop accepting opportunities, signal cancellation, terminate/join child, join coordinator, then close the build executor/server. Do not drain cache work on shutdown.

**Gate 2:** Deterministic tests prove zero overlap between the fake background CPU section and `pipeline.build`; a cache crash/drop/full queue leaves foreground results unchanged; shutdown leaves no live cache process.

**Verification:**

```bash
uv run pytest -q tests/web/test_cache_worker.py tests/web/test_jobs.py tests/web/test_server.py
uv run ruff check src/flab2bp/web tests/web
uv run mypy
```

---

## Phase 3 — Enqueue successful builds without mining on the request path

**Purpose:** Hand immutable evidence to the background worker in $O(1)$ request work.

**Files:**

- Modify: `src/flab2bp/web/jobs.py`
- Modify: `src/flab2bp/web/cache_worker.py`
- Modify: `tests/web/test_jobs.py`
- Modify: `tests/web/test_cache_worker.py`

- [ ] Add an injectable `OpportunitySink` to `Builder`; production binds it to `CacheWorker.offer` and tests may record object identity.
- [ ] After `pipeline.Build` is produced and `describe` succeeds, enqueue the immutable build reference. Do not traverse `BuildSpec`, `Placement`, or `Attempt` records in `_run`.
- [ ] Prove request completion does not wait for a blocked sink; `offer` itself must be nonblocking and bounded.
- [ ] On a full queue, drop the oldest unstarted opportunity and increment a drop counter. Never block or allocate an unbounded overflow list.
- [ ] Enqueue no artifact for `NoValidLayout`, operational error, failed description, or interrupted solve.
- [ ] Move validator-clean attempt filtering, request canonicalization, graph decomposition, and recurrence counting into the coordinator/child boundary.

**Gate 3:** A successful job hands off exactly the original immutable `Build` object once; every refusal/error hands off zero; a saturated worker does not measurably alter job completion latency in the deterministic test.

**Verification:**

```bash
uv run pytest -q tests/web/test_jobs.py tests/web/test_cache_worker.py
uv run ruff check src/flab2bp/web tests/web
uv run mypy
```

---

## Phase 4 — Implement background-only opportunity identification

**Purpose:** Identify reusable ingredient/rate blocks only after a user build is complete.

**Files:**

- Create: `src/flab2bp/layout/compound_mining.py`
- Create: `tests/layout/test_compound_mining.py`
- Modify: `src/flab2bp/web/cache_worker.py`
- Modify: `tests/web/test_cache_worker.py`

- [ ] Define a canonical `CompoundRequest` using exact reduced rationals and semantic game/build constraints from the approved cache assessment.
- [ ] Write process-hash-independence and insertion-order-independence tests under different `PYTHONHASHSEED` values.
- [ ] From validator-clean attempts only, identify connected recipe subgraphs with closed internal material edges and explicit external item/rate boundaries. Do not infer a block from geometric proximity alone.
- [ ] Exclude power, whole-blueprint input/output markers, latitude frame, names, stats, and surrounding routes from the local request.
- [ ] Treat existing intentional compound variants as direct opportunities; they do not need graph rediscovery.
- [ ] Track recurrence in the worker, not the request. The pilot may require two independent observations before spending background generation time; expose the threshold as a bounded server setting and measure it.
- [ ] Poll cancellation between decomposition stages. Return no partial opportunity after cancellation.
- [ ] Serialize the input passed to the child, not the entire live server/Builder object. Enforce a byte bound before process submission.

**Gate 4:** Fixtures recover exact demand boundaries and reject open/ambiguous subgraphs; semantically equal builds yield equal requests across processes; the foreground thread performs no mining calls.

**Verification:**

```bash
uv run pytest -q tests/layout/test_compound_mining.py tests/web/test_cache_worker.py
uv run ruff check src/flab2bp/layout/compound_mining.py tests/layout/test_compound_mining.py \
  src/flab2bp/web/cache_worker.py tests/web/test_cache_worker.py
uv run mypy
```

---

## Phase 5 — Add process-local generation and shadow replay

**Purpose:** Prove generated/replayed blocks are exact before touching persistent storage or request selection.

**Files:**

- Create: `src/flab2bp/layout/compound_library.py`
- Create: `tests/layout/test_compound_library.py`
- Modify: `src/flab2bp/layout/compound_mining.py`
- Modify: `src/flab2bp/web/cache_worker.py`

- [ ] Add a process-local byte-bounded library and maximum-four Pareto admission. Compare identical typed-port topologies only for dominance.
- [ ] Define categories: minimum area, minimum width, minimum height, and minimum typed-port escape cost. Deduplicate by content digest.
- [ ] Materialize intentional specialized planner output as a candidate without rerunning its construction. Generic opportunities may run bounded deterministic generation/refinement in the child only.
- [ ] Decode/replay every admitted fragment in shadow mode, translate it over deterministic offsets/bands, compose it into a fixture, and run local plus whole validation.
- [ ] Record hit/miss/admission/dominance/cancellation/generation time and exact local-vs-final metrics. These counters do not enter candidate scoring.
- [ ] Never inject a shadow hit into a user solve in this phase.

**Gate 5:** Zero digest/link/port/count mismatches; zero unexpected skipped checks; every replay has the same validity verdict and exact physical/rate boundary as its source. Any mismatch disables the block kind rather than weakening validation.

**Verification:**

```bash
uv run pytest -q tests/layout/test_compound.py tests/layout/test_compound_library.py \
  tests/layout/test_compound_mining.py tests/web/test_cache_worker.py
uv run ruff check src/flab2bp/layout tests/layout src/flab2bp/web tests/web
uv run mypy
```

---

## Phase 6 — Add atomic persistent positives; keep reads in shadow mode

**Purpose:** Prove cross-process correctness, invalidation, and bounded storage before production reads.

**Files:**

- Modify: `src/flab2bp/layout/compound_library.py`
- Modify: `tests/layout/test_compound_library.py`
- Modify: `src/flab2bp/web/server.py`
- Modify: `tests/web/test_server.py`

- [ ] Implement the canonical request/value wire schemas and full SHA-256 digests.
- [ ] Store under `$XDG_CACHE_HOME/flab2bp/compound-blocks/v1/positive/aa/bb/<digest>.json` with unique same-directory temporary files and atomic replacement.
- [ ] Strictly bound bytes before parsing; reject unknown schema/fields, invalid rationals, bad indices, noncanonical origins, or digest mismatch as a miss.
- [ ] Include planner/validator/finalizer/route ABI revisions plus exact dataset/rule-asset digests. Independently mutate every key dimension and prove a miss.
- [ ] Generate/validate outside locks. Use immutable same-key publication and optional advisory per-request locking only to reduce duplicate work; correctness cannot depend on locks.
- [ ] Add corruption/truncation, interrupted write, concurrent writer/reader, abandoned lock, and read-only directory tests.
- [ ] Bound entries and total bytes; eviction is best-effort background work and never blocks a build. Start with the measured sizes, not a permanent guessed limit; the assessment's initial ceiling is 2,000 positive requests and 1 GiB.
- [ ] Populate in one process and replay in a fresh process, still shadow-only.

**Gate 6:** Readers never observe partial content; corruption and stale versions are misses; semantic changes always miss; concurrent same-key writers leave one valid envelope; cache availability never becomes server availability.

**Verification:**

```bash
uv run pytest -q tests/layout/test_compound_library.py tests/web/test_server.py
uv run ruff check src/flab2bp/layout/compound_library.py tests/layout/test_compound_library.py \
  src/flab2bp/web/server.py tests/web/test_server.py
uv run mypy
```

---

## Phase 7 — Enable bounded positive reads in the solve path

**Purpose:** Consume cache entries without moving mining or persistence onto the request path.

**Files:**

- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/layout/strip_variants.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/web/jobs.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/web/test_jobs.py`

- [ ] Add an injectable read-only `CompoundBlockSource` to pipeline/layout construction. A disabled source returns no variants and preserves exact current candidate order.
- [ ] Canonicalize and perform one bounded lookup before local block planning. No write lock, mining, repair, migration, or persistent access-time manifest update is allowed.
- [ ] Inject each retained fragment as an outer candidate with stable content identity. Do not suppress from-scratch candidates yet.
- [ ] Compose integer copies plus an exact residual request; never geometrically scale a fragment or silently accept overproduction.
- [ ] Preserve exact physical counts, rate boundaries, cargo stack/domain, owned minimum belt tiers, port access, and internal immutability.
- [ ] Run normal outer routing, power, finalization, full validation, and objective selection for every hit.
- [ ] Make all lookup/decode/translation failures ordinary misses. Add fault-injection tests proving identical foreground result with the cache disabled or broken.
- [ ] Keep the CLI read-only. Add `--no-compound-cache` and a server equivalent for controlled baselines; default reads remain off until the phase gate passes.

**Gate 7:** On paired fixtures, cache off and cache on preserve all validator-clean outcomes, exact rates/counts, and noncompound behavior. No production code calls `publish` from a request stack.

**Verification:**

```bash
uv run pytest -q tests/test_pipeline.py tests/layout/test_compound.py \
  tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/web/test_jobs.py
uv run ruff check src tests
uv run mypy
```

---

## Phase 8 — Promote intentional planners, then generic learned blocks

**Purpose:** Separate operationally required blocks from opportunistically learned blocks.

### Phase 8A — Intentional specialized planners

- [ ] Move `MatrixLabBlock` and `FractionatorLoop` behind the shared fragment boundary after each planner's independent correctness gates pass.
- [ ] Run each planner synchronously when its recipe requires that topology. This work belongs to the requested solve.
- [ ] Enqueue the finished immutable fragment for asynchronous publication; never serialize/write it in the request worker.
- [ ] Do not retain a Matrix topology merely because it exists. Admit only independently validator-clean, nondominated variants; deadline refusals are not negatives.

### Phase 8B — Generic background creation

- [ ] Enable repeated-demand mining for non-specialized connected recipe subgraphs only in the idle child process.
- [ ] Use a bounded deterministic work contract and the same exact fragment validator. Cancellation produces no artifact.
- [ ] Compare extracted-as-is seeds against background-refined variants. Keep only nondominated exact port topologies.
- [ ] Do not add a universal callback/plugin registry. New block planners are explicit modules producing the same immutable data.

**Gate 8:** Specialized blocks remain operationally correct with cache disabled. Generic learned blocks add no validity/count/rate regression and demonstrate repeated cross-run reuse; otherwise leave generic mining disabled and retain only intentional planners.

---

## Phase 9 — Performance and density bake-off

**Purpose:** Falsify the claim that warm blocks save material work while losing negligible whole-blueprint area.

Run interleaved arms on Matrix-heavy, Fractionator-heavy, mixed, and noncompound controls:

- A: cache disabled, full from-scratch;
- B: warm cache, one minimum-area fragment;
- C: warm cache, frontier cap four;
- D: cache disabled with the same outer candidate cap as C.

Use the same commit, assets, options, affinity, load, workers, seeds, and quality contract. Populate in one process; warm measurements run in fresh processes. Use at least five trials. Do not run unrelated suites during timing.

- [ ] Compare local generation/routing time, end-to-end wall, final exact area, belt tiles, completion, physical counts, and rates.
- [ ] Keep the four-entry frontier only if it improves meaningful whole-layout completion/area over one entry with less than 10% extra warm wall time.
- [ ] Require warm hits to remove at least 80% of measured compound-local work and improve repeat-heavy median end-to-end wall by at least 20%.
- [ ] Require cold misses to regress no more than 5%.
- [ ] Require 100% retention of baseline-valid cells, geometric-mean warm/cold final-area ratio at most 1.01, worst paired area regression at most 2%, and unchanged noncompound controls.
- [ ] Report improvements and regressions separately; do not average a failure away.

**Gate 9:** Enable positive cache reads by default only if all correctness and density requirements pass. If speed passes but density fails, retain hits only as warm starts while continuing the requested from-scratch improvement search.

---

## Phase 10 — Add persistent negative proofs separately

**Purpose:** Reuse only facts proved impossible, never observations that search ran out of time.

**Files:**

- Modify: `src/flab2bp/layout/compound_library.py`
- Create: `tests/layout/test_compound_proofs.py`
- Modify: exact proof producers in `freeform.py`, `route_feedback.py`, `compact_seed.py`, and `sequence_solver.py` only where their current proof contracts are already exhaustive

- [ ] Define a separate `CompoundNegativeProof` schema and namespace.
- [ ] Admit only structural capacity inequalities, complete exact-domain `INFEASIBLE`, exact direct-relation no-goods, closed exhaustive cluster-relation no-goods, and independently complete projection-pair proofs.
- [ ] Replace solve-local ordinals with stable instance/variant identities and retain exact domain, outline, height, orientation, relative transform, cargo/net roles, solver/proof ABI, and evidence.
- [ ] Recheck cheap proof predicates on read. Decode/recheck failure is a miss plus quarantine, never refusal.
- [ ] Add a firewall test injecting timeout, deadline, cancellation, `UNKNOWN`, router `BUDGET`, no incumbent, beam/ALNS/archive exhaustion, dynamic congestion, power miss, validation error, exception, and crash. Assert zero persistent negatives.
- [ ] Prove relation/projection negatives remain internal search cuts and never become whole-request refusals.
- [ ] Add bounded proof storage and eviction independently of positives.

**Gate 10:** Every admitted negative re-proves on its exact finite fixture domain; no legal assignment is excluded; every observational failure writes nothing. One contradiction disables persistent negative reads globally until fixed.

---

## Phase 11 — Production rollout and observability

- [ ] Expose cache enabled/read-only status, queue depth, active/idle/cancelling state, drops, hits, misses, corruptions, admissions, evictions, child failures, and preemption latency through structured server telemetry. Do not expose cache contents or source URLs.
- [ ] Keep cache work absent from the user job's solver ceiling and progress denominator. If shown in the UI later, label it server maintenance, not build progress.
- [ ] Enable positive reads with a 5–10% shadow from-scratch sample of repeated requests.
- [ ] Keep negative reads behind a separate feature flag through a longer shadow period.
- [ ] Add operational tests for restart, disabled/read-only storage, full disk, permission failure, corrupt entries, abandoned child, and repeated foreground preemption.
- [ ] Update `README.md`, `docs/WEB_UI.md`, and `CHANGELOG.md` only when production reads become user-visible.

**Gate 11:** Sampled warm/cold comparisons continue to satisfy Gate 9; foreground p95 submission-to-solve-start is not materially regressed; cache failures never fail builds; disabling reads restores cache-free behavior without deleting artifacts.

## Final acceptance checklist

- [ ] User requests only look up and consume cache entries; they never mine, refine, validate-for-publication, or persist them.
- [ ] Intentional specialized construction remains part of the requested recipe solve; its persistence is asynchronous.
- [ ] Background CPU work cannot overlap a foreground solve and is hard-preemptible.
- [ ] Server shutdown leaves no orphan thread/process and does not drain optional cache work.
- [ ] CLI is read-only unless an explicit offline warm operation is invoked.
- [ ] Positive artifacts are exact, bounded, content-addressed, atomically published, and independently revalidated after composition.
- [ ] The frontier is at most four and survives only the one-vs-four bake-off.
- [ ] Ordinary refusals, Matrix deadline misses, `UNKNOWN`, and `BUDGET` never become negative entries.
- [ ] Cache-disabled behavior remains the correctness baseline and rollback path.
- [ ] Cross-process speed and whole-blueprint density gates pass before default enablement.
