from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.helpers import make_controller  # noqa: E402


@pytest.fixture
def ktv(tmp_path):
    controller, player, resolver = make_controller(tmp_path)
    yield controller, player, resolver
    controller.close()
