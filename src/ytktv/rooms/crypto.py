"""Signatures that let a room trust only the desk it was paired with."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from ecdsa import BadSignatureError, Ed25519, SigningKey, VerifyingKey

# Shown on both screens while pairing, so a desk pretending to be the real one is caught.
EMOJI = "🎤🎸🎹🥁🎺🎻🎧🎵🌙⭐🔥🌈🍉🍒🍩🍕🐱🐶🦊🐼🦄🐙🐝🦋🚀🎈🎁💎👑🌵🍀🌻"


def new_private_key() -> str:
    return SigningKey.generate(curve=Ed25519).to_string().hex()


def public_key(private_hex: str) -> str:
    key = SigningKey.from_string(bytes.fromhex(private_hex), curve=Ed25519)
    return key.verifying_key.to_string().hex()


def sign(private_hex: str, data: bytes) -> str:
    key = SigningKey.from_string(bytes.fromhex(private_hex), curve=Ed25519)
    return key.sign(data).hex()


def verify(public_hex: str, data: bytes, signature_hex: str) -> bool:
    try:
        key = VerifyingKey.from_string(bytes.fromhex(public_hex), curve=Ed25519)
        return bool(key.verify(bytes.fromhex(signature_hex), data))
    except (BadSignatureError, ValueError, AssertionError):
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
