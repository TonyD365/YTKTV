"""The Games page: a lobby of party games, each with its own screen.

Every game shows its result big on the console and on the MV screen. Rolling dice,
spinning names and flipping coins animate first; tests turn that off with
``GamesPage.animate = False`` so results are immediate.
"""

from __future__ import annotations

import random
import textwrap
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ytktv import i18n
from ytktv.core import games
from ytktv.i18n import N_, t
from ytktv.ui import icons
from ytktv.ui.pages import Context, Page
from ytktv.ui.support import run_async
from ytktv.youtube.search import HOT_CATEGORIES

STAGE_STYLE = (
    "QLabel#gameStage { background: #120c22; border: 1px solid #33284f; border-radius: 18px;"
    " color: white; padding: 18px; }"
)
SPIN_STYLE = (
    "QSpinBox { background: #1a1430; color: white; border: 1px solid #33284f;"
    " border-radius: 8px; padding: 6px 10px; font-size: 18px; min-width: 90px; }"
)


def stage_html(big: str, small: str = "", colour: str = "white", size: int = 64) -> str:
    # Emoji on the stage are drawn with our own icons, as big as the text.
    big = icons.html(big, colour if colour.startswith("#") else "#ffffff", size)
    small = icons.html(small, "#c9c3e6", 20)
    small_html = f"<div style='font-size:20px;color:#c9c3e6'>{small}</div>" if small else ""
    return f"<div style='font-size:{size}px;font-weight:800;color:{colour}'>{big}</div>{small_html}"


class GameScreen(QWidget):
    """One game: a title, how to play, a big stage, its own controls and a Start button."""

    key = ""
    icon = ""
    title = ""
    blurb = ""  # one line for the lobby
    rules = ""
    colour = "#7f77dd"
    start_text = N_("Start Game")

    def __init__(self, lobby: GamesPage) -> None:
        super().__init__()
        self.lobby = lobby
        self.controller = lobby.ctx.controller
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._frames: list[str] = []
        self._done: Callable[[], None] | None = None
        column = QVBoxLayout(self)
        column.setSpacing(14)
        top = QHBoxLayout()
        back = QPushButton(t("‹  All games"))
        back.clicked.connect(lobby.show_lobby)
        heading = QLabel(f"{self.icon}  {t(self.title)}")
        heading.setStyleSheet("color: white; font-size: 28px; font-weight: 800;")
        top.addWidget(back)
        top.addSpacing(12)
        top.addWidget(heading)
        top.addStretch()
        column.addLayout(top)
        rules = QLabel(t(self.rules))
        rules.setWordWrap(True)
        rules.setObjectName("muted")
        rules.setStyleSheet("font-size: 15px;")
        column.addWidget(rules)
        self.stage = QLabel()
        self.stage.setObjectName("gameStage")
        self.stage.setStyleSheet(STAGE_STYLE)
        self.stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stage.setWordWrap(True)
        self.stage.setTextFormat(Qt.TextFormat.RichText)
        self.stage.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        column.addWidget(self.stage, stretch=1)
        self.controls = QHBoxLayout()
        self.controls.setSpacing(10)
        column.addLayout(self.controls)
        self.start_button = QPushButton(t(self.start_text))
        self.start_button.setObjectName("accent")
        self.start_button.setMinimumHeight(56)
        self.start_button.setStyleSheet(
            f"QPushButton {{ background: {self.colour}; color: white; font-size: 20px;"
            " font-weight: 800; border-radius: 14px; }"
        )
        self.start_button.clicked.connect(self.start)
        column.addWidget(self.start_button)
        self.build()
        self.reset()

    # Subclasses fill these in.
    def build(self) -> None:
        """Add the game's own controls to self.controls."""

    def reset(self) -> None:
        self.show_stage(self.icon, t("Press Start Game"))

    def start(self) -> None:
        raise NotImplementedError

    # Helpers.
    def show_stage(self, big: str, small: str = "", colour: str = "white", size: int = 64) -> None:
        self.stage.setText(stage_html(big, small, colour, size))

    def button(self, text: str, handler: Callable[[], None]) -> QPushButton:
        item = QPushButton(text)
        item.setMinimumHeight(46)
        item.clicked.connect(handler)
        self.controls.addWidget(item)
        return item

    def animate(self, frames: list[str], done: Callable[[], None], interval: int = 70) -> None:
        """Flash *frames* on the stage, then call *done* (at once when animation is off)."""
        self._timer.stop()
        if not self.lobby.animate or not frames:
            done()
            return
        self._frames, self._done = list(frames), done
        self.start_button.setEnabled(False)
        self._timer.start(interval)

    def _tick(self) -> None:
        if self._frames:
            self.stage.setText(self._frames.pop(0))
            return
        self._timer.stop()
        self.start_button.setEnabled(True)
        if self._done is not None:
            done, self._done = self._done, None
            done()

    def finish(self, result: dict[str, str], colour: str = "white", size: int = 64) -> None:
        """Show the result here and on the TV."""
        self.show_stage(result["text"], result.get("detail", ""), colour, size)
        self.controller.announce(result)
        self.lobby.last_result = result


