"""A self-signed certificate for the phone-microphone page.

Browsers only let a page use the microphone over HTTPS. There is no way to get a
certificate that phones trust for an address on a home network, so YTKTV makes its
own; the phone shows a warning once and the singer chooses to continue.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
from pathlib import Path

log = logging.getLogger(__name__)

VALID_DAYS = 3650


def _covers(certificate_file: Path, address: str) -> bool:
    """Whether the stored certificate was made for *address* and is still valid."""
    from cryptography import x509

    try:
        certificate = x509.load_pem_x509_certificate(certificate_file.read_bytes())
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        now = datetime.datetime.now(datetime.UTC)
        return (
            ipaddress.ip_address(address) in names.get_values_for_type(x509.IPAddress)
            and certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc
        )
    except Exception:
        return False


def ensure_certificate(folder: Path, address: str) -> tuple[Path, Path]:
    """Return (certificate, private key) files for *address*, creating them if needed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder.mkdir(parents=True, exist_ok=True)
    certificate_file, key_file = folder / "phone-mic.crt", folder / "phone-mic.key"
    if certificate_file.exists() and key_file.exists() and _covers(certificate_file, address):
        return certificate_file, key_file

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "YTKTV phone microphone")])
    now = datetime.datetime.now(datetime.UTC)
    addresses = {ipaddress.ip_address(address), ipaddress.ip_address("127.0.0.1")}
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    *(x509.IPAddress(a) for a in sorted(addresses, key=str)),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_file.chmod(0o600)
    certificate_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    log.info("made a certificate for the phone microphone page at %s", address)
    return certificate_file, key_file
