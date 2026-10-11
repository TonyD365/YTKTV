"""Song queue and controller state cost with a very long queue."""

from __future__ import annotations

import pytest

from tests.helpers import make_controller, make_song
from ytktv.core.queue import SongQueue

SIZE = 500


@pytest.fixture
def big_queue():
    queue = SongQueue()
    items = [queue.add(make_song(i)) for i in range(SIZE)]
    return queue, items


def test_add(benchmark):
    queue = SongQueue()
    song = make_song(1)
    benchmark(queue.add, song)


def test_priority_add(benchmark, big_queue):
    queue, _ = big_queue
    song = make_song(1)

    def run():
        queue.add(song, priority=True)
        queue.pop_next()

    benchmark(run)


def test_prioritize_last(benchmark, big_queue):
    queue, _ = big_queue
    benchmark(lambda: queue.prioritize(queue.snapshot()[-1].id))


def test_move_middle(benchmark, big_queue):
    queue, items = big_queue
    benchmark(queue.move, items[SIZE // 2].id, SIZE // 3)


def test_snapshot(benchmark, big_queue):
    queue, _ = big_queue
    benchmark(queue.snapshot)


def test_controller_state(benchmark, tmp_path):
    """The snapshot every UI refresh and every WebSocket push is built from."""
    controller, _, _ = make_controller(tmp_path)
    try:
        for i in range(100):
            controller.queue.add(make_song(i))
        benchmark(controller.state)
    finally:
        controller.close()
