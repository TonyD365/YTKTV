from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from ytktv.youtube import hd_unlock, search
from ytktv.youtube.hd_unlock import HdUnlock, deno_target


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [
        ("Darwin", "arm64", "aarch64-apple-darwin"),
        ("Darwin", "x86_64", "x86_64-apple-darwin"),
        ("Windows", "AMD64", "x86_64-pc-windows-msvc"),
        ("Windows", "ARM64", None),
        ("Linux", "x86_64", "x86_64-unknown-linux-gnu"),
        ("Linux", "aarch64", "aarch64-unknown-linux-gnu"),
        ("FreeBSD", "amd64", None),
    ],
)
def test_deno_target(system, machine, target):
    assert deno_target(system, machine) == target


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def make_fetch(deno_zip: bytes, provider_zip: bytes, checksum: str | None = None):
    requested = []

    def fetch(url: str, dest: Path) -> None:
        requested.append(url)
        if url.endswith(".sha256sum"):
            digest = checksum or hashlib.sha256(deno_zip).hexdigest()
            dest.write_text(f"{digest}  deno.zip\n")
        elif "denoland" in url:
            dest.write_bytes(deno_zip)
        else:
            dest.write_bytes(provider_zip)

    return fetch, requested


PROVIDER = zip_bytes(
    {
        "bgutil-ytdlp-pot-provider-2.0.2/README.md": b"readme",
        "bgutil-ytdlp-pot-provider-2.0.2/server/": b"",
        "bgutil-ytdlp-pot-provider-2.0.2/server/deno.json": b"{}",
        "bgutil-ytdlp-pot-provider-2.0.2/server/src/generate_once.ts": b"// ts",
        "bgutil-ytdlp-pot-provider-2.0.2/plugin/x.py": b"",
    }
)


def ok_run(command, **_kwargs):
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def bad_run(command, **_kwargs):
    return subprocess.CompletedProcess(command, 1, stdout="", stderr="npm exploded")


@pytest.fixture
def unlock(tmp_path, monkeypatch):
    monkeypatch.setattr(hd_unlock, "plugin_version", lambda: "2.0.2")
    return HdUnlock(tmp_path / "hd", system="Linux")


def test_install_downloads_verifies_and_sets_up(unlock):
    fetch, requested = make_fetch(zip_bytes({"deno": b"#!binary"}), PROVIDER)
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs["cwd"], kwargs["env"]["DENO_DIR"]))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    assert unlock.supported() and not unlock.installed()
    lines: list[str] = []
    unlock.install(lines.append, fetch=fetch, run=run)

    assert unlock.installed()
    assert unlock.deno.read_bytes() == b"#!binary"
    if os.name != "nt":  # Windows has no executable bit
        assert unlock.deno.stat().st_mode & 0o111
    assert (unlock.server_home / "src" / "generate_once.ts").exists()
    assert not (unlock.root / "README.md").exists()  # only the server folder is kept
    assert any(url.endswith("/tags/2.0.2.zip") for url in requested)  # generator matches the plugin
    assert any(f"deno-{deno_target('Linux')}.zip" in url for url in requested)
    command, cwd, deno_dir = commands[0]
    assert command[:2] == [str(unlock.deno), "install"] and cwd == str(unlock.server_home)
    assert deno_dir == str(unlock.deno_dir)
    assert len(lines) == 3 and not list(unlock.root.glob("*.zip"))

    options = unlock.ytdlp_options()
    assert options["js_runtimes"] == {"deno": {"path": str(unlock.deno)}}
    assert options["extractor_args"]["youtube"]["player_client"] == ["tv_simply"]
    assert options["extractor_args"]["youtubepot-bgutilscript"]["server_home"] == [
        str(unlock.server_home)
    ]


