#!/bin/bash
# Build dist/YTKTV-<version>-macos-<arch>.pkg from the current checkout, for the
# architecture of the Python that runs it. build_universal_pkg.sh combines an
# arm64 and an x86_64 package into one installer.
#
# Optional environment:
#   CODESIGN_IDENTITY   "Developer ID Application: ..." to sign the app
#   INSTALLER_IDENTITY  "Developer ID Installer: ..." to sign the pkg
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD   notarize the signed pkg
# Without them the app is ad-hoc signed and macOS will ask the user to allow it.
set -euo pipefail

cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python3}"
VERSION="$("$PYTHON" -c 'import ytktv; print(ytktv.__version__)')"
ARCH="$(uname -m)"
IDENTIFIER="com.tonyd365.ytktv.${ARCH}"
OUT="dist/YTKTV-${VERSION}-macos-${ARCH}.pkg"

echo "==> Icon"
"$PYTHON" packaging/make_icon.py build/icon
ICONSET=build/icon/icon.iconset
rm -rf "$ICONSET" && mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" build/icon/icon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z "$((size * 2))" "$((size * 2))" build/icon/icon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o build/icon/icon.icns

echo "==> PyInstaller (YTKTV ${VERSION})"
"$PYTHON" -m PyInstaller packaging/ytktv.spec --noconfirm --distpath dist --workpath build/pyinstaller

echo "==> Code signing"
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  # PyInstaller already signed the nested binaries; seal the bundle itself.
  codesign --force --options runtime --timestamp \
    --entitlements packaging/macos/entitlements.plist -s "$CODESIGN_IDENTITY" dist/YTKTV.app
  codesign --verify --strict --verbose=2 dist/YTKTV.app
else
  codesign --force --deep -s - dist/YTKTV.app
fi

echo "==> Package"
STAGE=build/pkgroot
rm -rf "$STAGE" && mkdir -p "$STAGE"
ditto dist/YTKTV.app "$STAGE/YTKTV.app"
pkgbuild --analyze --root "$STAGE" build/component.plist >/dev/null
# Always install to /Applications instead of "wherever a copy already is".
/usr/libexec/PlistBuddy -c "Add :0:BundleIsRelocatable bool false" build/component.plist 2>/dev/null ||
  /usr/libexec/PlistBuddy -c "Set :0:BundleIsRelocatable false" build/component.plist
SIGN_ARGS=()
if [ -n "${INSTALLER_IDENTITY:-}" ]; then SIGN_ARGS=(--sign "$INSTALLER_IDENTITY"); fi
pkgbuild --root "$STAGE" --component-plist build/component.plist \
  --install-location /Applications --identifier "$IDENTIFIER" --version "$VERSION" \
  --scripts packaging/macos/scripts ${SIGN_ARGS[@]+"${SIGN_ARGS[@]}"} "$OUT"

if [ -n "${APPLE_ID:-}" ] && [ -n "${INSTALLER_IDENTITY:-}" ]; then
  echo "==> Notarizing"
  xcrun notarytool submit "$OUT" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$OUT"
fi

echo "==> Built $OUT"
