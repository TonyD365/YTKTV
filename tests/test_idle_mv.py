"""Background videos: they fill the silence when nobody has chosen a song, and give way at once."""

from __future__ import annotations

from tests.helpers import make_song, wait_for
from ytktv.core.models import PlayStatus


def test_off_by_default(ktv):
    controller, _player, _ = ktv
    assert controller.settings.idle_mv is False
    assert controller.state()["idle_mv"] is False


def test_background_video_gives_way_and_is_not_recorded(ktv):
    controller, player, _ = ktv
    controller.toggle_favorite(make_song(7))
    controller.set_idle_mv(True)
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    assert controller.idle_playing and controller.current.song.title == "Song 7"
    controller.enqueue(make_song(1))  # someone chooses a song: it starts straight away
    wait_for(lambda: controller.current is not None and controller.current.song.title == "Song 1")
    assert not controller.idle_playing
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    player.finish()  # the real song ends: background videos come back
    wait_for(lambda: controller.idle_playing and controller.status == PlayStatus.PLAYING)
    assert [s["title"] for s in controller.state()["history"]] == ["Song 1"]
    controller.set_idle_mv(False)
    wait_for(lambda: controller.status == PlayStatus.IDLE and controller.current is None)


def test_nothing_to_play_stays_idle(ktv):
    controller, _player, _ = ktv
    controller.set_idle_mv(True)  # no favorites, nothing sung yet
    wait_for(lambda: controller.status == PlayStatus.IDLE)
    assert controller.current is None and not controller.idle_playing