class DiceGame(GameScreen):
    key, icon, title, colour = "dice", "🎲", N_("Roll the Dice"), "#d4537e"
    blurb = N_("Roll up to six dice and add them up")
    rules = N_("Pick how many dice to roll. Highest total wins, or make up your own rule.")
    start_text = N_("Roll!")

    def build(self) -> None:
        self.controls.addWidget(QLabel(t("Dice")))
        self.count = QSpinBox()
        self.count.setRange(1, 6)
        self.count.setValue(5)
        self.count.setStyleSheet(SPIN_STYLE)
        self.controls.addWidget(self.count)
        self.controls.addStretch()

    def start(self) -> None:
        n = self.count.value()
        frames = [
            stage_html(" ".join(random.choice(games.DICE) for _ in range(n)), t("Rolling…"))
            for _ in range(14)
        ]
        self.animate(frames, lambda: self.finish(games.roll_dice(n), size=88))


class PlayersMixin:
    """Games played by a list of names: the singers, or names typed in."""

    lobby: GamesPage

    def players(self) -> list[str]:
        typed = [n.strip() for n in self.lobby.players.text().split(",")]
        names = [n for n in dict.fromkeys(typed) if n]
        return names or self.lobby.ctx.controller.singers()


class SpinGame(PlayersMixin, GameScreen):
    key, icon, title, colour = "spin", "🎡", N_("Who Sings Next?"), "#7f77dd"
    blurb = N_("Spin through the players and stop on one")
    rules = N_("Uses the players listed at the top of the lobby (or everyone in the queue).")
    start_text = N_("Spin!")

    def start(self) -> None:
        names = self.players()
        if not names:
            self.show_stage(
                t("Add players first"), t("Type names at the top of the games lobby"), size=36
            )
            return
        result = games.spin(names)
        order = names * 6
        start = random.randrange(len(names))
        frames = [
            stage_html(order[(start + i) % len(order)], t("Spinning…"), "#c9c3e6", 56)
            for i in range(22)
        ]
        frames += [stage_html(result["text"], t("Slowing down…"), "#c9c3e6", 56)] * 3
        self.animate(frames, lambda: self.finish(result, "#ffc94a", 80), interval=90)


class TruthOrDareGame(GameScreen):
    key, icon, title, colour = "truthdare", "💬", N_("Truth or Dare"), "#1d9e75"
    blurb = N_("Answer honestly, or do the dare")
    rules = N_("The player picks Truth or Dare, then reads the card out loud.")
    start_text = N_("Random: Truth or Dare")

    def build(self) -> None:
        self.button(t("💬  Truth"), lambda: self.draw("truth"))
        self.button(t("🔥  Dare"), lambda: self.draw("dare"))

    def start(self) -> None:
        self.draw(random.choice(("truth", "dare")))

    def draw(self, kind: str) -> None:
        result = games.truth_or_dare(kind)
        frames = [stage_html("🂠", t("Shuffling…"), size=96)] * 6
        colour = "#2ee6ff" if kind == "truth" else "#ff7a59"
        self.animate(frames, lambda: self.finish(result, colour, 34))


