# Selected-Candidate Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a different candidate row is selected in the web UI's attempts table, the detailed report (Machines, Area, bands, Buildings, Makes, Belt in, unmarked-input warning, validation report, title) follows the selection instead of keep describing the winning attempt.

**Architecture:** The report panel already receives `selectedAttempt`, but every per-attempt fact it renders is read from top-level `result.*` fields, which `payload.describe` fills from the *chosen* attempt only. Fix end to end: `pipeline.Attempt` gains the `BuildSpec` it was laid out from, the web payload emits a per-attempt `detail` block, the zod `Attempt` schema requires it, and `BuildReportPanel` renders all per-attempt facts from `selectedAttempt.detail` with a result-derived fallback for the nothing-selectable case (invalid build, string withheld). Build-global facts (flow provenance, belt rules, refusals, elapsed) stay on `result`.

**Tech Stack:** Python 3.14 (pydantic specs, dataclasses, `uv run pytest`), React 19 + zod 4 + rstest (`web/`), oxlint/oxfmt/eslint + tsc for the web gates, ruff + mypy (strict) for Python.

**Spec:** The user-reported bug, verbatim: "In the web UI, when you change the selected candidate, it updates the blueprint string and the table, and the view. But it does not update the detailed info (what is getting belted in, etc) above the table and below the blueprint string."

## Global Constraints

- Python 3.14 is the authoritative runtime (`uv run …`).
- mypy is strict over `src` and `tests` (`[tool.mypy] files = ["src", "tests"]`); no new `Any`.
- ruff `check` (line length 100, rules E/F/I/UP/B/SIM) is the gate; `ruff format` is NOT enforced repo-wide — do not run `ruff format` on files you did not touch.
- Web gates: `bun run test`, `bun run typecheck`, `bun run lint` (oxlint + oxfmt --check + eslint) from `web/`.
- Full pytest suite is serial by design and must stay under ~150 s; do not add solver-heavy tests. The web session fixture `small_build` (one candidate, one strategy, 3 s budget) is shared — new Python tests must reuse it, not build again.
- Blueprint short titles must stay within 60 UTF-16 code units; this plan only *reports* existing titles, it never generates them.
- Every response is parsed by the zod schema in `web/src/api/build.ts`, so a Python payload change and the schema change must land before any UI change that relies on them (task order below enforces this).

---

### Task 1: Backend — each attempt carries its own `detail`

**Files:**
- Modify: `src/flab2bp/pipeline.py:265-279` (`Attempt` dataclass) and `src/flab2bp/pipeline.py:642-651` (its construction)
- Modify: `src/flab2bp/web/payload.py` (extract `_report_block`, add `_attempt_detail`, emit `"detail"` per attempt)
- Test: `tests/web/test_payload.py`

**Interfaces:**
- Consumes: `pipeline.Build`, `pipeline.Attempt`, `BuildSpec`, `markers.unmarked_external_inputs`, `validate.Report` — all existing.
- Produces: `Attempt.spec: BuildSpec` (new field, position 3); `describe(build)["attempts"][i]["detail"]` — a JSON object with keys `machines` (int), `buildings` (int), `primary_band` (int), `certified_bands` (list[int]), `title` (str), `outputs` (dict item → `{"exact": str, "per_minute": float}`), `external_inputs` (same rate shape), `input_markers` (int), `unmarked_inputs` (list[str]), `report` (`{"ok", "checks_run", "skipped", "errors", "warnings"}`, same shape as the top-level `report`). Tasks 2–3 depend on exactly these names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_payload.py` (imports `dataclasses`, `Fraction`, `pytest`, `describe`, `pipeline` already exist at the top of that file):

```python
def test_each_attempt_carries_its_own_detail(small_build: pipeline.Build) -> None:
    """The candidate table selects what the report describes, so every attempt
    carries its own boundary facts rather than inheriting the winner's."""
    sprayed = small_build.spec.model_copy(
        update={
            "external_inputs": {
                **small_build.spec.external_inputs,
                "proliferator-mk-iii": Fraction(1),
            }
        }
    )
    retitled = dataclasses.replace(
        small_build.attempts[0].placement,
        short_desc="electromagnetic-matrix 60/min (all products)",
        stats={**small_build.attempts[0].placement.stats, "input_markers": 0},
    )
    other = dataclasses.replace(
        small_build.attempts[0],
        candidate="all-products",
        spec=sprayed,
        placement=retitled,
    )
    multi = dataclasses.replace(small_build, attempts=(*small_build.attempts, other))

    body = describe(multi)
    winner, loser = body["attempts"]
    assert isinstance(winner, dict) and isinstance(loser, dict)

    # The winner's detail is exactly what the top level has always said.
    for field in (
        "machines",
        "buildings",
        "primary_band",
        "certified_bands",
        "title",
        "outputs",
        "external_inputs",
        "input_markers",
        "unmarked_inputs",
        "report",
    ):
        assert winner["detail"][field] == body[field]

    # The loser's differs where the candidate differs: belt-in, markers, title.
    assert "proliferator-mk-iii" in loser["detail"]["external_inputs"]
    assert loser["detail"]["external_inputs"] != body["external_inputs"]
    assert "proliferator-mk-iii" in loser["detail"]["unmarked_inputs"]
    assert loser["detail"]["title"] == "electromagnetic-matrix 60/min (all products)"
    assert loser["detail"]["input_markers"] == 0


