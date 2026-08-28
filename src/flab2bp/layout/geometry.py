"""Pure geometry helpers shared by the layout strategies.

Nothing here knows about CP-SAT or about ``BuildSpec``.  These are the small
decidable pieces -- rounding, circle linearisation, lane ordering, band offsets --
kept separate precisely because each one is a place a silent error would survive
all the way into the game.
"""

from __future__ import annotations

import math
from fractions import Fraction

#: Fixed-point denominator for the integer model.  Rates below 10^4/s keep every
#: product well inside 2^63.
SCALE = 1_000_000


def up(f: Fraction) -> int:
    """Scale a *demand* or *flow*, rounding away from feasibility."""
    return -((-f.numerator * SCALE) // f.denominator)


def down(f: Fraction) -> int:
    """Scale a *capacity*, rounding away from feasibility."""
    return (f.numerator * SCALE) // f.denominator


def reach_table(radius: Fraction) -> list[int]:
    """``table[dy]`` = horizontal supply reach at vertical offset ``dy``.

    This evaluates the circle at the worst-case vertical offset rather than
    bounding ``dx`` and ``dy`` independently, so it is *exact for the circle*.
    An inscribed square would discard about 36% of the supply area.
    """
    r = float(radius)
    limit = math.ceil(r) + 1
    return [math.floor(math.sqrt(max(0.0, r * r - d * d))) for d in range(limit)]


def greedy_tower_xs(*, x0: int, width: int, hr: int, tower_w: int) -> list[int]:
    """Minimal tower x-positions covering the tiles ``[x0, x0 + width)``.

    Greedy interval covering is optimal for equal-reach intervals on a line, so
    this is not merely feasible but tower-minimal for the given row width.
    """
    if width <= 0:
        return []
    if hr <= 0:
        raise ValueError(f"uncoverable: horizontal reach {hr} cannot span {width} tiles")
    span = 2 * hr + tower_w
    xs: list[int] = []
    x = x0
    end = x0 + width
    while x < end:
        # Place the tower so its covered interval starts at x.
        xs.append(x + hr)
        x += span
    return xs


def covered_by(
    tiles: list[tuple[int, int]],
    centres: list[tuple[float, float]],
    radius: Fraction,
) -> bool:
    """True when every tile centre lies within ``radius`` of some tower centre.

    Uses true Euclidean distance, deliberately independent of the linearised
    ``reach_table`` form, so it can catch a linearisation error rather than
    agreeing with one.
    """
    if not tiles:
        return True
    if not centres:
        return False
    r = float(radius)
    for tx, ty in tiles:
        px, py = tx + 0.5, ty + 0.5
        if not any(math.dist((px, py), c) <= r + 1e-9 for c in centres):
            return False
    return True


def band_offsets(
    row_heights: list[int], corridor_heights: list[int]
) -> tuple[list[int], list[int], int]:
    """Stack corridors and rows alternately, returning their y offsets.

    Corridor ``c`` sits between row ``c-1`` and row ``c``, so ``R`` rows need
    ``R + 1`` corridors: ``C0`` carries the external inputs and ``CR`` the
    product out.
    """
    if len(corridor_heights) != len(row_heights) + 1:
        raise ValueError(
            f"need one more corridor than rows, got {len(corridor_heights)} "
            f"corridors for {len(row_heights)} rows"
        )
    row_y: list[int] = []
    corr_y: list[int] = []
    y = 0
    for i, ch in enumerate(corridor_heights):
        corr_y.append(y)
        y += ch
        if i < len(row_heights):
            row_y.append(y)
            y += row_heights[i]
    return row_y, corr_y, y


def lane_order(
    above: list[str],
    below: list[str],
    passthrough: list[str],
    max_reach: int,
) -> list[str] | None:
    """Order a corridor's lanes so every tapped lane is within sorter reach.

    Lanes tapped by the row above must sit within ``max_reach`` of the top;
    lanes tapped by the row below within ``max_reach`` of the bottom.  Lanes
    tapped by neither are pass-through and may sit anywhere, so an arbitrary
    number of them is always feasible.

    Returns ``None`` when more lanes need tapping from one side than sorters can
    reach -- the caller then splits the corridor rather than emitting an
    unreachable sorter.
    """
    if len(above) > max_reach or len(below) > max_reach:
        return None
    return [*above, *passthrough, *below]


def height_waste(row_height: int, blocks: list[tuple[int, int, int]]) -> int:
    """Tiles lost to mixing footprint heights within one row.

    ``blocks`` are ``(width, height, count)``.  Mixing a 3x3 block into a row of
    height 4 wastes one tile per column -- real cost the bounding-box objective
    cannot see, which is why it earns its own tie-break.
    """
    return sum((row_height - h) * w * k for w, h, k in blocks)
