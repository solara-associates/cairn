"""ADR-020 §3: ``cairn_kernel.vaid`` verifies a presented VAID, derives
the narrowed principal, and refuses everything else.

Every refusal test asserts the *reason*, not only that something was
raised (A8.fail-closed-negative): a test that accepts any exception
would pass just as happily on a verifier that refused valid credentials
too.

The adversarial documents here are produced two ways, deliberately.
``VaidTestIssuer.mint_child`` goes through the real mint, which refuses
to issue a widened child at all -- so a widened or cross-tenant child
is built with ``forge``, signed by the same kernel key, and is therefore
individually *authentic*. That is the only way to prove the verifier
runs its own independent containment check rather than trusting that
whoever minted the chain already did.
"""

from __future__ import annotations

import json

import pytest
from cairn_kernel.errors import ConfigurationError, TenantScopeViolationError
from cairn_kernel.hex import TenantId
from cairn_kernel.security import Principal, Role
from cairn_kernel.testing import VaidTestIssuer
from cairn_kernel.vaid import (
    ENV_VAID_ENABLED,
    ENV_VAID_KERNEL_KEYS,
    ENV_VAID_TRUST_DOMAINS,
    VAID_SUBJECT_PREFIX,
    VaidAuthenticator,
    VaidPresentation,
    VaidScopeWideningError,
    VaidTrustAnchors,
    VaidVerificationError,
    resolve_vaid_authenticator,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from vaid_mint import ChainVerification, InMemoryRevocationList, VaidVerdict

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
PROJECT_SCOPE = "cairn.tenant-a.project-1"


@pytest.fixture
def issuer() -> VaidTestIssuer:
    return VaidTestIssuer()


@pytest.fixture
def revocation() -> InMemoryRevocationList:
    """A populated-but-empty store: available, and nothing revoked.

    Not a bare ``InMemoryRevocationList()`` -- that one is *unavailable*
    by design, which the verifier fails closed on. The distinction is
    the point of the library's three-state seam and is asserted
    directly in ``test_unavailable_revocation_store_is_refused``.
    """

    return InMemoryRevocationList().assume_nothing_revoked()


def _anchors(issuer: VaidTestIssuer) -> VaidTrustAnchors:
    return VaidTrustAnchors(
        kernel_public_keys=(issuer.kernel_public_key,),
        trust_domains=frozenset({issuer.trust_domain}),
    )


def _authenticator(
    issuer: VaidTestIssuer, revocation: InMemoryRevocationList
) -> VaidAuthenticator:
    return VaidAuthenticator(_anchors(issuer), revocation)


def _present(leaf: dict[str, object], *ancestors: dict[str, object]) -> VaidPresentation:
    return VaidPresentation(
        document=json.dumps(leaf),
        lineage=tuple(json.dumps(ancestor) for ancestor in ancestors),
    )


def _root(issuer: VaidTestIssuer, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "tenant_id": TENANT_A,
        "capability_set": ["VIEWER", "ARCHITECT"],
        "scope_prefixes": [PROJECT_SCOPE],
    }
    kwargs.update(overrides)
    return issuer.mint_root(**kwargs)  # type: ignore[arg-type]


# -- the valid case ---------------------------------------------------


def test_a_valid_root_vaid_derives_the_principal_it_carries(issuer, revocation) -> None:
    root = _root(issuer)

    verified = _authenticator(issuer, revocation).verify(_present(root))

    assert verified.principal == Principal(
        subject=f"{VAID_SUBJECT_PREFIX}{root['agent_id']}",
        tenant_id=TenantId(TENANT_A),
        roles=(Role.VIEWER, Role.ARCHITECT),
    )
    assert verified.scope.vaid_id == root["vaid_id"]
    assert verified.scope.trust_domain == issuer.trust_domain
    assert verified.scope.resource_prefixes == (PROJECT_SCOPE,)
    assert verified.scope.delegation_depth == 0
    assert verified.scope.delegated_by is None


def test_a_valid_delegated_vaid_derives_the_narrowed_scope_not_its_parents(
    issuer, revocation
) -> None:
    """The whole point of delegation: the principal the gateway will
    authorize with is the *child's*, never the wider authority above
    it."""

    root = _root(issuer)
    child = issuer.mint_child(
        root, capability_set=["VIEWER"], scope_prefixes=[f"{PROJECT_SCOPE}.estate"]
    )

    verified = _authenticator(issuer, revocation).verify(_present(child, root))

    assert verified.principal.roles == (Role.VIEWER,)
    assert Role.ARCHITECT not in verified.principal.roles
    assert verified.scope.resource_prefixes == (f"{PROJECT_SCOPE}.estate",)
    assert verified.scope.delegated_by == root["vaid_id"]
    assert verified.scope.delegation_depth == 1
    assert verified.scope.permits_resource(f"{PROJECT_SCOPE}.estate.workload-1")
    assert not verified.scope.permits_resource(f"{PROJECT_SCOPE}.finops")


def test_the_mint_itself_refuses_to_issue_a_wider_child(issuer) -> None:
    """Context for the forged-document tests below: a widened child
    cannot be *minted*, which is why the verifier's own independent
    check has to be proved against a forged one."""

    root = _root(issuer, capability_set=["VIEWER"])

    with pytest.raises(Exception) as exc_info:
        issuer.mint_child(
            root, capability_set=["VIEWER", "TENANT_ADMIN"], scope_prefixes=[PROJECT_SCOPE]
        )

    assert "attenuation" in str(exc_info.value).lower() or "exceeds" in str(exc_info.value)


# -- refusals ---------------------------------------------------------


def test_an_expired_vaid_is_refused(revocation) -> None:
    """Genuinely expired, not simulated: the verifier exposes no
    injectable ``now``, so the credential is minted with a zero-hour
    TTL and really has lapsed."""

    expired_issuer = VaidTestIssuer(vaid_ttl_hours=0)
    root = _root(expired_issuer)

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(expired_issuer, revocation).verify(_present(root))

    assert exc_info.value.verdict is VaidVerdict.EXPIRED
    assert "EXPIRED" in str(exc_info.value)


def test_a_vaid_signed_by_an_unpinned_key_is_refused(issuer, revocation) -> None:
    """The realistic shape of a wrong signature: a document signed by a
    kernel key this deployment never pinned, rather than bytes flipped
    inside one it did."""

    forged = issuer.forge(
        vaid_id="99999999-9999-4999-8999-999999999999",
        tenant_id=TENANT_A,
        capability_set=["VIEWER"],
        scope_prefixes=[PROJECT_SCOPE],
        signing_key=Ed25519PrivateKey.generate(),
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(forged))

    assert exc_info.value.verdict is VaidVerdict.INAUTHENTIC


def test_a_tampered_vaid_is_refused(issuer, revocation) -> None:
    """A document whose signed bytes were altered after issue -- here
    the capability set, widened in place to claim TENANT_ADMIN."""

    root = _root(issuer, capability_set=["VIEWER"])
    tampered = dict(root)
    tampered["capability_set"] = ["VIEWER", "TENANT_ADMIN"]

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(tampered))

    assert exc_info.value.verdict is VaidVerdict.INAUTHENTIC


