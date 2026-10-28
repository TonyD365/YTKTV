"""Finding desks on the local network by their ID, so a changed IP address does not matter."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

SERVICE = "_ytktv-desk._tcp.local."


@dataclass
class FoundDesk:
    desk_id: str
    name: str
    address: str  # host:port


def browse(seconds: float = 2.0) -> list[FoundDesk]:
    """Every desk that answers on the local network within *seconds*."""
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

    found: dict[str, FoundDesk] = {}

    class Listener(ServiceListener):
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name, timeout=1500)
            if info is None or not info.addresses:
                return
            props = {k.decode(): (v or b"").decode() for k, v in info.properties.items()}
            host = socket.inet_ntoa(info.addresses[0])
            desk_id = props.get("id", "")
            found[desk_id] = FoundDesk(desk_id, props.get("name", name), f"{host}:{info.port}")

        update_service = add_service

        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE, Listener())
        time.sleep(seconds)
    finally:
        zc.close()
    return list(found.values())


def find(desk_id: str, seconds: float = 2.0) -> str | None:
    """Where the desk with *desk_id* is right now, as host:port."""
    for desk in browse(seconds):
        if desk.desk_id == desk_id:
            return desk.address
    return None


class Announcer:
    """The desk telling the network where it is."""

    def __init__(self, desk_id: str, name: str, ip: str, port: int) -> None:
        from zeroconf import ServiceInfo, Zeroconf

        self._zc = Zeroconf()
        self._info = ServiceInfo(
            SERVICE,
            f"YTKTV Desk {desk_id[:6]}.{SERVICE}",
            addresses=[socket.inet_aton(ip)],
            port=port,
            properties={"id": desk_id, "name": name},
        )
        self._zc.register_service(self._info)

    def close(self) -> None:
        self._zc.unregister_service(self._info)
        self._zc.close()
