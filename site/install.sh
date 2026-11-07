#!/bin/bash
# Install YTKTV (or YTKTV Desk) from the latest GitHub release.
#
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash -s -- --desk
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash -s -- --room --desk
#   add --yes to accept the license without being asked (for scripts)
#
# In a terminal it is interactive: pick the app and accept the license with the arrow
# keys (space ticks YTKTV, YTKTV Desk or both). It shows the same welcome, license and finish pages as the installers
# (packaging/installer/). Without a terminal, or with --yes, it prints plain text.
#
# macOS: downloads the universal .pkg and installs it with the system's installer (it asks
# for your password once). Downloaded this way, macOS does not quarantine it, so there is
# no "damaged" warning and no xattr step.
# Linux: puts the AppImage in ~/Applications and makes it runnable.
set -euo pipefail

REPO="TonyD365/YTKTV"
ROOM=""
DESK=""
YES=""
for arg in "$@"; do
  case "$arg" in
    --room) ROOM=1 ;;
    --desk) DESK=1 ;;
    -y|--yes) YES=1 ;;
    -h|--help) sed -n '2,16p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $arg (use --room for YTKTV, --desk for YTKTV Desk, --yes to skip questions)" >&2; exit 1 ;;
  esac
done

# --- Looks ---------------------------------------------------------------------------
# Interactive only with a real terminal to read keys from (stdin is the script itself).
TUI=""
if [ -z "$YES" ] && [ "${TERM:-dumb}" != "dumb" ] && { : </dev/tty; } 2>/dev/null; then
  TUI=1
fi
if [ -n "$TUI" ] || [ -t 1 ]; then
  B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'
  PINK=$'\033[38;5;205m'; CYAN=$'\033[38;5;51m'; GREEN=$'\033[32m'; RED=$'\033[31m'
else
  B=""; D=""; R=""; PINK=""; CYAN=""; GREEN=""; RED=""
fi

say() { printf '%s==>%s %s\n' "$PINK$B" "$R" "$*"; }
ok() { printf '  %s✓%s %s\n' "$GREEN" "$R" "$*"; }
fail() {
  [ -n "$TUI" ] && printf '\033[?25h' >/dev/tty
  printf '  %s✗ Error:%s %s\n' "$RED$B" "$R" "$*" >&2
  exit 1
}
cleanup() {
  [ -n "$TUI" ] && printf '\033[?25h' >/dev/tty 2>/dev/null
  [ -n "${WORK:-}" ] && rm -rf "$WORK"
  return 0
}
trap cleanup EXIT
trap 'exit 130' INT

# A rounded box around the given lines: box "plain text|colour" ...
box() {
  local width=40 item text line
  for item in "$@"; do text="${item%%|*}"; [ ${#text} -gt $width ] && width=${#text}; done
  printf '%s╭%s╮%s\n' "$PINK" "$(printf '─%.0s' $(seq 1 $((width + 4))))" "$R"
  for item in "$@"; do
    text="${item%%|*}"; line="$text"; [ "$item" != "$text" ] && line="${item#*|}$text$R"
    printf '%s│%s  %s%*s  %s│%s\n' "$PINK" "$R" "$line" $((width - ${#text})) "" "$PINK" "$R"
  done
  printf '%s╰%s╯%s\n' "$PINK" "$(printf '─%.0s' $(seq 1 $((width + 4))))" "$R"
}

# Run a command with a spinner: spin "message" command args...
spin() {
  local message="$1"; shift
  if [ -z "$TUI" ]; then say "$message"; "$@"; return; fi
  "$@" &
  local pid=$! i=0 frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
  printf '\033[?25l' >/dev/tty
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r  %s%s%s %s' "$CYAN" "${frames[i++ % 10]}" "$R" "$message" >/dev/tty
    sleep 0.1
  done
  printf '\r\033[K' >/dev/tty
  printf '\033[?25h' >/dev/tty
  wait "$pid"
}

# Arrow-key menu: menu "question" "label|hint" ...  → sets CHOICE to the chosen index.
CHOICE=0
menu() {
  local question="$1"; shift
  local count=$# selected=0 key rest i label hint
  printf '\033[?25l' >/dev/tty
  printf '\n  %s%s%s\n' "$B" "$question" "$R" >/dev/tty
  while true; do
    i=0
    for item in "$@"; do
      label="${item%%|*}"; hint=""; [ "$item" != "$label" ] && hint="${item#*|}"
      if [ $i -eq $selected ]; then
        printf '\033[K  %s❯ %-14s%s %s%s%s\n' "$PINK$B" "$label" "$R" "$D" "$hint" "$R" >/dev/tty
      else
        printf '\033[K    %-14s %s%s%s\n' "$label" "$D" "$hint" "$R" >/dev/tty
      fi
      i=$((i + 1))
    done
    printf '\033[K\n  %s↑/↓ to move · Enter to choose · q to quit%s\n' "$D" "$R" >/dev/tty
    IFS= read -rsn1 key </dev/tty || key=q
    case "$key" in
      $'\033')
        IFS= read -rsn2 rest </dev/tty || rest=""
        case "$rest" in
          '[A'|'OA') selected=$(((selected + count - 1) % count)) ;;
          '[B'|'OB') selected=$(((selected + 1) % count)) ;;
        esac ;;
      k) selected=$(((selected + count - 1) % count)) ;;
      j) selected=$(((selected + 1) % count)) ;;
      ''|' ') break ;;
      q|Q) printf '\033[?25h' >/dev/tty; printf '\n'; fail "Cancelled, nothing was installed." ;;
    esac
    printf '\033[%dA' $((count + 2)) >/dev/tty
  done
  printf '\033[?25h' >/dev/tty
  CHOICE=$selected
}

