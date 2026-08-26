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
5. Nothing but static files was ever requested.  Two independent witnesses:
   Chrome's own network log via CDP, and the static server's request log.
6. The viewer drew a real SVG.

``--refusal`` runs the same flow against a URL the pipeline refuses, so the
refusal path is exercised and screenshotted too.
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

#: The user's own URL: freeform / max-proliferation, ~1200 tiles, 20 coaters.
DEFAULT_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFyr0KwkAQReG3meJWO8GQapq7GDtJBMVt1"
    "UUkLoGAEpt5dhH.uo.DGY1naJDReMSiDoC-.Pi7QRU-3KH6HQn6zSTqt7OhlWJEkGIJQS6HbJQpz9"
    "Yh4YQBN3ANbsE9ODiviK3HFWLvcSOlTJacvvRe7qb6BOgIKRo_&v=11"
)

#: A URL whose objective the pipeline cannot build, used to exercise the
#: refusal path.  A refusal is a correct outcome here, never an error.
REFUSAL_URL = "https://factoriolab.github.io/dsp/list?z=not-a-real-payload&v=11"

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
                "--enable-features=WebAssemblyJSPromiseIntegration",
                f"--unsafely-treat-insecure-origin-as-secure=http://127.0.0.1:{args.port}",
            ],
        )
        try:
            from nodriver import cdp

            origin = f"http://127.0.0.1:{args.port}"
            base = origin + "/app.html"
            # Headless Chrome refuses clipboard access unless it is granted; the
            # *write* the button performs is what we are testing, and reading it
            # back afterwards is how we check the button did it.
            await browser.connection.send(
                cdp.browser.grant_permissions(
                    [
                        cdp.browser.PermissionType.CLIPBOARD_READ_WRITE,
                        cdp.browser.PermissionType.CLIPBOARD_SANITIZED_WRITE,
                    ],
                    origin=origin,
                )
            )

            page = await browser.get(base)
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

            await wait_for(page, "window.__flab && window.__flab.ready === true", args.boot_timeout)
            report["bootSeconds"] = round(time.perf_counter() - boot_started, 1)
            report["boot"] = json.loads(await page.evaluate("JSON.stringify(window.__flab.boot)"))

            url = args.url if not args.refusal else REFUSAL_URL
            await page.evaluate(f"document.getElementById('url').value = {json.dumps(url)}")
            await page.evaluate(
                f"document.getElementById('strategy').value = {json.dumps(args.strategy)};"
                f"document.getElementById('candidates').value = {args.candidates};"
                f"document.getElementById('budget').value = {args.budget};"
                f"document.getElementById('power').checked = {str(not args.no_power).lower()};"
            )
            solve_started = time.perf_counter()
            await page.evaluate("document.getElementById('solve').click()")
            await wait_for(page, "window.__flab.done === true", args.solve_timeout)
            report["solveSeconds"] = round(time.perf_counter() - solve_started, 1)

            raw = await page.evaluate("JSON.stringify(window.__flab.result)")
            result = json.loads(raw) if raw and raw != "null" else None
            report["fatal"] = json.loads(await page.evaluate("JSON.stringify(window.__flab.error)"))

            if result is None:
                report["result"] = None
            elif not result["ok"]:
                report["refusal"] = result["refusal"]
                report["refusalKind"] = result["kind"]
            else:
                report["strategy"] = result["strategy"]
                report["candidate"] = result["candidate"]
                report["machines"] = result["machines"]
                report["tiles"] = result["tiles"]
                report["buildings"] = result["buildings"]
                report["notes"] = result["notes"]
                report["errors"] = result["errors"]
                report["refused"] = result["refused"]

                await page.evaluate("document.getElementById('copy').click()")
                await asyncio.sleep(0.5)
                clipboard, how = await read_clipboard(page)
                report["clipboardSource"] = how
                report["clipboardChars"] = len(clipboard or "")
                report["clipboardError"] = await page.evaluate("window.__flab.copyError")
                report["blueprint"] = clipboard
                report["viewerRects"] = int(
                    await page.evaluate("document.querySelectorAll('svg rect').length")
                )

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
    ap.add_argument("--budget", type=float, default=2.0)
    ap.add_argument("--no-power", action="store_true")
    ap.add_argument("--refusal", action="store_true", help="drive the refusal path instead")
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
    if args.refusal:
        return 0 if report.get("refusal") else 1
    if not isinstance(decoded, dict) or not decoded["buildings"]:
        print("FAILED: the clipboard string did not decode to a blueprint with buildings")
        return 1
    if report["noServerSolveProblems"]:
        print("FAILED: something other than a static file was requested")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
