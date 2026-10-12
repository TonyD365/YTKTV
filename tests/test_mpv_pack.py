from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from ytktv import bootstrap, mpv_pack


def pack(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("YTKTV_MPV_ROOT", str(tmp_path / "mpv"))
    monkeypatch.setattr(mpv_pack.platform, "system", lambda: "Linux")
    monkeypatch.setattr(mpv_pack.platform, "machine", lambda: "x86_64")
    return tmp_path / "mpv"


def test_every_supported_platform_has_a_pack_name():
    assert mpv_pack.asset_name(mpv_pack.platform_name("Darwin", "arm64")) == (
        "YTKTV-mpv-macos-arm64.zip"
    )
    assert mpv_pack.platform_name("Darwin", "x86_64") == "macos-x86_64"
    assert mpv_pack.platform_name("Windows", "AMD64") == "windows-x64"
    assert mpv_pack.platform_name("Linux", "x86_64") == "linux-x86_64"
    assert mpv_pack.platform_name("Linux", "riscv64") is None


def test_a_release_looks_for_its_own_pack_first_and_a_dev_build_for_the_latest():
    released = mpv_pack.download_urls("p.zip", "1.4.0")
    assert released[0] == (
        "https://github.com/TonyD365/YTKTV/releases/download/v1.4.0/p.zip",
        "https://github.com/TonyD365/YTKTV/releases/download/v1.4.0/SHA256SUMS",
    )
    assert released[1][0].endswith("/releases/latest/download/p.zip")
    assert [url for url, _sums in mpv_pack.download_urls("p.zip", "1.4.1.dev3+gabc")] == [
        "https://github.com/TonyD365/YTKTV/releases/latest/download/p.zip"
    ]


def test_install_checks_the_download_and_unpacks_it(root):
    asset = "YTKTV-mpv-linux-x86_64.zip"
    data = pack({"libmpv.so.2": b"library", "libavcodec.so.60": b"codec"})
    sums = f"{hashlib.sha256(data).hexdigest()}  {asset}\nffff  something-else\n"
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        return sums.encode() if url.endswith("SHA256SUMS") else data

    assert not mpv_pack.installed()
    lines: list[str] = []
    assert mpv_pack.install(lines.append, fetch) == root
    assert mpv_pack.installed() and (root / "libmpv.so.2").read_bytes() == b"library"
    assert any("Downloading" in line for line in lines)
    assert asked[0].endswith("SHA256SUMS")  # the checksum comes first

    # Installing again replaces what was there instead of mixing two versions.
    (root / "stale.so").write_bytes(b"old")
    mpv_pack.install(fetch=fetch)
    assert not (root / "stale.so").exists() and (root / "libmpv.so.2").exists()


def test_install_refuses_a_download_that_does_not_match(root):
    asset = "YTKTV-mpv-linux-x86_64.zip"
    data = pack({"libmpv.so.2": b"library"})

    def tampered(url: str) -> bytes:
        return f"{'0' * 64}  {asset}\n".encode() if url.endswith("SHA256SUMS") else data

    with pytest.raises(RuntimeError, match="checksum"):
        mpv_pack.install(fetch=tampered)
    assert not mpv_pack.installed() and not root.exists()

    def unlisted(url: str) -> bytes:
        return b"abc  another-file\n" if url.endswith("SHA256SUMS") else data

    with pytest.raises(RuntimeError, match="no checksum listed"):
        mpv_pack.install(fetch=unlisted)


def test_install_falls_back_to_the_latest_release(root, monkeypatch):
    monkeypatch.setattr(mpv_pack, "__version__", "9.9.9")
    asset = "YTKTV-mpv-linux-x86_64.zip"
    data = pack({"libmpv.so.2": b"library"})
    sums = f"{hashlib.sha256(data).hexdigest()}  {asset}\n".encode()

    def fetch(url: str) -> bytes:
        if "/download/v9.9.9/" in url:
            raise OSError("404")  # that release has no pack (yet)
        return sums if url.endswith("SHA256SUMS") else data

    mpv_pack.install(fetch=fetch)
    assert mpv_pack.installed()


def test_unpack_rejects_anything_but_a_flat_folder(root, tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(pack({"../escape.so": b"x"}))
    with pytest.raises(RuntimeError, match="unexpected entry"):
        mpv_pack.unpack(archive)
    assert not root.exists()
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("mpv-")] == []  # no leftovers


def test_a_packaged_build_finds_and_installs_the_downloaded_library(root, monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "is_frozen", lambda: True)
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bootstrap, "bundle_dir", lambda: tmp_path / "bundle")
    monkeypatch.setattr(bootstrap, "lib_dir", lambda: tmp_path / "lib")
    assert "YTKTV-mpv-linux-x86_64.zip" in bootstrap.install_plan()

    calls: list[str] = []

    def fake_install(report):
        calls.append("install")
        root.mkdir(parents=True)
        (root / "libmpv.so.2").write_bytes(b"library")
        (root / mpv_pack.MARKER).write_text("test")

    monkeypatch.setattr(mpv_pack, "install", fake_install)
    monkeypatch.setattr(bootstrap.ctypes.util, "find_library", lambda name: None)
    assert bootstrap.find_libmpv() is None
    assert bootstrap.install_libmpv() is True and calls == ["install"]
    assert bootstrap.find_libmpv() == str(root / "libmpv.so.2")


