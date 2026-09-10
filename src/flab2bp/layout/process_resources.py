"""Portable process usage shared by worker supervision and bounded construction."""

from __future__ import annotations

import sys

try:
    import resource
except ImportError:  # pragma: no cover - exercised on non-POSIX platforms
    resource = None  # type: ignore[assignment]


def peak_rss_kib(raw: int, *, platform: str = sys.platform) -> int:
    """Normalize ``ru_maxrss`` to KiB on the platforms that expose it."""
    if platform == "darwin":
        return (raw + 1023) // 1024
    return raw


def usage() -> tuple[float, float, int]:
    """Return user CPU, system CPU, and normalized peak RSS when supported."""
    if resource is None:
        return 0.0, 0.0, 0
    measured = resource.getrusage(resource.RUSAGE_SELF)
    return measured.ru_utime, measured.ru_stime, peak_rss_kib(measured.ru_maxrss)
