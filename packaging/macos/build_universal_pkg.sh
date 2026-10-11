#!/bin/bash
# Combine an Apple Silicon and an Intel package into one installer that puts
# the right build of YTKTV on whichever Mac it runs on.
#
#   packaging/macos/build_universal_pkg.sh ARM64.pkg X86_64.pkg VERSION [OUT_DIR]
#
# Optional environment (see build_pkg.sh): INSTALLER_IDENTITY, APPLE_ID,
# APPLE_TEAM_ID, APPLE_APP_PASSWORD.
set -euo pipefail

ARM_PKG="$1"
INTEL_PKG="$2"
VERSION="$3"
OUT_DIR="${4:-dist}"
OUT="$OUT_DIR/YTKTV-${VERSION}-macos-universal.pkg"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$ARM_PKG" "$WORK/ytktv-arm64.pkg"
cp "$INTEL_PKG" "$WORK/ytktv-x86_64.pkg"

# Each choice is selected only on its own architecture. Installer itself runs
# natively, so hw.optional.arm64 is reliable even for apps under Rosetta.
cat > "$WORK/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>YTKTV</title>
    <options customize="never" require-scripts="false" hostArchitectures="arm64,x86_64"/>
    <script>
    function isAppleSilicon() { return system.sysctl('hw.optional.arm64') == 1; }
    </script>
    <choices-outline>
        <line choice="arm64"/>
        <line choice="x86_64"/>
    </choices-outline>
    <choice id="arm64" title="YTKTV (Apple Silicon)" visible="false"
            selected="isAppleSilicon()" enabled="isAppleSilicon()">
        <pkg-ref id="com.tonyd365.ytktv.arm64"/>
    </choice>
    <choice id="x86_64" title="YTKTV (Intel)" visible="false"
            selected="!isAppleSilicon()" enabled="!isAppleSilicon()">
        <pkg-ref id="com.tonyd365.ytktv.x86_64"/>
    </choice>
    <pkg-ref id="com.tonyd365.ytktv.arm64" version="${VERSION}">ytktv-arm64.pkg</pkg-ref>
    <pkg-ref id="com.tonyd365.ytktv.x86_64" version="${VERSION}">ytktv-x86_64.pkg</pkg-ref>
</installer-gui-script>
XML

mkdir -p "$OUT_DIR"
SIGN_ARGS=()
if [ -n "${INSTALLER_IDENTITY:-}" ]; then SIGN_ARGS=(--sign "$INSTALLER_IDENTITY"); fi
productbuild --distribution "$WORK/distribution.xml" --package-path "$WORK" \
  ${SIGN_ARGS[@]+"${SIGN_ARGS[@]}"} "$OUT"

if [ -n "${APPLE_ID:-}" ] && [ -n "${INSTALLER_IDENTITY:-}" ]; then
  echo "==> Notarizing"
  xcrun notarytool submit "$OUT" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$OUT"
fi

echo "==> Built $OUT"
