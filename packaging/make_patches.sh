#!/bin/bash
# Patches from the previous release to this one, for updates within a major version.
#
#   packaging/make_patches.sh macos              (in the macos-universal job)
#   packaging/make_patches.sh windows APP ARCH   (in a Windows build job)
#
# Needs GH_TOKEN, GH_REPO and TAG. Writes dist/patches/*.zip. Any trouble here only
# means no patch: users then get the installer, so this never fails the release.
set -uo pipefail
PY="${PYTHON:-python3}"
NEW="${TAG#v}"
PREV_TAG="$(gh api "repos/$GH_REPO/releases?per_page=30" --jq \
  '[.[] | select(.draft | not) | select(.prerelease | not) | select(.tag_name != env.TAG)][0].tag_name')"
if [ -z "$PREV_TAG" ] || [ "$PREV_TAG" = "null" ]; then echo "no previous release"; exit 0; fi
OLD="${PREV_TAG#v}"
WORK="$(mktemp -d)"
mkdir -p dist/patches
echo "patches $OLD -> $NEW"

patch() { # APP OLD_DIR NEW_DIR TAG INSTALLER
  "$PY" scripts/make_patch.py patch "$2" "$3" dist/patches --app "$1" \
    --from "$OLD" --to "$NEW" --tag "$4" --installer "$5" || echo "::warning::no patch for $1 $4"
}

case "$1" in
  macos)
    for APP in YTKTV YTKTV-Desk; do
      old_pkg="$APP-$OLD-macos-universal.pkg"
      gh release download "$PREV_TAG" -p "$old_pkg" -D "$WORK" || continue
      parts=parts; [ "$APP" = YTKTV-Desk ] && parts=desk-parts
      for ARCH in arm64 x86_64; do
        old_app="$("$PY" scripts/make_patch.py unpack-pkg "$WORK/$old_pkg" "$ARCH" "$WORK/old-$APP-$ARCH")" || continue
        new_app="$("$PY" scripts/make_patch.py unpack-pkg "$parts/$APP-$NEW-macos-$ARCH.pkg" "$ARCH" "$WORK/new-$APP-$ARCH")" || continue
        patch "$APP" "$old_app" "$new_app" "macos-$ARCH" "dist/$APP-$NEW-macos-universal.pkg"
      done
    done
    ;;
  windows)
    APP="$2"; ARCH="$3"
    old_exe="$APP-$OLD-windows-$ARCH-setup.exe"
    gh release download "$PREV_TAG" -p "$old_exe" -D "$WORK" || exit 0
    folder="YTKTV"; [ "$APP" = YTKTV-Desk ] && folder="YTKTV Desk"
    old_dir="$WORK/old"
    # Unpack the installer rather than run it: run on the runner, it never returned.
    if innoextract --silent --extract --output-dir "$WORK/x" "$WORK/$old_exe" && [ -d "$WORK/x/app" ]; then
      mv "$WORK/x/app" "$old_dir"
    else
      echo "::warning::innoextract could not read $old_exe; trying a silent install"
      timeout 300 "$WORK/$old_exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /NOICONS \
        "/DIR=$(cygpath -w "$old_dir")" || exit 0
    fi
    patch "$APP" "$old_dir" "dist/$folder" "windows-$ARCH" "dist/$APP-$NEW-windows-$ARCH-setup.exe"
    ;;
esac
exit 0