def test_corrupt_download_or_failed_setup_leaves_nothing(unlock):
    fetch, _ = make_fetch(zip_bytes({"deno": b"x"}), PROVIDER, checksum="0" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        unlock.install(fetch=fetch, run=ok_run)
    assert not unlock.root.exists() and not unlock.installed()

    fetch, _ = make_fetch(zip_bytes({"deno": b"x"}), PROVIDER)
    with pytest.raises(RuntimeError, match="npm exploded"):
        unlock.install(fetch=fetch, run=bad_run)
    assert not unlock.root.exists()


def test_a_new_plugin_version_invalidates_the_install(unlock, monkeypatch):
    fetch, _ = make_fetch(zip_bytes({"deno": b"x"}), PROVIDER)
    unlock.install(fetch=fetch, run=ok_run)
    assert unlock.installed()
    monkeypatch.setattr(hd_unlock, "plugin_version", lambda: "2.1.0")  # the app was updated
    assert not unlock.installed()
    marker = json.loads((unlock.root / hd_unlock.MARKER).read_text())
    assert marker["plugin"] == "2.0.2"


def test_unsupported_without_plugin_or_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(hd_unlock, "plugin_version", lambda: None)
    assert not HdUnlock(tmp_path, system="Linux").supported()
    monkeypatch.setattr(hd_unlock, "plugin_version", lambda: "2.0.2")
    assert not HdUnlock(tmp_path, system="FreeBSD").supported()
    with pytest.raises(RuntimeError, match="not available"):
        HdUnlock(tmp_path / "x", system="FreeBSD").install()


class FakeYdl:
    """Refuses the default clients, serves 360p to Android and HD through the unlock."""

    attempts: list[str] = []

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        youtube = (self.options.get("extractor_args") or {}).get("youtube", {})
        clients = youtube.get("player_client")
        if clients is None:
            FakeYdl.attempts.append("default")
            assert self.options["js_runtimes"] == {}  # a stray Deno on PATH must not interfere
            raise RuntimeError("This video is not available")
        FakeYdl.attempts.append(clients[0])
        if clients == ["tv_simply"]:
            assert "deno" in self.options["js_runtimes"]
            formats = [
                {
                    "url": "https://v.invalid/137",
                    "vcodec": "avc1",
                    "acodec": "none",
                    "height": 1080,
                },
                {"url": "https://v.invalid/140", "vcodec": "none", "acodec": "mp4a"},
            ]
            return {"id": "ZHyKR6EfnKQ", "title": "Kids song", "requested_formats": formats}
        return {
            "id": "ZHyKR6EfnKQ",
            "title": "Kids song",
            "url": "https://v.invalid/18",
            "vcodec": "avc1",
            "acodec": "mp4a",
            "height": 360,
        }

    def sanitize_info(self, info):
        return info


def test_restricted_video_is_360p_without_the_component_and_hd_with_it(unlock, monkeypatch):
    FakeYdl.attempts = []
    monkeypatch.setattr(search, "_ydl", lambda **options: FakeYdl(options))
    youtube = search.YouTube()
    youtube.hd_unlock = unlock

    source = youtube.resolve("ZHyKR6EfnKQ")
    assert FakeYdl.attempts == ["default", "android"]  # component not installed: not even tried
    assert source.video_url.endswith("/18") and youtube.is_limited("ZHyKR6EfnKQ")
    assert youtube.lookup("ZHyKR6EfnKQ").title == "Kids song" and len(FakeYdl.attempts) == 2

    fetch, _ = make_fetch(zip_bytes({"deno": b"x"}), PROVIDER)
    unlock.install(fetch=fetch, run=ok_run)
    youtube.forget_limited()  # what Settings does after the install
    source = youtube.resolve("ZHyKR6EfnKQ")
    assert FakeYdl.attempts[2:] == ["default", "tv_simply"]
    assert source.video_url.endswith("/137") and source.audio_url.endswith("/140")
    assert not youtube.is_limited("ZHyKR6EfnKQ")


def test_error_from_the_default_client_is_reported_when_everything_fails(monkeypatch):
    class Refuses(FakeYdl):
        def extract_info(self, url, download=False):
            raise RuntimeError(
                "Video unavailable" if "extractor_args" not in self.options else "other"
            )

    monkeypatch.setattr(search, "_ydl", lambda **options: Refuses(options))
    with pytest.raises(RuntimeError, match="Video unavailable"):
        search.YouTube().resolve("AAAAAAAAAAA")


def test_self_check_passes_in_a_normal_install():
    lines: list[str] = []
    assert hd_unlock.self_check(lines.append) == 0
    assert lines[-1] == "OK" and any("BgUtilScriptDeno" in line for line in lines)
