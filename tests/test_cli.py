"""Tests for :mod:`flab2bp.cli`'s report block.

Model: :mod:`tests.test_pipeline_cli_strategy`'s ``band_build`` fixture -- one
real, module-scoped build shared by every test here, so the whole module costs
one solve rather than one per test.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from flab2bp import cli, pipeline
from flab2bp.layout.observe import SearchEvent, SearchPhase
from flab2bp.rates.candidates import CandidatePolicy
from flab2bp.web.trace import frame_json

#: The reported deuteron-fuel-rod URL (see ``tests/test_pipeline.py``'s
#: ``DEUTERON_URL`` for the fuller story). At the researched Mk.III belt tier
#: it belts hydrogen in at 40 items/s on exactly two entry lanes -- fast
#: (about 2 s at the default budget), so no budget override is needed here.
DEUTERON_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNzD0LwjAYBOB.k-GmJGKd3uWCuokVFLNaO2gthfqBOry"
    ".XSrGdHvu4K6TCOet6YQVnLWAG3weOWbP4O2.JybJOxSjqU--ZbKCnya.8pIc3n.hjeKr06GWYPr6KWtEHNHgDq7"
    "ALbgHG-UFvCIsNCwRSg0b07a9RKXOtTQPce4DLu01vA__&v=11"
)


@pytest.fixture(scope="module")
def deuteron_build() -> pipeline.Build:
    return pipeline.build(
        DEUTERON_URL,
        strategy="sequence-pair",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    )


def test_cli_reports_how_many_entry_lanes_an_item_needs(
    deuteron_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mk.III fits 40/s hydrogen on exactly two lanes of a 30/s belt.

    ``super-magnetic-ring`` is also belted in on two lanes here, for a reason
    unrelated to rate (two assembler strips, each wanting its own feed), so
    the report carries its own ``entry lanes:`` line too -- this test filters
    by looking for the hydrogen line specifically rather than asserting the
    whole report.
    """
    assert deuteron_build.report.ok
    cli._report(deuteron_build, verbose=False)
    report = capsys.readouterr().err
    assert "  entry lanes: hydrogen 2 (needs 2 at 30/s)" in report


def test_cli_always_reports_stack_one_without_a_url_suffix(
    deuteron_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unstacked bus is still an explicit reporting contract, but ``ist=1``
    needs no URL provenance suffix."""
    cli._report(deuteron_build, verbose=False)
    line = next(
        line for line in capsys.readouterr().err.splitlines() if line.strip().startswith("belts:")
    )
    assert line.endswith("; stack 1; 0 piler(s)")
    assert "URL ist=" not in line


def test_cli_names_the_stack_when_the_url_carries_one(
    deuteron_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`ist` is the player's own setting, so the report says it back with the
    URL field named -- a reader who did not expect stacked belts has to be able
    to find where the number came from."""
    stacked = dataclasses.replace(
        deuteron_build, spec=deuteron_build.spec.model_copy(update={"belt_stack": 2})
    )
    cli._report(stacked, verbose=False)
    line = next(
        line for line in capsys.readouterr().err.splitlines() if line.strip().startswith("belts:")
    )
    assert "stack 2 (URL ist=2)" in line


def test_cli_reports_an_infeasible_spec_as_a_refusal_not_a_crash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``iron-ore`` is mining-only -- see ``tests/test_pipeline.py``'s
    ``NO_BUILDABLE_RECIPE_URL`` for why this has no crafting column at all.

    ``rates.solve`` raises a bare ``InfeasibleError`` for it, which today
    propagates out of ``main`` uncaught rather than taking the same exit-3
    refusal path a ``NoValidLayout`` already gets.
    """
    exit_code = cli.main(
        ["https://factoriolab.github.io/dsp/flow?o=iron-ore*60&v=11", "--budget", "1"]
    )
    assert exit_code == 3
    err = capsys.readouterr().err
    assert "iron-ore" in err
    assert "Traceback" not in err


def test_trace_jsonl_defaults_to_none() -> None:
    args = cli.build_parser().parse_args(["https://example/x"])
    assert args.trace_jsonl is None


def test_trace_jsonl_parses_to_a_path() -> None:
    args = cli.build_parser().parse_args(["https://example/x", "--trace-jsonl", "trace.jsonl"])
    assert args.trace_jsonl == Path("trace.jsonl")


def test_trace_jsonl_with_race_is_refused_rather_than_silently_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Task 13 fix round 1: this combination used to write a valid-looking,
    permanently empty trace file (no `trace_queue` was ever threaded through
    to a raced arm). It must now fail loudly at argument time, before any
    solve, rather than produce output that reads as "the search found
    nothing".
    """
    monkeypatch.setattr(
        pipeline,
        "build",
        lambda *args, **kwargs: pytest.fail("a raced+traced build must never start"),
    )
    trace_path = tmp_path / "trace.jsonl"

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["https://example/x", "--race", "--trace-jsonl", str(trace_path)])

    assert exc_info.value.code == 2
    assert not trace_path.exists()


