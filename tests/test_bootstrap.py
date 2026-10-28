from __future__ import annotations

from ytktv import bootstrap


def test_homebrew_is_found_outside_the_finders_short_path(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)  # as when opened from Finder
    brew = tmp_path / "brew"
    brew.write_text("")
    real_exists = bootstrap.Path.exists
    monkeypatch.setattr(
        bootstrap.Path,
        "exists",
        lambda self: (
            True if self == bootstrap.Path("/opt/homebrew/bin/brew") else real_exists(self)
        ),
    )
    # Compared as paths: Windows writes the same path with backslashes.
    assert bootstrap.Path(bootstrap.homebrew()) == bootstrap.Path("/opt/homebrew/bin/brew")
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Darwin")
    assert bootstrap.install_plan() == "brew install mpv"


def test_no_homebrew_means_no_automatic_plan_on_macos(monkeypatch):
    monkeypatch.setattr(bootstrap, "homebrew", lambda: None)
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Darwin")
    assert bootstrap.install_plan() is None


def test_packaged_builds_install_mpv_like_everyone_else(monkeypatch):
    """No YTKTV-made mpv download any more: a packaged build uses the same plan."""
    monkeypatch.setattr(bootstrap, "is_frozen", lambda: True)
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Windows")
    plan = bootstrap.install_plan()
    assert plan is not None and bootstrap.MPV_WINDOWS_REPO in plan and "YTKTV-mpv" not in plan


def test_mpv_downloaded_by_earlier_versions_is_still_used(tmp_path, monkeypatch):
    data = tmp_path / "data"
    legacy = data / "mpv"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "data_dir", lambda: data)
    monkeypatch.setattr(bootstrap, "bundle_dir", lambda: None)
    monkeypatch.setattr(bootstrap, "lib_dir", lambda: tmp_path / "lib")
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bootstrap.ctypes.util, "find_library", lambda name: None)
    (legacy / "libmpv.so.2").write_bytes(b"library")
    assert bootstrap.find_libmpv() is None  # not a finished download: no marker
    (legacy / "INSTALLED").write_text("1.5.0")
    assert bootstrap.find_libmpv() == str(legacy / "libmpv.so.2")