class NumberBombGame(GameScreen):
    key, icon, title, colour = "bomb", "💣", N_("Number Bomb"), "#c2410c"
    blurb = N_("Guess numbers until someone finds the bomb")
    rules = N_(
        "A bomb hides at a number between 1 and 100. Take turns guessing: the range shrinks"
        " with every miss. Whoever hits the bomb loses (and sings, or drinks)."
    )
    start_text = N_("New Bomb")

    def build(self) -> None:
        self.controls.addWidget(QLabel(t("Your guess")))
        self.guess = QSpinBox()
        self.guess.setRange(1, 100)
        self.guess.setValue(50)
        self.guess.setStyleSheet(SPIN_STYLE)
        self.controls.addWidget(self.guess)
        self.guess_button = self.button(t("💣  Guess"), self.try_guess)
        self.controls.addStretch()

    def reset(self) -> None:
        self.show_stage("💣", t("Press New Bomb to hide a number"))

    def start(self) -> None:
        result = self.controller.play_game("bomb")
        self.guess.setRange(2, 99)
        self.guess.setValue(50)
        self.show_stage(result["text"], t("Guess a number in between"), "#ffc94a", 80)
        self.lobby.last_result = result

    def try_guess(self) -> None:
        bomb = self.controller.bomb
        result = self.controller.play_game("bomb_guess", value=self.guess.value(), player="")
        if result["title"].startswith("💥"):
            frames = [stage_html("💥", "", "#ff3d3d", 120), stage_html("", "")] * 3
            self.animate(frames, lambda: self.finish(result, "#ff3d3d", 90), interval=120)
            self.guess.setRange(2, 99)
            return
        self.guess.setRange(bomb.low + 1, bomb.high - 1)
        self.show_stage(
            result["text"], result.get("detail") or t("Safe… next player!"), "#ffc94a", 80
        )
        self.lobby.last_result = result


class LiarsDiceGame(GameScreen):
    key, icon, title, colour = "liar", "🎲", N_("Liar's Dice"), "#5b3fa0"
    blurb = N_("Everyone rolls in secret, then bluff")
    rules = N_(
        "Everyone rolls five dice that only they can see: on their phone (Games → Liar's dice)"
        ' or here at the console. Take turns bidding, e.g. "four 5s". Ones are wild. When'
        " someone calls liar, press Reveal: every hand shows on the TV."
    )
    start_text = N_("Roll My Dice (Console)")

    def build(self) -> None:
        self.peek = self.button(t("👁  Hold to Peek"), lambda: None)
        self.peek.pressed.connect(self.show_hand)
        self.peek.released.connect(self.hide_hand)
        self.button(t("👀  Reveal Everyone"), self.reveal)

    def reset(self) -> None:
        players = len(self.controller.liars.hands)
        self.show_stage("🎲 🎲 🎲", t("{players} players rolled so far", players=players), size=72)

    def start(self) -> None:
        self.controller.play_game("liar_roll", player="Console")
        frames = [
            stage_html(" ".join(random.choice(games.DICE) for _ in range(5)), t("Rolling…"))
            for _ in range(10)
        ]
        self.animate(frames, self.hide_hand)

    def show_hand(self) -> None:
        hand = self.controller.liars.hand("Console")
        self.show_stage(hand or t("Roll first"), t("Only you should see this!"), "#ffc94a", 80)

    def hide_hand(self) -> None:
        players = len(self.controller.liars.hands)
        self.show_stage(
            "❓ ❓ ❓ ❓ ❓",
            t("Your dice are hidden · {players} players rolled", players=players),
            size=64,
        )

    def reveal(self) -> None:
        result = self.controller.play_game("liar_reveal")
        self.show_stage(result["text"], result.get("detail", ""), "white", 26)
        self.lobby.last_result = result


