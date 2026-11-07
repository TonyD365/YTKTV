# Contributing to YTKTV

Thanks for helping. Bug reports, ideas and pull requests are all welcome. Please follow the
[code of conduct](CODE_OF_CONDUCT.md); security problems go to [SECURITY.md](SECURITY.md).

## Reporting a problem

Open an [issue](https://github.com/TonyD365/YTKTV/issues/new/choose) and fill in the form. The
version, your system and, for a song that misbehaves, the YouTube link make a problem much
quicker to find.

Reports from hardware the project has not been tested on are especially useful: NVIDIA, AMD and
Intel graphics cards on Windows and Linux, and unusual audio interfaces.

## Setting up

You need Python 3.11 or newer.

```bash
git clone https://github.com/TonyD365/YTKTV.git
cd YTKTV
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m ytktv
```

The first start offers to install mpv if it is missing. Add the `separation` extra
(`pip install -e ".[dev,separation]"`) to work on vocal separation.

## Before you open a pull request

```bash
ruff check . && ruff format --check .
mypy src
pytest
```

CI runs the same checks on macOS, Windows and Linux, and compares the benchmarks with `main`;
a slowdown of more than 25% fails the pull request.

### The checks on a pull request

**Commands** (at the start of a comment on the pull request): `/retest` re-runs the checks that
failed or were cancelled (you or a maintainer); `/run packaging`, `/run installer`, `/run desk`
and `/run separation` run that part's heavier tests (maintainers); `/help` lists them.

A pull request that waits on its author (`Needs-Author-Action`) with no push or comment from
them for 14 days gets the `Stale` label and a reminder, and is closed after 14 more days. It
can always be reopened.

A bot keeps one comment on each pull request up to date: which checks passed or failed, what a
failure usually means, and what happens next. Besides the tests on three systems, the lint and
the benchmarks:

- **Security** audits the Python and npm dependencies and runs CodeQL on the changed code.
- **Labels** are added from the files you change. Some start heavier tests for that part:
  `installer` (real installs on macOS, Linux and Windows), `desk` (a live Desk and room),
  `separation` (the real model) and `packaging` (the whole release build with the built apps'
  self-tests). A maintainer can also add a label to run them.
- A pull request needs the maintainer's approval, and every check passing, before it is merged.
  The bot sums the checks up in one status, **YTKTV checks**; once the maintainer approves, it
  turns on auto-merge, so the pull request merges by itself when that status is green.
- The bot also keeps **status labels** up to date: `Checks-Running`, `Checks-Passed`,
  `Checks-Failed`, `Internal-Error` (a check was cancelled or timed out, usually not the
  change's fault), `Merge-Conflict` (bring `main` into your branch, resolve, push; nothing is
  merged until then), `Needs-Author-Action`, `Needs-Terms-Agreement`, `Needs-Review` and
  `Maintainer-Approved`. When the status changes it posts a new comment, so the newest status
  is always the latest comment.

A few conventions:

- Everything a user or a contributor reads is in English: the interface, comments, commit
  messages and pull requests.
- The core (`core/`, `audio/dsp.py`, `server/`, `youtube/parse.py`) does not import Qt, mpv or
  audio hardware, so it can be tested headless. Please keep it that way and add tests there.
- Tests must not need the network, a sound card or a visible window. Use the fake player and the helpers in `tests/helpers.py`.
- One topic per pull request, with a description of how you checked it.

The layout of the code is described in the [README](README.md#development).

## Contribution terms

On your first pull request the bot posts these terms as a comment. Reply with a comment that
says exactly

    I agree to the YTKTV contribution terms

and the check called **Contribution terms** turns green (it stays red until then). By replying
you agree that:

1. **License.** Your contribution is released under the [YTKTV License](LICENSE), like the rest
   of YTKTV: free to use, also in a business, but the software and anything based on it may not
   be sold.
2. **It is yours to give.** You wrote it, or you have the right to contribute it under that
   license. Code or assets from elsewhere are marked, with their source and license, and that
   license allows this.
3. **It may be changed or declined.** The maintainer may edit, rearrange or decline a
   contribution, and you are credited in the project's history (git), not paid.
4. **No warranty.** You give it as is, like the rest of YTKTV.
5. **Conduct.** You follow the [code of conduct](CODE_OF_CONDUCT.md).

The maintainer and the project's bots are not asked. Your answer is recorded (in an issue the
bot keeps), so once you have agreed, your later pull requests count as agreed too, until you
withdraw by replying `I do not agree to the YTKTV contribution terms`. A pull request whose
author has not agreed is labelled `Needs-Terms-Agreement`, and `Terms-Declined` after a no.
