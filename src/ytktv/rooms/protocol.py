"""The room's side of the handshake with the desk (no networking here, so it is testable)."""

from __future__ import annotations

import json
from typing import Any

from ytktv.rooms import crypto


class DeskImpostor(Exception):
    """A message that the paired desk did not sign."""


class RoomSession:
    def __init__(self, room_id: str, key: str, desk_key: str) -> None:
        self.room_id, self.key, self.desk_key = room_id, key, desk_key
        self.nonce = crypto.nonce()
        self.seq = 0

    def hello(self) -> str:
        return json.dumps({"room_id": self.room_id, "nonce": self.nonce})

    def open(self, raw: str) -> dict[str, Any]:
        """Check a message from the desk; raise DeskImpostor unless the desk signed it."""
        envelope = json.loads(raw)
        body = str(envelope.get("body", ""))
        data = f"{self.nonce}|{body}".encode()
        if not crypto.verify(self.desk_key, data, str(envelope.get("sig", ""))):
            raise DeskImpostor("bad signature")
        message: dict[str, Any] = json.loads(body)
        if int(message.get("seq", 0)) <= self.seq:
            raise DeskImpostor("replayed message")
        self.seq = int(message["seq"])
        return message

    def answer(self, challenge: dict[str, Any]) -> str:
        data = f"room|{self.room_id}|{challenge['nonce']}".encode()
        return json.dumps({"mac": crypto.mac(self.key, data)})
