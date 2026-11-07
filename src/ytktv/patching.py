"""Small updates as patches: only the files that changed between two builds.

An update within the same major version (4.0.1 -> 4.0.2, 4.0.2 -> 4.1.0) can come as a
patch instead of the whole installer. The release workflow compares the installed files
of the previous build with the new one (:func:`make_patch`) and attaches a zip with the
files that changed and a manifest. The app downloads it, checks it against the files it
has (:func:`check_base`), and hands over to a small script that waits for the app to
quit, swaps the files, checks every new file's hash, and puts the old files back if
anything is wrong. A failed patch is remembered, and the next update is the installer.

macOS: the patch root is the .app bundle (in /Applications, owned by root, so the swap
asks for the admin password, as the installer does). Windows: the install folder, which
is the user's own; Inno Setup's uninstall entry is updated to the new version so the
Apps list and winget see it. Linux AppImages are one file and always update whole.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

MANIFEST = "manifest.json"
FAILED_MARKER = "patch-failed"
# Files the installer itself writes next to the app, never part of a build.
IGNORED = re.compile(r"^(unins\d+\.(exe|dat|msg)|\.DS_Store|\.update-backup)$", re.IGNORECASE)
# Inno Setup's uninstall entry of each app (AppId in packaging/windows/*.iss).
WINDOWS_APP_IDS = {
    "YTKTV": "{6B0C5B0E-6C1B-4D0B-9E0F-59A7C0E6B2A1}_is1",
    "YTKTV-Desk": "{C2E7A1D4-3F6B-4E58-9A21-7D0B5E4C8F13}_is1",
}
EXECUTABLES = {"YTKTV": "YTKTV", "YTKTV-Desk": "YTKTV Desk"}


def patch_tag(system: str, machine: str) -> str | None:
    """The platform part of a patch's name, or None where patches are not made."""
    machine = machine.lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return "macos-arm64" if arm else "macos-x86_64"
    if system == "Windows":
        return "windows-arm64" if arm else "windows-x64"
    return None


def patch_name(app: str, old: str, new: str, tag: str) -> str:
    return f"{app}-patch-{old}-{new}-{tag}.zip"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan(root: Path) -> dict[str, dict[str, Any]]:
    """Every file under *root*: {"sha", "mode"} or, for a symlink, {"link"}."""
    found: dict[str, dict[str, Any]] = {}

    def walk(folder: Path) -> None:
        for entry in sorted(os.scandir(folder), key=lambda e: e.name):
            if IGNORED.match(entry.name):
                continue
            path = Path(entry.path)
            rel = path.relative_to(root).as_posix()
            if entry.is_symlink():
                found[rel] = {"link": os.readlink(path)}
            elif entry.is_dir():
                walk(path)
            else:
                found[rel] = {"sha": _sha(path), "mode": stat.S_IMODE(entry.stat().st_mode)}

    walk(root)
    return found


def make_patch(old_root: Path, new_root: Path, out: Path, meta: dict[str, str]) -> dict[str, Any]:
    """Write the patch from *old_root* to *new_root* to *out*; returns its manifest."""
    old, new = scan(old_root), scan(new_root)
    changed = {
        rel: {**entry, "old": old.get(rel)} for rel, entry in new.items() if old.get(rel) != entry
    }
    manifest = {
        **meta,
        "changed": changed,
        "deleted": {rel: entry for rel, entry in old.items() if rel not in new},
        "same": {rel: entry for rel, entry in new.items() if rel not in changed},
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, indent=1))
        for rel, entry in changed.items():
            if "sha" in entry:
                archive.write(new_root / rel, f"files/{rel}")
    return manifest


def stage(patch: Path, dest: Path) -> dict[str, Any]:
    """Unpack a downloaded patch into *dest* and check every file in it."""
    import shutil

    shutil.rmtree(dest, ignore_errors=True)
    files = dest / "files"
    files.mkdir(parents=True)
    with zipfile.ZipFile(patch) as archive:
        manifest: dict[str, Any] = json.loads(archive.read(MANIFEST))
        for rel, entry in manifest["changed"].items():
            _safe(rel)
            target = files / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # Nothing is written through a link the patch made (it could lead out of dest).
            if not target.parent.resolve().is_relative_to(files.resolve()):
                raise RuntimeError(f"bad path in patch: {rel}")
            if "link" in entry:
                _safe_link(rel, str(entry["link"]))
                os.symlink(entry["link"], target)
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha", ""))):
                raise RuntimeError(f"bad hash in patch for {rel}")
            with archive.open(f"files/{rel}") as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
            os.chmod(target, int(entry["mode"]))
            if _sha(target) != entry["sha"]:
                raise RuntimeError(f"patch file {rel} is damaged")
    for rel in manifest["deleted"]:
        _safe(rel)
    (dest / MANIFEST).write_text(json.dumps(manifest))
    return manifest


def _safe(rel: str) -> None:
    parts = Path(rel).parts
    if not parts or Path(rel).is_absolute() or ".." in parts or ":" in rel:
        raise RuntimeError(f"bad path in patch: {rel}")


