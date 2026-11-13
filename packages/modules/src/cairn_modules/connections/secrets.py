"""One-way digesting of provider credential secrets.

A provider connection's raw secret must never be persisted in plaintext
(R1-02 acceptance criteria). This module only ever produces a salted digest;
there is no function in this module that returns the original secret from a
``SecretDigest``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as secrets_module

from cairn_kernel.errors import ValidationError

from cairn_modules.connections.models import SecretDigest

ALGORITHM = "sha256"
_SALT_BYTES = 16


def digest_secret(secret: str) -> SecretDigest:
    """Return a one-way digest of ``secret``. The caller's ``secret`` value is
    never stored by this function or its caller; only the returned digest is."""

    if not secret.strip():
        raise ValidationError("provider credential secret is required")
    salt = secrets_module.token_bytes(_SALT_BYTES)
    digest = hashlib.sha256(salt + secret.encode("utf-8")).hexdigest()
    return SecretDigest(algorithm=ALGORITHM, salt_hex=salt.hex(), digest_hex=digest)


def secret_matches(secret: str, digest: SecretDigest) -> bool:
    """Constant-time check that ``secret`` produced ``digest``, without ever
    reconstructing the original secret from the digest."""

    if digest.algorithm != ALGORITHM:
        return False
    salt = bytes.fromhex(digest.salt_hex)
    expected = hashlib.sha256(salt + secret.encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, digest.digest_hex)


__all__ = ["ALGORITHM", "digest_secret", "secret_matches"]