def test_a_revoked_vaid_is_refused(issuer, revocation) -> None:
    root = _root(issuer)
    revocation.revoke(str(root["vaid_id"]))

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(root))

    assert exc_info.value.verdict is VaidVerdict.REVOKED


def test_revoking_a_parent_refuses_its_delegated_child(issuer, revocation) -> None:
    """Revocation is computed over the whole assembled lineage, so
    revoking the authority a child was delegated from refuses the
    child -- not only the document that was named."""

    root = _root(issuer)
    child = issuer.mint_child(
        root, capability_set=["VIEWER"], scope_prefixes=[f"{PROJECT_SCOPE}.estate"]
    )
    revocation.revoke(str(root["vaid_id"]))

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(child, root))

    assert exc_info.value.verdict is VaidVerdict.REVOKED


def test_unavailable_revocation_store_is_refused(issuer) -> None:
    """Fail closed (A5.7): "I could not reach the revocation list" is not
    "nothing is revoked"."""

    authenticator = _authenticator(issuer, InMemoryRevocationList.unavailable())

    with pytest.raises(VaidVerificationError) as exc_info:
        authenticator.verify(_present(_root(issuer)))

    assert "unavailable" in str(exc_info.value)


def test_a_delegated_vaid_presented_without_its_ancestors_is_refused(
    issuer, revocation
) -> None:
    """An unassemblable lineage is indeterminate, so the credential is
    refused rather than checked only as far as its leaf -- which is what
    would let a revoked or widened ancestor go unexamined."""

    root = _root(issuer)
    child = issuer.mint_child(
        root, capability_set=["VIEWER"], scope_prefixes=[f"{PROJECT_SCOPE}.estate"]
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(child))

    assert "lineage could not be assembled" in str(exc_info.value)


