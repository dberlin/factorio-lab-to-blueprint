# Cache Decorator Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the dataset-key correctness defect in belt-rule caching, replace the manual vendored mod-hash cache without changing explicit-path semantics, and put evidence-derived finite bounds on the five public geometry memoizers.

**Architecture:** Split each loader at its cacheability boundary: only the default vendored source is decorator-cached, while caller-supplied `Dataset` and `Path` values always take uncached paths. Measure geometry key traces from the real blueprint corpus and frozen projection fixtures before choosing any geometry `lru_cache` size, then make the measured retention policy executable in tests. Use `functools.cache`/`functools.lru_cache` directly; do not introduce a repository memoization layer.

**Tech Stack:** Python 3.14, `functools.cache`, `functools.lru_cache`, dataclasses, pytest, Ruff, mypy, existing blueprint/projection fixtures.

**Spec:** Audit authority `local://cache-decorator-audit.json`; all implementation-relevant decisions and invariants are reproduced below so this plan remains self-contained.

## Global Constraints

- Keep the public signatures of `belt_rules_for_url(url, dataset=None)` and `load_mod_hash(mod_id="dsp", *, path=None)` unchanged.
- Cache only default vendored inputs. An explicit `Dataset` or explicit `Path` is a request to use that exact object/source now, not a cache key and not permission to retain it.
- Task 1 uses a bounded standard decorator with `maxsize=512` on the default-dataset helper. Never decorate `belt_rules_for_url` directly.
- Task 2 uses `functools.cache` on a default-source helper. Explicit paths reread on every call; failed reads/parses remain retryable because exceptions are not cached.
- Preserve default `ModHash` object identity on cache hits. `ModHash` is frozen but contains mutable lists; callers currently receive the same cached object.
- Task 3 changes only these five public pure geometry memoizers: `catalog.collider_span`, `catalog.clearance`, `colliders.own_centre_extent`, `colliders.belt_keepout_offsets`, and `planet.collider_radius`.
- Do not choose or write any Task 3 `maxsize` before the committed working-set report exists. The selected integer for each function is the report's deterministic `recommended_maxsize`, not a guessed 512/1024 or a shared blanket value.
- Preserve `.cache_clear()`, `.cache_info()`, `__wrapped__`, function signatures, result types, exception behavior, and canonical geometry results when replacing `@cache` with `@lru_cache(maxsize=...)`.
- Do not add finite-yaw validation, NaN normalization, URL normalization, locks, weak references, telemetry, or a generic cache abstraction. Those are separate API decisions.
- Every observable production change follows red-green TDD. A behavior-preserving characterization may be green before a mechanical refactor, but each production task also contains a genuinely failing contract: Task 1's cross-dataset isolation/bound, Task 2's decorated retryable helper contract, and Task 3's finite measured retention contract.
- Keep all Portable/Task 9 work out of the implementation branch. The audited `_ProjectionCache` guardrail below applies if that code is present after branch integration; this cleanup neither ports nor rewrites it.
- Use one atomic commit for Task 1, one for Task 2, and two for Task 3: measurement evidence first, bounded decorators second.

## Confirmed Invariants and Risks

1. **Confirmed correctness defect:** current `lab.techs._CACHE` keys only by URL even though an explicitly supplied `Dataset` contributes the technology universe. For the same URL, whichever dataset is called first contaminates later calls.
2. **Default-only reuse:** repeated default belt-rule and mod-hash loads should reuse work; explicit values must not enter a process-global key or value graph.
3. **Retry semantics:** `functools` decorators do not cache exceptions. A missing or malformed vendored hash must succeed after the source is repaired without an intervening cache clear.
4. **Mutable result identity:** cached default `ModHash` hits return the same object, including the same list members. The cleanup must not copy or freeze it.
5. **Bounded geometry retention:** the five geometry functions accept public integer/float arguments. Arbitrary model IDs, item IDs, yaws, reaches, and levels otherwise remain strongly retained for the process lifetime.
6. **Safe geometry eviction:** the five functions are pure over immutable/hashable arguments, return immutable values, expose no hit counters, and have no semantic invalidation. Eviction may cause recomputation but may not change a result.
7. **Float edge:** repeated NaN yaws can create distinct cache keys. This plan bounds their retention but does not redefine whether NaN is valid input.
8. **Thread behavior:** `functools` keeps its mapping coherent but may compute a concurrent miss more than once. All converted computations are pure, so duplicate computation is acceptable; do not claim single-flight behavior.
9. **Test invalidation:** tests already rely on `.cache_clear()` for monkeypatched cached loaders in `tests/dsp/test_catalog.py`. `lru_cache` provides the same API; the new retention tests exercise it directly on all five converted functions.
10. **Do not globalize build state:** class-level decorators retain `self`; process-level decorators over build/request state risk cross-build contamination and retain complete placements, contexts, or mutable C arrays.

