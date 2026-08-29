"""Fetch a FactorioLab CSV export by driving a headless browser.

FactorioLab is a client-side Angular app: the URL carries the settings, the
solve runs *in the page* (GLPK compiled to WASM), and the CSV is produced by
``URL.createObjectURL`` on a Blob built in JavaScript.  There is no endpoint to
GET, so obtaining the player's own solved flow means running the page.

Why not Playwright
------------------

Playwright ships its own browser builds and none are available for this
platform (Fedora 44); ``playwright install chrome`` fails and the bundled
Chromium is not packaged for it.  ``nodriver`` drives a browser that is already
installed over the DevTools protocol, which is the part we actually need.

The waiting problem, which is the whole difficulty
--------------------------------------------------

The page is interactive long before it has an answer, so *time* is not a signal.
A ``sleep(n)`` here would be a flake generator in the worst possible place: it
would sometimes capture an empty or stale export, which parses perfectly and
produces a blueprint for the wrong flow.  That is the silent-wrong-answer class
this program exists to avoid, so every wait below is on a real condition with a
bounded timeout, and a timeout raises naming what it was waiting for.

The conditions, in order, and why each is genuinely downstream of the solve:

1. **DevTools answers** ``/json/version`` -- the browser is up and attachable.
2. **The CSV download button exists.**  This is the strong one.  In
   ``steps.html`` the button is inside ``@if (objectivesStore.steps().length)``,
   so Angular renders it only once the solver has produced steps.  Its presence
   *is* the statement that a solve finished; it cannot appear beforehand.
3. **The steps table has at least one row**, for the same reason from the other
   direction.
4. **The row count is unchanged across two consecutive polls.**  Belt and
   braces: ``steps()`` is a computed that flips atomically from empty to the
   full result rather than filling in, so this should never be the binding
   condition -- but if the app ever changes to stream rows, this is what stops
   us reading a half-built table instead of silently truncating a flow.
5. **A Blob was actually produced** by the click, and it is non-empty.

Capturing the bytes
-------------------

Rather than plumb CDP download behaviour and then poll a directory for a file
that may still be being written, this patches ``URL.createObjectURL`` to keep a
reference to the Blob and then reads it with ``Blob.text()``.  Those are the
exact bytes ``file-saver`` would have written -- the same Blob object -- with no
filesystem race to lose to.  If the app ever stops going through
``createObjectURL``, the reference stays null and this raises rather than
returning something plausible.

There is no fallback.  Every failure here raises :class:`CaptureError`, which is
a :class:`~flab2bp.lab.flow.FlowError`, so a capture that times out or comes
back empty refuses the build.  Quietly re-deriving the recipe selection because
the browser was slow would reintroduce the exact defect this feature removes.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Final, Protocol, TypedDict, TypeGuard, cast

from pydantic import TypeAdapter, ValidationError

from flab2bp.lab.flow import FlowError

__all__ = [
    "CaptureError",
    "SolveProbeState",
    "UrlValidator",
    "capture_flow_csv",
    "find_browser",
]
type UrlValidator = Callable[[str], None]


class CaptureError(FlowError):
    """The export could not be fetched.  Never falls back to deriving one."""


class SolveProbeState(TypedDict):
    """The complete JSON state returned by the in-page solve probe."""

    rows: int
    csv: bool


class _AsyncPage(Protocol):
    async def evaluate(
        self,
        expression: str,
        *,
        await_promise: bool = False,
        return_by_value: bool = False,
    ) -> object: ...


class _InterceptPage(_AsyncPage, Protocol):
    async def send(self, command: object) -> object: ...

    def add_handler(self, event_type: type[object], callback: object) -> None: ...


class _Request(Protocol):
    url: str


class _PausedRequest(Protocol):
    request_id: object
    request: _Request
    frame_id: object
    resource_type: object


class _Frame(Protocol):
    id_: object


class _FrameTree(Protocol):
    frame: _Frame


class _RequestStage(Protocol):
    REQUEST: object


class _ResourceType(Protocol):
    DOCUMENT: object


class _ErrorReason(Protocol):
    BLOCKED_BY_CLIENT: object


class _FetchDomain(Protocol):
    RequestPaused: type[object]
    RequestStage: _RequestStage

    def RequestPattern(self, *, resource_type: object, request_stage: object) -> object: ...

    def enable(self, *, patterns: list[object]) -> object: ...

    def continue_request(self, request_id: object) -> object: ...

    def fail_request(self, request_id: object, error_reason: object) -> object: ...


class _NetworkDomain(Protocol):
    ResourceType: _ResourceType
    ErrorReason: _ErrorReason


class _PageDomain(Protocol):
    def get_frame_tree(self) -> object: ...

    def navigate(self, url: str) -> object: ...


class _Cdp(Protocol):
    fetch: _FetchDomain
    network: _NetworkDomain
    page: _PageDomain


class _Browser(Protocol):
    async def get(self, url: str) -> _InterceptPage: ...

    def stop(self) -> None: ...


class _NoDriver(Protocol):
    cdp: _Cdp
    async def start(self, *, host: str, port: int) -> _Browser: ...


def _is_nodriver(module: object) -> TypeGuard[_NoDriver]:
    return callable(getattr(module, "start", None))



@dataclass(slots=True)
class _MainFrameRequestGuard:
    """Pause every main-frame document request until its URL is admitted."""

    page: _InterceptPage
    cdp: _Cdp
    validator: UrlValidator
    main_frame_id: object
    first_main_document_decided: asyncio.Event = field(default_factory=asyncio.Event)
    failure: CaptureError | None = None

    async def handle(self, raw_event: object) -> None:
        event = cast(_PausedRequest, raw_event)
        if (
            event.frame_id != self.main_frame_id
            or event.resource_type != self.cdp.network.ResourceType.DOCUMENT
        ):
            _ = await self.page.send(self.cdp.fetch.continue_request(event.request_id))
            return
        try:
            self.validator(event.request.url)
        except ValueError as exc:
            if self.failure is None:
                self.failure = CaptureError(
                    f"redirect target is not permitted: {event.request.url}: {exc}"
                )
            try:
                _ = await self.page.send(
                    self.cdp.fetch.fail_request(
                        event.request_id,
                        self.cdp.network.ErrorReason.BLOCKED_BY_CLIENT,
                    )
                )
            finally:
                self.first_main_document_decided.set()
            return
        try:
            _ = await self.page.send(self.cdp.fetch.continue_request(event.request_id))
        except Exception as exc:
            if self.failure is None:
                self.failure = CaptureError(
                    f"could not continue permitted navigation to {event.request.url}: {exc}"
                )
        finally:
            self.first_main_document_decided.set()

    def raise_if_failed(self) -> None:
        if self.failure is not None:
            raise self.failure


async def _navigate_with_request_guard(
    page: _InterceptPage,
    url: str,
    cdp: _Cdp,
    validator: UrlValidator,
    *,
    deadline_s: float = 30.0,
) -> _MainFrameRequestGuard:
    """Enable request-stage Fetch interception on ``about:blank``, then navigate."""

    frame_tree = cast(_FrameTree, await page.send(cdp.page.get_frame_tree()))
    guard = _MainFrameRequestGuard(page, cdp, validator, frame_tree.frame.id_)
    page.add_handler(cdp.fetch.RequestPaused, guard.handle)
    _ = await page.send(
        cdp.fetch.enable(
            patterns=[
                cdp.fetch.RequestPattern(
                    resource_type=cdp.network.ResourceType.DOCUMENT,
                    request_stage=cdp.fetch.RequestStage.REQUEST,
                )
            ]
        )
    )
    loop = asyncio.get_running_loop()
    end = loop.time() + deadline_s
    _ = await page.send(cdp.page.navigate(url))
    try:
        await asyncio.wait_for(
            guard.first_main_document_decided.wait(),
            timeout=max(0.0, end - loop.time()),
        )
    except TimeoutError as exc:
        raise CaptureError(
            "Chromium did not expose the first main-document request before "
            f"the {deadline_s:g}s capture navigation deadline"
        ) from exc
    guard.raise_if_failed()

    while loop.time() < end:
        location = await page.evaluate(_LOCATION_JS, return_by_value=True)
        guard.raise_if_failed()
        if location != "about:blank":
            return guard
        await asyncio.sleep(_POLL_S)
    raise CaptureError(
        "Chromium admitted the first main-document request but navigation "
        f"remained on about:blank for {deadline_s:g}s"
    )

_SOLVE_PROBE_STATE_ADAPTER = TypeAdapter(SolveProbeState)


def _parse_solve_probe(raw: object) -> SolveProbeState:
    if not isinstance(raw, str):
        raise CaptureError(f"invalid solve probe payload: expected JSON, got {raw!r}")
    try:
        return _SOLVE_PROBE_STATE_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        raise CaptureError(f"invalid solve probe payload: {raw!r}") from exc


def _solve_probe_values(raw: object) -> tuple[int, bool]:
    """Narrow the two poll fields without running schema validation in the loop."""
    if not isinstance(raw, str):
        raise CaptureError(f"invalid solve probe payload: expected JSON, got {raw!r}")
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CaptureError(f"invalid solve probe payload: {raw!r}") from exc
    if not isinstance(decoded, dict):
        raise CaptureError(f"invalid solve probe payload: {raw!r}")
    rows: object = decoded.get("rows")
    csv: object = decoded.get("csv")
    if isinstance(rows, bool) or not isinstance(rows, int) or not isinstance(csv, bool):
        raise CaptureError(f"invalid solve probe payload: {raw!r}")
    return rows, csv


#: Env var to point at a specific browser, for a machine where the search below
#: guesses wrong or where two builds are installed.
BROWSER_ENV: Final = "FLAB2BP_BROWSER"

#: Searched in order.  Chromium and Chrome only -- this speaks the DevTools
#: protocol, and Firefox's implementation of it does not cover what is used
#: here.  The bare ``chromium-browser`` path is Fedora's, whose ``/usr/bin``
#: entry is a shell wrapper; the real executable is preferred so the process we
#: terminate is the browser rather than its launcher.
BROWSER_CANDIDATES: Final = (
    "/usr/lib64/chromium-browser/chromium-browser",
    "/usr/lib/chromium-browser/chromium-browser",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "/opt/google/chrome/chrome",
)

_ARGS: Final = (
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--mute-audio",
    "--window-size=1280,1024",
)

#: How often to re-test a wait condition.  Small enough that a fast solve is not
#: made to wait, large enough that polling is not itself a load on the page.
_POLL_S: Final = 0.25
_LOCATION_JS: Final = "location.href"
_READY_STATE_JS: Final = "document.readyState"


#: Reads DOM state the solve is downstream of.  Returned as a JSON string
#: because nodriver hands back a CDP ``RemoteObject`` for anything structured,
#: and a string round-trips exactly.
_PROBE_JS: Final = """JSON.stringify({
    rows: document.querySelectorAll('table.table tbody tr').length,
    csv: !!Array.from(document.querySelectorAll('button')).find(
        b => ((b.getAttribute('aria-label') || '') + (b.textContent || ''))
            .toLowerCase().includes('csv')),
})"""

_PATCH_JS: Final = """
window.__flab2bp_blob = null;
if (!window.__flab2bp_patched) {
    window.__flab2bp_patched = true;
    const original = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (blob) => { window.__flab2bp_blob = blob; return original(blob); };
}
true"""

_CLICK_JS: Final = """(() => {
    const b = Array.from(document.querySelectorAll('button')).find(
        b => ((b.getAttribute('aria-label') || '') + (b.textContent || ''))
            .toLowerCase().includes('csv'));
    if (!b) return false;
    b.click();
    return true;
})()"""

_READ_JS: Final = "window.__flab2bp_blob ? window.__flab2bp_blob.text() : null"


def find_browser(explicit: str | None = None) -> str:
    """Locate a Chromium or Chrome executable, or say precisely what was tried."""
    for candidate in (explicit, os.environ.get(BROWSER_ENV)):
        if not candidate:
            continue
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
        raise CaptureError(
            f"browser {candidate!r} does not exist or is not executable "
            f"(from {'--browser' if candidate == explicit else BROWSER_ENV})"
        )
    for candidate in BROWSER_CANDIDATES:
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    raise CaptureError(
        "no Chromium or Chrome executable found. Fetching a flow export means "
        "running FactorioLab's page, because the solve happens in the browser. "
        f"Tried: {', '.join(BROWSER_CANDIDATES)}. Install one, or set "
        f"{BROWSER_ENV} to its path."
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


async def _await_devtools(port: int, process: subprocess.Popen[bytes], deadline_s: float) -> None:
    """Wait for the browser to answer, or say why it never did."""
    import httpx

    loop = asyncio.get_running_loop()
    end = loop.time() + deadline_s
    async with httpx.AsyncClient() as client:
        while loop.time() < end:
            if process.poll() is not None:
                raise CaptureError(
                    f"the browser exited with code {process.returncode} before its "
                    "DevTools port answered; it could not start on this machine"
                )
            try:
                response = await client.get(
                    f"http://127.0.0.1:{port}/json/version", timeout=1.0
                )
            except Exception:  # noqa: BLE001 - not up yet is the normal case here
                pass
            else:
                if response.status_code == 200:
                    return
            await asyncio.sleep(_POLL_S)
    raise CaptureError(
        f"the browser never answered on its DevTools port within {deadline_s:.0f}s"
    )


async def _validate_page_location(page: _AsyncPage, validator: UrlValidator) -> None:
    location = await page.evaluate(_LOCATION_JS, return_by_value=True)
    if not isinstance(location, str):
        raise CaptureError(f"browser returned invalid location.href: {location!r}")
    try:
        validator(location)
    except ValueError as exc:
        raise CaptureError(
            f"browser navigated outside the permitted flow page: {exc}"
        ) from exc


async def _await_navigation(
    page: _AsyncPage,
    validator: UrlValidator | None,
    deadline_s: float,
    request_guard: _MainFrameRequestGuard | None = None,
) -> None:
    """Wait for the main frame to finish loading, checking every observed URL."""
    loop = asyncio.get_running_loop()
    end = loop.time() + deadline_s
    last_ready: object = None
    while loop.time() < end:
        if request_guard is not None:
            request_guard.raise_if_failed()
        if validator is not None:
            await _validate_page_location(page, validator)
        last_ready = await page.evaluate(_READY_STATE_JS, return_by_value=True)
        if last_ready == "complete":
            if request_guard is not None:
                request_guard.raise_if_failed()
            return
        if last_ready not in ("loading", "interactive"):
            raise CaptureError(f"browser returned invalid document.readyState: {last_ready!r}")
        await asyncio.sleep(_POLL_S)
    raise CaptureError(
        "FactorioLab navigation did not settle before the capture deadline. "
        f"Last document.readyState: {last_ready!r}"
    )


async def _await_solve(
    page: _AsyncPage,
    url: str,
    deadline_s: float,
    url_validator: UrlValidator | None = None,
    request_guard: _MainFrameRequestGuard | None = None,
) -> None:
    """Wait until FactorioLab has actually finished solving.

    Never a sleep.  See the module docstring for why each condition is
    downstream of the solve; the failure message names the state we were still
    seeing so a timeout is diagnosable rather than just late.
    """
    loop = asyncio.get_running_loop()
    end = loop.time() + deadline_s
    settled: int | None = None
    last_rows = 0
    last_csv = False
    completed_raw: object | None = None
    while loop.time() < end:
        if request_guard is not None:
            request_guard.raise_if_failed()
        if url_validator is not None:
            await _validate_page_location(page, url_validator)
        raw = await page.evaluate(_PROBE_JS, return_by_value=True)
        rows, csv = _solve_probe_values(raw)
        last_rows, last_csv = rows, csv
        if csv and rows > 0 and settled == rows:
            completed_raw = raw
            break
        settled = rows if csv and rows > 0 else None
        await asyncio.sleep(_POLL_S)
    if completed_raw is not None:
        if request_guard is not None:
            request_guard.raise_if_failed()
        _ = _parse_solve_probe(completed_raw)
        return
    raise CaptureError(
        f"FactorioLab did not finish solving {url} within {deadline_s:.0f}s. "
        f"Last seen: {last_rows} step row(s), CSV button "
        f"{'present' if last_csv else 'absent'}. The download button is "
        "rendered only once the in-page solver has produced steps, so an absent "
        "button means the solve had not completed -- not that the page failed to "
        "load. Raise --fetch-timeout, or check the URL opens in a browser."
    )


async def _capture(
    url: str,
    executable: str,
    timeout_s: float,
    headless: bool,
    url_validator: UrlValidator | None,
) -> str:
    if url_validator is not None:
        try:
            url_validator(url)
        except ValueError as exc:
            raise CaptureError(f"requested flow URL is not permitted: {exc}") from exc
    nodriver: object = importlib.import_module("nodriver")
    if not _is_nodriver(nodriver):
        raise CaptureError("nodriver has no callable start()")

    port = _free_port()
    profile = tempfile.mkdtemp(prefix="flab2bp-browser-")
    args: Sequence[str] = (
        *(_ARGS if headless else _ARGS[1:]),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "about:blank",
    )
    process = subprocess.Popen(  # noqa: S603 - executable resolved by find_browser
        [executable, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    browser: _Browser | None = None
    request_guard: _MainFrameRequestGuard | None = None
    try:
        await _await_devtools(port, process, min(timeout_s, 30.0))
        browser = await nodriver.start(host="127.0.0.1", port=port)
        if url_validator is None:
            page = await browser.get(url)
        else:
            page = await browser.get("about:blank")
            cdp = nodriver.cdp
            request_guard = await _navigate_with_request_guard(
                page,
                url,
                cdp,
                url_validator,
                deadline_s=timeout_s,
            )
        await _await_navigation(page, url_validator, timeout_s, request_guard)
        await _await_solve(
            page,
            url,
            timeout_s,
            url_validator=url_validator,
            request_guard=request_guard,
        )

        await page.evaluate(_PATCH_JS, return_by_value=True)
        if request_guard is not None:
            request_guard.raise_if_failed()
        if url_validator is not None:
            await _validate_page_location(page, url_validator)
        clicked = await page.evaluate(_CLICK_JS, return_by_value=True)
        if not clicked:
            raise CaptureError(
                "the CSV download button vanished between being found and being "
                "clicked; the page changed underneath us"
            )
        text = await _await_blob(page, timeout_s=min(timeout_s, 30.0))
        if request_guard is not None:
            request_guard.raise_if_failed()
    finally:
        if browser is not None:
            browser.stop()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - kill is a backstop
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return text


async def _await_blob(page: _AsyncPage, timeout_s: float) -> str:
    """Read the Blob the click produced, refusing an empty or absent one."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout_s
    while loop.time() < end:
        text = await page.evaluate(_READ_JS, await_promise=True, return_by_value=True)
        if isinstance(text, str) and text.strip():
            return text
        await asyncio.sleep(_POLL_S)
    raise CaptureError(
        "clicking the CSV button produced no data. The export builds a Blob via "
        "URL.createObjectURL, which is what this captures; an empty result means "
        "either the export path changed or the page had nothing to export."
    )


def capture_flow_csv(
    url: str,
    *,
    timeout_s: float = 90.0,
    browser: str | None = None,
    headless: bool = True,
    url_validator: UrlValidator | None = None,
) -> str:
    """Drive a headless browser to ``url`` and return its CSV export.

    Raises :class:`CaptureError` on any failure -- a missing browser, a browser
    that will not start, a solve that does not finish, or an empty download.
    It never returns a partial or substituted result: the caller's alternative
    to a real export is refusing, not deriving one.
    """
    executable = find_browser(browser)
    if find_spec("nodriver") is None:  # pragma: no cover - declared dependency
        raise CaptureError(
            "nodriver is not installed, so a flow export cannot be fetched; "
            "pass --flow with a CSV downloaded from FactorioLab instead"
        )
    return asyncio.run(_capture(url, executable, timeout_s, headless, url_validator))
