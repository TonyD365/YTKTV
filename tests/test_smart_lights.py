from __future__ import annotations

import time

import pytest

from ytktv import smart_lights
from ytktv.config import Settings


class FakeLights:
    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply

    def __call__(self, method, url, body=None):
        self.calls.append((method, url, body))
        return self.reply


def test_wled_and_hue_payloads():
    state = smart_lights.wled_state(1.0, 0.0)
    assert state["on"] and state["bri"] == 255 and state["seg"][0]["col"][0][0] == 255
    action = smart_lights.hue_action(0.5, 0.5)
    assert action["hue"] == round(0.5 * 65535) and 120 <= action["bri"] <= 130


def test_pair_hue_needs_the_link_button():
    pressed = FakeLights([{"success": {"username": "abc123"}}])
    assert smart_lights.pair_hue("10.0.0.2", pressed) == "abc123"
    assert pressed.calls[0][1] == "http://10.0.0.2/api"
    not_pressed = FakeLights([{"error": {"description": "link button not pressed"}}])
    with pytest.raises(RuntimeError, match="link button"):
        smart_lights.pair_hue("10.0.0.2", not_pressed)


def test_lights_follow_the_glow_at_their_pace():
    settings = Settings(smart_lights="wled", smart_lights_host="10.0.0.5")
    fake = FakeLights()
    lights = smart_lights.SmartLights(settings, fake)
    lights.start()
    try:
        lights.on_event("glow", {"level": 0.8, "hue": 0.2})
        lights.on_event("score", {})  # other events are ignored
        deadline = time.monotonic() + 3
        while not fake.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        method, url, body = fake.calls[0]
        assert (method, url) == ("POST", "http://10.0.0.5/json/state") and body["on"]

        settings.smart_lights, settings.hue_key = "hue", "abc123"
        lights.send(0.5, 0.1)
        assert fake.calls[-1][:2] == ("PUT", "http://10.0.0.5/api/abc123/groups/0/action")
        settings.smart_lights = "off"
        before = len(fake.calls)
        lights.send(0.5, 0.1)
        assert len(fake.calls) == before
    finally:
        lights.stop()
