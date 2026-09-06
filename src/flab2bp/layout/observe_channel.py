"""Getting trace events from a spawned child to the parent.

Modelled directly on ``RaceChannels`` (strategy_race.py:187-236), and for the
same reasons: a ``multiprocessing.Queue`` reaches a child only through
``initargs`` (strategy_race.py:396-401), a full queue must never make a searcher
wait, and an unread queue with buffered data blocks its process's exit until
something reads it -- which after a deadline is nobody.

One direction only.  The race's queues are peer-to-peer because each arm both
publishes and consumes; this one is child-to-parent, and the parent never
answers.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from flab2bp.layout.observe import SearchEvent

TRACE_QUEUE_MAXSIZE: Final = 64
TRACE_DRAIN_MAX_EVENTS: Final = 32


class MessageQueue(Protocol):
    def put_nowait(self, item: object, /) -> None: ...

    def get_nowait(self) -> object: ...


@runtime_checkable
class _JoinCancellable(Protocol):
    def cancel_join_thread(self) -> None: ...


@dataclass
class TraceChannel:
    """A child's write end of the child -> parent trace queue."""

    publish: MessageQueue
    _dropped: int = field(default=0, init=False)

    @property
    def dropped(self) -> int:
        return self._dropped

    def offer(self, event: SearchEvent, /) -> None:
        """Enqueue, or drop and count.  Never blocks and never raises.

        Broad except on purpose: this is the last hop of a debugging path, and a
        pipe that went away must cost the picture and not the build.
        """
        try:
            self.publish.put_nowait(event)
        except Exception:  # noqa: BLE001
            self._dropped += 1

    def close(self) -> None:
        if isinstance(self.publish, _JoinCancellable):
            self.publish.cancel_join_thread()


_TRACE_CHANNEL: TraceChannel | None = None


def install_trace_channel(q: object) -> None:
    """Pool initializer half: give this child its write end.  ``None`` clears it."""
    global _TRACE_CHANNEL
    _TRACE_CHANNEL = None if q is None else TraceChannel(publish=q)  # type: ignore[arg-type]


def trace_channel() -> TraceChannel | None:
    return _TRACE_CHANNEL


def drain_trace(q: MessageQueue) -> tuple[SearchEvent, ...]:
    """Parent side: at most ``TRACE_DRAIN_MAX_EVENTS`` events per poll.

    The bound is on the GETS and not on what survives the type check, for the
    reason ``RaceChannels.drain`` gives (strategy_race.py:212-218): the cost of a
    poll is the dequeue.
    """
    taken: list[SearchEvent] = []
    for _ in range(TRACE_DRAIN_MAX_EVENTS):
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        except OSError, ValueError:
            # A closed or broken queue (fix round 2, Minor 4): reachable on
            # the wedged-thread path in `TraceCollector.stop()`, where
            # `close()` runs while the daemon thread that calls this is still
            # mid-read. The whole point of this channel is that a debugging
            # view never disturbs a build -- yield whatever was already
            # collected and stop, rather than propagate.
            break
        if isinstance(item, SearchEvent):
            taken.append(item)
    return tuple(taken)
