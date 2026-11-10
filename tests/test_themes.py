from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from ytktv.ui import theme  # noqa: E402
from ytktv.ui.mv_window import MvWindow  # noqa: E402

# The style sheet before themes existed: Neon must stay exactly the same.
NEON_SHA256 = "037696cc088972ae4c7b0ea24bfba76a6a419ac4bda4a7092e6d3606f4bd47d9"
STATIC = Path(theme.__file__).parents[1] / "server" / "static"


@pytest.fixture(autouse=True)
def neon_afterwards():
    yield
    theme.apply()
    theme.logo = None


def picture(path: Path, size: int = 40, fmt: str = "PNG") -> Path:
    from PySide6.QtGui import QColor, QImage

    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    assert image.save(str(path), fmt)
    return path


def test_neon_is_unchanged():
    assert hashlib.sha256(theme.build("Neon").encode()).hexdigest() == NEON_SHA256
    assert theme.build("Neon") == theme.STYLESHEET and theme.PINK == "#ff3d9a"


def test_every_theme_builds_and_switches():
    assert len(theme.THEMES) >= 4
    for name in theme.THEMES:
        sheet = theme.apply(name)
        assert "{" in sheet and "{BG}" not in sheet and theme.current == name
        assert theme.THEMES[name]["PINK"] == theme.PINK and sheet == theme.STYLESHEET
    theme.apply("No such theme")
    assert theme.current == "Neon" and theme.PINK == "#ff3d9a"


def test_venue_accent_replaces_the_main_accent():
    assert theme.valid_accent("#12AbEf") and not theme.valid_accent("red")
    assert not theme.valid_accent("#123") and not theme.valid_accent("")
    theme.apply("Lounge", "#12AbEf")
    assert theme.PINK == "#12abef" and "#12abef" in theme.STYLESHEET
    assert theme.accent_of("Neon", "nonsense") == "#ff3d9a"


def test_logo_is_checked_and_stored(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    stored = theme.import_logo(picture(tmp_path / "bar.png"), folder)
    assert stored == folder / "venue-logo.png" and stored.is_file()
    jpeg = theme.import_logo(picture(tmp_path / "bar.jpg", fmt="JPG"), folder)
    assert not stored.exists() and jpeg.is_file()  # the old one is replaced
    assert theme.logo_file("venue-logo.jpg", folder) == jpeg
    assert theme.logo_file("../secret.png", folder) is None
    assert theme.logo_file("", folder) is None

    text = tmp_path / "notes.txt"
    text.write_text("hello")
    fake = tmp_path / "fake.png"
    fake.write_text("not a picture")
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG" + b"0" * (theme.LOGO_MAX_BYTES + 1))
    for bad in (text, fake, big, tmp_path / "missing.png"):
        with pytest.raises(ValueError):
            theme.import_logo(bad, folder)


def test_idle_screen_draws_the_venue_logo(qtbot, tmp_path):
    mv = MvWindow(None)
    qtbot.addWidget(mv)
    mv.idle.resize(640, 360)
    mv.idle.set_url("http://192.168.0.2:8765")
    plain = mv.idle.grab().toImage()
    theme.logo = picture(tmp_path / "logo.png", 200)
    with_logo = mv.idle.grab().toImage()
    assert plain != with_logo


def test_lobby_follows_the_desk_theme():
    from ytktv.desk import lobby

    theme.apply("Lounge")
    assert theme.THEMES["Lounge"]["PINK"] in lobby.style()


def test_phone_pages_follow_light_and_dark():
    for name in ("index.html", "mic.html"):
        html = (STATIC / name).read_text(encoding="utf-8")
        assert "@media (prefers-color-scheme: light)" in html
        assert 'media="(prefers-color-scheme: dark)"' in html
    assert "state.accent" in (STATIC / "index.html").read_text(encoding="utf-8")
