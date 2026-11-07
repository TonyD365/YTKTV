# Security

**Looking for security holes in YTKTV is welcome.** Reports are answered, fixed and credited.

## Reporting a problem

**Please do not open a public issue for a security problem.** Report it privately instead:

- on GitHub, open the repository's **Security** tab and choose **Report a vulnerability**, or
- if that is not available, write to the maintainer through the contact on
  [TonyD365's GitHub profile](https://github.com/TonyD365).

Say what the problem is, how to reproduce it, and which version and system you used. You will
get an answer within a week. Please give a reasonable time to fix it before telling anyone else.

## What happens after you report

1. You get an answer within a week, saying whether it is a vulnerability and how serious it is.
2. The fix is made in a private fork of the repository, where you are welcome to check it.
3. It ships as an update; YTKTV and YTKTV Desk update themselves, so most installs get it soon.
4. A few days later a security advisory is published here, with a CVE number when it is
   serious, and **you are credited in it** (unless you would rather not be).

Please keep it private until the advisory is out.

## What is in scope

The current release (see [releases](https://github.com/TonyD365/YTKTV/releases/latest)) and
the `main` branch. Older versions are not fixed; updating is the remedy.

## Things to know before reporting

Some behaviour is by design for a karaoke room on a home network, and is documented:

- **The phone page has no password.** Anyone on the same network can queue songs, skip and change
  the sound. Run YTKTV on a network you trust. A room PIN is on the roadmap.
- **The phone-microphone page uses a self-signed certificate**, made on the computer the first
  time it is needed, so browsers warn about it once.
- **Downloads are checked.** Updates are verified against the `SHA256SUMS` published with each
  release before they are installed. mpv is not distributed by YTKTV; it is installed from
  Homebrew, the Windows build linked from mpv.io, or the Linux package manager.
- **The installers are not code-signed yet**, so macOS and Windows warn before the first start.

Reports that show a way around these, or anything else that lets someone outside the room
reach the computer, are very welcome.
