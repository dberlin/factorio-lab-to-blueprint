import queue

from flab2bp.layout.observe import SearchEvent, SearchPhase
from flab2bp.layout.observe_channel import (
    TRACE_DRAIN_MAX_EVENTS,
    TraceChannel,
    drain_trace,
    install_trace_channel,
    trace_channel,
)


def _event() -> SearchEvent:
    return SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)


def test_offer_drops_and_counts_when_the_queue_is_full() -> None:
    channel = TraceChannel(publish=queue.Queue(maxsize=2))
    for _ in range(5):
        channel.offer(_event())
    # A dropped frame costs a picture and never a result, exactly as
    # RaceChannels._put has it (strategy_race.py:199-203).
    assert channel.dropped == 3


def test_offer_never_raises_on_an_unexpected_queue_failure() -> None:
    class _Broken:
        def put_nowait(self, item: object, /) -> None:
            raise RuntimeError("the pipe went away")

        def get_nowait(self) -> object:
            raise queue.Empty

    channel = TraceChannel(publish=_Broken())
    channel.offer(_event())
    assert channel.dropped == 1


def test_drain_is_bounded_per_poll() -> None:
    q: queue.Queue[object] = queue.Queue()
    for _ in range(TRACE_DRAIN_MAX_EVENTS + 10):
        q.put_nowait(_event())
    assert len(drain_trace(q)) == TRACE_DRAIN_MAX_EVENTS


def test_drain_ignores_anything_that_is_not_a_search_event() -> None:
    q: queue.Queue[object] = queue.Queue()
    q.put_nowait("not an event")
    q.put_nowait(_event())
    assert len(drain_trace(q)) == 1


def test_install_and_read_back_the_module_global() -> None:
    q: queue.Queue[object] = queue.Queue()
    install_trace_channel(q)
    try:
        channel = trace_channel()
        assert channel is not None
        channel.offer(_event())
        assert isinstance(q.get_nowait(), SearchEvent)
    finally:
        install_trace_channel(None)
        assert trace_channel() is None


def test_close_cancels_the_join_thread_when_the_queue_supports_it() -> None:
    class _CancellableQueue:
        def __init__(self) -> None:
            self.cancelled = False

        def put_nowait(self, item: object, /) -> None:
            pass

        def get_nowait(self) -> object:
            raise queue.Empty

        def cancel_join_thread(self) -> None:
            self.cancelled = True

    cancellable = _CancellableQueue()
    channel = TraceChannel(publish=cancellable)
    channel.close()
    # An unread multiprocessing.Queue with buffered data blocks its process's
    # exit until something reads it, so close() must disarm that -- exactly
    # the reason RaceChannels.close() does the same (strategy_race.py:230-235).
    assert cancellable.cancelled is True


def test_close_is_a_noop_for_a_queue_without_cancel_join_thread() -> None:
    # queue.Queue has no cancel_join_thread; close() must not raise on it.
    channel = TraceChannel(publish=queue.Queue())
    channel.close()
