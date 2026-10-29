#!/bin/bash
# Build dist/YTKTV-<version>-linux-<x86_64 or aarch64>.AppImage from the current checkout.
# Needs libmpv installed (e.g. `sudo apt-get install libmpv2`) and appimagetool on PATH.
set -euo pipefail

cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python3}"
ARCH="$(uname -m)"  # x86_64 or aarch64
VERSION="$("$PYTHON" -c 'import ytktv; print(ytktv.__version__)')"
APPDIR=build/YTKTV.AppDir
OUT="dist/YTKTV-${VERSION}-linux-${ARCH}.AppImage"

"$PYTHON" packaging/make_icon.py build/icon
"$PYTHON" -m PyInstaller packaging/ytktv.spec --noconfirm --distpath dist --workpath build/pyinstaller

rm -rf "$APPDIR" && mkdir -p "$APPDIR/usr/lib"
cp -a dist/YTKTV "$APPDIR/usr/lib/ytktv"
cp build/icon/icon.png "$APPDIR/ytktv.png"
cat > "$APPDIR/ytktv.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=YTKTV
Comment=Karaoke machine powered by YouTube
Exec=YTKTV
Icon=ytktv
Categories=AudioVideo;Audio;Player;
Terminal=false
DESKTOP
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/ytktv/YTKTV" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

ARCH="$ARCH" appimagetool --no-appstream "$APPDIR" "$OUT"
echo "==> Built $OUT"
