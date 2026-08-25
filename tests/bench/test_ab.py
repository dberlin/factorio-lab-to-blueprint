"""The guards that keep the A/B comparison honest.

Every test here corresponds to a specific way the earlier comparison in this
project reached a wrong answer -- "A wins, geometric mean 1.359", produced by
scoring layouts the validator had rejected.  Invalid layouts are systematically
SMALLER (an unrouted net is a belt run that does not exist), so the failure mode
is not random noise: it reliably crowns whichever strategy is more broken.

None of these run CP-SAT.  The engine is dependency-injected at ``sample_once``
precisely so the arithmetic can be pinned in milliseconds; the full suite has to
stay at ~21s and a bake-off belongs behind a script entry point.
"""

from __future__ import annotations

import argparse
import mmap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from runpy import run_path
from typing import cast

import pytest

from flab2bp.bench.ab import (
    Cell,
    Comparison,
    CrossSummary,
    Outcome,
    Pair,
    RunMeta,
    Sample,
    Trial,
    budget_flip,
    compare,
    cross_verdict,
    crossvalidate_samples,
    isolated_attempt,
    render_markdown,
    render_text,
    sample_once,
    samples_from_json,
    ship,
    to_json,
    trials_from,
)
from flab2bp.bench.crossvalidate import CrossCheck
from flab2bp.bench.types import Metrics
from flab2bp.layout.base import LayoutStrategy, NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.freeform import FreeformLayout


def _metrics(area: int, *, belts: int = 0, direct: int = 0) -> Metrics:
    return Metrics(
        area=area,
        used_tiles=area // 2,
        width=area,
        height=1,
        machines=2,
        belt_tiles=belts,
        sorters=0,
        direct_inserts=direct,
        towers=0,
        altitude_levels=1,
    )


def _sample(
    outcome: Outcome,
    *,
    url: str = "u",
    strategy: str = "spine",
    area: int | None = None,
    candidate: str = "c",
    trial: int = 0,
    budget: float = 1.0,
    detail: str = "",
    blueprint: str = "",
    buildings: int = 0,
) -> Sample:
    return Sample(
        url_id=url,
        candidate=candidate,
        strategy=strategy,
        budget_s=budget,
        trial=trial,
        outcome=outcome,
        seconds=0.5,
        metrics=_metrics(area) if area is not None else None,
        buildings=buildings,
        blueprint=blueprint,
        detail=detail,
    )


def _trial(
    outcome: Outcome,
    *,
    url: str = "u",
    strategy: str = "spine",
    area: int | None = None,
    trial: int = 0,
    budget: float = 1.0,
    belts: int = 0,
    direct: int = 0,
    buildings: int = 0,
    detail: str = "",
) -> Trial:
    return Trial(
        url_id=url,
        strategy=strategy,
        budget_s=budget,
        trial=trial,
        outcome=outcome,
        candidate="c",
        seconds=0.5,
        metrics=_metrics(area, belts=belts, direct=direct) if area is not None else None,
        buildings=buildings,
        detail=detail,
    )


# --------------------------------------------------------------------------
# Guard 1: a rejected layout cannot hold an area, structurally.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome", [Outcome.INVALID, Outcome.REFUSED, Outcome.ERROR, Outcome.CROSSFAIL]
)
def test_a_rejected_sample_cannot_carry_an_area(outcome: Outcome) -> None:
    """The exact bug that produced the 1.359 artifact, made unrepresentable.

    Not a convention or a filter that a later refactor could drop: there is no
    object in the system pairing a rejected layout with an area, so no aggregate
    can accidentally consume one.
    """
    with pytest.raises(ValueError, match="systematically smaller"):
        Sample("u", "c", "spine", 1.0, 0, outcome, 0.5, metrics=_metrics(1))


def test_a_valid_sample_must_carry_measured_geometry() -> None:
    with pytest.raises(ValueError, match="must carry measured geometry"):
        Sample("u", "c", "spine", 1.0, 0, Outcome.VALID, 0.5)


