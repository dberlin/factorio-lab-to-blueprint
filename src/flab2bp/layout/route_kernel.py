"""Backend selection for the compiled routing loops.

``FLAB2BP_ROUTE_KERNEL`` forces one backend: ``python`` or ``cython``.
Unset, the first available of ``cython`` then ``python`` is used.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Literal

BackendName = Literal["python", "cython"]

_candidates: dict[BackendName, Callable[..., object] | None] = {"python": None}
try:
    from flab2bp.layout._route_kernel import astar_flat as _cython_astar

    _candidates["cython"] = _cython_astar
except ImportError:
    _candidates["cython"] = None

_PREFERENCE: tuple[BackendName, ...] = ("cython", "python")


def _choose() -> BackendName:
    forced = os.environ.get("FLAB2BP_ROUTE_KERNEL")
    if forced in ("python", "cython"):
        return forced  # type: ignore[return-value]
    for name in _PREFERENCE:
        if name == "python" or _candidates.get(name) is not None:
            return name
    return "python"


_backend: BackendName = _choose()
_compiled_astar: Callable[..., object] | None = _candidates.get(_backend)

#: The relaxed global search shares the one Cython extension with the A* loop
#: above, so a forced ``python`` backend disables both.
_compiled_relaxed: Callable[..., object] | None
try:
    from flab2bp.layout._route_kernel import relaxed_search_flat as _compiled_relaxed
except ImportError:
    _compiled_relaxed = None
if _backend == "python":
    _compiled_relaxed = None


def compiled_available() -> bool:
    return _compiled_astar is not None


def selected_backend() -> BackendName:
    return _backend if _compiled_astar is not None else "python"
