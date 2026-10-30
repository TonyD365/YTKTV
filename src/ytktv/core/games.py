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


CHALLENGES = (
    "Sing the next song in a baby voice.",
    "Sing the next song as an opera singer.",
    "Duet the next song with the person on your left.",
    "Sing the next chorus without looking at the lyrics.",
    "Everyone sings the next chorus together.",
    "Sing the next song while doing a dance move on every line.",
    "Swap the next song with the person on your right.",
    "Sing the next song in slow motion (Tempo down).",
    "Sing the next song one key higher.",
    "Introduce the next song like a radio DJ first.",
)
LOTS = ("Drink!", "Sing next!", "Safe", "Safe", "Pick someone to drink", "Everyone drinks!")


def challenge(rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    return {"title": "🎤 Challenge card", "text": rng.choice(CHALLENGES), "detail": ""}


def draw_lots(names: list[str], rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    names = [n for n in dict.fromkeys(n.strip() for n in names) if n]
    who = rng.choice(names) if names else "You"
    return {"title": "🥢 Draw lots", "text": f"{who}: {rng.choice(LOTS)}", "detail": ""}


def high_low(names: list[str], rng: random.Random | None = None) -> dict[str, str]:
    """Everyone rolls one die: the highest picks the next song, the lowest drinks."""
    rng = rng or random.Random()
    names = [n for n in dict.fromkeys(n.strip() for n in names) if n] or ["Player 1", "Player 2"]
    if len(names) == 1:
        names.append("The machine")
    rolls = {name: rng.randrange(6) for name in names}
    best, worst = max(rolls.values()), min(rolls.values())
    winners = [n for n, r in rolls.items() if r == best]
    losers = [n for n, r in rolls.items() if r == worst]
    return {
        "title": "🎲 High or low",
        # Numbers, not dice faces: next to names the faces are too small to read.
        "text": "   ".join(f"{n} {r + 1}" for n, r in rolls.items()),
        "detail": f"High: {', '.join(winners)}  ·  Low: {', '.join(losers)}",
    }


def coin(rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    return {"title": "🪙 Coin", "text": rng.choice(("Heads", "Tails")), "detail": ""}


def is_seven(n: int) -> bool:
    return n % 7 == 0 or "7" in str(n)


class Sevens:
    """Count out loud and say "pass" instead of any number with a 7 or divisible by 7."""

    def __init__(self) -> None:
        self.n = 0

    def next(self) -> dict[str, str]:
        self.n += 1
        if is_seven(self.n):
            return {"title": "7️⃣ Sevens", "text": "PASS!", "detail": f"({self.n})"}
        return {"title": "7️⃣ Sevens", "text": str(self.n), "detail": "Next person!"}

    def reset(self) -> dict[str, str]:
        self.n = 0
        return {"title": "7️⃣ Sevens", "text": "Start from 1", "detail": ""}


class NumberBomb:
    """A secret number between 1 and 100; every wrong guess shrinks the range."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.start()

    def start(self) -> dict[str, str]:
        self.low, self.high = 1, 100
        self.secret = self.rng.randint(2, 99)
        return {"title": "💣 Number bomb", "text": "1 – 100", "detail": "Guess a number!"}

    def guess(self, n: int, who: str = "") -> dict[str, str]:
        if not self.low < n < self.high:
            return {
                "title": "💣 Number bomb",
                "text": f"{self.low} – {self.high}",
                "detail": f"{n} is not in the range",
            }
        if n == self.secret:
            boomed = f"{who} hit the bomb!" if who else "You hit the bomb!"
            result = {"title": "💥 BOOM!", "text": str(n), "detail": boomed}
            self.start()
            return result
        if n < self.secret:
            self.low = n
        else:
            self.high = n
        return {"title": "💣 Number bomb", "text": f"{self.low} – {self.high}", "detail": ""}


class LiarsDice:
    """Everyone rolls five dice that only they can see; the reveal shows them all."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.hands: dict[str, list[int]] = {}

    def roll(self, player: str) -> list[int]:
        self.hands[player] = sorted(self.rng.randrange(6) for _ in range(5))
        return self.hands[player]

    def hand(self, player: str) -> str:
        return " ".join(DICE[f] for f in self.hands.get(player, []))

    def public(self) -> dict[str, str]:
        return {
            "title": "🎲 Liar's dice",
            "text": f"{len(self.hands)} players rolled",
            "detail": "Make your bids, then reveal",
        }

    def reveal(self) -> dict[str, str]:
        if not self.hands:
            return {"title": "🎲 Liar's dice", "text": "Nobody rolled yet", "detail": ""}
        counts = [sum(hand.count(face) for hand in self.hands.values()) for face in range(6)]
        hands = "   ".join(f"{p}: {self.hand(p)}" for p in self.hands)
        # Ones are wild in liar's dice: they count as every other face.
        totals = "  ".join(f"{DICE[f]}×{counts[f] + (counts[0] if f else 0)}" for f in range(6))
        self.hands = {}
        return {"title": "🎲 Liar's dice — reveal", "text": hands, "detail": totals}


class Tournament:
    """King of Singers: knockout rounds of one-on-one songs; the higher score goes through.

    Scores come from the score card when a match's singer finishes a song (or are typed in).
    """

    TITLE = "👑 King of Singers"

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.round = 0
        self.matches: list[tuple[str, str]] = []
        self.index = 0
        self.scores: dict[str, int] = {}
        self.winners: list[str] = []
        self.champion = ""

    @property
    def active(self) -> bool:
        return bool(self.matches) and not self.champion

    def start(self, names: list[str]) -> dict[str, str]:
        players = [n for n in dict.fromkeys(n.strip() for n in names) if n]
        if len(players) < 2:
            raise ValueError("a tournament needs at least two singers")
        self.rng.shuffle(players)
        self.round, self.champion = 0, ""
        return self._next_round(players)

    def _next_round(self, players: list[str]) -> dict[str, str]:
        self.round += 1
        self.matches = [(players[i], players[i + 1]) for i in range(0, len(players) - 1, 2)]
        # With an odd number, the last singer goes through to the next round without a match.
        self.winners = [players[-1]] if len(players) % 2 else []
        self.index, self.scores = 0, {}
        return self.public()

    def current(self) -> tuple[str, str] | None:
        return self.matches[self.index] if self.active else None

    def public(self) -> dict[str, str]:
        if self.champion:
            return {"title": self.TITLE, "text": f"👑 {self.champion}", "detail": "Champion!"}
        match = self.current()
        if match is None:
            return {"title": self.TITLE, "text": "Add singers and start", "detail": ""}
        scored = "  ·  ".join(f"{n} {self.scores[n]}" for n in match if n in self.scores)
        bye = f"  ·  {self.winners[0]} goes through" if self.winners and self.index == 0 else ""
        return {
            "title": f"{self.TITLE} · Round {self.round}",
            "text": f"{match[0]}  vs  {match[1]}",
            "detail": f"Match {self.index + 1} of {len(self.matches)}"
            + (f"  ·  {scored}" if scored else "  ·  each sings one song")
            + bye,
        }

    def record(self, name: str, points: int) -> dict[str, str] | None:
        """Note *name*'s score if they are in the current match; the result when it is decided."""
        match = self.current()
        if match is None:
            return None
        who = next((n for n in match if n.casefold() == name.strip().casefold()), None)
        if who is None or who in self.scores:
            return None
        self.scores[who] = int(points)
        if len(self.scores) < 2:
            return self.public()
        a, b = match
        if self.scores[a] == self.scores[b]:
            winner, how = self.rng.choice(match), "A tie! A coin decides"
        else:
            winner = a if self.scores[a] > self.scores[b] else b
            how = f"{a} {self.scores[a]} – {self.scores[b]} {b}"
        self.winners.append(winner)
        self.index, self.scores = self.index + 1, {}
        if self.index < len(self.matches):
            following = self.public()
            return {"title": self.TITLE, "text": f"🏆 {winner} wins",
                    "detail": f"{how}  ·  Next: {following['text']}"}  # fmt: skip
        if len(self.winners) == 1:
            self.champion = winner
            return {"title": self.TITLE, "text": f"👑 {winner}", "detail": f"{how}  ·  Champion!"}
        survivors = list(self.winners)
        self._next_round(survivors)
        return {"title": self.TITLE, "text": f"🏆 {winner} wins",
                "detail": f"{how}  ·  Round {self.round}: {self.public()['text']}"}  # fmt: skip


BIRTHDAY_SEARCH = "Happy Birthday to You karaoke"  # the song queued for the birthday singer


def birthday(name: str) -> dict[str, str]:
    name = name.strip() or "you"
    return {
        "title": "🎂 Happy Birthday!",
        "text": f"🎉 {name} 🎉",
        "detail": "Everyone sing along!",
    }