## Deliberate Keep-As-Is Decisions

These exclusions are part of the design, not deferred cleanup:

- **Task 9 `_ProjectionCache`:** the audited Task 9 implementation constructs one `_ProjectionCache` per `finalize_placement`. Its `invariants`, `pairs`, and `projections` dictionaries are mutable, naturally bounded by one finalization, use reduced exact keys, and support `invariant_cache_hits`, `pair_cache_hits`, and `projection_cache_hits`. Its nested cached complete checks retain only that instance and count cached `None` failures correctly. Keep all five hit definitions and the `tests/layout/test_finalize.py` reuse/counter contracts. This plan branch predates that implementation; do not import it from current Portable/Task 9 work merely to edit it.
- **Validator `_Cache`:** the sixteen stores in `layout/validate.py::_Cache` live for one frozen `Context`, share mutable sets/dicts/lists intentionally, cache negative results with membership semantics, and are bounded by buildings/runs/enum values. Decorating `Context` methods would retain entire validation requests globally.
- **Compiled kernel caches:** `CompiledSequenceKernel._sizes` and `._targets` in `layout/sequence_kernel.py` own mutable C arrays tied to one compiled problem. A global decorator would retain kernels and could cross-contaminate problems.
- **Per-build solver memos:** `_production_run.selected_cache` and `.direct_cache` in `layout/sequence_solver.py` deliberately capture one `strips`/`spec` build and use reduced keys. Do not widen keys to whole problems or promote them to module scope.
- **Freeform/local memos:** `_search.hcache` is a dense allocation-efficient list; `_route_all.junction_ok` depends on an attempt-local mutable canvas; `_projection_envelope.candidates_by_extent` is bounded by one envelope. The existing `_junction_ban_offsets(maxsize=256)` and `_routing_transitions(maxsize=16)` are already deliberately bounded.
- **Validation local and cyclic caches:** `_coverage.covered`, `_external_entry_reachable.free`, and `_propagate.memo` are check-local. `_propagate.memo` works with a `visiting` set and mutable dict results; a decorator alone cannot preserve its cycle behavior.
- **Per-instance hash:** `PlacementKey._cached_hash` is one scalar attached to an immutable key and is rebuilt after pickle. A method cache would retain instances.
- **Disk ETag cache:** `lab/data.py` persists URL-hashed bodies and ETags across processes, supports force refresh and conditional requests, replaces bodies atomically, and swallows cache-I/O failures best-effort. A decorator cannot preserve those semantics.
- **No-argument loaders:** catalog table loaders and `rates.adjust._footprints_by_lab_id` have a singleton argument domain. Their existing unbounded `@cache` has an effective one-entry bound and stays unchanged.
- **Mutable/cyclic values generally:** never decorator-convert caches whose values are mutable scratch, whose keys omit captured state, or whose lookup protocol distinguishes recursion-in-progress/negative results from absence.

## File Map and Task Dependencies

| Task | Files | Responsibility | Dependency |
|---|---|---|---|
| 1 | Create `tests/lab/test_techs.py`; modify `src/flab2bp/lab/techs.py` | Isolate explicit datasets and bound only default URL retention | None |
| 2 | Modify `tests/lab/test_params.py`; modify `src/flab2bp/lab/params.py` | Decorate the default vendored hash loader while retaining explicit rereads/retry behavior | None; execute after Task 1 only for clean commits |
| 3A | Create `scripts/measure_geometry_cache_working_sets.py`, `tests/scripts/test_measure_geometry_cache_working_sets.py`, and `tests/fixtures/geometry_cache_working_sets.json` | Produce deterministic cardinality/reuse evidence and baseline timing before production changes | Tasks 1–2 complete; no geometry decorator edits yet |
| 3B | Create `tests/dsp/test_geometry_cache_bounds.py`; modify `src/flab2bp/dsp/catalog.py`, `src/flab2bp/dsp/colliders.py`, and `src/flab2bp/dsp/planet.py` | Enforce report-derived finite bounds with unchanged results and cache-clear behavior | Task 3A report committed |
| 4 | No new files | Focused, static, whole-suite, and before/after performance verification | Tasks 1–3 complete |

Tasks 1 and 2 must not share helpers: their source selection and error contracts differ. Task 3 must not modify either loader. If a task reveals a defect in an excluded cache, record it separately rather than broadening this plan.

---

