# Troubleshooting

## My voice comes out late

Almost always the speakers are wireless. **AirPlay** adds one to two seconds and **Bluetooth** a
few hundred milliseconds. Connect the speakers or TV with a cable and choose them in
**Mixer → MAIN OUT**. A phone used as a microphone adds roughly 40–120 ms on top of that.

## All sound stops, but the video keeps playing

1. Look at the display on the **Mixer** page: note any `BAD n` or `XRUN n`.
2. Press **MIC ON** off and on again.
3. Check that the output device in **MAIN OUT** is still connected (an AirPlay or Bluetooth
   device may have dropped).

Then please [open an issue](https://github.com/TonyD365/YTKTV/issues/new/choose) with what you
saw in step 1 and whether step 2 helped.

## A loud squeal

That is feedback: a microphone hears the speakers. Move the microphone away from the speakers,
turn the speakers away from the singers, lower GAIN, and set the **feedback guard** to *low* or
*medium* on the Mixer page.

## A song will not play, or plays in low quality

Some videos are restricted by YouTube. YTKTV falls back to other ways of playing them; videos
"made for kids" may only be available in low quality unless **Settings → Restricted Videos** is
installed. If a song still fails, use the **A song does not work** form on the
[issues page](https://github.com/TonyD365/YTKTV/issues/new/choose) and include the link.

## No lyrics

Lyrics come from the video's subtitles, or YouTube's automatic captions when it has none. Some
videos have neither. Turn **Lyrics** on in the control bar. If the lyrics run ahead of or behind
the singing, use the arrows beside the Lyrics button.

## The instrumental never gets ready

Vocal separation runs in the background and takes from seconds (with a GPU) to a few minutes
(on the processor) per song. Check **Settings → Vocal Separation**: on Windows and Linux the
runtime may still need to be installed. Intel Macs cannot run it; use **More → Vocal Cut**.

## macOS: "YTKTV is damaged" or "cannot be opened"

Run `sudo xattr -dr com.apple.quarantine /Applications/YTKTV.app` in Terminal, then open it again.

## Getting a log for a bug report

A log shows what YTKTV was doing when something went wrong. Start YTKTV like this, reproduce the
problem, quit, and attach the file to your issue.

**macOS** (Terminal):

```bash
YTKTV_LOG_FILE=~/Desktop/ytktv.log /Applications/YTKTV.app/Contents/MacOS/YTKTV --debug
```

**Windows** (Command Prompt):

```bat
set YTKTV_LOG_FILE=%USERPROFILE%\Desktop\ytktv.log
"%LOCALAPPDATA%\Programs\YTKTV\YTKTV.exe" --debug
```

**Linux**:

```bash
YTKTV_LOG_FILE=~/ytktv.log ./YTKTV-*.AppImage --debug
```

## Where YTKTV keeps its files

| | Settings, playlists, mpv | Cache (instrumentals, downloads) |
|---|---|---|
| macOS | `~/Library/Application Support/YTKTV` | `~/Library/Caches/YTKTV` |
| Windows | `%LOCALAPPDATA%\YTKTV` | `%LOCALAPPDATA%\YTKTV\Cache` |
| Linux | `~/.local/share/YTKTV` | `~/.cache/YTKTV` |

Deleting the cache is safe: instrumentals are made again when needed. Deleting the `mpv` folder
makes YTKTV download mpv again on the next start.
