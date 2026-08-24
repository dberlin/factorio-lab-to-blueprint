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
import json
import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from flab2bp.lab.flow import FlowError

__all__ = ["CaptureError", "capture_flow_csv", "find_browser"]


class CaptureError(FlowError):
    """The export could not be fetched.  Never falls back to deriving one."""


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


async def _await_solve(page: Any, url: str, deadline_s: float) -> None:
    """Wait until FactorioLab has actually finished solving.

    Never a sleep.  See the module docstring for why each condition is
    downstream of the solve; the failure message names the state we were still
    seeing so a timeout is diagnosable rather than just late.
    """
    loop = asyncio.get_running_loop()
    end = loop.time() + deadline_s
    settled: int | None = None
    state: dict[str, Any] = {}
    while loop.time() < end:
        raw = await page.evaluate(_PROBE_JS, return_by_value=True)
        state = json.loads(raw) if isinstance(raw, str) else {}
        rows = int(state.get("rows") or 0)
        if state.get("csv") and rows > 0 and settled == rows:
            return
        settled = rows if state.get("csv") and rows > 0 else None
        await asyncio.sleep(_POLL_S)
    raise CaptureError(
        f"FactorioLab did not finish solving {url} within {deadline_s:.0f}s. "
        f"Last seen: {state.get('rows', 0)} step row(s), CSV button "
        f"{'present' if state.get('csv') else 'absent'}. The download button is "
        "rendered only once the in-page solver has produced steps, so an absent "
        "button means the solve had not completed -- not that the page failed to "
        "load. Raise --fetch-timeout, or check the URL opens in a browser."
    )


async def _capture(url: str, executable: str, timeout_s: float, headless: bool) -> str:
    # nodriver ships no py.typed, and adding a mypy override to pyproject for
    # it would touch a file another agent is editing. Scoped here instead.
    import nodriver  # type: ignore[import-untyped]

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
    browser = None
    try:
        await _await_devtools(port, process, min(timeout_s, 30.0))
        browser = await nodriver.start(host="127.0.0.1", port=port)
        page = await browser.get(url)
        await _await_solve(page, url, timeout_s)

        await page.evaluate(_PATCH_JS, return_by_value=True)
        clicked = await page.evaluate(_CLICK_JS, return_by_value=True)
        if not clicked:
            raise CaptureError(
                "the CSV download button vanished between being found and being "
                "clicked; the page changed underneath us"
            )
        text = await _await_blob(page, timeout_s=min(timeout_s, 30.0))
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


async def _await_blob(page: Any, timeout_s: float) -> str:
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
) -> str:
    """Drive a headless browser to ``url`` and return its CSV export.

    Raises :class:`CaptureError` on any failure -- a missing browser, a browser
    that will not start, a solve that does not finish, or an empty download.
    It never returns a partial or substituted result: the caller's alternative
    to a real export is refusing, not deriving one.
    """
    executable = find_browser(browser)
    try:
        import nodriver  # noqa: F401
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise CaptureError(
            "nodriver is not installed, so a flow export cannot be fetched; "
            "pass --flow with a CSV downloaded from FactorioLab instead"
        ) from exc
    return asyncio.run(_capture(url, executable, timeout_s, headless))
