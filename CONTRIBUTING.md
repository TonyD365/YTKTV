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

A few conventions:

- Everything a user or a contributor reads is in English: the interface, comments, commit
  messages and pull requests.
- The core (`core/`, `audio/dsp.py`, `server/`, `youtube/parse.py`) does not import Qt, mpv or
  audio hardware, so it can be tested headless. Please keep it that way and add tests there.
- Tests must not need the network, a sound card or a visible window. Use the fake player and the helpers in `tests/helpers.py`.
- One topic per pull request, with a description of how you checked it.

The layout of the code is described in the [README](README.md#development).

## License

By contributing you agree that your work is released under the [YTKTV License](LICENSE):
free to use, also in a business, but the software and anything based on it may not be sold.
