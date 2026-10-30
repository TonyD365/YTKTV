from __future__ import annotations

import json
import logging
import zipfile

from ytktv import diagnostics


def test_log_is_kept_and_zipped_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "cache_dir", lambda: tmp_path / "cache")
    path = diagnostics.keep_log("ytktv")
    handler = logging.getLogger().handlers[-1]
    try:
        logging.getLogger("ytktv.test").warning("the song would not play")
        handler.flush()
        assert "would not play" in path.read_text(encoding="utf-8")
        (tmp_path / "separator.log").write_text("separator says hi")
        settings = {"room_key": "s3cret", "desk_key": "", "music_volume": 70,
                    "mics": [{"name": "Mic 1", "api_token": "abc"}]}  # fmt: skip
        out = diagnostics.save(
            tmp_path / "out" / "d.zip", "YTKTV", settings, files=[tmp_path / "separator.log"]
        )
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    with zipfile.ZipFile(out) as bundle:
        names = set(bundle.namelist())
        assert {"about.json", "settings.json", "logs/ytktv.log", "logs/separator.log"} <= names
        saved = json.loads(bundle.read("settings.json"))
        about = json.loads(bundle.read("about.json"))
    assert saved["room_key"] == diagnostics.HIDDEN and saved["desk_key"] == ""
    assert saved["music_volume"] == 70 and saved["mics"][0]["api_token"] == diagnostics.HIDDEN
    assert about["app"] == "YTKTV" and about["version"]
    assert diagnostics.default_name("YTKTV Desk").startswith("ytktv-desk-diagnostics-")


def test_crash_report_link_has_the_error_and_no_upload():
    import sys
    import urllib.parse

    from ytktv.ui import feedback

    try:
        raise ValueError("the song would not load")
    except ValueError:
        kind, error, trace = sys.exc_info()
    url = feedback.crash_report_url(kind, error, trace)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert url.startswith(feedback.ISSUES) and len(url) <= feedback.MAX_URL
    assert "ValueError" in query["title"][0] and "would not load" in query["body"][0]
