"""A log that is always kept, and one zip file with everything a bug report needs.

The zip holds the recent logs, the version, the system, and the settings with every key,
token and password taken out, so it can be attached to a GitHub issue as it is.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import sys
import time
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from ytktv import __version__
from ytktv.config import cache_dir

LOG_BYTES = 1_000_000  # per file; three are kept
SECRET = re.compile(r"key|token|password|secret|cookie|private|pin", re.IGNORECASE)
HIDDEN = "(hidden)"
ISSUES = "https://github.com/TonyD365/YTKTV/issues/new/choose"


def log_dir() -> Path:
    return cache_dir() / "logs"


def keep_log(name: str, level: int = logging.INFO) -> Path:
    """Write the log to <cache>/logs/<name>.log as well, whatever else happens to it."""
    folder = log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.log"
    handler = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=2, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return path


def redact(value: Any, name: str = "") -> Any:
    """*value* with anything that looks like a secret replaced."""
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, name) for v in value]
    if name and SECRET.search(name) and value not in ("", None, 0, False):
        return HIDDEN
    return value


def system_info(app: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "app": app,
        "version": __version__,
        "made": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "system": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "packaged": bool(getattr(sys, "frozen", False)),
    }
    try:
        from PySide6 import __version__ as qt

        info["qt"] = qt
    except ImportError:
        pass
    info.update(extra or {})
    return info


def default_name(app: str) -> str:
    return f"{app.lower().replace(' ', '-')}-diagnostics-{time.strftime('%Y%m%d-%H%M')}.zip"


def save(
    out: Path,
    app: str,
    settings: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    logs: Path | None = None,
    files: list[Path] | None = None,
) -> Path:
    """Write the diagnostics zip to *out* and return it."""
    out.parent.mkdir(parents=True, exist_ok=True)
    folder = logs or log_dir()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("about.json", json.dumps(system_info(app, extra), indent=2))
        if settings is not None:
            bundle.writestr("settings.json", json.dumps(redact(settings), indent=2))
        if folder.is_dir():
            for path in sorted(folder.glob("*.log*")):
                bundle.write(path, f"logs/{path.name}")
        for path in files or []:
            if path.is_file():
                bundle.write(path, f"logs/{path.name}")
    return out
