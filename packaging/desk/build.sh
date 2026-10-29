#!/bin/bash
# Build the YTKTV Desk installer for this machine into dist/:
#   macOS  YTKTV-Desk-<version>-macos-<arch>.pkg   (installs to /Applications)
#   Linux  YTKTV-Desk-<version>-linux-<x86_64 or aarch64>.AppImage   (needs appimagetool)
# Windows uses packaging/windows/desk_installer.iss after PyInstaller instead.
#
# Optional on macOS: CODESIGN_IDENTITY, INSTALLER_IDENTITY (see packaging/macos/build_pkg.sh).
set -euo pipefail

cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python3}"
ARCH="$(uname -m)"  # x86_64 or aarch64
VERSION="$("$PYTHON" -c 'import ytktv; print(ytktv.__version__)')"
"$PYTHON" packaging/make_icon.py build/desk-icon src/ytktv/desk/assets/icon.png

if [ "$(uname)" = "Darwin" ]; then
  ICONSET=build/desk-icon/icon.iconset
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" build/desk-icon/icon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z "$((size * 2))" "$((size * 2))" build/desk-icon/icon.png \
      --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o build/desk-icon/icon.icns
fi

"$PYTHON" -m PyInstaller packaging/desk.spec --noconfirm --distpath dist --workpath build/desk

if [ "$(uname)" = "Darwin" ]; then
  APP="dist/YTKTV Desk.app"
  if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    codesign --force --options runtime --timestamp \
      --entitlements packaging/macos/entitlements.plist -s "$CODESIGN_IDENTITY" "$APP"
  else
    codesign --force --deep -s - "$APP"
  fi
  STAGE=build/desk-pkgroot
  rm -rf "$STAGE" && mkdir -p "$STAGE"
  ditto "$APP" "$STAGE/YTKTV Desk.app"
  pkgbuild --analyze --root "$STAGE" build/desk-component.plist >/dev/null
  /usr/libexec/PlistBuddy -c "Set :0:BundleIsRelocatable false" build/desk-component.plist
  SIGN_ARGS=()
  if [ -n "${INSTALLER_IDENTITY:-}" ]; then SIGN_ARGS=(--sign "$INSTALLER_IDENTITY"); fi
  OUT="dist/YTKTV-Desk-${VERSION}-macos-$(uname -m).pkg"
  pkgbuild --root "$STAGE" --component-plist build/desk-component.plist \
    --install-location /Applications --identifier "com.tonyd365.ytktv.desk.$(uname -m)" \
    --version "$VERSION" ${SIGN_ARGS[@]+"${SIGN_ARGS[@]}"} "$OUT"
else
  APPDIR=build/YTKTV-Desk.AppDir
  OUT="dist/YTKTV-Desk-${VERSION}-linux-${ARCH}.AppImage"
  rm -rf "$APPDIR" && mkdir -p "$APPDIR/usr/lib"
  cp -a "dist/YTKTV Desk" "$APPDIR/usr/lib/ytktv-desk"
  cp build/desk-icon/icon.png "$APPDIR/ytktv-desk.png"
  cat > "$APPDIR/ytktv-desk.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=YTKTV Desk
Comment=Staff terminal for YTKTV karaoke rooms
Exec=ytktv-desk
Icon=ytktv-desk
Categories=Office;
Terminal=false
DESKTOP
  cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/ytktv-desk/YTKTV Desk" "$@"
APPRUN
  chmod +x "$APPDIR/AppRun"
  ARCH="$ARCH" appimagetool --no-appstream "$APPDIR" "$OUT"
fi
echo "==> Built $OUT"