def test_only_a_valid_sample_may_carry_a_blueprint() -> None:
    with pytest.raises(ValueError, match="blueprint"):
        Sample("u", "c", "spine", 1.0, 0, Outcome.INVALID, 0.5, blueprint="H4sI")


def test_demotion_drops_the_area_with_the_verdict() -> None:
    """Re-grading and un-counting are one step, so neither can be forgotten."""
    valid = _sample(Outcome.VALID, area=100, blueprint="H4sI", buildings=7)
    demoted = valid.demoted(Outcome.CROSSFAIL, "MD5F hash invalid")
    assert demoted.outcome is Outcome.CROSSFAIL
    assert demoted.area is None
    assert demoted.buildings == 0
    assert demoted.blueprint == ""
    assert "MD5F" in demoted.detail


# --------------------------------------------------------------------------
# Guard 2: the four failure modes stay apart.
# --------------------------------------------------------------------------


def test_refused_invalid_and_error_are_counted_separately() -> None:
    """"B refused" and "B blew up" call for different investigations."""
    cell = Cell(
        "u",
        "freeform",
        1.0,
        (
            _trial(Outcome.REFUSED, strategy="freeform"),
            _trial(Outcome.INVALID, strategy="freeform", trial=1),
            _trial(Outcome.ERROR, strategy="freeform", trial=2),
            _trial(Outcome.CROSSFAIL, strategy="freeform", trial=3),
        ),
    )
    assert cell.count(Outcome.REFUSED) == 1
    assert cell.count(Outcome.INVALID) == 1
    assert cell.count(Outcome.ERROR) == 1
    assert cell.count(Outcome.CROSSFAIL) == 1
    assert cell.median_area is None
    assert not cell.covered
    for word in ("refused", "invalid", "error", "crossfail"):
        assert word in cell.why


def test_a_crash_is_never_hidden_behind_a_refusal() -> None:
    """A candidate sweep that crashed once reports the crash, not the refusal.

    A refusal is a property of the instance; a crash is a bug in us. Reporting
    whichever happened to be last would let a real defect hide behind the
    structural gap that is already known about.
    """
    trial = ship(
        [
            _sample(Outcome.REFUSED, candidate="a", detail="no routable pack"),
            _sample(Outcome.ERROR, candidate="b", detail="KeyError: 2020"),
        ]
    )
    assert trial.outcome is Outcome.ERROR
    assert "KeyError" in trial.detail


def test_ship_mirrors_the_pipeline_and_keeps_the_smallest_valid_candidate() -> None:
    trial = ship(
        [
            _sample(Outcome.VALID, candidate="prolif", area=900),
            _sample(Outcome.INVALID, candidate="free", detail="flow.lane_sourced"),
            _sample(Outcome.VALID, candidate="none", area=700),
        ]
    )
    assert trial.outcome is Outcome.VALID
    assert trial.candidate == "none"
    assert trial.area == 700
    # Wall clock is what a user waits for: the whole candidate sweep, not the
    # winner alone.
    assert trial.seconds == pytest.approx(1.5)


def test_a_tiny_invalid_candidate_never_beats_a_larger_valid_one() -> None:
    """The artifact in miniature: area 10 that the validator rejected loses."""
    trial = ship(
        [
            _sample(Outcome.INVALID, candidate="broken", detail="flow.unrouted"),
            _sample(Outcome.VALID, candidate="whole", area=5000),
        ]
    )
    assert trial.area == 5000


# --------------------------------------------------------------------------
# Guard 3: no aggregate without its denominator.
# --------------------------------------------------------------------------


def _comparison(trials: list[Trial], urls: list[str]) -> Comparison:
    return compare(trials, a_name="spine", b_name="freeform", budget_s=1.0, url_ids=urls)


