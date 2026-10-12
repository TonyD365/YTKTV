"""Karaoke scoring: compare what is sung with the original singer's melody."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ytktv.separation.pitch_core import pitch_class_distance

# A sung note this close to the original counts in full / in half. Octaves are ignored:
# singing the tune an octave down is still singing the tune.
FULL_CREDIT_SEMITONES = 1.0
HALF_CREDIT_SEMITONES = 2.0
# Singers are rarely exactly on the beat, and the two clocks are not perfectly aligned:
# accept a match against the melody anywhere within this many frames (of 50 ms).
TIMING_SLACK_FRAMES = 3
# The microphone hears the singer slightly after the player's position says so.
MIC_LATENCY_SECONDS = 0.08
# Below this much sung melody there is nothing fair to say (a skipped song, an instrumental).
MIN_FRAMES = 100  # 5 seconds

GRADES = ((95, "Superstar!"), (88, "Amazing!"), (78, "Great!"), (65, "Nice!"), (0, "Keep singing!"))


@dataclass(frozen=True, slots=True)
class Melody:
    hop: float  # seconds between values
    notes: tuple[float | None, ...]  # MIDI note numbers; None where nobody sings

    @classmethod
    def load(cls, path: Path) -> Melody:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(float(data["hop"]), tuple(data["notes"]))

    def window(self, index: int, slack: int) -> list[float]:
        """The melody notes around frame *index*, skipping the silent ones."""
        low, high = max(0, index - slack), min(len(self.notes), index + slack + 1)
        return [note for note in self.notes[low:high] if note is not None]


@dataclass(frozen=True, slots=True)
class Score:
    points: int  # 0..100
    accuracy: float  # share of the sung notes that were right
    participation: float  # share of the melody that was sung at all
    grade: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": self.points,
            "accuracy": round(self.accuracy, 3),
            "participation": round(self.participation, 3),
            "grade": self.grade,
        }


def grade_for(points: int) -> str:
    return next(text for threshold, text in GRADES if points >= threshold)


class ScoreKeeper:
    """Accumulates a score for one song. Feed it the microphone pitch as the song plays."""

    def __init__(self, melody: Melody, transpose: float = 0.0) -> None:
        self.melody = melody
        self.transpose = transpose  # key change in semitones, applied to the melody
        self._lock = threading.Lock()
        self._last_index = -1
        self._frames = 0  # melody frames that went by
        self._sung = 0  # of those, frames where the microphone had a pitch
        self._credit = 0.0
        # One more keeper per microphone, fed separately, so a duet gets two scores.
        self._voices: dict[int, ScoreKeeper] = {}

    def feed_voice(self, mic: int, position: float, sung: float | None) -> None:
        """Like :meth:`feed`, for microphone number *mic* alone."""
        with self._lock:
            voice = self._voices.get(mic)
            if voice is None:
                voice = self._voices[mic] = ScoreKeeper(self.melody)
        voice.transpose = self.transpose
        voice.feed(position, sung)

    def voice_results(self) -> dict[int, Score]:
        """The score of every microphone that was sung into enough to be judged."""
        with self._lock:
            voices = dict(self._voices)
        results = {mic: voice.result() for mic, voice in sorted(voices.items())}
        return {mic: score for mic, score in results.items() if score is not None}

    def feed(self, position: float, sung: float | None) -> None:
        """Record the microphone pitch (MIDI or None) at playback *position* seconds."""
        index = int((position - MIC_LATENCY_SECONDS) / self.melody.hop)
        with self._lock:
            if index <= self._last_index or index < 0 or index >= len(self.melody.notes):
                return  # each stretch of melody is judged once, even after a seek back
            self._last_index = index
            if self.melody.notes[index] is None:
                return  # nobody sings here in the original: nothing to judge
            self._frames += 1
            if sung is None:
                return
            self._sung += 1
            targets = self.melody.window(index, TIMING_SLACK_FRAMES)
            distance = min(pitch_class_distance(sung, note + self.transpose) for note in targets)
            if distance <= FULL_CREDIT_SEMITONES:
                self._credit += 1.0
            elif distance <= HALF_CREDIT_SEMITONES:
                self._credit += 0.5

    def result(self) -> Score | None:
        """The score so far, or None when too little has been sung to judge."""
        with self._lock:
            frames, sung, credit = self._frames, self._sung, self._credit
        if frames < MIN_FRAMES or sung < MIN_FRAMES // 4:
            return None
        participation = sung / frames
        accuracy = credit / sung
        # Mostly about hitting the notes, partly about singing the whole song; then a
        # generous curve, because this is a party and not an audition.
        raw = 0.3 * participation + 0.7 * accuracy * participation
        points = max(0, min(100, round(100 * raw**0.6)))
        return Score(points, accuracy, participation, grade_for(points))


SCOREBOARD_LIMIT = 100


class Scoreboard:
    """The scores of one evening, best first."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._count = 0

    def add(self, points: int, title: str, singer: str) -> int:
        """Record a score and return its place tonight (1 = the best so far)."""
        with self._lock:
            self._count += 1
            entry = {"points": points, "title": title, "singer": singer, "order": self._count}
            self._entries.append(entry)
            # A later score that only equals an earlier one does not push it down.
            self._entries.sort(key=lambda e: (-e["points"], e["order"]))
            del self._entries[SCOREBOARD_LIMIT:]
            return self._entries.index(entry) + 1 if entry in self._entries else len(self._entries)

    def top(self, count: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"rank": i + 1, "points": e["points"], "title": e["title"], "singer": e["singer"]}
                for i, e in enumerate(self._entries[:count])
            ]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class ScoringLoop:
    """Samples the microphone pitch a few times a second and feeds the current keeper."""

    INTERVAL = 0.05

    def __init__(
        self,
        mic_pitch: Callable[[], float | None],
        current: Callable[[], tuple[ScoreKeeper, float] | None],
        on_sample: Callable[[float, float | None], None] | None = None,
        voice_pitches: Callable[[], dict[int, float | None]] | None = None,
    ) -> None:
        """*current* returns (keeper, playback position) while a song is being scored.

        *on_sample* is told every (position, sung note or None), for drawing the voice.
        *voice_pitches* gives the note of each microphone on its own, by channel.
        """
        self._mic_pitch = mic_pitch
        self._current = current
        self._on_sample = on_sample
        self._voice_pitches = voice_pitches
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ytktv-score", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.INTERVAL):
            active = self._current()
            if active is None:
                continue
            keeper, position = active
            try:
                sung = self._mic_pitch()
                keeper.feed(position, sung)
                if self._voice_pitches is not None:
                    for mic, note in self._voice_pitches().items():
                        keeper.feed_voice(mic, position, note)
                if self._on_sample is not None:
                    self._on_sample(position, sung)
            except Exception:
                continue  # one bad frame must not end scoring for the night
