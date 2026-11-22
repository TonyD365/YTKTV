"""Who a room and the desk are, and the sealed messages between them (built on lanpair).

Every message between a room and the desk is a lanpair envelope: encrypted to the
recipient, signed by the sender and numbered, so it cannot be read, forged or played back
on the network. Each connection also swaps fresh session keys, so a message recorded today
cannot be read later even with either side's long-term key (forward secrecy).
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from lanpair import Identity, JsonFileSeqStore, Opener, PublicIdentity

APP = "ytktv-desk"  # the mDNS service, _ytktv-desk._tcp
SKEW = 300.0  # seconds a room's clock may be off from the desk's


def new_seed() -> str:
    """A new private identity, as hex of its 32-byte seed."""
    return Identity.generate().seed().hex()


def identity(seed_hex: str) -> Identity:
    return Identity.from_seed(bytes.fromhex(seed_hex))


def public(identity_hex: str) -> PublicIdentity:
    """Another side's public identity from its hex; ValueError when it is not one."""
    raw = bytes.fromhex(identity_hex)
    return PublicIdentity.from_bytes(raw)


def public_hex(identity: Identity | PublicIdentity) -> str:
    key = identity.public if isinstance(identity, Identity) else identity
    return key.to_bytes().hex()


def valid_public(identity_hex: str) -> bool:
    try:
        public(identity_hex)
    except ValueError:
        return False
    return True


def opener(me: Identity, seq_file: Path) -> Opener:
    """Opens messages for *me*; numbers kept in *seq_file*, so nothing replays after a restart."""
    return Opener(me, store=JsonFileSeqStore(seq_file), max_skew=SKEW)


def session_key(receiver: Opener) -> bytes:
    """A fresh key for this connection; returns its public half to send to the other side."""
    return receiver.add_session_key(X25519PrivateKey.generate())
