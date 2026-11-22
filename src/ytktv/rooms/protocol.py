"""The room's side of the conversation with the desk (no networking here, so it is testable).

The room says who it is in a plain ``hello``, then proves it with a sealed ``auth`` that
carries its session key. The desk answers with a sealed ``ack`` carrying the desk's
session key, or with a sealed ``unbind`` when it no longer knows the room.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lanpair import EnvelopeError, Sealer

from ytktv.rooms import secure


class DeskImpostor(Exception):
    """A message that the paired desk did not seal."""


class RoomSession:
    def __init__(self, room_id: str, seed_hex: str, desk_hex: str, seq_file: Path) -> None:
        self.room_id = room_id
        self.me = secure.identity(seed_hex)
        self.desk = secure.public(desk_hex)
        self.sealer = Sealer(self.me)
        self.opener = secure.opener(self.me, seq_file)
        self.opener.add_peer(self.desk)
        self.session = secure.session_key(self.opener)
        self.desk_session: bytes | None = None

    def hello(self) -> str:
        return json.dumps({"room_id": self.room_id, "identity": secure.public_hex(self.me)})

    def auth(self) -> str:
        return self.seal({"type": "auth", "room": self.room_id, "session": self.session.hex()})

    def seal(self, message: dict[str, Any]) -> str:
        """A message for the desk, to its session key once it has sent one."""
        return self.sealer.seal(self.desk, message, box_key=self.desk_session).decode()

    def open(self, raw: str | bytes) -> dict[str, Any]:
        """Check a message from the desk; raise DeskImpostor unless the desk sealed it."""
        try:
            _sender, message = self.opener.open(raw.encode() if isinstance(raw, str) else raw)
        except EnvelopeError as exc:
            raise DeskImpostor(str(exc)) from exc
        if not isinstance(message, dict):
            raise DeskImpostor("not a message")
        # Sealed for another room (the room is named in every message): not ours.
        if message.get("room") != self.room_id:
            raise DeskImpostor("message for another room")
        if message.get("type") == "ack":
            try:
                self.desk_session = bytes.fromhex(str(message.get("session", "")))
            except ValueError as exc:
                raise DeskImpostor("bad session key") from exc
            if len(self.desk_session) != 32:
                raise DeskImpostor("bad session key")
        return message
