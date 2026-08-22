"""Little-endian reader over a byte buffer, with bounds checks on every read."""

from __future__ import annotations

import struct


class BinaryReader:
    """Sequential little-endian reader.

    Mirrors :class:`~flab2bp.dsp.writer.BinaryWriter` field for field; the two
    are tested for symmetry so a change to one that is not matched in the other
    shows up immediately.
    """

    __slots__ = ("_buf", "offset")

    def __init__(self, buf: bytes) -> None:
        self._buf = buf
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self._buf) - self.offset

    def _need(self, n: int) -> int:
        at = self.offset
        if at + n > len(self._buf):
            raise ValueError(
                f"read of {n} byte(s) at offset {at} exceeds buffer length {len(self._buf)}"
            )
        self.offset = at + n
        return at

    def skip(self, n: int) -> None:
        self._need(n)

    def _unpack(self, fmt: str, size: int) -> int:
        at = self._need(size)
        value: int = struct.unpack_from(fmt, self._buf, at)[0]
        return value

    def i8(self) -> int:
        return self._unpack("<b", 1)

    def u8(self) -> int:
        return self._unpack("<B", 1)

    def i16(self) -> int:
        return self._unpack("<h", 2)

    def u16(self) -> int:
        return self._unpack("<H", 2)

    def i32(self) -> int:
        return self._unpack("<i", 4)

    def u32(self) -> int:
        return self._unpack("<I", 4)

    def f32(self) -> float:
        at = self._need(4)
        value: float = struct.unpack_from("<f", self._buf, at)[0]
        return value

    def leb(self) -> int:
        """7-bit encoded length, as written by C# ``BinaryWriter``."""
        result = 0
        shift = 0
        for _ in range(5):
            b = self.u8()
            result += (b & 0x7F) << shift
            if not b & 0x80:
                if result > 0x7FFFFFFF:
                    raise ValueError(f"LEB128 length out of range: {result}")
                return result
            shift += 7
        raise ValueError("LEB128 length is too long (more than 5 bytes)")

    def string(self) -> str:
        """C# ``BinaryWriter.Write(string)``: LEB128 *byte* length, then UTF-8."""
        n = self.leb()
        at = self._need(n)
        return self._buf[at : at + n].decode("utf-8")

    def rest(self) -> bytes:
        """Everything not yet consumed, leaving the cursor at the end."""
        at = self._need(self.remaining)
        return self._buf[at:]