def test_an_attempt_without_a_frame_is_a_payload_error(
    small_build: pipeline.Build,
) -> None:
    """An attempt with no band evidence is refused, like the chosen one is."""
    unframed = dataclasses.replace(
        small_build.attempts[0],
        placement=dataclasses.replace(small_build.attempts[0].placement, frame=None),
    )
    built = dataclasses.replace(small_build, attempts=(unframed,))

    with pytest.raises(ValueError, match="area frame"):
        describe(built)
```

Note: `test_an_attempt_without_a_frame_is_a_payload_error` replaces only the *attempt's* placement, so `build.placement` (same original object) stays framed and `describe` reaches the attempt loop before raising.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_payload.py -q`
Expected: both new tests FAIL — the first with `KeyError: 'detail'` (or a `TypeError` constructing `Attempt` with `spec=`), the second does NOT raise (no `detail` computed yet).

- [ ] **Step 3: Add `spec` to `pipeline.Attempt`**

In `src/flab2bp/pipeline.py`, replace the dataclass (current lines 265–279):

```python
@dataclass(frozen=True, slots=True)
class Attempt:
    """One (candidate, strategy) pair laid out."""

    candidate: str
    strategy: str
    #: The spec this attempt was laid out from.  The web payload reports each
    #: attempt's own boundary -- machines, belt-in, outputs -- and without the
    #: spec only the winner's would survive to JSON.
    spec: BuildSpec
    placement: Placement
    report: validate.Report
    blueprint: str
    #: Measured before display-only input markers are added to the blueprint.
    layout_area: int

    @property
    def area(self) -> int:
        return self.layout_area

    @property
    def ok(self) -> bool:
        return self.report.ok
```

and its only construction site (current lines 642–651) to:

```python
            attempts.append(
                Attempt(
                    spec.label,
                    sname,
                    spec,
                    labelled,
                    report,
                    blueprint,
                    placement.area,
                )
            )
```

`Attempt` is constructed nowhere else in `src/` (verified: only this site; `bench/ab.py`'s `MeasuredAttempt` and `layout/freeform.py`'s `PackAttempt` are unrelated types), and the CLI reads attempts by attribute only.

- [ ] **Step 4: Emit the per-attempt `detail` in the payload**

In `src/flab2bp/web/payload.py`:

Add `validate` to the layout import and two helpers after `_rates`:

```python
from flab2bp.layout import markers, validate
```

