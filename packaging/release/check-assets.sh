#!/usr/bin/env bash
# Fails when a published release is missing any installer people download.
# Usage: check-assets.sh v1.2.3 (needs GH_TOKEN and GH_REPO)
set -euo pipefail

version="${1#v}"
have="$(gh release view "$1" --json assets --jq '.assets[] | select(.size > 0) | .name')"
want=(SHA256SUMS ytktv-installer.sha256)
for target in darwin-arm64 darwin-x64 linux-arm64 linux-x64 windows-x64.exe; do
  want+=("ytktv-installer-$target.gz")
done
for app in YTKTV YTKTV-Desk; do
  want+=("$app-$version-macos-universal.pkg")
  for arch in aarch64 x86_64; do want+=("$app-$version-linux-$arch.AppImage"); done
  for arch in arm64 x64; do
    want+=("$app-$version-windows-$arch-setup.exe" "$app-$version-windows-$arch-files.zip")
  done
done

missing=0
for name in "${want[@]}"; do
  if ! grep -Fxq -- "$name" <<<"$have"; then
    echo "missing: $name"
    missing=1
  fi
done
[ "$missing" -eq 0 ] && echo "all ${#want[@]} release files are there"
exit "$missing"
