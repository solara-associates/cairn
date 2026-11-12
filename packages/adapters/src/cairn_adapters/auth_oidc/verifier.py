import uuid
from dataclasses import dataclass

import jwt
from cairn_kernel.errors import UnauthenticatedError
from cairn_kernel.hex import TenantId
from cairn_kernel.security import Principal, Role, role_from_claim


@dataclass(frozen=True, slots=True)
class OidcSettings:
    issuer: str
    audience: str
    algorithms: tuple[str, ...] = ("RS256",)
    jwks_url: str | None = None
    secret: str | None = None
    tenant_claim: str = "tenant_id"
    roles_claim: str = "roles"
    email_claim: str = "email"

    def __post_init__(self) -> None:
        if (self.jwks_url is None) == (self.secret is None):
            raise ValueError("configure exactly one of jwks_url or secret")
        if not self.algorithms:
            raise ValueError("at least one signing algorithm is required")


class JwtAuthenticator:
    def __init__(self, settings: OidcSettings) -> None:
        self._settings = settings
        self._jwks_client = (
            jwt.PyJWKClient(settings.jwks_url) if settings.jwks_url is not None else None
        )

    def verify(self, token: str) -> Principal:
        if not token:
            raise UnauthenticatedError("missing bearer token")
        claims = self._decode(token)
        return self._principal_from_claims(claims)

    def _decode(self, token: str) -> dict[str, object]:
        settings = self._settings
        try:
            key: object
            if self._jwks_client is not None:
                key = self._jwks_client.get_signing_key_from_jwt(token).key
            else:
                key = settings.secret
            return jwt.decode(
                token,
                key,
                algorithms=list(settings.algorithms),
                audience=settings.audience,
                issuer=settings.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise UnauthenticatedError(f"invalid token: {exc}") from exc

    def _principal_from_claims(self, claims: dict[str, object]) -> Principal:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise UnauthenticatedError("token is missing a subject")
        tenant_id = self._tenant_from_claims(claims)
        roles = self._roles_from_claims(claims)
        email = claims.get(self._settings.email_claim)
        return Principal(
            subject=subject,
            tenant_id=tenant_id,
            roles=roles,
            email=email if isinstance(email, str) else None,
        )

    def _tenant_from_claims(self, claims: dict[str, object]) -> TenantId:
        raw = claims.get(self._settings.tenant_claim)
        if not isinstance(raw, str) or not raw:
            raise UnauthenticatedError("token is missing a tenant claim")
        try:
            return TenantId(str(uuid.UUID(raw)))
        except ValueError as exc:
            raise UnauthenticatedError("token tenant claim is not a uuid") from exc

    def _roles_from_claims(self, claims: dict[str, object]) -> tuple[Role, ...]:
        raw = claims.get(self._settings.roles_claim)
        if not isinstance(raw, list):
            return ()
        roles: list[Role] = []
        for value in raw:
            if isinstance(value, str):
                role = role_from_claim(value)
                if role is not None and role not in roles:
                    roles.append(role)
        return tuple(roles)
