#!/bin/bash
# Install YTKTV (or YTKTV Desk) from the latest GitHub release.
#
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash -s -- --desk
#   curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash -s -- --room --desk
#   add --yes to accept the license without being asked (for scripts)
#
# In a terminal it is interactive: pick the app and accept the license with the arrow
# keys (space ticks YTKTV, YTKTV Desk or both). It shows the same welcome, license and
# finish pages as the installers (packaging/installer/), says what is already installed,
# checks the disk space, closes a running copy, downloads with a progress bar (retrying and
# resuming when the network drops), offers mpv, and can open the app at the end.
# Without a terminal, or with --yes, it prints plain text and takes the defaults.
#
# In a terminal it first runs the full-screen installer program from the release
# (installer/, built with Ink like Claude Code's CLI), checked against SHA256SUMS. When the
# release has none for this computer, or with --plain, this script does the same itself.
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
PLAIN=""
for arg in "$@"; do
  case "$arg" in
    --plain) PLAIN=1 ;;
    --room) ROOM=1 ;;
    --desk) DESK=1 ;;
    -y|--yes) YES=1 ;;
    -h|--help) sed -n '2,23p' "$0" 2>/dev/null || true; exit 0 ;;
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

# --- The installer program -------------------------------------------------------------
run_program() {
  local target base work code
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) target="darwin-arm64" ;;
    Darwin-x86_64) target="darwin-x64" ;;
    Linux-x86_64|Linux-amd64) target="linux-x64" ;;
    Linux-aarch64|Linux-arm64) target="linux-arm64" ;;
    *) return 1 ;;
  esac
  base="${YTKTV_INSTALLER_BASE:-https://github.com/$REPO/releases/latest/download}"  # override for tests
  work=$(mktemp -d)
  printf '\033[2m  Getting the installer…\033[0m\r' >/dev/tty
  if ! curl -fsSL --retry 3 -o "$work/i.gz" "$base/ytktv-installer-$target.gz" 2>/dev/null; then
    printf '\033[K' >/dev/tty; rm -rf "$work"; return 1
  fi
  printf '\033[K' >/dev/tty
  # Its own checksum file is attached first, before the release's SHA256SUMS exists.
  expected=$( { curl -fsSL --retry 3 "$base/ytktv-installer.sha256" 2>/dev/null || curl -fsSL --retry 3 "$base/SHA256SUMS" 2>/dev/null; } \
    | grep " \*\?ytktv-installer-$target.gz\$" | cut -d' ' -f1 || true)
  if command -v sha256sum >/dev/null; then actual=$(sha256sum "$work/i.gz" | cut -d' ' -f1)
  else actual=$(shasum -a 256 "$work/i.gz" | cut -d' ' -f1); fi
  if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then rm -rf "$work"; return 1; fi
  # Named so that anything macOS shows names it ("YTKTV Installer"), not a temporary file.
  gunzip -c "$work/i.gz" > "$work/YTKTV Installer" && chmod +x "$work/YTKTV Installer" || { rm -rf "$work"; return 1; }
  code=0
  # The terminal's real device: the program gets no keys through the /dev/tty alias on macOS.
  term="/dev/$(ps -o tty= -p $$ 2>/dev/null | tr -d ' ')"
  { [ -c "$term" ] && : <"$term"; } 2>/dev/null || term=/dev/tty
  "$work/YTKTV Installer" "$@" <"$term" || code=$?
  rm -rf "$work"
  exit "$code"
}
if [ -n "$TUI" ] && [ -z "$PLAIN" ]; then
  args=()
  [ -n "$ROOM" ] && args+=(--room)
  [ -n "$DESK" ] && args+=(--desk)
  run_program ${args[@]+"${args[@]}"} || true
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
  if [ -z "$TUI" ]; then say "$message" >&2; "$@"; return; fi
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
  *) fail "This script is for macOS and Linux. On Windows: irm https://tonyd365.github.io/YTKTV/install.ps1 | iex" ;;
esac

WORK=$(mktemp -d)
spin "Looking up the latest release…" \
  curl -fsSL --retry 3 ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} \
    -o "$WORK/release.json" "https://api.github.com/repos/$REPO/releases/latest" \
  || fail "Could not reach GitHub. Check the internet connection and try again."
RELEASE=$(cat "$WORK/release.json")
TAG=$(printf '%s' "$RELEASE" | grep -o '"tag_name": *"[^"]*"' | head -n 1 | cut -d'"' -f4)
LATEST="${TAG#v}"