class RandomSongGame(GameScreen):
    key, icon, title, colour = "random", "🎰", N_("Random Song"), "#0e7490"
    blurb = N_("A slot machine picks your next song")
    rules = N_("Spins through a hot-songs list and queues whatever it stops on. No take-backs!")
    start_text = N_("Pull the Lever")

    def start(self) -> None:
        self.start_button.setEnabled(False)
        self.show_stage("🎰", t("Loading songs…"))
        category = random.choice(list(HOT_CATEGORIES))
        run_async(lambda: self.lobby.ctx.youtube.hot(category), self.spin, self.failed)

    def failed(self, _exc: Exception) -> None:
        self.start_button.setEnabled(True)
        self.show_stage("😕", t("Could not load a song list. Check the internet."), size=48)

    def spin(self, songs: list[Any]) -> None:
        self.start_button.setEnabled(True)
        if not songs:
            self.failed(Exception())
            return
        titles = [s.title for s in songs]
        frames = [stage_html(random.choice(titles), "🎰 🎰 🎰", "#c9c3e6", 32) for _ in range(18)]

        def land() -> None:
            result = self.controller.random_song(songs, who=self.lobby.players.text().split(",")[0])
            if result is not None:
                self.finish(result, "#2ee6ff", 36)

        self.animate(frames, land, interval=90)


class ChallengeGame(GameScreen):
    key, icon, title, colour = "challenge", "🎤", N_("Challenge Cards"), "#be185d"
    blurb = N_("Draw a dare for the next singer")
    rules = N_("Draw a card before the next song. The singer must follow it, or pick a forfeit.")
    start_text = N_("Draw a Card")

    def start(self) -> None:
        result = games.challenge()
        frames = [stage_html("🂠", t("Drawing…"), size=110)] * 5
        self.animate(frames, lambda: self.finish(result, "#ffc94a", 34))


class LotsGame(PlayersMixin, GameScreen):
    key, icon, title, colour = "lots", "🥢", N_("Draw Lots"), "#4d7c0f"
    blurb = N_("Everyone draws a stick: drink, sing or safe")
    rules = N_("Every player draws one lot. Some are safe, some are not.")
    start_text = N_("Everyone Draws")

    def start(self) -> None:
        names = self.players() or [t("You")]
        rng = random.Random()
        lots = [f"{n}: {t(rng.choice(games.LOTS))}" for n in names]
        result = {"title": t("🥢 Draw lots"), "text": "  ·  ".join(lots), "detail": ""}
        frames = [stage_html("🥢 " * min(8, len(names)), t("Drawing…"), size=56)] * 6
        self.animate(frames, lambda: self.finish(result, "white", 30))


class HighLowGame(PlayersMixin, GameScreen):
    key, icon, title, colour = "highlow", "⚖️", N_("High or Low"), "#7c2d12"
    blurb = N_("One die each: highest picks, lowest drinks")
    rules = N_("Every player rolls one die. The highest picks the next song; the lowest drinks.")
    start_text = N_("Roll for Everyone")

    def start(self) -> None:
        result = games.high_low(self.players())
        frames = [
            stage_html("  ".join(random.choice(games.DICE) for _ in range(4)), t("Rolling…"))
            for _ in range(12)
        ]
        self.animate(frames, lambda: self.finish(result, "white", 34))


class SevensGame(GameScreen):
    key, icon, title, colour = "sevens", "7️⃣", N_("Sevens"), "#1e40af"
    blurb = N_("Count up, but say PASS on sevens")
    rules = N_(
        "Take turns counting up. Any number with a 7 in it, or divisible by 7, must be"
        ' replaced by "PASS". Get it wrong and you lose. Press Next for each number.'
    )
    start_text = N_("Next Number")

    def build(self) -> None:
        self.button(t("↺  Start Over"), self.restart)

    def reset(self) -> None:
        self.show_stage("1", t("Press Next Number to start counting"), size=96)

    def restart(self) -> None:
        self.controller.play_game("sevens_reset")
        self.reset()

    def start(self) -> None:
        result = self.controller.play_game("sevens")
        passed = result["text"] == t("PASS!")
        self.show_stage(
            result["text"], result.get("detail", ""), "#ff3d9a" if passed else "white", 110
        )
        self.lobby.last_result = result


