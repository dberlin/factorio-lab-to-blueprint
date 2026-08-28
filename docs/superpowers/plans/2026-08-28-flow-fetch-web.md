# Safe Flow Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Python 3.14 flow capture and expose it as a safe, explicit, mutually exclusive web option.

**Architecture:** Pin the newest nodriver wheel whose Python source is valid UTF-8, preserve the existing CLI flow precedence, and carry a `fetch_flow` boolean through the web request boundary. The web path supplies an allowlist validator to capture so both the requested and final main-frame URLs must remain on the supported FactorioLab HTTPS pages.

**Tech Stack:** Python 3.14, nodriver 0.47.0, pytest, Pydantic-backed validation, React 19, TypeScript, Zod, Rstest, Testing Library, Biome.

**Spec:** `docs/superpowers/specs/2026-08-28-portable-bands-and-flow-fetch-design.md`

## Global Constraints

- Required Python runtime remains `>=3.14`.
- Pin `nodriver==0.47.0`; releases 0.48.0 through 0.50.3 contain invalid non-UTF-8 Python source.
- Web automatic fetch accepts only `https://factoriolab.github.io/dsp/list` and `/dsp/flow`, with no nonstandard port.
- Validate the final `location.href` before solve probes or CSV clicks; redirects outside the allowlist refuse.
- Web `flow` and `fetch_flow` are mutually exclusive; CLI `--flow` continues to win over `--fetch-flow`.
- Capture failure never falls back to re-derived recipe selection.
- `fetch_flow` defaults to false and the UI checkbox defaults unchecked.
- Do not add a web timeout control; use the existing 90-second capture default.
- Every production change follows red-green TDD.

---

### Task 1: Pin an Importable Browser Driver

**Files:**
- Modify: `pyproject.toml:10-24`
- Modify: `uv.lock`
- Test: `tests/lab/test_capture.py`

**Interfaces:**
- Consumes: Python's normal import machinery.
- Produces: an installed `nodriver` module that imports under Python 3.14 and still provides callable `start()`.

- [ ] **Step 1: Add a regression that imports the declared capture dependency**

Add near the top-level capture dependency tests:

```python
def test_declared_nodriver_imports_on_the_supported_runtime() -> None:
    module = importlib.import_module("nodriver")
    assert callable(getattr(module, "start", None))
```

Add `import importlib` with the existing standard-library imports. This test must use the real installed dependency; do not monkeypatch `find_spec` or `import_module`.

- [ ] **Step 2: Run the regression and verify the current lock fails for the packaging defect**

Run:

```bash
uv run pytest tests/lab/test_capture.py::test_declared_nodriver_imports_on_the_supported_runtime -q
```

Expected: FAIL with `SyntaxError: Non-UTF-8 code starting with '\xb1'` from `nodriver/cdp/network.py`.

- [ ] **Step 3: Pin the newest valid wheel and regenerate the environment**

Change the dependency entry to:

```toml
"nodriver==0.47.0",
```

Then run:

```bash
uv lock
uv sync
```

Confirm `uv.lock` records exactly `version = "0.47.0"` and the project dependency records `specifier = "==0.47.0"`.

- [ ] **Step 4: Verify import and focused capture unit tests**

Run:

```bash
uv run pytest tests/lab/test_capture.py::test_declared_nodriver_imports_on_the_supported_runtime tests/lab/test_capture.py -q
```

Expected: PASS. `nodriver==0.47.0` may emit its known third-party `SyntaxWarning` from `connection.py`; leave that upstream warning visible and do not add a repository-wide warning filter. The acceptance criterion is an importable dependency and successful capture, not warning suppression.

- [ ] **Step 5: Commit the dependency fix**

```bash
git add pyproject.toml uv.lock tests/lab/test_capture.py
git commit -m "Pin importable nodriver release"
```

---

### Task 2: Validate Web Fetch Requests and Final Navigation

**Files:**
- Modify: `src/flab2bp/lab/capture.py:59-78, 92-113, 308-387`
- Modify: `src/flab2bp/pipeline.py:250-320`
- Modify: `src/flab2bp/web/jobs.py:34-169, 210-231`
- Test: `tests/lab/test_capture.py`
- Test: `tests/web/test_options.py`
- Test: `tests/web/test_jobs.py`

**Interfaces:**
- Consumes: `capture_flow_csv(url, *, timeout_s, browser, headless)` and `pipeline.build(..., fetch_flow, fetch_timeout_s, browser)`.
- Produces:
  - `type UrlValidator = Callable[[str], None]` in `capture.py`;
  - `capture_flow_csv(..., url_validator: UrlValidator | None = None) -> str`;
  - `pipeline.build(..., fetch_url_validator: UrlValidator | None = None) -> Build`;
  - `Options.fetch_flow: bool = False`;
  - `_validate_web_fetch_url(url: str) -> None` in `web/jobs.py`.

