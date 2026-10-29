"""Binding a room to the front desk, and the rule for undoing it."""

from __future__ import annotations

import json
import ssl
import time
import urllib.request
from dataclasses import dataclass

from ytktv.config import Settings
from ytktv.rooms import crypto

# A binding is permanent. Only after the desk has been unreachable this long may the
# room unbind itself, and even then someone has to press Unbind in the room's settings.
UNBIND_AFTER = 7 * 24 * 3600


@dataclass
class Pairing:
    desk_url: str
    room_id: str
    key: str
    name: str
    desk_id: str
    desk_key: str

    @property
    def fingerprint(self) -> str:
        """Must match the security code the desk shows; otherwise it is not that desk."""
        return crypto.fingerprint(self.desk_key)


def is_bound(settings: Settings) -> bool:
    return bool(settings.desk_url and settings.room_id and settings.room_key and settings.desk_key)


def can_unbind(settings: Settings, now: float | None = None) -> bool:
    if not is_bound(settings):
        return False
    now = time.time() if now is None else now
    return now - settings.desk_last_seen >= UNBIND_AFTER


def tls_context() -> ssl.SSLContext:
    # The desk's certificate is self-signed. TLS keeps the traffic private; who the desk
    # is gets checked by its signing key, which the room pins when it pairs.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def desk_url(address: str) -> str:
    address = address.strip().rstrip("/")
    return address if "://" in address else f"https://{address}"


def request(address: str, code: str, name: str, timeout: float = 5.0) -> Pairing:
    """Ask the desk for a pairing. Nothing is saved until the room confirms it."""
    url = desk_url(address)
    body = json.dumps({"code": code.strip(), "name": name.strip()}).encode()
    req = urllib.request.Request(f"{url}/api/pair", body, {"Content-Type": "application/json"})
    context = tls_context() if url.startswith("https") else None
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:  # noqa: S310
        reply = json.loads(response.read())
    if crypto.desk_id(reply["desk_key"]) != reply["desk_id"]:
        raise ValueError("the desk's ID does not match its key")
    return Pairing(
        url, reply["room_id"], reply["key"], reply["name"], reply["desk_id"], reply["desk_key"]
    )


def apply(settings: Settings, pairing: Pairing) -> None:
    settings.desk_url = pairing.desk_url
    settings.room_id = pairing.room_id
    settings.room_key = pairing.key
    settings.room_name = pairing.name
    settings.desk_id = pairing.desk_id
    settings.desk_key = pairing.desk_key
    settings.desk_last_seen = time.time()


def clear(settings: Settings) -> None:
    settings.desk_url = settings.room_id = settings.room_key = settings.room_name = ""
    settings.desk_id = settings.desk_key = ""
    settings.desk_last_seen = 0.0
