"""ADR-020 §3: a caller may present a VAID at the MCP gateway, and the
narrowed principal it derives is enforced by the same path a bearer
token's already is.

The point every test here makes, in one form or another: the gateway's
*ordering* guarantee is unchanged. A VAID is verified at the one
``authenticate`` step, and a refused VAID raises before ``authorize``
and therefore before ``McpRegistry.lookup``/``invoke`` -- so the
counting fixture server's call list stays empty, exactly as it already
does for a refused token.

The second point, made by the tenant tests at the bottom: the
bounded-context servers know nothing about VAIDs. They enforce ADR-020
§2 against whatever ``Principal`` they are handed, which is why a VAID
cannot become a route around a tenant check.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import (
    ForbiddenError,
    TenantScopeViolationError,
    UnauthenticatedError,
)
from cairn_kernel.security import Principal, Role
from cairn_kernel.testing import VaidTestIssuer
from cairn_kernel.vaid import (
    VAID_SUBJECT_PREFIX,
    VaidAuthenticator,
    VaidPresentation,
    VaidScopeWideningError,
    VaidTrustAnchors,
    VaidVerificationError,
)
from cairn_kits.mcp import BoundedContextServer, McpRegistry, ToolCapability
from cairn_mcp_gateway import McpGateway
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from vaid_mint import InMemoryRevocationList

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"
TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
PROJECT_SCOPE = "cairn.project-1"
TOOL = "fixture.read_only_thing"


def _settings() -> OidcSettings:
    return OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)


def _token(*, roles: tuple[str, ...] = (), tenant_id: str = TENANT_A) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_id": tenant_id,
            "roles": list(roles),
        },
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def vaid_issuer() -> VaidTestIssuer:
    return VaidTestIssuer()


@pytest.fixture
def revocation() -> InMemoryRevocationList:
    return InMemoryRevocationList().assume_nothing_revoked()


def _build(
    vaid_issuer: VaidTestIssuer | None,
    revocation: InMemoryRevocationList,
) -> tuple[McpGateway, list[Principal]]:
    """A gateway over one counting fixture tool requiring ``AUDITOR``.

    The fixture records the ``Principal`` it was handed, not only that
    it ran -- what matters is *which* principal reached the handle, since
    that is the one ADR-020 §2's tenant checks will see.
    """

    seen: list[Principal] = []

    def handle(name: str, arguments: dict, principal: Principal) -> object:
        del name, arguments
        seen.append(principal)
        return {"ok": True}

    registry = McpRegistry()
    registry.register(
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=(TOOL,),
            capabilities={TOOL: ToolCapability.READ},
            handle=handle,
        )
    )
    vaid_authenticator = (
        None
        if vaid_issuer is None
        else VaidAuthenticator(
            VaidTrustAnchors(
                kernel_public_keys=(vaid_issuer.kernel_public_key,),
                trust_domains=frozenset({vaid_issuer.trust_domain}),
            ),
            revocation,
        )
    )
    gateway = McpGateway(
        authenticator=JwtAuthenticator(_settings()),
        registry=registry,
        required_roles={TOOL: Role.AUDITOR},
        vaid_authenticator=vaid_authenticator,
    )
    return gateway, seen


def _present(leaf: dict[str, object], *ancestors: dict[str, object]) -> VaidPresentation:
    return VaidPresentation(
        document=json.dumps(leaf),
        lineage=tuple(json.dumps(ancestor) for ancestor in ancestors),
    )


def _root(
    vaid_issuer: VaidTestIssuer,
    *,
    tenant_id: str = TENANT_A,
    capability_set: list[str] | None = None,
    scope_prefixes: list[str] | None = None,
) -> dict[str, object]:
    return vaid_issuer.mint_root(
        tenant_id=tenant_id,
        capability_set=capability_set if capability_set is not None else ["AUDITOR"],
        scope_prefixes=scope_prefixes if scope_prefixes is not None else [PROJECT_SCOPE],
    )


# -- a VAID authenticates, and authorizes, like a token ---------------


def test_a_valid_vaid_reaches_the_registered_tool(vaid_issuer, revocation) -> None:
    gateway, seen = _build(vaid_issuer, revocation)
    root = _root(vaid_issuer)

    result = gateway.call_tool(TOOL, vaid=_present(root), arguments={"x": 1})

    assert result == {"ok": True}
    assert len(seen) == 1
    assert seen[0].subject == f"{VAID_SUBJECT_PREFIX}{root['agent_id']}"
    assert seen[0].tenant_id.value == TENANT_A
    assert seen[0].roles == (Role.AUDITOR,)


def test_a_vaid_still_has_to_satisfy_the_tools_required_role(vaid_issuer, revocation) -> None:
    """A VAID authenticates; it does not authorize. The role check is the
    same one, run against the principal the VAID derived."""

    gateway, seen = _build(vaid_issuer, revocation)
    under_scoped = _root(vaid_issuer, capability_set=["VIEWER"])

    with pytest.raises(ForbiddenError) as exc_info:
        gateway.call_tool(TOOL, vaid=_present(under_scoped))

    assert "AUDITOR" in str(exc_info.value)
    assert seen == []


def test_a_delegated_vaid_is_authorized_on_its_narrowed_roles_not_its_parents(
    vaid_issuer, revocation
) -> None:
    """The case the whole decision exists for: a wide root delegates a
    narrow child, and the gateway authorizes the child's authority. The
    root would have passed this tool's role check; the child must not."""

    gateway, seen = _build(vaid_issuer, revocation)
    root = _root(vaid_issuer, capability_set=["AUDITOR", "VIEWER"])
    child = vaid_issuer.mint_child(
        root, capability_set=["VIEWER"], scope_prefixes=[f"{PROJECT_SCOPE}.estate"]
    )

    assert gateway.call_tool(TOOL, vaid=_present(root)) == {"ok": True}

    with pytest.raises(ForbiddenError):
        gateway.call_tool(TOOL, vaid=_present(child, root))

    assert len(seen) == 1