def _safe_link(rel: str, link: str) -> None:
    """A link in the app must point inside the app (relative, not climbing out of it)."""
    where = os.path.normpath(os.path.join(os.path.dirname(rel), link))
    if not link or os.path.isabs(link) or where == ".." or where.startswith(("../", "..\\")):
        raise RuntimeError(f"bad link in patch: {rel} -> {link}")


def _matches(path: Path, entry: dict[str, Any] | None) -> bool:
    if entry is None:
        return not os.path.lexists(path)
    if "link" in entry:
        return path.is_symlink() and os.readlink(path) == entry["link"]
    return path.is_file() and not path.is_symlink() and _sha(path) == entry["sha"]


def check_base(manifest: dict[str, Any], root: Path) -> bool:
    """True when the installed files are exactly what the patch was made from."""
    if not all(_matches(root / rel, e) for rel, e in manifest["same"].items()):
        return False
    if not all(_matches(root / rel, e.get("old")) for rel, e in manifest["changed"].items()):
        return False
    return all(_matches(root / rel, e) for rel, e in manifest["deleted"].items())


def app_root(executable: str | None = None, system: str | None = None) -> Path:
    """The folder a patch applies to: the .app bundle on macOS, else the install folder."""
    exe = Path(executable or sys.executable).resolve()
    if (system or sys.platform) in ("Darwin", "darwin"):
        return exe.parents[2]  # YTKTV.app/Contents/MacOS/YTKTV
    return exe.parent


def needs_admin(manifest: dict[str, Any], root: Path) -> bool:
    """Whether some folder the patch writes to is not ours to write."""
    folders = {root}
    for rel in (*manifest["changed"], *manifest["deleted"]):
        parent = (root / rel).parent
        while not parent.exists() and parent != root:
            parent = parent.parent
        folders.add(parent)
    return not all(os.access(folder, os.W_OK) for folder in folders)