```python
def _report_block(report: validate.Report) -> Json:
    """A validation report as JSON, identical shape for the winner and losers."""
    return {
        "ok": report.ok,
        "checks_run": _array(report.checks_run),
        "skipped": _array(report.skipped),
        "errors": [
            {"check": finding.check, "message": finding.message} for finding in report.errors
        ],
        "warnings": [
            {"check": finding.check, "message": finding.message} for finding in report.warnings
        ],
    }


def _attempt_detail(attempt: pipeline.Attempt) -> Json:
    """One attempt's own facts: what IT belts in, makes, and costs.

    The candidate table lets a player view a losing attempt, and the report
    above it must follow that selection rather than keep describing the
    winner -- an ``all-products`` selection next to a ``no-proliferator``
    winner differs in machines, in belt-in, and in markers.
    """
    frame = attempt.placement.frame
    if frame is None:
        raise ValueError("successful build placement has no area frame")
    spec = attempt.spec
    unmarked = markers.unmarked_external_inputs(attempt.placement, spec)
    return {
        "machines": spec.machine_count,
        "buildings": len(attempt.placement.buildings),
        "primary_band": frame.primary_band,
        "certified_bands": _array(frame.certified_bands),
        "title": attempt.placement.short_desc,
        "outputs": _rates(dict(spec.outputs)),
        "external_inputs": _rates(dict(spec.external_inputs)),
        "input_markers": int(attempt.placement.stats.get("input_markers", 0)),
        "unmarked_inputs": _array(sorted(unmarked)),
        "report": _report_block(attempt.report),
    }
```

In `describe`, add `"detail": _attempt_detail(attempt),` to the per-attempt dict (after `"blueprint"`), and replace the inline top-level `"report": {...}` value with `"report": _report_block(build.report),` (deleting the now-duplicated `errors`/`warnings` local lists if nothing else uses them — nothing else does). The docstring of `describe` stays true as written.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_payload.py tests/web -q`
Expected: PASS, including the pre-existing payload tests (top-level fields unchanged).

- [ ] **Step 6: Lint and type-check Python**

Run: `uv run ruff check src tests && uv run mypy`
Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/pipeline.py src/flab2bp/web/payload.py tests/web/test_payload.py
git commit -m "feat: report each attempt's own machines, belt-in, and report in the web payload"
```

---

### Task 2: Frontend contract — zod requires per-attempt `detail`; fixtures carry it

