import threading
import time

from ytktv.core.warmup import Warmup


def test_downloads_wait_while_a_song_settles():
    warm = Warmup(seconds=0.3)
    warm.wait()  # nothing playing: no wait
    warm.started()
    began = time.monotonic()
    done = threading.Event()
    threading.Thread(target=lambda: (warm.wait(), done.set()), daemon=True).start()
    assert done.wait(2) and time.monotonic() - began >= 0.25
