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
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import BytesIO
from multiprocessing.queues import Queue
from typing import Any, Final, Protocol, cast, runtime_checkable

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


class _TraceReceiver:
    """Keep native framing, but distinguish boundary EOF from a lost payload.

    Connection.recv_bytes raises EOFError both before a header and after a
    complete header with no payload. Observe its native read steps instead
    of copying its framing codec or guessing integrity from producer status.
    Installed once on the parent connection before its collector starts.
    Connection's spawn reduction transfers handles, not these parent hooks.
    """

    def __init__(self, reader: Any) -> None:
        self._receive = reader.recv_bytes
        self._message_started = False
        read_chunk = getattr(reader, "_recv", None)
        if read_chunk is not None:
            self._read_chunk = read_chunk
            reader._recv = self._read
        else:
            # Windows named pipes preserve message boundaries. MORE_DATA is
            # the point at which native receive has consumed a partial message.
            self._read_tail = reader._get_more_data
            reader._get_more_data = self._read_more

    def _read(self, size: int) -> BytesIO:
        data = self._read_chunk(size)
        self._message_started = True
        return cast(BytesIO, data)

    def _read_more(self, overlapped: object, maxsize: int | None) -> BytesIO:
        self._message_started = True
        return cast(BytesIO, self._read_tail(overlapped, maxsize))

    def receive(self) -> bytes:
        self._message_started = False
        try:
            return cast(bytes, self._receive())
        except EOFError as exc:
            if self._message_started:
                raise OSError("trace producer exited during a message") from exc
            raise queue.Empty from exc


def prepare_trace_queue(q: object) -> None:
    """Install parent-only receive state before any reader or producer starts."""
    if isinstance(q, Queue):
        owned = cast(Any, q)
        owned._recv_bytes = _TraceReceiver(owned._reader).receive


def finish_trace_producers(q: object | None) -> None:
    """Half-close only the writer after every producer process has exited.

    The parent never publishes on this queue: serial events use the collector
    deque, so there is no local feeder to flush. Clean boundary EOF drains
    normally; interrupted framing fails explicitly without closing the reader.
    """
    if isinstance(q, Queue):
        cast(Any, q)._writer.close()


def close_trace_queue(q: object) -> None:
    """Release the parent's queue only after its collector has terminated."""
    owned = cast(Any, q)
    owned.cancel_join_thread()
    owned.close()
    if isinstance(q, Queue):
        # Queue.close() only wakes a LOCAL feeder. This read-only parent has
        # none, so it must release both endpoints itself after the reader exits.
        owned._reader.close()
        owned._writer.close()


def drain_trace(q: MessageQueue) -> Iterator[SearchEvent]:
    """Yield at most ``TRACE_DRAIN_MAX_EVENTS`` dequeued events per poll.

    The bound is on the GETS and not on what survives the type check, for the
    reason ``RaceChannels.drain`` gives (strategy_race.py:212-218): the cost of a
    poll is the dequeue.

    Only ``queue.Empty`` means exhaustion. A broken queue propagates to its
    collector owner, which reports trace failure without changing solver state.
    Yield each valid event immediately so a later read failure cannot discard
    events already removed from the transport.
    """
    for _ in range(TRACE_DRAIN_MAX_EVENTS):
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, SearchEvent):
            yield item
