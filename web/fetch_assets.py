"""Fetch the browser runtimes the client-side arm needs.

Nothing here is a global install and nothing is a build step: it downloads
files into ``web/vendor/`` and stops.  Two sources:

* **Pyodide 0.28.3** -- CPython compiled to wasm, plus the thirteen wheels
  flab2bp's dependency closure needs.  Taken from the official CDN, which is
  where every Pyodide page gets them; we host them ourselves so the cold
  payload can be measured from our own server and so a solve provably touches
  nothing but static files.
* **or-tools-wasm 0.9.1** -- the CP-SAT runtime *and* the MPSolver runtime.
  Both are needed: flab2bp uses CP-SAT for layout and SCIP (inside MPSolver)
  for the rate solve.  The npm package unpacks to 332 MB; these two runtimes
  are the part a browser needs.

Run it from the repository root::

    python web/fetch_assets.py

It is idempotent -- a file whose size already matches is left alone.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PYODIDE_VERSION = "0.28.3"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"

#: Pyodide core.  ``pyodide-lock.json`` is what ``loadPackage`` consults, so it
#: has to be here even though we hand it an explicit wheel list.
PYODIDE_CORE = (
    "pyodide.js",
    "pyodide.mjs",
    "pyodide.asm.js",
    "pyodide.asm.wasm",
    "python_stdlib.zip",
    "pyodide-lock.json",
)

#: The transitive closure of micropip + numpy + pandas + sympy + pydantic +
#: protobuf, resolved against 0.28.3's lock file.  numpy and pandas are here
#: because ortools' own ``cp_model.py`` imports them; sympy because the rate
#: stage re-derives its balances in exact rationals; pydantic because the
#: FactorioLab dataset schema is pydantic models; protobuf because every
#: message that crosses the wasm seam is a serialized proto.
PYODIDE_WHEELS = (
    "annotated_types-0.7.0-py3-none-any.whl",
    "micropip-0.10.1-py3-none-any.whl",
    "mpmath-1.3.0-py3-none-any.whl",
    "numpy-2.2.5-cp313-cp313-pyodide_2025_0_wasm32.whl",
    "pandas-2.3.1-cp313-cp313-pyodide_2025_0_wasm32.whl",
    "protobuf-6.31.1-cp313-cp313-pyodide_2025_0_wasm32.whl",
    "pydantic-2.10.6-py3-none-any.whl",
    "pydantic_core-2.27.2-cp313-cp313-pyodide_2025_0_wasm32.whl",
    "python_dateutil-2.9.0.post0-py2.py3-none-any.whl",
    "pytz-2025.2-py2.py3-none-any.whl",
    "six-1.17.0-py2.py3-none-any.whl",
    "sympy-1.13.3-py3-none-any.whl",
    "typing_extensions-4.14.1-py3-none-any.whl",
)

ORTOOLS_NPM = "or-tools-wasm@0.9.1"
#: Only the MPSolver runtime is fetched: the CP-SAT runtime and every
#: ``browser/*.js`` module are small enough to live in git and are already
#: committed.  ``mp_solver_runtime.wasm`` is 19 MB, which is not.
ORTOOLS_WANT = (
    ("package/build/javascript/wasm/mp_solver_runtime.js", "wasm/mp_solver_runtime.js"),
    ("package/build/javascript/wasm/mp_solver_runtime.wasm", "wasm/mp_solver_runtime.wasm"),
)


def _download(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - fixed https
        body = response.read()
    dest.write_bytes(body)
    return len(body)


def fetch_pyodide(root: Path, *, force: bool) -> int:
    out = root / "vendor" / "pyodide"
    total = 0
    for name in (*PYODIDE_CORE, *PYODIDE_WHEELS):
        dest = out / name
        if dest.exists() and not force:
            total += dest.stat().st_size
            continue
        size = _download(PYODIDE_CDN + name, dest)
        print(f"  {name}  {size / 1048576:.2f} MB")
        total += size
    return total


def fetch_ortools(root: Path, *, force: bool) -> int:
    out = root / "vendor" / "ortools"
    missing = [(src, dst) for src, dst in ORTOOLS_WANT if force or not (out / dst).exists()]
    if missing:
        if shutil.which("npm") is None:
            raise SystemExit(
                "npm is needed to fetch the or-tools MPSolver runtime "
                f"({', '.join(dst for _, dst in missing)}). Install Node, or copy the "
                f"files out of {ORTOOLS_NPM} by hand."
            )
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(  # noqa: S603
                ["npm", "pack", ORTOOLS_NPM],  # noqa: S607
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            tarball = next(Path(tmp).glob("*.tgz"))
            with tarfile.open(tarball) as archive:
                for src, dst in missing:
                    member = archive.extractfile(src)
                    if member is None:
                        raise SystemExit(f"{ORTOOLS_NPM} has no {src}")
                    target = out / dst
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(member.read())
                    print(f"  {dst}  {target.stat().st_size / 1048576:.2f} MB")
    return sum((out / dst).stat().st_size for _, dst in ORTOOLS_WANT)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-download files already present")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parent
    print(f"pyodide {PYODIDE_VERSION} -> {root / 'vendor' / 'pyodide'}")
    pyodide_bytes = fetch_pyodide(root, force=args.force)
    print(f"{ORTOOLS_NPM} -> {root / 'vendor' / 'ortools'}")
    ortools_bytes = fetch_ortools(root, force=args.force)
    print(
        f"\npyodide {pyodide_bytes / 1048576:.1f} MB, "
        f"or-tools MPSolver {ortools_bytes / 1048576:.1f} MB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
