"""The HTTP surface: four endpoints and a static directory.

On the standard library, on purpose.  A build is CPU-bound for seconds to
minutes behind a queue that is one worker deep, so nothing here is under any
throughput pressure that would justify making ``flab2bp`` -- a CLI -- depend on
a web framework.  ``ThreadingHTTPServer`` answers polls while a solve holds a
worker thread, which is the entire concurrency requirement.

    POST /api/build          submit; returns an id
    GET  /api/build/<id>     poll; returns state, and the result when there is one
    GET  /api/health         is the server up, and is the front end built
    GET  /api/fetch?url=...  the viewer's own blueprint-page proxy
    GET  /*                  the built front end, with an SPA fallback

Bound to 127.0.0.1 by default.  ``/api/fetch`` is an open relay to any http(s)
URL -- inherited from the viewer, where the same caveat already applied -- and
``/api/build`` will spend every core on a CP-SAT solve for anyone who asks.
Neither belongs on a public interface without work this does not do.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import subprocess
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from flab2bp.pipeline import Build
from flab2bp.web.jobs import Builder, InvalidOptions, Options, parse_options, run_build
from flab2bp.web.payload import Json

#: Refuse a body larger than this. A FactorioLab URL is long, but not this long.
MAX_BODY_BYTES = 256 * 1024

#: How long the inherited ``/api/fetch`` proxy waits on a third-party page.
FETCH_TIMEOUT_S = 20.0

#: How long ``--build`` gives bun before giving up.
BUILD_TIMEOUT_S = 240.0

#: Where ``bun run build`` puts the front end, relative to the repo root.
DIST = Path("web") / "dist"


def repo_root() -> Path:
    """The checkout this package was installed from, editable.

    ``web/`` is a sibling of ``src/``, so the front end is found by walking up
    from this file rather than by guessing a working directory.  A non-editable
    install has no ``web/`` at all, which ``--dist`` exists to answer.
    """
    return Path(__file__).resolve().parents[3]


class Handler(BaseHTTPRequestHandler):
    """One request.  Routing is explicit; there is not enough of it to abstract."""

    server_version = "flab2bp"
    protocol_version = "HTTP/1.1"

    #: Both are set on a subclass by :func:`serve`.
    builder: Builder
    dist: Path

    def log_message(self, format: str, *args: Any) -> None:
        """Quieter than the default, which would log every poll of every job."""
        if self.command == "GET" and self.path.startswith("/api/build/"):
            return
        super().log_message(format, *args)

    # ---- plumbing -------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The whole app is one person's local tool; a cached poll, or a cached
        # index.html after a rebuild, is pure confusion.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, body: Json) -> None:
        self._send(status, json.dumps(body).encode(), "application/json; charset=utf-8")

    def _text(self, status: int, body: str) -> None:
        self._send(status, body.encode(), "text/plain; charset=utf-8")

    def _read_json(self) -> object:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise InvalidOptions(f"request body over {MAX_BODY_BYTES} bytes")
        try:
            return json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError as exc:
            raise InvalidOptions(f"body is not valid JSON: {exc}") from exc

    # ---- routes ---------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's spelling
        if urlparse(self.path).path != "/api/build":
            self._text(HTTPStatus.NOT_FOUND, "no such endpoint")
            return
        try:
            options = parse_options(self._read_json())
        except InvalidOptions as exc:
            # A bad request is the one thing here that IS an error: nothing was
            # attempted, so there is no result to report.
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        job = self.builder.submit(options)
        self._json(HTTPStatus.ACCEPTED, self.builder.snapshot(job))

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._json(
                HTTPStatus.OK,
                {"ok": True, "front_end_built": (self.dist / "index.html").is_file()},
            )
            return

        if path.startswith("/api/build/"):
            job = self.builder.get(path.removeprefix("/api/build/"))
            if job is None:
                # Distinct from a refusal: this is a poll for a job that never
                # existed, or one that has aged out of the history.
                self._json(HTTPStatus.NOT_FOUND, {"error": "no such job"})
                return
            self._json(HTTPStatus.OK, self.builder.snapshot(job))
            return

        if path == "/api/fetch":
            self._proxy(parse_qs(parsed.query).get("url", [""])[0])
            return

        if path.startswith("/api/"):
            self._text(HTTPStatus.NOT_FOUND, "no such endpoint")
            return

        self._static(path)

    # ---- the viewer's inherited proxy -----------------------------------

    def _proxy(self, target: str) -> None:
        """``/api/fetch``, reimplemented from the viewer's ``src/server/proxy.ts``.

        Kept because the viewer's "or URL" field is a feature we took over, and
        dropping it while serving the same page from Python would have been a
        silent regression in an inherited app.  Same shape as the original: the
        page body as plain text, 400 on bad input, 502 carrying the real reason
        when the upstream is unreachable.  Same known limitation, too --
        redirects are followed, so it is not hardened against a local-to-local
        SSRF, which is one of the reasons this binds to localhost.
        """
        if not target:
            self._text(HTTPStatus.BAD_REQUEST, "Missing url")
            return
        if urlparse(target).scheme not in ("http", "https"):
            self._text(HTTPStatus.BAD_REQUEST, "Only http/https are allowed")
            return
        try:
            upstream = httpx.get(
                target,
                timeout=FETCH_TIMEOUT_S,
                follow_redirects=True,
                headers={"user-agent": "dsp-blueprint-viewer"},
            )
        except httpx.HTTPError as exc:
            self._text(HTTPStatus.BAD_GATEWAY, f"Could not reach {target}: {exc}")
            return
        self._send(upstream.status_code, upstream.text.encode(), "text/plain; charset=utf-8")

    # ---- static ---------------------------------------------------------

    def _static(self, path: str) -> None:
        index = self.dist / "index.html"
        if not index.is_file():
            self._text(
                HTTPStatus.SERVICE_UNAVAILABLE,
                f"The front end is not built. Expected {index}.\n"
                f"Run:  cd web && bun install && bun run build\n"
                f"or start the server with:  flab2bp-web --build\n",
            )
            return

        root = self.dist.resolve()
        target = (root / path.lstrip("/")).resolve()
        # A single-page app answers an unknown path with index.html. A path that
        # escapes the dist directory is not an unknown route, it is an attempt,
        # and it gets exactly the same answer rather than a file.
        if not target.is_relative_to(root) or not target.is_file():
            target = index

        kind, _ = mimetypes.guess_type(target.name)
        self._send(HTTPStatus.OK, target.read_bytes(), kind or "application/octet-stream")


def build_front_end(root: Path, *, timeout_s: float = BUILD_TIMEOUT_S) -> None:
    """``bun install && bun run build`` in ``web/``.

    Here rather than in a shell script so that one command starts the whole
    thing.  It shells out to ``bun`` because that is what the viewer already
    used, and reproducing rsbuild in Python is not a thing anyone wants.
    """
    bun = shutil.which("bun")
    if bun is None:
        raise RuntimeError("bun is not on PATH; install it, or build web/ yourself")
    web = root / "web"
    for args in (["install", "--frozen-lockfile"], ["run", "build"]):
        subprocess.run([bun, *args], cwd=web, check=True, timeout=timeout_s)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    dist: Path | None = None,
    workers: int = 1,
    solve: Callable[[Options], Build] = run_build,
) -> tuple[ThreadingHTTPServer, Builder]:
    """A configured, unstarted server and the queue behind it.

    Returned rather than run so a test can drive it on an ephemeral port.
    ``solve`` is injectable for the same reason: the HTTP surface can then be
    tested against a build that takes no CP-SAT time, or one that never
    finishes, without either being a special case in the server itself.
    """
    builder = Builder(workers=workers, solve=solve)

    class Bound(Handler):
        pass

    Bound.builder = builder
    Bound.dist = dist if dist is not None else repo_root() / DIST
    httpd = ThreadingHTTPServer((host, port), Bound)
    httpd.daemon_threads = True
    return httpd, builder


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="flab2bp-web",
        description="Serve the flab2bp browser front end and the build API.",
    )
    ap.add_argument("--host", default="127.0.0.1", help="interface to bind (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8000, help="port to bind (default 8000)")
    ap.add_argument("--dist", type=Path, help="built front end (default <repo>/web/dist)")
    ap.add_argument(
        "--build",
        action="store_true",
        help="run 'bun install && bun run build' in web/ first, even if dist/ exists",
    )
    ap.add_argument(
        "--no-build",
        dest="autobuild",
        action="store_false",
        help="never shell out to bun; serve whatever dist/ holds",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=1,
        help="concurrent builds (default 1; one CP-SAT solve already uses every core)",
    )
    args = ap.parse_args(argv)

    root = repo_root()
    dist = args.dist if args.dist is not None else root / DIST
    if args.build or (args.autobuild and not (dist / "index.html").is_file()):
        print("flab2bp-web: building the front end (bun install && bun run build) ...")
        try:
            build_front_end(root)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            # Not fatal: the API is the half that needs Python, and the page
            # itself explains what is missing rather than 404ing silently.
            print(f"flab2bp-web: could not build the front end: {exc}")
            print("flab2bp-web: serving the API anyway; the page will say so.")

    httpd, builder = serve(host=args.host, port=args.port, dist=dist, workers=args.workers)
    print(f"flab2bp-web: http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        httpd.shutdown()
        httpd.server_close()
        # In-flight solves are abandoned here, not finished. See the README:
        # a job does not survive a restart, and nothing pretends otherwise.
        builder.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