def test_coverage_is_reported_before_density_with_both_denominators() -> None:
    trials = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000),
        _trial(Outcome.VALID, url="b", strategy="spine", area=1000),
        _trial(Outcome.VALID, url="c", strategy="spine", area=1000),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=800),
        _trial(Outcome.INVALID, url="b", strategy="freeform", detail="flow.lane_sourced"),
        _trial(Outcome.REFUSED, url="c", strategy="freeform", detail="no routable pack"),
    ]
    c = _comparison(trials, ["a", "b", "c"])
    assert (c.a_covered, c.b_covered, c.n_urls) == (3, 1, 3)
    assert c.n_pairs == 1

    head = c.headline()
    assert head[0].startswith("COVERAGE")
    assert "3 URLs attempted" in head[0]
    assert "valid on 3/3 URLs" in head[1]
    assert "valid on 1/3 URLs" in head[2]
    density = next(line for line in head if line.startswith("DENSITY"))
    # The ratio must never appear without the subset it describes.
    assert "1/3 URLs where BOTH shipped" in density
    assert any("Coverage outranks" in line for line in head)
    assert any("not a corpus-wide claim" in line for line in head)


def test_no_shared_success_means_no_ratio_at_all() -> None:
    """Not 1.0. "They tied" and "nothing could be compared" are different claims."""
    trials = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000),
        _trial(Outcome.REFUSED, url="a", strategy="freeform"),
    ]
    c = _comparison(trials, ["a"])
    assert c.geo_mean is None
    assert c.n_pairs == 0
    assert any("no comparison possible" in line for line in c.headline())


def test_a_url_that_never_ran_still_counts_in_the_denominator() -> None:
    """A spec that would not even resolve must not vanish from the corpus size.

    Dropping it would make a broken URL look like a URL nobody ran, and shrink
    the denominator for both strategies silently.
    """
    c = _comparison([_trial(Outcome.VALID, url="a", area=10)], ["a", "ghost"])
    assert c.n_urls == 2
    assert c.a_covered == 1
    ghost = next(p for p in c.pairs if p.url_id == "ghost")
    assert ghost.a.n == 0 and not ghost.a.covered


def test_reliability_is_distinct_from_coverage() -> None:
    """Shipping 1 run in 3 is not the same as shipping every run."""
    trials = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=100, trial=0),
        _trial(Outcome.INVALID, url="a", strategy="spine", trial=1),
        _trial(Outcome.INVALID, url="a", strategy="spine", trial=2),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=100, trial=0),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=100, trial=1),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=100, trial=2),
    ]
    c = _comparison(trials, ["a"])
    assert (c.a_covered, c.a_always) == (1, 0)
    assert (c.b_covered, c.b_always) == (1, 1)
    assert "1/1 URLs (0/1 on every repeat)" in c.headline()[1]


# --------------------------------------------------------------------------
# Guard 4: nondeterminism is measured, not averaged away.
# --------------------------------------------------------------------------


def _cell(name: str, areas: list[int]) -> Cell:
    return Cell(
        "u",
        name,
        1.0,
        tuple(
            _trial(Outcome.VALID, strategy=name, area=x, trial=i)
            for i, x in enumerate(areas)
        ),
    )


def _spread_pair(a: list[int], b: list[int]) -> Pair:
    return Pair("u", 1.0, _cell("spine", a), _cell("freeform", b))


def test_one_sample_per_cell_can_never_be_declared_separated() -> None:
    """The correct answer to a single multi-worker CP-SAT run is "don't know"."""
    pair = _spread_pair([1000], [500])
    assert pair.ratio == pytest.approx(0.5)
    assert not pair.separated


def test_overlapping_spreads_are_not_a_verdict() -> None:
    """Medians say B wins by 5%; the runs say the solver just shrugged."""
    pair = _spread_pair([1000, 1100, 1200], [950, 1050, 1250])
    assert pair.ratio is not None and pair.ratio < 1.0
    assert not pair.separated


def test_a_gap_wider_than_the_spread_is_separated() -> None:
    pair = _spread_pair([1000, 1010, 1020], [500, 505, 510])
    assert pair.separated
    bounds = pair.bounds
    assert bounds is not None and bounds[1] < 1.0


def test_a_ratio_nothing_supports_says_so_as_loudly_as_the_ratio() -> None:
    """One repeat still prints a number, so it must also print its own warning."""
    trials = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=600),
    ]
    head = _comparison(trials, ["a"]).headline()
    assert any("geometric mean B/A = 0.600" in line for line in head)
    assert any("NOTHING is separated from noise" in line for line in head)
    assert any("that 1 URL" in line for line in head)


