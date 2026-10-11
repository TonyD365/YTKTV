#!/bin/bash
# CI helper: import the Developer ID certificates from MACOS_CERTIFICATE_P12
# (base64 .p12) into a temporary keychain. Exits 1 when no certificate is set,
# so callers can fall back to an unsigned build.
set -euo pipefail

if [ -z "${MACOS_CERTIFICATE_P12:-}" ]; then
  exit 1
fi
keychain="$RUNNER_TEMP/signing.keychain-db"
keychain_password="$(uuidgen)"
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
echo "$MACOS_CERTIFICATE_P12" | base64 --decode > "$RUNNER_TEMP/certificate.p12"
security import "$RUNNER_TEMP/certificate.p12" -k "$keychain" -P "$MACOS_CERTIFICATE_PASSWORD" \
  -T /usr/bin/codesign -T /usr/bin/pkgbuild -T /usr/bin/productbuild -T /usr/bin/productsign
security set-key-partition-list -S apple-tool:,apple: -k "$keychain_password" "$keychain" >/dev/null
security list-keychains -d user -s "$keychain"
rm "$RUNNER_TEMP/certificate.p12"
