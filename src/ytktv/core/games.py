"""Party games like a KTV room's: dice, a spin to pick the next singer, truth or dare."""

from __future__ import annotations

import random

DICE = "⚀⚁⚂⚃⚄⚅"

TRUTHS = (
    "Which song do you secretly sing in the shower?",
    "Who in this room would you duet with?",
    "What is the most embarrassing song on your phone?",
    "What was your worst karaoke moment?",
    "Which singer did you have a crush on?",
    "What song always makes you cry?",
)
DARES = (
    "Sing the next chorus in a whisper.",
    "Dance through the whole next song.",
    "Sing the next song with your eyes closed.",
    "Do your best impression of the original singer.",
    "Sing one line in a different language.",
    "Pick a duet partner and sing the next song together.",
)


def roll_dice(count: int = 5, rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    faces = [rng.randrange(6) for _ in range(count)]
    total = sum(faces) + count
    return {
        "title": "🎲 Dice",
        "text": " ".join(DICE[f] for f in faces),
        "detail": f"Total {total}",
    }


def spin(names: list[str], rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    names = [n for n in dict.fromkeys(n.strip() for n in names) if n]
    if not names:
        return {"title": "🎡 Spin", "text": "Add singers first", "detail": ""}
    return {"title": "🎡 Next to sing", "text": rng.choice(names), "detail": ""}


def truth_or_dare(kind: str, rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    if kind == "truth":
        return {"title": "💬 Truth", "text": rng.choice(TRUTHS), "detail": ""}
    return {"title": "🔥 Dare", "text": rng.choice(DARES), "detail": ""}
