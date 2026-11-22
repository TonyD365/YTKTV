"""Finding desks on the local network by their ID, so a changed IP address does not matter.

Built on lanpair's discovery. What a desk announces is not trusted: a room only talks to
the desk whose sealed messages it can verify.
"""

from __future__ import annotations

from dataclasses import dataclass

from lanpair import PublicIdentity
from lanpair import discovery as lanpair_discovery

from ytktv.rooms.secure import APP


@dataclass
class FoundDesk:
    desk_id: str
    name: str
    address: str  # host:port


def browse(seconds: float = 2.0) -> list[FoundDesk]:
    """Every desk that answers on the local network within *seconds*."""
    return [
        FoundDesk(found.device_id, found.name, found.address)
        for found in lanpair_discovery.browse(seconds, app=APP)
    ]


def find(desk_id: str, seconds: float = 2.0) -> str | None:
    """Where the desk with *desk_id* is right now, as host:port."""
    found = lanpair_discovery.find(desk_id, seconds, app=APP)
    return found.address if found is not None else None


class Announcer:
    """The desk telling the network where it is."""

    def __init__(self, desk: PublicIdentity, name: str, ip: str, port: int) -> None:
        self._announcer = lanpair_discovery.Announcer(desk, name, port, addresses=[ip], app=APP)

    def close(self) -> None:
        self._announcer.close()