label() { printf '%s' "${1/-/ }"; }
app_path() {  # where the app is (or will be) installed
  case "$SUFFIX" in
    *.pkg) printf '/Applications/%s.app' "$(label "$1")" ;;
    *) printf '%s/Applications/%s.AppImage' "$HOME" "$1" ;;
  esac
}
installed_version() {
  local path; path=$(app_path "$1")
  case "$SUFFIX" in
    *.pkg)
      [ -d "$path" ] && { defaults read "$path/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "?"; } ;;
    *)
      [ -f "$path" ] && { cat "$path.version" 2>/dev/null || echo "?"; } ;;
  esac
  return 0
}
newer() {  # is version $1 newer than $2?
  [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)" = "$1" ]
}
status_of() {  # a short hint for the checklist
  local have; have=$(installed_version "$1")
  if [ -z "$have" ]; then printf 'not installed'
  elif [ "$have" = "?" ]; then printf 'installed, version unknown'
  elif [ "$have" = "$LATEST" ]; then printf '%s installed, up to date' "$have"
  elif newer "$LATEST" "$have"; then printf '%s installed → update to %s' "$have" "$LATEST"
  else printf '%s installed, newer than %s' "$have" "$LATEST"; fi
}

if [ -n "$TUI" ]; then
  printf '\n'
  box "YTKTV Installer|$B" "${TAG:-latest} for ${SYSTEM}|$D" | sed 's/^/  /'
fi
if [ -z "$ROOM$DESK" ]; then
  ROOM=1
  if [ -n "$TUI" ]; then
    checklist "What do you want to install?" \
      "YTKTV|for a karaoke room · $(status_of YTKTV)" "YTKTV Desk|for the front desk · $(status_of YTKTV-Desk)"
    set -- $TICKED
    ROOM=""; DESK=""; [ "$1" = 1 ] && ROOM=1; [ "$2" = 1 ] && DESK=1
  fi
fi
APPS=()
[ -n "$ROOM" ] && APPS+=("YTKTV")
[ -n "$DESK" ] && APPS+=("YTKTV-Desk")

# Already up to date: ask whether to install it again (without a terminal: skip it).
KEEP=()
for app in "${APPS[@]}"; do
  if [ "$(installed_version "$app")" = "$LATEST" ]; then
    if [ -n "$TUI" ]; then
      menu "$(label "$app") $LATEST is already installed." "Skip|keep it as it is" "Reinstall|download and install it again"
      [ "$CHOICE" -eq 1 ] && KEEP+=("$app")
    else
      ok "$(label "$app") $LATEST is already installed"
    fi
  else
    KEEP+=("$app")
  fi
done
[ ${#KEEP[@]} -gt 0 ] || { printf '\n'; ok "Nothing to do."; exit 0; }
APPS=("${KEEP[@]}")
NAMES=$(label "${APPS[0]}"); [ ${#APPS[@]} -gt 1 ] && NAMES="YTKTV and YTKTV Desk"

# The asset whose name is APP-<version>-<suffix> (YTKTV must not match YTKTV-Desk), and its size.
url_of() {
  printf '%s' "$RELEASE" | grep -o '"browser_download_url": *"[^"]*"' | cut -d'"' -f4 \
    | grep -E "/${1}-[0-9][^/]*-${SUFFIX}\$" | head -n 1 || true
}
size_of() {  # bytes, from the release's asset list ("size" comes just before the URL)
  local name; name=$(basename "$(url_of "$1")")
  printf '%s' "$RELEASE" | tr -d '\n' | grep -o "\"name\": *\"$name\".*" \
    | grep -o '"size": *[0-9]*' | head -n 1 | grep -o '[0-9]*$' || echo 0
}
mb() { echo $((($1 + 1048575) / 1048576)); }
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

# What is about to happen
printf '\n  %sWhat happens next%s\n' "$B$CYAN" "$R"
for app in "${APPS[@]}"; do
  have=$(installed_version "$app")
  what="install $LATEST"; [ -n "$have" ] && what="$have → $LATEST"
  printf '  - %s: %s, download %s MB, to %s\n' "$(label "$app")" "$what" "$(mb "$(size_of "$app")")" "$(app_path "$app")"
done
[ "$SUFFIX" = "macos-universal.pkg" ] && printf '  - macOS asks for your password once, to install into /Applications.\n'
printf '  - A running copy is closed first. Your settings and songs are kept.\n'

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

# --- Disk space ----------------------------------------------------------------------
# The download, plus the installed app (about 2.5 times the download), with some to spare.
NEED=0
for app in "${APPS[@]}"; do NEED=$((NEED + $(size_of "$app") * 7 / 2)); done
free_bytes() { df -Pk "$1" 2>/dev/null | awk 'NR == 2 { print $4 * 1024 }'; }
DEST="/Applications"; [ "$SUFFIX" = "macos-universal.pkg" ] || { mkdir -p "$HOME/Applications"; DEST="$HOME/Applications"; }
FREE=$(free_bytes "$DEST"); FREE=${FREE:-0}
if [ "$FREE" -gt 0 ] && [ "$FREE" -lt "$NEED" ]; then
  fail "Not enough disk space: $(mb "$NEED") MB needed, $(mb "$FREE") MB free. Free some space and try again."
fi
ok "Disk space OK ($(mb "$FREE") MB free, $(mb "$NEED") MB needed)"

# --- Close running copies ------------------------------------------------------------
running() {
  case "$SUFFIX" in
    *.pkg) pgrep -f "$(app_path "$1")/Contents/MacOS/" >/dev/null 2>&1 ;;
    *) pgrep -f "$(app_path "$1")" >/dev/null 2>&1 ;;
  esac
}
for app in "${APPS[@]}"; do
  running "$app" || continue
  if [ -n "$TUI" ]; then
    menu "$(label "$app") is running." "Close it|and go on" "Cancel|install nothing"
    [ "$CHOICE" -eq 0 ] || { printf '\n'; fail "Cancelled, nothing was installed."; }
  fi
  case "$SUFFIX" in
    *.pkg) osascript -e "quit app \"$(label "$app")\"" >/dev/null 2>&1 || true ;;
    *) pkill -f "$(app_path "$app")" 2>/dev/null || true ;;
  esac
  for _ in $(seq 1 30); do running "$app" || break; sleep 0.5; done
  if running "$app"; then
    case "$SUFFIX" in
      *.pkg) pkill -f "$(app_path "$app")/Contents/MacOS/" 2>/dev/null || true ;;
      *) pkill -9 -f "$(app_path "$app")" 2>/dev/null || true ;;
    esac
    sleep 1
  fi
  ok "Closed $(label "$app")"
