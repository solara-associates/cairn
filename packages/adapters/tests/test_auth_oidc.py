from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import UnauthenticatedError
from cairn_kernel.security import Role

SECRET = "test-secret-that-is-long-enough-for-hs256"
TENANT = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-api"


def _settings(**overrides: object) -> OidcSettings:
    values: dict[str, object] = {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "algorithms": ("HS256",),
        "secret": SECRET,
    }
    values.update(overrides)
    return OidcSettings(**values)  # type: ignore[arg-type]


def _token(**claims: object) -> str:
    issued = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": "user-1",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(minutes=5)).timestamp()),
        "tenant_id": TENANT,
        "roles": ["ENGINEER", "VIEWER"],
    }
    payload.update(claims)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_valid_token_maps_to_a_principal() -> None:
    principal = JwtAuthenticator(_settings()).verify(_token(email="user@example.test"))
    assert principal.subject == "user-1"
    assert principal.tenant_id.value == TENANT
    assert principal.roles == (Role.ENGINEER, Role.VIEWER)
    assert principal.email == "user@example.test"


def test_unknown_roles_are_ignored_and_duplicates_collapse() -> None:
    token = _token(roles=["ENGINEER", "PLATFORM_OPERATOR", "ENGINEER", "AUDITOR"])
    principal = JwtAuthenticator(_settings()).verify(token)
    assert principal.roles == (Role.ENGINEER, Role.AUDITOR)


def test_missing_roles_claim_yields_no_roles() -> None:
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": 0,
            "exp": 4102444800,
            "tenant_id": TENANT,
        },
        SECRET,
        algorithm="HS256",
    )
    principal = JwtAuthenticator(_settings()).verify(token)
    assert principal.roles == ()


def test_tenant_claim_is_canonicalised() -> None:
    token = _token(tenant_id=TENANT.upper())
    principal = JwtAuthenticator(_settings()).verify(token)
    assert principal.tenant_id.value == TENANT


def test_expired_token_is_rejected() -> None:
    issued = datetime.now(UTC) - timedelta(hours=1)
    token = _token(iat=int(issued.timestamp()), exp=int(issued.timestamp()) + 60)
    with pytest.raises(UnauthenticatedError, match="invalid token"):
        JwtAuthenticator(_settings()).verify(token)


def test_wrong_audience_is_rejected() -> None:
    with pytest.raises(UnauthenticatedError, match="invalid token"):
        JwtAuthenticator(_settings()).verify(_token(aud="another-api"))


def test_wrong_issuer_is_rejected() -> None:
    with pytest.raises(UnauthenticatedError, match="invalid token"):
        JwtAuthenticator(_settings()).verify(_token(iss="https://evil.example.test"))


def test_token_signed_with_another_secret_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": 0,
            "exp": 4102444800,
            "tenant_id": TENANT,
        },
        "different-secret-that-is-also-long-enough",
        algorithm="HS256",
    )
    with pytest.raises(UnauthenticatedError, match="invalid token"):
        JwtAuthenticator(_settings()).verify(forged)


def test_missing_subject_is_rejected() -> None:
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": 0,
            "exp": 4102444800,
            "tenant_id": TENANT,
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(UnauthenticatedError, match="invalid token"):
        JwtAuthenticator(_settings()).verify(token)


def test_missing_tenant_claim_is_rejected() -> None:
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": 0,
            "exp": 4102444800,
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(UnauthenticatedError, match="tenant claim"):
        JwtAuthenticator(_settings()).verify(token)


def test_non_uuid_tenant_claim_is_rejected() -> None:
    with pytest.raises(UnauthenticatedError, match="not a uuid"):
        JwtAuthenticator(_settings()).verify(_token(tenant_id="tenant-a"))


def test_empty_token_is_rejected() -> None:
    with pytest.raises(UnauthenticatedError, match="missing bearer token"):
        JwtAuthenticator(_settings()).verify("")


def test_settings_require_exactly_one_key_source() -> None:
    with pytest.raises(ValueError, match="exactly one of jwks_url or secret"):
        OidcSettings(issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(ValueError, match="exactly one of jwks_url or secret"):
        OidcSettings(
            issuer=ISSUER,
            audience=AUDIENCE,
            secret=SECRET,
            jwks_url="https://issuer.example.test/jwks.json",
        )
