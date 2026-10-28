# Phones

Phones need no app: they use the web browser. The phone and the computer must be on the same
Wi-Fi network.

## Queueing songs

Scan the QR code on the console (top right) or on the TV while nothing is playing. The page has
four tabs:

- **SEARCH**: find songs, see suggestions and recent searches, browse artists; *Select* queues
  a song, *Priority* plays it next.
- **QUEUE**: what is playing and coming up. **Your songs** shows the songs this phone queued,
  how many are ahead and roughly how long until each one; *Tonight's best* shows the scores.
- **LISTS**: playlists and favourites; import a YouTube playlist.
- **REMOTE**: pause, skip, scoring, lyrics and their timing, vocals, key and tempo, volumes, the
  microphone controls, and the phone microphone.

Type your name in the singer box once and it is shown next to your songs.

Phones are told apart by their address on the network. Two phones behind the same router
address (some guest networks do this) count as one.

## A phone as a microphone

1. On the phone page, open **REMOTE → Use this phone as a microphone**.
2. The browser warns about the certificate the first time. Choose to continue (on iPhone:
   *Show Details → visit this website*; on Android Chrome: *Advanced → Proceed*). Browsers only
   allow the microphone on secure pages, and a home network cannot have a certificate that phones
   trust, so YTKTV makes its own.
3. Type a name, press **Start microphone**, and allow the microphone.
4. On the computer, open **Mixer** and choose **Phone: your name** as the input of a channel.

The page shows which channel the phone is on, how much sound is buffered and the network delay.
Keep the page open and the screen on while singing.

**What to expect.** The voice is sent uncompressed, and the phone's call processing (echo
cancellation, noise suppression, automatic gain) is switched off. Even so, a phone on Wi-Fi is
always a little behind a wired microphone, typically 40 to 120 ms depending on the phone and the
router. A phone that disconnects stays chosen on its channel and is back when it reconnects.

Phone microphones have not been tested on many phones yet. If yours does not connect, please
[open an issue](https://github.com/TonyD365/YTKTV/issues/new/choose) with the phone model and
browser.
