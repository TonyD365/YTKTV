"""A staff terminal: this Desk works on the main Desk's records instead of its own.

Every call goes to the main Desk over one kept-alive HTTPS connection. Each new connection
starts by checking that the main Desk signs this connection's certificate with the key that
was pinned when the terminal paired, so a machine in between cannot pretend to be it.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ytktv.desk.staff import STORE_METHODS, decode, encode, proof
from ytktv.rooms import crypto, discovery
from ytktv.rooms.binding import desk_url, tls_context

log = logging.getLogger(__name__)
TIMEOUT = 3.0  # seconds; the main Desk is on the same network
RETRY_AFTER = 3.0  # seconds between attempts to reach a main Desk that went offline


class DeskOffline(ConnectionError):
    """The main Desk cannot be reached right now."""


class NotPaired(PermissionError):
    """The main Desk no longer accepts this terminal."""


@dataclass
class TerminalConfig:
    address: str  # https://host:port of the main Desk
    desk_id: str
    desk_key: str
    token: str
    name: str  # this terminal's name in the log
    main_name: str = ""

    @property
    def fingerprint(self) -> str:
        return crypto.fingerprint(self.desk_key)


def config_path() -> Path:
    from ytktv.config import data_dir

    return data_dir() / "desk-terminal.json"


def load_config(path: Path | None = None) -> TerminalConfig | None:
    try:
        return TerminalConfig(**json.loads((path or config_path()).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def save_config(config: TerminalConfig, path: Path | None = None) -> None:
    (path or config_path()).write_text(json.dumps(asdict(config)), encoding="utf-8")


def forget_config(path: Path | None = None) -> None:
    (path or config_path()).unlink(missing_ok=True)


def _connect(address: str) -> tuple[http.client.HTTPSConnection, str]:
    """An open connection to *address* and the SHA-256 of the certificate it presented."""
    parts = urlsplit(desk_url(address))
    connection = http.client.HTTPSConnection(
        parts.hostname or "", parts.port or 443, timeout=TIMEOUT, context=tls_context()
    )
    connection.connect()
    sock: Any = connection.sock
    der = sock.getpeercert(binary_form=True) or b""
    return connection, hashlib.sha256(der).hexdigest()


def _post(connection: http.client.HTTPConnection, path: str, body: Any, token: str = "") -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection.request("POST", path, json.dumps(body), headers)
    response = connection.getresponse()
    data = response.read()
    if response.status == 401:
        raise NotPaired("The main Desk no longer accepts this terminal")
    if response.status == 403:
        message = json.loads(data).get("detail", "refused") if data else "refused"
        raise NotPaired(str(message))
    if response.status != 200:
        raise DeskOffline(f"the main Desk answered {response.status}")
    return json.loads(data)


def _check(reply: dict[str, Any], nonce: str, cert_hash: str, desk_key: str | None) -> None:
    """Raise unless *reply* is signed by the main Desk for this connection."""
    key = desk_key or reply["desk_key"]
    if crypto.desk_id(reply["desk_key"]) != reply["desk_id"] or reply["desk_key"] != key:
        raise ValueError("This is not the Desk this terminal was paired with")
    if not crypto.verify(key, proof(nonce, cert_hash), reply["signature"]):
        raise ValueError("The Desk's signature does not match this connection")


def pair(address: str, code: str, name: str) -> TerminalConfig:
    """Pair with the Desk at *address*. Show config.fingerprint to compare before saving."""
    connection, cert_hash = _connect(address)
    try:
        nonce = crypto.nonce()
        reply = _post(
            connection, "/api/staff/pair", {"code": code.strip(), "name": name, "nonce": nonce}
        )
    finally:
        connection.close()
    _check(reply, nonce, cert_hash, None)
    return TerminalConfig(
        desk_url(address), reply["desk_id"], reply["desk_key"], reply["token"], name,
        reply.get("main_name", ""),
    )  # fmt: skip


class MainDesk:
    """The connection to the main Desk. Calls are made one at a time, from any thread."""

    def __init__(self, config: TerminalConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._connection: http.client.HTTPSConnection | None = None
        self._reconnecting = False
        self._closed = False
        self.online = True

    def _open(self) -> http.client.HTTPSConnection:
        try:
            connection, cert_hash = _connect(self.config.address)
        except OSError:
            # The main Desk may have a new address: look for it by its ID.
            found = discovery.find(self.config.desk_id, seconds=1.5)
            if not found:
                raise
            self.config.address = desk_url(found)
            connection, cert_hash = _connect(self.config.address)
        nonce = crypto.nonce()
        try:
            _check(_post(connection, "/api/staff/hello", {"nonce": nonce}), nonce, cert_hash,
                   self.config.desk_key)  # fmt: skip
        except Exception:
            connection.close()
            raise
        return connection

    def call(self, target: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call the main Desk. While it is offline this fails at once (see reconnect)."""
        if not self.online:
            raise DeskOffline("The main Desk is offline")
        body = {"target": target, "method": method, "args": encode(args), "kwargs": encode(kwargs)}
        with self._lock:
            for attempt in range(2):  # a kept-alive connection may have been closed meanwhile
                try:
                    if self._connection is None:
                        self._connection = self._open()
                    reply = _post(self._connection, "/api/staff/call", body, self.config.token)
                    break
                except NotPaired:  # an answer, not a lost connection (it is an OSError too)
                    raise
                except (OSError, http.client.HTTPException, ValueError, DeskOffline) as exc:
                    if self._connection is not None:
                        self._connection.close()
                    self._connection = None
                    if attempt == 1:
                        self._went_offline()
                        raise DeskOffline(f"The main Desk is offline ({exc})") from exc
        if "error" in reply:
            kinds = {"KeyError": KeyError, "ValueError": ValueError, "LookupError": LookupError}
            raise kinds.get(reply["error"], RuntimeError)(reply.get("message", ""))
        return decode(reply.get("result"))

    def _went_offline(self) -> None:
        """Try again in the background, so the window never waits on a Desk that is gone."""
        self.online = False
        if self._reconnecting:
            return
        self._reconnecting = True

        def retry() -> None:
            while not self._closed:
                time.sleep(RETRY_AFTER)
                try:
                    connection = self._open()
                except Exception:  # still gone, or not who it should be
                    continue
                with self._lock:
                    self._connection = connection
                self.online = True
                break
            self._reconnecting = False

        threading.Thread(target=retry, name="ytktv-terminal", daemon=True).start()

    def close(self) -> None:
        self._closed = True
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


class RemoteStore:
    """Looks like a DeskStore to the Desk's window; every call goes to the main Desk."""

    def __init__(self, main: MainDesk) -> None:
        self.main = main
        self.desk_id = main.config.desk_id
        self.public_key = main.config.desk_key
        self.fingerprint = main.config.fingerprint

    def __getattr__(self, name: str) -> Any:
        if name not in STORE_METHODS:
            raise AttributeError(name)
        return lambda *args, **kwargs: self.main.call("store", name, *args, **kwargs)


class RemoteHub:
    """Looks like the Hub: rooms are reached through the main Desk."""

    def __init__(self, main: MainDesk) -> None:
        self.main = main

    def online(self) -> set[str]:
        return set(self.main.call("hub", "online"))

    def send_soon(self, room_id: str, message: dict[str, Any]) -> None:
        self.main.call("hub", "send_soon", room_id, message)
