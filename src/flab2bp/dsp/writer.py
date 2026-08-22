"""Little-endian writer, the exact inverse of :mod:`flab2bp.dsp.reader`."""

from __future__ import annotations

import struct


class BinaryWriter:
    """Sequential little-endian writer.

    Every integer method range-checks through :mod:`struct`, so a value that
    would silently wrap in C# raises here instead.
    """

    __slots__ = ("_parts",)

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def getvalue(self) -> bytes:
        return b"".join(self._parts)

    def __len__(self) -> int:
        return sum(len(p) for p in self._parts)

    def raw(self, data: bytes) -> None:
        self._parts.append(data)

    def _pack(self, fmt: str, value: int) -> None:
        try:
            self._parts.append(struct.pack(fmt, value))
        except struct.error as exc:
            # struct.error does not subclass ValueError; normalise it so callers
            # can catch one exception type across the whole codec.
            raise ValueError(f"value {value} does not fit format {fmt!r}: {exc}") from exc

    def i8(self, value: int) -> None:
        self._pack("<b", value)

    def u8(self, value: int) -> None:
        self._pack("<B", value)

    def i16(self, value: int) -> None:
        self._pack("<h", value)

    def u16(self, value: int) -> None:
        self._pack("<H", value)

    def i32(self, value: int) -> None:
        self._pack("<i", value)

    def u32(self, value: int) -> None:
        self._pack("<I", value)

    def f32(self, value: float) -> None:
        self._parts.append(struct.pack("<f", value))

    def leb(self, value: int) -> None:
        """7-bit encoded length, as written by C# ``BinaryWriter``."""
        if value < 0 or value > 0x7FFFFFFF:
            raise ValueError(f"LEB128 length out of range: {value}")
        while True:
            byte = value & 0x7F
            value >>= 7
            if value:
                self.u8(byte | 0x80)
            else:
                self.u8(byte)
                return

    def string(self, text: str) -> None:
        """C# ``BinaryWriter.Write(string)``: LEB128 *byte* length, then UTF-8."""
        data = text.encode("utf-8")
        self.leb(len(data))
        self.raw(data)
