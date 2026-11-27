"""Test helpers for minting the VAIDs ``cairn_kernel.vaid`` verifies.

Lives beside the other fakes (``FixedClock`` and friends) and for the
same reason: both the kernel's own VAID tests and the MCP gateway's
need to produce a real, kernel-signed credential, and neither should
reimplement the mint to do it.

CAIRN **verifies** VAIDs and never mints them in production -- nothing
outside this module and its callers touches ``MintService``,
``ReferenceIssuer`` or a private kernel key. A test issuer is a test
fixture, exactly like ``FakeEvidenceSigner``.

Two kinds of document are produced here, and the difference matters:

- :meth:`VaidTestIssuer.mint_root`/:meth:`mint_child` go through the
  real ``MintService``, which itself refuses to mint a child wider than
  its parent. They produce the credentials a verifier should accept.
- :meth:`VaidTestIssuer.forge` builds a document field by field and
  signs it with the same kernel key, bypassing the mint's own
  attenuation guard. This is how a *widened* or *cross-tenant* child is
  produced at all: one that is individually authentic and still must be
  refused, by the verifier's own independent containment check rather
  than by the mint's. A test that could only use the mint could never
  prove that check runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from vaid_mint import (
    InMemoryAudit,
    MintPop,
    MintService,
    ReferenceIssuer,
    VaidSeed,
    build_mint_pop_payload,
    build_unsigned_vaid_document,
    canonical_vaid_signing_bytes,
    compute_lineage_hash,
    prefix_entry,
)
from vaid_pop import canonical_request_signing_bytes

DEFAULT_TRUST_DOMAIN = "cairn.test"
SCHEMA_VERSION = "schema-v1"


class VaidTestIssuer:
    """A throwaway VAID mint over its own ephemeral kernel key.

    ``vaid_ttl_hours=0`` is the supported way to mint a credential that
    is *genuinely* expired against the real clock, which is what the
    expiry test needs: ``cairn_kernel.vaid`` deliberately exposes no
    injectable ``now``, so expiry has to be real rather than simulated.
    """

    def __init__(
        self,
        *,
        trust_domain: str = DEFAULT_TRUST_DOMAIN,
        vaid_ttl_hours: int = 24,
        max_delegation_depth: int = 4,
    ) -> None:
        self._kernel_key = Ed25519PrivateKey.generate()
        self.trust_domain = trust_domain
        self._issuer = ReferenceIssuer(self._kernel_key, vaid_ttl_hours, trust_domain)
        self._mint = MintService(
            self._issuer, InMemoryAudit(), max_delegation_depth=max_delegation_depth
        )
        # The mint rejects a replayed PoP nonce, so every mint from this
        # issuer needs a distinct one. A counter, not ``id(seed)``: CPython
        # reuses the address of a collected object, so two seeds minted in
        # sequence can genuinely share an id and the second mint is then
        # refused as a replay.
        self._nonce_counter = 0

    @property
    def kernel_public_key(self) -> bytes:
        """The raw Ed25519 public key a verifier pins this issuer by."""

        return self._issuer.kernel_public_key()

    def mint_root(
        self,
        *,
        tenant_id: str,
        capability_set: list[str],
        scope_prefixes: list[str],
        agent_class: str = "test-agent",
    ) -> dict[str, Any]:
        holder = Ed25519PrivateKey.generate()
        seed = VaidSeed(
            agent_class=agent_class,
            version=SCHEMA_VERSION,
            tenant_id=tenant_id,
            scope_boundary=[prefix_entry(value) for value in scope_prefixes],
            capability_set=list(capability_set),
            public_key_der=holder.public_key().public_bytes_raw(),
        )
        return self._mint.mint_root(seed, self._pop(seed, holder))

    def mint_child(
        self,
        parent: dict[str, Any],
        *,
        capability_set: list[str],
        scope_prefixes: list[str],
        tenant_id: str | None = None,
        agent_class: str = "test-worker",
    ) -> dict[str, Any]:
        """Mint an attenuated child through the real ``MintService``.

        The mint refuses anything wider than ``parent`` on scope,
        capabilities, tenant or lifetime -- so this raises
        ``vaid_mint.UnauthorizedError`` rather than returning a widened
        child. Use :meth:`forge` when a widened document is the point.
        """

        holder = Ed25519PrivateKey.generate()
        seed = VaidSeed(
            agent_class=agent_class,
            version=SCHEMA_VERSION,
            tenant_id=tenant_id if tenant_id is not None else parent["tenant_id"],
            parent_vaid=parent["vaid_id"],
            scope_boundary=[prefix_entry(value) for value in scope_prefixes],
            capability_set=list(capability_set),
            public_key_der=holder.public_key().public_bytes_raw(),
        )
        return self._mint.mint_child(seed, parent, self._pop(seed, holder)).vaid

    def forge(
        self,
        *,
        vaid_id: str,
        tenant_id: str,
        capability_set: list[str],
        scope_prefixes: list[str],
        parent: dict[str, Any] | None = None,
        issued_at: str | None = None,
        expires_at: str | None = None,
        agent_class: str = "test-forged",
        signing_key: Ed25519PrivateKey | None = None,
        trust_domain: str | None = None,
    ) -> dict[str, Any]:
        """Hand-build and sign a document, bypassing the mint's
        attenuation guard.

        Authentic under this issuer's kernel key unless ``signing_key``
        names another -- which is how the "wrong signature" case is
        produced without tampering with bytes, since a document signed
        by a key the verifier has not pinned is the realistic shape of
        that attack.
        """

        reference = (
            parent
            if parent is not None
            else self.mint_root(
                tenant_id=tenant_id, capability_set=capability_set, scope_prefixes=scope_prefixes
            )
        )
        parent_vaid = parent["vaid_id"] if parent is not None else None
        document = build_unsigned_vaid_document(
            vaid_id=vaid_id,
            agent_id=vaid_id,
            agent_class=agent_class,
            version=SCHEMA_VERSION,
            tenant_id=tenant_id,
            issued_at=issued_at if issued_at is not None else reference["issued_at"],
            expires_at=expires_at if expires_at is not None else reference["expires_at"],
            public_key_der=self._holder_key(),
            parent_vaid=parent_vaid,
            scope_boundary=[prefix_entry(value) for value in scope_prefixes],
            lineage_hash=compute_lineage_hash(parent_vaid, vaid_id),
            capability_set=list(capability_set),
            trust_domain=trust_domain if trust_domain is not None else self.trust_domain,
            kernel_key_thumbprint=reference["kernel_key_thumbprint"],
        )
        key = signing_key if signing_key is not None else self._kernel_key
        document["kernel_signature"] = list(key.sign(canonical_vaid_signing_bytes(document)))
        return document

    # -- internals -----------------------------------------------------

    def _holder_key(self) -> list[int]:
        """A fresh per-agent holder public key, as the document carries it.

        The holder key is bound into the signed document -- it is what
        request-level proof of possession would later be checked
        against. These tests never need the matching private key,
        because ``cairn_kernel.vaid`` deliberately does not verify PoP
        at this seam; see its own docstring.
        """

        return list(Ed25519PrivateKey.generate().public_key().public_bytes_raw())

    def _pop(self, seed: VaidSeed, holder: Ed25519PrivateKey) -> MintPop:
        """A valid mint-time proof of possession for ``seed``.

        The mint requires the requester to prove it holds the key it is
        asking to have bound, so ``holder`` must be the private half of
        ``seed.public_key_der``.
        """

        self._nonce_counter += 1
        nonce = f"cairn-test-{id(self):x}-{self._nonce_counter}"
        issued_at = _utc_whole_second()
        payload = build_mint_pop_payload(
            seed,
            public_key_der=holder.public_key().public_bytes_raw(),
            nonce=nonce,
            issued_at=issued_at,
        )
        return MintPop(
            nonce=nonce,
            issued_at=issued_at,
            signature=holder.sign(canonical_request_signing_bytes(payload)),
        )


def _utc_whole_second() -> str:
    from datetime import UTC

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["DEFAULT_TRUST_DOMAIN", "SCHEMA_VERSION", "VaidTestIssuer"]