def _moves(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(paths backed up before the swap, paths put in from the patch)."""
    backed = [r for r, e in manifest["changed"].items() if e.get("old") is not None]
    return backed + list(manifest["deleted"]), list(manifest["changed"])


def shell_script(
    manifest: dict[str, Any], staged: Path, root: Path, marker: Path, secure: bool = False
) -> str:
    """The POSIX script that swaps the files.

    *secure* is for running as root (an app in /Applications): the staged folder belongs to
    the user, so the script first copies the files into a folder only root can write and
    checks every one of them against the hashes written into this script, before it
    touches the app. It never writes into the user's folders either (no failure marker:
    the caller tells from its exit code), and the script itself is never saved anywhere
    the user can change it: it is handed to root as text.
    """
    q = shlex.quote
    backed, placed = _moves(manifest)
    lines = ["#!/bin/sh", "set -u"]
    if secure:
        files, backup = '"$work/files"', '"$work/backup"'
        lines += [
            # mktemp -d makes a fresh folder, mode 700, owned by whoever runs this (root).
            'work=$(mktemp -d "${TMPDIR:-/tmp}/ytktv-patch.XXXXXX") || exit 1',
            "trap 'rm -rf \"$work\"' EXIT",
            f'cp -RP {q(str(staged / "files"))} "$work/files" || exit 1',
        ]
        # Every file, as copied, before anything in the app changes.
        for rel, entry in manifest["changed"].items():
            path = f'"$work/files/"{q(rel)}'
            if "link" in entry:
                lines.append(
                    f'[ -L {path} ] && [ "$(readlink {path})" = {q(entry["link"])} ] || exit 1'
                )
            else:
                sha = f'"$(shasum -a 256 {path} | cut -c1-64)"'
                lines.append(f"[ ! -L {path} ] && [ {sha} = {q(entry['sha'])} ] || exit 1")
        fail = "fail() { restore; exit 1; }"
    else:
        files, backup = q(str(staged / "files")), q(str(staged / "backup"))
        fail = f"fail() {{ restore; : > {q(str(marker))}; exit 1; }}"

    def under(base: str, rel: str) -> str:
        return f"{base}/{q(rel)}"

    def parent(base: str, rel: str) -> str:
        return f'"$(dirname {under(base, rel)})"'

    lines.append("restore() {")
    for rel in placed:
        lines.append(f"  rm -rf {q(str(root / rel))}")
    for rel in backed:
        src, dst = under(backup, rel), q(str(root / rel))
        lines.append(
            f"  if [ -e {src} ] || [ -L {src} ]; then "
            f"mkdir -p {q(str((root / rel).parent))} && mv {src} {dst}; fi"
        )
    lines += ["}", fail]
    for rel in backed:
        app_file = q(str(root / rel))
        lines.append(
            f"mkdir -p {parent(backup, rel)} && mv {app_file} {under(backup, rel)} || fail"
        )
    for rel in placed:
        app_file, app_dir = q(str(root / rel)), q(str((root / rel).parent))
        lines.append(f"mkdir -p {app_dir} && mv {under(files, rel)} {app_file} || fail")
    for rel, entry in manifest["changed"].items():
        path = q(str(root / rel))
        if "link" in entry:
            lines.append(f'[ "$(readlink {path})" = {q(entry["link"])} ] || fail')
        else:
            lines.append(f'[ "$(shasum -a 256 {path} | cut -c1-64)" = {q(entry["sha"])} ] || fail')
    if not secure:
        lines.append(f"rm -rf {backup}")
    lines += ["exit 0", ""]
    return "\n".join(lines)


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def powershell_script(
    manifest: dict[str, Any], staged: Path, root: Path, marker: Path, pid: int
) -> str:
    """The Windows script: wait for the app, swap, check, update the Apps entry, restart."""
    backup = staged / "backup"
    backed, placed = _moves(manifest)
    app = str(manifest.get("app", "YTKTV"))
    exe = root / f"{EXECUTABLES.get(app, app)}.exe"
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"try {{ Wait-Process -Id {int(pid)} -Timeout 120 }} catch {{}}",
        "Start-Sleep -Milliseconds 500",
        "function Move-To($from, $to) {",
        "  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $to) | Out-Null",
        "  Move-Item -LiteralPath $from -Destination $to -Force",
        "}",
        # .NET, not Get-FileHash: that module is not always loaded.
        "function Hash-Of($path) {",
        "  $sha = [System.Security.Cryptography.SHA256]::Create()",
        "  $stream = [System.IO.File]::OpenRead($path)",
        "  try { $bytes = $sha.ComputeHash($stream) } finally { $stream.Dispose() }",
        "  return ([System.BitConverter]::ToString($bytes) -replace '-', '').ToLower()",
        "}",
        "function Restore {",
    ]
    for rel in placed:
        target = _ps(str(root / rel))
        lines.append(f"  Remove-Item -LiteralPath {target} -Force -ErrorAction SilentlyContinue")
    for rel in backed:
        src, dst = _ps(str(backup / rel)), _ps(str(root / rel))
        lines.append(f"  if (Test-Path -LiteralPath {src}) {{ Move-To {src} {dst} }}")
    lines += ["}", "try {"]
    for rel in backed:
        lines.append(f"  Move-To {_ps(str(root / rel))} {_ps(str(backup / rel))}")
    for rel in placed:
        lines.append(f"  Move-To {_ps(str(staged / 'files' / rel))} {_ps(str(root / rel))}")
    for rel, entry in manifest["changed"].items():
        path = _ps(str(root / rel))
        lines.append(
            f"  if ((Hash-Of {path}) -ne '{entry['sha']}') {{ throw 'bad file: ' + {path} }}"
        )
    key = WINDOWS_APP_IDS.get(app)
    if key:
        old, new = _ps(str(manifest["from"])), _ps(str(manifest["to"]))
        lines += [
            "  foreach ($hive in 'HKCU:', 'HKLM:') {",
            f'    $key = "$hive\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{key}"',
            "    if (Test-Path -LiteralPath $key) {",
            "      try {",
            f"        Set-ItemProperty -LiteralPath $key -Name DisplayVersion -Value {new}",
            "        $name = (Get-ItemProperty -LiteralPath $key).DisplayName",
            f"        if ($name) {{ Set-ItemProperty -LiteralPath $key -Name DisplayName "
            f"-Value $name.Replace({old}, {new}) }}",
            "      } catch {}",
            "    }",
            "  }",
        ]
    lines += [
        f"  Remove-Item -LiteralPath {_ps(str(backup))} -Recurse -Force "
        "-ErrorAction SilentlyContinue",
        "} catch {",
        "  Restore",
        f'  Set-Content -LiteralPath {_ps(str(marker))} -Value "$_"',  # why, for the log
        "}",
        f"Start-Process -FilePath {_ps(str(exe))}",
        "",
    ]
    return "\n".join(lines)


def admin_prompt(root: Path, marker: Path) -> str:
    """What the macOS password dialog says: which app, and why it needs the password."""
    app = root.stem
    version = marker.name.removeprefix("patch-failed-")
    return (
        f"{app} is installing its update to {version}. It needs your password to replace "
        f"the changed files of {root.name} in {root.parent}. Nothing else is touched."
    )


def macos_launcher(
    apply: Path | str, root: Path, marker: Path, pid: int, admin: bool, reopen: bool = True
) -> str:
    """Waits for the app to quit, runs the swap (asking for the password if needed), reopens.

    With *admin*, *apply* is the root script's text (see shell_script(secure=True)), passed
    to osascript as an argument, so root never runs a file the user could have changed.
    Without, it is the path of the script to run as the user.
    """
    q = shlex.quote
    if admin:
        run = (
            "osascript -e 'on run argv' -e 'do shell script (item 1 of argv) "
            "with prompt (item 2 of argv) with administrator privileges' "
            f"-e 'end run' {q(str(apply))} {q(admin_prompt(root, marker))} || : > {q(str(marker))}"
        )
    else:
        run = f"/bin/sh {q(str(apply))}"
    lines = [
        "#!/bin/sh",
        f"while kill -0 {int(pid)} 2>/dev/null; do sleep 0.5; done",
        run,
    ]
    if reopen:
        lines.append(f"open {q(str(root))}")
    return "\n".join(lines) + "\n"
