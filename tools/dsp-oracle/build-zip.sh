#!/usr/bin/env bash
# Builds the plugin and packs it into a zip laid out to be extracted at the DSP
# game root, so BepInEx/plugins/flab2bp-oracle/FlabOracle.dll lands correctly.
#
#   ./build-zip.sh
#   -> tools/dsp-oracle/dist/flab2bp-oracle-<version>.zip
#
# Override the game location with DSP_MANAGED_DIR if it is not ~/Dyson Sphere Program.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
version="1.0.0"
dist="$here/dist"
stage="$dist/stage"

managed_arg=()
if [[ -n "${DSP_MANAGED_DIR:-}" ]]; then
  managed_arg=(-p:DspManagedDir="$DSP_MANAGED_DIR")
fi

rm -rf "$stage"
mkdir -p "$stage/BepInEx/plugins/flab2bp-oracle"

dotnet build "$here/FlabOracle.csproj" -c Release "${managed_arg[@]}"

cp "$here/bin/Release/FlabOracle.dll" "$stage/BepInEx/plugins/flab2bp-oracle/"
cp "$here/README.md" "$stage/BepInEx/plugins/flab2bp-oracle/"

zipfile="$dist/flab2bp-oracle-$version.zip"
rm -f "$zipfile"
(cd "$stage" && zip -q -r "$zipfile" BepInEx)
rm -rf "$stage"

echo "built $zipfile"
unzip -l "$zipfile"
