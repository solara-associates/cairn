"""`_default_authenticator` wires `cairn_api.app`'s OIDC settings from
`CAIRN_OIDC_*` environment variables -- the path a real deployment (or
the bundled local dex quickstart, see docs/identity.md) actually uses,
as opposed to the explicit `authenticator=` override every other test
in this directory passes to `create_app`."""

from __future__ import annotations

import jwt
import pytest
from cairn_api.app import _ClosedAuthenticator, _default_authenticator
from cairn_kernel.errors import UnauthenticatedError

SECRET = "test-secret-that-is-long-enough-for-hs256"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-console"
TENANT = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CAIRN_OIDC_ISSUER",
        "CAIRN_OIDC_AUDIENCE",
        "CAIRN_OIDC_SECRET",
        "CAIRN_OIDC_JWKS_URL",
        "CAIRN_OIDC_TENANT_CLAIM",
        "CAIRN_OIDC_ROLES_CLAIM",
    ):
        monkeypatch.delenv(name, raising=False)


def test_unconfigured_env_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    assert isinstance(_default_authenticator(), _ClosedAuthenticator)


def test_default_claim_names_match_prior_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("CAIRN_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("CAIRN_OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("CAIRN_OIDC_SECRET", SECRET)
    authenticator = _default_authenticator()

    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": 0,
            "exp": 9_999_999_999,
            "tenant_id": TENANT,
            "roles": ["VIEWER"],
        },
        SECRET,
        algorithm="HS256",
    )
    principal = authenticator.verify(token)
    assert principal.tenant_id.value == TENANT
    assert principal.role_values() == ("VIEWER",)


def test_tenant_and_roles_claim_names_are_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bundled local dex quickstart (docs/identity.md) has no
    `tenant_id`/`roles` claims -- it carries the tenant in `name` and
    roles in `groups`. Without this override, every sign-in through it
    would fail with a missing-tenant-claim error."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("CAIRN_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("CAIRN_OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("CAIRN_OIDC_SECRET", SECRET)
    monkeypatch.setenv("CAIRN_OIDC_TENANT_CLAIM", "name")
    monkeypatch.setenv("CAIRN_OIDC_ROLES_CLAIM", "groups")
    authenticator = _default_authenticator()

    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": 0,
            "exp": 9_999_999_999,
            "name": TENANT,
            "groups": ["ENGINEER"],
        },
        SECRET,
        algorithm="HS256",
    )
    principal = authenticator.verify(token)
    assert principal.tenant_id.value == TENANT
    assert principal.role_values() == ("ENGINEER",)

    # The default claim names are no longer present, so they must not
    # be read even though this token happens to lack them too -- this
    # proves the override, not just a lenient fallback.
    with pytest.raises(UnauthenticatedError):
        authenticator.verify(
            jwt.encode(
                {
                    "sub": "user-2",
                    "iss": ISSUER,
                    "aud": AUDIENCE,
                    "iat": 0,
                    "exp": 9_999_999_999,
                    "tenant_id": TENANT,
                },
                SECRET,
                algorithm="HS256",
            )
        )
