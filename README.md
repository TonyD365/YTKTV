# YTKTV

Turn any computer into a karaoke (KTV) machine powered by YouTube.

The main display becomes a KTV song console, an extended display shows the music video full
screen, guests pick songs from their phones, and a built-in mixing console blends the
microphones into the music with reverb and echo.

[![CI](https://github.com/TonyD365/YTKTV/actions/workflows/ci.yml/badge.svg)](https://github.com/TonyD365/YTKTV/actions/workflows/ci.yml)

## Features

- **Any YouTube video is a song.** Search from the console or the phone, paste a link, or browse
  the Hot Songs categories. Playback streams straight from YouTube through mpv: no ads, no
  embedded web player.
- **MV screen.** A borderless full-screen window on the extended display, with a
  "Now Playing" / "Up Next" banner and an idle screen showing the phone QR code.
- **Original / Instrumental switch.** Every selected song is split into vocals and backing track
  in the background with an AI model, on the GPU when one is available (Apple Silicon via Metal,
  NVIDIA via CUDA, other Windows GPUs via DirectML). Both tracks play together and switching is
  a crossfade, so there is no gap. A song waits for its instrumental before it starts (shown as
  "Preparing instrumental"), and work on songs removed from the queue is cancelled. *Vocal Cut*
  and *L* / *R* (for classic split-track KTV videos) need no preparation.
- **Smooth playback.** The next songs in the queue are downloaded ahead of time and played from
  disk; only the first song of a session streams, with a loading screen until it is ready.
  Separation runs in its own low-priority process so it cannot disturb the live sound.
- **Mixing console.** Four microphone channels laid out like a hardware desk: input selection,
  GAIN, 3-band EQ, ECHO, FX (reverb), PAN, fader, MUTE and PEAK LEDs; MUSIC, MICS and MAIN bus
  faders, an OUTPUT meter for the total level (music and microphones), and output device
  selection. Each channel has a low cut and a noise gate, so an open microphone stays silent
  until someone sings. Microphones are mixed into the output
  automatically.
- **KTV controls.** Queue, Priority (play next), Skip, Replay, Pause, Key up/down (±6 semitones),
  Tempo, favorites, sung history, plus Applause / Cheer / Air Horn / Drum Roll buttons.
- **Phone remote.** A local web page for searching, queueing and remote control. No app to
  install: scan the QR code.
- **Automatic updates.** Installed builds update themselves from the latest GitHub release.

## Install

### Installers

Download the installer for your system from the
[latest release](https://github.com/TonyD365/YTKTV/releases/latest):

| System | File |
|---|---|
| macOS (Apple Silicon and Intel) | `YTKTV-<version>-macos-universal.pkg` |
| Windows 10/11 (64-bit) | `YTKTV-<version>-windows-x64-setup.exe` |
| Linux (x86-64) | `YTKTV-<version>-linux-x86_64.AppImage` |

The installers are not code-signed yet. On macOS, remove the download quarantine with `xattr`
before opening the package:

```bash
xattr -d com.apple.quarantine ~/Downloads/YTKTV-<version>-macos-universal.pkg
```

If macOS still refuses to open the app after installing, run
`sudo xattr -dr com.apple.quarantine /Applications/YTKTV.app`. On Windows, choose
**More info → Run anyway** in the SmartScreen prompt.

### Vocal separation and your graphics card

| System | How the installer provides it | Runs on |
|---|---|---|
| macOS, Apple Silicon | Built in | GPU (Metal) |
| Windows | Downloaded on first run | NVIDIA GPU (CUDA), other GPUs (DirectML), or CPU |
| Linux | Downloaded on first run | NVIDIA GPU (CUDA) or CPU |
| macOS, Intel | Not available | Vocal Cut and L / R still work |

On Windows and Linux, YTKTV checks the graphics card the first time it starts and offers to
download the matching runtime: about 2.5 GB for NVIDIA, about 1 GB for DirectML, about 500 MB
for CPU. It asks before downloading, and the same choice is available later under
**Settings → Vocal Separation**. NVIDIA cards need their driver installed first. If the GPU
runtime cannot be installed, YTKTV falls back to the CPU one.

### From source

Requires Python 3.11 or newer.

```bash
git clone https://github.com/TonyD365/YTKTV.git
cd YTKTV
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[separation]"     # leave out [separation] to skip the AI vocal remover
ytktv
```

On first start YTKTV looks for mpv (libmpv) and offers to install it if it is missing:
`brew install mpv` on macOS, a download from the official Windows builds on Windows, or your
package manager on Linux (`libmpv2` / `mpv-libs` / `mpv`). ffmpeg is bundled.

Linux also needs PortAudio for the mixer: `sudo apt-get install libportaudio2`.

NVIDIA users can install `".[separation-cuda]"` instead for CUDA-accelerated separation.

## Using it

1. Connect a second display (TV or projector) and start YTKTV. The console opens on the main
   display and the MV screen goes full screen on the other one. With a single display the MV
   screen stays a normal window; choose the display under **Settings → MV Screen**.
2. Scan the QR code with a phone on the same Wi-Fi, or use **Search** on the console.
3. Press **Select** to queue a song or **Priority** to play it next.
4. Open **Mixer** to choose each microphone and the output device, then set levels.

Use headphones or keep microphones away from the speakers while setting levels: an open
microphone next to loud speakers will feed back, exactly like a real PA system.

### Console layout

| Area | What it does |
|---|---|
| Top bar | Now playing, progress, next song, phone QR code |
| Left | Search, Hot Songs, Favorites, Selected (queue), Sung (history), Mixer, Settings |
| Bottom bar | Original / Instrumental / Vocal Cut / L / R, Replay, Play/Pause, Skip, Key, Tempo, Music and Mic volume, crowd effects |

`F11` toggles full screen for the console. On the MV screen, double-click or press `F` to
toggle full screen.

### Command line

```
ytktv [--port PORT] [--no-mic] [--windowed] [--debug]
```

| Option | Meaning |
|---|---|
| `--port` | Port for the phone remote (default 8765) |
| `--no-mic` | Start without the microphone mixer |
| `--windowed` | Keep the MV screen in a window for this run |
| `--debug` | Verbose logging |

### Notes

- The phone remote is open to everyone on your local network and has no password. Run it on a
  network you trust.
- Vocal separation needs a moment per song (well under a minute on a recent GPU, a few minutes
  on CPU), so songs queued in advance are ready by the time they play. Results are cached, so a
  song is only processed once. The model (about 60 MB) is downloaded the first time.
- YouTube changes often. If videos stop playing, update yt-dlp (`pip install -U yt-dlp`) or
  install the newest YTKTV release.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy src
pytest
```

The core (queue, controller, DSP, server, updater) has no dependency on Qt, mpv or audio
hardware, so the test suite runs headless.

```
src/ytktv/
  core/         models, song queue, event bus, KTVController (the single command entry point)
  youtube/      yt-dlp search, stream resolution, parsing
  player/       libmpv player and a fake for tests
  separation/   vocal separation worker and cache
  audio/        DSP effects, mixer engine, synthesised crowd effects
  server/       FastAPI app and the phone page
  ui/           PySide6 console, mixing console, MV window
  updater.py    GitHub-release self-update
  bootstrap.py  finds or installs libmpv and ffmpeg
```

### Benchmarks

```bash
pytest benchmarks --benchmark-only
```

Covers microphone DSP cost per audio block, queue and controller operations, phone API latency
and YouTube result parsing. Everything runs offline.

Every pull request runs the suite for the base branch and for the pull request on the same CI
runner, posts a comparison as a comment, and fails if a benchmark gets more than 25% slower.
To compare two runs yourself:

```bash
pytest benchmarks --benchmark-only --benchmark-json=head.json
python benchmarks/compare.py --base base.json --head head.json
```

### Releasing

Versions come from git tags; there is no version number in the source.

1. On GitHub, open **Releases → Draft a new release**.
2. Choose a new tag such as `v1.2.3` on `main`, keep **Set as the latest release** ticked, and
   publish.
3. The `Release` workflow builds the universal macOS `.pkg`, the Windows installer and the
   Linux AppImage from that tag and attaches them, together with `SHA256SUMS`, to the release.

Installed copies check `releases/latest` at startup and every six hours. Once the installers
are attached they download the one for their platform, verify its checksum, and offer to
install when nothing is playing. A release marked as a pre-release is not offered as an update.

Run the workflow manually (*Actions → Release → Run workflow*) to test the builds without
touching any release.

The macOS package is signed and notarized when the Developer ID secrets listed at the top of
the macOS build step in `.github/workflows/release.yml` are configured; otherwise it is ad-hoc
signed.

To build the macOS package locally: `brew install mpv`, `pip install -e ".[package]"`, then
`packaging/macos/build_pkg.sh`.

## License

MIT
