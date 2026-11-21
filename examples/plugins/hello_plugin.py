"""Says hello when a song starts and adds a Sunset theme (a YTKTV example plugin)."""

NAME = "Hello"
VERSION = "1.0.0"
PERMISSIONS = ["events", "themes", "toast"]
API_VERSION = 1


def setup(api):
    api.add_theme("Sunset", {"PINK": "#ff7a45", "CYAN": "#ffd166", "BG": "#1a0f14"})
    last = {"title": ""}

    def on_state(_payload):
        song = api.now_playing()
        if song and song["title"] != last["title"]:
            last["title"] = song["title"]
            api.toast(f"Now singing: {song['title']}")

    api.on("state", on_state)
