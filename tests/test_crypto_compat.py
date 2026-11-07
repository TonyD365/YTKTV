"""Rooms paired before YTKTV moved from the ecdsa package to cryptography keep working."""

from __future__ import annotations

from ytktv.rooms import crypto

# Made with ecdsa 0.19.2 (Ed25519, SigningKey.to_string() / sign()), as old installs stored them.
OLD_PRIVATE = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
OLD_PUBLIC = "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
DATA = b"ytktv pairing check"
OLD_SIGNATURE = (
    "fd046ce78056d7dd861424c2c42b58e454a6cde3620df0a11d89159f5353c172"
    "8cc272feb96200c56c7603c09420d7acc3962e11ad07adc8e54e0f9a87b8a303"
)


def test_keys_and_signatures_from_before_still_work():
    assert crypto.public_key(OLD_PRIVATE) == OLD_PUBLIC
    assert crypto.verify(OLD_PUBLIC, DATA, OLD_SIGNATURE)
    # Ed25519 signatures are deterministic: the new code signs exactly as the old one did.
    assert crypto.sign(OLD_PRIVATE, DATA) == OLD_SIGNATURE


def test_new_keys_sign_and_verify():
    private = crypto.new_private_key()
    public = crypto.public_key(private)
    assert len(private) == len(public) == 64
    signature = crypto.sign(private, DATA)
    assert crypto.verify(public, DATA, signature)
    assert not crypto.verify(public, DATA + b"!", signature)
    assert not crypto.verify(public, DATA, "00" * 64)
    assert not crypto.verify("zz", DATA, signature)
