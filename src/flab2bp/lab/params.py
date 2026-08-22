"""The low-level FactorioLab query-parameter codec.

A faithful Python port of FactorioLab's URL serialisation primitives, verified
against ``main``:

* ``src/state/router/constants.ts``   -- the separator characters
* ``src/state/router/compression.ts`` -- the custom base64 alphabet, the
  integer-id codec, and deflate/inflate (including the truncation repair)
* ``src/state/router/zip.ts``         -- the field parsers

Only the *parsing* direction is needed to consume a URL; ``deflate`` and
``bytes_to_base64`` exist so tests can construct compressed URLs and so a
future feature can emit them.

Everything here is deliberately free of any knowledge of what the parameters
*mean*.  That interpretation lives in :mod:`flab2bp.lab.url`.
"""

from __future__ import annotations

import base64
import json
import re
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

__all__ = [
    "ZARRAYSEP",
    "ZBASE64ABC",
    "ZEMPTY",
    "ZFALSE",
    "ZFIELDSEP",
    "ZTRUE",
    "LabUrlError",
    "ModHash",
    "base64_to_bytes",
    "bytes_to_base64",
    "deflate",
    "id_to_n",
    "inflate",
    "inflate_query_value",
    "load_mod_hash",
    "n_to_id",
    "parse_array",
    "parse_bool",
    "parse_indices",
    "parse_n_array",
    "parse_n_string",
    "parse_number",
    "parse_rational",
    "parse_string",
    "parse_subset",
    "split_fields",
    "to_params",
    "to_string",
    "zip_fields",
]

# --- constants.ts ------------------------------------------------------------

ZEMPTY = "_"
ZARRAYSEP = "~"
ZFIELDSEP = "*"
ZTRUE = "1"
ZFALSE = "0"

# --- compression.ts ----------------------------------------------------------

#: Standard base64 for the first 62 code points; ``-`` and ``.`` replace ``+``
#: and ``/`` so the payload survives a URL query string untouched.
ZBASE64ABC = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-."
_ZMAP = {c: i for i, c in enumerate(ZBASE64ABC)}

_STD_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_TO_LAB = str.maketrans(_STD_B64 + "=", ZBASE64ABC + ZEMPTY)
_TO_STD = str.maketrans(ZBASE64ABC + ZEMPTY, _STD_B64 + "=")

#: Characters a chat client may strip from the end of a URL.  FactorioLab
#: re-appends each in turn until the payload inflates.
_MEND_CHARS = ("-", ".", "_")


class LabUrlError(ValueError):
    """A FactorioLab URL could not be decoded."""


