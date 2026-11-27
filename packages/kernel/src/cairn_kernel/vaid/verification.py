"""ADR-020 §3: verifying a presented VAID and deriving the narrowed
``Principal`` the rest of CAIRN already enforces against.

This module is the whole of CAIRN's VAID integration. It is in
``cairn_kernel`` -- core, not an adapter -- for the reason ADR-020 §3
gives: verifying a VAID's own cryptographic structure is a kernel-level
concern with no provider SDK underneath it and no network call in it,
the same reasoning that keeps ``ModelGateway``'s policy chain in
``cairn_kernel``. The published, open-source ``vaid-mint`` package (and
its ``vaid-pop`` dependency) is a library dependency like ``pydantic``;
nothing here is vendored and nothing here phones a VAID-operated
service.

**What this verifies, and what it deliberately does not.**

Verified here, all of it offline against a pinned
:class:`~cairn_kernel.vaid.trust.VaidTrustAnchors`:

- the document parses as a VAID at all (``parse_vaid_document``);
- its ``trust_domain`` is one this deployment accepts, for the leaf and
  for every ancestor presented with it;
- its lineage assembles completely from the documents presented;
- the issuer's kernel Ed25519 signature, the ``lineage_hash``, the
  signature-scheme version, expiry, and revocation over the whole
  assembled lineage (``verify_vaid_standing``);
- **attenuation at every hop of the chain** -- tenant, scope,
  capabilities and expiry each contained in the parent's
  (``verify_chain_at``). This is the "scope can only shrink" guarantee
  inside the credential.

Not verified here, and named rather than quietly skipped:

- **Request-level proof of possession.** ``vaid_pop``'s ``RequestSigner``
  and the four ``x-...-vaid``/``-timestamp``/``-nonce``/``-signature``
  headers bind a *specific HTTP request* (method, path, body digest) to
  the holder's key. ``McpGateway.call_tool`` is an in-process call with
  no HTTP request to bind to, so there is nothing for that signature to
  cover at this seam. A VAID presented here proves the credential is
  genuine, current and attenuated; it does not, on its own, prove the
  presenter holds the key. A deployment that exposes the gateway over a
  real network transport must add the PoP check at that transport, and
  this docstring is the record that it is not here yet.
- **A chain that crosses kernel keys.** ``verify_chain_at`` requires a
  consent attestation for any hop whose child was signed by a different
  issuer key than its parent. This unit carries no attestations, so such
  a chain is refused (``UNVERIFIABLE``/``CONSENT_EXPIRED``) rather than
  accepted. CAIRN's own agent VAIDs are single-issuer, so this costs
  nothing today and fails closed if it ever stops being true.

**The clock is this process's own, never the caller's.** Leaf expiry is
the library's ``is_expired`` against the system clock and chain expiry
is ``verify_chain_at`` against ``datetime.now(timezone.utc)``. No
``now`` is injectable, deliberately: a verifier whose idea of the
current time a caller can influence is not a verifier. Tests that need
an expired credential mint one that is genuinely expired (a
zero-hour-TTL issuer), rather than moving the verifier's clock.

**What CAIRN requires of whoever mints its VAIDs.** A ``Principal`` has
a tenant, a subject and ``Role``s, so the VAID document must carry those
in its own fields -- this is a deployment convention CAIRN imposes on an
issuer, not something the VAID standard prescribes:

- ``tenant_id`` is a CAIRN ``TenantId``, i.e. a UUID string, the same
  shape ``JwtAuthenticator`` already requires of its tenant claim;
- ``capability_set`` names CAIRN ``Role`` values (``VIEWER``,
  ``ARCHITECT``, ...). Entries that name no CAIRN role are kept on the
  scope but grant nothing; a VAID whose capabilities name no CAIRN role
  at all is refused, because it could only ever be a misconfiguration;
- ``scope_boundary`` prefix entries name CAIRN resource prefixes, kept
  on :class:`VaidScope` as the narrowing the credential carries.

**Scope can only ever shrink.** Two axes, both enforced:

1. *Inside the chain*, by ``verify_chain_at`` as above -- a child that
   widens scope, capabilities, tenant or lifetime relative to its parent
   is ``NOT_ATTENUATED``, and refused, even when every document in the
   chain is individually authentic.
2. *Against the authority backing it*, when a bearer token is presented
   alongside the VAID (ADR-020 §3's "instead of, or in addition to"):
   the VAID's tenant must be the bearer principal's own, and the VAID's
   derived roles must be a subset of the bearer principal's. A VAID used
   to ask for more than its backing token actually grants is refused.

The ``Principal`` this returns is the narrowed one. Nothing downstream
-- ``McpGateway.authorize``, every bounded-context server's tenant check
(ADR-020 §2) -- knows or cares which authenticator produced it, which is
exactly why a VAID cannot become a way around those checks.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from vaid_mint import (
    AttestationBundle,
    ChainVerification,
    KernelKeyMap,
    PresentedBundle,
    RevocationCheck,
    RevocationStatus,
    VaidVerdict,
    assemble_lineage,
    is_in_scope,
    parse_vaid_document,
    verify_chain_at,
    verify_vaid_standing,
)

from cairn_kernel.errors import TenantScopeViolationError, UnauthenticatedError
from cairn_kernel.hex import TenantId
from cairn_kernel.security import Principal, Role, role_from_claim
from cairn_kernel.vaid.trust import VaidTrustAnchors

#: ``Principal.subject`` prefix for a principal derived from a VAID, so
#: an audit entry or evidence envelope says which credential shape the
#: actor was proved by, not only its id.
VAID_SUBJECT_PREFIX = "vaid:"


class VaidVerificationError(UnauthenticatedError):
    """A presented VAID was refused.

    An :class:`~cairn_kernel.errors.UnauthenticatedError` subclass
    because a VAID *is* the caller's credential: a bad one is the same
    class of failure as a bad bearer token, and the API's own
    ``STATUS_BY_CODE`` already maps that code to 401. ``verdict`` and
    ``chain`` carry the library's own reason where there is one, so
    "forged" is never collapsed into "could not reach a revocation
    list" in a log.
    """

    title = "VAID verification failed"

    def __init__(
        self,
        detail: str = "",
        *,
        verdict: VaidVerdict | None = None,
        chain: ChainVerification | None = None,
    ) -> None:
        super().__init__(detail)
        self.verdict = verdict
        self.chain = chain


class VaidScopeWideningError(VaidVerificationError):
    """A presented VAID asked for more authority than the credential
    behind it actually grants. Scope can only shrink (ADR-020 §3)."""

    title = "VAID scope widening refused"


@dataclass(frozen=True, slots=True)
class VaidPresentation:
    """What a caller presents: one leaf VAID document as JSON text, plus
    the ancestor documents needed to assemble its lineage, root-last
    order irrelevant (they are indexed by ``vaid_id``).

    A root VAID is presented alone. A delegated one must be presented
    with every ancestor up to its root: a lineage that cannot be
    assembled from what was presented is ``UNAVAILABLE``, and refused,
    rather than checked only as far as the leaf.
    """

    document: str
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.document.strip():
            raise VaidVerificationError("no VAID document was presented")


@dataclass(frozen=True, slots=True)
class VaidScope:
    """The narrowed scope a verified VAID carries, alongside the
    ``Principal`` derived from it.

    This is the credential's own narrowing, recorded so a caller that
    needs more than tenant/role -- a project prefix, the delegation
    chain this authority came down -- has it from the credential rather
    than from an argument the caller supplied about itself.
    """

    vaid_id: str
    agent_id: str
    tenant_id: TenantId
    trust_domain: str
    roles: tuple[Role, ...]
    capability_set: tuple[str, ...]
    resource_prefixes: tuple[str, ...]
    delegation_lineage: tuple[str, ...]
    expires_at: str

    @property
    def delegated_by(self) -> str | None:
        """The ``vaid_id`` this authority was delegated from, or ``None``
        for a root VAID."""

        if len(self.delegation_lineage) < 2:
            return None
        return self.delegation_lineage[-2]

    @property
    def delegation_depth(self) -> int:
        """Hops from the root: 0 for a root VAID."""

        return max(len(self.delegation_lineage) - 1, 0)

    def permits_resource(self, resource: str) -> bool:
        """Is ``resource`` inside this VAID's own ``scope_boundary``?

        Delegated to the library's single scope matcher (``is_in_scope``)
        rather than reimplemented here, so CAIRN cannot disagree with
        the mint about what a boundary means. An empty boundary is
        unrestricted, per the standard -- which the chain check already
        constrained: an empty child boundary is only attenuated under an
        empty parent.
        """

        return bool(is_in_scope(self._boundary_document(), resource))

    def _boundary_document(self) -> dict[str, object]:
        return {
            "scope_boundary": [
                {"kind": "prefix", "value": value} for value in self.resource_prefixes
            ]
        }


@dataclass(frozen=True, slots=True)
class VerifiedVaid:
    """A verified VAID: the narrowed ``Principal`` to authorize with, and
    the scope the credential carried."""

    principal: Principal
    scope: VaidScope


class VaidAuthenticator:
    """Verifies a presented VAID and derives the narrowed principal.

    Deliberately shaped like ``cairn_adapters.auth_oidc.JwtAuthenticator``
    -- credential in, ``Principal`` out, raise on refusal -- because
    ADR-020 §3 and ``docs/specs/r5-integration-boundaries.md``'s attach
    point 1 both say a VAID verifier is a second implementation of that
    same shape, never a parallel auth path.

    ``revocation`` has **no default**. The library's seam is three-valued
    and fails closed on ``UNAVAILABLE``; a default would have to be
    either "nothing is revoked" (fails open, so a revoked credential
    keeps working) or an unavailable store (refuses every VAID, so the
    default is indistinguishable from broken). A deployment accepting
    VAIDs therefore states which revocation source it consults. The
    library's own ``InMemoryRevocationList`` is explicitly non-durable
    and is what this repository's tests inject.
    """

    def __init__(self, anchors: VaidTrustAnchors, revocation: RevocationCheck) -> None:
        self._anchors = anchors
        self._revocation = revocation
        self._keys = KernelKeyMap(anchors.kernel_public_keys)

    def verify(
        self,
        presentation: VaidPresentation,
        *,
        backing_principal: Principal | None = None,
    ) -> VerifiedVaid:
        """Verify ``presentation`` and return the narrowed principal.

        Raises :class:`VaidVerificationError` for a VAID that is
        unparseable, from an unaccepted trust domain, inauthentic,
        expired, revoked or whose standing cannot be determined;
        :class:`VaidScopeWideningError` when it asks for more role
        authority than ``backing_principal`` holds; and
        ``TenantScopeViolationError`` when it names a different tenant
        than ``backing_principal``'s.

        ``backing_principal`` is the principal a bearer token presented
        alongside the VAID already proved (ADR-020 §3's "in addition
        to"). When it is ``None`` the VAID stands alone, and the chain's
        own attenuation is the only narrowing there is to check.
        """

        leaf = self._parse(presentation.document, "leaf")
        ancestors = tuple(
            self._parse(text, f"ancestor {index}")
            for index, text in enumerate(presentation.lineage)
        )
        for document in (leaf, *ancestors):
            self._require_accepted_trust_domain(document)

        bundle = PresentedBundle(list(ancestors))
        lineage = assemble_lineage(leaf, bundle)
        if lineage is None:
            raise VaidVerificationError(
                "VAID lineage could not be assembled from the documents presented; an"
                " incomplete chain is indeterminate, not unrevoked",
                verdict=VaidVerdict.INDETERMINATE,
            )

        revocation = self._revocation.check_lineage(list(lineage))
        if revocation is RevocationStatus.UNAVAILABLE:
            raise VaidVerificationError(
                "VAID revocation status is unavailable; a credential whose standing cannot be"
                " determined is refused",
                verdict=VaidVerdict.INDETERMINATE,
            )

        self._require_valid_standing(leaf, revocation)
        self._require_attenuated_chain(leaf, bundle)

        scope = self._scope_from(leaf, lineage)
        principal = Principal(
            subject=f"{VAID_SUBJECT_PREFIX}{scope.agent_id}",
            tenant_id=scope.tenant_id,
            roles=scope.roles,
        )
        if backing_principal is not None:
            self._require_narrower_than(scope, backing_principal)
        return VerifiedVaid(principal=principal, scope=scope)

    # -- individual checks, in the order ``verify`` runs them ----------

    def _parse(self, text: str, position: str) -> dict[str, object]:
        document = parse_vaid_document(text)
        if document is None:
            raise VaidVerificationError(
                f"presented VAID {position} document is not a VAID",
                verdict=VaidVerdict.UNPARSEABLE,
            )
        return document

    def _require_accepted_trust_domain(self, document: dict[str, object]) -> None:
        trust_domain = document.get("trust_domain")
        if not self._anchors.accepts_trust_domain(trust_domain):
            raise VaidVerificationError(
                f"VAID trust_domain {trust_domain!r} is not one this deployment accepts;"
                " tenant_id alone is not globally meaningful",
                verdict=VaidVerdict.MALFORMED_TRUST_DOMAIN,
            )

    def _require_valid_standing(
        self, leaf: dict[str, object], revocation: RevocationStatus
    ) -> None:
        thumbprint = leaf.get("kernel_key_thumbprint")
        key = self._keys.resolve_key(thumbprint) if isinstance(thumbprint, str) else None
        if key is None:
            raise VaidVerificationError(
                f"VAID names a kernel key this deployment has not pinned ({thumbprint!r})",
                verdict=VaidVerdict.ISSUER_MISMATCH,
            )
        verdict = verify_vaid_standing(key, leaf, revocation)
        if verdict is not VaidVerdict.VALID:
            raise VaidVerificationError(f"VAID was refused: {verdict.name}", verdict=verdict)

    def _require_attenuated_chain(self, leaf: dict[str, object], bundle: PresentedBundle) -> None:
        chain = verify_chain_at(
            self._keys,
            leaf,
            bundle,
            AttestationBundle(),
            datetime.now(UTC),
        )
        if chain is not ChainVerification.ATTENUATED:
            raise VaidVerificationError(
                "VAID delegation chain is not attenuated: "
                f"{chain.name}. Authority may only ever narrow down a chain",
                chain=chain,
            )

    def _scope_from(
        self, leaf: dict[str, object], lineage: tuple[str, ...] | list[str]
    ) -> VaidScope:
        tenant_id = _tenant_id_of(leaf)
        capability_set = _string_tuple(leaf.get("capability_set"), "capability_set")
        roles = tuple(
            dict.fromkeys(
                role
                for role in (role_from_claim(value) for value in capability_set)
                if role is not None
            )
        )
        if not roles:
            raise VaidVerificationError(
                "VAID capability_set names no CAIRN role"
                f" ({list(capability_set)!r}); it could authorize nothing"
            )
        return VaidScope(
            vaid_id=_required_string(leaf, "vaid_id"),
            agent_id=_required_string(leaf, "agent_id"),
            tenant_id=tenant_id,
            trust_domain=_required_string(leaf, "trust_domain"),
            roles=roles,
            capability_set=capability_set,
            resource_prefixes=_scope_prefixes(leaf.get("scope_boundary")),
            delegation_lineage=tuple(lineage),
            expires_at=_required_string(leaf, "expires_at"),
        )

    def _require_narrower_than(self, scope: VaidScope, backing: Principal) -> None:
        if scope.tenant_id != backing.tenant_id:
            raise TenantScopeViolationError(
                f"VAID names tenant {scope.tenant_id.value} but the credential behind it is"
                f" authenticated for tenant {backing.tenant_id.value}"
            )
        widened = tuple(role for role in scope.roles if role not in backing.roles)
        if widened:
            raise VaidScopeWideningError(
                "VAID claims role(s)"
                f" {[role.value for role in widened]!r} that the credential behind it does not"
                f" hold (it holds {list(backing.role_values())!r}); a VAID may only narrow"
                " authority, never widen it"
            )


def _required_string(document: dict[str, object], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise VaidVerificationError(f"VAID is missing a usable {field}")
    return value


def _tenant_id_of(document: dict[str, object]) -> TenantId:
    raw = _required_string(document, "tenant_id")
    try:
        return TenantId(str(uuid.UUID(raw)))
    except ValueError as exc:
        raise VaidVerificationError(
            "VAID tenant_id is not a uuid; CAIRN tenants are uuids, the same shape the"
            " bearer-token tenant claim already requires"
        ) from exc


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise VaidVerificationError(f"VAID {field} must be a list of strings")
    return tuple(value)


def _scope_prefixes(boundary: object) -> tuple[str, ...]:
    """The ``prefix``-kind values of a ``scope_boundary``.

    An entry of a kind this version does not understand is refused
    rather than ignored: the library's own ``VaidVerdict`` has an
    ``UNKNOWN_SCOPE_KIND`` state for exactly this, and silently
    dropping an entry would read a *narrowing* the issuer wrote as no
    narrowing at all.
    """

    if not isinstance(boundary, list):
        raise VaidVerificationError("VAID scope_boundary must be a list")
    prefixes: list[str] = []
    for entry in boundary:
        if not isinstance(entry, dict) or entry.get("kind") != "prefix":
            raise VaidVerificationError(
                f"VAID scope_boundary entry {json.dumps(entry, default=str)} is not a prefix"
                " entry; CAIRN cannot evaluate it, and ignoring it would read a narrowing as"
                " no narrowing",
                verdict=VaidVerdict.UNKNOWN_SCOPE_KIND,
            )
        value = entry.get("value")
        if not isinstance(value, str) or not value.strip():
            raise VaidVerificationError("VAID scope_boundary prefix entry has no value")
        prefixes.append(value)
    return tuple(prefixes)


__all__ = [
    "VAID_SUBJECT_PREFIX",
    "VaidAuthenticator",
    "VaidPresentation",
    "VaidScope",
    "VaidScopeWideningError",
    "VaidVerificationError",
    "VerifiedVaid",
]
