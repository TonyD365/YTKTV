from __future__ import annotations

from tests.helpers import make_song
from ytktv.core.queue import SongQueue


def titles(queue: SongQueue) -> list[str]:
    return [item.song.title for item in queue.snapshot()]


def test_add_appends_and_priority_goes_first():
    queue = SongQueue()
    queue.add(make_song(1))
    queue.add(make_song(2))
    queue.add(make_song(3), priority=True)
    assert titles(queue) == ["Song 3", "Song 1", "Song 2"]


def test_prioritize_move_and_remove():
    queue = SongQueue()
    items = [queue.add(make_song(i)) for i in range(4)]
    assert queue.prioritize(items[2].id)
    assert titles(queue) == ["Song 2", "Song 0", "Song 1", "Song 3"]
    assert queue.move(items[2].id, 99)  # clamped to the end
    assert titles(queue)[-1] == "Song 2"
    assert queue.remove(items[0].id)
    assert not queue.remove("missing")
    assert not queue.move("missing", 0)
    assert len(queue) == 3


def test_pop_next_and_peek():
    queue = SongQueue()
    assert queue.pop_next() is None and queue.peek() is None
    first = queue.add(make_song(1))
    queue.add(make_song(2))
    assert queue.peek() is first
    assert queue.pop_next() is first
    assert len(queue) == 1


def test_history_is_bounded_newest_first_and_skips_immediate_repeat():
    queue = SongQueue(history_limit=3)
    for i in range(5):
        queue.add_history(make_song(i))
    queue.add_history(make_song(4))
    assert [s.title for s in queue.history()] == ["Song 4", "Song 3", "Song 2"]
