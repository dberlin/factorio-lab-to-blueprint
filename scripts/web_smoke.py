#!/usr/bin/env python
"""Drive the web UI in a real browser and prove the string it hands out decodes.

Run it::

    uv run scripts/web_smoke.py --out /tmp/flab2bp-smoke

It starts ``flab2bp-web`` on a free port (unless ``--server`` names one already
running), opens a real Chromium over the DevTools protocol, types the URL,
picks the options, clicks Build, waits, clicks **Copy blueprint string**, reads
the clipboard back, and then decodes THAT STRING with
:func:`flab2bp.dsp.codec.decode`.  Then it does the unhappy path: a spec the
layout model refuses, checked for the reason text on the page.

Why every step is what it is
----------------------------

* **The clipboard, not the DOM.**  Reading the value out of the input would
  prove the input has a value.  The button is what a player uses, so what the
  button put on the clipboard is what has to decode.  Chromium will not hand a
  page the clipboard without permission, so this grants it over CDP -- and if
  the grant fails it says so and fails, rather than quietly reading the DOM
  instead.
* **Decode, do not eyeball.**  A 10kB base64 string that is subtly wrong looks
  exactly like one that is right.  ``encode(decode(x)) == x``, byte for byte,
  is the only check that could have come back false.
* **nodriver, not Playwright.**  Same reason ``flab2bp.lab.capture`` uses it:
  Playwright ships its own browser builds and none are available for Fedora, so
  a proof driven through Playwright is a proof nobody on this machine can
  re-run.  The browser search here is ``capture.find_browser``, unchanged.

It exits non-zero on the first thing that does not hold, and prints what it
checked either way.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zlib
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NotRequired, Protocol, TypedDict, runtime_checkable

from pydantic import TypeAdapter, ValidationError

from flab2bp.dsp.codec import decode, encode_blueprint
from flab2bp.lab.capture import _ARGS, _await_devtools, _free_port, find_browser

#: The user's own URL.  Freeform, max-proliferation, and it builds.
BUILD_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFyr0KwkAQReG3meJWO8GQapq7GDtJBMVt1UUkLoGAEpt5"
    "dhH.uo.DGY1naJDReMSiDoC-.Pi7QRU-3KH6HQn6zSTqt7OhlWJEkGIJQS6HbJQpz9Yh4YQBN3ANbsE9ODiviK3H"
    "FWLvcSOlTJacvvRe7qb6BOgIKRo_&v=11"
)

#: The corpus's ``universe-matrix``: deepest real chain in the set, and freeform
#: refuses every candidate of it.  A refusal is a RESULT here, and the reason
#: text is the product -- this checks it reaches the page verbatim.
REFUSE_URL = (
    "https://factoriolab.github.io/dsp/list?o=universe-matrix*60&ibe=conveyor-belt-3"
    "&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11"
)

#: The graphene spec and the FactorioLab export captured from it, used to
#: drive the ``--flow`` path through the page.  Paired: ``flow_from_text``
#: verifies the export was generated from this URL and refuses otherwise, so a
#: fixture is only usable with its own URL.  Small, and it lays out in seconds.
FLOW_URL = (
    "https://factoriolab.github.io/dsp/list?o=graphene*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)
FLOW_CSV = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "flow_graphene_real_capture.csv"
)

#: How long to wait for a build to settle in the page.  Both cases below stay
#: well inside it; nothing in this repo may run with a timeout over 300s.
SETTLE_TIMEOUT_S = 240.0

_POLL_S = 0.5


class SmokeFailure(AssertionError):
    """Something the page promised did not hold."""



type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type CdpPayload = dict[str, JsonValue]
type CdpCommand = Generator[CdpPayload, CdpPayload, object]
type Strategy = Literal["freeform", "sequence-pair"]


class CanvasSize(TypedDict):
    w: int
    h: int


class CanvasBox(TypedDict):
    x: int
    y: int
    width: int
    height: int


class ConsoleMessage(TypedDict):
    level: str
    text: str


class PageState(TypedDict):
    progress: str | None
    title: str | None
    report: str | None
    refusal: str | None
    errors: str | None
    warnings: str | None
    alert: list[str]
    hasString: bool
    flowText: str | None
    canvasEmpty: bool
    canvas: CanvasSize | None
    saw_progress: NotRequired[bool]


class SuccessResult(TypedDict):
    screenshot: str
    clipboard_chars: int
    buildings: int
    round_trips: bool
    canvas: CanvasBox
    canvas_distinct_colours: int
    title: str
    report: str
    warnings: str
    console: list[ConsoleMessage]


class RefusalResult(TypedDict):
    screenshot: str
    refusal: str
    console: list[ConsoleMessage]


class FlowResult(TypedDict):
    report: str
    flow_chars: int


class SmokeReport(TypedDict):
    success: SuccessResult
    flow: FlowResult
    refusal: RefusalResult


class _Page(Protocol):
    async def evaluate(
        self,
        expression: str,
        *,
        await_promise: bool = False,
        return_by_value: bool = False,
    ) -> object: ...

    async def send(
        self, cdp_obj: CdpCommand, _attach: bool = False, **kwargs: object
    ) -> object: ...


class _Browser(Protocol):
    async def get(
        self, url: str = "chrome://welcome", new_tab: bool = False, new_window: bool = False
    ) -> _Page: ...

    async def send(
        self, cdp_obj: CdpCommand, _attach: bool = False, **kwargs: object
    ) -> object: ...

    def stop(self) -> None: ...


class _PermissionType(Protocol):
    CLIPBOARD_READ_WRITE: object
    CLIPBOARD_SANITIZED_WRITE: object


@runtime_checkable
class _BrowserDomain(Protocol):
    PermissionType: _PermissionType

    def grant_permissions(
        self, *, permissions: list[object], origin: str
    ) -> CdpCommand: ...


@runtime_checkable
class _EmulationDomain(Protocol):
    def set_device_metrics_override(
        self, width: int, height: int, device_scale_factor: float, mobile: bool
    ) -> CdpCommand: ...

    def set_focus_emulation_enabled(self, *, enabled: bool) -> CdpCommand: ...


@runtime_checkable
class _PageDomain(Protocol):
    def capture_screenshot(
        self,
        *,
        format_: str,
        clip: object | None,
        capture_beyond_viewport: bool,
    ) -> CdpCommand: ...

    def Viewport(
        self, *, x: int, y: int, width: int, height: int, scale: float
    ) -> object: ...

    def enable(self) -> CdpCommand: ...

    def add_script_to_evaluate_on_new_document(self, *, source: str) -> CdpCommand: ...


class _Cdp(Protocol):
    @property
    def browser(self) -> _BrowserDomain: ...

    @property
    def emulation(self) -> _EmulationDomain: ...

    @property
    def page(self) -> _PageDomain: ...


class _CdpFacade:
    """Runtime-narrow nodriver's untyped CDP module once at browser ingress."""

    browser: _BrowserDomain
    emulation: _EmulationDomain
    page: _PageDomain

    def __init__(self, module: object) -> None:
        browser: object = getattr(module, "browser", None)
        emulation: object = getattr(module, "emulation", None)
        page: object = getattr(module, "page", None)
        if not isinstance(browser, _BrowserDomain):
            raise SmokeFailure("nodriver's CDP module has no compatible browser domain")
        if not isinstance(emulation, _EmulationDomain):
            raise SmokeFailure("nodriver's CDP module has no compatible emulation domain")
        if not isinstance(page, _PageDomain):
            raise SmokeFailure("nodriver's CDP module has no compatible page domain")
        self.browser = browser
        self.emulation = emulation
        self.page = page


