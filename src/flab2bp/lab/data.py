"""Locating, caching and loading the FactorioLab DSP dataset.

Resolution order is: an explicit path, then the on-disk HTTP cache, then the
network, then the copy vendored in this package.  The vendored copy is what
makes the tool work offline and what makes the test suite hermetic -- nothing
in ``tests/`` reaches the network.

The cache is a plain directory of JSON bodies plus sidecar metadata holding the
``ETag``, so a refresh costs a conditional GET that normally comes back ``304``.
"""

from __future__ import annotations

import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

from flab2bp.lab.schema import Dataset, HashIndex

DATA_URL: Final = "https://factoriolab.github.io/data/dsp/data.json"
HASH_URL: Final = "https://factoriolab.github.io/data/dsp/hash.json"

VENDORED_DIR: Path = Path(__file__).parent / "vendored"

#: Set to a non-empty value to force offline behaviour process-wide.
OFFLINE_ENV_VAR: Final = "FLAB2BP_OFFLINE"

_DEFAULT_TIMEOUT: Final = 30.0


class DatasetNotAvailable(RuntimeError):
    """No source -- explicit path, cache, network or vendored copy -- worked."""


# ---------------------------------------------------------------------------
# Cache plumbing
# ---------------------------------------------------------------------------


def default_cache_dir() -> Path:
    """Where downloaded datasets live between runs."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "flab2bp"


def cache_path_for(url: str, cache_dir: Path | None = None) -> Path:
    """The cached body path for ``url``.

    Keyed by a hash of the URL so unrelated datasets never collide, with a
    readable suffix so the cache directory is browsable.
    """
    directory = cache_dir if cache_dir is not None else default_cache_dir()
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    stem = Path(url).stem or "dataset"
    return directory / f"{stem}-{digest}.json"


def _meta_path(body_path: Path) -> Path:
    return body_path.with_suffix(".meta.json")


def _read_etag(body_path: Path) -> str | None:
    try:
        meta = json.loads(_meta_path(body_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    etag = meta.get("etag")
    return etag if isinstance(etag, str) else None


def _write_cache(body_path: Path, text: str, etag: str | None) -> None:
    try:
        body_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = body_path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(body_path)
        if etag:
            _meta_path(body_path).write_text(json.dumps({"etag": etag}), encoding="utf-8")
    except OSError:
        # A broken cache must never break the program; the value is still in hand.
        pass


def _offline_forced() -> bool:
    return bool(os.environ.get(OFFLINE_ENV_VAR))


def _download(url: str, body_path: Path, *, force_refresh: bool) -> str | None:
    """Conditional GET, writing through to the cache.  ``None`` on any failure."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a hard dependency
        return None

    headers: dict[str, str] = {}
    etag = None if force_refresh else _read_etag(body_path)
    if etag:
        headers["If-None-Match"] = etag

    try:
        response = httpx.get(url, headers=headers, timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
    except Exception:
        return None

    if response.status_code == 304:
        try:
            return body_path.read_text(encoding="utf-8")
        except OSError:
            return None
    if response.status_code != 200:
        return None

    text = response.text
    _write_cache(body_path, text, response.headers.get("ETag"))
    return text


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _parse_json(text: str) -> Any:
    """Parse with exact rationals for every decimal literal.

    ``parse_float`` receives the raw token text, so ``0.32`` becomes exactly
    ``Fraction(8, 25)`` rather than the nearest binary double.
    """
    return json.loads(text, parse_float=Fraction)


def _resolve_text(
    url: str,
    *,
    path: Path | None,
    vendored_name: str,
    allow_network: bool,
    cache_dir: Path | None,
    force_refresh: bool,
) -> str:
    if path is not None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DatasetNotAvailable(f"could not read dataset at {path}") from exc

    body_path = cache_path_for(url, cache_dir)

    if not force_refresh:
        try:
            return body_path.read_text(encoding="utf-8")
        except OSError:
            pass

    if allow_network and not _offline_forced():
        text = _download(url, body_path, force_refresh=force_refresh)
        if text is not None:
            return text

    try:
        return (VENDORED_DIR / vendored_name).read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetNotAvailable(
            f"no dataset available for {url}: explicit path, cache "
            f"({body_path}), network and vendored copy all failed"
        ) from exc


def load_dataset(
    path: Path | str | None = None,
    *,
    allow_network: bool = True,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
) -> Dataset:
    """Load the DSP dataset.

    Args:
        path: Read this file instead of consulting cache, network or vendor.
        allow_network: Whether a cache miss may fetch from FactorioLab.
        cache_dir: Override the on-disk cache location.
        force_refresh: Skip the cached body and re-fetch.
    """
    text = _resolve_text(
        DATA_URL,
        path=Path(path) if path is not None else None,
        vendored_name="data.json",
        allow_network=allow_network,
        cache_dir=cache_dir,
        force_refresh=force_refresh,
    )
    return Dataset.parse(_parse_json(text))


def load_hash_index(
    path: Path | str | None = None,
    *,
    allow_network: bool = True,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
) -> HashIndex:
    """Load ``hash.json``, the id tables that ``z=``-compressed URLs index into."""
    text = _resolve_text(
        HASH_URL,
        path=Path(path) if path is not None else None,
        vendored_name="hash.json",
        allow_network=allow_network,
        cache_dir=cache_dir,
        force_refresh=force_refresh,
    )
    return HashIndex.parse(_parse_json(text))


def load_vendored() -> Dataset:
    """Load the in-repo copy directly, bypassing cache and network."""
    return Dataset.parse(_parse_json((VENDORED_DIR / "data.json").read_text(encoding="utf-8")))


def load_vendored_hash_index() -> HashIndex:
    return HashIndex.parse(_parse_json((VENDORED_DIR / "hash.json").read_text(encoding="utf-8")))


__all__ = (
    "DATA_URL",
    "HASH_URL",
    "VENDORED_DIR",
    "DatasetNotAvailable",
    "cache_path_for",
    "default_cache_dir",
    "load_dataset",
    "load_hash_index",
    "load_vendored",
    "load_vendored_hash_index",
)
