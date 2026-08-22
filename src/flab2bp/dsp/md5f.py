"""MD5F -- the MD5 variant Dyson Sphere Program signs blueprints with.

It is RFC 1321 MD5 except for two deliberate corruptions:

* two of the four init constants have swapped nibbles --
  ``B: 0xEFCDAB89 -> 0xEFDCAB89`` and ``D: 0x10325476 -> 0x10325746``;
* eight of the sixty-four round constants are altered, so the table cannot be
  regenerated from ``sin()`` and must be hardcoded.

Padding, shifts and the round functions are all standard.  The altered indices
are 1, 6, 12, 15, 19, 21, 24 and 27, each flagged inline below; the values are
confirmed against the checksums the game embedded in all eleven fixtures.
"""

from __future__ import annotations

import struct

_MASK = 0xFFFFFFFF

# Per-round left-rotation amounts. Identical to standard MD5.
_S = (
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
)  # fmt: skip

# Round constants. Eight entries deviate from floor(abs(sin(i+1)) * 2**32) and
# are marked; do not "correct" them.
_T = (
    0xD76AA478, 0xE8D7B756, 0x242070DB, 0xC1BDCEEE,  # [1] altered (std E8C7B756)
    0xF57C0FAF, 0x4787C62A, 0xA8304623, 0xFD469501,  # [6] altered (std A8304613)
    0x698098D8, 0x8B44F7AF, 0xFFFF5BB1, 0x895CD7BE,
    0x6B9F1122, 0xFD987193, 0xA679438E, 0x39B40821,  # [12] std 6B901122, [15] std 49B40821
    0xF61E2562, 0xC040B340, 0x265E5A51, 0xC9B6C7AA,  # [19] altered (std E9B6C7AA)
    0xD62F105D, 0x02443453, 0xD8A1E681, 0xE7D3FBC8,  # [21] altered (std 02441453)
    0x21F1CDE6, 0xC33707D6, 0xF4D50D87, 0x475A14ED,  # [24] std 21E1CDE6, [27] std 455A14ED
    0xA9E3E905, 0xFCEFA3F8, 0x676F02D9, 0x8D2A4C8A,
    0xFFFA3942, 0x8771F681, 0x6D9D6122, 0xFDE5380C,
    0xA4BEEA44, 0x4BDECFA9, 0xF6BB4B60, 0xBEBFBC70,
    0x289B7EC6, 0xEAA127FA, 0xD4EF3085, 0x04881D05,
    0xD9D4D039, 0xE6DB99E5, 0x1FA27CF8, 0xC4AC5665,
    0xF4292244, 0x432AFF97, 0xAB9423A7, 0xFC93A039,
    0x655B59C3, 0x8F0CCC92, 0xFFEFF47D, 0x85845DD1,
    0x6FA87E4F, 0xFE2CE6E0, 0xA3014314, 0x4E0811A1,
    0xF7537E82, 0xBD3AF235, 0x2AD7D2BB, 0xEB86D391,
)  # fmt: skip

# Init vector. A and C are standard; B and D are DSP's nibble-swapped variants.
_INIT_A = 0x67452301
_INIT_B = 0xEFDCAB89  # standard MD5 uses 0xEFCDAB89
_INIT_C = 0x98BADCFE
_INIT_D = 0x10325746  # standard MD5 uses 0x10325476


def _rotl(x: int, c: int) -> int:
    x &= _MASK
    return ((x << c) | (x >> (32 - c))) & _MASK


def md5f(data: bytes) -> str:
    """Return DSP's MD5F digest of ``data`` as 32 uppercase hex characters."""
    bit_len = len(data) * 8
    # Pad to 56 mod 64, then append the 64-bit little-endian bit length.
    padded = bytearray(data)
    padded.append(0x80)
    while len(padded) % 64 != 56:
        padded.append(0x00)
    padded += struct.pack("<Q", bit_len & 0xFFFFFFFFFFFFFFFF)

    a0, b0, c0, d0 = _INIT_A, _INIT_B, _INIT_C, _INIT_D

    for chunk in range(0, len(padded), 64):
        m = struct.unpack_from("<16I", padded, chunk)
        a, b, c, d = a0, b0, c0, d0

        for i in range(64):
            if i < 16:
                f = (b & c) | (~b & d)
                g = i
            elif i < 32:
                f = (d & b) | (~d & c)
                g = (5 * i + 1) % 16
            elif i < 48:
                f = b ^ c ^ d
                g = (3 * i + 5) % 16
            else:
                f = c ^ (b | (~d & _MASK))
                g = (7 * i) % 16

            tmp = d
            d = c
            c = b
            b = (b + _rotl((a + (f & _MASK) + _T[i] + m[g]) & _MASK, _S[i])) & _MASK
            a = tmp

        a0 = (a0 + a) & _MASK
        b0 = (b0 + b) & _MASK
        c0 = (c0 + c) & _MASK
        d0 = (d0 + d) & _MASK

    return struct.pack("<4I", a0, b0, c0, d0).hex().upper()
