"""Physical splitter chains for arbitrary rated fan-out or fan-in."""

from __future__ import annotations

from fractions import Fraction

from .construction import Constructor, Terminal


def tree_extent(branches: int) -> int:
    # Both facing leaves need their mandatory two-cell ground approach.
    return 6 * max(1, branches // 2)


def terminals(
    constructor: Constructor, root: int, rates: list[Fraction], *, feed: bool
) -> list[Terminal]:
    """Root reserves east for merge output, west for split input.

    Each continuation spends one north port and gains two leaf ports at the
    next physical junction. Every continuation is rated at its descendants' sum.
    """
    assert rates and all(rate > 0 for rate in rates)
    result: list[Terminal] = []
    node = root
    first = True
    offset = 0
    while offset < len(rates):
        remaining = len(rates) - offset
        side = (-1, 0) if feed else (1, 0)
        choices = (side, (0, 1), (0, -1)) if first else ((1, 0), (-1, 0), (0, 1))
        if remaining <= 3:
            result.extend(
                constructor.dock(node, direction, feed=feed) for direction in choices[:remaining]
            )
            break
        choices = (side, (0, -1)) if first else ((1, 0), (-1, 0))
        result.extend(constructor.dock(node, direction, feed=feed) for direction in choices)
        offset += 2
        parent = constructor.canvas.buildings[node]
        child = constructor.splitter(int(parent.x), int(parent.y) + 6, parent.carries_item or "")
        upper = constructor.dock(node, (0, 1), feed=feed)
        lower = constructor.dock(child, (0, -1), feed=not feed)
        source, sink = (lower.port, upper.port) if feed else (upper.port, lower.port)
        constructor.connect(
            source,
            sink,
            [(source.x, source.y, source.z), (sink.x, sink.y, sink.z)],
            parent.carries_item or "",
            sum(rates[offset:], Fraction()),
            "local-junction-tree",
        )
        node = child
        first = False
    return result