- [ ] **Step 1: Add failing request-boundary tests**

Extend `tests/web/test_options.py`:

```python
def test_fetch_flow_defaults_off_and_accepts_the_factorio_lab_origin() -> None:
    assert parse_options({"url": URL}).fetch_flow is False
    assert parse_options({"url": URL, "fetch_flow": True}).fetch_flow is True


@pytest.mark.parametrize("value", [1, "yes", None, []])
def test_fetch_flow_requires_a_boolean(value: JsonValue) -> None:
    with pytest.raises(InvalidOptions, match="'fetch_flow' must be a boolean"):
        parse_options({"url": URL, "fetch_flow": value})


def test_web_fetch_and_supplied_flow_are_mutually_exclusive() -> None:
    with pytest.raises(InvalidOptions, match="flow.*fetch_flow"):
        parse_options({"url": URL, "flow": "Recipes\n", "fetch_flow": True})


@pytest.mark.parametrize(
    "url",
    [
        "http://factoriolab.github.io/dsp/flow?o=x&v=11",
        "https://example.com/dsp/flow?o=x&v=11",
        "https://factoriolab.github.io:444/dsp/flow?o=x&v=11",
        "https://factoriolab.github.io/dsp/other?o=x&v=11",
        "https://factoriolab.github.io:bad/dsp/flow?o=x&v=11",
    ],
)
def test_web_fetch_rejects_navigation_outside_supported_pages(url: str) -> None:
    with pytest.raises(InvalidOptions, match="FactorioLab HTTPS"):
        parse_options({"url": url, "fetch_flow": True})
```

Use the module's existing `URL`, which is already an allowed FactorioLab URL.

- [ ] **Step 2: Run request tests and verify they fail for the missing option**

Run:

```bash
uv run pytest tests/web/test_options.py -q
```

Expected: FAIL because `Options` has no `fetch_flow`, non-booleans are accepted/ignored, and unsafe fetch URLs are not rejected.

- [ ] **Step 3: Add the web option and exact allowlist**

In `Options` add:

```python
fetch_flow: bool = False
```

In `parse_options`, validate the boolean and then enforce:

```python
fetch_flow = raw.get("fetch_flow", False)
if not isinstance(fetch_flow, bool):
    raise InvalidOptions("'fetch_flow' must be a boolean")
if fetch_flow and flow.strip():
    raise InvalidOptions("'flow' and 'fetch_flow' are mutually exclusive")
if fetch_flow:
    _validate_web_fetch_url(url.strip())
```

Implement the allowlist with `urllib.parse.urlsplit`:

```python
def _validate_web_fetch_url(url: str) -> None:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise InvalidOptions(
            "automatic flow fetch requires a FactorioLab HTTPS /dsp/list or /dsp/flow URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "factoriolab.github.io"
        or port not in (None, 443)
        or parsed.path not in ("/dsp/list", "/dsp/flow")
    ):
        raise InvalidOptions(
            "automatic flow fetch requires a FactorioLab HTTPS /dsp/list or /dsp/flow URL"
        )

Pass `fetch_flow=fetch_flow` into the constructed `Options`.

- [ ] **Step 4: Add a failing pipeline-plumbing test**

Extend the existing `tests/web/test_jobs.py` spy tests:

```python
def test_run_build_passes_fetch_flow_and_web_url_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def spy(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)
        raise ValueError("stop after observing options")

    monkeypatch.setattr(pipeline, "build", spy)
    with pytest.raises(ValueError, match="stop after observing"):
        run_build(Options(url=URL, fetch_flow=True), lambda _step: None)

    assert seen["fetch_flow"] is True
    validator = seen["fetch_url_validator"]
    assert callable(validator)
```

Run:

```bash
uv run pytest tests/web/test_jobs.py::test_run_build_passes_fetch_flow_and_web_url_validator -q
```

Expected: FAIL because `run_build` does not pass either keyword.

- [ ] **Step 5: Add capture-level final-location validation tests**

Define a tiny fake page matching `_AsyncPage` and test a helper before touching browser orchestration:

```python
class _LocationPage:
    def __init__(self, location: object) -> None:
        self.location = location

    async def evaluate(self, expression: str, **_kwargs: object) -> object:
        assert expression == "location.href"
        return self.location


def test_final_navigation_is_checked_before_page_probes() -> None:
    seen: list[str] = []

    def validate(url: str) -> None:
        seen.append(url)
        if url.startswith("http://127.0.0.1"):
            raise CaptureError("outside allowlist")

    with pytest.raises(CaptureError, match="outside allowlist"):
        asyncio.run(_validate_page_location(_LocationPage("http://127.0.0.1/private"), validate))
    assert seen == ["http://127.0.0.1/private"]