_PAGE_STATE_ADAPTER = TypeAdapter(PageState)
_CANVAS_BOX_ADAPTER = TypeAdapter(CanvasBox)
_CONSOLE_ADAPTER = TypeAdapter(list[ConsoleMessage])


class _Args(argparse.Namespace):
    out: Path = Path("out/web-smoke")
    port: int | None = None
    server: str | None = None
    browser: str | None = None
    headed: bool = False

# ---- what runs in the page -------------------------------------------------

#: Every console message and page error, kept from the first script this page
#: runs.  Installed via ``Page.addScriptToEvaluateOnNewDocument`` so it is in
#: place before the bundle loads -- a handler attached after navigation would
#: miss exactly the errors that matter most.
_CONSOLE_HOOK = """
(() => {
  if (window.__smoke) return;
  window.__smoke = [];
  for (const level of ['error', 'warn']) {
    const original = console[level].bind(console);
    console[level] = (...args) => {
      try { window.__smoke.push({level, text: args.map(String).join(' ')}); } catch {}
      original(...args);
    };
  }
  window.addEventListener('error', (e) =>
    window.__smoke.push({level: 'uncaught', text: String(e.message)}));
  window.addEventListener('unhandledrejection', (e) =>
    window.__smoke.push({level: 'unhandledrejection', text: String(e.reason)}));
})();
"""

