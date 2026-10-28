# The mixing console

Open **Mixer** in the console's menu. The desk has four microphone channels on the left and the
master section on the right.

## A channel strip, top to bottom

| Control | What it does |
|---|---|
| Input | The microphone for this channel: a sound card input, a connected phone, *System Default*, or *Off* |
| GAIN | How loud the microphone comes in. Set it so normal singing lights the green signal LED but loud singing does not light the red PEAK LED |
| HIGH, MID, LOW | Three-band EQ, ±12 dB. A little HIGH adds clarity; less LOW reduces boom close to the microphone |
| COMP | Compressor: brings quiet words up and holds loud ones back. 20–40 % suits most singers |
| ECHO | The classic karaoke echo |
| FX | Reverb, the sound of a room or hall |
| PAN | Left or right in the stereo picture |
| Fader | The channel's level in the mix |
| MUTE | Silences the channel |

Every channel also has a low cut and a noise gate built in, so an open microphone stays silent
until someone sings into it.

## The master section

- **Display**: the output device, whether the mixer is running, where vocal separation runs,
  and the feedback guard. `XRUN n` means the computer was too busy to deliver sound in time n
  times; `BAD n` means a microphone sent data that was not sound n times (it is replaced by
  silence).
- **MAIN OUT**: where all sound goes, music and microphones. Prefer a wired device.
- **MIC ON**: mixes the microphones into the output. **RESCAN** looks for newly connected devices.
- **Feedback guard**: see below.
- **Effect preset**: Pop, Ballad, Rock, KTV Hall and Dry set the EQ, echo and reverb of every
  channel at once. *Save As* keeps your own setting (taken from channel 1).
- **MUSIC, MICS, MAIN**: the music level, all microphones together, and everything.

The phone page's **REMOTE** tab has the same microphone controls, so singers can adjust their
own sound.

## Feedback guard

Feedback is the squeal when a microphone picks up its own sound from the speakers. The guard
listens for a single pure tone that stands out and cuts just that frequency.

| Setting | Behaviour |
|---|---|
| Off | Nothing is cut |
| Low (default) | Only a tone that keeps getting louder, as feedback does, or that lasts a full second. Whistling and held notes are left alone |
| Medium | Any steady pure tone after about a tenth of a second. A whistle is cut too |
| High | Quicker and less picky still |

The display shows how many frequencies it is cutting. Cuts are released by themselves after a
while.

## Getting a good sound

1. Start with the **Pop** preset and every fader at the 0 mark.
2. Set **GAIN** while someone sings their loudest part: no red PEAK.
3. Balance **MUSIC** and **MICS** so the voice sits on top of the music.
4. Add **ECHO** and **FX** to taste. Less is usually better for fast songs.
5. If it squeals, move the microphone away from the speakers before turning up the guard.