**Files:**
- Modify: `web/src/api/build.ts:70-118` (`Attempt`, new `AttemptDetail`, shared `Report`, exported type)
- Modify: `web/tests/support/build.ts` (new `anAttemptDetail`/`anAttempt` helpers; `aResult` threads overrides into the chosen attempt's detail)
- Modify: `web/tests/api/build.test.ts:156-174` (inline attempt now built from the helper) and add a drift test

**Interfaces:**
- Consumes: Task 1's payload keys (`detail.machines`, `detail.buildings`, `detail.primary_band`, `detail.certified_bands`, `detail.title`, `detail.outputs`, `detail.external_inputs`, `detail.input_markers`, `detail.unmarked_inputs`, `detail.report`).
- Produces for Task 3: exported type `AttemptDetail` from `web/src/api/build.ts`; `anAttempt(overrides?: Partial<Attempt>): Attempt` and `anAttemptDetail(overrides?: Partial<AttemptDetail>): AttemptDetail` from `web/tests/support/build.ts`; the invariant that `aResult(...)`'s chosen attempt detail mirrors every overridden per-attempt top-level field (`title`, `report`, `machines`, `buildings`, `primary_band`, `certified_bands`, `outputs`, `external_inputs`, `input_markers`, `unmarked_inputs`, `area`).

- [ ] **Step 1: Write the failing tests**

In `web/tests/api/build.test.ts`, change the sequence-pair test's fixture (current lines 156–174) and add a drift test after it:

```ts
test('sequence-pair is accepted as an explicit response strategy', async () => {
  const result = aResult({
    strategy: 'sequence-pair',
    attempts: [anAttempt({ strategy: 'sequence-pair' })],
  });
  serving({ status: 200, body: aJob({ result }) });
  const job = await pollBuild('x');
  expect(job.result?.strategy).toBe('sequence-pair');
});

test('an attempt without its own detail is rejected rather than half-described', async () => {
  // The report follows the SELECTED attempt; an attempt missing its detail
  // would silently fall back to describing the winner, which is the bug this
  // schema tightened to prevent.
  const bare: Record<string, unknown> = { ...anAttempt() };
  delete bare.detail;
  serving({ status: 200, body: aJob({ result: { ...aResult(), attempts: [bare] } }) });
  await expect(pollBuild('x')).rejects.toThrow();
});
```

Add `anAttempt` to the existing import from `'../support/build'`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && bun run test`
Expected: FAILURES across every test whose fixture builds an attempt — the zod schema does not know `detail`, so `anAttempt`/`anAttemptDetail` do not exist yet (compile error) and the drift test cannot pass.

- [ ] **Step 3: Extend the schema**

In `web/src/api/build.ts`, replace the `Attempt` schema (current lines 70–79) and the inline `report` in `BuildResult` (current lines 110–116):

```ts
const Report = z.object({
  ok: z.boolean(),
  checks_run: z.array(z.string()),
  skipped: z.array(z.string()),
  errors: z.array(Finding),
  warnings: z.array(Finding),
});

/**
 * One candidate's own facts. The report panel describes the SELECTED attempt,
 * so every attempt carries its own boundary — what it belts in, what it makes,
 * what it costs — rather than inheriting the winner's.
 */
const AttemptDetail = z.object({
  machines: z.number(),
  buildings: z.number(),
  primary_band: z.number(),
  certified_bands: z.array(z.number()),
  title: z.string(),
  outputs: z.record(z.string(), Rate),
  external_inputs: z.record(z.string(), Rate),
  input_markers: z.number(),
  unmarked_inputs: z.array(z.string()),
  report: Report,
});

const Attempt = z.object({
  candidate: z.string(),
  strategy: ExplicitStrategy,
  area: z.number(),
  ok: z.boolean(),
  errors: z.number(),
  chosen: z.boolean(),
  /** Withheld for an invalid attempt unless allow_invalid was requested. */
  blueprint: z.string().nullable(),
  detail: AttemptDetail,
});
```

Inside `BuildResult`, replace the inline report object with `report: Report,`. Add to the type exports next to `export type Attempt`:

```ts
export type AttemptDetail = z.infer<typeof AttemptDetail>;
```

- [ ] **Step 4: Update the shared fixtures**

In `web/tests/support/build.ts`, add the two helpers above `aResult` and rewrite `aResult` so the chosen attempt mirrors the result (this is what production emits — top-level fields ARE the chosen attempt's):

```ts
import { readFileSync } from 'node:fs';
import type { Attempt, AttemptDetail, BuildResult, Job } from '../../src/api/build';

export function anAttemptDetail(overrides: Partial<AttemptDetail> = {}): AttemptDetail {
  return {
    machines: 9,
    buildings: 42,
    primary_band: 160,
    certified_bands: [160, 200],
    title: 'electromagnetic-matrix 60/min',
    outputs: { 'electromagnetic-matrix': { exact: '1', per_minute: 60 } },
    external_inputs: { 'magnetic-coil': { exact: '5/6', per_minute: 50 } },
    input_markers: 1,
    unmarked_inputs: [],
    report: { ok: true, checks_run: ['power'], skipped: [], errors: [], warnings: [] },
    ...overrides,
  };
}

export function anAttempt(overrides: Partial<Attempt> = {}): Attempt {
  return {
    candidate: 'no-proliferator',
    strategy: 'freeform',
    area: 575,
    ok: true,
    errors: 0,
    chosen: true,
    blueprint: A_BLUEPRINT,
    detail: anAttemptDetail(),
    ...overrides,
  };
}

export function aResult(overrides: Partial<BuildResult> = {}): BuildResult {
  const blueprint = overrides.blueprint === undefined ? A_BLUEPRINT : overrides.blueprint;
  const base = {
    blueprint,
    valid: true,
    strategy: 'freeform',
    candidate: 'no-proliferator',
    machines: 9,
    area: 575,
    primary_band: 160,
    certified_bands: [160, 200],
    buildings: 42,
    title: 'electromagnetic-matrix 60/min',
    description: 'flab2bp freeform layout',
    outputs: { 'electromagnetic-matrix': { exact: '1', per_minute: 60 } },
    external_inputs: { 'magnetic-coil': { exact: '5/6', per_minute: 50 } },
    input_markers: 1,
    unmarked_inputs: [] as string[],
    flow_pinned: false,
    flow_findings: [] as string[],
    belt_rules: { max_z: 26.55, lab_level: 9, vertical_construction: true, from_url: false },
    refused: [] as BuildResult['refused'],
    report: { ok: true, checks_run: ['power'], skipped: [], errors: [], warnings: [] },
  };
  const merged = { ...base, ...overrides };
  // The top level describes the chosen attempt, so the fixture keeps them
  // equal — exactly what `flab2bp.web.payload.describe` emits.
  return {
    ...merged,
    attempts: [
      anAttempt({
        blueprint,
        area: merged.area,
        detail: anAttemptDetail({
          machines: merged.machines,
          buildings: merged.buildings,
          primary_band: merged.primary_band,
          certified_bands: merged.certified_bands,
          title: merged.title,
          outputs: merged.outputs,
          external_inputs: merged.external_inputs,
          input_markers: merged.input_markers,
          unmarked_inputs: merged.unmarked_inputs,
          report: merged.report,
        }),
      }),
    ],
  };
}
```

(`A_BLUEPRINT`/`B_BLUEPRINT` and the `Scripted`/`serving`/`restoreFetch`/`aJob` parts of the file are unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && bun run test`
Expected: PASS — including the previously-failing UI tests, because every `aResult()`-built chosen attempt now carries a coherent `detail`.

- [ ] **Step 6: Type-check and lint**

Run: `cd web && bun run typecheck && bun run lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/build.ts web/tests/support/build.ts web/tests/api/build.test.ts
git commit -m "feat: require each attempt's own detail in the web response schema"
```

---

### Task 3: UI — the report describes the selected candidate

**Files:**
- Modify: `web/src/ui/BuildReport.tsx:65-269` (`BuildReportPanel`)
- Modify: `web/src/ui/BuildPanel.tsx:371-373` (blueprint title strong)
- Test: `web/tests/ui/BuildReport.test.tsx`, `web/tests/ui/BuildPanel.test.tsx`

**Interfaces:**
- Consumes: `AttemptDetail` type (Task 2), `anAttempt`/`anAttemptDetail` fixtures (Task 2), `selectedAttempt: Attempt | null` prop (existing).
- Produces: no new public components or props. Rendered behavior contract: with a non-chosen attempt selected, `report-title`, the `<dl>` (Showing/Machines/Area/primary_band/certified_bands/Buildings/Makes/Belt in), the unmarked-inputs warning, the skipped/warnings/errors blocks, and `blueprint-title` all describe the selected attempt; with `selectedAttempt === null` they describe the result exactly as before.

- [ ] **Step 1: Write the failing component test**

Append to `web/tests/ui/BuildReport.test.tsx` (add `anAttempt`, `anAttemptDetail` to the `'../support/build'` import; add `import type { Attempt } from '../../src/api/build';`):

```tsx
test('the report describes the selected candidate, not just the winner', () => {
  const result = aResult();
  const alternative: Attempt = anAttempt({
    candidate: 'all-products',
    chosen: false,
    area: 640,
    detail: anAttemptDetail({
      machines: 13,
      buildings: 51,
      primary_band: 200,
      certified_bands: [200],
      title: 'electromagnetic-matrix 60/min (all products)',
      external_inputs: {
        'magnetic-coil': { exact: '5/6', per_minute: 50 },
        'proliferator-mk-iii': { exact: '1', per_minute: 60 },
      },
      input_markers: 2,
    }),
  });

  render(
    <BuildReportPanel
      result={result}
      selectedAttempt={alternative}
      onSelectAttempt={() => {}}
    />,
  );

  expect(screen.getByTestId('report-title')).toHaveTextContent('(all products)');
  expect(screen.getByText('Showing').nextElementSibling).toHaveTextContent(
    'freeform / all-products',
  );
  expect(screen.getByText('Machines').nextElementSibling).toHaveTextContent('13');
  expect(screen.getByText('Area').nextElementSibling).toHaveTextContent('640 tiles');
  expect(screen.getByText('primary_band').nextElementSibling).toHaveTextContent('200');
  expect(screen.getByText('certified_bands').nextElementSibling).toHaveTextContent('200');
  expect(screen.getByText('Buildings').nextElementSibling).toHaveTextContent('51');
  expect(screen.getByText('Belt in').nextElementSibling).toHaveTextContent(
    'magnetic-coil, proliferator-mk-iii (2 marked with icons)',
  );
});
```

And in `web/tests/ui/BuildPanel.test.tsx`, rewrite `candidateResult` (current lines 34–67) so each row carries its own detail:

```ts
function candidateResult(chosenBlueprint = A_BLUEPRINT, alternativeBlueprint = B_BLUEPRINT) {
  return {
    ...aResult({ blueprint: chosenBlueprint }),
    attempts: [
      anAttempt({ blueprint: chosenBlueprint }),
      anAttempt({
        candidate: 'all-products',
        strategy: 'sequence-pair',
        area: 640,
        chosen: false,
        blueprint: alternativeBlueprint,
        detail: anAttemptDetail({
          machines: 13,
          buildings: 51,
          primary_band: 200,
          certified_bands: [200],
          title: 'electromagnetic-matrix 60/min (all products)',
          external_inputs: {
            'magnetic-coil': { exact: '5/6', per_minute: 50 },
            'proliferator-mk-iii': { exact: '1', per_minute: 60 },
          },
          input_markers: 2,
        }),
      }),
      anAttempt({
        candidate: 'output-products',
        strategy: 'freeform',
        area: 490,
        ok: false,
        errors: 1,
        chosen: false,
        blueprint: null,
      }),
    ],
  };
}
```

(add `anAttempt`, `anAttemptDetail` to that file's `'../support/build'` import), then extend the existing selection test `'candidate rows select the blueprint string, viewer model, and copy source'` — after the existing `fireEvent.click(alternative);` assertions block (current lines 238–246), add:

```tsx
  // The report above the table follows the selection too, not just the string.
  expect(screen.getByTestId('report-title')).toHaveTextContent('(all products)');
  expect(screen.getByTestId('blueprint-title')).toHaveTextContent(
    'electromagnetic-matrix 60/min (all products)',
  );
  expect(screen.getByText('Showing').nextElementSibling).toHaveTextContent(
    'sequence-pair / all-products',
  );
  expect(screen.getByText('Machines').nextElementSibling).toHaveTextContent('13');
  expect(screen.getByText('Area').nextElementSibling).toHaveTextContent('640 tiles');
  expect(screen.getByText('Belt in').nextElementSibling).toHaveTextContent(
    'proliferator-mk-iii',
  );
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && bun run test`
Expected: the new BuildReport test FAILS (`report-title` still shows the winner's title, `Machines` shows 9, `Belt in` lacks proliferator-mk-iii, no `Showing` term); the extended BuildPanel test FAILS the same way after the click.

- [ ] **Step 3: Render the report from the selection**

In `web/src/ui/BuildReport.tsx`:

Add `AttemptDetail` to the type import from `'../api/build'`, then replace the top of `BuildReportPanel` (current lines 76–78) and every per-attempt read in its body:

```tsx
  // The panel describes the SELECTED candidate, and falls back to the winner
  // only when nothing is selectable — an invalid build withholds every string,
  // and its report is still the thing to show.  Build-global facts (flow
  // provenance, belt rules, refusals) stay on `result` regardless.
  const shown: AttemptDetail = selectedAttempt?.detail ?? {
    machines: result.machines,
    buildings: result.buildings,
    primary_band: result.primary_band,
    certified_bands: result.certified_bands,
    title: result.title,
    outputs: result.outputs,
    external_inputs: result.external_inputs,
    input_markers: result.input_markers,
    unmarked_inputs: result.unmarked_inputs,
    report: result.report,
  };
  const strategy = selectedAttempt?.strategy ?? result.strategy;
  const candidate = selectedAttempt?.candidate ?? result.candidate;
  const area = selectedAttempt?.area ?? result.area;
  const viewingLoser = selectedAttempt !== null && !selectedAttempt.chosen;
  const inputs = Object.keys(shown.external_inputs);
  const belt = result.belt_rules;
```

Then, inside the JSX, swap the reads:

- `<h2 data-testid="report-title">{result.title}</h2>` → `{shown.title}` (keep the comment above it, adjusting "the blueprint's own name" wording only if you touch it).
- The `<dl>`: `Won with` dt becomes `{viewingLoser ? 'Showing' : 'Won with'}`; its dd `{strategy} / {candidate}`; `Machines` → `{shown.machines}`; `Area` → `{area} tiles`; `primary_band` → `{shown.primary_band}`; `certified_bands` → `{shown.certified_bands.join(', ')}`; `Buildings` → `{shown.buildings}`; `Makes` maps `Object.entries(shown.outputs)`; `Belt in` uses `inputs` and `{shown.input_markers}`. `Solved in`/elapsed stays on `elapsedS`.
- Unmarked warning: `shown.unmarked_inputs.length > 0` and `shown.unmarked_inputs.join(', ')`.
- Flow-pinned/derived paragraph and the belt-rules paragraphs: UNCHANGED (build-global).
- Refused block: UNCHANGED (build-global).
- Skipped note: `shown.report.skipped`.
- Warnings block: `shown.report.warnings.length > 0`, mapping `shown.report.warnings`.
- Errors block: `shown.report.errors.length > 0`, mapping `shown.report.errors`.
- Attempts table: UNCHANGED.

In `web/src/ui/BuildPanel.tsx` (current lines 371–373), the title shown beside the string is the selected blueprint's own name:

```tsx
              <strong className="bp-title" data-testid="blueprint-title">
                {selectedAttempt?.detail.title ?? job.result.title}
              </strong>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && bun run test`
Expected: PASS — including the pre-existing tests (`primary_band` frame test passes `selectedAttempt={null}` so it exercises the fallback; the warnings test and title test pass because Task 2's `aResult` threads their overrides into the chosen attempt's detail).

- [ ] **Step 5: Type-check and lint**

Run: `cd web && bun run typecheck && bun run lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/ui/BuildReport.tsx web/src/ui/BuildPanel.tsx web/tests/ui/BuildReport.test.tsx web/tests/ui/BuildPanel.test.tsx
git commit -m "fix: the web report follows the selected candidate, not just the winner"
```

---

### Task 4: Whole-repo verification gate

**Files:**
- None created or modified.

**Interfaces:**
- Consumes: Tasks 1–3, all merged on the branch.
- Produces: evidence that nothing else regressed (Python suite includes `test_pipeline.py`, CLI strategy tests, and web server/jobs tests that consume `describe` output; web suite includes every panel and schema test).

- [ ] **Step 1: Full Python suite, lint, types**

Run: `uv run pytest -q && uv run ruff check src tests && uv run mypy`
Expected: all pass; suite runtime within the ~150 s target (unchanged solver load — only the shared `small_build` fixture is exercised by the new tests).

- [ ] **Step 2: Full web suite, types, lint, production build**

Run: `cd web && bun run test && bun run typecheck && bun run lint && bun run build`
Expected: all pass; build emits the single `index` entry as before.

- [ ] **Step 3: Manual smoke on the dev stack**

Run: `cd web && bun run dev` (Python API on 8000, Rsbuild on 3001), then in the browser at `http://localhost:3001`: paste a small FactorioLab URL (e.g. `https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11`), keep at least two candidate policies checked, Build, then click a non-winning row in the attempts table and confirm the Belt in / Machines / Makes lines and the title above the string change with it; click back on the winning row and confirm they revert. Stop with Ctrl-C (both processes die together by design). No commit — no code changed.

---

## Self-Review

**Spec coverage:** The user's complaint — detailed info above the table and below the blueprint string not updating on candidate change — is covered by Task 3 (report panel + title) with the data it needs supplied by Tasks 1–2. The blueprint string, table, and view already updated; nothing in this plan touches them. The dl's `Solved in`, flow-provenance, belt-rules, and refused sections describe the build rather than an attempt and deliberately stay fixed.

**Placeholder scan:** No TBD/TODO/"add tests" steps; every step carries exact code or an exact command with expected output.

**Type consistency:** `AttemptDetail` name and its ten keys are identical across Task 1 (`_attempt_detail`), Task 2 (zod schema + `anAttemptDetail`), and Task 3 (`shown` view-model). `anAttempt`/`anAttemptDetail` signatures match their Task 3 imports. `pipeline.Attempt` field order in Task 1 Step 3 matches the positional call in the same step. `certified_bands: [160, 200]` in the zod schema (`z.array(z.number())`) accepts the Python list; `primary_band`/`buildings`/`machines`/`input_markers` are JSON ints into `z.number()`.
