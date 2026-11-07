from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from ytktv import patching, updater

WINDOWS = sys.platform == "win32"


def build(root: Path, files: dict[str, bytes], links: dict[str, str] | None = None) -> Path:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for rel, target in (links or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, root / rel)
    return root


OLD = {
    "app.exe": b"old program",
    "lib/qt.dll": b"big library that does not change" * 100,
    "lib/gone.dll": b"removed in the new build",
    "data/a b's.txt": b"old text",
}
NEW = {
    "app.exe": b"new program",
    "lib/qt.dll": OLD["lib/qt.dll"],
    "lib/new.dll": b"added",
    "data/a b's.txt": b"new text",
}


def versions(tmp_path: Path) -> tuple[Path, Path]:
    links = None if WINDOWS else {"Current": "lib"}
    old = build(tmp_path / "old", OLD, links)
    new = build(tmp_path / "new", NEW, links)
    if not WINDOWS:
        (new / "app.exe").chmod(0o755)
    (old / "unins000.exe").write_bytes(b"the uninstaller")  # never part of a patch
    return old, new


def make(tmp_path: Path) -> tuple[Path, Path, dict]:
    old, new = versions(tmp_path)
    archive = tmp_path / "p.zip"
    meta = {"app": "Test", "from": "4.0.1", "to": "4.0.2", "platform": "x"}
    manifest = patching.make_patch(old, new, archive, meta)
    return old, archive, manifest


def test_the_patch_holds_only_what_changed(tmp_path):
    _, archive, manifest = make(tmp_path)
    assert set(manifest["changed"]) == {"app.exe", "lib/new.dll", "data/a b's.txt"}
    assert set(manifest["deleted"]) == {"lib/gone.dll"}
    assert "lib/qt.dll" in manifest["same"]
    names = zipfile.ZipFile(archive).namelist()
    assert "files/lib/qt.dll" not in names and "files/app.exe" in names
    assert not any("unins" in name for name in names)


