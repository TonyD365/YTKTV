"""HTTPS helpers.

Python builds from python.org on macOS (and frozen apps) ship without a CA
bundle, so plain ``urllib`` fails certificate checks; use certifi's instead.
"""

from __future__ import annotations

import ssl
import urllib.request
from typing import Any


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def urlopen(request: urllib.request.Request | str, timeout: float = 20) -> Any:
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())