### Task 1: Isolate Explicit Datasets and Bound the Default Belt-Rule Cache

**Files:**
- Create: `tests/lab/test_techs.py`
- Modify: `src/flab2bp/lab/techs.py:20-57`

**Interfaces:**
- Consumes: `load_vendored() -> Dataset`, `parse_url(url)`, `catalog.belt_rules_for_technologies(researched, all_technologies)`.
- Produces: private uncached `_belt_rules(url: str, dataset: Dataset) -> BeltAltitudeRules`; private `_vendored_belt_rules_for_url(url: str) -> BeltAltitudeRules` with `lru_cache(maxsize=512)`; unchanged public `belt_rules_for_url(url: str, dataset: Dataset | None = None)`.
- Later tasks may rely on `_vendored_belt_rules_for_url.cache_clear()` only in focused test/measurement infrastructure. It remains private and is not added to `__all__`.

- [ ] **Step 1: Add the same-URL, both-call-orders behavioral regression**

Create `tests/lab/test_techs.py` with the following dataset construction and test. The two URLs are deliberately different across call-order cases so the old process-global `_CACHE` cannot let one parameter case mask the other.

```python
from __future__ import annotations

from dataclasses import replace

import pytest

from flab2bp.dsp import catalog
from flab2bp.lab import techs
from flab2bp.lab.data import load_vendored
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url


def _without_technologies(dataset: Dataset) -> Dataset:
    return replace(
        dataset,
        items=tuple(replace(item, technology=None) for item in dataset.items),
    )


def _expected(url: str, dataset: Dataset) -> catalog.BeltAltitudeRules:
    return catalog.belt_rules_for_technologies(
        parse_url(url).researched_technology_ids,
        {item.id for item in dataset.items if item.technology is not None},
    )


@pytest.mark.parametrize(
    ("url", "empty_first"),
    (
        ("https://factoriolab.github.io/dsp/list?o=iron-ingot*60001&v=11", False),
        ("https://factoriolab.github.io/dsp/list?o=iron-ingot*60002&v=11", True),
    ),
)
def test_same_url_explicit_datasets_never_share_rules(
    url: str,
    empty_first: bool,
) -> None:
    full = load_vendored()
    empty = _without_technologies(full)
    first, second = (empty, full) if empty_first else (full, empty)

    first_rules = techs.belt_rules_for_url(url, first)
    second_rules = techs.belt_rules_for_url(url, second)

    assert _expected(url, full) != _expected(url, empty)
    assert first_rules == _expected(url, first)
    assert second_rules == _expected(url, second)
```

- [ ] **Step 2: Add the failing default-only finite-retention contract**

Append this test. It proves the standard wrapper is bounded, repeated defaults hit it, and an explicit dataset does not change its hit/miss/size state.

```python
def test_only_default_dataset_uses_the_bounded_cache() -> None:
    helper = techs._vendored_belt_rules_for_url
    helper.cache_clear()
    try:
        url = "https://factoriolab.github.io/dsp/list?o=iron-ingot*61000&v=11"
        first = techs.belt_rules_for_url(url)
        second = techs.belt_rules_for_url(url)
        assert second is first
        assert helper.cache_info().hits == 1

        before_explicit = helper.cache_info()
        explicit = _without_technologies(load_vendored())
        assert techs.belt_rules_for_url(url, explicit) == _expected(url, explicit)
        assert helper.cache_info() == before_explicit

        for amount in range(1, 514):
            techs.belt_rules_for_url(
                f"https://factoriolab.github.io/dsp/list?o=copper-ingot*{amount}&v=11"
            )
        info = helper.cache_info()
        assert info.maxsize == 512
        assert info.currsize == 512
    finally:
        helper.cache_clear()
```

- [ ] **Step 3: Run Task 1 tests and verify RED**

```bash
uv run pytest tests/lab/test_techs.py -q
```

Expected before the fix:

- `test_same_url_explicit_datasets_never_share_rules` fails on the second call in each parameter case because `_CACHE[url]` returns the first dataset's rules.
- `test_only_default_dataset_uses_the_bounded_cache` fails because `_vendored_belt_rules_for_url` does not exist.

Do not weaken the test by clearing between the two same-URL explicit calls; their isolation is the bug contract.

- [ ] **Step 4: Split pure computation from default-source caching**

In `src/flab2bp/lab/techs.py`, import `lru_cache`, delete `_CACHE` and its URL-key comment, and implement exactly this flow:

