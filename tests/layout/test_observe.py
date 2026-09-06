import pytest

from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.observe import (
    ALWAYS_SAMPLE,
    TRACE_CHILD_SAMPLE_INTERVAL_S,
    TRACE_SAMPLE_INTERVAL_S,
    SampledObserver,
    SearchEvent,
    SearchPhase,
)


def _placement() -> Placement:
    return Placement(buildings=(PlacedBuilding(item_id=2001, model_index=35, x=0, y=0),))


class _Clock:
    """A monotonic that only moves when the test says so."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_event_holds_the_same_placement_object_it_was_given() -> None:
    placement = _placement()
    event = SearchEvent(
        strategy="freeform",
        candidate="all-products",
        phase=SearchPhase.PACKED,
        placement=placement,
    )
    # A copy here would defeat the whole point: Placement is frozen, so a
    # reference costs a pointer and can never change under a reader.
    assert event.placement is placement


def test_sampler_refuses_a_second_ordinary_sample_inside_the_interval() -> None:
    clock = _Clock()
    seen: list[SearchEvent] = []
    observer = SampledObserver(sink=seen.append, min_interval_s=0.25, monotonic=clock)

    assert observer.due(SearchPhase.PACKED) is True
    observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED))
    clock.now = 0.1
    assert observer.due(SearchPhase.PACKED) is False
    clock.now = 0.25
    assert observer.due(SearchPhase.PACKED) is True
    assert len(seen) == 1


def test_incumbent_and_composed_bypass_the_interval() -> None:
    clock = _Clock()
    observer = SampledObserver(sink=lambda _e: None, min_interval_s=1000.0, monotonic=clock)
    observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED))
    assert observer.due(SearchPhase.PACKED) is False
    assert observer.due(SearchPhase.INCUMBENT) is True
    assert observer.due(SearchPhase.COMPOSED) is True
    assert frozenset({SearchPhase.INCUMBENT, SearchPhase.COMPOSED}) == ALWAYS_SAMPLE


def test_note_never_raises_when_the_sink_does() -> None:
    def explode(_event: SearchEvent) -> None:
        raise RuntimeError("a trace sink must never kill a build")

    observer = SampledObserver(sink=explode)
    # R3: a progress sink that raises is a caller bug worth surfacing; a TRACE
    # sink that raises would kill a real build for a debugging view.
    observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED))


def test_event_is_frozen() -> None:
    event = SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED)
    with pytest.raises(AttributeError):
        event.strategy = "sequence-pair"  # type: ignore[misc]


def test_the_two_sample_intervals_are_fixed_v1_constants() -> None:
    # Settled by the user: no "detail" slider in v1. A configurable interval
    # is a follow-on, only if Task 13's overhead-gate baseline leaves room
    # (design §5.3, §10).
    assert TRACE_SAMPLE_INTERVAL_S == 0.25
    assert TRACE_CHILD_SAMPLE_INTERVAL_S == 0.5
    assert SampledObserver(sink=lambda _e: None).min_interval_s == TRACE_SAMPLE_INTERVAL_S


def test_overlay_payloads_are_tuples_so_an_event_stays_hashable() -> None:
    event = SearchEvent(
        strategy="freeform",
        candidate="c",
        phase=SearchPhase.ROUTED,
        stranded=((0, 0, 4, 4),),
        no_goods=((3, 7),),
    )
    assert isinstance(event.stranded, tuple)
    assert isinstance(event.no_goods, tuple)
    hash(event)  # frozen + slots + tuples: an event can key a set.
