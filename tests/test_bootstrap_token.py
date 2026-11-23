from __future__ import annotations

import pytest

from ytktv import bootstrap


def test_no_token_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YTKTV_GITHUB_TOKEN", raising=False)
    assert bootstrap._latest_mpv_request().get_header("Authorization") is None


def test_token_is_not_sent_on_a_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTKTV_GITHUB_TOKEN", "test-value")
    request = bootstrap._latest_mpv_request()
    assert request.unredirected_hdrs["Authorization"] == "Bearer test-value"
    assert "Authorization" not in request.headers