def test_a_repeatable_exact_tie_is_a_tie_not_a_missing_verdict() -> None:
    """Zero spread on both sides means the ratio is exact, including at 1.0."""
    pair = _spread_pair([100, 100], [100, 100])
    assert pair.separated
    trials = [
        _trial(Outcome.VALID, url="a", strategy=name, area=100, trial=i)
        for name in ("spine", "freeform")
        for i in (0, 1)
    ]
    assert _comparison(trials, ["a"]).wins == (0, 0, 1)


def test_an_effect_inside_the_noise_floor_is_called_out() -> None:
    trials = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000, trial=0),
        _trial(Outcome.VALID, url="a", strategy="spine", area=1300, trial=1),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=980, trial=0),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=1280, trial=1),
    ]
    c = _comparison(trials, ["a"])
    assert c.wins == (0, 0, 0)  # nothing separated, so nothing is a win
    assert any("does NOT clear" in line for line in c.headline())


def test_wins_are_counted_only_over_separated_pairs() -> None:
    trials = [
        # a: B clearly smaller, tight spreads -> separated, a B win
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000, trial=0),
        _trial(Outcome.VALID, url="a", strategy="spine", area=1005, trial=1),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=600, trial=0),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=605, trial=1),
        # b: medians differ but spreads overlap -> no verdict
        _trial(Outcome.VALID, url="b", strategy="spine", area=1000, trial=0),
        _trial(Outcome.VALID, url="b", strategy="spine", area=1400, trial=1),
        _trial(Outcome.VALID, url="b", strategy="freeform", area=900, trial=0),
        _trial(Outcome.VALID, url="b", strategy="freeform", area=1500, trial=1),
    ]
    c = _comparison(trials, ["a", "b"])
    assert c.n_pairs == 2
    assert len(c.separated) == 1
    assert c.wins == (0, 1, 0)


# --------------------------------------------------------------------------
# Guard 5: the time budget is a confound, so a flip is the headline.
# --------------------------------------------------------------------------


def test_a_winner_that_flips_with_the_budget_is_reported_as_such() -> None:
    fast = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000, budget=1.0),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=600, budget=1.0),
    ]
    slow = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=500, budget=10.0),
        _trial(Outcome.VALID, url="a", strategy="freeform", area=900, budget=10.0),
    ]
    comparisons = [
        compare(fast + slow, a_name="spine", b_name="freeform", budget_s=1.0, url_ids=["a"]),
        compare(fast + slow, a_name="spine", b_name="freeform", budget_s=10.0, url_ids=["a"]),
    ]
    message = budget_flip(comparisons)
    assert "FLIPS" in message
    assert "1s -> freeform" in message and "10s -> spine" in message


def test_a_stable_winner_says_so() -> None:
    trials = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000, budget=b)
        for b in (1.0, 10.0)
    ] + [
        _trial(Outcome.VALID, url="a", strategy="freeform", area=600, budget=b)
        for b in (1.0, 10.0)
    ]
    comparisons = [
        compare(trials, a_name="spine", b_name="freeform", budget_s=b, url_ids=["a"])
        for b in (1.0, 10.0)
    ]
    assert "stable across budgets" in budget_flip(comparisons)


# --------------------------------------------------------------------------
# Guard 6: cross-validation against the game's own format.
# --------------------------------------------------------------------------


