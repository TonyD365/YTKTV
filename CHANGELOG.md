# Changelog

What changed in each release. The [releases page](https://github.com/TonyD365/YTKTV/releases)
has the installers and the full notes.

## 4.1.7

### 🔑 Clearer password requests on macOS
- **Installing with the one-line command** now asks for your Mac password right in the terminal, saying why (to put the app in /Applications), instead of a macOS window that only said "a script started by i".
- **Updating inside the app:** when an update needs your password, YTKTV and YTKTV Desk now say so first, and macOS's password window names the app ("a script started by YTKTV"). This applies from the next update on, since the update is run by the version you have.

### 🔧 Also
- The project's automation (pull request checks, labels, release steps) now works under one account, with an approved pull request merging itself once every check passes.
- Release builds fail fast instead of waiting up to 40 minutes when a self-test of the built apps stalls.

## 4.1.6

**🔒 Security update: install as soon as possible.** This release fixes several security problems in YTKTV and YTKTV Desk: open Settings → Updates and install it.

### 🔒 Security
- The signatures between rooms and the Desk, and the certificate for the phone microphone page, now use the `cryptography` library (the latest version on every system) instead of a library with a known weakness. Rooms that are already paired keep working.
- The phone page only talks to YTKTV itself, and the microphone link only opens an `https://` page.
- Pasted YouTube links are read in a way that stays fast whatever text is pasted.

### 🔧 Also
- Release notes now end with how to install, and which file to download.
- YTKTV Desk is not in winget for now (its submission waited a long time without being accepted); install it with the one-line installer.

## 4.1.5

### 🔒 Security update
- A security fix for updates on macOS. Please update soon: YTKTV and YTKTV Desk update themselves (Settings → Updates).

## 4.1.4

### 🔧 Fixes
- The terminal installer (`curl … install.sh | bash`) quit right after showing the list on macOS, without waiting for a key. It now gets the keys from the terminal and waits.
- The terminal installer is attached to each release as soon as it is built, so the one-line installs use the new one within minutes instead of after all the installers are built.

## 4.1.3

### 🖥 A new installer in the terminal
The one-line installs now open an interactive installer, drawn like a modern command-line app:

```bash
curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash        # macOS, Linux
```
```powershell
irm https://tonyd365.github.io/YTKTV/install.ps1 | iex               # Windows
```

- Tick **YTKTV, YTKTV Desk or both**. It shows what is already installed ("4.1.2 → 4.1.3", or up to date).
- What each app does and needs, what is about to happen, and the license to read and accept.
- Checks the disk space and closes a running copy first.
- A progress bar with speed and time left; if the network drops it tries again and goes on where it stopped. Every download is checked against the release's checksums.
- Offers to install mpv, and to open the app at the end.
- `--room`, `--desk` and `--yes` (PowerShell: `-Room`, `-Desk`, `-Yes`) skip the questions.

### 📄 Installer pages
- The macOS and Windows installers show a welcome page (what the app does, what it needs, where it goes, privacy), the license to accept, and a finish page with how to start.

### 🔧 Also
- Fixed: the one-line install with `--yes` always said the download was damaged.

## 4.1.2

### 🔑 Clearer password request on macOS
- When an update needs your password on macOS, the dialog now says which app is updating, to which version, and why: to replace the changed files of the app in /Applications, and nothing else.

### 🔧 Also
- First release with Windows patches: updating YTKTV or YTKTV Desk on Windows from 4.1.1 downloads only the changed files.

## 4.1.1

### 🔒 Lobby screen
- The lobby TV now shows only the rooms: free, in use (with the time left) and today's bookings. Tonight's best scores, singers and song titles are no longer shown, so what a room sings stays private.

### 🔧 Also
- Releases attach each Windows build's files, so Windows updates can come as small patches from the next release on.

## 4.1.0

### Smaller updates

Updates within the same major version now download only the files that changed, usually tens of MB instead of the whole installer. A new major version still comes as the full installer.

- macOS and Windows, for both YTKTV and YTKTV Desk. Linux AppImages still update whole.
- Before using a patch, the app checks it against the files you have. If anything does not match, or the patch fails, the old files are put back and the full installer is used instead.
- On macOS you are asked for your password, as with the installer, and YTKTV reopens by itself.
- On Windows the Apps list (and winget) shows the new version after a patch. Uninstalling now removes the whole install folder.
- The update message shows the download size.

This update from 4.0.0 is still the full installer, because 4.0.0 cannot apply patches. Patches start with the next release after 4.1.0.

## 4.0.0

### 🖥 YTKTV Desk: Server Mode
- **A server console instead of the front desk.** Settings → Staff Terminals → *Switch to Server Mode…* turns the main Desk's computer into the server: it shows rooms and staff terminals online, requests per minute, CPU, memory and database size, today's takings, and a live log you can filter and export. Staff work on the staff terminals.
- It stays in Server Mode across restarts until you leave it (with the Desk password, if one is set), keeps the computer awake, can start with the computer, and backs the records up with one button.

### 🎮 The Desk's GPU works for every room
- **Process songs for the rooms**: with a GPU on the Desk, it removes the vocals and writes the lyrics of the songs every room has queued. The rooms' own computers need no GPU, even a Raspberry Pi will do.
- Every room's current song comes first, then every room's next one. A song sung in two rooms is done once.
- When the Desk is off, busy, or cannot download a song, the room sends it the audio or does the song itself, as before.
- Server Mode shows a **Songs for rooms** card: queue, the song being worked on, the GPU and the cache.

### 🎤 Lyrics that match the video
- **With a GPU, every song's lyrics are written on your computer** by Whisper, from the singer separated from the band, so the timing matches this video. The lyrics found online are shown until then and help Whisper with the words.
- **Songs singing now or next are done in 30-second pieces**: the lyrics appear piece by piece within seconds, while the rest of the song is still being worked on.
- Without a GPU, lyrics come from online as before; Whisper writes only songs that have none.

### 🎚 Original and Instrumental line up
- The instrumental is lined up with the original to the sample after it is separated, so switching between them no longer sounds doubled.

### 🔧 Also
- Pull requests from forks get area labels too (GitHub restricts `pull_request_target` from December 2).
- Fixed a CI crash in the Server Mode tests and a flaky test on Windows.

### ✅ Works with older versions
- Rooms and Desks of any 3.x version keep working with 4.0. To have songs processed on the Desk, update **both** the Desk and the rooms to 4.0.
- Instrumentals already in the cache line up the next time they are separated. Lyrics written before stay until the song is written again.

## 3.2.1

### 🛎 YTKTV Desk
- **The 3.x look comes to the Desk**: the same night sky as the console behind see-through panels, and glossy room tiles in the usual status colours.
- **Fix**: the Maintenance / Back in Service button no longer shows a system emoji next to its icon.

### 📖 Docs
- The Desk screenshot in the README shows the new look.

### ✅ Works with older versions
Only how the Desk looks has changed: it works with rooms of any 3.x version, and nothing needs setting up again.

## 3.2.0

The TV and the phones now match the console's 3.0 look.

### 📺 MV screen
- **Between songs**, the TV shows the console's night sky, with the QR code in a glass panel with a glowing pink-to-cyan edge.
- The **Now Playing / Up Next** banner is a glossy pink-to-violet pill.

### 📱 Phone page
- The same **night sky** behind everything.
- **Tabs with icons**: search, queue, lists, remote and games, with the queue count on the mic.
- **Big glossy tiles** in the console's colours for playback, vocals, crowd sounds and moods.

### 📖 Docs
- The README tells why YTKTV was made.

### ✅ Works with older versions
Only how things look has changed: rooms, the Desk and phones of any 3.x version work together, and nothing needs setting up again.

## 3.1.0

### 🎤 YTKTV
- **Background videos.** Settings → Background Videos (off by default) plays music videos while nobody has chosen a song, like a KTV room before the first song. Play from your favorites and sung songs, or from one playlist. The first song anyone chooses takes over at once; background videos are not scored and not added to Sung.
- **Confetti for a great song.** A score of 90 or more, or the best of the night, bursts confetti over the MV behind the score card.

### 🛎 YTKTV Desk
- **Tonight's best on the lobby screen.** Rooms send their scores to the Desk, and the lobby screen shows the five best of the day with the singer and the song.
- A room's **Admin Settings** can turn background videos on or off.

### 🔧 Under the hood
- Pull requests run fewer macOS and Windows tests, so checks finish sooner; main still tests everything.
- The benchmark check measures again before calling something a slowdown.

### ✅ Works with older versions
- A 3.1 room works with an older Desk, and an older room works with Desk 3.1; older rooms just do not send scores to the lobby board.
- The Desk's records are upgraded in place the first time it starts; nothing is lost.
- Background videos stay off until you turn them on.

## 3.0.0

YTKTV 3.0 has a new look: our own icons everywhere and a console that feels like a KTV touch screen.

### 🎤 YTKTV
- **Our own icons.** 71 icons drawn for YTKTV replace the system emoji on the console, the phone page, the games and the MV screen. Reactions fly across the TV as coloured icons.
- **A KTV-style console.** A night-sky background, glossy tiles with the icon and name in the middle, and an on-screen **Keyboard** on the Search page for touch screens (initials still work: `yldb`).
- **Mood scenes.** Party → Mood, or the phone page: Birthday, Romantic, Party or Chill keeps the TV's edge lights and smart lights in that scene's colours, with a cheer or an air horn to start.
- **Menu pictures.** Items on the staff terminal's menu show their picture when guests order from the console or a phone.

### 🛎 YTKTV Desk
- **Lobby screen.** Settings → Lobby Screen puts a board on a TV outside the desk: free rooms, when busy rooms come free, and today's bookings. It goes full screen on the chosen display, like a room's MV screen.
- **Service calls that wait too long** turn bright red, show how long they have waited and beep again (Settings → Service Calls, 3 minutes by default). The shift report counts them.
- **Pictures for menu items**: Settings → Menu and Prices → Picture.

### 📖 Docs
- The user guide has a new **More features** page, and the changelog is complete again.

### ✅ Works with older versions
Nothing to redo when you update:
- A 3.0 room works with an older YTKTV Desk, and an older room works with Desk 3.0. Older rooms just do not show menu pictures.
- The Desk's records are upgraded in place the first time it starts; rooms, members, bookings and history are all kept.
- Settings, playlists, favorites and downloads stay as they were.

## 2.5.1

### Fixes
- The voice effect box on each mixer channel is no longer cut off ("Voice: C" now reads "Voice: Off").

### Docs
- The README describes the newer features: service charge and tax at the Desk till, Admin Settings from the Desk, low-power mode and problem reports.
- New screenshots from the current version.

## 2.5.0

### 🎤 YTKTV
- **TV without a cable**: use the TV as a wireless second screen (AirPlay on a Mac, Miracast with Win + K on Windows). The MV moves there by itself, lyrics and effects included, and a **picture delay** setting keeps the sound in step with a wireless picture. Settings → TV Without a Cable.
- **Spotify and Apple Music playlists**: paste a public playlist link (Playlists → Import Playlist), or a list of songs one per line; each song is found on YouTube, karaoke versions first.
- **Voice effects**: Chipmunk, Deep or Robot voice on any microphone, from its channel strip in the Mixer.
- **Kids mode**: for a children's room, songs not meant for children are left out and cannot be chosen, and the volume has a ceiling.

### 🛎 YTKTV Desk
- **Service charge and tax** on bills and receipts (Settings → Menu and prices), added after discounts.
- Kids mode and the wireless TV's picture delay can be set per room in **⚙ Admin Settings**.

### 🔧 Fixes
- Number boxes use the dark theme everywhere.

## 2.4.1

### What's fixed in 2.4.1

- **Vocal separation and AI lyrics work again after updating (macOS, Apple Silicon).** YTKTV keeps a copy of ffmpeg in its data folder; an update overwrote it in place, and macOS then stopped that copy from running, so song audio could not be downloaded. The copy is now replaced as a new file, checked at start, and made again (or the bundled one used) if it will not run.
- **No stall a few seconds after a song starts.** Background downloads (vocal separation, AI lyrics, the next songs) now wait while a song that has just started buffers, and playback starts once a little is buffered.

## 2.4.0

### 🎤 YTKTV
- **AI lyrics**: a song with no lyrics anywhere (no subtitles, nothing on LRCLIB) gets them written by Whisper, with line and word timing, kept for next time. Settings → AI Lyrics, a one-time download: the Apple GPU on Apple Silicon, CUDA on NVIDIA cards, the CPU otherwise.
- **Low-power mode** for a Raspberry Pi or an old computer: 720p video and no light effects. Turned on by itself on the first start of such a computer; Settings → MV Screen.
- **Report a Bug / Suggest a Feature** in Settings → Help. After an unexpected error YTKTV asks whether to report it, and only then opens a GitHub issue with the details filled in for you to check. Nothing is sent automatically.

### 🛎 YTKTV Desk
- **Admin Settings**: a room bound to a staff terminal now shows only the guests' settings (text size, phone remote, keys, help, unbinding). Video, sound output, vocal separation, AI lyrics, local songs, smart lights, low-power mode and updates are set on the staff terminal: select the room, then **⚙ Admin Settings**. Changes travel as signed, numbered messages and the room accepts only those settings, each checked.
- **Pairing codes can no longer be guessed**: five wrong codes from one address lock it out for five minutes; twenty in all throw away every open code.

### 🔧 Under the hood
- yt-dlp is checked for new versions every day, so a YouTube change is followed quickly; other dependencies were updated too.
- Every page of YTKTV and YTKTV Desk is checked for white boxes on the dark theme in CI, with screenshots kept.
- Every build now includes the uv installer, so macOS can download the AI lyrics runtime.

## 2.3.1

- **Smart lights**: WLED strips or Philips Hue lights change colour with the music, like the TV's edge lights. Settings → Smart Lights picks the kind and address, pairs a Hue bridge (press its button first) and has a Test button.
- **Phone order menu by category**: the phone's service menu is grouped under category headings, and the Drinks/Snacks call buttons hide while there is a menu.
- **Local folders from the staff terminal**: a room bound to YTKTV Desk gets its local song folders from there (Room settings → Local Folders…, paths on the room's computer); the room's Local Songs card becomes read-only.
- Lists use the dark theme everywhere (the folder list was a white box).
- **Installing explained step by step** in the README and on the website.

## 2.3.0

### 🎤 Singing
- **Local songs**: add folders of video files (MP4, MKV and more) in Settings → Local Songs. They show first in Search and on a new Local page. Karaoke MKVs with two audio tracks switch to the instrumental at once (no AI needed), and an `.lrc` file next to a video gives its lyrics.
- **King of Singers** and **Birthday** in Games: a knockout tournament decided by the score cards, and a birthday celebration with the song up next. Fourteen games now, on the console and phones.
- **Keyboard and remotes**: Space, N, R, V, the arrows and media keys play, skip, switch to the instrumental and change volume and key. USB remotes work as they are; a TV remote works through HDMI-CEC on a Raspberry Pi.
- **Large text**: Settings → Text Size makes the console's text 25% or 50% bigger.
- **Save Diagnostics** (Settings → Help): one zip with the recent logs, version and settings (keys and passwords left out) for a bug report.
- The service menu shows categories and big − / + buttons, and hides the Drinks/Snacks calls when there is a menu.

### 🛎 YTKTV Desk
- **Staff terminal on a phone**: open the Desk's `/staff` page, pair with a code, and handle calls, orders, opening, extending and checking out rooms.
- **Packages and coupons**: bundles such as 3 hours + a beer tower at one price, coupon codes for a percent or an amount off, and a members' birthday discount.
- **Insights**: takings, busy hours and weekdays, top songs, best-selling items and rooms for the last 7, 30 or 90 days.
- **Local songs only**: a room can be limited to the video files on its own computer.

### 📦 Installing
- **Windows**: `winget install TonyD365.YTKTV` (YTKTV Desk: `winget install TonyD365.YTKTVDesk`, once it is accepted). No SmartScreen prompt; `winget upgrade` updates it. Silent installs no longer start the app.
- **macOS and Linux**: `curl -fsSL https://tonyd365.github.io/YTKTV/install.sh | bash` (add `-s -- --desk` for YTKTV Desk). No quarantine warning, no `xattr`.

If you download the macOS package in a browser instead, run `xattr -d com.apple.quarantine ~/Downloads/YTKTV-2.3.0-macos-universal.pkg` before opening it. On Windows, a browser download may need **More info → Run anyway**.

## 2.2.0

### 🛎 YTKTV Desk: several staff terminals
- **Staff terminals**: other computers running YTKTV Desk pair with the main Desk (a one-time code and four pictures, like rooms) and work on the same rooms, bookings, members and records. A terminal keeps nothing of its own; if the main Desk is unreachable it says so and reconnects by itself, even after the main Desk's IP address changes.
- **📜 Log**: every change on the main Desk or a terminal, by day and machine ("Bar: Closed Kids, $60.00 by Card"). Passwords are never written into it.
- **Records by day, week or month**, with a takings chart and **Export CSV** that Excel opens (names in any language included).
- **Stock alerts**: a product running low shows in the service bar ("📦 Cola: 2 left"); set the number in Settings → Shop.
- **Settings → Updates**: the version, automatic checks on or off, and Check Now.
- The front desk is now called the **Staff Terminal** everywhere; what guests read says "the staff".
- The Desk's database now has versioned migrations and keeps a backup copy before it changes an existing file.

### 🎤 Singing
- **Downloads**: press ⬇ on any song, or Download All Favorites, to keep the video, lyrics and instrumental on the computer and sing without internet. A Downloads page lists them with their size.
- **Duet mode** (Party tab): the TV's lyrics turn blue for one singer, pink for the other and gold for both, from the 男/女/合 (or M/F) marks in the lyrics, or verse by verse when there are none.
- **More lyrics**: a video with no subtitles at all now gets synced lyrics from [LRCLIB](https://lrclib.net) when a recording of the same length is found.

## 2.1.1

### 💻 AI vocal separation on Windows on ARM
Windows on ARM computers (Snapdragon X and others) now get **Original / Instrumental** switching too. The separation runtime is the x64 one, run through Windows' built-in x64 emulation on the CPU; it is downloaded on first run (about 500 MB), like on other Windows computers. YTKTV also downloads an **ARM64 build of ffmpeg** there, so audio is not emulated as well.

Expect a few minutes per song: it is prepared in the background while earlier songs in the queue play.

## 2.1.0

### 🎤 Finding and singing
- **Pinyin initials**: type the first letters of a song's pinyin and it is suggested at once, like on a KTV machine (`yldb` → 月亮代表我的心, `hktk` → 海闊天空), on the console and phones.
- **Artists by language and type**: Mandarin, Cantonese, English, Japanese, Korean; male, female or group.
- **PK battle** (Party tab): two microphones sing the same song, two live score bars race on the TV, and the score card names the winner.
- **Glow sticks**: on the phone remote, the whole screen lights up in the TV's edge-light colours.

### 🎲 Party games with their own screens
The Games page is a lobby of twelve games, and each one opens its own screen with how to play, a big stage, its own buttons and an animation, on the console and on phones (new GAMES tab): dice, who sings next, truth or dare, number bomb, liar's dice (your dice only on your phone), random song, challenge cards, draw lots, high or low, sevens, countdown and a coin. Phones play under the name you typed.

### 🛎 YTKTV Desk
- **The till**: members (by phone number) save a set percent and earn points; discounts; drop the small change; pay by cash, card, WeChat Pay, Alipay or a member's stored balance. The shift report adds up takings by payment.
- **Members** tab: stored balance top-ups and points.
- **Receipts**: 58 mm or 80 mm receipts on any installed printer, by hand or at every check-out.
- **Updates itself** like YTKTV, and installs on macOS from one universal package.
- Fixes in the menu editor: readable cell editing, a labelled On menu switch, prices up to 99,999,999, and scrolling no longer changes values.
- A full [YTKTV Desk guide](https://github.com/TonyD365/YTKTV/blob/main/docs/guide/front-desk.md) (also in the wiki).

### 💻 ARM
New installers for **Windows on ARM** and **Linux ARM** (64-bit, e.g. Raspberry Pi 4/5), for YTKTV and YTKTV Desk.

### 🐞 Fixed
- The updater could pick YTKTV Desk's installer for YTKTV, or the other way round, because their file names end the same way.

## 2.0.0

### 🛎 YTKTV Desk: run a whole KTV with rooms
A new front-desk app manages several YTKTV machines on your network, like a real KTV: the adults in one room, the kids in another.

- **Rooms bind to the desk** with a one-time code and a four-picture security code. A binding is permanent: a room can only unbind itself after the desk has been offline for 7 days. Rooms find the desk by its ID, so a changed IP address does not matter, and they obey only messages the desk has signed.
- **Open, extend and close rooms** for 1–3 hours or without a limit. A closed room shows "This room is closed" and its TV goes black. Open rooms show the time left; when time is up, the song finishes and the room closes.
- **Service and orders**: rooms call the desk or order from its menu, from the console or a phone. The desk beeps and lists the calls.
- **Billing**: price per hour (per room if you like), a minimum spend, and a choice of how open-ended rooms are charged. The bill prints or saves as a PDF.
- **Remote control and broadcasts**: skip, pause, volume, lock a room, or send a message to every room.
- **Bookings** with a calendar and timeline, **records** of every session with its songs, a **shift report**, **room types**, **cleaning and maintenance** states, **change room**, **stock**, and an optional **desk password**.
- A classic front-desk layout and its own bell icon.

Install **YTKTV Desk** on one computer (`YTKTV-Desk-2.0.0-…` below), then in each room open **Settings → Front Desk**, press **Find Desks** and enter the code the desk shows. The YTKTV installers already include everything a room needs.

### 🎲 More party games
Number bomb, liar's dice (each player sees their own dice on their phone), random song, challenge cards, draw lots, high or low, the sevens counting game, a 10-second countdown and a coin flip.

## 1.7.0

- **A new console that looks like a real KTV screen.** It opens on a home page: what's playing and up next on the left, big coloured tiles for every feature on the right, and the menu across the top.
- **Volume keys with a pop-up level display.** The sliders became − / + keys. Each press shows a volume display on the console and on the MV screen, and so do changes made from a phone.
- **A Party tab.** Danmaku, eight emoji reactions that float up the MV screen (phones can send them too) and crowd sounds.
- **Party games.** Roll the dice, pick who sings next, truth or dare. The result shows big on the MV screen. Play from the Games tab or from a phone.
- New screenshots in the README and on the website.

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
