from __future__ import annotations

import hashlib
import io
import json
import urllib.error

import pytest

from ytktv import updater


def release(tag="v1.2.0", **extra):
    names = [
        "YTKTV-1.2.0-macos-arm64.pkg",
        "YTKTV-1.2.0-windows-x64-setup.exe",
        "YTKTV-1.2.0-linux-x86_64.AppImage",
        "SHA256SUMS",
    ]
    data = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "body": "notes",
        "html_url": "https://github.com/TonyD365/YTKTV/releases/tag/" + tag,
        "assets": [{"name": n, "browser_download_url": f"https://dl.invalid/{n}"} for n in names],
    }
    data.update(extra)
    return lambda url: json.dumps(data).encode()


@pytest.mark.parametrize(
    ("tag", "current", "expected"),
    [
        ("v1.0.1", "1.0.0", True),
        ("v1.0.0", "1.0.0", False),
        ("v0.9.0", "1.0.0", False),
        ("v1.10.0", "1.9.9", True),
        ("v1.0.0", "1.0.1.dev3+gabc123", False),
        ("v2.0.0", "0.1.dev1+gabc123", True),
        ("nightly", "1.0.0", False),
    ],
)
def test_is_newer(tag, current, expected):
    assert updater.is_newer(tag, current) is expected


@pytest.mark.parametrize(
    ("system", "machine", "suffix"),
    [
        ("Darwin", "arm64", "macos-arm64.pkg"),
        ("Darwin", "x86_64", "macos-x86_64.pkg"),
        ("Windows", "AMD64", "windows-x64-setup.exe"),
        ("Linux", "x86_64", "linux-x86_64.AppImage"),
        ("Linux", "riscv64", None),
    ],
)
def test_platform_suffix(system, machine, suffix):
    assert updater.platform_suffix(system, machine) == suffix


def test_check_finds_the_right_installer_for_each_platform():
    info = updater.check_for_update("1.1.0", fetch=release(), suffix="macos-arm64.pkg")
    assert info is not None
    assert (info.version, info.tag) == ("1.2.0", "v1.2.0")
    assert info.asset_name == "YTKTV-1.2.0-macos-arm64.pkg"
    assert info.checksum_url == "https://dl.invalid/SHA256SUMS"
    windows = updater.check_for_update("1.1.0", fetch=release(), suffix="windows-x64-setup.exe")
    assert windows is not None and windows.asset_name.endswith("setup.exe")


def test_check_ignores_same_version_prereleases_and_missing_installers():
    assert updater.check_for_update("1.2.0", fetch=release(), suffix="macos-arm64.pkg") is None
    pre = release("v1.3.0", prerelease=True)
    assert updater.check_for_update("1.2.0", fetch=pre, suffix="macos-arm64.pkg") is None
    assert updater.check_for_update("1.1.0", fetch=release(), suffix="macos-x86_64.pkg") is None


def test_check_treats_no_releases_as_up_to_date():
    def not_found(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    assert updater.check_for_update("1.0.0", fetch=not_found, suffix="macos-arm64.pkg") is None


def test_expected_checksum_parses_sha256sum_output():
    sums = "aaa111  YTKTV-1.2.0-macos-arm64.pkg\nBBB222 *YTKTV-1.2.0-windows-x64-setup.exe\n"
    assert updater.expected_checksum(sums, "YTKTV-1.2.0-macos-arm64.pkg") == "aaa111"
    assert updater.expected_checksum(sums, "YTKTV-1.2.0-windows-x64-setup.exe") == "bbb222"
    assert updater.expected_checksum(sums, "other") is None


class _Response(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _info(name="YTKTV-1.2.0-macos-arm64.pkg", checksum_url="https://dl.invalid/SHA256SUMS"):
    return updater.UpdateInfo(
        "1.2.0", "v1.2.0", name, f"https://dl.invalid/{name}", checksum_url, "", ""
    )


def test_download_verifies_checksum(tmp_path, monkeypatch):
    payload = b"installer-bytes" * 1000
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(updater, "urlopen", lambda request, timeout=30: _Response(payload))
    info = _info()

    path = updater.download_update(
        info, tmp_path, fetch=lambda url: f"{digest}  {info.asset_name}\n".encode()
    )
    assert path.read_bytes() == payload

    with pytest.raises(RuntimeError, match="checksum"):
        updater.download_update(
            info, tmp_path / "bad", fetch=lambda url: f"{'0' * 64}  {info.asset_name}\n".encode()
        )
    assert list((tmp_path / "bad").iterdir()) == []  # the bad download is not left behind


def test_download_refuses_releases_without_checksums(tmp_path):
    with pytest.raises(RuntimeError, match="SHA256SUMS"):
        updater.download_update(_info(checksum_url=None), tmp_path)
    with pytest.raises(RuntimeError, match="no checksum"):
        updater.download_update(_info(), tmp_path, fetch=lambda url: b"abc  something-else\n")