# -- refusals, all of them before the registry ------------------------


@pytest.mark.parametrize(
    ("case", "expected_fragment"),
    [
        ("expired", "EXPIRED"),
        ("wrong_signature", "INAUTHENTIC"),
        ("revoked", "REVOKED"),
        ("unparseable", "not a VAID"),
    ],
)
def test_a_refused_vaid_never_reaches_the_registry(
    vaid_issuer, revocation, case: str, expected_fragment: str
) -> None:
    if case == "expired":
        vaid_issuer = VaidTestIssuer(vaid_ttl_hours=0)
    gateway, seen = _build(vaid_issuer, revocation)

    if case == "unparseable":
        presentation = VaidPresentation(document="{}")
    elif case == "wrong_signature":
        presentation = _present(
            vaid_issuer.forge(
                vaid_id=str(uuid.uuid4()),
                tenant_id=TENANT_A,
                capability_set=["AUDITOR"],
                scope_prefixes=[PROJECT_SCOPE],
                signing_key=Ed25519PrivateKey.generate(),
            )
        )
    else:
        root = _root(vaid_issuer)
        if case == "revoked":
            revocation.revoke(str(root["vaid_id"]))
        presentation = _present(root)

    with pytest.raises(VaidVerificationError) as exc_info:
        gateway.call_tool(TOOL, vaid=presentation)

    assert expected_fragment in str(exc_info.value)
    assert seen == []


