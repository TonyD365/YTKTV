# Security

## Reporting a problem

**Please do not open a public issue for a security problem.** Report it privately instead:

- on GitHub, open the repository's **Security** tab and choose **Report a vulnerability**, or
- if that is not available, write to the maintainer through the contact on
  [TonyD365's GitHub profile](https://github.com/TonyD365).

Say what the problem is, how to reproduce it, and which version and system you used. You will
get an answer within a week. Please give a reasonable time to fix it before telling anyone else.

## What is in scope

The current release (see [releases](https://github.com/TonyD365/YTKTV/releases/latest)) and
the `main` branch. Older versions are not fixed; updating is the remedy.

## Things to know before reporting

Some behaviour is by design for a karaoke room on a home network, and is documented:

- **The phone page has no password.** Anyone on the same network can queue songs, skip and change
  the sound. Run YTKTV on a network you trust. A room PIN is on the roadmap.
- **The phone-microphone page uses a self-signed certificate**, made on the computer the first
  time it is needed, so browsers warn about it once.
- **Downloads are checked.** Updates and the separate mpv download are verified against the
  `SHA256SUMS` published with each release before they are used.
- **The installers are not code-signed yet**, so macOS and Windows warn before the first start.

Reports that show a way around these, or anything else that lets someone outside the room
reach the computer, are very welcome.
