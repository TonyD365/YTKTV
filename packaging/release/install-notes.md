
---

## Install

**One line** (checks the download, then installs; pick YTKTV, YTKTV Desk or both):

- macOS / Linux: `curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash`
- Windows (PowerShell): `irm https://tonyd365.github.io/YTKTV/install.ps1 | iex`, or `winget install TonyD365.YTKTV`

Already installed? YTKTV and YTKTV Desk update themselves (Settings → Updates).

**Or download the installer** from the files below:

| | YTKTV (the room) | YTKTV Desk (the front desk) |
|---|---|---|
| macOS (Apple Silicon and Intel) | `YTKTV-…-macos-universal.pkg` | `YTKTV-Desk-…-macos-universal.pkg` |
| Windows | `YTKTV-…-windows-x64-setup.exe` (ARM: `…-arm64-setup.exe`) | `YTKTV-Desk-…-windows-x64-setup.exe` |
| Linux | `YTKTV-…-linux-x86_64.AppImage` (ARM: `aarch64`) | `YTKTV-Desk-…-linux-x86_64.AppImage` |

You don't need the other files: `*-patch-*.zip` are the small updates the apps download themselves, `*-files.zip` are used to make the next patches, and `ytktv-installer-*` is the program the one-line install runs. `SHA256SUMS` lists every file's checksum.

The installers are not code-signed yet, so macOS and Windows may warn before the first start. Help: [README](https://github.com/TonyD365/YTKTV#install) · [Report a problem](https://github.com/TonyD365/YTKTV/issues)