def test_a_scope_widening_vaid_is_refused_before_the_registry(vaid_issuer, revocation) -> None:
    """Forged, so individually authentic, and still refused: the gateway
    recomputes containment at every hop."""

    gateway, seen = _build(vaid_issuer, revocation)
    root = _root(vaid_issuer, scope_prefixes=[f"{PROJECT_SCOPE}.estate"])
    widened = vaid_issuer.forge(
        vaid_id=str(uuid.uuid4()),
        tenant_id=TENANT_A,
        capability_set=["AUDITOR"],
        scope_prefixes=["cairn"],
        parent=root,
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        gateway.call_tool(TOOL, vaid=_present(widened, root))

    assert "may only ever narrow" in str(exc_info.value)
    assert seen == []


def test_a_cross_tenant_delegation_is_refused_before_the_registry(
    vaid_issuer, revocation
) -> None:
    gateway, seen = _build(vaid_issuer, revocation)
    root = _root(vaid_issuer, tenant_id=TENANT_A)
    cross_tenant = vaid_issuer.forge(
        vaid_id=str(uuid.uuid4()),
        tenant_id=TENANT_B,
        capability_set=["AUDITOR"],
        scope_prefixes=[PROJECT_SCOPE],
        parent=root,
    )

    with pytest.raises(VaidVerificationError) as exc_info:
        gateway.call_tool(TOOL, vaid=_present(cross_tenant, root))

    assert "narrow" in str(exc_info.value)
    assert seen == []


def test_a_vaid_presented_to_a_deployment_that_accepts_none_is_refused(
    vaid_issuer, revocation
) -> None:
    """The default (``CAIRN_VAID_ENABLED`` unset) binds no VAID
    authenticator. A presented VAID is then refused because there is no
    pinned anchor to check it against -- never accepted unverified."""

    gateway, seen = _build(None, revocation)

    with pytest.raises(VaidVerificationError) as exc_info:
        gateway.call_tool(TOOL, vaid=_present(_root(vaid_issuer)))

    assert "accepts none" in str(exc_info.value)
    assert seen == []


# -- a token alongside a VAID: scope can only shrink ------------------


def test_a_vaid_narrower_than_its_bearer_token_is_accepted(vaid_issuer, revocation) -> None:
    gateway, seen = _build(vaid_issuer, revocation)
    root = _root(vaid_issuer, capability_set=["AUDITOR"])
    token = _token(roles=(Role.TENANT_ADMIN.value, Role.AUDITOR.value))

    assert gateway.call_tool(TOOL, token, vaid=_present(root)) == {"ok": True}
    assert seen[0].roles == (Role.AUDITOR,)
    assert Role.TENANT_ADMIN not in seen[0].roles


def test_a_vaid_claiming_more_than_its_bearer_token_is_refused(vaid_issuer, revocation) -> None:
    gateway, seen = _build(vaid_issuer, revocation)
    root = _root(vaid_issuer, capability_set=["TENANT_ADMIN"])
    token = _token(roles=(Role.VIEWER.value,))

    with pytest.raises(VaidScopeWideningError):
        gateway.call_tool(TOOL, token, vaid=_present(root))

    assert seen == []


def test_a_vaid_for_another_tenant_than_its_bearer_token_is_refused(
    vaid_issuer, revocation
) -> None:
    gateway, seen = _build(vaid_issuer, revocation)
    root = _root(vaid_issuer, tenant_id=TENANT_A)
    token = _token(roles=(Role.AUDITOR.value,), tenant_id=TENANT_B)

    with pytest.raises(TenantScopeViolationError):
        gateway.call_tool(TOOL, token, vaid=_present(root))

    assert seen == []


def test_an_invalid_bearer_token_is_refused_even_with_a_valid_vaid(
    vaid_issuer, revocation
) -> None:
    """A VAID presented *in addition to* a token does not rescue a bad
    token: the token is verified first, and a credential this gateway
    cannot verify is a refusal, not something to fall back from."""

    gateway, seen = _build(vaid_issuer, revocation)

    with pytest.raises(UnauthenticatedError):
        gateway.call_tool(TOOL, "not-a-real-jwt", vaid=_present(_root(vaid_issuer)))

    assert seen == []


# -- callers without a VAID are untouched -----------------------------


def test_a_bearer_token_alone_behaves_exactly_as_before(vaid_issuer, revocation) -> None:
    gateway, seen = _build(vaid_issuer, revocation)

    assert gateway.call_tool(TOOL, _token(roles=(Role.AUDITOR.value,))) == {"ok": True}
    assert seen[0].subject == "user-1"
    assert not seen[0].subject.startswith(VAID_SUBJECT_PREFIX)


def test_presenting_no_credential_at_all_is_refused(vaid_issuer, revocation) -> None:
    gateway, seen = _build(vaid_issuer, revocation)

    with pytest.raises(UnauthenticatedError):
        gateway.call_tool(TOOL)

    assert seen == []


# -- the servers do not know a VAID exists ----------------------------


def test_a_vaid_cannot_reach_another_tenants_data(vaid_issuer, revocation) -> None:
    """ADR-020 §2 and §3 meeting: the bounded-context server enforces
    tenant scope against the principal it is handed and has no idea a
    VAID produced it, so a VAID for tenant B is refused by the same
    check that refuses a *token* for tenant B."""

    def handle(name: str, arguments: dict, principal: Principal) -> object:
        del name
        if arguments["tenant_id"] != principal.tenant_id.value:
            raise TenantScopeViolationError(
                f"resource belongs to tenant {arguments['tenant_id']}, caller is"
                f" authenticated for {principal.tenant_id.value}"
            )
        return {"ok": True}

    registry = McpRegistry()
    registry.register(
        BoundedContextServer(
            context_id="fixture",
            name="fixture",
            tools=(TOOL,),
            capabilities={TOOL: ToolCapability.READ},
            handle=handle,
        )
    )
    gateway = McpGateway(
        authenticator=JwtAuthenticator(_settings()),
        registry=registry,
        required_roles={TOOL: Role.AUDITOR},
        vaid_authenticator=VaidAuthenticator(
            VaidTrustAnchors(
                kernel_public_keys=(vaid_issuer.kernel_public_key,),
                trust_domains=frozenset({vaid_issuer.trust_domain}),
            ),
            revocation,
        ),
    )
    tenant_b_vaid = _present(_root(vaid_issuer, tenant_id=TENANT_B))

    assert gateway.call_tool(
        TOOL, vaid=_present(_root(vaid_issuer, tenant_id=TENANT_A)), arguments={"tenant_id": TENANT_A}
    ) == {"ok": True}

    with pytest.raises(TenantScopeViolationError) as exc_info:
        gateway.call_tool(TOOL, vaid=tenant_b_vaid, arguments={"tenant_id": TENANT_A})

    assert TENANT_B in str(exc_info.value)