def test_stage_refuses_paths_outside_the_app(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as out:
        manifest = {"changed": {"../x": {"sha": "0", "mode": 420}}, "deleted": {}, "same": {}}
        out.writestr(patching.MANIFEST, json.dumps(manifest))
        out.writestr("files/../x", b"x")
    with pytest.raises(RuntimeError, match="bad path"):
        patching.stage(archive, tmp_path / "staged")


def test_a_damaged_patch_file_is_refused(tmp_path):
    _, archive, manifest = make(tmp_path)
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(broken, "w") as out:
        for name in src.namelist():
            data = src.read(name)
            out.writestr(name, b"tampered" if name == "files/app.exe" else data)
    with pytest.raises(RuntimeError, match="damaged"):
        patching.stage(broken, tmp_path / "staged")


def test_the_patch_only_fits_the_build_it_was_made_from(tmp_path):
    old, archive, _ = make(tmp_path)
    manifest = patching.stage(archive, tmp_path / "staged")
    assert patching.check_base(manifest, old)
    (old / "lib/qt.dll").write_bytes(b"another build")
    assert not patching.check_base(manifest, old)


def run_patch(tmp_path: Path, old: Path, staged: Path, manifest: dict) -> Path:
    marker = tmp_path / "patch-failed-4.0.2"
    if WINDOWS:
        script = staged / "apply.ps1"
        dead = 2**22  # no such process: nothing to wait for
        script.write_text(
            patching.powershell_script(manifest, staged, old, marker, dead), encoding="utf-8-sig"
        )
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    else:
        script = staged / "apply.sh"
        script.write_text(patching.shell_script(manifest, staged, old, marker))
        command = ["/bin/sh", str(script)]
    subprocess.run(command, check=False, timeout=120)
    return marker


def test_the_patch_turns_the_old_build_into_the_new_one(tmp_path):
    old, archive, _ = make(tmp_path)
    staged = tmp_path / "staged"
    manifest = patching.stage(archive, staged)
    marker = run_patch(tmp_path, old, staged, manifest)
    assert not marker.exists(), marker.read_text()
    result = patching.scan(old)
    assert result == patching.scan(tmp_path / "new")
    assert (old / "unins000.exe").exists()  # the uninstaller stays
    assert not (staged / "backup").exists()


def test_a_bad_file_puts_the_old_build_back(tmp_path):
    old, archive, _ = make(tmp_path)
    before = patching.scan(old)
    staged = tmp_path / "staged"
    manifest = patching.stage(archive, staged)
    (staged / "files" / "lib/new.dll").write_bytes(b"corrupted after the check")
    marker = run_patch(tmp_path, old, staged, manifest)
    assert marker.exists()
    assert patching.scan(old) == before


@pytest.mark.skipif(WINDOWS, reason="the macOS launcher is a POSIX script")
def test_the_macos_launcher_asks_for_the_password_only_when_needed(tmp_path):
    apply, root, marker = tmp_path / "apply.sh", tmp_path / "YTKTV.app", tmp_path / "m"
    plain = patching.macos_launcher(apply, root, marker, 123, admin=False)
    assert "osascript" not in plain and "kill -0 123" in plain and "open " in plain
    marker = tmp_path / "patch-failed-4.1.1"
    admin = patching.macos_launcher(apply, root, marker, 123, admin=True)
    assert "administrator privileges" in admin and "with prompt" in admin
    assert "YTKTV is installing its update to 4.1.1" in admin


def test_app_root():
    mac = "/Applications/YTKTV.app/Contents/MacOS/YTKTV"
    assert patching.app_root(mac, "Darwin").name == "YTKTV.app"
    assert patching.app_root("/opt/YTKTV/YTKTV.exe", "Windows").name == "YTKTV"


def _release(names: list[str]):
    data = {
        "tag_name": "v4.0.2",
        "draft": False,
        "prerelease": False,
        "html_url": "https://example.invalid",
        "assets": [
            {"name": n, "browser_download_url": f"https://dl.invalid/{n}", "size": 10}
            for n in names
        ],
    }
    return lambda url: json.dumps(data).encode()


INSTALLER = "YTKTV-4.0.2-windows-x64-setup.exe"
PATCH = "YTKTV-patch-4.0.1-4.0.2-windows-x64.zip"


def test_an_update_within_the_major_version_offers_the_patch():
    fetch = _release([INSTALLER, PATCH, "SHA256SUMS"])
    args = {"fetch": fetch, "suffixes": ["windows-x64-setup.exe"], "tag_for_patch": "windows-x64"}
    info = updater.check_for_update("4.0.1", **args)
    assert info is not None and info.patch_name == PATCH and info.asset_name == INSTALLER
    # Skipped a version: the patch is from 4.0.1, so 4.0.0 gets the installer.
    info = updater.check_for_update("4.0.0", **args)
    assert info is not None and info.patch_name is None
    # A Desk never takes the room's patch.
    info = updater.check_for_update("4.0.1", app="YTKTV-Desk", **args)
    assert info is None or info.patch_name is None


def test_a_new_major_version_is_always_the_installer():
    fetch = _release([INSTALLER, "YTKTV-patch-3.9.0-4.0.2-windows-x64.zip", "SHA256SUMS"])
    info = updater.check_for_update(
        "3.9.0", fetch=fetch, suffixes=["windows-x64-setup.exe"], tag_for_patch="windows-x64"
    )
    assert info is not None and info.patch_name is None


def test_download_uses_the_patch_and_falls_back_to_the_installer(tmp_path, monkeypatch):
    old, archive, _ = make(tmp_path)
    data = {PATCH: archive.read_bytes(), INSTALLER: b"whole installer"}
    sums = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in data.items())

    class Response:
        def __init__(self, body: bytes) -> None:
            self.body, self.headers = body, {"Content-Length": str(len(body))}

        def read(self, _n: int = -1) -> bytes:
            body, self.body = self.body, b""
            return body

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(
        updater, "urlopen", lambda request, timeout: Response(data[request.full_url.split("/")[-1]])
    )
    info = updater.UpdateInfo(
        version="4.0.2", tag="v4.0.2", asset_name=INSTALLER,
        asset_url=f"https://dl.invalid/{INSTALLER}", checksum_url="https://dl.invalid/SHA256SUMS",
        notes="", page_url="", patch_name=PATCH, patch_url=f"https://dl.invalid/{PATCH}",
        current="4.0.1", app="Test",
    )  # fmt: skip
    got = updater.download_update(info, tmp_path / "dl", fetch=lambda url: sums.encode(), root=old)
    assert got.is_dir() and got.name == "patch-4.0.2"
    (old / "lib/qt.dll").write_bytes(b"not the build the patch is for")
    got = updater.download_update(info, tmp_path / "dl", fetch=lambda url: sums.encode(), root=old)
    assert got.name == INSTALLER


def _make_patch_script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "make_patch.py"
    spec = importlib.util.spec_from_file_location("make_patch_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_release_checks_each_patch_by_applying_it(tmp_path, capsys):
    script = _make_patch_script()
    old, archive, _ = make(tmp_path)
    assert script.verify(old, tmp_path / "new", archive) == 0
    assert "verified" in capsys.readouterr().out
    # A patch that does not give the new build is caught (and the old build is untouched).
    (tmp_path / "new" / "app.exe").write_bytes(b"a different new program")
    assert script.verify(old, tmp_path / "new", archive) == 1
    assert (old / "app.exe").read_bytes() == b"old program"