# Checkboxes: checklist "question" "label|hint" ... → sets TICKED to "1 0 1 ..." (first ticked).
TICKED=""
checklist() {
  local question="$1"; shift
  local count=$# selected=0 key rest i label hint box ticks=(1)
  for ((i = 1; i < count; i++)); do ticks[i]=0; done
  printf '\033[?25l' >/dev/tty
  printf '\n  %s%s%s\n' "$B" "$question" "$R" >/dev/tty
  while true; do
    i=0
    for item in "$@"; do
      label="${item%%|*}"; hint=""; [ "$item" != "$label" ] && hint="${item#*|}"
      box="◯"; [ "${ticks[i]}" = 1 ] && box="${GREEN}◉${R}"
      if [ $i -eq $selected ]; then
        printf '\033[K  %s❯%s %s %s%-12s%s %s%s%s\n' "$PINK$B" "$R" "$box" "$B" "$label" "$R" "$D" "$hint" "$R" >/dev/tty
      else
        printf '\033[K    %s %-12s %s%s%s\n' "$box" "$label" "$D" "$hint" "$R" >/dev/tty
      fi
      i=$((i + 1))
    done
    printf '\033[K\n  %s↑/↓ to move · Space to tick · Enter to go on · q to quit%s\n' "$D" "$R" >/dev/tty
    IFS= read -rsn1 key </dev/tty || key=q
    case "$key" in
      $'\033')
        IFS= read -rsn2 rest </dev/tty || rest=""
        case "$rest" in
          '[A'|'OA') selected=$(((selected + count - 1) % count)) ;;
          '[B'|'OB') selected=$(((selected + 1) % count)) ;;
        esac ;;
      k) selected=$(((selected + count - 1) % count)) ;;
      j) selected=$(((selected + 1) % count)) ;;
      ' ') ticks[selected]=$((1 - ticks[selected])) ;;
      '')
        case " ${ticks[*]} " in *" 1 "*) break ;; esac ;;  # at least one
      q|Q) printf '\033[?25h' >/dev/tty; printf '\n'; fail "Cancelled, nothing was installed." ;;
    esac
    printf '\033[%dA' $((count + 2)) >/dev/tty
  done
  printf '\033[?25h' >/dev/tty
  TICKED="${ticks[*]}"
}

# --- What to install -----------------------------------------------------------------
case "$(uname -s)" in
  Darwin) SUFFIX="macos-universal.pkg"; SYSTEM="macOS" ;;
  Linux)
    SYSTEM="Linux"
    case "$(uname -m)" in
      x86_64|amd64) SUFFIX="linux-x86_64.AppImage" ;;
      aarch64|arm64) SUFFIX="linux-aarch64.AppImage" ;;
      *) fail "No Linux build for $(uname -m)." ;;
    esac ;;
  *) fail "This script is for macOS and Linux. On Windows: winget install TonyD365.YTKTV" ;;
esac

WORK=$(mktemp -d)
spin "Looking up the latest release…" \
  curl -fsSL -o "$WORK/release.json" "https://api.github.com/repos/$REPO/releases/latest" \
  || fail "Could not reach GitHub. Check the internet connection and try again."
RELEASE=$(cat "$WORK/release.json")
TAG=$(printf '%s' "$RELEASE" | grep -o '"tag_name": *"[^"]*"' | head -n 1 | cut -d'"' -f4)

if [ -n "$TUI" ]; then
  printf '\n'
  box "YTKTV Installer|$B" "${TAG:-latest} for ${SYSTEM}|$D" | sed 's/^/  /'
fi
if [ -z "$ROOM$DESK" ]; then
  ROOM=1
  if [ -n "$TUI" ]; then
    checklist "What do you want to install?" "YTKTV|for a karaoke room" "YTKTV Desk|for the front desk"
    set -- $TICKED
    ROOM=""; DESK=""; [ "$1" = 1 ] && ROOM=1; [ "$2" = 1 ] && DESK=1
  fi
