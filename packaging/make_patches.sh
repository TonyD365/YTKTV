#!/bin/bash
# Patches from the previous release to this one, for updates within a major version.
#
#   packaging/make_patches.sh macos              (in the macos-universal job)
#   packaging/make_patches.sh windows APP ARCH   (in a Windows build job; also writes
#                                                 APP-VERSION-windows-ARCH-files.zip)
#
# Needs GH_TOKEN, GH_REPO and TAG. Writes dist/patches/*.zip. Any trouble here only
# means no patch: users then get the installer, so this never fails the release.
set -uo pipefail
PY="${PYTHON:-python3}"
NEW="${TAG#v}"
mkdir -p dist/patches
if [ "$1" = windows ]; then
  # This build's files, attached to the release: the next release makes its patch from
  # them. (Unpacking or running the old installer on the runner did not work.)
  folder="YTKTV"; [ "$2" = YTKTV-Desk ] && folder="YTKTV Desk"
  "$PY" -c "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2])" \
    "dist/patches/$2-$NEW-windows-$3-files" "dist/$folder"
fi
PREV_TAG="$(gh api "repos/$GH_REPO/releases?per_page=30" --jq \
  '[.[] | select(.draft | not) | select(.prerelease | not) | select(.tag_name != env.TAG)][0].tag_name')"
if [ -z "$PREV_TAG" ] || [ "$PREV_TAG" = "null" ]; then echo "no previous release"; exit 0; fi
OLD="${PREV_TAG#v}"
WORK="$(mktemp -d)"
mkdir -p dist/patches
echo "patches $OLD -> $NEW"

patch() { # APP OLD_DIR NEW_DIR TAG INSTALLER
  "$PY" scripts/make_patch.py patch "$2" "$3" dist/patches --app "$1" \
    --from "$OLD" --to "$NEW" --tag "$4" --installer "$5" || { echo "::warning::no patch for $1 $4"; return; }
  # Apply it as the app would, to a copy of the old build: only a patch that turns it into
  # exactly the new build is attached. Otherwise users get the installer, as without one.
  local zip="dist/patches/$1-patch-$OLD-$NEW-$4.zip"
  [ -f "$zip" ] || return 0
  if ! "$PY" scripts/make_patch.py verify "$2" "$3" "$zip"; then
    echo "::error::the $1 $4 patch did not turn $OLD into $NEW; it is not attached"
    rm -f "$zip"
    VERIFY_FAILED=1
  fi
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
    folder="YTKTV"; [ "$APP" = YTKTV-Desk ] && folder="YTKTV Desk"
    old_zip="$APP-$OLD-windows-$ARCH-files.zip"
    gh release download "$PREV_TAG" -p "$old_zip" -D "$WORK" || { echo "no $old_zip"; exit 0; }
    "$PY" -c "import shutil, sys; shutil.unpack_archive(sys.argv[1], sys.argv[2])" \
      "$WORK/$old_zip" "$WORK/old" || exit 0
    patch "$APP" "$WORK/old" "dist/$folder" "windows-$ARCH" "dist/$APP-$NEW-windows-$ARCH-setup.exe"
    ;;
esac
# A failed check shows in red on the release run (the step itself may not stop it).
[ -z "${VERIFY_FAILED:-}" ] || exit 1
exit 0