def test_an_unparseable_presentation_is_refused(issuer, revocation) -> None:
    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(
            VaidPresentation(document="this is not a VAID")
        )

    assert exc_info.value.verdict is VaidVerdict.UNPARSEABLE


def test_an_unaccepted_trust_domain_is_refused(revocation) -> None:
    """``tenant_id`` is namespaced by nothing, so a self-hosted issuer
    minting the same tenant id must not be accepted as this
    deployment's own."""

    other_issuer = VaidTestIssuer(trust_domain="someone-else.example")
    root = _root(other_issuer)
    authenticator = VaidAuthenticator(
        VaidTrustAnchors(
            kernel_public_keys=(other_issuer.kernel_public_key,),
            trust_domains=frozenset({"cairn.test"}),
        ),
        revocation,
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        authenticator.verify(_present(root))

    assert exc_info.value.verdict is VaidVerdict.MALFORMED_TRUST_DOMAIN


def test_a_vaid_whose_capabilities_name_no_cairn_role_is_refused(issuer, revocation) -> None:
    root = _root(issuer, capability_set=["read", "write"])

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(root))

    assert "names no CAIRN role" in str(exc_info.value)


def test_a_non_uuid_tenant_id_is_refused(issuer, revocation) -> None:
    root = _root(issuer, tenant_id="acme")

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(root))

    assert "not a uuid" in str(exc_info.value)


# -- scope can only shrink: inside the chain --------------------------


def test_a_child_widening_its_scope_is_refused(issuer, revocation) -> None:
    """The forged child is authentic under the pinned kernel key and
    still refused, because the verifier recomputes containment at every
    hop instead of trusting the chain it was handed."""

    root = _root(issuer, capability_set=["VIEWER"], scope_prefixes=[f"{PROJECT_SCOPE}.estate"])
    widened = issuer.forge(
        vaid_id="99999999-9999-4999-8999-999999999999",
        tenant_id=TENANT_A,
        capability_set=["VIEWER"],
        scope_prefixes=["cairn"],
        parent=root,
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(widened, root))

    assert exc_info.value.chain is ChainVerification.NOT_ATTENUATED
    assert "may only ever narrow" in str(exc_info.value)


def test_a_child_widening_its_capabilities_is_refused(issuer, revocation) -> None:
    root = _root(issuer, capability_set=["VIEWER"])
    widened = issuer.forge(
        vaid_id="99999999-9999-4999-8999-999999999999",
        tenant_id=TENANT_A,
        capability_set=["VIEWER", "TENANT_ADMIN"],
        scope_prefixes=[PROJECT_SCOPE],
        parent=root,
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(widened, root))

    assert exc_info.value.chain is ChainVerification.NOT_ATTENUATED


