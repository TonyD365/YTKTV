"""Several Desks on one: what a staff terminal may ask the main Desk, and the log of who did what.

The main Desk keeps every record. A staff terminal is another YTKTV Desk that sends each read
and each change to it (see remote.py), so every terminal sees the same rooms. Changes made on
any of them, the main Desk included, are written to the operation log with the machine's name.
"""

from __future__ import annotations

import dataclasses
import hashlib
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ytktv.desk import billing
from ytktv.desk import store as desk_store
from ytktv.desk.server import Hub, tell
from ytktv.desk.store import DeskStore

# Values that travel as {"__type__": name, "fields": {...}} and come back as the same class.
TYPES: dict[str, type] = {
    cls.__name__: cls
    for cls in (
        desk_store.Product,
        desk_store.Order,
        desk_store.Call,
        desk_store.Booking,
        desk_store.Member,
        desk_store.Visit,
        desk_store.Room,
        desk_store.Terminal,
        desk_store.LogEntry,
        billing.Bill,
    )
}

# DeskStore methods a terminal may call. Anything else (pairing, keys, signing) stays local.
READS = frozenset(
    {
        "rooms", "room", "now_singing", "history", "members", "member_by_phone", "bookings",
        "clashes", "setting", "low_stock", "products", "orders", "calls", "terminals", "oplog",
    }
)  # fmt: skip
CHANGES = frozenset(
    {
        "new_code", "rename", "remove", "open_room", "extend", "close_room", "add_member",
        "top_up", "pay_from_balance", "add_points", "book", "set_booking_status", "set_state",
        "set_type", "change_room", "set_rate", "set_setting", "save_product", "remove_product",
        "add_order", "set_order_status", "finish_call", "remove_terminal", "rename_terminal",
    }
)  # fmt: skip
STORE_METHODS = READS | CHANGES
# Settings whose values are not written into the log.
SECRET_SETTINGS = ("password", "pin")


def encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
        return {"__type__": type(value).__name__, "fields": fields}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    return value


def decode(value: Any) -> Any:
    if isinstance(value, dict):
        if "__type__" in value:
            cls = TYPES[value["__type__"]]
            fields = {k: decode(v) for k, v in value["fields"].items()}
            if cls in (desk_store.Visit, billing.Bill):
                fields["lines"] = [tuple(line) for line in fields.get("lines", [])]
            return cls(**fields)
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(item) for item in value]
    return value


def describe(store: DeskStore, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """A line for the operation log, in words a manager reads."""

    def room(room_id: Any) -> str:
        found = store.room(str(room_id))
        return found.name if found else str(room_id)

    def arg(i: int, name: str) -> Any:
        return args[i] if len(args) > i else kwargs.get(name)

    if method == "open_room":
        minutes = arg(2, "minutes")
        length = "no time limit" if minutes is None else f"{minutes} min"
        guest = arg(1, "guest")
        return (
            f"Opened {room(arg(0, 'room_id'))}"
            + (f" for {guest}" if guest else "")
            + (f" ({length})")
        )
    if method == "close_room":
        bill = arg(1, "bill")
        paid = f", {bill.currency}{bill.total:.2f} by {bill.payment}" if bill is not None else ""
        return f"Closed {room(arg(0, 'room_id'))}{paid}"
    if method == "extend":
        return f"Added {arg(1, 'minutes')} min to {room(arg(0, 'room_id'))}"
    if method == "change_room":
        return f"Moved the guests from {room(arg(0, 'from_id'))} to {room(arg(1, 'to_id'))}"
    if method == "set_setting":
        key = str(arg(0, "key"))
        if any(secret in key for secret in SECRET_SETTINGS):
            return f"Changed the setting {key}"
        return f"Set {key} to {arg(1, 'value')}"
    if method in ("rename", "set_state", "set_type", "set_rate", "remove"):
        details = ", ".join(str(a) for a in args[1:])
        words = {
            "rename": "Renamed",
            "set_state": "Marked",
            "set_type": "Set the type of",
            "set_rate": "Set the price of",
            "remove": "Unbound",
        }[method]
        return f"{words} {room(arg(0, 'room_id'))}" + (f": {details}" if details else "")
    if method == "add_order":
        items = arg(1, "items") or []
        names = {p.product_id: p.name for p in store.products()}
        what = ", ".join(f"{qty} × {names.get(pid, pid)}" for pid, qty in items)
        return f"Added {what} to {room(arg(0, 'room_id'))}"
    if method == "save_product":
        product = arg(0, "product")
        return f"Saved the product {getattr(product, 'name', product)}"
    if method == "book":
        booking = arg(0, "booking")
        when = getattr(booking, "guest", "")
        return f"Booked {room(getattr(booking, 'room_id', ''))}" + (f" for {when}" if when else "")
    if method == "new_code":
        return "Showed a code to bind a room"
    words = method.replace("_", " ")
    shown = ", ".join(str(a) for a in args)
    return words[:1].upper() + words[1:] + (f": {shown}" if shown else "")


def describe_message(store: DeskStore, room_id: str, message: dict[str, Any]) -> str | None:
    """A line for the log when a room is told something by hand; None for routine updates."""
    name = store.room(room_id)
    where = name.name if name else room_id
    kind = message.get("type")
    if kind == "control":
        value = message.get("value")
        return f"{str(message.get('action')).capitalize()} in {where}" + (
            f" ({value})" if value is not None else ""
        )
    if kind in ("lock", "unlock"):
        return f"{'Paused' if kind == 'lock' else 'Unpaused'} {where}"
    if kind == "message":
        return f"Sent “{message.get('text')}” to {where}"
    return None


class LoggedStore:
    """A DeskStore whose changes are written to the operation log under *machine*'s name."""

    def __init__(self, store: DeskStore, machine: Callable[[], str]) -> None:
        self._store = store
        self._machine = machine

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._store, name)
        if name not in CHANGES:
            return value

        def logged(*args: Any, **kwargs: Any) -> Any:
            line = describe(self._store, name, args, kwargs)  # before: a room may be removed
            result = value(*args, **kwargs)
            self._store.log(self._machine(), line)
            return result

        return logged