class CountdownGame(GameScreen):
    key, icon, title, colour = "countdown", "⏱", N_("Countdown"), "#9d174d"
    blurb = N_("A big timer on the TV for any race")
    rules = N_("Chug, find a song, finish the verse… pick the seconds and race the clock.")
    start_text = N_("Start Countdown")

    def build(self) -> None:
        self.controls.addWidget(QLabel(t("Seconds")))
        self.seconds = QSpinBox()
        self.seconds.setRange(3, 60)
        self.seconds.setValue(10)
        self.seconds.setStyleSheet(SPIN_STYLE)
        self.controls.addWidget(self.seconds)
        self.controls.addStretch()
        self._left = 0
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._count)

    def start(self) -> None:
        self._left = self.seconds.value()
        self.controller.countdown(self._left)
        self.show_stage(str(self._left), "", "#ffc94a", 140)
        self._clock.start(1000)

    def _count(self) -> None:
        self._left -= 1
        if self._left > 0:
            self.show_stage(str(self._left), "", "#ffc94a", 140)
        else:
            self._clock.stop()
            self.show_stage(t("Time!"), "", "#ff3d3d", 120)


class CoinGame(GameScreen):
    key, icon, title, colour = "coin", "🪙", N_("Flip a Coin"), "#a16207"
    blurb = N_("Heads or tails, settle it")
    rules = N_("Call heads or tails, then flip.")
    start_text = N_("Flip!")

    def start(self) -> None:
        result = games.coin()
        frames = [stage_html("🪙", side, size=100) for side in (t("Heads"), t("Tails")) * 6]
        self.animate(frames, lambda: self.finish(result, "#ffc94a", 96), interval=90)


class TournamentGame(PlayersMixin, GameScreen):
    key, icon, title, colour = "tournament", "👑", N_("King of Singers"), "#b45309"
    blurb = N_("Knockout rounds until one singer is king")
    rules = N_(
        "Uses the players at the top of the lobby (or everyone in the queue). Two singers per"
        " match each sing a song with their name on it; the score card decides who goes"
        " through. No scoring? Type the scores in below."
    )
    start_text = N_("Start Tournament")

    def build(self) -> None:
        self.controls.addWidget(QLabel(t("Score")))
        self.points = QSpinBox()
        self.points.setRange(1, 100)
        self.points.setValue(80)
        self.points.setStyleSheet(SPIN_STYLE)
        self.controls.addWidget(self.points)
        self.first = self.button("…", lambda: self.score(0))
        self.second = self.button("…", lambda: self.score(1))
        self.controls.addStretch()
        self._watch = QTimer(self)
        self._watch.timeout.connect(self.show_bracket)  # scores also arrive from the score card
        self._watch.start(1500)

    def reset(self) -> None:
        self.show_bracket()

    def show_bracket(self) -> None:
        state = self.controller.tournament.public()
        colour = "#ffc94a" if self.controller.tournament.champion else "white"
        if state["text"] == "Add singers and start":
            self.show_stage(self.icon, t("Press Start Tournament"))
        else:
            self.show_stage(state["text"], f"{state['title']}<br>{state['detail']}", colour, 48)
        match = self.controller.tournament.current()
        for button, index in ((self.first, 0), (self.second, 1)):
            button.setVisible(match is not None)
            if match is not None:
                button.setText(t("Score for {value}", value=match[index]))

    def start(self) -> None:
        names = self.players()
        if len(names) < 2:
            self.show_stage(t("Add players first"), t("At least two names, at the top"), size=36)
            return
        self.controller.play_game("tournament", player=",".join(names) + ",")
        self.show_bracket()

    def score(self, index: int) -> None:
        match = self.controller.tournament.current()
        if match is not None:
            self.controller.play_game("tournament_score", self.points.value(), match[index])
            self.show_bracket()