done

# --- Download ------------------------------------------------------------------------
# A progress bar with MB, speed and time left; up to 5 tries, each going on where the last stopped.
bar() {  # bar DONE TOTAL SPEED
  local done=$1 total=$2 speed=$3 width=28 filled pct left eta full="" empty="" i
  [ "$total" -gt 0 ] || total=1
  pct=$((done * 100 / total)); [ $pct -gt 100 ] && pct=100
  filled=$((pct * width / 100))
  for ((i = 0; i < width; i++)); do if [ $i -lt $filled ]; then full+="█"; else empty+="░"; fi; done
  left="--:--"
  if [ "$speed" -gt 0 ]; then eta=$(((total - done) / speed)); left=$(printf '%d:%02d' $((eta / 60)) $((eta % 60))); fi
  printf '\r\033[K  %s%s%s%s%s %3d%%  %s / %s MB  %s MB/s  %s left' \
    "$PINK" "$full" "$D" "$empty" "$R" \
    "$pct" "$(mb "$done")" "$(mb "$total")" "$(awk "BEGIN { printf \"%.1f\", $speed / 1048576 }")" "$left" >/dev/tty
}
size_on_disk() { wc -c <"$1" 2>/dev/null | tr -d ' ' || echo 0; }
download() {  # download URL FILE TOTAL
  local url=$1 file=$2 total=$3 try pid now before then_ speed
  for try in 1 2 3 4 5; do
    if [ -z "$TUI" ]; then
      curl -fL -C - --progress-bar -o "$file" "$url" && return 0
    else
      curl -fsL -C - -o "$file" "$url" &
      pid=$!
      printf '\033[?25l' >/dev/tty
      before=$(size_on_disk "$file"); then_=$(date +%s); speed=0
      while kill -0 "$pid" 2>/dev/null; do
        sleep 0.25
        now=$(date +%s)
        if [ "$now" -gt "$then_" ]; then
          speed=$((($(size_on_disk "$file") - before) / (now - then_)))
          [ $((now - then_)) -ge 3 ] && { before=$(size_on_disk "$file"); then_=$now; }
        fi
        bar "$(size_on_disk "$file")" "$total" "$speed"
      done
      printf '\033[?25h' >/dev/tty
      if wait "$pid"; then bar "$total" "$total" "$speed"; printf '\n' >/dev/tty; return 0; fi
      printf '\n' >/dev/tty
    fi
    [ "$try" -lt 5 ] && { say "The download stopped; trying again ($((try + 1)) of 5)…"; sleep $((try * 2)); }
  done
  return 1
}

