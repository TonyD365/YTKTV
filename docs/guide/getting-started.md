# Getting started

## What you need

- A computer: a Mac (Apple Silicon or Intel), a Windows 10/11 PC, or a Linux PC (x86-64).
- A TV or projector as a second screen. One screen also works; the video then opens in a window.
- Speakers, ideally connected **with a cable** (see [Sound and delay](#sound-and-delay)).
- One or more microphones: USB microphones, a wireless microphone receiver, an audio
  interface, or a phone (see [Phones](phones.md)).
- An internet connection: songs come from YouTube.

## Install

Download the installer from the [latest release](https://github.com/TonyD365/YTKTV/releases/latest).

**macOS.** The package is not signed with a paid Apple certificate yet, so remove the download
quarantine first, in Terminal:

```bash
xattr -d com.apple.quarantine ~/Downloads/YTKTV-*-macos-universal.pkg
```

Then open the package. If the installed app still will not open, run
`sudo xattr -dr com.apple.quarantine /Applications/YTKTV.app`.

**Windows.** Run the setup program. If SmartScreen stops it, choose **More info → Run anyway**.

**Linux.** Make the AppImage executable (`chmod +x YTKTV-*.AppImage`) and run it.

## The first start

1. If **mpv**, the free video player YTKTV uses, is not installed yet, YTKTV offers to install
   it: with Homebrew on macOS (`brew install mpv`; without Homebrew it shows how to get it),
   by downloading the Windows build listed on mpv.io on Windows, or with your package manager
   on Linux. This happens once and needs the internet.
2. A short **setup** asks three things, each applied as soon as you choose it:
   - **Sound**: the speakers. Press *Play Test Sound* to check.
   - **MV Screen**: the TV. The music video moves there at once.
   - **Microphone**: the microphone for channel 1. Say something; the bar moves when it hears you.
3. On Windows and Linux, YTKTV may offer to download the **vocal separation** runtime that fits
   your graphics card. It is needed for the *Instrumental* mode and for scoring.

You can run the setup again at any time from **Settings → Setup**.

## Your first song

1. Press **Search**, type a song, and press **Select** on a result (or **Priority** to play it
   next).
2. The song appears on the TV. The first song of the evening takes a moment to load; the
   ones after it are prepared while the previous one plays.
3. Choose **Original** or **Instrumental** in the control bar. *Instrumental* needs the vocal
   separation; until it is ready, the song waits ("Preparing instrumental").
4. Turn on **Lyrics** and **Score** in the control bar if you like.

Guests can queue songs from their phones by scanning the QR code in the top right corner of
the console or on the TV while nothing plays. See [Phones](phones.md).

## The control bar

| Group | Buttons |
|---|---|
| Vocals | Original, Instrumental, More (Vocal Cut, Left Only, Right Only for old split-track videos) |
| Playback | Replay, Play/Pause, Skip, Score, Lyrics, and the arrows that move the lyrics 0.1 s earlier or later |
| Key, Tempo | Key down/up (±6 semitones), slower/faster |
| Guide, Music, Mic | How much of the original singer stays in Instrumental mode; music volume; microphone volume |
| Crowd | Applause, Cheer, Air Horn, Drum Roll, Lights |

## Sound and delay

Choose the speakers in **Mixer → MAIN OUT**. Use speakers connected with a cable (HDMI to the
TV, USB, or the headphone jack). **AirPlay delays sound by one to two seconds and Bluetooth by a
few hundred milliseconds**: fine for watching, but you hear your own voice late when you sing.
That delay is part of how wireless audio works and cannot be tuned away.

Keep microphones away from the speakers and do not point them at each other, or the sound will
feed back (a loud squeal). The [feedback guard](mixer.md#feedback-guard) helps, but distance
helps more.
