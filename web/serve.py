"""Static server for the client-side arm probe.

Two modes, because the whole question is whether a host that CANNOT set
cross-origin-isolation headers can run this:

    python serve.py --port 8081            # GitHub Pages simulation: no COOP/COEP
    python serve.py --port 8082 --isolated # a host that CAN set them

Every response's byte count is tallied so a cold load can be measured from the
server side as well as from the browser's resource timings.
"""

from __future__ import annotations

import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

_LOCK = threading.Lock()
TALLY: dict[str, int] = {}
#: Every request this server ever answered, in order.  It is the corroborating
#: witness for "no server solved this": the browser's own network log says
#: nothing left the page, and this says nothing but files arrived here.
LOG: list[str] = []

MIME_EXTRA = {
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
}


class Handler(SimpleHTTPRequestHandler):
    isolated = False

    def end_headers(self) -> None:
        if self.isolated:
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path: str) -> str:  # type: ignore[override]
        for ext, mime in MIME_EXTRA.items():
            if path.endswith(ext):
                return mime
        return super().guess_type(path)

    def send_response(self, code: int, message: str | None = None) -> None:
        super().send_response(code, message)

    def copyfile(self, source, outputfile) -> None:  # type: ignore[override]
        data = source.read()
        with _LOCK:
            TALLY[self.path] = TALLY.get(self.path, 0) + len(data)
        outputfile.write(data)

    def do_POST(self) -> None:  # noqa: N802 - http.server's name
        # There is no POST handler on purpose: a solve would have to be one.
        with _LOCK:
            LOG.append(f"POST {self.path}")
        self.send_error(405, "this server only hands out files")

    def do_GET(self) -> None:
        if self.path not in ("/__tally__", "/__reset__", "/__log__"):
            with _LOCK:
                LOG.append(self.path)
        if self.path == "/__log__":
            body = json.dumps({"paths": list(LOG)}, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/__tally__":
            body = json.dumps(
                {"total": sum(TALLY.values()), "by_path": TALLY}, indent=2
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/__reset__":
            with _LOCK:
                TALLY.clear()
                LOG.clear()
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        super().do_GET()

    def log_message(self, *args: object) -> None:  # quiet
        return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--isolated", action="store_true")
    ap.add_argument("--dir", default=".")
    args = ap.parse_args()

    Handler.isolated = args.isolated
    handler = partial(Handler, directory=args.dir)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"serving {args.dir} on :{args.port} isolated={args.isolated}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