```

Also test a non-string `location.href` raises `CaptureError` rather than bypassing validation.

- [ ] **Step 6: Implement the validator through capture and pipeline**

In `capture.py`:

```python
type UrlValidator = Callable[[str], None]
_LOCATION_JS: Final = "location.href"

async def _validate_page_location(page: _AsyncPage, validator: UrlValidator) -> None:
    location = await page.evaluate(_LOCATION_JS, return_by_value=True)
    if not isinstance(location, str):
        raise CaptureError(f"browser returned invalid location.href: {location!r}")
    try:
        validator(location)
    except ValueError as exc:
        raise CaptureError(f"browser navigated outside the permitted flow page: {exc}") from exc

Add `url_validator` to `_capture` and `capture_flow_csv`. Call it once before browser launch, and call `_validate_page_location(page, url_validator)` immediately after `browser.get(url)` and before `_await_solve`.

Add `fetch_url_validator: UrlValidator | None = None` to `pipeline.build` and pass it to `capture_flow_csv` only on the `fetch_flow` branch.

In `run_build`, pass:

```python
fetch_flow=options.fetch_flow,
fetch_url_validator=_validate_web_fetch_url if options.fetch_flow else None,
```

Do not alter the CLI's existing `flow`-before-`fetch_flow` ordering.

- [ ] **Step 7: Run the focused Python contract tests**

Run:

```bash
uv run pytest tests/lab/test_capture.py tests/web/test_options.py tests/web/test_jobs.py tests/test_pipeline_cli_strategy.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit the safe server path**

```bash
git add src/flab2bp/lab/capture.py src/flab2bp/pipeline.py src/flab2bp/web/jobs.py tests/lab/test_capture.py tests/web/test_options.py tests/web/test_jobs.py tests/test_pipeline_cli_strategy.py
git commit -m "Expose safe server-side flow capture"
```

---

### Task 3: Add the Fetch-Flow Web Control

**Files:**
- Modify: `web/src/api/build.ts:119-150`
- Modify: `web/src/ui/BuildPanel.tsx:22-247`
- Modify: `web/src/ui/BuildReport.tsx:93-113`
- Modify: `web/src/ui/app.css:295-313`
- Test: `web/tests/api/build.test.ts`
- Test: `web/tests/ui/BuildPanel.test.tsx`

**Interfaces:**
- Consumes: Python request field `fetch_flow: bool` and existing `flow: string`.
- Produces: `BuildOptions.fetch_flow: boolean`, default false, and a checkbox labelled `Fetch FactorioLab flow automatically`.

- [ ] **Step 1: Add failing API-schema and UI-submission tests**

In `web/tests/api/build.test.ts`, extend the request assertion:

```ts
expect(body.fetch_flow).toBe(false);
```

In `BuildPanel.test.tsx` add:

```tsx
test('automatic flow fetch is off by default and is submitted when selected', async () => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  const fetchFlow = screen.getByRole('checkbox', {
    name: 'Fetch FactorioLab flow automatically',
  });
  expect(fetchFlow).not.toBeChecked();

  fireEvent.click(fetchFlow);
  build();
  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.fetch_flow).toBe(true);
});
```

- [ ] **Step 2: Add failing mutual-exclusion interaction tests**

```tsx
test('automatic fetch and supplied CSV cannot both be selected', () => {
  mount();
  const fetchFlow = screen.getByRole('checkbox', {
    name: 'Fetch FactorioLab flow automatically',
  });
  const text = screen.getByTestId('flow-text');
  const file = screen.getByTestId('flow-file');

  fireEvent.change(text, { target: { value: 'Recipes\nid,name\n' } });
  expect(fetchFlow).toBeDisabled();

  fireEvent.change(text, { target: { value: '' } });
  fireEvent.click(fetchFlow);
  expect(text).toBeDisabled();
  expect(file).toBeDisabled();
});
```

- [ ] **Step 3: Run frontend tests and verify the missing schema/control failures**

Run from `web/`:

```bash
bun run test -- tests/api/build.test.ts tests/ui/BuildPanel.test.tsx
```

Expected: FAIL because `fetch_flow` is absent and no checkbox exists.

- [ ] **Step 4: Implement the API field and defaults**

In `BuildOptions` add:

```ts
fetch_flow: z.boolean(),
```

In `DEFAULT_OPTIONS` add:

```ts
fetch_flow: false,
```

Keep the field adjacent to `flow` so the mutual-exclusion contract is visible.

- [ ] **Step 5: Implement the checkbox and disabled states**

Add a labelled checkbox in the flow row:

```tsx
<label className="checkbox">
  <input
    type="checkbox"
    checked={options.fetch_flow}
    disabled={Boolean(options.flow.trim()) || busy}
    onChange={(event) => set('fetch_flow', event.target.checked)}
  />
  Fetch FactorioLab flow automatically
