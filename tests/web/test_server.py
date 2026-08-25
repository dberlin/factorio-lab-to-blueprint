"""The HTTP surface, driven over a real socket on an ephemeral port."""

from __future__ import annotations

import gzip
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from flab2bp import pipeline
from flab2bp.web.jobs import Builder, Options, Solve, run_build
from flab2bp.web.server import serve

URL = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"


def _decode(content_type: str, body: bytes) -> Any:
    return json.loads(body) if "json" in content_type else body.decode()


class Client:
    """Just enough of an HTTP client to poll a job."""

    def __init__(self, base: str) -> None:
        self.base = base

    def get(self, path: str) -> tuple[int, Any]:
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.status, _decode(r.headers.get("Content-Type", ""), r.read())

    def post(self, path: str, body: object) -> tuple[int, Any]:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, _decode(r.headers.get("Content-Type", ""), r.read())

    def failing(self, path: str, body: object = None, *, method: str = "GET") -> tuple[int, Any]:
        """A 4xx/5xx, decoded. ``urlopen`` raises on those rather than returning."""
        with pytest.raises(urllib.error.HTTPError) as caught:
            self.post(path, body) if method == "POST" else self.get(path)
        error = caught.value
        return error.code, _decode(error.headers.get("Content-Type", ""), error.read())

    def settled(self, job_id: str, *, timeout_s: float = 20.0) -> Any:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            _, snap = self.get(f"/api/build/{job_id}")
            if snap["state"] in ("done", "refused", "error"):
                return snap
            time.sleep(0.02)
        raise AssertionError(f"job {job_id} never finished")


@pytest.fixture
def start(tmp_path: Path) -> Iterator[Callable[..., Client]]:
    """Start a server on an ephemeral port, with an injectable solve function."""
    running: list[tuple[ThreadingHTTPServer, Builder, threading.Thread]] = []

    def go(solve: Solve = run_build) -> Client:
        httpd, builder = serve(port=0, dist=tmp_path, solve=solve)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        running.append((httpd, builder, thread))
        return Client(f"http://127.0.0.1:{httpd.server_address[1]}")

    try:
        yield go
    finally:
        for httpd, builder, thread in running:
            httpd.shutdown()
            httpd.server_close()
            builder.shutdown()
            thread.join(timeout=5)


def test_health_says_whether_the_front_end_is_built(start: Callable[..., Client]) -> None:
    status, body = start().get("/api/health")
    assert status == 200
    assert body == {"ok": True, "front_end_built": False}