fi
APPS=()
[ -n "$ROOM" ] && APPS+=("YTKTV")
[ -n "$DESK" ] && APPS+=("YTKTV-Desk")
label() { printf '%s' "${1/-/ }"; }
NAMES=$(label "${APPS[0]}"); [ ${#APPS[@]} -gt 1 ] && NAMES="YTKTV and YTKTV Desk"

# The asset whose name is APP-<version>-<suffix> (YTKTV must not match YTKTV-Desk).
url_of() {
  printf '%s' "$RELEASE" | grep -o '"browser_download_url": *"[^"]*"' | cut -d'"' -f4 \
    | grep -E "/${1}-[0-9][^/]*-${SUFFIX}\$" | head -n 1 || true
}
for app in "${APPS[@]}"; do
  [ -n "$(url_of "$app")" ] \
    || fail "The latest release has no $(label "$app") file for this computer yet. Try again in a while."
done

# --- Welcome and license -------------------------------------------------------------
# From the release's own tag, or from main when that tag does not have them yet.
RAW="https://raw.githubusercontent.com/$REPO/${TAG:-main}"
pages_of() { [ "$1" = "YTKTV-Desk" ] && echo desk || echo ytktv; }
page() {
  curl -fsSL "$RAW/$1" 2>/dev/null \
    || curl -fsSL "https://raw.githubusercontent.com/$REPO/main/$1" 2>/dev/null || true
}
show() { page "$1" | sed "s/^/  /; 1s/^  \\(.*\\)/  ${B}${CYAN}\\1${R}/"; }

for app in "${APPS[@]}"; do
  printf '\n'
  show "packaging/installer/$(pages_of "$app")-welcome.txt"
done
if [ -z "$YES" ]; then
  [ -n "$TUI" ] || fail "Cannot ask you to accept the license here. Read it at $RAW/LICENSE and run again with --yes."
  while true; do
    menu "Do you accept the YTKTV License?" "Accept|and install ${NAMES}" "View|read the license" "Cancel|install nothing"
    case "$CHOICE" in
      0) break ;;
      1) page LICENSE | ${PAGER:-less} >/dev/tty 2>&1 </dev/tty || page LICENSE ;;
      *) printf '\n'; fail "You did not accept the license, so nothing was installed." ;;
    esac
    printf '\033[7A\033[J' >/dev/tty
  done
fi
printf '\n'
ok "License accepted"

# --- Download and install ------------------------------------------------------------
SUMS_URL=$(printf '%s' "$RELEASE" | grep -o '"browser_download_url": *"[^"]*SHA256SUMS"' | cut -d'"' -f4 || true)
SUMS=""
[ -n "$SUMS_URL" ] && SUMS=$(curl -fsSL "$SUMS_URL" || true)
if command -v sha256sum >/dev/null; then sum_of() { sha256sum "$1" | cut -d' ' -f1; }
else sum_of() { shasum -a 256 "$1" | cut -d' ' -f1; }; fi
[ "$SUFFIX" = "macos-universal.pkg" ] && { say "Installing asks for your macOS password once…"; sudo -v </dev/tty 2>/dev/null || sudo -v; }

TARGETS=()
for app in "${APPS[@]}"; do
  URL=$(url_of "$app"); NAME="${URL##*/}"; LABEL=$(label "$app")
  printf '\n'
  say "${LABEL}: downloading ${NAME}…"
  curl -fL --progress-bar -o "$WORK/$NAME" "$URL" || fail "The download failed. Please try again."
  ok "Downloaded"
  # Check the download against the release's SHA256SUMS, when it has one.
  EXPECTED=$(printf '%s\n' "$SUMS" | grep " \*\?$NAME\$" | cut -d' ' -f1 || true)
  if [ -n "$EXPECTED" ]; then
    spin "Checking the download…" sum_of "$WORK/$NAME" >"$WORK/actual"
    [ "$(cat "$WORK/actual")" = "$EXPECTED" ] || fail "The download is damaged (checksum mismatch). Please try again."
    ok "Checksum OK"
  fi
  case "$SUFFIX" in
    *.pkg)
      spin "Installing ${LABEL}…" sudo installer -pkg "$WORK/$NAME" -target / >/dev/null \
        || fail "The installer failed."
      ;;
    *.AppImage)
      mkdir -p "$HOME/Applications"
      TARGET="$HOME/Applications/${app}.AppImage"
      mv "$WORK/$NAME" "$TARGET"
      chmod +x "$TARGET"
      TARGETS+=("$TARGET")
      ;;
  esac
  ok "Installed ${LABEL} ${TAG}"
done

for app in "${APPS[@]}"; do
  printf '\n'
  show "packaging/installer/$(pages_of "$app")-done.txt"
done
for target in ${TARGETS[@]+"${TARGETS[@]}"}; do printf '\n  Run it with: %s%s%s' "$B" "$target" "$R"; done
printf '\n\n'
