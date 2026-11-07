"""Signatures that let a room trust only the desk it was paired with."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# Keys are stored as hex of their raw 32 bytes (the private key is the RFC 8032 seed), as
# the ecdsa package wrote them before: rooms paired then keep working.
_RAW = serialization.Encoding.Raw

# Shown on both screens while pairing, so a desk pretending to be the real one is caught.
EMOJI = "🎤🎸🎹🥁🎺🎻🎧🎵🌙⭐🔥🌈🍉🍒🍩🍕🐱🐶🦊🐼🦄🐙🐝🦋🚀🎈🎁💎👑🌵🍀🌻"


def new_private_key() -> str:
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        _RAW, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    ).hex()


def public_key(private_hex: str) -> str:
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    return key.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw).hex()


def sign(private_hex: str, data: bytes) -> str:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex)).sign(data).hex()


def verify(public_hex: str, data: bytes, signature_hex: str) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
        key.verify(bytes.fromhex(signature_hex), data)
        return True
    except (InvalidSignature, ValueError):
        return False


def desk_id(public_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()[:16]


def fingerprint(public_hex: str) -> str:
    digest = hashlib.sha256(b"ytktv-desk" + bytes.fromhex(public_hex)).digest()
    return "".join(EMOJI[b % len(EMOJI)] for b in digest[:4])


def mac(key: str, data: bytes) -> str:
    return hmac.new(key.encode(), data, hashlib.sha256).hexdigest()


def nonce() -> str:
    return secrets.token_hex(16)
