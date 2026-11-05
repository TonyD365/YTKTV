# More features

Smaller features that do not need a guide of their own.

## Voice effects

Each microphone channel in the **Mixer** has a voice box under its **MUTE** button. Pick
**Chipmunk** (higher), **Deep** (lower) or **Robot**; **Voice: Off** turns it off again.

## Mood scenes

On the **Party** page, under **Mood**, pick **Birthday**, **Romantic**, **Party** or **Chill**.
The MV screen's edge lights and any smart lights keep to that scene's colours and still pulse
with the music; Birthday starts with a cheer and Party with an air horn. **Usual** goes back to
the normal colours.

## Spotify and Apple Music playlists

Open **Playlists → Import Playlist** and paste the link of a public Spotify or Apple Music
playlist, or a list of songs, one per line. Each song is looked up on YouTube, karaoke versions
first, and the result is saved as a playlist.

## AI lyrics

When a song has no lyrics anywhere, YTKTV can write them, with the timing, using Whisper on
your computer. Turn it on in **Settings → AI Lyrics**; the first time, it downloads the model
once. It runs on the GPU on Apple Silicon and NVIDIA, and on the processor elsewhere (slower).

## Kids mode

For a children's room. In **Settings → Kids Mode**, songs not meant for children are left out
and cannot be chosen, and the volume cannot go above the ceiling you set. A room bound to
YTKTV Desk gets this from the desk's **Admin Settings** instead.

## Low-power mode

On a Raspberry Pi or an old computer, **Settings → Low-power mode** plays video at 720p and
turns off the light effects so songs stay smooth. On a weak computer it is already on from the
first start.

## Reporting a problem

The feedback button opens a GitHub issue with your version and system filled in. After an
unexpected error YTKTV asks whether to report it; a page opens with the details, and nothing
is sent until you read them and send it yourself.

## For YTKTV Desk

- **Service charge and tax**: set both percentages in the desk's settings. The service charge
  is added after discounts, and tax is added on everything, service charge included. Both show
  on the bill and the receipt.
- **Admin Settings**: select a bound room and press **⚙ Admin Settings** to change its video,
  sound output, vocal separation, local songs, smart lights, updates, kids mode and low-power
  mode from the desk. The room shows that these are managed by the desk. Every change is signed
  and numbered, so it cannot be forged or replayed.
