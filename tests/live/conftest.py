"""Live tests: real servers, real network, real models. Run by area-tests.yml when a pull
request carries their area's label, or locally with YTKTV_LIVE=1."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("YTKTV_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set YTKTV_LIVE=1")
    for item in items:
        if "tests/live" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)
