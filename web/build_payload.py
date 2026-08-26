"""Build the two payloads the page loads into Pyodide.

* ``dist/pyshim.zip`` -- the ortools stand-in: ortools 9.11's own pure-Python
  ``cp_model.py`` and its generated protobuf modules, plus the three modules
  that replace what upstream implements in C++ (``cp_model_helper``,
  ``sorted_interval_list`` and ``swig_helper``, the last of which is the seam
  to the wasm solvers).  It goes on ``sys.path`` *ahead* of anything else, so
  ``from ortools.sat.python import cp_model`` inside flab2bp resolves here.
* ``dist/flab2bp-*.whl`` -- flab2bp itself, unmodified, including its vendored
  FactorioLab dataset.  Nothing in the browser build patches the package.

Run from anywhere::

    python web/build_payload.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
DIST = WEB / "dist"


def build_pyshim() -> Path:
    out = DIST / "pyshim.zip"
    source = WEB / "pyshim"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*.py")):
            archive.write(path, path.relative_to(source).as_posix())
    return out


def build_wheel() -> Path:
    for stale in DIST.glob("flab2bp-*.whl"):
        stale.unlink()
    tool = shutil.which("uv")
    if tool is None:
        raise SystemExit(
            "uv is needed to build the flab2bp wheel; install it, or run `uv build` by hand"
        )
    subprocess.run(  # noqa: S603
        [tool, "build", "--wheel", "--out-dir", str(DIST)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    wheels = sorted(DIST.glob("flab2bp-*.whl"))
    if not wheels:
        raise SystemExit("uv build produced no wheel")
    return wheels[-1]


def main() -> int:
    DIST.mkdir(exist_ok=True)
    shim = build_pyshim()
    wheel = build_wheel()
    manifest = {"pyshim": shim.name, "wheel": wheel.name}
    (DIST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{shim.name}  {shim.stat().st_size / 1024:.0f} KB")
    print(f"{wheel.name}  {wheel.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
