import asyncio
from datetime import UTC, datetime, timedelta

import jwt
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_api import AuthMiddleware, CairnErrorMiddleware

_SECRET = b"test-assertion-secret"
from cairn_kernel.security import Role, require_roles
from cairn_kernel.tenancy import current_tenant_context, has_tenant_context

SECRET = "test-secret-that-is-long-enough-for-hs256"
TENANT = "6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a"
ISSUER = "https://issuer.example.test"
AUDIENCE = "cairn-api"


def _authenticator() -> JwtAuthenticator:
    return JwtAuthenticator(
        OidcSettings(
            issuer=ISSUER,
            audience=AUDIENCE,
            algorithms=("HS256",),
            secret=SECRET,
        )
    )


def _token(*, roles: list[str] | None = None, tenant_id: str = TENANT) -> str:
    issued = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(issued.timestamp()),
            "exp": int((issued + timedelta(minutes=5)).timestamp()),
            "tenant_id": tenant_id,
            "roles": ["VIEWER"] if roles is None else roles,
        },
        SECRET,
        algorithm="HS256",
    )


def _scope(path: str = "/v1/me", headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "state": {},
    }


def _call(app, scope: dict) -> list[dict]:
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    return messages


def _json_body(messages: list[dict]) -> dict:
    import json

    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return json.loads(body)


def _response_status(messages: list[dict]) -> int:
    starts = [message for message in messages if message["type"] == "http.response.start"]
    return starts[0]["status"]


def _response_headers(messages: list[dict]) -> dict[bytes, bytes]:
    starts = [message for message in messages if message["type"] == "http.response.start"]
    return dict(starts[0]["headers"])


async def _echo_principal(scope: dict, receive, send) -> None:
    principal = scope["state"]["principal"]
    context = current_tenant_context()
    assert context.tenant_id == principal.tenant_id
    assert context.actor_id == principal.subject
    assert context.actor_roles == principal.role_values()
    body = {"subject": principal.subject, "tenant": context.tenant_id.value}.__repr__().encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


def test_missing_authorization_header_is_rejected() -> None:
    app = AuthMiddleware(_echo_principal, _authenticator(), assertion_secret=_SECRET)
    messages = _call(app, _scope())
    assert _response_status(messages) == 401
    headers = _response_headers(messages)
    assert headers[b"content-type"] == b"application/problem+json"
    problem = _json_body(messages)
    assert problem["code"] == "UNAUTHENTICATED"
    assert problem["status"] == 401
    assert problem["instance"] == "/v1/me"
    assert problem["trace_id"] == headers[b"x-correlation-id"].decode()


def test_non_bearer_scheme_is_rejected() -> None:
    app = AuthMiddleware(_echo_principal, _authenticator(), assertion_secret=_SECRET)
    messages = _call(app, _scope(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")]))
    assert _response_status(messages) == 401


def test_invalid_token_is_rejected() -> None:
    app = AuthMiddleware(_echo_principal, _authenticator(), assertion_secret=_SECRET)
    messages = _call(app, _scope(headers=[(b"authorization", b"Bearer not-a-jwt")]))
    assert _response_status(messages) == 401
    assert _json_body(messages)["code"] == "UNAUTHENTICATED"


def test_valid_token_authenticates_and_binds_tenant_context() -> None:
    app = AuthMiddleware(_echo_principal, _authenticator(), assertion_secret=_SECRET)
    scope = _scope(headers=[(b"authorization", f"Bearer {_token()}".encode())])
    messages = _call(app, scope)
    assert _response_status(messages) == 200
    assert scope["state"]["principal"].subject == "user-1"
    assert not has_tenant_context()


def test_correlation_id_is_propagated_from_the_request() -> None:
    app = AuthMiddleware(_echo_principal, _authenticator(), assertion_secret=_SECRET)
    scope = _scope(
        headers=[
            (b"authorization", f"Bearer {_token()}".encode()),
            (b"x-correlation-id", b"corr-123"),
        ]
    )
    messages = _call(app, scope)
    assert _response_status(messages) == 200
    assert scope["state"]["correlation_id"] == "corr-123"


def test_public_paths_bypass_authentication() -> None:
    async def health(scope: dict, receive, send) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = AuthMiddleware(health, _authenticator(), assertion_secret=_SECRET, public_paths={"/healthz"})
    assert _response_status(_call(app, _scope("/healthz"))) == 204
    assert _response_status(_call(app, _scope("/v1/me"))) == 401


def test_authorization_denial_becomes_a_problem_response() -> None:
    async def guarded(scope: dict, receive, send) -> None:
        require_roles(scope["state"]["principal"], Role.ENGINEER)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = CairnErrorMiddleware(AuthMiddleware(guarded, _authenticator(), assertion_secret=_SECRET))
    scope = _scope(headers=[(b"authorization", f"Bearer {_token(roles=['VIEWER'])}".encode())])
    messages = _call(app, scope)
    assert _response_status(messages) == 403
    problem = _json_body(messages)
    assert problem["code"] == "FORBIDDEN"
    assert "ENGINEER" in problem["detail"]


def test_authorized_request_passes_rbac() -> None:
    async def guarded(scope: dict, receive, send) -> None:
        require_roles(scope["state"]["principal"], Role.ENGINEER)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = CairnErrorMiddleware(AuthMiddleware(guarded, _authenticator(), assertion_secret=_SECRET))
    scope = _scope(headers=[(b"authorization", f"Bearer {_token(roles=['ENGINEER'])}".encode())])
    assert _response_status(_call(app, scope)) == 200


def test_tenant_context_is_not_leaked_between_requests() -> None:
    app = AuthMiddleware(_echo_principal, _authenticator(), assertion_secret=_SECRET)
    other_tenant = "1b1b1b1b-2c2c-4d4d-8e8e-3f3f3f3f3f3f"
    first = _scope(headers=[(b"authorization", f"Bearer {_token()}".encode())])
    second = _scope(
        headers=[(b"authorization", f"Bearer {_token(tenant_id=other_tenant)}".encode())]
    )
    assert _response_status(_call(app, first)) == 200
    assert _response_status(_call(app, second)) == 200
    assert first["state"]["principal"].tenant_id.value == TENANT
    assert second["state"]["principal"].tenant_id.value == other_tenant
    assert not has_tenant_context()
