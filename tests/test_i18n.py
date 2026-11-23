"""The room app's languages: every wrapped string is translated, and nothing can crash."""

from __future__ import annotations

import ast
import json
import string
from collections.abc import Iterator
from pathlib import Path

import pytest

from ytktv import i18n
from ytktv.config import Settings

SRC = Path(i18n.__file__).parent
SCOPE = [
    *sorted((SRC / "ui").glob("*.py")),
    SRC / "app.py",
    SRC / "core" / "games.py",
    SRC / "core" / "controller.py",
    *sorted((SRC / "desk").glob("*.py")),
]


@pytest.fixture(autouse=True)
def english_afterwards() -> Iterator[None]:
    yield
    i18n.set_language("en")


def literals() -> set[str]:
    found: set[str] = set()
    for path in SCOPE:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if getattr(node.func, "id", "") not in ("t", "N_"):
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def data_labels() -> set[str]:
    """Names kept in English as data and translated only where they are shown."""
    from ytktv import catalog
    from ytktv.audio.dsp import VOICES
    from ytktv.audio.presets import BUILT_IN
    from ytktv.core.scenes import SCENES
    from ytktv.core.scoring import GRADES
    from ytktv.plugins import PERMISSIONS
    from ytktv.ui.mixer_panel import DEFAULT, OFF
    from ytktv.ui.mv_overlays import CUSTOM_COLOURS, LYRIC_COLOURS, LYRIC_OUTLINES, LYRIC_SIZES
    from ytktv.ui.theme import TEXT_SIZES, THEMES
    from ytktv.youtube.search import HOT_CATEGORIES

    labels = {*catalog.LANGUAGES, *catalog.KINDS, *VOICES.values(), *BUILT_IN}
    labels |= {*PERMISSIONS.values(), *(g for _, g in GRADES), DEFAULT, OFF, CUSTOM_COLOURS}
    labels |= {x for scene in SCENES.values() for x in (scene.title, scene.message) if x}
    labels |= {*LYRIC_COLOURS, *LYRIC_OUTLINES, *LYRIC_SIZES, *TEXT_SIZES, *THEMES}
    return labels | set(HOT_CATEGORIES)


def fields(text: str) -> set[tuple[str, str]]:
    return {(f, spec or "") for _, f, spec, _ in string.Formatter().parse(text) if f is not None}


def table() -> dict[str, str]:
    return json.loads((i18n.ASSETS / "zh_CN.json").read_text(encoding="utf-8"))


def test_every_string_has_a_translation_with_the_same_placeholders() -> None:
    zh = table()
    wanted = literals() | data_labels()
    assert sorted(wanted - set(zh)) == []
    for key in wanted:
        assert fields(key) == fields(zh[key]), key


def test_unknown_text_falls_back_and_formats_only_with_values() -> None:
    i18n.set_language("zh_CN")
    assert i18n.current() == "zh_CN"
    assert i18n.t("Settings") == "设置"
    assert i18n.t("Not a known string {x}") == "Not a known string {x}"
    assert i18n.t("Hello {x}", x=1) == "Hello 1"
    assert i18n.t("Added: {title}", title="{odd}") == "已点：{odd}"


def test_the_phone_page_still_recognises_the_bomb() -> None:
    # index.html looks for "BOOM" in the result's title.
    assert "BOOM" in table()["💥 BOOM!"]


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]"])
def test_a_bad_or_missing_file_means_english(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    monkeypatch.setattr(i18n, "ASSETS", tmp_path)
    if content is not None:
        (tmp_path / "zh_CN.json").write_text(content, encoding="utf-8")
    assert i18n.set_language("zh_CN") == "en"
    assert i18n.t("Settings") == "Settings"


def test_a_broken_translation_shows_the_english(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(i18n, "ASSETS", tmp_path)
    (tmp_path / "zh_CN.json").write_text('{"Hi {name}": "你好 {other}"}', encoding="utf-8")
    i18n.set_language("zh_CN")
    assert i18n.t("Hi {name}", name="Kim") == "Hi Kim"


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["zh-Hans-CN"], "zh_CN"),
        (["zh_CN"], "zh_CN"),
        (["en-US", "zh-Hans"], "en"),
        (["fr_FR"], "en"),
        (["C"], "en"),
        ([], "en"),
    ],
)
def test_the_default_follows_the_system(
    monkeypatch: pytest.MonkeyPatch, names: list[str], expected: str
) -> None:
    monkeypatch.setattr(i18n, "_system_names", lambda: names)
    assert i18n.set_language("") == expected
    assert i18n.set_language("klingon") == expected


