"""Mood scenes: the controller switches them and the lights keep near the scene's colour."""

from __future__ import annotations

from ytktv.core.scenes import SCENES
from ytktv.ui.mv_overlays import LightShow


def test_scene_is_in_the_state_and_turns_the_lights_on(ktv):
    controller, _player, _resolver = ktv
    controller.set_lights(False)
    played: list[str] = []
    controller.play_sfx = lambda name: played.append(name) or True
    controller.set_scene("party")
    state = controller.state()
    assert state["scene"] == "party" and state["lights"] is True
    assert played == ["airhorn"]
    controller.set_scene("no such scene")
    assert controller.state()["scene"] == ""


def test_lights_stay_near_the_scene_colour():
    show = LightShow()
    show.scene = SCENES["romantic"]
    for _ in range(200):
        strips = show.step(0.6, 0.05)
        for intensity, hue in strips.values():
            assert intensity > 0
            distance = min(abs(hue - 0.92), 1 - abs(hue - 0.92))
            assert distance <= 0.05 * 1.8 + 1e-9
