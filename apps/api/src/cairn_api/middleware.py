import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from cairn_kernel.errors import CairnError, UnauthenticatedError
from cairn_kernel.security import Principal, sign_tenant_assertion
from cairn_kernel.tenancy import TenantContext, tenant_scope

from cairn_api.errors import send_problem

Scope = dict[str, Any]
Message = dict[str, Any]
App = Callable[
    [Scope, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]],
    Awaitable[None],
]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _bearer_token(scope: Scope) -> str:
    authorization = _header(scope, b"authorization")
    if authorization is None:
        raise UnauthenticatedError("missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthenticatedError("authorization header must use the Bearer scheme")
    return token.strip()


class AuthMiddleware:
    def __init__(
        self,
        app: App,
        authenticator: Any,
        *,
        assertion_secret: bytes,
        assertion_ttl: timedelta = timedelta(minutes=5),
        public_paths: Iterable[str] = (),
    ) -> None:
        self._app = app
        self._authenticator = authenticator
        self._assertion_secret = assertion_secret
        self._assertion_ttl = assertion_ttl
        self._public_paths = frozenset(public_paths)

    async def __call__(
        self,
        scope: Scope,
        receive: Callable[[], Awaitable[Message]],
        send: Callable[[Message], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or scope.get("path") in self._public_paths:
            await self._app(scope, receive, send)
            return

        correlation_id = _header(scope, b"x-correlation-id") or str(uuid.uuid4())
        try:
            principal: Principal = self._authenticator.verify(_bearer_token(scope))
        except CairnError as error:
            await send_problem(scope, send, error, correlation_id)
            return

        state = scope.setdefault("state", {})
        state["principal"] = principal
        state["correlation_id"] = correlation_id
        state["tenant_assertion"] = sign_tenant_assertion(
            secret=self._assertion_secret,
            tenant_id=principal.tenant_id,
            actor_id=principal.subject,
            expires_at=datetime.now(UTC) + self._assertion_ttl,
        )
        context = TenantContext(
            tenant_id=principal.tenant_id,
            project_id=None,
            actor_id=principal.subject,
            actor_roles=principal.role_values(),
            correlation_id=correlation_id,
        )
        with tenant_scope(context):
            await self._app(scope, receive, send)


class CairnErrorMiddleware:
    def __init__(self, app: App) -> None:
        self._app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Callable[[], Awaitable[Message]],
        send: Callable[[Message], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        try:
            await self._app(scope, receive, send)
        except CairnError as error:
            correlation_id = scope.get("state", {}).get("correlation_id") or str(uuid.uuid4())
            await send_problem(scope, send, error, correlation_id)