def test_a_saved_language_beats_the_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_system_names", lambda: ["zh-Hans"])
    assert i18n.set_language("en") == "en"
    assert Settings().language == ""


def test_the_picker_is_for_guests_and_not_an_admin_setting(qtbot, ktv) -> None:
    pytest.importorskip("PySide6")
    from tests.helpers import FakeSource
    from ytktv.rooms import admin
    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow

    controller, _, _ = ktv
    store = controller.store
    mv = MvWindow(None)
    main = MainWindow(controller, FakeSource(), mv, "http://192.168.0.2:8765")  # type: ignore[arg-type]
    qtbot.addWidget(main)
    qtbot.addWidget(mv)
    page = main.settings_page
    frame = page.language_choice.parentWidget()
    assert frame not in page.admin_cards
    assert "language" not in admin.FIELDS
    assert "language" not in admin.report(controller.settings)
    names = [page.language_choice.itemText(i) for i in range(page.language_choice.count())]
    assert names == ["English", "简体中文"]

    page.language_choice.setCurrentIndex(1)
    page.language_choice.activated.emit(1)
    assert store.settings.language == "zh_CN"
    assert json.loads(store.path.read_text(encoding="utf-8"))["language"] == "zh_CN"
    assert page.language_note.text() == "新语言将在重启 YTKTV 后生效。"
    assert i18n.current() == "en"  # nothing changes until the restart

    store.settings.desk_url = "http://desk"
    page.apply_role()
    assert not frame.isHidden()


def test_the_desk_keeps_its_language_in_its_settings_or_on_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ytktv.desk import language
    from ytktv.desk.store import DeskStore

    monkeypatch.setattr(i18n, "_system_names", lambda: ["en-US"])
    store = DeskStore(tmp_path / "desk.sqlite3")
    assert language.apply(store) == "en"
    store.set_setting(language.SETTING, "zh_CN")
    assert language.apply(store) == "zh_CN"
    assert i18n.t("Settings") == "设置"
    # A staff terminal's choice lives on its own computer, never in the main Desk's records.
    mine = tmp_path / "desk-language.json"
    language.save_local("zh_CN", mine)
    assert language.load_local(mine) == "zh_CN"
    assert language.apply(None, mine) == "zh_CN"
    assert language.load_local(tmp_path / "missing.json") == ""
    monkeypatch.setattr(i18n, "_system_names", lambda: ["zh-Hans"])
    assert language.apply(None, tmp_path / "missing.json") == "zh_CN"  # first run: the system


def test_the_desk_picker_saves_without_changing_this_run(qtbot, tmp_path: Path) -> None:
    pytest.importorskip("PySide6")
    from ytktv.desk import language
    from ytktv.desk.store import DeskStore

    store = DeskStore(tmp_path / "desk.sqlite3")
    picker = language.LanguageSettings(store)
    qtbot.addWidget(picker)
    picker.choice.setCurrentIndex(1)
    picker.choice.activated.emit(1)
    assert store.setting(language.SETTING) == "zh_CN"
    assert picker.note.text() == "新语言将在重启 YTKTV Desk 后生效。"
    assert i18n.current() == "en"
    mine = tmp_path / "terminal.json"
    terminal = language.LanguageSettings(store, local=True, path=mine)
    qtbot.addWidget(terminal)
    terminal.choice.setCurrentIndex(0)
    terminal.choice.activated.emit(0)
    assert language.load_local(mine) == "en"
    assert store.setting(language.SETTING) == "zh_CN"


def test_phone_pages_learn_the_language_from_html_lang_only() -> None:
    page = '<!doctype html>\n<html lang="en">\n<head></head>'
    assert i18n.localize_page(page) == page
    i18n.set_language("zh_CN")
    assert 'lang="zh-CN"' in i18n.localize_page(page)
    for name in ("index.html", "mic.html"):
        text = (SRC / "server" / "static" / name).read_text(encoding="utf-8")
        assert '<html lang="en">' in text
        assert 'src="http' not in text
    staff = (SRC / "desk" / "assets" / "staff.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in staff and "zh_CN" in staff