SUMS_URL=$(printf '%s' "$RELEASE" | grep -o '"browser_download_url": *"[^"]*SHA256SUMS"' | cut -d'"' -f4 || true)
SUMS=""
[ -n "$SUMS_URL" ] && SUMS=$(curl -fsSL --retry 3 "$SUMS_URL" || true)
if command -v sha256sum >/dev/null; then sum_of() { sha256sum "$1" | cut -d' ' -f1; }
else sum_of() { shasum -a 256 "$1" | cut -d' ' -f1; }; fi
[ "$SUFFIX" = "macos-universal.pkg" ] && { printf '\n'; say "Your Mac password is needed to put the apps in /Applications (typed here, not shown, not stored):"; sudo -v </dev/tty 2>/dev/null || sudo -v; }

# --- Install -------------------------------------------------------------------------
for app in "${APPS[@]}"; do
  URL=$(url_of "$app"); NAME="${URL##*/}"; LABEL=$(label "$app")
  printf '\n'
  say "${LABEL}: downloading ${NAME}"
  download "$URL" "$WORK/$NAME" "$(size_of "$app")" || fail "The download failed 5 times. Check the internet connection and try again."
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
      TARGET=$(app_path "$app")
      mv "$WORK/$NAME" "$TARGET"
      chmod +x "$TARGET"
      printf '%s\n' "$LATEST" >"$TARGET.version"
      ;;
  esac
  ok "Installed ${LABEL} ${LATEST}"
done

# --- mpv (YTKTV plays songs through it; the Desk does not need it) --------------------
mpv_found() {
  command -v mpv >/dev/null 2>&1 || [ -x /opt/homebrew/bin/mpv ] || [ -x /usr/local/bin/mpv ]
}
if [ -n "$ROOM" ] && ! mpv_found; then
  printf '\n'
  install_mpv=""
  case "$SYSTEM" in
    macOS)
      BREW=$(command -v brew || { [ -x /opt/homebrew/bin/brew ] && echo /opt/homebrew/bin/brew; } || { [ -x /usr/local/bin/brew ] && echo /usr/local/bin/brew; } || true)
      [ -n "$BREW" ] && install_mpv="$BREW install mpv" ;;
    Linux)
      if command -v apt-get >/dev/null; then install_mpv="sudo apt-get install -y mpv libmpv2"
      elif command -v dnf >/dev/null; then install_mpv="sudo dnf install -y mpv mpv-libs"
      elif command -v pacman >/dev/null; then install_mpv="sudo pacman -S --noconfirm mpv"
      elif command -v zypper >/dev/null; then install_mpv="sudo zypper install -y mpv"; fi ;;
  esac
  if [ -z "$install_mpv" ]; then
    say "YTKTV needs mpv to play songs. It will offer to install it when it first opens."
  else
    go=1
    if [ -n "$TUI" ]; then
      menu "YTKTV plays songs through mpv, which is not on this computer. Install it now?" \
        "Install mpv|runs: $install_mpv" "Later|YTKTV offers it when it first opens"
      [ "$CHOICE" -eq 0 ] || go=""
    else
      go=""
      say "YTKTV needs mpv to play songs. Install it with: $install_mpv"
    fi
    if [ -n "$go" ]; then
      printf '\n'
      if $install_mpv </dev/tty; then ok "Installed mpv"; else say "mpv was not installed; YTKTV will offer it when it first opens."; fi
    fi
  fi
fi

# --- Done ----------------------------------------------------------------------------
for app in "${APPS[@]}"; do
  printf '\n'
  show "packaging/installer/$(pages_of "$app")-done.txt"
done
open_app() {
  case "$SUFFIX" in
    *.pkg) open -a "$(app_path "$1")" ;;
    *) nohup "$(app_path "$1")" >/dev/null 2>&1 & ;;
  esac
}
if [ -n "$TUI" ]; then
  options=()
  for app in "${APPS[@]}"; do options+=("Open $(label "$app")|start it now"); done
  [ ${#APPS[@]} -gt 1 ] && options+=("Open both|start YTKTV and YTKTV Desk")
  options+=("Not now|close the installer")
  menu "Open it now?" "${options[@]}"
  if [ "$CHOICE" -lt ${#APPS[@]} ]; then open_app "${APPS[$CHOICE]}"
  elif [ ${#APPS[@]} -gt 1 ] && [ "$CHOICE" -eq ${#APPS[@]} ]; then for app in "${APPS[@]}"; do open_app "$app"; done
  fi
elif [ "$SUFFIX" != "macos-universal.pkg" ]; then
  for app in "${APPS[@]}"; do printf '\n  Run it with: %s%s%s' "$B" "$(app_path "$app")" "$R"; done
fi
printf '\n\n'
