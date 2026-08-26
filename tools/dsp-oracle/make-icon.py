#!/usr/bin/env python3
"""Emit ``icon.png`` -- the 256x256 Thunderstore package icon.

Thunderstore rejects a package whose icon is any other size, so the dimensions
here are not a style choice.  Written with ``zlib`` and ``struct`` rather than
Pillow so that packaging never gains a dependency the rest of the repo does not
already have; the file is committed, and this script exists so the next person
can change the artwork without reverse-engineering a binary.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

Rgb = tuple[int, int, int]

SIZE = 256
BG: Rgb = (18, 22, 30)
GRID: Rgb = (38, 48, 66)
BELT: Rgb = (72, 148, 214)
HOT: Rgb = (232, 168, 72)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _pixels() -> list[list[Rgb]]:
    """A blueprint grid, one belt lane across it, and one flagged cell."""
    rows: list[list[Rgb]] = [[BG] * SIZE for _ in range(SIZE)]
    step = 32

    for y in range(SIZE):
        for x in range(SIZE):
            if x % step == 0 or y % step == 0:
                rows[y][x] = GRID

    # The lane: a horizontal run through the middle band.
    for y in range(112, 144):
        for x in range(16, 240):
            rows[y][x] = BELT

    # The one cell the oracle flags -- offset off the lane, which is the whole
    # point of the tool: the game's verdict, not ours.
    for y in range(48, 96):
        for x in range(160, 208):
            rows[y][x] = HOT

    return rows


def render() -> bytes:
    raw = bytearray()
    for row in _pixels():
        raw.append(0)  # filter type 0 (None) for this scanline
        for r, g, b in row:
            raw += bytes((r, g, b))

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)  # 8-bit truecolour
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "icon.png"
    out.write_bytes(render())
    print(f"wrote {out} ({out.stat().st_size} bytes, {SIZE}x{SIZE})")
