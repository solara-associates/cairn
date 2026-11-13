import os
import secrets
import uuid
from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_kernel.errors import CairnError, UnauthenticatedError
from cairn_kernel.security import Principal
from cairn_modules.projects import InMemoryProjectRepository, ProjectRepository, ProjectService
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cairn_api.errors import problem_from_error
from cairn_api.middleware import AuthMiddleware, CairnErrorMiddleware
from cairn_api.routes_projects import register_projects_routes

ReadinessProbe = Callable[[], Mapping[str, bool]]

_PUBLIC_PATHS = frozenset({"/healthz", "/readyz"})


def _service_version() -> str:
    try:
        return version("cairn-api")
    except PackageNotFoundError:
        return "0.1.0"


def _run_probe(probe: ReadinessProbe) -> dict[str, bool]:
    try:
        return {str(name): bool(ok) for name, ok in probe().items()}
    except Exception:  # noqa: BLE001 - readiness must fail closed on any probe error
        return {"readiness_probe": False}


class _ClosedAuthenticator:
    """Fails closed: authenticates nothing until OIDC settings are configured."""

    def verify(self, token: str) -> Principal:
        raise UnauthenticatedError("authentication is not configured")


def _default_authenticator() -> JwtAuthenticator | _ClosedAuthenticator:
    issuer = os.environ.get("CAIRN_OIDC_ISSUER")
    audience = os.environ.get("CAIRN_OIDC_AUDIENCE")
    secret = os.environ.get("CAIRN_OIDC_SECRET")
    jwks_url = os.environ.get("CAIRN_OIDC_JWKS_URL")
    if not issuer or not audience or not (secret or jwks_url):
        return _ClosedAuthenticator()
    algorithms = ("HS256",) if secret else ("RS256",)
    return JwtAuthenticator(
        OidcSettings(
            issuer=issuer,
            audience=audience,
            algorithms=algorithms,
            secret=secret,
            jwks_url=jwks_url,
        )
    )


def _default_assertion_secret() -> bytes:
    configured = os.environ.get("CAIRN_TENANT_ASSERTION_SECRET")
    if configured:
        return configured.encode()
    # No production secret configured: mint a process-local secret so the
    # service still starts. It only has to be stable within this process's
    # lifetime (it signs an internal, short-lived tenant assertion), never
    # across restarts.
    return secrets.token_bytes(32)


async def _cairn_error_handler(request: Request, exc: CairnError) -> JSONResponse:
    correlation_id = (
        getattr(request.state, "correlation_id", None)
        or request.headers.get("x-correlation-id")
        or str(uuid.uuid4())
    )
    problem = problem_from_error(exc, instance=request.url.path, trace_id=correlation_id)
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
        headers={"x-correlation-id": correlation_id},
    )


def create_app(
    *,
    readiness: ReadinessProbe | None = None,
    project_repository: ProjectRepository | None = None,
    authenticator: Any | None = None,
    assertion_secret: bytes | None = None,
) -> FastAPI:
    service_version = _service_version()
    probe = readiness or (dict)
    app = FastAPI(title="CAIRN API", version=service_version)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "api", "version": service_version}

    @app.get("/readyz", response_model=None)
    def readyz() -> dict[str, Any] | JSONResponse:
        checks = _run_probe(probe)
        if not all(checks.values()):
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": "api",
                    "version": service_version,
                    "checks": checks,
                },
            )
        return {
            "status": "ready",
            "service": "api",
            "version": service_version,
            "checks": checks,
        }

    service = ProjectService(project_repository or InMemoryProjectRepository())
    register_projects_routes(app, service)

    app.add_exception_handler(CairnError, _cairn_error_handler)
    app.add_middleware(
        AuthMiddleware,
        authenticator or _default_authenticator(),
        assertion_secret=assertion_secret or _default_assertion_secret(),
        public_paths=_PUBLIC_PATHS,
    )
    app.add_middleware(CairnErrorMiddleware)

    return app


__all__ = ["ReadinessProbe", "create_app"]