#: The state a poll needs, as one JSON string.  nodriver hands back a CDP
#: RemoteObject for anything structured; a string round-trips exactly.
_STATE_JS = """JSON.stringify({
  progress: (document.querySelector('[data-testid="progress"]')||{}).textContent || null,
  title: (document.querySelector('[data-testid="blueprint-title"]')||{}).textContent || null,
  report: (document.querySelector('[data-testid="build-report"]')||{}).textContent || null,
  refusal: (document.querySelector('[data-testid="refusal"]')||{}).textContent || null,
  errors: (document.querySelector('[data-testid="validation-errors"]')||{}).textContent || null,
  warnings: (document.querySelector('[data-testid="validation-warnings"]')||{}).textContent || null,
  alert: Array.from(document.querySelectorAll('[role="alert"]')).map(n => n.textContent),
  hasString: !!document.querySelector('[data-testid="blueprint-string"]'),
  flowText: (document.querySelector('[data-testid="flow-text"]')||{}).value || null,
  canvasEmpty: !!document.querySelector('.canvas-empty'),
  canvas: (() => {
    const c = document.querySelector('canvas');
    return c ? {w: c.width, h: c.height} : null;
  })(),
})"""

_FILL_JS = """((url) => {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  const input = document.querySelector('.build-panel input');
  if (!input) return 'no url input';
  // React owns this input's value; assigning to `.value` directly updates the
  // DOM node and leaves React's state holding the old one, so the submit would
  // send an empty URL. The native setter plus a bubbled `input` event is what
  // React's onChange actually listens for.
  setter.call(input, url);
  input.dispatchEvent(new Event('input', {bubbles: true}));
  return 'ok';
})(%s)"""

_SET_FLOW_JS = """((csv) => {
  const area = document.querySelector('[data-testid="flow-text"]');
  if (!area) return 'no flow textarea';
  // Same reason as _FILL_JS: React owns the value, and a direct assignment
  // updates the DOM node while React keeps the old state -- so the submit
  // would carry no flow and the report would say "derived" while the page
  // showed a pasted export. The native setter plus a bubbled input event is
  // what onChange listens for.
  Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set.call(area, csv);
  area.dispatchEvent(new Event('input', {bubbles: true}));
  return 'ok';
})(%s)"""

_SET_OPTION_JS = """((label, value) => {
  const labels = Array.from(document.querySelectorAll('.build-panel .options label'));
  const found = labels.find(l => l.textContent.trim().startsWith(label));
  if (!found) return 'no label ' + label;
  const control = document.getElementById(found.htmlFor);
  if (!control) return 'no control for ' + label;
  const proto = control.tagName === 'SELECT'
    ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(control, String(value));
  control.dispatchEvent(new Event(control.tagName === 'SELECT' ? 'change' : 'input',
                                  {bubbles: true}));
  return 'ok';
})(%s, %s)"""

_CLICK_JS = """((text) => {
  const button = Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.trim() === text);
  if (!button) return 'no button ' + JSON.stringify(text);
  if (button.disabled) return 'button disabled: ' + text;
  button.click();
  return 'ok';
})(%s)"""

_CLIPBOARD_JS = "navigator.clipboard.readText()"

#: The button relabels itself only when ``writeText`` RESOLVES, so this is the
#: page's own statement that the write happened.
_COPIED_JS = """!!Array.from(document.querySelectorAll('button'))
  .find(b => b.textContent.trim() === 'Copied')"""

