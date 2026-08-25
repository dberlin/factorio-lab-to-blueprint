"""Check our encoder against the viewer's independent TypeScript decoder.

The viewer is a sibling checkout, not a dependency.  Everything here degrades to
a clean skip when it or ``bun`` is absent -- CI without the sibling repo must
stay green, and the skip reason names exactly what is missing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BRIDGE = _REPO_ROOT / "scripts" / "crossvalidate.ts"
#: The decoder now lives in this repo, under ``web/``.  The sibling checkout is
#: still consulted after it, so a machine that has one keeps working, but the
#: in-tree copy is what a fresh clone gets and so it is what wins.
_IN_TREE = _REPO_ROOT / "web"
_DEFAULT_SIBLING = _REPO_ROOT.parent / "dsp-blueprint-viewer"


@dataclass(frozen=True, slots=True)
class CrossCheck:
    """One blueprint's verdict from the independent decoder."""

    ok: bool
    hash_valid: bool = False
    buildings: int = 0
    areas: int = 0
    version: int | None = None
    item_ids: dict[int, int] = field(default_factory=dict)
    bounds: dict[str, float] | None = None
    error: str | None = None


def bun_available() -> bool:
    return shutil.which("bun") is not None


def viewer_path() -> Path | None:
    """Resolve the viewer: ``$DSP_VIEWER_PATH``, then in-tree, then the sibling."""
    candidates: list[Path] = []
    override = os.environ.get("DSP_VIEWER_PATH")
    if override:
        candidates.append(Path(override))
    else:
        candidates.extend((_IN_TREE, _DEFAULT_SIBLING))

    for candidate in candidates:
        if (candidate / "src" / "format" / "index.ts").exists():
            return candidate
    return None


def viewer_deps_installed() -> bool:
    """Has anyone run ``bun install`` for the viewer yet?

    The source being present is not the same as the source being RUNNABLE.
    ``web/node_modules`` used to be committed, so this was always true by
    accident; untracking it made a fresh checkout fail these tests with
    ``Cannot find package 'fflate'`` instead of skipping, which is exactly what
    the module docstring promises never happens. `bun.lock` is the declaration
    and `bun install` is the fix -- the caller is told so rather than left to
    read a resolver error.
    """
    root = viewer_path()
    return root is not None and (root / "node_modules").is_dir()


class CrossValidationUnavailable(RuntimeError):
    """Raised only when the caller demanded strictness."""


def crossvalidate(
    blueprints: Sequence[str], *, strict: bool = False, timeout_s: float = 120.0
) -> list[CrossCheck]:
    """Parse ``blueprints`` with the viewer's decoder, one subprocess for all.

    Returns one ``CrossCheck`` per input, in order.  With ``strict`` false and
    the toolchain missing, returns an empty list so callers can skip.
    """
    root = viewer_path()
    if root is None or not bun_available():
        if strict:
            raise CrossValidationUnavailable(
                "cross-validation needs `bun` and a dsp-blueprint-viewer "
                "checkout (set DSP_VIEWER_PATH)"
            )
        return []

    payload = "\n".join(b.strip() for b in blueprints)
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["bun", str(_BRIDGE), str(root)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        if strict:
            raise CrossValidationUnavailable(
                f"bridge failed ({proc.returncode}): {proc.stderr[:400]}"
            )
        return []

    results: list[CrossCheck] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        if not raw.get("ok"):
            results.append(CrossCheck(ok=False, error=raw.get("error")))
            continue
        results.append(
            CrossCheck(
                ok=True,
                hash_valid=bool(raw.get("hashValid")),
                buildings=int(raw.get("buildings", 0)),
                areas=int(raw.get("areas", 0)),
                version=raw.get("version"),
                item_ids={int(k): int(v) for k, v in (raw.get("itemIds") or {}).items()},
                bounds=raw.get("bounds"),
            )
        )
    return results
