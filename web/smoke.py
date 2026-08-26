"""Drive the client-side page in a real browser and prove what came out of it.

This is the verification gate for the client-side arm, and it is a script
rather than a transcript so the claims can be re-run::

    python web/build_payload.py
    python web/fetch_assets.py
    uv run python web/smoke.py

What it asserts, in order:

1. The page boots and reports cross-origin isolation, SharedArrayBuffer and
   JSPI -- the three things the wasm solvers need.
2. Solve produces a result, or a refusal, and either is reported verbatim.
3. The Copy button really put the blueprint on the clipboard: the string is
   read back out of the browser, not out of a variable we hoped matched.
4. That exact string decodes with ``flab2bp.dsp.codec.decode`` *in native
   Python*, carries buildings, and re-encodes to itself.
5. Nothing but static files was ever requested.  Three witnesses, of which the
   first is the one that could have falsified the claim: the browser runs with
   every hostname blackholed, so any dependency on a CDN, an API or
   FactorioLab itself would have failed the solve outright; the static server
   logs every request it answered; and Chrome's CDP network log is captured
   too, though it only covers the top-level document -- the worker and the
   wasm runtimes' own workers are separate CDP targets it does not see.
6. The viewer drew something. It is the SERVER arm's viewer -- the same
   React/three.js tree, mounted from `web/src/embed.tsx` -- so the check is
   `scripts/web_smoke.py`'s own: screenshot the canvas through CDP and count
   distinct colours, because a WebGL surface that never drew is one flat
   colour and one flat colour is exactly 1.

``--refusal`` runs the same flow against ``scripts/web_smoke.py``'s own
refusal fixture -- one spec, both arms -- so the refusal path is exercised and
screenshotted too.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import nodriver

WEB = Path(__file__).resolve().parent

# The two arms are proved by two scripts, but "did the viewer actually draw
# anything" must not be two different questions. `scripts/web_smoke.py` already
# owns that check -- screenshot the canvas through CDP, count distinct colours,
# refuse a surface that is one flat colour -- so it is imported rather than
# written again here. Both arms now mount the SAME viewer (web/src/embed.tsx),
# which is what makes one implementation of the check correct for both.
sys.path.insert(0, str(WEB.parent / "scripts"))
from web_smoke import (  # noqa: E402
    FLOW_CSV,
    FLOW_URL,
    REFUSE_URL,
    SmokeFailure,
    _canvas_variety,
)

#: The user's own URL: freeform / max-proliferation, ~1200 tiles, 20 coaters.
DEFAULT_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFyr0KwkAQReG3meJWO8GQapq7GDtJBMVt1"
    "UUkLoGAEpt5dhH.uo.DGY1naJDReMSiDoC-.Pi7QRU-3KH6HQn6zSTqt7OhlWJEkGIJQS6HbJQpz9"
    "Yh4YQBN3ANbsE9ODiviK3HFWLvcSOlTJacvvRe7qb6BOgIKRo_&v=11"
)

#: The corpus's ``universe-matrix``, imported from ``scripts/web_smoke.py`` so
#: that both arms are driven onto the refusal path by the same spec.
#:
#: It used to be ``z=not-a-real-payload``, which is a different thing entirely:
#: an unparseable URL raises ``ValueError`` before any layout is attempted, and
#: the page rightly calls that an ERROR. A refusal is what happens when the
#: pipeline ran, tried every strategy on every candidate, and none of them
#: produced a layout -- the reason text is the product, and only this URL
#: exercises the path that carries it.
REFUSAL_URL = REFUSE_URL

BROWSER_CANDIDATES = (
    "/usr/lib64/chromium-browser/chromium-browser",
    "/usr/lib/chromium-browser/chromium-browser",
    "/opt/google/chrome/chrome",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


def find_browser(explicit: str | None) -> str:
    import shutil

    for candidate in ([explicit] if explicit else []) + list(BROWSER_CANDIDATES):
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate if Path(candidate).is_file() else str(shutil.which(candidate))
    raise SystemExit("no Chromium or Chrome found; pass --browser")


class StaticServer:
    """``web/serve.py``, plus a read of the request log it keeps."""

    def __init__(self, port: int, *, isolated: bool) -> None:
        self.port = port
        self.isolated = isolated
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> StaticServer:
        args = [sys.executable, str(WEB / "serve.py"), "--port", str(self.port), "--dir", str(WEB)]
        if self.isolated:
            args.append("--isolated")
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/__reset__", timeout=1).read()
                return self
            except OSError:
                time.sleep(0.2)
        raise SystemExit("the static server never came up")

    def __exit__(self, *exc: object) -> None:
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=10)

    def reset_tally(self) -> None:
        urllib.request.urlopen(f"http://127.0.0.1:{self.port}/__reset__", timeout=5).read()

    def requests(self) -> list[str]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/__log__", timeout=5) as body:
            return json.loads(body.read())["paths"]

    def bytes_served(self) -> dict[str, object]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/__tally__", timeout=5) as body:
            tally = json.loads(body.read())
        by_path = tally["by_path"]
        biggest = sorted(by_path.items(), key=lambda kv: -kv[1])[:12]
        return {
            "totalMB": round(tally["total"] / 1048576, 2),
            "files": len(by_path),
            "biggest": [{"path": p, "MB": round(n / 1048576, 2)} for p, n in biggest],
        }


async def drive(args: argparse.Namespace) -> dict[str, object]:
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {}

    with StaticServer(args.port, isolated=not args.no_isolation) as server:
        browser = await nodriver.start(
            browser_executable_path=find_browser(args.browser),
            headless=not args.headed,
            browser_args=[
                "--no-sandbox",
                "--disable-gpu",
                # Headless Chrome will not hand out clipboard-read without it;
                # the write the button performs needs no permission.
                # A no-op on Chromium 151, which ships JSPI unconditionally, and
                # kept for older builds that still gate it. Measured: neither
                # `--disable-features=WebAssemblyJSPromiseIntegration` nor
                # `--js-flags=--no-wasm-jspi` nor
                # `--js-flags=--no-experimental-wasm-jspi` turns it back off
                # here -- `typeof WebAssembly.Suspending` reads `function` under
                # all three -- so the no-JSPI path cannot be driven from a
                # browser on this box. What happens without it is on record in
                # web/CLIENTSIDE.md, measured when it could still be switched.
                "--enable-features=WebAssemblyJSPromiseIntegration",
                f"--unsafely-treat-insecure-origin-as-secure=http://127.0.0.1:{args.port}",
                # The strongest form of "no server solved this": every hostname
                # in the browser is a dead end. Only the literal 127.0.0.1 our
                # static server listens on is reachable, because an IP literal
                # never goes through the resolver. If the page needed a CDN, an
                # API or FactorioLab itself, it would fail here rather than
                # quietly succeed and leave the claim resting on a log.
                # Both EXCLUDEs are load-bearing. `MAP *` matches IP literals
                # too, so without them neither the driver's DevTools connection
                # nor the page's own origin resolves, and the run hangs before
                # anything has loaded -- which would look like a pass with an
                # empty request log rather than the failure it is.
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
            ],
        )
        try:
            from nodriver import cdp

            origin = f"http://127.0.0.1:{args.port}"
            base = origin + "/app.html"

            page = await browser.get(base)
            # `navigator.clipboard.writeText` needs two things headless Chrome
            # does not give by default: the permission, and a focused document.
            # Both are granted here so that a failure to copy means the button
            # is broken rather than that the harness never let it work.
            try:
                await page.send(
                    cdp.browser.grant_permissions(
                        [
                            cdp.browser.PermissionType.CLIPBOARD_READ_WRITE,
                            cdp.browser.PermissionType.CLIPBOARD_SANITIZED_WRITE,
                        ],
                        origin=origin,
                    )
                )
            except Exception as error:  # noqa: BLE001 - reported, and focus alone may do
                report["permissionGrant"] = str(error)
            await page.send(cdp.emulation.set_focus_emulation_enabled(True))
            await page.bring_to_front()
            seen: list[str] = []
            console: list[str] = []
            await instrument(page, cdp, seen, console)

            if not args.no_isolation:
                # coi-serviceworker installs on the first load and only takes
                # effect on the next one. Reloading unconditionally keeps the
                # two hosting modes on the same code path.
                await asyncio.sleep(1.0)
            # Everything below is one cold load: the byte tally is reset here so
            # the reload above is not counted twice. `Cache-Control: no-store`
            # means the reload really does re-fetch, so this is a true cold
            # figure and not a warm one.
            server.reset_tally()
            boot_started = time.perf_counter()
            page = await browser.get(base)
            await instrument(page, cdp, seen, console)
            await page.send(cdp.emulation.set_focus_emulation_enabled(True))
            await page.bring_to_front()

            await wait_for(page, "window.__flab && window.__flab.ready === true", args.boot_timeout)
            report["bootSeconds"] = round(time.perf_counter() - boot_started, 1)
            report["boot"] = json.loads(await page.evaluate("JSON.stringify(window.__flab.boot)"))

            url = args.url
            if args.refusal:
                url = REFUSAL_URL
            elif args.flow_pin:
                url = FLOW_URL
            # Same knobs the server arm drives the same URL with: one
            # candidate, freeform, so the refusal is the layout model's and
            # not a budget the page happened to be set low on.
            if args.refusal:
                args.strategy, args.candidates, args.budget = "freeform", 1, 4.0
            if args.flow_pin:
                args.strategy, args.candidates, args.budget = "freeform", 1, 4.0
            await page.evaluate(f"document.getElementById('url').value = {json.dumps(url)}")
            # Always set it, empty included: a flow left in the box from a
            # previous run would be submitted with this run's URL, where
            # `flow_from_text` rightly refuses it as an export for a different
            # URL and the case fails on that instead of on what it meant to test.
            flow_csv = FLOW_CSV.read_text(encoding="utf-8-sig") if args.flow_pin else ""
            await page.evaluate(
                f"document.getElementById('flow').value = {json.dumps(flow_csv)}"
            )
            report["flowChars"] = len(flow_csv)
            await page.evaluate(
                f"document.getElementById('strategy').value = {json.dumps(args.strategy)};"
                f"document.getElementById('candidates').value = {args.candidates};"
                f"document.getElementById('budget').value = {args.budget};"
                f"document.getElementById('power').checked = {str(not args.no_power).lower()};"
                # Setting `.value` does not fire `input`, and the page's budget
                # note is computed from these. Dispatched so the screenshot
                # shows the note for the build that actually ran.
                "for (const id of ['strategy','candidates','budget'])"
                " document.getElementById(id)"
                ".dispatchEvent(new Event('input', {bubbles: true}));"
            )
            solve_started = time.perf_counter()
            await page.evaluate("document.getElementById('solve').click()")
            await wait_for(page, "window.__flab.done === true", args.solve_timeout)
            report["solveSeconds"] = round(time.perf_counter() - solve_started, 1)

            # The job snapshot, field for field what the server arm's
            # `GET /api/build/<id>` returns -- see web/bootstrap.py.
            raw = await page.evaluate("JSON.stringify(window.__flab.snapshot)")
            snapshot = json.loads(raw) if raw and raw != "null" else None
            report["fatal"] = json.loads(await page.evaluate("JSON.stringify(window.__flab.error)"))
            # What the page ACTUALLY submitted, read back off the snapshot --
            # not what this script asked for. The two differ the moment a
            # control is set in a way the page does not read, and a bake-off
            # number attributed to the wrong budget is worse than no number.
            if snapshot is not None:
                report["submitted"] = snapshot["options"]

            if snapshot is None:
                report["result"] = None
            elif snapshot["state"] == "refused":
                report["refusal"] = snapshot["refusal"]["message"]
                report["refusalReasons"] = snapshot["refusal"]["reasons"]
            elif snapshot["state"] == "error":
                report["error"] = snapshot["error"]
            else:
                result = snapshot["result"]
                report["strategy"] = result["strategy"]
                report["candidate"] = result["candidate"]
                report["machines"] = result["machines"]
                report["tiles"] = result["area"]
                report["buildings"] = result["buildings"]
                report["title"] = result["title"]
                report["valid"] = result["valid"]
                report["refused"] = result["refused"]
                report["skipped"] = result["report"]["skipped"]
                # Warnings were the drift this unification caught: a check that
                # RAN and found something to act on was serialised by the
                # server arm and by nothing at all here.
                report["validationWarnings"] = [
                    f"{f['check']}: {f['message']}" for f in result["report"]["warnings"]
                ]
                report["validationErrors"] = [
                    f"{f['check']}: {f['message']}" for f in result["report"]["errors"]
                ]
                report["beltRulesFromUrl"] = (result["belt_rules"] or {}).get("from_url")
                report["flowPinned"] = result["flow_pinned"]
                report["runtimeWarnings"] = snapshot.get("runtime_warnings", [])
                report["settled"] = snapshot["settled"]

                await page.evaluate("document.getElementById('copy').click()")
                await asyncio.sleep(0.5)
                clipboard, how = await read_clipboard(page)
                report["clipboardSource"] = how
                report["clipboardChars"] = len(clipboard or "")
                report["clipboardError"] = await page.evaluate("window.__flab.copyError")
                report["blueprint"] = clipboard
                # The string in the DOM, not the one in `state`: the button
                # reads the same object the panel rendered from, so comparing
                # them is what catches a panel showing one build's string while
                # the button copies another's.
                report["domString"] = await page.evaluate(
                    "(document.querySelector('[data-testid=blueprint-string]')||{}).value || null"
                )

                await wait_for(
                    page,
                    "window.__flab.viewerMounted === true || window.__flab.viewerError !== null",
                    args.viewer_timeout,
                )
                report["viewerError"] = await page.evaluate("window.__flab.viewerError")
                if report["viewerError"] is None:
                    try:
                        colours, box = await _canvas_variety(page, cdp)
                    except SmokeFailure as exc:
                        # Reported, never swallowed: `main` turns a missing or
                        # flat canvas into a non-zero exit.
                        report["viewerError"] = str(exc)
                    else:
                        report["canvasColours"] = colours
                        report["canvas"] = box

            await page.save_screenshot(
                str(shots / ("refusal.png" if args.refusal else "success.png")),
                format="png",
                full_page=True,
            )
            report["screenshot"] = str(shots / ("refusal.png" if args.refusal else "success.png"))
            report["console"] = [line for line in console if "error" in line.lower()]
            report["browserRequests"] = sorted(set(seen))
        finally:
            browser.stop()
        report["serverRequests"] = server.requests()
        report["coldPayload"] = server.bytes_served()
    return report


async def instrument(page, cdp, seen: list[str], console: list[str]) -> None:
    """Watch every request and every console error on this tab.

    Re-applied after each navigation: CDP domains and handlers belong to the
    target, and a fresh document starts with neither.  Subresources fetched by
    the worker and by the wasm runtimes' own workers appear here too, which is
    what makes the "nothing but static files" claim falsifiable.
    """
    await page.send(cdp.network.enable())
    await page.send(cdp.runtime.enable())
    await page.send(cdp.log.enable())
    page.add_handler(cdp.network.RequestWillBeSent, lambda e: seen.append(e.request.url))
    page.add_handler(
        cdp.runtime.ConsoleAPICalled,
        lambda e: console.append(
            f"{e.type_}: " + " ".join(str(getattr(a, "value", a)) for a in (e.args or []))
        ),
    )
    page.add_handler(
        cdp.runtime.ExceptionThrown,
        lambda e: console.append(f"exception: {e.exception_details.text}"),
    )
    page.add_handler(
        cdp.log.EntryAdded,
        lambda e: console.append(f"{e.entry.level}: {e.entry.text} {e.entry.url or ''}"),
    )


async def wait_for(page, expression: str, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if await page.evaluate(expression):
            return
        await asyncio.sleep(1.0)
    raise SystemExit(f"timed out after {timeout_s}s waiting for: {expression}")


async def read_clipboard(page) -> tuple[str | None, str]:
    """Prefer the real clipboard; fall back to what the button recorded writing.

    Both are readings of the button's effect, not of the result object: the
    page only sets ``__flab.copied`` after ``navigator.clipboard.writeText``
    resolves.
    """
    try:
        text = await page.evaluate(
            "navigator.clipboard.readText()", await_promise=True, return_by_value=True
        )
        if isinstance(text, str) and text:
            return text, "navigator.clipboard.readText()"
    except Exception:  # noqa: BLE001 - permission refusal is expected headless
        pass
    text = await page.evaluate("window.__flab.copied")
    return (text if isinstance(text, str) else None), "window.__flab.copied (post-writeText)"


def check_no_server_solve(report: dict[str, object], port: int) -> list[str]:
    """Every request must be a static asset from our own origin."""
    problems: list[str] = []
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", ""}
    for url in report.get("browserRequests", []):  # type: ignore[union-attr]
        split = urlsplit(url)
        if split.scheme in ("data", "blob"):
            continue
        if split.netloc not in allowed_hosts:
            problems.append(f"off-origin request: {url}")
    for path in report.get("serverRequests", []):  # type: ignore[union-attr]
        head = path.split("?")[0]
        if head in ("/__reset__", "/__log__", "/__tally__"):
            continue
        if not head.startswith("/"):
            problems.append(f"odd request path: {path}")
        if head.rstrip("/").endswith(("solve", "build", "api", "job", "jobs")):
            problems.append(f"looks like a solve endpoint: {path}")
    return problems


def verify_blueprint(text: str) -> dict[str, object]:
    """Decode the exact clipboard string with the real, native flab2bp."""
    from flab2bp.dsp import codec

    blueprint = codec.decode(text)
    reencoded = codec.encode_blueprint(blueprint)
    return {
        "buildings": len(blueprint.buildings),
        "areas": len(blueprint.areas),
        "hashValid": blueprint.hash_valid,
        "title": blueprint.header.short_desc,
        "roundTrips": reencoded == text,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--port", type=int, default=8493)
    ap.add_argument("--strategy", default="best", choices=("best", "spine", "freeform"))
    ap.add_argument("--candidates", type=int, default=3)
    # 6, not the CLI's 2, because the page's default is 6: the wasm CP-SAT
    # runtime has a four-thread pool and CP-SAT is a portfolio, so the same
    # wall-clock budget buys materially less search here. Measured, in
    # docs/WEB_UI.md. The proof runs what the page ships with.
    ap.add_argument("--budget", type=float, default=6.0)
    ap.add_argument("--no-power", action="store_true")
    ap.add_argument("--refusal", action="store_true", help="drive the refusal path instead")
    ap.add_argument(
        "--flow-pin",
        action="store_true",
        help="paste `scripts/web_smoke.py`'s FactorioLab flow export and check the "
        "recipe selection comes back PINNED. `--flow` is the half of the flow story a "
        "page can do; `--fetch-flow` is the half it cannot, because it drives a headless "
        "browser to make FactorioLab run its own solve.",
    )
    ap.add_argument(
        "--no-isolation",
        action="store_true",
        help="serve without COOP/COEP, the way GitHub Pages does, so the "
        "coi-serviceworker route is what supplies isolation",
    )
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--browser")
    ap.add_argument("--boot-timeout", type=float, default=240.0)
    ap.add_argument("--solve-timeout", type=float, default=280.0)
    ap.add_argument("--viewer-timeout", type=float, default=120.0)
    ap.add_argument("--shots", default=str(WEB / "shots"))
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args(argv)

    report = nodriver.loop().run_until_complete(drive(args))

    blueprint = report.pop("blueprint", None)
    if isinstance(blueprint, str) and blueprint:
        report["decoded"] = verify_blueprint(blueprint)
    report["noServerSolveProblems"] = check_no_server_solve(report, args.port)

    if args.json:
        Path(args.json).write_text(json.dumps({**report, "blueprint": blueprint}, indent=2) + "\n")

    printable = dict(report)
    printable["browserRequests"] = len(report.get("browserRequests", []))  # type: ignore[arg-type]
    printable["serverRequests"] = len(report.get("serverRequests", []))  # type: ignore[arg-type]
    print(json.dumps(printable, indent=2))

    decoded = report.get("decoded")
    if args.flow_pin:
        # Falsifiable: a page that dropped the paste would come back
        # flow_pinned false, which is what an unpinned build reports and is
        # exactly the silent weaker guarantee this exists to catch.
        if report.get("flowPinned") is not True:
            print(f"FAILED: the pasted flow did not pin; flow_pinned={report.get('flowPinned')!r}")
            return 1
        if report.get("candidate") != "flow-pinned":
            print(f"FAILED: the winning candidate is {report.get('candidate')!r}, not flow-pinned")
            return 1
        if not isinstance(decoded, dict) or not decoded["buildings"]:
            print("FAILED: the flow-pinned build handed out nothing that decodes")
            return 1
        return 0
    if args.refusal:
        return 0 if report.get("refusal") else 1
    if not isinstance(decoded, dict) or not decoded["buildings"]:
        print("FAILED: the clipboard string did not decode to a blueprint with buildings")
        return 1
    if not decoded["roundTrips"]:
        print("FAILED: the clipboard string does not re-encode to itself, byte for byte")
        return 1
    if report.get("domString") != blueprint:
        print("FAILED: the button copied something other than the string on the page")
        return 1
    if report.get("viewerError") is not None:
        print(f"FAILED: the viewer did not mount: {report['viewerError']}")
        return 1
    # A WebGL surface that never drew is one flat colour, and one flat colour
    # is exactly 1. This is the check that could have caught a canvas mounted
    # over an empty scene.
    if int(report.get("canvasColours") or 0) < 2:
        print(f"FAILED: the canvas is one flat colour ({report.get('canvasColours')})")
        return 1
    if report["noServerSolveProblems"]:
        print("FAILED: something other than a static file was requested")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
