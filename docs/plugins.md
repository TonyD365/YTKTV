# Writing YTKTV plugins

A plugin is a small Python add-on. It can listen to what happens in the room, add colour
themes, add songs to search results and show short messages on the TV.

## The smallest plugin

```python
"""Says the song title when a song starts."""

NAME = "Hello"
VERSION = "1.0.0"
PERMISSIONS = ["events", "toast"]
API_VERSION = 1


def setup(api):
    def on_state(_payload):
        song = api.now_playing()
        if song:
            api.toast(f"Now singing: {song['title']}")

    api.on("state", on_state)
```

A fuller example is in [examples/plugins/hello_plugin.py](../examples/plugins/hello_plugin.py).

## Installing

- **A single file:** copy the `.py` file into the `plugins` folder of the YTKTV data folder.
  Settings → Plugins shows the exact path.
- **A package:** publish it on PyPI with an entry point in the `ytktv.plugins` group:

  ```toml
  [project.entry-points."ytktv.plugins"]
  hello = "ytktv_hello"
  ```

A plugin stays off until the venue turns it on in **Settings → Plugins**. Before it is
turned on, YTKTV shows what it asks for. Changes take effect the next time YTKTV starts.
If a new version asks for more than the venue agreed to, it is turned off again until the
venue agrees.

## Permissions

| Permission | Lets the plugin |
| --- | --- |
| `events` | use `api.on(topic, callback)` and `api.now_playing()` |
| `themes` | use `api.add_theme(name, colours)` |
| `songs` | use `api.add_song_source(search)` |
| `toast` | use `api.toast(text)` |

Calling something you did not ask for raises `PermissionDenied`, and the plugin is turned
off for the session.

Permissions say what a plugin means to do. They are **not a sandbox**: a plugin is Python
code running with this computer's access. Venues should only turn on plugins they trust.

## The API

- `api.on(topic, callback)`: `callback(payload)` runs whenever the app emits `topic`.
  Topics include `state`, `score`, `lyrics`, `game`, `reaction` and `toast`. Use `"*"` to
  get every topic as `callback(topic, payload)`. Callbacks run on the app's own threads,
  so return quickly.
- `api.now_playing()`: the song on screen (`video_id`, `title`, `channel`, `singer`), or
  `None`.
- `api.add_theme(name, colours)`: a theme based on Neon. `colours` replaces any of `BG`,
  `PANEL`, `PANEL_2`, `LINE`, `TEXT`, `MUTED`, `PINK`, `CYAN`, `PURPLE`, `GOLD`, `GREEN`
  and `DANGER` with `#rrggbb` colours.
- `api.add_song_source(search)`: `search(query)` returns `ytktv.core.models.Song` objects
  with YouTube video ids. They are added after the normal results (at most 20 per
  plugin). It runs off the GUI thread.
- `api.toast(text)`: a short message on the TV.
- `api.data_dir`: a folder of the plugin's own for files it keeps.
- `api.log`: a `logging.Logger` for the plugin.
- `api.api_version`: the plugin API version, `1` today. A plugin that sets a higher
  `API_VERSION` than YTKTV supports is not loaded.

## When something goes wrong

If `setup`, a callback or a song source raises an error, the error is logged, the plugin
is turned off for the session and the error is shown in Settings → Plugins. YTKTV keeps
running.