#: What the DOM says the button copies.  Read only to CROSS-CHECK the
#: clipboard, never as a substitute for it.
_DOM_STRING_JS = (
    """(document.querySelector('[data-testid="blueprint-string"]')||{}).value || null"""
)


# ---- the server ------------------------------------------------------------


@dataclass
class Server:
    process: subprocess.Popen[bytes] | None
    base: str


def start_server(port: int | None) -> Server:
    """``flab2bp-web`` on a free port, waited for rather than slept on."""
    chosen = port or _free_port()
    root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "flab2bp.web", "--port", str(chosen), "--no-build"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{chosen}"
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure(f"flab2bp-web exited with {process.returncode} before serving")
        try:
            with socket.create_connection(("127.0.0.1", chosen), timeout=1.0):
                return Server(process, base)
        except OSError:
            time.sleep(_POLL_S)
    process.terminate()
    raise SmokeFailure(f"flab2bp-web never answered on {base}")


# ---- the browser -----------------------------------------------------------


async def _js(page: _Page, script: str) -> object:
    return await page.evaluate(script, return_by_value=True, await_promise=False)


def _validated_json[PayloadT](
    adapter: TypeAdapter[PayloadT], raw: object, what: str
) -> PayloadT:
    if not isinstance(raw, str):
        raise SmokeFailure(f"{what} returned {raw!r}, not JSON")
    try:
        return adapter.validate_json(raw)
    except ValidationError as exc:
        raise SmokeFailure(f"{what} returned invalid JSON: {raw!r}") from exc


