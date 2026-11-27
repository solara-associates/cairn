"""ADR-020 §3: what this deployment trusts a VAID to have been issued
under.

A VAID is checked **offline**, against a pinned trust anchor: the raw
Ed25519 kernel public key of the issuer that minted it, plus the set of
``trust_domain`` values this deployment accepts. Both are configuration,
not credentials -- a public key is safe to put in config, and nothing
here ever holds a private key (CAIRN verifies VAIDs, it never mints
them; ``vaid_mint``'s ``MintService``/``ReferenceIssuer`` are used only
in this repository's own tests).

``trust_domain`` matters because ``tenant_id`` alone is not globally
meaningful: the library's own ``tenant_attenuates`` compares the
qualified ``(trust_domain, tenant_id)`` pair for exactly that reason,
and a deployment that accepted any trust domain would accept a
self-hosted issuer's ``tenant_id: "acme"`` as its own. Accepting a
domain is therefore an explicit, listed decision here, never a default.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from cairn_kernel.errors import ConfigurationError

#: Length of a raw (not DER-wrapped) Ed25519 public key.
_ED25519_RAW_PUBLIC_KEY_BYTES = 32

ENV_VAID_KERNEL_KEYS = "CAIRN_VAID_KERNEL_KEYS"
ENV_VAID_TRUST_DOMAINS = "CAIRN_VAID_TRUST_DOMAINS"


@dataclass(frozen=True, slots=True)
class VaidTrustAnchors:
    """The pinned anchors a presented VAID is checked against.

    ``kernel_public_keys`` are raw 32-byte Ed25519 public keys; a key
    placed here is one this deployment accepts as an issuer. The
    library resolves which of them signed a given document by that
    document's own ``kernel_key_thumbprint``, so the order is
    irrelevant and a chain crossing issuers is supported by listing
    every accepted key.

    Both fields are required and neither may be empty: an anchor set
    with no key verifies nothing, and a domain set with no entry would
    make the ``(trust_domain, tenant_id)`` qualification meaningless.
    Refusing that at construction is the fail-closed shape (A5.7) --
    a deployment with no VAID configuration has no
    :class:`VaidTrustAnchors` at all, rather than an empty one that
    silently accepts whatever it is shown.
    """

    kernel_public_keys: tuple[bytes, ...]
    trust_domains: frozenset[str]

    def __post_init__(self) -> None:
        if not self.kernel_public_keys:
            raise ConfigurationError(
                "VAID trust anchors need at least one kernel public key; an empty anchor set"
                " verifies nothing"
            )
        for key in self.kernel_public_keys:
            if not isinstance(key, bytes) or len(key) != _ED25519_RAW_PUBLIC_KEY_BYTES:
                raise ConfigurationError(
                    "every VAID kernel public key must be"
                    f" {_ED25519_RAW_PUBLIC_KEY_BYTES} raw bytes (an Ed25519 public key)"
                )
        if not self.trust_domains:
            raise ConfigurationError(
                "VAID trust anchors need at least one accepted trust_domain; tenant_id alone is"
                " not globally meaningful"
            )
        if any(not domain.strip() for domain in self.trust_domains):
            raise ConfigurationError("a VAID trust_domain must not be blank")

    def accepts_trust_domain(self, trust_domain: object) -> bool:
        return isinstance(trust_domain, str) and trust_domain in self.trust_domains

    @classmethod
    def from_env(cls, env: dict[str, str]) -> VaidTrustAnchors:
        """Build anchors from ``CAIRN_VAID_KERNEL_KEYS`` (a comma-separated
        list of base64url-encoded raw Ed25519 public keys) and
        ``CAIRN_VAID_TRUST_DOMAINS`` (a comma-separated list of accepted
        ``trust_domain`` values).

        Both must be present and non-empty. A deployment that does not
        accept VAIDs sets neither and gets no authenticator at all
        (see ``cairn_kernel.vaid.selection``) -- it does not get an
        authenticator with nothing pinned.
        """

        keys = tuple(_decode_public_key(part) for part in _split(env.get(ENV_VAID_KERNEL_KEYS, "")))
        if not keys:
            raise ConfigurationError(
                f"{ENV_VAID_KERNEL_KEYS} is required to verify a VAID and names no key"
            )
        domains = frozenset(_split(env.get(ENV_VAID_TRUST_DOMAINS, "")))
        if not domains:
            raise ConfigurationError(
                f"{ENV_VAID_TRUST_DOMAINS} is required to verify a VAID and names no domain"
            )
        return cls(kernel_public_keys=keys, trust_domains=domains)


def _split(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _decode_public_key(encoded: str) -> bytes:
    """Decode one base64url-encoded raw Ed25519 public key, padding
    tolerated either way, and reject anything that is not one."""

    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise ConfigurationError(
            f"{ENV_VAID_KERNEL_KEYS} entry is not valid base64url: {exc}"
        ) from exc
    if len(decoded) != _ED25519_RAW_PUBLIC_KEY_BYTES:
        raise ConfigurationError(
            f"{ENV_VAID_KERNEL_KEYS} entry decodes to {len(decoded)} bytes, expected"
            f" {_ED25519_RAW_PUBLIC_KEY_BYTES} (a raw Ed25519 public key)"
        )
    return decoded


__all__ = [
    "ENV_VAID_KERNEL_KEYS",
    "ENV_VAID_TRUST_DOMAINS",
    "VaidTrustAnchors",
]
