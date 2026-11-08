"""Write the user guide (docs/guide) as GitHub wiki pages.

    python scripts/sync_wiki.py <wiki checkout>

docs/guide is the source (changed through pull requests); the wiki is a copy for reading on
GitHub. Each guide file becomes a page, links between them become wiki links, and links that
only work inside the repository become full GitHub links. Pages no longer in the guide are
removed. Run by .github/workflows/wiki.yml after the guide changes on main.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = "https://github.com/TonyD365/YTKTV"
GUIDE = Path(__file__).resolve().parent.parent / "docs" / "guide"

# Guide file -> wiki page, in sidebar order (README is the wiki's Home).
PAGES = {
    "README.md": ("Home", None),
    "getting-started.md": ("Getting-started", "Getting started"),
    "mixer.md": ("The-mixing-console", "The mixing console"),
    "phones.md": ("Phones", "Phones"),
    "front-desk.md": ("YTKTV-Desk", "YTKTV Desk"),
    "more-features.md": ("More-features", "More features"),
    "troubleshooting.md": ("Troubleshooting", "Troubleshooting"),
}

SIDEBAR_TAIL = """
**Elsewhere**

- [Website](https://tonyd365.github.io/YTKTV/)
- [Download](https://github.com/TonyD365/YTKTV/releases/latest)
- [FAQ](https://github.com/TonyD365/YTKTV#faq)
- [Discussions](https://github.com/TonyD365/YTKTV/discussions)
- [Report a problem](https://github.com/TonyD365/YTKTV/issues/new/choose)
- [中文说明](https://github.com/TonyD365/YTKTV/blob/main/README.zh-CN.md)
"""

FOOTER = (
    "[Website](https://tonyd365.github.io/YTKTV/) · [GitHub](https://github.com/TonyD365/YTKTV)"
    " · [Discussions](https://github.com/TonyD365/YTKTV/discussions)"
    " · [Report a problem](https://github.com/TonyD365/YTKTV/issues/new/choose)\n"
)

NOTE = (
    "\n---\n\n<sub>This page is copied from"
    " [`docs/guide`](https://github.com/TonyD365/YTKTV/tree/main/docs/guide) in the repository."
    " To change it, edit the file there (a pull request is welcome); edits made only here would"
    " be overwritten by the next copy.</sub>\n"
)

_LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+)\)")


def wiki_link(target: str) -> str:
    """A link from a guide file, as it should read on the wiki."""
    path, _, anchor = target.partition("#")
    suffix = f"#{anchor}" if anchor else ""
    name = Path(path).name
    if path == name and name in PAGES:
        return PAGES[name][0] + suffix
    # Anything else in the repository: a full link to it on main.
    resolved = (Path("docs/guide") / path).as_posix()
    parts: list[str] = []
    for part in resolved.split("/"):
        if part == "..":
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return f"{REPO}/blob/main/{'/'.join(parts)}{suffix}"


def convert(text: str) -> str:
    return _LINK.sub(lambda m: f"]({wiki_link(m.group(1))})", text).rstrip("\n") + "\n" + NOTE


def main(wiki: Path) -> None:
    wanted = {page for page, _ in PAGES.values()} | {"_Sidebar", "_Footer"}
    for old in wiki.glob("*.md"):
        if old.stem not in wanted:
            old.unlink()
    for source, (page, _) in PAGES.items():
        text = (GUIDE / source).read_text(encoding="utf-8")
        (wiki / f"{page}.md").write_text(convert(text), encoding="utf-8")
    links = [f"- [{title}]({page})" for page, title in PAGES.values() if title]
    sidebar = "**[YTKTV wiki](Home)**\n\n" + "\n".join(links) + "\n" + SIDEBAR_TAIL
    (wiki / "_Sidebar.md").write_text(sidebar, encoding="utf-8")
    (wiki / "_Footer.md").write_text(FOOTER, encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
