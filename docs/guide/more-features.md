# More features

Smaller features that do not need a guide of their own.

## Voice effects

Each microphone channel in the **Mixer** has a voice box under its **MUTE** button. Pick
**Chipmunk** (higher), **Deep** (lower) or **Robot**; **Voice: Off** turns it off again.

## Background videos

**Settings → Background Videos** (off unless you turn it on) plays music videos by themselves
while nobody has chosen a song, like a KTV room before the first song. Choose to play from your
favorites and sung songs, or from one playlist. The first song anyone chooses starts at once;
background videos are not scored and are not added to Sung.

## Session recap

When YTKTV Desk closes a room, the room's TV shows a recap of the session: how many songs were
sung, the time spent singing, who sang the most (from the singer names in the queue), the
highest score and the best duet. Its QR code opens the same recap on a phone, from the room's
own phone remote server. The link carries a random code and stops working as soon as the room
opens for the next session. Turn it off in **Settings → MV Screen** ("Show a recap of the
session...").

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

Lyrics found online are often timed for a different upload, so they run early or late. YTKTV
can write the lyrics itself with Whisper, from the song's own audio, so they match the video.
Download it once in **Settings → AI Lyrics**.

- **With a GPU** (Apple Silicon or an NVIDIA card), every song's lyrics are written on your
  computer. Whisper listens to the singer separated from the band, which it hears far better.
  Until it is done, the lyrics found online are shown, then replaced. Songs coming up in the
  queue are written ahead, so they are usually ready when they start. A song needed right
  away (singing now or next) is separated in 30-second pieces, and each piece's lyrics appear
  as soon as it is done, while the rest of the song is still being worked on.
- **With only a processor**, that is too slow for every song: the lyrics found online are
  used, and Whisper writes only those of songs that have none.
- **Use the lyrics found online to get the words right** (on by default) gives Whisper those
  words as a hint for spelling. The timing always comes from the song.

Written lyrics are kept, so a song is only done once.

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