class BirthdayGame(GameScreen):
    key, icon, title, colour = "birthday", "🎂", N_("Birthday"), "#db2777"
    blurb = N_("Their name on the TV, then the birthday song")
    rules = N_(
        "Type whose birthday it is. Their name goes up on the TV and the birthday song plays next."
    )
    start_text = N_("Celebrate!")

    def build(self) -> None:
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("Whose birthday?"))
        self.controls.addWidget(self.name, stretch=1)

    def start(self) -> None:
        name = self.name.text().strip() or "you"
        self.start_button.setEnabled(False)
        self.show_stage("🎂", t("Finding the birthday song…"))

        def celebrate(songs: list[Any]) -> None:
            self.start_button.setEnabled(True)
            result = self.controller.birthday(name, songs[0] if songs else None)
            frames = [stage_html(c, "", size=96) for c in ("🎈", "🎁", "🎉", "🎂") * 3]
            self.animate(frames, lambda: self.show_stage(result["text"], result["detail"],
                                                         "#ff8ad0", 64))  # fmt: skip

        run_async(
            lambda: self.lobby.ctx.youtube.search(games.BIRTHDAY_SEARCH, 5),
            celebrate,
            lambda _exc: celebrate([]),
        )


SCREENS: tuple[type[GameScreen], ...] = (
    DiceGame,
    SpinGame,
    TruthOrDareGame,
    NumberBombGame,
    LiarsDiceGame,
    RandomSongGame,
    ChallengeGame,
    LotsGame,
    HighLowGame,
    SevensGame,
    CountdownGame,
    CoinGame,
    TournamentGame,
    BirthdayGame,
)
COLUMNS = 4


class GamesPage(Page):
    animate = True

    def __init__(self, ctx: Context) -> None:
        super().__init__(t("Games"), ctx)
        self.last_result: dict[str, str] | None = None
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack, stretch=1)

        lobby = QWidget()
        column = QVBoxLayout(lobby)
        column.setContentsMargins(0, 0, 0, 0)
        players_row = QHBoxLayout()
        players_row.addWidget(QLabel(t("Players")))
        self.players = QLineEdit()
        self.players.setPlaceholderText(
            t("Names, separated by commas (empty: everyone in the queue)")
        )
        players_row.addWidget(self.players, stretch=1)
        column.addLayout(players_row)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.screens: dict[str, GameScreen] = {}
        for index, screen_type in enumerate(SCREENS):
            screen = screen_type(self)
            self.screens[screen.key] = screen
            self.stack.addWidget(screen)
            tile = QPushButton()
            tile.setObjectName("tile")
            tile.setStyleSheet(
                f"#tile {{ background: {screen.colour}; text-align: left; padding: 16px; }}"
            )
            # Buttons do not wrap on their own; Chinese characters are about twice as wide.
            blurb = textwrap.fill(t(screen.blurb), 14 if i18n.current() == "zh_CN" else 30)
            tile.setText(f"{screen.icon}  {t(screen.title)}\n{blurb}")
            tile.setMinimumHeight(110)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.clicked.connect(lambda _c=False, k=screen.key: self.open_game(k))
            grid.addWidget(tile, index // COLUMNS, index % COLUMNS)
        column.addLayout(grid, stretch=1)
        self.stack.insertWidget(0, lobby)
        self.lobby = lobby
        self.stack.setCurrentWidget(lobby)

    def open_game(self, key: str) -> GameScreen:
        screen = self.screens[key]
        screen.reset()
        self.stack.setCurrentWidget(screen)
        return screen

    def show_lobby(self) -> None:
        self.stack.setCurrentWidget(self.lobby)