</label>
```

Set `disabled={options.fetch_flow || busy}` on the textarea and file input. Keep current pasted text intact when a control is disabled; do not clear user data as a side effect.

Add note copy:

```tsx
<span className="note">
  Runs FactorioLab in a server-side browser and pins its solved recipe selection.
</span>
```

Add an explicit disabled state in `web/src/ui/app.css`:

```css
.build-panel .row.flow :disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
```

Update the unpinned `BuildReport` paragraph to offer automatic fetch or paste/upload and remove the statement that fetch is unavailable.

- [ ] **Step 6: Verify frontend tests, lint, and types**

Run from `web/`:

```bash
bun run test -- tests/api/build.test.ts tests/ui/BuildPanel.test.tsx
bun run lint
bun run typecheck
```

Expected: all PASS with no warnings.

- [ ] **Step 7: Commit the web control**

```bash
git add web/src/api/build.ts web/src/ui/BuildPanel.tsx web/src/ui/BuildReport.tsx web/src/ui/app.css web/tests/api/build.test.ts web/tests/ui/BuildPanel.test.tsx
git commit -m "Add automatic flow fetch control"
```

---

### Task 4: Update User Documentation and Verify the Actual Surfaces

**Files:**
- Modify: `README.md:95-110`
- Modify: `docs/WEB_UI.md:90-105`
- Modify: `docs/BACKLOG.md:960-975`
- Test: existing suites only

**Interfaces:**
- Consumes: completed CLI and web behavior from Tasks 1-3.
- Produces: accurate CLI/web documentation and behavioral evidence for the exact reported URL.

- [ ] **Step 1: Replace stale “not wired” documentation**

Document:

- `--fetch-flow` drives installed Chromium and defaults off;
- the web checkbox uses only the supported FactorioLab HTTPS pages;
- pasted flow and automatic fetch are mutually exclusive in web requests;
- capture failure refuses rather than deriving silently;
- nodriver is intentionally pinned pending a verified importable upgrade.

Mark the corresponding BACKLOG item resolved; do not leave both “not wired” and “wired” claims.

- [ ] **Step 2: Run the exact CLI capture smoke**

Use the exact URL from the issue:

```bash
uv run flab2bp 'https://factoriolab.github.io/dsp/list?z=eJxFxrEKgzAUBdC.yXCnxCpOb7mhuEkVW8hadSgqQqRil.ftYqn0TGcWBlysNbOwRZpZwB3..J8jsb8-kGTnSbjzzdHvX89eaGK.yQ0BHQa8wRK8g4NyBBf4Ar5SX5tpihKUetXKrOLcDk0nJEA_&v=11' --fetch-flow --fetch-timeout 90 --budget 0.5 -o /tmp/flab2bp-fetch-smoke.txt
```

Expected capture evidence: no nodriver `SyntaxError`; FactorioLab CSV capture completes and reaches flow provenance/layout. A later honest `NoValidLayout` is a separate solver result and must not be reported as a capture failure.

- [ ] **Step 3: Run the network-gated capture regression**

```bash
FLAB2BP_NETWORK_TESTS=1 uv run pytest tests/lab/test_capture.py::test_real_capture_round_trips_through_flow_solver -q
```

Use the actual test name present after Task 1; do not deselect provenance assertions. Expected: PASS.

- [ ] **Step 4: Browser-drive the actual web UI**

Start the managed dev surface with `bun run dev`, wait for ports 8000 and 3001, then use the browser tool against `http://127.0.0.1:3001`:

1. enter the exact URL;
2. verify the automatic-fetch checkbox is initially unchecked;
3. select it and verify paste/upload controls disable;
4. submit and observe queued/running/settled state;
5. verify an unsafe URL with automatic fetch receives the server's allowlist error;
6. toggle fetch off, paste CSV, and verify the checkbox disables.

A DOM-only test is not a substitute for this behavioral UI verification.

- [ ] **Step 5: Run complete flow-fetch verification**

```bash
uv run pytest tests/lab/test_capture.py tests/web/test_options.py tests/web/test_jobs.py tests/web/test_server.py tests/test_pipeline_cli_strategy.py -q
uv run ruff check src/flab2bp/lab/capture.py src/flab2bp/pipeline.py src/flab2bp/web/jobs.py tests/lab/test_capture.py tests/web/test_options.py tests/web/test_jobs.py
uv run mypy
cd web && bun run test -- tests/api/build.test.ts tests/ui/BuildPanel.test.tsx && bun run lint && bun run typecheck
```

Expected: all PASS; no schema, lint, type, or import warnings.

- [ ] **Step 6: Commit documentation and any verification-only corrections**

```bash
git add README.md docs/WEB_UI.md docs/BACKLOG.md
git commit -m "Document safe flow fetching"
```

Do not commit `/tmp` smoke outputs or browser profiles.
