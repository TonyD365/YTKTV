"""Binding a room to the staff terminal, and the rule for undoing it."""

from __future__ import annotations

import json
import ssl
import time
import urllib.request
from dataclasses import dataclass

from ytktv.config import Settings
from ytktv.rooms import crypto, secure

# A binding is permanent. Only after the desk has been unreachable this long may the
# room unbind itself, and even then someone has to press Unbind in the room's settings.
UNBIND_AFTER = 7 * 24 * 3600


@dataclass
class Pairing:
    desk_url: str
    room_id: str
    key: str  # this room's private lanpair identity (hex of its seed)
    name: str
    desk_id: str
    desk_key: str  # the desk's public lanpair identity (hex)

    @property
    def fingerprint(self) -> str:
        """Must match the security code the desk shows; otherwise it is not that desk."""
        return crypto.fingerprint(signing_key(self.desk_key))


def signing_key(desk_key: str) -> str:
    """The desk's Ed25519 key (the first half of its lanpair identity), as hex."""
    return desk_key[:64]


def is_bound(settings: Settings) -> bool:
    # A pairing from before 4.6 (a shared secret, not a lanpair identity) no longer counts:
    # the room has to be paired again.
    return bool(
        settings.desk_url
        and settings.room_id
        and len(settings.room_key) == 64
        and secure.valid_public(settings.desk_key)
    )


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
    seed = secure.new_seed()
    me = secure.public_hex(secure.identity(seed))
    body = json.dumps({"code": code.strip(), "name": name.strip(), "identity": me}).encode()
    req = urllib.request.Request(f"{url}/api/pair", body, {"Content-Type": "application/json"})
    context = tls_context() if url.startswith("https") else None
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:  # noqa: S310
        reply = json.loads(response.read())
    desk = secure.public(str(reply["desk_identity"]))
    if desk.device_id != reply["desk_id"]:
        raise ValueError("the desk's ID does not match its key")
    return Pairing(
        url, reply["room_id"], seed, reply["name"], reply["desk_id"], secure.public_hex(desk)
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
