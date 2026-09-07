"""The index backend never leaks past ``layout/buildings.py``.

The user's ruling: whichever library backs the index, it is hidden behind the
domain abstraction.  Today the backend is plain dicts; if someone swaps in
``littletable`` or ``polars`` later, this test is what keeps the swap confined
to one file instead of spreading query expressions across the call sites.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "flab2bp"
BACKENDS = ("littletable", "polars", "networkx", "pandas")
OWNER = SRC / "layout" / "buildings.py"

_IMPORT = re.compile(r"^\s*(?:import|from)\s+(" + "|".join(BACKENDS) + r")\b", re.MULTILINE)


def test_no_module_outside_buildings_imports_an_index_backend() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{match.group(1)}"
        for path in SRC.rglob("*.py")
        if path != OWNER
        for match in _IMPORT.finditer(path.read_text())
    ]
    assert offenders == [], (
        "index-backend imports must stay inside layout/buildings.py; found: " + ", ".join(offenders)
    )


def test_buildings_public_methods_return_domain_types() -> None:
    """No public method may be annotated with a backend library's type."""
    source = OWNER.read_text()
    for backend in BACKENDS:
        assert f"{backend}." not in source or backend == "networkx", (
            f"{backend} type names must not appear in buildings.py's public surface"
        )
