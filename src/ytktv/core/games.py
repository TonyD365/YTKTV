"""Party games like a KTV room's: dice, a spin to pick the next singer, truth or dare."""

from __future__ import annotations

import random

from ytktv.i18n import N_, t

DICE = "⚀⚁⚂⚃⚄⚅"

TRUTHS = (
    N_("Which song do you secretly sing in the shower?"),
    N_("Who in this room would you duet with?"),
    N_("What is the most embarrassing song on your phone?"),
    N_("What was your worst karaoke moment?"),
    N_("Which singer did you have a crush on?"),
    N_("What song always makes you cry?"),
)
DARES = (
    N_("Sing the next chorus in a whisper."),
    N_("Dance through the whole next song."),
    N_("Sing the next song with your eyes closed."),
    N_("Do your best impression of the original singer."),
    N_("Sing one line in a different language."),
    N_("Pick a duet partner and sing the next song together."),
)


def roll_dice(count: int = 5, rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    faces = [rng.randrange(6) for _ in range(count)]
    total = sum(faces) + count
    return {
        "title": t("🎲 Dice"),
        "text": " ".join(DICE[f] for f in faces),
        "detail": t("Total {total}", total=total),
    }


def spin(names: list[str], rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    names = [n for n in dict.fromkeys(n.strip() for n in names) if n]
    if not names:
        return {"title": t("🎡 Spin"), "text": t("Add singers first"), "detail": ""}
    return {"title": t("🎡 Next to sing"), "text": rng.choice(names), "detail": ""}


def truth_or_dare(kind: str, rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    if kind == "truth":
        return {"title": t("💬 Truth"), "text": t(rng.choice(TRUTHS)), "detail": ""}
    return {"title": t("🔥 Dare"), "text": t(rng.choice(DARES)), "detail": ""}


CHALLENGES = (
    N_("Sing the next song in a baby voice."),
    N_("Sing the next song as an opera singer."),
    N_("Duet the next song with the person on your left."),
    N_("Sing the next chorus without looking at the lyrics."),
    N_("Everyone sings the next chorus together."),
    N_("Sing the next song while doing a dance move on every line."),
    N_("Swap the next song with the person on your right."),
    N_("Sing the next song in slow motion (Tempo down)."),
    N_("Sing the next song one key higher."),
    N_("Introduce the next song like a radio DJ first."),
)
LOTS = (
    N_("Drink!"),
    N_("Sing next!"),
    N_("Safe"),
    N_("Safe"),
    N_("Pick someone to drink"),
    N_("Everyone drinks!"),
)


def challenge(rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    return {"title": t("🎤 Challenge card"), "text": t(rng.choice(CHALLENGES)), "detail": ""}


def draw_lots(names: list[str], rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    names = [n for n in dict.fromkeys(n.strip() for n in names) if n]
    who = rng.choice(names) if names else t("You")
    return {"title": t("🥢 Draw lots"), "text": f"{who}: {t(rng.choice(LOTS))}", "detail": ""}


def high_low(names: list[str], rng: random.Random | None = None) -> dict[str, str]:
    """Everyone rolls one die: the highest picks the next song, the lowest drinks."""
    rng = rng or random.Random()
    names = [n for n in dict.fromkeys(n.strip() for n in names) if n] or [
        t("Player 1"),
        t("Player 2"),
    ]
    if len(names) == 1:
        names.append(t("The machine"))
    rolls = {name: rng.randrange(6) for name in names}
    best, worst = max(rolls.values()), min(rolls.values())
    winners = [n for n, r in rolls.items() if r == best]
    losers = [n for n, r in rolls.items() if r == worst]
    return {
        "title": t("🎲 High or low"),
        # Numbers, not dice faces: next to names the faces are too small to read.
        "text": "   ".join(f"{n} {r + 1}" for n, r in rolls.items()),
        "detail": t(
            "High: {value}  ·  Low: {value2}", value=", ".join(winners), value2=", ".join(losers)
        ),
    }


def coin(rng: random.Random | None = None) -> dict[str, str]:
    rng = rng or random.Random()
    return {"title": t("🪙 Coin"), "text": rng.choice((t("Heads"), t("Tails"))), "detail": ""}


def is_seven(n: int) -> bool:
    return n % 7 == 0 or "7" in str(n)


class Sevens:
    """Count out loud and say "pass" instead of any number with a 7 or divisible by 7."""

    def __init__(self) -> None:
        self.n = 0

    def next(self) -> dict[str, str]:
        self.n += 1
        if is_seven(self.n):
            return {"title": t("7️⃣ Sevens"), "text": t("PASS!"), "detail": f"({self.n})"}
        return {"title": t("7️⃣ Sevens"), "text": str(self.n), "detail": t("Next person!")}

    def reset(self) -> dict[str, str]:
        self.n = 0
        return {"title": t("7️⃣ Sevens"), "text": t("Start from 1"), "detail": ""}


class NumberBomb:
    """A secret number between 1 and 100; every wrong guess shrinks the range."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.start()

    def start(self) -> dict[str, str]:
        self.low, self.high = 1, 100
        self.secret = self.rng.randint(2, 99)
        return {"title": t("💣 Number bomb"), "text": "1 – 100", "detail": t("Guess a number!")}

    def guess(self, n: int, who: str = "") -> dict[str, str]:
        if not self.low < n < self.high:
            return {
                "title": t("💣 Number bomb"),
                "text": f"{self.low} – {self.high}",
                "detail": t("{n} is not in the range", n=n),
            }
        if n == self.secret:
            boomed = t("{who} hit the bomb!", who=who) if who else t("You hit the bomb!")
            result = {"title": t("💥 BOOM!"), "text": str(n), "detail": boomed}
            self.start()
            return result
        if n < self.secret:
            self.low = n
        else:
            self.high = n
        return {"title": t("💣 Number bomb"), "text": f"{self.low} – {self.high}", "detail": ""}


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
            "title": t("🎲 Liar's dice"),
            "text": t("{count} players rolled", count=len(self.hands)),
            "detail": t("Make your bids, then reveal"),
        }

    def reveal(self) -> dict[str, str]:
        if not self.hands:
            return {"title": t("🎲 Liar's dice"), "text": t("Nobody rolled yet"), "detail": ""}
        counts = [sum(hand.count(face) for hand in self.hands.values()) for face in range(6)]
        hands = "   ".join(f"{t(p) if p == 'Console' else p}: {self.hand(p)}" for p in self.hands)
        # Ones are wild in liar's dice: they count as every other face.
        totals = "  ".join(f"{DICE[f]}×{counts[f] + (counts[0] if f else 0)}" for f in range(6))
        self.hands = {}
        return {"title": t("🎲 Liar's dice — reveal"), "text": hands, "detail": totals}


class Tournament:
    """King of Singers: knockout rounds of one-on-one songs; the higher score goes through.

    Scores come from the score card when a match's singer finishes a song (or are typed in).
    """

    TITLE = N_("👑 King of Singers")

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
            return {"title": t(self.TITLE), "text": f"👑 {self.champion}", "detail": t("Champion!")}
        match = self.current()
        if match is None:
            return {"title": t(self.TITLE), "text": t("Add singers and start"), "detail": ""}
        scored = "  ·  ".join(f"{n} {self.scores[n]}" for n in match if n in self.scores)
        bye = (
            t("  ·  {winner} goes through", winner=self.winners[0])
            if self.winners and self.index == 0
            else ""
        )
        return {
            "title": t("{title} · Round {round}", title=t(self.TITLE), round=self.round),
            "text": f"{match[0]}  vs  {match[1]}",
            "detail": t("Match {value} of {count}", value=self.index + 1, count=len(self.matches))
            + (f"  ·  {scored}" if scored else t("  ·  each sings one song"))
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
            winner, how = self.rng.choice(match), t("A tie! A coin decides")
        else:
            winner = a if self.scores[a] > self.scores[b] else b
            how = f"{a} {self.scores[a]} – {self.scores[b]} {b}"
        self.winners.append(winner)
        self.index, self.scores = self.index + 1, {}
        if self.index < len(self.matches):
            following = self.public()
            detail = t("{how}  ·  Next: {text}", how=how, text=following["text"])
            return {"title": t(self.TITLE), "text": t("🏆 {winner} wins", winner=winner),
                    "detail": detail}  # fmt: skip
        if len(self.winners) == 1:
            self.champion = winner
            return {
                "title": t(self.TITLE),
                "text": f"👑 {winner}",
                "detail": t("{how}  ·  Champion!", how=how),
            }
        survivors = list(self.winners)
        self._next_round(survivors)
        detail = t(
            "{how}  ·  Round {round}: {text}", how=how, round=self.round, text=self.public()["text"]
        )
        return {"title": t(self.TITLE), "text": t("🏆 {winner} wins", winner=winner),
                "detail": detail}  # fmt: skip


BIRTHDAY_SEARCH = "Happy Birthday to You karaoke"  # the song queued for the birthday singer


def birthday(name: str) -> dict[str, str]:
    name = name.strip()
    name = t("you") if name in ("", "you") else name
    return {
        "title": t("🎂 Happy Birthday!"),
        "text": f"🎉 {name} 🎉",
        "detail": t("Everyone sing along!"),
    }
