from __future__ import annotations

import sys


def test_supported_python_runtime() -> None:
    assert sys.version_info >= (3, 14), (
        f"Python 3.14 or newer is required; running {sys.version.split()[0]}"
    )
