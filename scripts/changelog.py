"""Add releases that are missing from CHANGELOG.md, from their notes on GitHub.

    python scripts/changelog.py            # every release newer than the top of the changelog
    python scripts/changelog.py 2.6.0 notes.md   # a release that is not published yet

Only the "What's new" part of the notes is kept; install and download sections are left out.
Needs the GitHub CLI (gh) for the first form.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
# Sections of the release notes that are about installing, not about what changed
SKIP = (
    "## install",
    "## download",
    "## vocal separation",
    "## what's changed",
    "## full changelog",
)


def version(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.lstrip("v").split("."))


def whats_new(body: str) -> str:
    """The notes up to the first section about installing; their headings one level down."""
    kept: list[str] = []
    for line in body.replace("\r\n", "\n").splitlines():
        if line.startswith("## "):
            if line.lower().startswith("## what's new"):
                continue
            if line.lower().startswith(SKIP):
                break
            line = "#" + line
        kept.append(line)
    return "\n".join(kept).strip()


def insert(entries: list[tuple[str, str]]) -> None:
    """Put the entries (newest first) above the first release in the changelog."""
    text = CHANGELOG.read_text(encoding="utf-8")
    at = text.index("\n## ") + 1
    block = "".join(f"## {name}\n\n{notes}\n\n" for name, notes in entries)
    CHANGELOG.write_text(text[:at] + block + text[at:], encoding="utf-8")


def published() -> list[tuple[str, str]]:
    out = subprocess.run(
        ["gh", "release", "list", "--limit", "100", "--json", "tagName,isPrerelease"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tags = [r["tagName"] for r in json.loads(out) if not r["isPrerelease"]]
    top = re.search(r"^## (\d+\.\d+\.\d+)", CHANGELOG.read_text(encoding="utf-8"), re.M)
    newest = version(top.group(1)) if top else (0,)
    entries = []
    for tag in sorted((t for t in tags if version(t) > newest), key=version, reverse=True):
        body = subprocess.run(
            ["gh", "release", "view", tag, "--json", "body", "--jq", ".body"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        entries.append((tag.lstrip("v"), whats_new(body)))
    return entries


def main() -> None:
    if len(sys.argv) == 3:
        entries = [(sys.argv[1].lstrip("v"), whats_new(Path(sys.argv[2]).read_text("utf-8")))]
    else:
        entries = published()
    if entries:
        insert(entries)
    print("added", ", ".join(name for name, _ in entries) or "nothing")


if __name__ == "__main__":
    main()