def n_to_id(n: int) -> str:
    """Encode a non-negative integer as a base-64 id (``Compression.nToId``)."""
    if n < 0:
        raise LabUrlError(f"cannot encode negative index {n}")
    if n >= 64:
        return n_to_id(n // 64) + n_to_id(n % 64)
    return ZBASE64ABC[n]


def id_to_n(value: str) -> int:
    """Decode a base-64 id back to an integer (``Compression.idToN``)."""
    if not value:
        raise LabUrlError("empty base-64 id")
    try:
        head = _ZMAP[value[0]]
    except KeyError:
        raise LabUrlError(f"invalid base-64 id character {value[0]!r}") from None
    rest = value[1:]
    if rest:
        place: int = 64 ** len(rest)
        return head * place + id_to_n(rest)
    return head


def bytes_to_base64(data: bytes) -> str:
    """Encode bytes with FactorioLab's alphabet, padding with ``_``."""
    return base64.b64encode(data).decode("ascii").translate(_TO_LAB)


def base64_to_bytes(value: str) -> bytes:
    """Decode FactorioLab's base64.

    Mirrors ``Compression.base64ToBytes``, including its two validity checks:
    the length must be a multiple of four, and padding may appear only in the
    final two positions.  Those checks are what make a truncated payload fail
    fast enough for :func:`inflate` to try mending it.
    """
    if len(value) % 4 != 0:
        raise LabUrlError("base64 payload length is not a multiple of 4")
    pad = value.find(ZEMPTY)
    if pad != -1 and pad < len(value) - 2:
        raise LabUrlError("base64 payload has misplaced padding")
    unknown = set(value) - set(ZBASE64ABC) - {ZEMPTY}
    if unknown:
        raise LabUrlError(f"base64 payload has invalid characters: {sorted(unknown)!r}")
    try:
        return base64.b64decode(value.translate(_TO_STD), validate=True)
    except Exception as exc:  # pragma: no cover - guarded by the checks above
        raise LabUrlError("could not decode base64 payload") from exc


def deflate(text: str) -> str:
    """Compress and encode, matching browser ``CompressionStream('deflate')``.

    That stream emits a zlib (RFC 1950) wrapper rather than raw deflate, which
    is exactly what :func:`zlib.compress` produces.
    """
    return bytes_to_base64(zlib.compress(text.encode("utf-8")))


def _inflate_str(value: str) -> str:
    return zlib.decompress(base64_to_bytes(value)).decode("utf-8")


def inflate(value: str) -> str:
    """Decode and decompress, repairing a truncated payload if need be.

    Chat clients and link previewers often eat a trailing ``-``, ``.``, or
    ``_``.  FactorioLab tries the payload as-is, then re-appends each candidate
    in turn; so do we.
    """
    try:
        return _inflate_str(value)
    except Exception:
        pass
    for char in _MEND_CHARS:
        try:
            mended = _inflate_str(value + char)
        except Exception:
            continue
        if mended:
            return mended
    raise LabUrlError("could not inflate compressed URL payload")


def inflate_query_value(value: str) -> str:
    """Inflate a raw ``z`` parameter, upgrading V0 query-unsafe characters."""
    safe = value.replace("+", "-").replace("/", ".").replace("=", ZEMPTY)
    return inflate(safe)


# --- router-sync.ts: param string <-> mapping --------------------------------


def to_params(value: str) -> dict[str, str | list[str]]:
    """Split an inflated ``k=v&k=v`` payload into a parameter mapping.

    Pre-V11 hashed payloads have no ``=`` delimiter at all -- the key is the
    single leading character.  ``RouterSync.toParams`` detects that by checking
    whether *any* section lacks an ``=``, and so do we.
    """
    sections = value.split("&")
    if any("=" not in s for s in sections):
        return {s[0]: s[1:] for s in sections if s}

    result: dict[str, str | list[str]] = {}
    for section in sections:
        if not section:
            continue
        parts = section.split("=")
        # JS destructuring keeps only the first two segments.
        key, val = parts[0], (parts[1] if len(parts) > 1 else "")
        existing = result.get(key)
        if existing is None:
            result[key] = val
        elif isinstance(existing, list):
            existing.append(val)
        else:
            result[key] = [existing, val]
    return result


def to_string(value: Mapping[str, Any]) -> str:
    """Render a parameter mapping back to ``k=v&k=v``, dropping empty values."""
    out: list[str] = []
    for key, val in value.items():
        if isinstance(val, list):
            out.extend(f"{key}={v}" for v in val)
        elif val:
            out.append(f"{key}={val}")
    return "&".join(out)


# --- zip.ts: field-level parsers ---------------------------------------------


def zip_fields(fields: Sequence[str]) -> str:
    """Join fields with ``*`` and strip the trailing empties."""
    return re.sub(r"\*+$", "", ZFIELDSEP.join(fields))


def split_fields(value: str) -> list[str]:
    """Split a ``*``-separated record into its fields."""
    return value.split(ZFIELDSEP)


def _field(fields: Sequence[str], index: int) -> str | None:
    """Field *index*, or ``None`` when it was stripped as a trailing empty."""
    return fields[index] if index < len(fields) else None


def parse_string(value: str | None, hash_list: Sequence[str | None] | None = None) -> str | None:
    if value == ZEMPTY:
        return ""
    if hash_list is not None:
        return parse_n_string(value, hash_list)
    if not value:
        return None
    return value


def parse_bool(value: str | None) -> bool | None:
    if not value:
        return None
    return value == ZTRUE


def parse_number(value: str | None) -> int | float | None:
    if not value:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def parse_rational(value: str | None) -> Fraction | None:
    """Parse an exact rational.  FactorioLab uses BigInt fractions; so do we."""
    if not value:
        return None
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise LabUrlError(f"invalid rational value {value!r}") from exc


def parse_array(
    value: str | None, hash_list: Sequence[str | None] | None = None
) -> list[str] | None:
    if hash_list is not None:
        return parse_n_array(value, hash_list)
    if not value:
        return None
    return [] if value == ZEMPTY else value.split(ZARRAYSEP)


def parse_indices[T](
    value: str | None,
    arr: Sequence[T],
    empty: Callable[[], Any] = dict,
) -> list[T] | None:
    """Resolve ``~``-joined integer indices into *arr*.

    Out-of-range indices become a fresh *empty* value, matching JavaScript's
    ``arr[i] ?? {}``.  Callers pass a constructor so the result stays typed.
    """
    if not value:
        return None
    if value == ZEMPTY:
        return []
    out: list[T] = []
    for token in value.split(ZARRAYSEP):
        try:
            index = int(token)
        except ValueError:
            out.append(empty())
            continue
        out.append(arr[index] if 0 <= index < len(arr) else empty())
    return out


def parse_n_string(value: str | None, hash_list: Sequence[str | None]) -> str | None:
    if value == ZEMPTY:
        return ""
    if not value:
        return None
    index = id_to_n(value)
    if 0 <= index < len(hash_list):
        return hash_list[index]
    return None


def parse_n_array(value: str | None, hash_list: Sequence[str | None]) -> list[str] | None:
    if not value:
        return None
    if value == ZEMPTY:
        return []
    out: list[str] = []
    for token in value.split(ZARRAYSEP):
        index = id_to_n(token)
        if 0 <= index < len(hash_list):
            resolved = hash_list[index]
            if resolved is not None:
                out.append(resolved)
    return out


def parse_subset(value: str | None, hash_list: Sequence[str | None]) -> set[str] | None:
    """Decode a range-encoded set of ids (``Zip.parseSubset``).

    The value is a ``*``-separated list of ranges; each range is either a
    single base-64 index or ``start~end`` (inclusive).  Indices address the
    corresponding ``hash.json`` array -- note that this holds even for *bare*
    URLs, which is why parsing ``iex``/``rex`` needs the mod hash regardless of
    how the rest of the URL is encoded.
    """
    if not value:
        return None
    if value == ZEMPTY:
        return set()

    result: set[str] = set()
    for range_str in value.split(ZFIELDSEP):
        bounds = range_str.split(ZARRAYSEP)
        start = id_to_n(bounds[0])
        end = id_to_n(bounds[1]) if len(bounds) > 1 else None
        stop = (end + 1) if end is not None else (start + 1)
        result.update(v for v in hash_list[start:stop] if v is not None)
    return result


# --- hash.json ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModHash:
    """The id tables a compressed URL indexes into.

    ``None`` entries are real: they are holes left by removed ids, and they
    must be preserved because every id in a URL is a *positional* index.
    """

    items: list[str | None]
    beacons: list[str | None]
    belts: list[str | None]
    fuels: list[str | None]
    machines: list[str | None]
    modules: list[str | None]
    recipes: list[str | None]
    technologies: list[str | None]
    wagons: list[str | None]
    locations: list[str | None]

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ModHash:
        def table(key: str) -> list[str | None]:
            return list(data.get(key) or [])

        return cls(
            items=table("items"),
            beacons=table("beacons"),
            belts=table("belts"),
            fuels=table("fuels"),
            machines=table("machines"),
            modules=table("modules"),
            recipes=table("recipes"),
            technologies=table("technologies"),
            wagons=table("wagons"),
            locations=table("locations"),
        )


_VENDORED = Path(__file__).parent / "vendored"
_HASH_CACHE: dict[str, ModHash] = {}


def _candidate_paths(mod_id: str) -> Iterable[Path]:
    yield _VENDORED / mod_id / "hash.json"
    yield _VENDORED / f"{mod_id}-hash.json"
    if mod_id == "dsp":
        # The single-dataset layout currently vendored in this package.
        yield _VENDORED / "hash.json"


def load_mod_hash(mod_id: str = "dsp", *, path: Path | None = None) -> ModHash:
    """Load a dataset's ``hash.json`` from the vendored copy.

    Kept local and cached: the tables are needed to decode any compressed URL
    and any excluded/checked set, so a network round trip here would make
    offline use impossible.
    """
    if path is None and mod_id in _HASH_CACHE:
        return _HASH_CACHE[mod_id]

    source = path
    if source is None:
        source = next((p for p in _candidate_paths(mod_id) if p.is_file()), None)
    if source is None or not source.is_file():
        raise LabUrlError(f"no vendored hash.json for dataset {mod_id!r}; looked under {_VENDORED}")

    mod_hash = ModHash.from_json(json.loads(source.read_text(encoding="utf-8")))
    if path is None:
        _HASH_CACHE[mod_id] = mod_hash
    return mod_hash
