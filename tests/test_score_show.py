"""Tonight's best on the lobby screen, and confetti over the MV for a great score."""

from __future__ import annotations

from ytktv.desk.server import receive
from ytktv.desk.store import DeskStore


def test_rooms_scores_make_tonights_board():
    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Blue")
    store.open_room(room.room_id, "", None)
    for points, singer in ((88, "Kim"), (97, "Sam"), (101, "Cheat"), (72, "Lee")):
        receive(
            store,
            room.room_id,
            {"type": "score", "points": points, "title": "Song", "singer": singer},
        )
    receive(store, room.room_id, {"type": "score", "points": "99", "title": "x", "singer": "y"})
    best = store.top_scores(0, 2e10)
    assert [(p, s) for p, _t, s, _r in best] == [(97, "Sam"), (88, "Kim"), (72, "Lee")]


def test_lobby_shows_the_board(qtbot):
    from ytktv.desk.lobby import Lobby, LobbyWindow

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Blue")
    store.add_score(room.room_id, 95, "Moon Song", "")
    lobby = Lobby(store)
    lobby.window = LobbyWindow()
    qtbot.addWidget(lobby.window)
    lobby.refresh(store.rooms(), lambda _room: "free")
    assert "95 · Blue · Moon Song" in lobby.window.columns[3].text()


def test_great_score_bursts_confetti(qtbot):
    from ytktv.ui.mv_overlays import Celebration

    confetti = Celebration()
    qtbot.addWidget(confetti)
    confetti.resize(800, 450)
    confetti.burst(20)
    assert confetti.isVisible()
    for _ in range(int(Celebration.SECONDS / 0.033) + 2):
        confetti._step()
    assert not confetti.isVisible()
