#!/usr/bin/env bash
# Builds the plugin and packs it as a Thunderstore package, which is the format
# r2modman's "Import local mod" accepts.
#
#   ./build-zip.sh
#   -> tools/dsp-oracle/dist/flab2bp_oracle-<version>.zip
#
# The layout is flat on purpose.  r2modman reads `manifest.json` from the ARCHIVE
# ROOT and installs loose DLLs into `BepInEx/plugins/<mod>/` itself; a zip that
# instead carries its own `BepInEx/` tree imports as a mod with no plugin in it.
# Thunderstore also rejects the package outright if `icon.png` is not exactly
# 256x256, so the icon is generated rather than hand-cropped.
#
# Override the game location with DSP_MANAGED_DIR if it is not ~/Dyson Sphere Program.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dist="$here/dist"
stage="$dist/stage"

# One source of truth for the version: the manifest r2modman will read.
version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version_number"])' "$here/manifest.json")"
name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$here/manifest.json")"

managed_arg=()
if [[ -n "${DSP_MANAGED_DIR:-}" ]]; then
  managed_arg=(-p:DspManagedDir="$DSP_MANAGED_DIR")
fi

rm -rf "$stage"
mkdir -p "$stage"

python3 "$here/make-icon.py"
dotnet build "$here/FlabOracle.csproj" -c Release "${managed_arg[@]}"

cp "$here/bin/Release/FlabOracle.dll" "$stage/"
cp "$here/manifest.json" "$here/icon.png" "$here/README.md" "$stage/"

zipfile="$dist/$name-$version.zip"
rm -f "$zipfile"
# -j would be wrong for a nested layout, but everything here is already flat and
# `zip .` from inside the stage keeps manifest.json at the root where it must be.
(cd "$stage" && zip -q -r "$zipfile" .)
rm -rf "$stage"

echo "built $zipfile"
unzip -l "$zipfile"
