"""The table and graph backends live in `flab2bp.indexed` and nowhere else.

Ruling 3: "no caller imports the library, receives a Table or DataFrame, or
writes a query expression; the backend lives in one module per type; a test
greps the tree outside those modules for littletable/polars/networkx imports and
fails on any."
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED = _ROOT / "src" / "flab2bp" / "indexed"
_SEARCHED = (_ROOT / "src", _ROOT / "scripts", _ROOT / "tests")
_BANNED = re.compile(
    r"^\s*(?:import|from)\s+(littletable|polars|networkx|rustworkx|scipy)\b",
    re.MULTILINE,
)


def _python_files() -> list[Path]:
    out: list[Path] = []
    for root in _SEARCHED:
        out.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return out


def test_no_backend_import_outside_the_indexed_package() -> None:
    offenders: list[str] = []
    for path in _python_files():
        if _ALLOWED in path.parents or path == _ALLOWED:
            continue
        if path.name == "test_backend_containment.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in _BANNED.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(_ROOT)}:{line}: {match.group(1)}")
    assert not offenders, "backend imports outside flab2bp.indexed:\n" + "\n".join(offenders)


def test_the_indexed_package_exists_and_exports_nothing_library_shaped() -> None:
    from flab2bp import indexed

    for name in indexed.__all__:
        exported = getattr(indexed, name)
        module = getattr(exported, "__module__", "")
        assert module.startswith("flab2bp.indexed"), f"{name} leaks {module}"
