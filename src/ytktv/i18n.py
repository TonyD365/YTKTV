"""The room app's language: English source strings are the keys of the translations."""

from __future__ import annotations

import json
import locale
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LANGUAGES = {"en": "English", "zh_CN": "简体中文"}
ASSETS = Path(__file__).parent / "ui" / "assets"

_current = "en"
_table: dict[str, str] = {}


def _system_names() -> list[str]:
    names = [os.environ.get(k, "") for k in ("LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        from PySide6.QtCore import QLocale

        names = [*QLocale.system().uiLanguages(), QLocale.system().name(), *names]
    except Exception:  # no Qt here: the environment and the C locale still say enough
        log.debug("Qt locale unavailable", exc_info=True)
    with suppress(ValueError):
        names.append(locale.getlocale()[0] or "")
    return names


def system_language() -> str:
    """zh_CN on a computer set to Chinese, English on every other one."""
    first = next((n for n in _system_names() if n and n not in ("C", "POSIX")), "")
    return "zh_CN" if first.lower().startswith(("zh", "chinese")) else "en"


def resolve(code: str | None) -> str:
    """The language to use for a saved setting: empty or unknown follows the system."""
    return code if isinstance(code, str) and code in LANGUAGES else system_language()


def _load(code: str) -> dict[str, str]:
    try:
        data = json.loads((ASSETS / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("could not read the %s translations; using English", code)
        return {}
    if not isinstance(data, dict):
        log.warning("the %s translations are malformed; using English", code)
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def set_language(code: str | None) -> str:
    """Switch to *code* (empty or unknown follows the system); returns the language used."""
    global _current, _table
    wanted = resolve(code)
    _table = {} if wanted == "en" else _load(wanted)
    _current = wanted if wanted == "en" or _table else "en"
    return _current


def current() -> str:
    return _current


def N_(text: str) -> str:  # noqa: N802 - the usual name for this marker
    """Mark a constant for translation; it is translated with t() where it is shown."""
    return text


def t_in(code: str, text: str) -> str:
    """*text* in a language other than the current one (the restart notice)."""
    return text if code == "en" else _load(code).get(text, text)


def t(text: str, /, **values: Any) -> str:
    """*text* in the current language, formatted only when values are given."""
    translated = _table.get(text, text)
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):  # a broken translation must not crash the room
        log.warning("bad translation for %r", text)
        return text.format(**values)
