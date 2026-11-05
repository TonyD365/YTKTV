"""Mood scenes: one tap sets the colour of the MV edge lights and smart lights, with a sound."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scene:
    title: str
    hue: float  # centre of the colours, 0..1 around the colour wheel
    spread: float  # how far the four sides wander from it (0.5 = the whole wheel)
    speed: float  # how fast the colours drift, 1 = as without a scene
    sound: str = ""  # a crowd sound played when the scene starts
    message: str = ""  # shown as a toast when the scene starts


SCENES: dict[str, Scene] = {
    "birthday": Scene("🎂 Birthday", 0.12, 0.08, 1.0, "cheer", "Happy birthday!"),
    "romantic": Scene("💕 Romantic", 0.92, 0.05, 0.3),
    "party": Scene("🪩 Party", 0.0, 0.5, 4.0, "airhorn", "Let's party!"),
    "chill": Scene("🌊 Chill", 0.55, 0.06, 0.4),
}