def test_without_the_flag_no_observer_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_build(*_args: object, **kwargs: object) -> pipeline.Build:
        seen["search_observer"] = kwargs.get("search_observer")
        # KeyError short-circuits before a real solve; `main` already turns
        # one into exit code 2 (cli.py:381-383), so no new exception path
        # is needed here.
        raise KeyError("short-circuit before a real solve")

    monkeypatch.setattr(pipeline, "build", fake_build)
    exit_code = cli.main(["https://example/x"])
    assert exit_code == 2
    assert seen["search_observer"] is None


def test_main_writes_one_json_object_per_search_event_per_line(
    deuteron_build: pipeline.Build,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_build(*_args: object, **kwargs: object) -> pipeline.Build:
        # The same contract every other call site gets: due() gates, note()
        # records. Exercising it here is what proves the CLI and the web
        # path share one observer and one frame schema (design §7.4).
        observer = kwargs["search_observer"]
        assert observer is not None
        assert observer.due(SearchPhase.INCUMBENT) is True
        observer.note(
            SearchEvent(
                strategy="freeform",
                candidate="c",
                phase=SearchPhase.INCUMBENT,
                incumbent=True,
            )
        )
        return deuteron_build

    monkeypatch.setattr(pipeline, "build", fake_build)
    trace_path = tmp_path / "trace.jsonl"
    exit_code = cli.main(["https://example/x", "--trace-jsonl", str(trace_path)])

    assert exit_code == 0
    lines = trace_path.read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["phase"] == "incumbent"
    assert row["strategy"] == "freeform"
    assert "blueprint" not in row  # N1: not even the CLI's own copy is pasteable.


def test_trace_jsonl_line_matches_frame_json_for_the_same_event(
    deuteron_build: pipeline.Build,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pins design §7.4's "one observer, one frame schema, two transports":
    the CLI's JSONL line and ``web.trace.frame_json``'s own projection of the
    identical event must be equal as parsed objects, not merely share a few
    fields. Both transports call ``frame_json`` directly -- this asserts there
    is no CLI-side post-processing layered on top of it, by feeding the CLI's
    own emitted ``seq``/``t`` straight back into a direct ``frame_json`` call
    on the SAME event object and comparing the two dicts for equality. The
    next task's overhead gate captures frames through ``--trace-jsonl``; if
    the two transports ever drift, this is what catches it.
    """
    event = SearchEvent(
        strategy="freeform",
        candidate="c",
        phase=SearchPhase.INCUMBENT,
        incumbent=True,
    )

    def fake_build(*_args: object, **kwargs: object) -> pipeline.Build:
        observer = kwargs["search_observer"]
        assert observer is not None
        observer.note(event)
        return deuteron_build

    monkeypatch.setattr(pipeline, "build", fake_build)
    trace_path = tmp_path / "trace.jsonl"
    exit_code = cli.main(["https://example/x", "--trace-jsonl", str(trace_path)])
    assert exit_code == 0

    row = json.loads(trace_path.read_text().splitlines()[0])
    assert row == frame_json(row["seq"], row["t"], event)


def test_a_failing_close_does_not_change_mains_exit_code(
    deuteron_build: pipeline.Build,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """R3: a debugging view must never kill a build. The trace file's own
    ``close()`` can raise (disk filled during the build, permission revoked,
    an NFS hiccup) AFTER the build has already succeeded -- that failure must
    not propagate out of ``main`` and turn a finished blueprint into a crash.
    """
    trace_path = tmp_path / "trace.jsonl"
    real_open = Path.open

    def flaky_open(self: Path, *args: object, **kwargs: object) -> object:
        handle = real_open(self, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        # Only the CLI's own write-mode open on the trace path is wrapped:
        # `main` itself later reads this same file back (`read_text`, below)
        # through the unpatched, real read-mode open, so a plain `close()`
        # keeps working for everything except the one write handle `main`
        # closes in its `finally`.
        if self != trace_path or mode != "w":
            return handle

        class _RaisingClose:
            def write(self, data: str) -> int:
                return handle.write(data)

            def close(self) -> None:
                handle.close()
                raise OSError("disk full")

        return _RaisingClose()

    monkeypatch.setattr(Path, "open", flaky_open)

    def fake_build(*_args: object, **kwargs: object) -> pipeline.Build:
        observer = kwargs["search_observer"]
        assert observer is not None
        observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT))
        return deuteron_build

    monkeypatch.setattr(pipeline, "build", fake_build)
    exit_code = cli.main(["https://example/x", "--trace-jsonl", str(trace_path)])

    assert exit_code == 0
    assert trace_path.read_text().splitlines()  # the write before the failed close survived


def test_a_writer_thread_write_failure_does_not_change_mains_exit_code_or_skip_the_close(
    deuteron_build: pipeline.Build,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Re-review round, I1 regression: before this fix, a write failure
    (disk full, a broken pipe, an NFS hiccup) inside the CLI's trace writer
    thread was unguarded. `_run`'s own drain could die silently, but
    `stop()`'s FINAL drain runs on the MAIN thread once the writer thread is
    gone -- so the same error resurfaced there, propagated out of
    `cli_main`'s `finally` BEFORE `trace_file.close()`, and killed a build
    that had already succeeded. That is the identical "raise inside a
    `finally` skips the resource release" shape Critical 1 fixed in
    `jobs.py`, reintroduced here by the same fix wave -- and a real
    regression, since before I1 existed `SampledObserver.note` swallowed
    sink exceptions and this same disk error was a harmless no-op.

    Model: `test_a_failing_close_does_not_change_mains_exit_code` above, but
    the fake file's `write()` itself raises rather than only its `close()`.
    """
    trace_path = tmp_path / "trace.jsonl"
    closed: list[bool] = []
    real_open = Path.open

    def flaky_open(self: Path, *args: object, **kwargs: object) -> object:
        mode = args[0] if args else kwargs.get("mode", "r")
        if self != trace_path or mode != "w":
            return real_open(self, *args, **kwargs)

        class _RaisingWrite:
            def write(self, data: str) -> int:
                raise OSError("disk full")

            def close(self) -> None:
                closed.append(True)

        return _RaisingWrite()

    monkeypatch.setattr(Path, "open", flaky_open)

    def fake_build(*_args: object, **kwargs: object) -> pipeline.Build:
        observer = kwargs["search_observer"]
        assert observer is not None
        observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT))
        return deuteron_build

    monkeypatch.setattr(pipeline, "build", fake_build)
    exit_code = cli.main(["https://example/x", "--trace-jsonl", str(trace_path)])

    assert exit_code == 0
    assert closed == [True]  # the file was still closed despite the write failure
