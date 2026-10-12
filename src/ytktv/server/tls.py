"""A self-signed certificate for the phone-microphone page.

Browsers only let a page use the microphone over HTTPS. There is no way to get a
certificate that phones trust for an address on a home network, so YTKTV makes its
own; the phone shows a warning once and the singer chooses to continue.

The certificate is built with two small pure-Python libraries. The usual choice,
``cryptography``, brings its own copy of OpenSSL in some builds, and inside a packaged
app that copy collides with the one Python uses.
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import logging
import secrets
from pathlib import Path

log = logging.getLogger(__name__)

# Apple's browsers refuse server certificates that are valid for longer than 825 days.
VALID_DAYS = 800


def _covers(certificate_file: Path, address: str) -> bool:
    """Whether the stored certificate was made for *address* and is still valid."""
    from asn1crypto import pem, x509

    try:
        _kind, _headers, der = pem.unarmor(certificate_file.read_bytes())
        certificate = x509.Certificate.load(der)
        names = certificate.subject_alt_name_value.native
        validity = certificate["tbs_certificate"]["validity"]
        now = datetime.datetime.now(datetime.UTC)
        # Renew a month early, so it does not run out in the middle of an evening.
        return (
            str(ipaddress.ip_address(address)) in {str(name) for name in names}
            and validity["not_before"].native <= now
            and now + datetime.timedelta(days=30) < validity["not_after"].native
        )
    except Exception:
        return False


def ensure_certificate(folder: Path, address: str) -> tuple[Path, Path]:
    """Return (certificate, private key) files for *address*, creating them if needed."""
    from asn1crypto import keys, pem, x509
    from ecdsa import NIST256p, SigningKey
    from ecdsa.util import sigencode_der

    folder.mkdir(parents=True, exist_ok=True)
    certificate_file, key_file = folder / "phone-mic.crt", folder / "phone-mic.key"
    if certificate_file.exists() and key_file.exists() and _covers(certificate_file, address):
        return certificate_file, key_file

    key = SigningKey.generate(curve=NIST256p)
    name = x509.Name.build({"common_name": "YTKTV phone microphone"})
    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    addresses = sorted({str(ipaddress.ip_address(address)), "127.0.0.1"})
    algorithm = {"algorithm": "sha256_ecdsa"}
    body = x509.TbsCertificate(
        {
            "version": "v3",
            "serial_number": secrets.randbits(63) + 1,
            "signature": algorithm,
            "issuer": name,
            "validity": {
                "not_before": x509.Time({"utc_time": now - datetime.timedelta(days=1)}),
                "not_after": x509.Time({"utc_time": now + datetime.timedelta(days=VALID_DAYS)}),
            },
            "subject": name,
            "subject_public_key_info": keys.PublicKeyInfo.load(key.get_verifying_key().to_der()),
            "extensions": [
                {
                    "extn_id": "subject_alt_name",
                    "critical": False,
                    "extn_value": [
                        x509.GeneralName("dns_name", "localhost"),
                        *(x509.GeneralName("ip_address", a) for a in addresses),
                    ],
                },
                {"extn_id": "basic_constraints", "critical": True, "extn_value": {"ca": False}},
                {"extn_id": "key_usage", "critical": True, "extn_value": {"digital_signature"}},
                {"extn_id": "extended_key_usage", "critical": False, "extn_value": ["server_auth"]},
            ],
        }
    )
    signature = key.sign_deterministic(
        body.dump(), hashfunc=hashlib.sha256, sigencode=sigencode_der
    )
    certificate = x509.Certificate(
        {"tbs_certificate": body, "signature_algorithm": algorithm, "signature_value": signature}
    )
    key_file.write_bytes(key.to_pem(format="pkcs8"))
    key_file.chmod(0o600)
    certificate_file.write_bytes(pem.armor("CERTIFICATE", certificate.dump()))
    log.info("made a certificate for the phone microphone page at %s", address)
    return certificate_file, key_file