def test_a_missing_toolchain_reads_as_skipped_not_as_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero failures with the decoder absent is not "everything passed"."""
    monkeypatch.setattr("flab2bp.bench.ab.bun_available", lambda: False)
    samples = [_sample(Outcome.VALID, area=10, blueprint="H4sI", buildings=3)]
    out, summary = crossvalidate_samples(samples)
    assert out == samples
    assert not summary.available
    assert "SKIPPED" in summary.summary()
    assert "bun" in summary.reason


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        (CrossCheck(ok=False, error="bad base64"), "decode failed"),
        (CrossCheck(ok=True, hash_valid=False, buildings=3), "MD5F hash invalid"),
        (CrossCheck(ok=True, hash_valid=True, buildings=2), "building count 2 != placed 3"),
        (CrossCheck(ok=True, hash_valid=True, buildings=3), ""),
    ],
)
def test_cross_verdict_rejects_what_the_game_format_would(
    check: CrossCheck, expected: str
) -> None:
    """A building count mismatch is invisible to our own validator.

    We validate the ``Placement``; the decoder validates the bytes. Only the
    second one notices an encoder that dropped a building.
    """
    verdict = cross_verdict(check, _sample(Outcome.VALID, area=10, buildings=3))
    assert expected in verdict
    assert bool(verdict) == bool(expected)


def test_a_blueprint_the_decoder_rejects_stops_contributing_an_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("flab2bp.bench.ab.bun_available", lambda: True)
    monkeypatch.setattr("flab2bp.bench.ab.viewer_path", lambda: "/somewhere")
    monkeypatch.setattr(
        "flab2bp.bench.ab.crossvalidate",
        lambda blueprints, strict=False: [
            CrossCheck(ok=True, hash_valid=True, buildings=3),
            CrossCheck(ok=True, hash_valid=False, buildings=3),
        ],
    )
    good = _sample(Outcome.VALID, url="a", area=1000, blueprint="A", buildings=3)
    bad = _sample(Outcome.VALID, url="b", area=10, blueprint="B", buildings=3)
    out, summary = crossvalidate_samples([good, bad])

    assert summary.available and summary.checked == 2 and summary.passed == 1
    assert len(summary.demoted) == 1 and "b/" in summary.demoted[0]
    kept, dropped = out
    assert kept.outcome is Outcome.VALID and kept.area == 1000
    assert dropped.outcome is Outcome.CROSSFAIL and dropped.area is None

    # And the demotion has to reach the aggregate, not just the sample.
    c = compare(
        trials_from(out), a_name="spine", b_name="freeform", budget_s=1.0, url_ids=["a", "b"]
    )
    assert c.a_covered == 1


# --------------------------------------------------------------------------
# sample_once: grading one attempt.
# --------------------------------------------------------------------------


def _placement() -> Placement:
    return Placement(buildings=(PlacedBuilding(item_id=2304, model_index=66, x=0, y=0),))

@dataclass(frozen=True)
class _MemoryLayout:
    megabytes: int

    def __call__(self) -> Placement:
        payload = bytearray(self.megabytes * 1024 * 1024)
        # Commit every virtual page so peak RSS observes the requested allocation.
        for offset in range(0, len(payload), mmap.PAGESIZE):
            payload[offset] = 1
        placement = _placement()
        assert payload
        return placement


def test_isolated_attempt_peak_rss_is_not_contaminated_by_a_prior_attempt() -> None:
    large_megabytes = 96
    small_megabytes = 1
    large = isolated_attempt(_MemoryLayout(large_megabytes))
    small = isolated_attempt(_MemoryLayout(small_megabytes))

    minimum_resident_delta = (large_megabytes - small_megabytes) / 2
    assert large.peak_rss_mb > small.peak_rss_mb + minimum_resident_delta




def _grade(
    lay_out: object, judge: object = None, encode: object = None
) -> Sample:
    return sample_once(
        url_id="u",
        candidate="c",
        strategy="spine",
        budget_s=1.0,
        trial=0,
        lay_out=lay_out,  # type: ignore[arg-type]
        judge=judge or (lambda p: (True, ())),  # type: ignore[arg-type]
        encode=encode or (lambda p: "H4sI"),  # type: ignore[arg-type]
    )


def test_a_refusal_is_graded_as_a_result_not_a_crash() -> None:
    def refuse() -> Placement:
        raise NoValidLayout("no routable pack", spec_label="x", budget_s=1.0)

    s = _grade(refuse)
    assert s.outcome is Outcome.REFUSED
    assert s.detail == "no routable pack"
    assert s.area is None


def test_a_crash_is_graded_as_a_crash() -> None:
    def boom() -> Placement:
        raise KeyError(2020)

    s = _grade(boom)
    assert s.outcome is Outcome.ERROR
    assert "KeyError" in s.detail


def test_a_rejected_placement_records_which_checks_failed() -> None:
    s = _grade(_placement, judge=lambda p: (False, ("flow.lane_sourced", "geom.overlap")))
    assert s.outcome is Outcome.INVALID
    assert s.detail == "flow.lane_sourced,geom.overlap"
    assert s.area is None


def test_an_unencodable_placement_is_not_a_win() -> None:
    def bad_encode(p: Placement) -> str:
        raise ValueError("unknown item 9999")

    s = _grade(_placement, encode=bad_encode)
    assert s.outcome is Outcome.CROSSFAIL
    assert "encode" in s.detail
    assert s.area is None


def test_an_accepted_placement_is_measured_not_asked() -> None:
    """Geometry comes from the buildings, never from ``Placement.stats``."""

    def lying_placement() -> Placement:
        return Placement(
            buildings=(PlacedBuilding(item_id=2304, model_index=66, x=0, y=0, width=4, height=4),),
            stats={"area": 1.0},
        )

    s = _grade(lying_placement)
    assert s.outcome is Outcome.VALID
    assert s.area == 16
    assert s.buildings == 1
    assert s.blueprint == "H4sI"
    assert s.cpu_seconds is not None and s.cpu_seconds >= 0
    assert s.peak_rss_mb is not None and s.peak_rss_mb > 0


# --------------------------------------------------------------------------
# Rendering keeps the guards visible.
# --------------------------------------------------------------------------


def test_a_covered_url_still_reports_a_mostly_broken_candidate_frontier() -> None:
    """3/3 trials shipped, but only one of three candidates ever laid out.

    The pipeline emits a frontier precisely so it has alternatives; a URL one
    broken candidate away from refusing must not read as healthy.
    """
    trial = ship(
        [
            _sample(Outcome.VALID, candidate="a", area=99),
            _sample(Outcome.INVALID, candidate="b", detail="flow.lane_sourced"),
            _sample(Outcome.INVALID, candidate="c", detail="flow.lane_sourced"),
        ]
    )
    assert (trial.candidates_valid, trial.candidates_total) == (1, 3)
    cell = Cell("u", "spine", 1.0, (trial,))
    assert cell.always
    assert cell.candidate_health == "only 1/3 candidates laid out"
    assert "only 1/3 candidates laid out" in "\n".join(
        render_text(_comparison([trial], ["u"]))
    )


def test_the_table_names_the_failure_kind_per_strategy() -> None:
    trials = [
        _trial(Outcome.VALID, url="a", strategy="spine", area=1000),
        _trial(Outcome.INVALID, url="a", strategy="freeform", detail="flow.lane_sourced"),
    ]
    text = "\n".join(render_text(_comparison(trials, ["a"])))
    assert "freeform: invalid x1 (flow.lane_sourced)" in text
    assert "COVERAGE" in text


def test_composition_is_reported_so_the_reason_for_a_win_is_visible() -> None:
    trials = [
        _trial(
            Outcome.VALID, url="a", strategy="spine", area=1000,
            belts=800, direct=0, buildings=900,
        ),
        _trial(
            Outcome.VALID, url="a", strategy="freeform", area=900,
            belts=300, direct=11, buildings=420,
        ),
    ]
    text = "\n".join(render_text(_comparison(trials, ["a"])))
    assert "Composition" in text
    for token in ("800", "300", "11", "420"):
        assert token in text


def test_the_markdown_report_carries_the_method_and_the_skip_reason() -> None:
    meta = RunMeta(("small",), (1.0,), repeat=3, candidates=3, power=False, urls=1)
    cross = CrossSummary(available=False, reason="bun not on PATH")
    doc = render_markdown([_comparison([], ["a"])], meta, cross)
    assert "cross-validation SKIPPED" in doc
    assert "nondeterministic by design" in doc
    assert "repeat=3" in doc


def test_the_json_dump_never_carries_an_area_for_a_failure() -> None:
    samples = [
        _sample(Outcome.VALID, url="a", area=1000, blueprint="H4sI", buildings=3),
        _sample(Outcome.INVALID, url="b", detail="flow.lane_sourced"),
    ]
    meta = RunMeta(("small",), (1.0,), repeat=1, candidates=1, power=False, urls=2)
    dumped = to_json(samples, meta, CrossSummary(available=True, checked=1, passed=1))
    rows = dumped["samples"]
    assert isinstance(rows, list)
    assert rows[0]["area"] == 1000
    assert rows[1]["area"] is None
    assert rows[1]["outcome"] == "invalid"


def test_cpu_and_peak_rss_survive_json_and_shipping() -> None:
    sample = Sample(
        url_id="u",
        candidate="c",
        strategy="freeform",
        budget_s=1.0,
        trial=0,
        outcome=Outcome.VALID,
        seconds=0.5,
        metrics=_metrics(100),
        buildings=1,
        cpu_seconds=0.25,
        peak_rss_mb=123.5,
    )
    meta = RunMeta(
        ("small",),
        (1.0,),
        repeat=1,
        candidates=1,
        power=False,
        urls=1,
        a_name="freeform",
        b_name="sequence-pair",
    )

    dumped = to_json([sample], meta, CrossSummary(available=False, reason="test"))
    loaded = samples_from_json(dumped)
    trial = trials_from(loaded)[0]

    dumped_meta = dumped["meta"]
    dumped_rows = dumped["samples"]
    assert isinstance(dumped_meta, dict)
    assert isinstance(dumped_rows, list)
    assert dumped_meta["a"] == "freeform"
    assert dumped_meta["b"] == "sequence-pair"
    assert dumped_rows[0]["cpu_seconds"] == 0.25
    assert dumped_rows[0]["peak_rss_mb"] == 123.5
    assert trial.cpu_seconds == pytest.approx(0.25)
    assert trial.peak_rss_mb == pytest.approx(123.5)


def test_old_json_without_resource_metrics_still_parses() -> None:
    dumped = to_json(
        [_sample(Outcome.VALID, area=100, buildings=1)],
        RunMeta(("small",), (1.0,), repeat=1, candidates=1, power=False, urls=1),
        CrossSummary(available=False, reason="test"),
    )
    rows = dumped["samples"]
    assert isinstance(rows, list)
    row = rows[0]
    del row["cpu_seconds"]
    del row["peak_rss_mb"]

    loaded = samples_from_json(dumped)

    assert loaded[0].cpu_seconds is None
    assert loaded[0].peak_rss_mb is None


def test_audit_and_ab_strategy_tables_use_constructor_factories() -> None:
    root = Path(__file__).parents[2]
    audit_symbols = run_path(str(root / "scripts" / "audit.py"))
    ab_symbols = run_path(str(root / "scripts" / "ab_compare.py"))
    audit_strategies = cast(
        dict[str, Callable[[bool, int], LayoutStrategy]],
        audit_symbols["_STRATEGIES"],
    )
    ab_strategies = cast(
        dict[str, Callable[[bool], LayoutStrategy]],
        ab_symbols["STRATEGIES"],
    )

    audit_sequence = audit_strategies["sequence-pair"](False, 7)
    ab_sequence = ab_strategies["sequence-pair"](False)

    assert audit_sequence.name == "sequence-pair"
    assert ab_sequence.name == "sequence-pair"
    freeform = audit_strategies["freeform"](False, 7)
    assert isinstance(freeform, FreeformLayout)
    assert freeform.workers == 7


def test_ab_cli_keeps_defaults_and_accepts_an_explicit_backend_pair() -> None:
    root = Path(__file__).parents[2]
    symbols = run_path(str(root / "scripts" / "ab_compare.py"))
    parse_args = cast(
        Callable[[list[str] | None], argparse.Namespace],
        symbols["_parse_args"],
    )
    defaults = parse_args([])
    selected = parse_args(
        ["--a", "freeform", "--b", "sequence-pair", "--power", "--json", "out.json"]
    )

    assert (defaults.a, defaults.b) == ("spine", "freeform")
    assert (selected.a, selected.b) == ("freeform", "sequence-pair")
    assert selected.power
    assert selected.json == Path("out.json")
