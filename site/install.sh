#!/bin/bash
# Install YTKTV (or YTKTV Desk) from the latest GitHub release.
#
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash -s -- --desk
#
# macOS: downloads the universal .pkg and installs it with the system's installer (it asks
# for your password once). Downloaded this way, macOS does not quarantine it, so there is
# no "damaged" warning and no xattr step.
# Linux: puts the AppImage in ~/Applications and makes it runnable.
set -euo pipefail

REPO="TonyD365/YTKTV"
APP="YTKTV"
for arg in "$@"; do
  case "$arg" in
    --desk) APP="YTKTV-Desk" ;;
    -h|--help) sed -n '2,10p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $arg (use --desk for YTKTV Desk)" >&2; exit 1 ;;
  esac
done

say() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) SUFFIX="macos-universal.pkg" ;;
  Linux)
    case "$(uname -m)" in
      x86_64|amd64) SUFFIX="linux-x86_64.AppImage" ;;
      aarch64|arm64) SUFFIX="linux-aarch64.AppImage" ;;
      *) fail "No Linux build for $(uname -m)." ;;
    esac ;;
  *) fail "This script is for macOS and Linux. On Windows: winget install TonyD365.YTKTV" ;;
esac

say "Looking up the latest release…"
RELEASE=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")
# The asset whose name is APP-<version>-<suffix> (YTKTV must not match YTKTV-Desk).
URL=$(printf '%s' "$RELEASE" | grep -o '"browser_download_url": *"[^"]*"' | cut -d'"' -f4 \
  | grep -E "/${APP}-[0-9][^/]*-${SUFFIX}\$" | head -n 1 || true)
[ -n "$URL" ] || fail "The latest release has no ${APP} file for this computer yet. Try again in a while."
NAME="${URL##*/}"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
say "Downloading ${NAME}…"
curl -fL --progress-bar -o "$WORK/$NAME" "$URL"

# Check the download against the release's SHA256SUMS, when it has one.
SUMS_URL=$(printf '%s' "$RELEASE" | grep -o '"browser_download_url": *"[^"]*SHA256SUMS"' | cut -d'"' -f4 || true)
if [ -n "$SUMS_URL" ]; then
  EXPECTED=$(curl -fsSL "$SUMS_URL" | grep " \*\?$NAME\$" | cut -d' ' -f1 || true)
  if [ -n "$EXPECTED" ]; then
    if command -v sha256sum >/dev/null; then ACTUAL=$(sha256sum "$WORK/$NAME" | cut -d' ' -f1)
    else ACTUAL=$(shasum -a 256 "$WORK/$NAME" | cut -d' ' -f1); fi
    [ "$ACTUAL" = "$EXPECTED" ] || fail "The download is damaged (checksum mismatch). Please try again."
    say "Checksum OK."
  fi
fi

case "$SUFFIX" in
  *.pkg)
    say "Installing (macOS asks for your password)…"
    sudo installer -pkg "$WORK/$NAME" -target /
    LABEL="${APP/-/ }"
    say "Done. Open ${LABEL} from Applications or Launchpad."
    ;;
  *.AppImage)
    mkdir -p "$HOME/Applications"
    TARGET="$HOME/Applications/${APP}.AppImage"
    mv "$WORK/$NAME" "$TARGET"
    chmod +x "$TARGET"
    say "Done. Run it with: $TARGET"
    ;;
esac
