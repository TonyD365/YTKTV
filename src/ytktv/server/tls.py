"""A self-signed certificate for the phone-microphone page (and the Desk's server).

Browsers only let a page use the microphone over HTTPS. There is no way to get a
certificate that phones trust for an address on a home network, so YTKTV makes its
own; the phone shows a warning once and the singer chooses to continue.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import secrets
from pathlib import Path

log = logging.getLogger(__name__)

# Apple's browsers refuse server certificates that are valid for longer than 825 days.
VALID_DAYS = 800


def _covers(certificate_file: Path, address: str) -> bool:
    """Whether the stored certificate was made for *address* and is still valid."""
    from cryptography import x509

    try:
        certificate = x509.load_pem_x509_certificate(certificate_file.read_bytes())
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        ips = {str(ip) for ip in names.get_values_for_type(x509.IPAddress)}
        now = datetime.datetime.now(datetime.UTC)
        # Renew a month early, so it does not run out in the middle of an evening.
        return (
            str(ipaddress.ip_address(address)) in ips
            and certificate.not_valid_before_utc <= now
            and now + datetime.timedelta(days=30) < certificate.not_valid_after_utc
        )
    except Exception:
        return False


def ensure_certificate(folder: Path, address: str) -> tuple[Path, Path]:
    """Return (certificate, private key) files for *address*, creating them if needed."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    folder.mkdir(parents=True, exist_ok=True)
    certificate_file, key_file = folder / "phone-mic.crt", folder / "phone-mic.key"
    if certificate_file.exists() and key_file.exists() and _covers(certificate_file, address):
        return certificate_file, key_file

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "YTKTV phone microphone")])
    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    addresses = sorted({str(ipaddress.ip_address(address)), "127.0.0.1"})
    no = {"content_commitment": False, "key_encipherment": False, "data_encipherment": False,
          "key_agreement": False, "key_cert_sign": False, "crl_sign": False,
          "encipher_only": False, "decipher_only": False}  # fmt: skip
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(secrets.randbits(63) + 1)
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    *(x509.IPAddress(ipaddress.ip_address(a)) for a in addresses),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, **no), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
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
