#!/usr/bin/env bash
# Clone and build fontanf/packingsolver outside this repo.
#
# The binary is an optional experiment dependency: layout/packsolver.py skips
# cleanly when it is absent, so nothing here is required to build or test the
# project. Re-running is a no-op once the binary exists.
#
#   scripts/build_packingsolver.sh          # build if missing
#   PACKINGSOLVER_FORCE=1 scripts/...       # rebuild from scratch
#
# Prints the binary path on success.
set -euo pipefail

ROOT="${PACKINGSOLVER_ROOT:-$HOME/src/packingsolver}"
BIN="$ROOT/install/bin/packingsolver_rectangle"

if [[ -x "$BIN" && -z "${PACKINGSOLVER_FORCE:-}" ]]; then
    echo "$BIN"
    exit 0
fi

command -v cmake >/dev/null || { echo "cmake not found; brew install cmake" >&2; exit 1; }

mkdir -p "$(dirname "$ROOT")"
if [[ ! -d "$ROOT/.git" ]]; then
    git clone --depth 1 https://github.com/fontanf/packingsolver.git "$ROOT"
fi

cd "$ROOT"
# The project fetches its own dependencies at configure time, so a network
# round trip is expected on a cold build.
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel
cmake --install build --config Release --prefix install

[[ -x "$BIN" ]] || { echo "build finished but $BIN is missing" >&2; exit 1; }
echo "$BIN"