def test_the_post_does_not_wait_for_the_solve(
    start: Callable[..., Client], small_build: pipeline.Build
) -> None:
    """The whole reason for the job model.

    The solve is held open, so a blocking POST could not return -- if this
    passes with a synchronous handler it is because the assertion is wrong, not
    because the server is fast.
    """
    release = threading.Event()

    def slow(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        release.wait(timeout=20.0)
        return small_build

    client = start(slow)
    started = time.monotonic()
    status, job = client.post("/api/build", {"url": URL})
    submit_s = time.monotonic() - started

    assert status == 202
    assert submit_s < 2.0
    assert job["state"] in ("queued", "running")

    # ...and the poll works while that solve is still held open.
    _, mid = client.get(f"/api/build/{job['id']}")
    assert mid["state"] in ("queued", "running")

    release.set()
    snap = client.settled(job["id"])
    assert snap["state"] == "done"
    assert snap["result"]["blueprint"] == small_build.blueprint


def test_a_refusal_comes_back_200_not_500(start: Callable[..., Client]) -> None:
    """A spec that cannot be laid out is an answer, and answers are not errors."""
    from flab2bp.layout.base import NoValidLayout

    def refuse(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        raise NoValidLayout("spine/a: too tall", spec_label="a", budget_s=1.0)

    client = start(refuse)
    _, job = client.post("/api/build", {"url": URL})
    snap = client.settled(job["id"])
    assert snap["state"] == "refused"
    assert snap["refusal"]["reasons"] == ["spine/a: too tall"]


def test_a_bad_body_is_400_with_a_reason(start: Callable[..., Client]) -> None:
    status, body = start().failing("/api/build", {"strategy": "best"}, method="POST")
    assert status == 400
    assert "url" in body["error"]


def test_a_body_that_is_not_json_is_400(start: Callable[..., Client]) -> None:
    client = start()
    request = urllib.request.Request(
        client.base + "/api/build", data=b"{not json", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 400


def test_polling_an_unknown_job_is_404(start: Callable[..., Client]) -> None:
    status, body = start().failing("/api/build/deadbeef")
    assert status == 404
    assert body["error"] == "no such job"


def test_an_unbuilt_front_end_says_so_rather_than_404ing(start: Callable[..., Client]) -> None:
    status, body = start().failing("/")
    assert status == 503
    assert "bun run build" in body


def test_static_files_are_served_and_unknown_paths_fall_back_to_index(
    start: Callable[..., Client], tmp_path: Path
) -> None:
    client = start()
    (tmp_path / "index.html").write_text("<title>flab2bp</title>")
    (tmp_path / "main.js").write_text("console.log(1)")

    assert client.get("/")[1] == "<title>flab2bp</title>"
    assert client.get("/main.js")[1] == "console.log(1)"
    # A single-page app answers an unknown route with the app.
    assert client.get("/some/route")[1] == "<title>flab2bp</title>"


def test_a_path_escaping_dist_gets_the_app_not_the_file(
    start: Callable[..., Client], tmp_path: Path
) -> None:
    client = start()
    (tmp_path / "index.html").write_text("<title>flab2bp</title>")
    (tmp_path.parent / "secret.txt").write_text("not yours")

    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/a/../../secret.txt"):
        assert "not yours" not in client.get(path)[1]


def test_an_unknown_api_endpoint_is_404(start: Callable[..., Client]) -> None:
    assert start().failing("/api/nope")[0] == 404


def test_the_inherited_proxy_still_validates_its_input(start: Callable[..., Client]) -> None:
    """Same contract as the viewer's proxy.ts, which this replaced."""
    client = start()
    assert client.failing("/api/fetch") == (400, "Missing url")
    assert client.failing("/api/fetch?url=file:///etc/passwd") == (
        400,
        "Only http/https are allowed",
    )


def test_a_large_text_response_is_gzipped_when_the_client_asks(
    start: Callable[..., Client], tmp_path: Path
) -> None:
    """1.2MB of JavaScript uncompressed is the difference this makes."""
    client = start()
    (tmp_path / "index.html").write_text("<title>flab2bp</title>")
    (tmp_path / "big.js").write_text("console.log('x');\n" * 5000)

    request = urllib.request.Request(
        client.base + "/big.js", headers={"Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read()
        assert response.headers.get("Content-Encoding") == "gzip"
        assert response.headers.get("Vary") == "Accept-Encoding"
        assert len(raw) < 5000  # 85KB of repetitive JS
        assert gzip.decompress(raw).decode() == "console.log('x');\n" * 5000

    # A client that did not ask still gets it uncompressed and intact.
    plain = client.get("/big.js")[1]
    assert plain == "console.log('x');\n" * 5000


def test_the_icon_atlas_is_not_gzipped(start: Callable[..., Client], tmp_path: Path) -> None:
    """A PNG is already compressed; gzipping it spends CPU to add bytes."""
    client = start()
    (tmp_path / "index.html").write_text("<title>flab2bp</title>")
    (tmp_path / "atlas.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20)

    request = urllib.request.Request(
        client.base + "/atlas.png", headers={"Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers.get("Content-Encoding") is None


def test_a_small_json_poll_is_not_gzipped(start: Callable[..., Client]) -> None:
    """The header would cost more than the saving on a few hundred bytes."""
    client = start()
    request = urllib.request.Request(
        client.base + "/api/health", headers={"Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers.get("Content-Encoding") is None
        assert json.loads(response.read())["ok"] is True