def served(files: dict[str, bytes]):
    asset = "YTKTV-mpv-linux-x86_64.zip"
    data = pack(files)
    sums = f"{hashlib.sha256(data).hexdigest()}  {asset}\n".encode()
    return lambda url: sums if url.endswith("SHA256SUMS") else data


def test_after_an_update_the_newer_pack_is_fetched_and_used_from_the_next_start(root, monkeypatch):
    monkeypatch.setattr(mpv_pack, "__version__", "1.0.0")
    mpv_pack.install(fetch=served({"libmpv.so.2": b"old"}))
    assert mpv_pack.installed_version() == "1.0.0" and not mpv_pack.outdated()
    assert mpv_pack.fetch_next(fetch=served({"libmpv.so.2": b"never"})) is False  # up to date

    monkeypatch.setattr(mpv_pack, "__version__", "1.1.0")  # YTKTV was updated
    assert mpv_pack.outdated()
    assert mpv_pack.apply_pending() is False  # nothing fetched yet
    assert mpv_pack.fetch_next(fetch=served({"libmpv.so.2": b"new"})) is True
    # The pack in use is untouched while YTKTV runs...
    assert (root / "libmpv.so.2").read_bytes() == b"old"
    assert mpv_pack.fetch_next(fetch=served({"libmpv.so.2": b"again"})) is False  # once is enough
    # ...and replaced at the next start.
    assert mpv_pack.apply_pending() is True
    assert (root / "libmpv.so.2").read_bytes() == b"new"
    assert mpv_pack.installed_version() == "1.1.0" and not mpv_pack.outdated()
    assert not mpv_pack.next_dir().exists()


def test_a_failed_refresh_keeps_the_pack_that_works(root, monkeypatch):
    monkeypatch.setattr(mpv_pack, "__version__", "1.0.0")
    mpv_pack.install(fetch=served({"libmpv.so.2": b"old"}))
    monkeypatch.setattr(mpv_pack, "__version__", "1.1.0")

    def offline(url: str) -> bytes:
        raise OSError("no network")

    assert mpv_pack.fetch_next(fetch=offline) is False
    assert mpv_pack.apply_pending() is False
    assert (root / "libmpv.so.2").read_bytes() == b"old" and mpv_pack.installed()

    # A download cut short leaves a folder without the marker: it is thrown away.
    mpv_pack.next_dir().mkdir()
    (mpv_pack.next_dir() / "libmpv.so.2").write_bytes(b"half")
    assert mpv_pack.apply_pending() is False
    assert not mpv_pack.next_dir().exists() and (root / "libmpv.so.2").read_bytes() == b"old"

    # Without any pack there is nothing to refresh; the first-start download handles that.
    import shutil

    shutil.rmtree(root)
    assert not mpv_pack.outdated() and mpv_pack.fetch_next(fetch=offline) is False