class LoggedHub:
    """A Hub that logs what staff send to rooms by hand (controls, pauses, messages)."""

    def __init__(self, hub: Hub, store: DeskStore, machine: Callable[[], str]) -> None:
        self._hub = hub
        self._store = store
        self._machine = machine

    def online(self) -> set[str]:
        return self._hub.online()

    def send_soon(self, room_id: str, message: dict[str, Any]) -> None:
        line = describe_message(self._store, room_id, message)
        self._hub.send_soon(room_id, message)
        if line:
            self._store.log(self._machine(), line)


# -- the main Desk's side ---------------------------------------------------------

ASSETS = Path(__file__).parent / "assets"
SERVER_SETTING = "terminal_server"  # "1" while other Desks may pair and work on this one
NAME_SETTING = "machine_name"


def certificate_hash(certificate_file: Path) -> str:
    """SHA-256 of the TLS certificate, as a terminal sees it in the handshake."""
    from asn1crypto import pem

    _kind, _headers, der = pem.unarmor(certificate_file.read_bytes())
    return hashlib.sha256(der).hexdigest()


def proof(nonce: str, cert_hash: str) -> bytes:
    """What the main Desk signs: this connection's certificate, for this terminal's nonce."""
    return f"ytktv-staff:{nonce}:{cert_hash}".encode()


def checkout(store: Any, hub: Hub, room_id: str, payment: str) -> billing.Bill:
    """Close a room with its bill at the usual prices (for phones, which have no till)."""
    bill = billing.bill(store, room_id)
    bill.payment = payment if payment in billing.PAYMENTS else bill.payment
    store.close_room(room_id, bill)
    tell(store, hub, room_id)
    return bill


def machine_name(store: DeskStore) -> str:
    return store.setting(NAME_SETTING) or socket.gethostname() or "Main desk"


class PairIn(BaseModel):
    code: str
    name: str
    nonce: str


class HelloIn(BaseModel):
    nonce: str


class CallIn(BaseModel):
    target: str  # "store", "hub" or "terminal"
    method: str
    args: list[Any] = []
    kwargs: dict[str, Any] = {}


def add_staff_routes(app: FastAPI, store: DeskStore, hub: Hub, cert_hash: str) -> None:
    def serving() -> None:
        if store.setting(SERVER_SETTING, "0") != "1":
            raise HTTPException(403, "This Desk does not accept staff terminals")

    def signed(nonce: str) -> dict[str, str]:
        return {
            "desk_id": store.desk_id,
            "desk_key": store.public_key,
            "signature": store.sign(proof(nonce, cert_hash)),
            "main_name": machine_name(store),
        }

    @app.get("/staff", response_class=HTMLResponse)
    def phone_page() -> str:
        """The staff terminal for a phone: rooms, calls and orders, in the browser."""
        return (ASSETS / "staff.html").read_text(encoding="utf-8")

    @app.post("/api/staff/hello")
    def hello(body: HelloIn) -> dict[str, str]:
        return signed(body.nonce)

    @app.post("/api/staff/pair")
    def pair(body: PairIn) -> dict[str, str]:
        serving()
        try:
            terminal_id, token = store.pair_terminal(body.code.strip(), body.name.strip())
        except KeyError as exc:
            raise HTTPException(403, "wrong or expired code") from exc
        store.log(body.name.strip() or "Staff terminal", "Paired as a staff terminal")
        return {"terminal_id": terminal_id, "token": token, **signed(body.nonce)}

    @app.post("/api/staff/call")
    def call(body: CallIn, authorization: str = Header("")) -> dict[str, Any]:
        serving()
        terminal = store.terminal_by_token(authorization.removeprefix("Bearer ").strip())
        if terminal is None:
            raise HTTPException(401, "This terminal is no longer paired")
        args, kwargs = decode(body.args), decode(body.kwargs)
        name = terminal.name
        try:
            if body.target == "store" and body.method in STORE_METHODS:
                result = getattr(LoggedStore(store, lambda: name), body.method)(*args, **kwargs)
            elif body.target == "hub" and body.method in ("online", "send_soon"):
                result = getattr(LoggedHub(hub, store, lambda: name), body.method)(*args)
            elif body.target == "terminal" and body.method == "whoami":
                result = {"name": name, "main_name": machine_name(store)}
            elif body.target == "terminal" and body.method == "tell":
                tell(store, hub, str(args[0]))  # after a phone opened, extended or closed it
                result = None
            elif body.target == "terminal" and body.method == "checkout":
                bill = checkout(LoggedStore(store, lambda: name), hub, str(args[0]), str(args[1]))
                result = {"total": bill.total, "currency": bill.currency, "payment": bill.payment}
            elif body.target == "terminal" and body.method == "rename":
                store.rename_terminal(terminal.terminal_id, str(args[0]))
                store.log(str(args[0]), f"Renamed this terminal (was {name})")
                result = None
            else:
                raise HTTPException(404, f"no such call: {body.target}.{body.method}")
        except (KeyError, ValueError, LookupError) as exc:
            return {"error": type(exc).__name__, "message": str(exc)}
        return {"result": encode(result)}