def test_a_mid_chain_widening_is_refused_even_with_an_untouched_leaf(
    issuer, revocation
) -> None:
    """Every hop is checked independently: a leaf that attenuates its
    own (forged, widened) parent correctly is still refused, because the
    hop above it does not."""

    root = _root(issuer, capability_set=["VIEWER"], scope_prefixes=[f"{PROJECT_SCOPE}.estate"])
    widened_middle = issuer.forge(
        vaid_id="99999999-9999-4999-8999-999999999999",
        tenant_id=TENANT_A,
        capability_set=["VIEWER"],
        scope_prefixes=["cairn"],
        parent=root,
    )
    honest_leaf = issuer.mint_child(
        widened_middle, capability_set=["VIEWER"], scope_prefixes=["cairn.other-tenant"]
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(
            _present(honest_leaf, widened_middle, root)
        )

    assert exc_info.value.chain is ChainVerification.NOT_ATTENUATED


def test_a_cross_tenant_child_is_refused(issuer, revocation) -> None:
    """Tenant is one of the axes authority narrows along: a child
    naming a different tenant than its parent is not a narrowing, it is
    a different tenant's data."""

    root = _root(issuer)
    cross_tenant = issuer.forge(
        vaid_id="99999999-9999-4999-8999-999999999999",
        tenant_id=TENANT_B,
        capability_set=["VIEWER"],
        scope_prefixes=[PROJECT_SCOPE],
        parent=root,
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        _authenticator(issuer, revocation).verify(_present(cross_tenant, root))

    assert exc_info.value.chain is ChainVerification.NOT_ATTENUATED


# -- scope can only shrink: against the credential behind it ----------


def test_a_vaid_narrower_than_its_backing_principal_is_accepted(issuer, revocation) -> None:
    root = _root(issuer, capability_set=["VIEWER"])
    backing = Principal(
        subject="user-1",
        tenant_id=TenantId(TENANT_A),
        roles=(Role.TENANT_ADMIN, Role.VIEWER),
    )

    verified = _authenticator(issuer, revocation).verify(
        _present(root), backing_principal=backing
    )

    assert verified.principal.roles == (Role.VIEWER,)
    assert Role.TENANT_ADMIN not in verified.principal.roles


def test_a_vaid_claiming_a_role_its_backing_principal_lacks_is_refused(
    issuer, revocation
) -> None:
    """Scope can only shrink, relative to the authority behind the VAID
    as well as inside the VAID's own chain: a perfectly valid VAID is
    still refused when the token presented with it does not hold what
    the VAID claims."""

    root = _root(issuer, capability_set=["TENANT_ADMIN"])
    backing = Principal(
        subject="user-1", tenant_id=TenantId(TENANT_A), roles=(Role.VIEWER,)
    )

    with pytest.raises(VaidScopeWideningError) as exc_info:
        _authenticator(issuer, revocation).verify(
            _present(root), backing_principal=backing
        )

    assert "TENANT_ADMIN" in str(exc_info.value)
    assert "never widen it" in str(exc_info.value)


def test_a_vaid_naming_a_different_tenant_than_its_backing_principal_is_refused(
    issuer, revocation
) -> None:
    root = _root(issuer, tenant_id=TENANT_A)
    backing = Principal(
        subject="user-1", tenant_id=TenantId(TENANT_B), roles=(Role.VIEWER, Role.ARCHITECT)
    )

    with pytest.raises(TenantScopeViolationError) as exc_info:
        _authenticator(issuer, revocation).verify(
            _present(root), backing_principal=backing
        )

    assert TENANT_A in str(exc_info.value)
    assert TENANT_B in str(exc_info.value)


# -- trust anchors and selection --------------------------------------


def test_trust_anchors_refuse_an_empty_key_set() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        VaidTrustAnchors(kernel_public_keys=(), trust_domains=frozenset({"cairn.test"}))

    assert "verifies nothing" in str(exc_info.value)


def test_trust_anchors_refuse_an_empty_trust_domain_set(issuer) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        VaidTrustAnchors(
            kernel_public_keys=(issuer.kernel_public_key,), trust_domains=frozenset()
        )

    assert "not globally meaningful" in str(exc_info.value)


def test_trust_anchors_refuse_a_key_that_is_not_an_ed25519_public_key() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        VaidTrustAnchors(
            kernel_public_keys=(b"too-short",), trust_domains=frozenset({"cairn.test"})
        )

    assert "32 raw bytes" in str(exc_info.value)


def test_vaid_is_off_by_default(revocation) -> None:
    """A clean clone and ``make test`` accept no VAID at all; callers
    presenting a bearer token are unaffected."""

    assert resolve_vaid_authenticator(revocation, {}) is None
    assert resolve_vaid_authenticator(revocation, {ENV_VAID_ENABLED: "false"}) is None


def test_vaid_enabled_without_trust_anchors_fails_at_startup(revocation) -> None:
    """Enabled-but-unconfigured is a startup failure, never an
    authenticator with nothing pinned."""

    with pytest.raises(ConfigurationError) as exc_info:
        resolve_vaid_authenticator(revocation, {ENV_VAID_ENABLED: "true"})

    assert ENV_VAID_KERNEL_KEYS in str(exc_info.value)


def test_vaid_enabled_with_anchors_resolves_an_authenticator_that_verifies(
    issuer, revocation
) -> None:
    import base64

    encoded = base64.urlsafe_b64encode(issuer.kernel_public_key).decode().rstrip("=")
    authenticator = resolve_vaid_authenticator(
        revocation,
        {
            ENV_VAID_ENABLED: "true",
            ENV_VAID_KERNEL_KEYS: encoded,
            ENV_VAID_TRUST_DOMAINS: issuer.trust_domain,
        },
    )

    assert authenticator is not None
    verified = authenticator.verify(_present(_root(issuer)))
    assert verified.principal.tenant_id == TenantId(TENANT_A)


def test_an_unrecognised_enabled_value_is_rejected(revocation) -> None:
    with pytest.raises(ConfigurationError):
        resolve_vaid_authenticator(revocation, {ENV_VAID_ENABLED: "maybe"})
