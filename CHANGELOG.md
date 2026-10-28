# Changelog

What changed in each release. The [releases page](https://github.com/TonyD365/YTKTV/releases)
has the installers and the full notes.

## 1.6.0

- **mpv is no longer attached to the releases.** When YTKTV finds no mpv it offers to install it
  the usual way for each system: Homebrew on macOS, the Windows build listed on mpv.io, the
  package manager on Linux. Copies that already downloaded mpv keep using it.
- The first song's lyrics show without pressing Lyrics off and on.
- One corrupt sample from a microphone no longer silences all sound until a restart.
- A live roadmap on the website, issue labels and forms, automatic pull request labels,
  Dependabot, and a more detailed benchmark report on pull requests.

## 1.5.0

- **Windows: YTKTV starts.** Every Windows build up to 1.4.1 failed to start (the web server
  behind the phone page tripped over the missing console of a windowed app). The Windows icon
  shows its lettering.
- **A phone as a microphone**, chosen on a channel of the mixing console; uncompressed sound,
  phone-side voice processing off, a short self-adjusting buffer.
- Duet scores: each microphone gets its own score and leaderboard line.
- Lyrics can be moved 0.1 s earlier or later per song.
- Feedback guard with off, low, medium and high; low leaves whistling and held notes alone.
- mpv downloads without asking, and is refreshed after an update. Quitting stops helper
  programs; old update installers are deleted. The mixer fits a small window.

## 1.4.1

- The separate mpv download for macOS no longer mixes two incompatible encryption libraries.

## 1.4.0

- Live pitch lane on the MV screen and tonight's leaderboard.
- Lyrics colour follows the singer word by word.
- Each phone sees its own songs and how long until its turn; drag to reorder the queue.
- Compressor and feedback guard on every microphone channel.
- First-start setup wizard.
- **New license**: free to use, also in a business, but not for sale. **mpv is downloaded on
  first start** instead of being inside the installers.

## 1.3.3

- A Lyrics button switches lyrics on and off, and uses automatic captions when a video has no
  subtitles. Smoother line changes.

## 1.3.2

- Fixed stuttering and crackling while lyrics are on screen.

## 1.3.1

- Fixed unreadable menus and search suggestions.

## 1.3.0

- Singing scores, playlists and YouTube playlist import, search suggestions and an Artists page,
  effect presets, mixing from the phone, and HD for restricted videos.

## 1.2.0

- Karaoke lyrics from the video's subtitles, guide vocal, danmaku and lights.

## 1.1.0

- Songs in the queue are prepared ahead; seamless original / instrumental switching; a total
  output meter; fixes for noise during separation.

## 1.0.0

- First release: YouTube karaoke with a full-screen MV display, AI vocal removal, a hardware-style
  mixing console, phone song requests, automatic updates, installers for macOS, Windows and Linux.