```python
from functools import lru_cache


def _belt_rules(url: str, dataset: Dataset) -> catalog.BeltAltitudeRules:
    return catalog.belt_rules_for_technologies(
        parse_url(url).researched_technology_ids,
        {item.id for item in dataset.items if item.technology is not None},
    )


@lru_cache(maxsize=512)
def _vendored_belt_rules_for_url(url: str) -> catalog.BeltAltitudeRules:
    return _belt_rules(url, load_vendored())


def belt_rules_for_url(url: str, dataset: Dataset | None = None) -> catalog.BeltAltitudeRules:
    """Keep the existing public documentation, including absent-technology semantics."""
    if dataset is None:
        return _vendored_belt_rules_for_url(url)
    return _belt_rules(url, dataset)
```

Retain the existing full docstring rather than the abbreviated docstring shown in the snippet. Do not key the cache by `Dataset`, retain explicit datasets in a second cache, or add an alias for `_CACHE`.

- [ ] **Step 5: Run focused tests and static checks**

```bash
uv run pytest tests/lab/test_techs.py tests/dsp/test_catalog.py::TestBeltRulesComeFromTheUrlsTechnologies -q
uv run ruff check src/flab2bp/lab/techs.py tests/lab/test_techs.py
uv run mypy src/flab2bp/lab/techs.py tests/lab/test_techs.py
```

Expected: all pass. The explicit call leaves helper cache statistics unchanged; 513 additional default URLs retain exactly 512 entries.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/flab2bp/lab/techs.py tests/lab/test_techs.py
git commit -m "Fix dataset isolation in belt rule cache"
```

---

### Task 2: Decorate Only the Default Mod-Hash Source

**Files:**
- Modify: `tests/lab/test_params.py:7-16,263-286`
- Modify: `src/flab2bp/lab/params.py:1-20,424-456`

**Interfaces:**
- Consumes: `_candidate_paths(mod_id)`, `Path.read_text(encoding="utf-8")`, `json.loads`, `ModHash.from_json`.
- Produces: `_load_mod_hash_path(path: Path) -> ModHash` with no decorator; `_load_vendored_mod_hash(mod_id: str) -> ModHash` with `@cache`; unchanged public `load_mod_hash`.
- Preserves: default-source object identity, explicit-path rereads, `ValidationError`/`JSONDecodeError` timing, and `LabUrlError` for missing sources.

- [ ] **Step 1: Add explicit-path reread characterization and retryable-helper RED test**

Add `import json` to `tests/lab/test_params.py`, then append these methods to `TestModHash`:

```python
def test_explicit_path_is_reread_after_replacement(self, tmp_path: Path) -> None:
    source = tmp_path / "hash.json"
    source.write_text(json.dumps({"items": ["first"]}), encoding="utf-8")
    first = P.load_mod_hash(path=source)

    source.write_text(json.dumps({"items": ["second"]}), encoding="utf-8")
    second = P.load_mod_hash(path=source)

    assert first.items == ["first"]
    assert second.items == ["second"]
    assert second is not first


