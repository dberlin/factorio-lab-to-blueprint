# Named Candidate Policies Web Cutover Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the misleading numeric web “Candidates” input with explicit checkboxes for `all-products`, `output-products`, and `no-proliferator`, all selected by default.

**Architecture:** Define one typed Python candidate-policy vocabulary and preserve its canonical rate-solver order. Thread a non-empty immutable policy subset through pipeline and web options. Mirror the exact labels in a strict Zod enum and render three checkboxes. This UX cutover is independent of solver reliability repairs.

**Tech Stack:** Python 3.14, immutable enums/tuples, Pydantic models, React 19, TypeScript, Zod, pytest, Vitest, Ruff, strict MyPy, Biome.

## Constraints

- All three policies remain selected by default.
- Empty, duplicate, numeric, and unknown policy selections are rejected rather than guessed or clamped.
- Rate solving emits selected policies in canonical order regardless of checkbox click order.
- A pinned FactorioLab flow remains one authoritative candidate; derived policy selection does not rewrite it.
- Define `effective_candidate_count = 1` when `flow` text is present or `fetch_flow` is selected; otherwise use `len(candidate_policies)`. Solver ceiling and progress totals use that effective count.
- Historical benchmark result fields may retain numeric cardinality where they describe observed samples; production request semantics may not.
- This plan does not change proliferation formulas, solver budgets, layout strategy behavior, or reliability gates.

---

### Task 1: Add typed candidate-policy selection to rates and pipeline

**Files:**
- Modify: `src/flab2bp/rates/candidates.py`
- Modify: `src/flab2bp/rates/__init__.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: production callers identified by LSP references
- Modify: `tests/rates/test_candidates.py`
- Modify: `tests/rates/test_candidates_flow_pin.py`
- Modify: `tests/test_pipeline.py`

- [ ] Run LSP references for exported `build_candidates`, `_build_candidates_canonical`, and `pipeline.build`; record every production caller before editing.
- [ ] Define `CandidatePolicy` and canonical order for `no-proliferator`, `all-products`, and `output-products` next to the existing policy implementations.
- [ ] Add RED tests for each single-policy subset, representative two-policy subsets, all-three default, request-order normalization, and empty/duplicate/unknown rejection.
- [ ] Replace production `count` inputs with `candidate_policies: tuple[CandidatePolicy, ...]` and migrate every caller. Do not keep a count alias or compatibility shim.
- [ ] Filter policy construction before expensive solves while retaining canonical output order and existing runaway-candidate handling.
- [ ] Preserve pinned-flow behavior as one authoritative candidate.
- [ ] Run:

```bash
uv run pytest -q tests/rates/test_candidates.py tests/rates/test_candidates_flow_pin.py tests/test_pipeline.py -k "candidate or policy or flow"
uv run ruff check src/flab2bp/rates/candidates.py src/flab2bp/rates/__init__.py src/flab2bp/pipeline.py tests/rates/test_candidates.py tests/rates/test_candidates_flow_pin.py tests/test_pipeline.py
uv run mypy src/flab2bp/rates/candidates.py src/flab2bp/rates/__init__.py src/flab2bp/pipeline.py tests/rates/test_candidates.py tests/rates/test_candidates_flow_pin.py tests/test_pipeline.py
```

**Acceptance:** Derived production callers receive exactly the selected policies in canonical order; pinned flow emits exactly one authoritative candidate independent of the selected derived-policy subset.

---

### Task 2: Cut web request semantics over to named policies

**Files:**
- Modify: `src/flab2bp/web/jobs.py`
- Modify: `tests/web/test_options.py`
- Modify: `tests/web/test_jobs.py`
- Modify: `web/src/api/build.ts`
- Modify: `web/src/ui/BuildPanel.tsx`
- Modify: `web/tests/api/build.test.ts`
- Modify: `web/tests/ui/BuildPanel.test.tsx`

- [ ] Add a matching Zod `CandidatePolicy` enum and change `BuildOptions` from numeric `candidates` to a non-empty policy array/tuple.
- [ ] Add RED API tests proving all-three default, exact subsets, empty/numeric/duplicate/unknown refusal, and strict request serialization.
- [ ] Change Python `Options` and `parse_options` to the same named tuple. Reject the legacy numeric field as unknown input.
- [ ] Add one `effective_candidate_count` property used by solver ceiling, progress totals, and error text: one for `flow`/`fetch_flow`, otherwise `len(candidate_policies)`.
- [ ] Replace the numeric input with a `fieldset` containing three labeled checkboxes in user-requested order: `all-products`, `output-products`, `no-proliferator`.
- [ ] Keep all checked by default. Disable Build and render an inline validation message when none are checked.
- [ ] Preserve canonical backend order; UI order is presentation only.
- [ ] Run:

```bash
uv run pytest -q tests/web/test_options.py tests/web/test_jobs.py -k "candidate or policy or ceiling or progress or pinned_flow"
uv run ruff check src/flab2bp/web/jobs.py tests/web/test_options.py tests/web/test_jobs.py
uv run mypy src/flab2bp/web/jobs.py tests/web/test_options.py tests/web/test_jobs.py
cd web && bun run test -- tests/api/build.test.ts tests/ui/BuildPanel.test.tsx
cd web && bun run lint
cd web && bun run typecheck
```

**Acceptance:** Web users select any non-empty subset with all checked by default; derived jobs advertise that subset's work, while pinned-flow jobs advertise and execute exactly one candidate.

---

### Task 3: Migrate CLI and intentional benchmark callers

**Files:**
- Modify: `src/flab2bp/cli.py`
- Modify: `src/flab2bp/bench/runner.py`
- Modify: `src/flab2bp/bench/__main__.py`
- Modify: other callers from the Task 1 reference inventory
- Modify: focused CLI and benchmark tests

- [ ] Replace CLI `--candidates N` with a repeatable/comma-delimited `--candidate-policy` using the exact public labels and all-three default.
- [ ] Migrate benchmark execution callers to explicit policy tuples while preserving numeric sample-cardinality fields in stored result metadata and promotion manifests.
- [ ] Add RED CLI tests for default, subset, empty, duplicate, and unknown selections.
- [ ] Confirm audit/corpus jobs still produce the same three canonical candidate identities by default.
- [ ] Run focused CLI/benchmark tests, Ruff, and MyPy for every migrated file.

**Acceptance:** Every production caller uses named policies; numeric cardinality remains only where it is descriptive result metadata, never request behavior.

---

### Task 4: Verify the complete cutover

- [ ] Run all candidate, pipeline, web-option, job, CLI, and frontend focused tests.
- [ ] Run Ruff, strict MyPy, web lint, TypeScript typecheck, and web production build.
- [ ] Browser-drive the actual Build panel: confirm three checkboxes, all checked default, subset submission, and disabled empty selection.
- [ ] Run one production CLI smoke with a two-policy subset and require progress/attempt identities to contain only that subset.
- [ ] Request whole-range review for missed numeric callers or duplicate policy authorities.

**Acceptance:** No production request surface exposes numeric candidate semantics; actual UI/API/CLI behavior and work totals match the named non-empty subset end to end.
