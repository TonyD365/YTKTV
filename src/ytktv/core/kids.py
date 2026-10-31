"""Kids mode: songs for children only, and the volume kept down."""

from __future__ import annotations

import re

from ytktv.core.models import Song

# Words in a title or channel that mark a video as not for children. Kept short and
# plain on purpose: it catches what YouTube marks in titles, it is not a guarantee.
_NOT_FOR_KIDS = re.compile(
    r"\b(explicit|uncensored|nsfw|18\+|18 ?禁|adults? only|sexy|sex|porn|drunk|drugs?|"
    r"kill|murder|blood|gore|horror|fuck|shit|bitch)\b|限制级|成人|色情|血腥|恐怖",
    re.IGNORECASE,
)
DEFAULT_MAX_VOLUME = 70


def suitable(song: Song) -> bool:
    return not _NOT_FOR_KIDS.search(f"{song.title} {song.channel}")