def _json_object(raw: str, what: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{what} returned malformed JSON: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise SmokeFailure(f"{what} returned a JSON {type(parsed).__name__}, not an object")
    result: dict[str, object] = {}
    for raw_key, raw_value in parsed.items():
        if not isinstance(raw_key, str):
            raise SmokeFailure(f"{what} returned a JSON object with a non-text key")
        value: object = raw_value
        result[raw_key] = value
    return result

async def _state_json(page: _Page) -> str:
    raw = await _js(page, _STATE_JS)
    if not isinstance(raw, str):
        raise SmokeFailure(f"the page's state probe returned {raw!r}, not JSON")
    return raw


async def _state(page: _Page) -> PageState:
    return _validated_json(
        _PAGE_STATE_ADAPTER, await _state_json(page), "the page's state probe"
    )


async def _settle(page: _Page, out: Path, tag: str) -> PageState:
    """Poll until the panel shows a result, a refusal or an error.

    Never a fixed sleep: a build is seconds to minutes and the whole point of
    the submit-and-poll design is that nobody knows which. Polls use the JSON
    decoder's native value types; the cached schema adapter validates exactly
    once, when a terminal state crosses into the result.
    """
    deadline = time.monotonic() + SETTLE_TIMEOUT_S
    last_raw = "{}"
    last: dict[str, object] = {}
    seen_progress = False
    settled_raw: str | None = None
    while time.monotonic() < deadline:
        last_raw = await _state_json(page)
        last = _json_object(last_raw, "the page's state probe")
        if last.get("progress"):
            seen_progress = True
        if last.get("report") or last.get("refusal") or last.get("alert"):
            settled_raw = last_raw
            break
        await asyncio.sleep(_POLL_S)
    if settled_raw is not None:
        settled = _validated_json(
            _PAGE_STATE_ADAPTER, settled_raw, "the page's settled state"
        )
        settled["saw_progress"] = seen_progress
        return settled
    (out / f"{tag}-timeout-state.json").write_text(json.dumps(last, indent=2))
    raise SmokeFailure(f"[{tag}] nothing settled within {SETTLE_TIMEOUT_S:.0f}s; last: {last}")


async def _capture(
    page: _Page, cdp: _Cdp, clip: object | None = None, *, beyond: bool = False
) -> bytes:
    """A PNG of the page, or of one box on it, from the compositor.

    ``beyond`` is ``Page.captureScreenshot``'s ``captureBeyondViewport``. A
    clip below the fold needs it: without it the compositor answers with a
    blank box rather than an error.
    """
    shot = await page.send(
        cdp.page.capture_screenshot(format_="png", clip=clip, capture_beyond_viewport=beyond)
    )
    if not isinstance(shot, str):
        raise SmokeFailure(f"CDP returned a non-text screenshot payload: {shot!r}")
    return base64.b64decode(shot)


async def _shot(page: _Page, cdp: _Cdp, path: Path) -> None:
    path.write_bytes(await _capture(page, cdp))
    if not path.is_file() or path.stat().st_size == 0:
        raise SmokeFailure(f"no screenshot was written to {path}")


def _png_variety(png: bytes) -> int:
    """Distinct RGB colours in a PNG, decoded without an image library.

    Only truecolour, 8-bit, non-interlaced PNGs -- which is what CDP's
    ``Page.captureScreenshot`` produces.  This exists so "the canvas rendered
    something" is a measurement rather than a glance at a screenshot: a WebGL
    surface that never drew is one flat colour, and one flat colour is 1.
    """
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise SmokeFailure("screenshot is not a PNG")
    pos, idat, width, height, colour_type, depth = 8, bytearray(), 0, 0, -1, -1
    while pos < len(png):
        length = int.from_bytes(png[pos : pos + 4], "big")
        kind = png[pos + 4 : pos + 8]
        body = png[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width = int.from_bytes(body[0:4], "big")
            height = int.from_bytes(body[4:8], "big")
            depth, colour_type = body[8], body[9]
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    if (depth, colour_type) not in ((8, 2), (8, 6)):
        raise SmokeFailure(f"unsupported PNG: depth {depth}, colour type {colour_type}")

    import numpy as np

    channels = 3 if colour_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(height, stride + 1)
    filters, data = rows[:, 0], rows[:, 1:].astype(np.int32).copy()
    # Undo the per-scanline filters. Row-by-row because Paint/Up/Average/Paeth
    # each depend on the reconstructed row above (and, within a row, on the
    # pixel to the left -- hence the inner loop for those two).
    for y in range(height):
        f = filters[y]
        up = data[y - 1] if y > 0 else np.zeros(stride, dtype=np.int32)
        if f == 0:
            continue
        if f == 2:
            data[y] = (data[y] + up) & 0xFF
            continue
        row, left = data[y], np.zeros(stride, dtype=np.int32)
        for x in range(stride):
            a = row[x - channels] if x >= channels else 0
            b = up[x]
            c = up[x - channels] if x >= channels else 0
            if f == 1:
                row[x] = (row[x] + a) & 0xFF
            elif f == 3:
                row[x] = (row[x] + ((a + b) >> 1)) & 0xFF
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[x] = (row[x] + pred) & 0xFF
            else:
                raise SmokeFailure(f"unknown PNG filter {f}")
        del left
    pixels = data.reshape(height, width, channels)[:, :, :3].reshape(-1, 3)
    return int(np.unique(pixels, axis=0).shape[0])


async def _canvas_variety(page: _Page, cdp: _Cdp) -> tuple[int, CanvasBox]:
    """How many distinct colours the 3D canvas is actually showing.

    Screenshotted through CDP rather than read with ``toDataURL``: the viewer's
    WebGL context is created without ``preserveDrawingBuffer``, so a readback
    from JavaScript is entitled to come back blank whatever is on screen.  The
    compositor's own capture is not.
    """
    # PAGE coordinates, not viewport coordinates: `captureBeyondViewport`
    # measures from the document origin. Using viewport coordinates can capture
    # a blank box and falsely report that a viewer which drew correctly failed.
    box_raw = await _js(
        page,
        """(() => {
          const c = document.querySelector('canvas');
          if (!c) return 'null';
          const r = c.getBoundingClientRect();
          return JSON.stringify({x: Math.round(r.x + window.scrollX),
                                 y: Math.round(r.y + window.scrollY),
                                 width: Math.round(r.width), height: Math.round(r.height)});
        })()""",
    )
    if box_raw == "null":
        raise SmokeFailure("there is no <canvas> on the page at all")
    box = _validated_json(_CANVAS_BOX_ADAPTER, box_raw, "the canvas bounds probe")
    if box["width"] <= 0 or box["height"] <= 0:
        raise SmokeFailure(f"the canvas has no size: {box}")
    clip = cdp.page.Viewport(
        x=box["x"], y=box["y"], width=box["width"], height=box["height"], scale=1
    )
    return _png_variety(await _capture(page, cdp, clip, beyond=True)), box


async def _console(page: _Page) -> list[ConsoleMessage]:
    raw = await _js(page, "JSON.stringify(window.__smoke || [])")
    return _validated_json(_CONSOLE_ADAPTER, raw, "the console probe")


async def _expect_ok(page: _Page, script: str, what: str) -> None:
    answer = await _js(page, script)
    if answer != "ok":
        raise SmokeFailure(f"{what}: {answer!r}\n--- the script was ---\n{script}")


async def _drive(
    page: _Page,
    *,
    url: str,
    strategy: Strategy,
    candidates: int,
    budget_s: float,
    out: Path,
    tag: str,
    flow: str | None = None,
) -> PageState:
    await _expect_ok(page, _FILL_JS % json.dumps(url), "filling the URL")
    # Always set it, including to empty. The three cases share one page, and a
    # flow left in the box by the previous case is submitted with the next
    # one's URL -- where `flow_from_text` rightly refuses it as an export for a
    # different URL, and the case that meant to test something else fails on
    # that instead. (Found exactly that way; the page's message was correct and
    # this harness was not.)
    await _expect_ok(page, _SET_FLOW_JS % json.dumps(flow or ""), "setting the flow export")
    await _expect_ok(
        page, _SET_OPTION_JS % (json.dumps("Strategy"), json.dumps(strategy)), "setting strategy"
    )
    await _expect_ok(
        page,
        _SET_OPTION_JS % (json.dumps("Candidates"), json.dumps(str(candidates))),
        "setting candidates",
    )
    await _expect_ok(
        page, _SET_OPTION_JS % (json.dumps("Budget"), json.dumps(str(budget_s))), "setting budget"
    )
    await _expect_ok(page, _CLICK_JS % json.dumps("Build"), "clicking Build")
    settled = await _settle(page, out, tag)
    return settled


# ---- the two cases ---------------------------------------------------------


async def _case_success(page: _Page, cdp: _Cdp, out: Path) -> SuccessResult:
    settled = await _drive(
        page,
        url=BUILD_URL,
        strategy="freeform",
        candidates=3,
        budget_s=10,
        out=out,
        tag="success",
    )
    if settled.get("refusal"):
        raise SmokeFailure(f"the build URL refused, which it is not supposed to: {settled}")
    if not settled.get("hasString"):
        raise SmokeFailure(f"a finished build produced no blueprint string: {settled}")
    if not settled.get("saw_progress"):
        raise SmokeFailure("the build never showed any progress while it ran")

    await _expect_ok(page, _CLICK_JS % json.dumps("Copy blueprint string"), "clicking Copy")
    # The button relabels itself only when `writeText` RESOLVES, so this is the
    # page's own statement that the write happened -- checked before the read,
    # because a read that works over a write that did not would be a lie.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if await _js(page, _COPIED_JS):
            break
        await asyncio.sleep(_POLL_S)
    else:
        state = await _state(page)
        raise SmokeFailure(f"the Copy button never confirmed the write. Alerts: {state['alert']}")

    clipboard = await page.evaluate(_CLIPBOARD_JS, return_by_value=True, await_promise=True)
    if not isinstance(clipboard, str) or not clipboard.strip():
        raise SmokeFailure(f"the clipboard came back {clipboard!r} after clicking Copy")

    in_dom = await _js(page, _DOM_STRING_JS)
    if in_dom != clipboard:
        raise SmokeFailure("the button copied something other than the string on the page")

    blueprint = decode(clipboard)
    buildings = len(blueprint.buildings)
    if buildings <= 0:
        raise SmokeFailure("the copied string decoded to a blueprint with no buildings")
    # Byte for byte, not merely structurally. `decode(encode(decode(x))) ==
    # decode(x)` passes for an encoder that drops a field both times; only
    # `encode(decode(x)) == x` proves the string handed to the user is exactly
    # what this codec would produce.
    if encode_blueprint(blueprint) != clipboard:
        raise SmokeFailure("the copied string does not re-encode to itself, byte for byte")

    if settled.get("canvasEmpty"):
        raise SmokeFailure("the viewer is still showing 'Load a blueprint to see it.'")
    colours, box = await _canvas_variety(page, cdp)
    if colours < 2:
        raise SmokeFailure(f"the canvas is one flat colour ({colours}); nothing rendered")

    shot = out / "success.png"
    await _shot(page, cdp, shot)
    return {
        "screenshot": str(shot),
        "clipboard_chars": len(clipboard),
        "buildings": buildings,
        "round_trips": True,
        "canvas": box,
        "canvas_distinct_colours": colours,
        "title": (settled.get("title") or "").strip(),
        "report": " ".join((settled.get("report") or "").split())[:400],
        "warnings": " ".join((settled.get("warnings") or "").split())[:400],
        "console": await _console(page),
    }


async def _case_refusal(page: _Page, cdp: _Cdp, out: Path) -> RefusalResult:
    settled = await _drive(
        page,
        url=REFUSE_URL,
        strategy="freeform",
        candidates=1,
        budget_s=4,
        out=out,
        tag="refusal",
    )
    refusal = settled["refusal"]
    if not refusal:
        raise SmokeFailure(
            "the refusal URL did not refuse. That is not necessarily a bug in the "
            f"page -- the layout model may have improved -- but this case then "
            f"proves nothing and needs a new URL. Got: {settled}"
        )
    if settled.get("hasString"):
        raise SmokeFailure("a refusal handed out a blueprint string")
    shot = out / "refusal.png"
    await _shot(page, cdp, shot)
    return {
        "screenshot": str(shot),
        "refusal": " ".join(refusal.split())[:600],
        "console": await _console(page),
    }


async def _run(base: str, out: Path, browser_path: str, headless: bool) -> SmokeReport:
    import nodriver
    from nodriver import cdp

    cdp_api: _Cdp = _CdpFacade(cdp)

    port = _free_port()
    profile = tempfile.mkdtemp(prefix="flab2bp-smoke-")
    process = subprocess.Popen(  # noqa: S603 - executable resolved by find_browser
        [
            browser_path,
            *(_ARGS if headless else _ARGS[1:]),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    browser: _Browser | None = None
    try:
        await _await_devtools(port, process, 30.0)
        browser = await nodriver.start(host="127.0.0.1", port=port)

        # Everything below is set up on `about:blank` and the app is then loaded
        # ONCE. Loading it and reloading it to get the console hook in first
        # looks equivalent and is not: the poll for the build panel would see
        # the first load's DOM, break, and then have the second navigation wipe
        # it out from under the very next call. That is exactly what happened.
        page = await browser.get("about:blank")

        # Without this the Copy button's `writeText` rejects and the page says
        # so -- which is correct behaviour, and useless as a proof.  Sent on the
        # browser connection, which nodriver only opens once a tab exists.
        await browser.send(
            cdp_api.browser.grant_permissions(
                permissions=[
                    cdp_api.browser.PermissionType.CLIPBOARD_READ_WRITE,
                    cdp_api.browser.PermissionType.CLIPBOARD_SANITIZED_WRITE,
                ],
                origin=base,
            )
        )
        await page.send(
            cdp_api.emulation.set_device_metrics_override(1600, 1000, 1.0, False)
        )
        # A headless page is never focused, and `navigator.clipboard.readText`
        # refuses on an unfocused document ("Document is not focused").  The
        # WRITE the button does is unaffected; this is only so the proof can
        # read back what the button wrote.
        await page.send(cdp_api.emulation.set_focus_emulation_enabled(enabled=True))
        # Before the bundle, so an error thrown while it loads is still caught.
        # `Page.enable` first: without the domain enabled the script is accepted
        # and then never runs, which reads as a page that threw nothing.
        await page.send(cdp_api.page.enable())
        await page.send(
            cdp_api.page.add_script_to_evaluate_on_new_document(source=_CONSOLE_HOOK)
        )

        page = await browser.get(base)

        # The catalog fetch gates the whole app; until it lands there is no
        # build panel to type into.  `readyState` is checked alongside it so a
        # panel seen mid-navigation cannot be the one that breaks this loop.
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            ready = await _js(
                page,
                "document.readyState === 'complete'"
                " && !!document.querySelector('.build-panel input')"
                " && !!window.__smoke",
            )
            if ready is True:
                break
            await asyncio.sleep(_POLL_S)
        else:
            body = await _js(page, "document.body.innerText.slice(0, 400)")
            raise SmokeFailure(f"the page never rendered a build panel. Body was: {body!r}")

        success = await _case_success(page, cdp_api, out)
        flow = await _case_flow_pin(page, out)
        refusal = await _case_refusal(page, cdp_api, out)
        return {"success": success, "flow": flow, "refusal": refusal}
    finally:
        if browser is not None:
            browser.stop()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - kill is a backstop
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)


async def _case_flow_pin(page: _Page, out: Path) -> FlowResult:
    """``--flow``, pasted into the page.

    The point of a pin is that WHICH recipe makes what is FactorioLab's own
    decision rather than one re-derived here, and the difference is invisible
    in the blueprint: both builds emit a string, and only the report says which
    guarantee it carries.  So the check is the report, and it is falsifiable --
    a page that dropped the paste would say "derived, not pinned" here.
    """
    settled = await _drive(
        page,
        url=FLOW_URL,
        strategy="freeform",
        candidates=1,
        budget_s=4,
        out=out,
        tag="flow",
        flow=FLOW_CSV.read_text(encoding="utf-8-sig"),
    )
    if settled.get("refusal"):
        raise SmokeFailure(f"the flow-pinned build refused: {settled}")
    report = settled.get("report") or ""
    if "derived, not pinned" in report:
        raise SmokeFailure(
            "the pasted flow never reached the solver: the report says the "
            f"selection was derived. Report: {report[:400]!r}"
        )
    if "pinned to the supplied flow" not in report:
        raise SmokeFailure(f"the report does not say the flow was pinned: {report[:400]!r}")
    if not settled.get("hasString"):
        raise SmokeFailure("the flow-pinned build produced no blueprint string")
    return {"report": report[:300], "flow_chars": len(FLOW_CSV.read_bytes())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="web_smoke", description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("out/web-smoke"), help="where screenshots go")
    ap.add_argument("--port", type=int, help="port for the server this starts")
    ap.add_argument("--server", help="drive an already-running server instead, e.g. 127.0.0.1:8000")
    ap.add_argument("--browser", help="Chromium/Chrome path (default: the usual search)")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    args = ap.parse_args(argv, namespace=_Args())

    args.out.mkdir(parents=True, exist_ok=True)
    browser_path = find_browser(args.browser)

    server: Server | None = None
    if args.server:
        base = args.server if args.server.startswith("http") else f"http://{args.server}"
    else:
        server = start_server(args.port)
        base = server.base
    print(f"web_smoke: driving {base} with {browser_path}", flush=True)

    try:
        report = asyncio.run(_run(base, args.out, browser_path, not args.headed))
    except SmokeFailure as exc:
        print(f"\nFAILED: {exc}", flush=True)
        return 1
    finally:
        if server is not None and server.process is not None:
            server.process.terminate()

    good = report["success"]
    bad = report["refusal"]
    print("\n-- the happy path --")
    print(f"  title                    {good['title']}")
    print(f"  clipboard                {good['clipboard_chars']} chars")
    print(f"  decoded buildings        {good['buildings']}")
    print(f"  codec round-trip         {good['round_trips']}")
    print(f"  canvas                   {good['canvas']}, {good['canvas_distinct_colours']} colours")
    print(f"  screenshot               {good['screenshot']}")
    print(f"  report                   {good['report']}")
    print(f"  warnings on the page     {good['warnings'] or '(none)'}")
    pinned = report["flow"]
    print("\n-- the flow pin --")
    print(f"  flow pasted              {pinned['flow_chars']} bytes")
    print(f"  report                   {pinned['report']}")
    print("\n-- the refusal --")
    print(f"  reason                   {bad['refusal']}")
    print(f"  screenshot               {bad['screenshot']}")

    console = good["console"] + bad["console"]
    print(f"\n-- console ({len(console)} message(s)) --")
    for message in console:
        print(f"  [{message['level']}] {message['text'][:300]}")
    (args.out / "report.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {args.out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