def test_failed_vendored_load_is_retryable_and_success_is_cached(
    self,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vendored = tmp_path / "vendored"
    source = vendored / "retryable" / "hash.json"
    source.parent.mkdir(parents=True)
    monkeypatch.setattr(P, "_VENDORED", vendored)

    helper = P._load_vendored_mod_hash
    helper.cache_clear()
    try:
        source.write_text('{"items": [7]}', encoding="utf-8")
        with pytest.raises(ValidationError):
            P.load_mod_hash("retryable")

        source.write_text(json.dumps({"items": ["repaired"]}), encoding="utf-8")
        repaired = P.load_mod_hash("retryable")
        assert repaired.items == ["repaired"]
        assert P.load_mod_hash("retryable") is repaired
        assert helper.cache_info().currsize == 1
    finally:
        helper.cache_clear()
```

The explicit-path test is a characterization: it should already pass and guards against the tempting but incorrect `@cache` on public `load_mod_hash`. The retry test is RED because the required decorated helper does not exist; after conversion it also proves exceptions do not occupy a cache entry.

- [ ] **Step 2: Run the focused tests and verify the mixed GREEN/RED baseline**

```bash
uv run pytest \
  tests/lab/test_params.py::TestModHash::test_explicit_path_is_reread_after_replacement \
  tests/lab/test_params.py::TestModHash::test_failed_vendored_load_is_retryable_and_success_is_cached -q
```

Expected: explicit reread passes; helper retry test fails with `AttributeError: module 'flab2bp.lab.params' has no attribute '_load_vendored_mod_hash'`.

- [ ] **Step 3: Replace `_HASH_CACHE` with a default-source helper**

In `src/flab2bp/lab/params.py`, add `from functools import cache`, delete `_HASH_CACHE`, and use this decomposition:

```python
def _load_mod_hash_path(path: Path) -> ModHash:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    return ModHash.from_json(raw)


@cache
def _load_vendored_mod_hash(mod_id: str) -> ModHash:
    source = next(
        (candidate for candidate in _candidate_paths(mod_id) if candidate.is_file()), None
    )
    if source is None:
        raise LabUrlError(f"no vendored hash.json for dataset {mod_id!r}; looked under {_VENDORED}")
    return _load_mod_hash_path(source)


def load_mod_hash(mod_id: str = "dsp", *, path: Path | None = None) -> ModHash:
    """Retain the existing public docstring."""
    if path is None:
        return _load_vendored_mod_hash(mod_id)
    if not path.is_file():
        raise LabUrlError(f"no vendored hash.json for dataset {mod_id!r}; looked under {_VENDORED}")
    return _load_mod_hash_path(path)
```

Retain the full existing public docstring. Keep the explicit-path missing-file exception type/message consistent with the current combined branch. Do not decorate `_load_mod_hash_path`, do not include `path` in the helper key, and do not catch parse/validation exceptions.

- [ ] **Step 4: Run all mod-hash behavior and URL integration tests**

```bash
uv run pytest tests/lab/test_params.py::TestModHash tests/lab/test_url.py -q
uv run ruff check src/flab2bp/lab/params.py tests/lab/test_params.py
uv run mypy src/flab2bp/lab/params.py tests/lab/test_params.py
```

Expected: all pass. The first malformed default call raises; the repaired second call succeeds without `cache_clear`; the third call is the same object. Explicit path replacement is observed on the next call.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/flab2bp/lab/params.py tests/lab/test_params.py
git commit -m "Use a decorator for vendored mod hashes"
```

---

### Task 3: Measure, Then Bound the Five Public Geometry Caches

**Files:**
- Create: `scripts/measure_geometry_cache_working_sets.py`
- Create: `tests/scripts/test_measure_geometry_cache_working_sets.py`
- Create: `tests/fixtures/geometry_cache_working_sets.json`
- Create: `tests/dsp/test_geometry_cache_bounds.py`
- Modify: `src/flab2bp/dsp/catalog.py:49-56,1469,1506`
- Modify: `src/flab2bp/dsp/colliders.py:118-121,400,920`
- Modify: `src/flab2bp/dsp/planet.py:54-61,913`

**Interfaces:**
- Consumes realistic keys from every decodable `tests/fixtures/*.txt` blueprint and every `tests/fixtures/projection/*.json` frozen placement.
- Produces a deterministic JSON report with per-function call count, total distinct keys, peak per-case distinct keys, unbounded hits, candidate bounded-LRU hits, and `recommended_maxsize`.
- Produces unchanged callable geometry APIs with measured finite `cache_info().maxsize` and working `.cache_clear()`.

#### Measurement Policy

For each named function, build case-local key traces that mirror existing callsites:

| Function | Key recorded per real/frozen building |
|---|---|
| `catalog.collider_span` | `(item_id, yaw)` for catalog-known buildings |
| `catalog.clearance` | `(item_id, yaw)` for catalog-known buildings |
| `colliders.own_centre_extent` | `(model_index, yaw)` for catalog-known buildings, plus `(model_index, 0.0)` for catalog construction behavior |
| `colliders.belt_keepout_offsets` | the actual `junction._keepout` default key `(splitter_model_index, 0.0, 3, 4)` once per case that contains/uses a splitter |
| `planet.collider_radius` | `(model_index,)` for each frozen placement building considered by projection broad phase |

Sort input paths for determinism and retain key order within each fixture. Invalid/DYBP fixtures are skipped only on the existing `BlueprintFormatError`; do not catch arbitrary exceptions. Keep separate case traces as well as a deterministic concatenation.

Candidate sizes are powers of two from 1 through the first power that is at least the total distinct cardinality. For each candidate, simulate true LRU ordering and count hits. Define:

```python
def recommended_maxsize(case_traces: list[list[tuple[object, ...]]]) -> int:
    peak_case_distinct = max((len(set(trace)) for trace in case_traces), default=1)
    combined = [key for trace in case_traces for key in trace]
    unbounded_hits = len(combined) - len(set(combined))
    for size in powers_of_two_through(max(len(set(combined)), 1)):
        hits = lru_hits(combined, size)
        retained = 1.0 if unbounded_hits == 0 else hits / unbounded_hits
        if size >= peak_case_distinct and retained >= 0.99:
            return size
    raise AssertionError("candidate range must include an evidence-backed bound")
```

This is the size-selection contract: the smallest power of two that holds the largest observed single-build working set and preserves at least 99% of the hits an unbounded cache would have across the ordered realistic trace. No manually chosen floor, common size, or audit-suggested 512/1024 may override it.

- [ ] **Step 1: TDD the deterministic LRU measurement core**

Create `tests/scripts/test_measure_geometry_cache_working_sets.py`. Test these exact behaviors before writing the script:

```python
from scripts.measure_geometry_cache_working_sets import lru_hits, recommended_maxsize


def test_lru_hits_respects_recency_not_insertion_order() -> None:
    trace = [("a",), ("b",), ("a",), ("c",), ("a",), ("b",)]
    assert lru_hits(trace, 2) == 2


def test_recommendation_holds_peak_case_and_retains_observed_hits() -> None:
    cases = [
        [("a",), ("b",), ("a",)],
        [("c",), ("d",), ("c",)],
    ]
    assert recommended_maxsize(cases) == 2


def test_no_repeat_trace_still_holds_one_complete_case() -> None:
    cases = [[("a",), ("b",), ("c",)], [("d",)]]
    assert recommended_maxsize(cases) == 4
```

Run:

```bash
uv run pytest tests/scripts/test_measure_geometry_cache_working_sets.py -q
```

Expected: collection fails because `scripts.measure_geometry_cache_working_sets` does not exist.

- [ ] **Step 2: Implement the measurement/report tool without touching decorators**

Create `scripts/measure_geometry_cache_working_sets.py` following the repository's benchmark-script bootstrap (`_ROOT`, then add root and `src` to `sys.path`). Expose `lru_hits(trace, maxsize)`, `recommended_maxsize(case_traces)`, `collect_case_traces(root)`, `build_report(root)`, and `main()` as testable functions. Use the exact `recommended_maxsize` algorithm in the Measurement Policy section; implement `lru_hits` with an insertion-ordered `dict`: delete/reinsert on a hit, insert on a miss, and `pop(next(iter(cache)))` when over capacity. `collect_case_traces` returns case names mapped to the five stable function names and their ordered tuple keys. `build_report` emits those function names in the five-function order above and includes this schema for every function:


```json
{
  "calls": 0,
  "distinct_keys": 0,
  "peak_case_distinct": 0,
  "unbounded_hits": 0,
  "candidates": [
    {"maxsize": 1, "hits": 0, "retained_hit_ratio": 1.0}
  ],
  "recommended_maxsize": 1
}
```

Add CLI options:

- `--output PATH`: write deterministic indented JSON with a trailing newline; otherwise print it.
- `--samples N`: in addition to cardinality, clear all five caches and replay all keys `N` times through the real functions, reporting per-function median seconds and cache info. Require `N >= 1`.
- `--compare PATH`: load a prior timed report and exit nonzero if a function's median exceeds the prior median by more than 5%, if its retained-hit ratio drops below 99%, or if the actual decorator `maxsize` differs from the deterministic recommendation.

Do not import pytest or production-private Task 9 code. Do not mutate/normalize keys. Use current `decode()` and frozen projection JSON fields rather than inventing synthetic geometry workloads.

Run the pure tool tests:

```bash
uv run pytest tests/scripts/test_measure_geometry_cache_working_sets.py -q
```

Expected: all pass.

- [ ] **Step 3: Generate and inspect evidence before any geometry source edit**

Generate the deterministic committed report and a timed unbounded baseline:

```bash
uv run python scripts/measure_geometry_cache_working_sets.py \
  --output tests/fixtures/geometry_cache_working_sets.json
uv run python scripts/measure_geometry_cache_working_sets.py \
  --samples 9 --output /tmp/geometry-cache-before.json
```

Inspect all five report entries. Each must have nonzero calls and distinct keys. For each function, verify `recommended_maxsize` is one of its candidate sizes, is at least `peak_case_distinct`, and has `retained_hit_ratio >= 0.99`. If any trace is empty or a known fixture/callsite is absent, fix the collector and regenerate; do not proceed with a guessed size.

The timed `/tmp` file is local comparison evidence and is not committed. The deterministic fixture is durable evidence and must be committed before decorators change.

- [ ] **Step 4: Commit the measurement harness and evidence**

```bash
git add \
  scripts/measure_geometry_cache_working_sets.py \
  tests/scripts/test_measure_geometry_cache_working_sets.py \
  tests/fixtures/geometry_cache_working_sets.json
git commit -m "Measure geometry cache working sets"
```

At this boundary, `src/flab2bp/dsp/{catalog,colliders,planet}.py` must still use `@cache` on all five candidates.

- [ ] **Step 5: Add the failing measured-retention and eviction-stability contracts**

Create `tests/dsp/test_geometry_cache_bounds.py` with the complete report typing, callable mapping, and canonical calls below:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, TypedDict, cast

import pytest

from flab2bp.dsp import catalog, colliders, planet


class _CacheInfo(Protocol):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class _CacheFunction(Protocol):
    def __call__(self, *args: object) -> object: ...
    def cache_clear(self) -> None: ...
    def cache_info(self) -> _CacheInfo: ...


class _FunctionReport(TypedDict):
    recommended_maxsize: int


class _Report(TypedDict):
    functions: dict[str, _FunctionReport]


_REPORT = cast(
    _Report,
    cast(
        object,
        json.loads(
            (Path(__file__).parents[1] / "fixtures" / "geometry_cache_working_sets.json").read_text(
                encoding="utf-8"
            )
        ),
    ),
)
_FUNCTIONS: tuple[tuple[str, _CacheFunction], ...] = (
    ("catalog.collider_span", cast(_CacheFunction, catalog.collider_span)),
    ("catalog.clearance", cast(_CacheFunction, catalog.clearance)),
    ("colliders.own_centre_extent", cast(_CacheFunction, colliders.own_centre_extent)),
    ("colliders.belt_keepout_offsets", cast(_CacheFunction, colliders.belt_keepout_offsets)),
    ("planet.collider_radius", cast(_CacheFunction, planet.collider_radius)),
)
_ASSEMBLER_MODEL = catalog.building(2303).model_index
_SPLITTER_MODEL = catalog.building(catalog.SPLITTER_ID).model_index
_CANONICAL_CALLS: tuple[tuple[_CacheFunction, tuple[object, ...]], ...] = (
    (cast(_CacheFunction, catalog.collider_span), (2303, 0.0)),
    (cast(_CacheFunction, catalog.clearance), (2303, 0.0)),
    (cast(_CacheFunction, colliders.own_centre_extent), (_ASSEMBLER_MODEL, 0.0)),
    (cast(_CacheFunction, colliders.belt_keepout_offsets), (_SPLITTER_MODEL,)),
    (cast(_CacheFunction, planet.collider_radius), (_ASSEMBLER_MODEL,)),
)


@pytest.mark.parametrize(("name", "function"), _FUNCTIONS)
def test_public_geometry_cache_uses_measured_finite_bound(
    name: str,
    function: _CacheFunction,
) -> None:
    expected = _REPORT["functions"][name]["recommended_maxsize"]
    info = function.cache_info()
    assert expected > 0
    assert info.maxsize == expected


@pytest.mark.parametrize(("function", "args"), _CANONICAL_CALLS)
def test_cache_clear_recomputes_the_same_geometry(
    function: _CacheFunction,
    args: tuple[object, ...],
) -> None:
    function.cache_clear()
    expected = function(*args)
    assert function.cache_info().currsize == 1
    function.cache_clear()
    assert function(*args) == expected
    assert function.cache_info().currsize == 1
    function.cache_clear()
```

Run:

```bash
uv run pytest tests/dsp/test_geometry_cache_bounds.py -q
```

Expected RED: the finite-bound test reports `cache_info().maxsize is None` for each current `@cache`. The recomputation characterization passes and proves the test infrastructure can clear every cache.

- [ ] **Step 6: Apply each report-derived bound directly with `lru_cache`**

Read the five `recommended_maxsize` integers from the committed report immediately before editing. In each source module, retain `cache` for unrelated singleton loaders and add/use `lru_cache` only for the named functions:

- `catalog.py`: change decorators on `collider_span` and `clearance`.
- `colliders.py`: change decorators on `own_centre_extent` and `belt_keepout_offsets`.
- `planet.py`: change the decorator on `collider_radius`; its imports already include both primitives.

For each function, set `maxsize` to that function's own exact report integer. Do not round again, copy another function's value, or centralize the five numbers in a new cache-policy module. The committed test compares each literal to the evidence report and will reject drift.

No function body, signature, docstring, exception path, public export, or caller changes in this step. Do not alter the unrelated `_table`, `_load`, catalog ID loaders, `bands(maxsize=8)`, or `build_graph(maxsize=1)` decorators.

- [ ] **Step 7: Run focused geometry behavior and retention tests**

```bash
uv run pytest \
  tests/dsp/test_geometry_cache_bounds.py \
  tests/dsp/test_catalog.py \
  tests/dsp/test_colliders.py \
  tests/dsp/test_planet.py \
  tests/scripts/test_measure_geometry_cache_working_sets.py -q
```

Expected: all pass. Existing exact clearance/rotation, own-centre extent, splitter keepout, and planet projection behavior remains unchanged; all five cache bounds equal the committed evidence and survive `cache_clear()`.

- [ ] **Step 8: Re-run measurement and enforce performance/retention gates**

```bash
uv run python scripts/measure_geometry_cache_working_sets.py \
  --samples 9 \
  --compare /tmp/geometry-cache-before.json \
  --output /tmp/geometry-cache-after.json
```

Expected:

- every actual `cache_info().maxsize` equals its report recommendation;
- each simulated bounded trace retains at least 99% of unbounded hits;
- each median replay time is no more than 5% slower than the same function's unbounded baseline;
- repeated canonical results remain identical after eviction/clear.

If timing noise alone crosses 5%, rerun both before and after reports in the same otherwise-idle environment with 21 samples. Do not relax the threshold based on a single noisy run.

- [ ] **Step 9: Commit the bounded decorators**

```bash
git add \
  src/flab2bp/dsp/catalog.py \
  src/flab2bp/dsp/colliders.py \
  src/flab2bp/dsp/planet.py \
  tests/dsp/test_geometry_cache_bounds.py
git commit -m "Bound public geometry caches"
```

---

### Task 4: Final Static, Whole-Suite, and Rollback Verification

**Files:**
- Verify only; no planned file changes.

**Interfaces:**
- Consumes all three task contracts and the before/after measurement reports.
- Produces release evidence; no additional cache conversions.

- [ ] **Step 1: Run all focused cache contracts together**

```bash
uv run pytest \
  tests/lab/test_techs.py \
  tests/lab/test_params.py::TestModHash \
  tests/lab/test_url.py \
  tests/dsp/test_geometry_cache_bounds.py \
  tests/dsp/test_catalog.py \
  tests/dsp/test_colliders.py \
  tests/dsp/test_planet.py \
  tests/scripts/test_measure_geometry_cache_working_sets.py -q
```

Expected: all pass in one process, proving one task's populated caches do not invalidate another's isolation assumptions.

- [ ] **Step 2: Run repository static checks**

```bash
uv run ruff check .
uv run mypy
```

Expected: both pass. Fix typing in the measurement/test protocols rather than weakening strictness or adding ignores around cache APIs.

- [ ] **Step 3: Run the full serial suite**

```bash
uv run pytest
```

Expected: the complete configured suite passes serially. Do not use `-n auto`; `pyproject.toml` explicitly documents solver oversubscription and shared test memo behavior.

- [ ] **Step 4: Reconfirm the performance report after the suite**

```bash
uv run python scripts/measure_geometry_cache_working_sets.py \
  --samples 21 \
  --compare /tmp/geometry-cache-before.json \
  --output /tmp/geometry-cache-final.json
```

Expected: the same 99% retention and 5% median-time gates pass. Do not commit `/tmp/geometry-cache-{before,after,final}.json`.

- [ ] **Step 5: Apply rollback criteria rather than hiding failures**

- **Task 1 correctness failure:** never restore URL-only explicit-dataset caching. If `maxsize=512` misses cause a demonstrated performance regression, keep the default/explicit split and gather a default-URL trace for a separately reviewed bound change.
- **Task 2 semantic failure:** if identity, explicit reread, or retry-after-exception changes, revert the decorator conversion to the prior manual default-only dictionary while retaining the new behavioral tests. Do not cache explicit paths or exception sentinels.
- **Task 3 empty/insufficient evidence:** if any function has no realistic trace or no candidate meets both selection predicates, revert that function to `@cache` and stop the Task 3 merge until the workload collector is corrected. Never insert a guessed finite number merely to make `maxsize is not None` pass.
- **Task 3 result failure:** if any canonical result changes after clear/eviction, revert that function's decorator-only commit and investigate unintended body/caller edits; eviction itself is not allowed to affect results.
- **Task 3 performance failure:** if a repeatable same-machine 21-sample median exceeds baseline by more than 5%, revert that function to `@cache`, preserve the report, and investigate working-set selection separately. Do not broaden a bound silently or suppress the comparison.
- **Excluded-cache failure:** do not modify `_ProjectionCache`, validator/kernel/per-build/local memos, the disk ETag cache, or mutable/cyclic caches to compensate for a failure in these tasks.

- [ ] **Step 6: Review commit boundaries and scope**

The implementation branch should contain exactly these logical commits after its base:

1. `Fix dataset isolation in belt rule cache`
2. `Use a decorator for vendored mod hashes`
3. `Measure geometry cache working sets`
4. `Bound public geometry caches`

Review the final diff and confirm no Portable/Task 9 code, unrelated cache decorator, validation behavior, kernel code, disk-cache behavior, or generic memoization primitive entered the branch.
