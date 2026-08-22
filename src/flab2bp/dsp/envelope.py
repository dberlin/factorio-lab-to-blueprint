"""The text envelope wrapping a blueprint payload.

Shape::

    BLUEPRINT:<csv header>"<base64(gzip(payload))>"<32 hex MD5F>

The hash covers everything from ``BLUEPRINT:`` up to but *not* including the
closing quote, so it signs the header and the base64 together.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import io
import struct
import zlib
from dataclasses import dataclass
from urllib.parse import quote, unquote

from flab2bp.dsp.md5f import md5f
from flab2bp.dsp.records import BlueprintHeader

FACTORY_PREFIX = "BLUEPRINT:"
DYSON_PREFIX = "DYBP:"

#: Difference between the .NET epoch (0001-01-01) and the Unix epoch, in seconds.
DOTNET_EPOCH_OFFSET_S = 62_135_596_800
TICKS_PER_SECOND = 10_000_000


class BlueprintFormatError(Exception):
    """Raised for anything that is not a well-formed factory blueprint."""


@dataclass(frozen=True, slots=True)
class Envelope:
    header: BlueprintHeader
    payload: bytes
    hash_valid: bool
    gzip_os: int
    gzip_xfl: int
    gzip_mtime: int


def _int(value: str | None, what: str) -> int:
    text = (value or "").strip() or "0"
    try:
        # Parse as an integer first. Timestamps are .NET tick counts around
        # 6.4e17, well past the 2**53 where float would start rounding.
        return int(text)
    except ValueError:
        pass
    try:
        return int(float(text))
    except (TypeError, ValueError) as exc:
        raise BlueprintFormatError(f"{what} is not a number: {value}") from exc


def _decode_text(s: str) -> str:
    try:
        return unquote(s)
    except (UnicodeDecodeError, ValueError):
        return s


def parse_envelope(text: str) -> Envelope:
    raw = text.strip()

    if raw.startswith(DYSON_PREFIX):
        raise BlueprintFormatError(
            "This is a Dyson sphere blueprint (DYBP). Only factory blueprints are supported."
        )
    if not raw.startswith(FACTORY_PREFIX):
        raise BlueprintFormatError("Not a blueprint string (expected it to start with BLUEPRINT:)")

    first_quote = raw.find('"')
    last_quote = raw.rfind('"')
    if first_quote < 0 or last_quote <= first_quote:
        raise BlueprintFormatError("Malformed blueprint: missing the quoted payload section")

    hash_valid = md5f(raw[:last_quote].encode("utf-8")) == raw[last_quote + 1 :].strip().upper()

    cells = tuple(raw[len(FACTORY_PREFIX) : first_quote].split(","))
    header_version = _int(cells[0] if cells else None, "header version")

    def cell(i: int) -> str:
        return cells[i] if i < len(cells) else ""

    header = BlueprintHeader(
        header_version=header_version,
        layout=_int(cell(1), "layout"),
        icons=tuple(_int(cell(i), f"icon {i - 2}") for i in range(2, 7)),
        timestamp=_int(cell(8), "timestamp"),
        game_version=cell(9),
        short_desc=_decode_text(cell(10)),
        author=_decode_text(cell(11)) if header_version >= 1 else "",
        custom_version=_decode_text(cell(12)) if header_version >= 1 else "",
        attributes=(
            tuple(a for a in _decode_text(cell(13)).split(";") if a) if header_version >= 1 else ()
        ),
        description=_decode_text(cell(14) if header_version >= 1 else cell(11)),
        raw_cells=cells,
    )

    gz = _b64_decode(raw[first_quote + 1 : last_quote])
    if len(gz) < 10 or gz[:2] != b"\x1f\x8b":
        raise BlueprintFormatError("Could not decode the blueprint payload: not a gzip stream")
    gzip_xfl, gzip_os = gz[8], gz[9]
    gzip_mtime: int = struct.unpack_from("<I", gz, 4)[0]

    try:
        payload = gzip.decompress(gz)
    except (OSError, EOFError, zlib.error) as exc:
        raise BlueprintFormatError(f"Could not decode the blueprint payload: {exc}") from exc

    return Envelope(
        header=header,
        payload=payload,
        hash_valid=hash_valid,
        gzip_os=gzip_os,
        gzip_xfl=gzip_xfl,
        gzip_mtime=gzip_mtime,
    )


def _b64_decode(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BlueprintFormatError(f"Could not decode the blueprint payload: {exc}") from exc


def compress_payload(payload: bytes, *, os_byte: int, xfl: int, mtime: int) -> bytes:
    """gzip ``payload`` the way the game does.

    Python's level-6 deflate reproduces the game's compressed bytes exactly for
    every blueprint in the corpus, so the only fields that need replaying are
    the header's XFL, OS and mtime bytes, which Python fills in differently.
    """
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=mtime) as f:
        f.write(payload)
    out = bytearray(buf.getvalue())
    out[8] = xfl
    out[9] = os_byte
    return bytes(out)


def _encode_text(s: str) -> str:
    """Percent-encode the way the game's exporter does."""
    return quote(s, safe="")


def build_header_cells(header: BlueprintHeader) -> tuple[str, ...]:
    """Render a header to CSV cells.

    Cell 7 is a reserved field the game always writes as ``0``.
    """
    icons = list(header.icons) + [0] * 5
    cells = [
        str(header.header_version),
        str(header.layout),
        *(str(i) for i in icons[:5]),
        "0",
        str(header.timestamp),
        header.game_version,
        _encode_text(header.short_desc),
    ]
    if header.header_version >= 1:
        cells += [
            _encode_text(header.author),
            _encode_text(header.custom_version),
            _encode_text(";".join(header.attributes)),
            _encode_text(header.description),
        ]
    else:
        cells.append(_encode_text(header.description))
    return tuple(cells)


def build_envelope(
    header: BlueprintHeader,
    payload: bytes,
    *,
    gzip_os: int = 0x0B,
    gzip_xfl: int = 0x00,
    gzip_mtime: int = 0,
    raw_cells: tuple[str, ...] | None = None,
) -> str:
    """Assemble a complete blueprint string, hash included.

    ``raw_cells`` replays a decoded header verbatim.  Percent-encoding is not
    round-trip stable in general -- the game escapes a slightly different set of
    characters than :func:`urllib.parse.quote` -- so re-encoding a blueprint we
    parsed must reuse the original cells rather than regenerate them.
    """
    cells = raw_cells if raw_cells is not None else build_header_cells(header)
    gz = compress_payload(payload, os_byte=gzip_os, xfl=gzip_xfl, mtime=gzip_mtime)
    b64 = base64.b64encode(gz).decode("ascii")
    prefix = f'{FACTORY_PREFIX}{",".join(cells)}"{b64}'
    return f'{prefix}"{md5f(prefix.encode("utf-8"))}'


def dotnet_ticks(unix_seconds: float) -> int:
    """Convert a Unix timestamp to the .NET tick count the header stores."""
    return int((unix_seconds + DOTNET_EPOCH_OFFSET_S) * TICKS_PER_SECOND)
