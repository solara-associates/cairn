import hashlib
import hmac
import os
import secrets
import uuid
from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_contracts.finops import PriceListRelease
from cairn_contracts.posture import ControlCatalogueRelease
from cairn_kernel.errors import CairnError, UnauthenticatedError
from cairn_kernel.evidence import FAKE_ALGORITHM, EvidenceSigner
from cairn_kernel.outbox import InMemoryOutboxStore, OutboxStore
from cairn_kernel.security import AuditSink, InMemoryAuditSink, Principal
from cairn_modules.assessment import AssessmentService, CheckpointStore, InMemoryCheckpointStore
from cairn_modules.connections import ConnectionRegistry
from cairn_modules.finops import load_price_list_release
from cairn_modules.posture import load_control_catalogue_release
from cairn_modules.projects import InMemoryProjectRepository, ProjectRepository, ProjectService
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cairn_api.errors import problem_from_error
from cairn_api.middleware import AuthMiddleware, CairnErrorMiddleware
from cairn_api.routes_assessment import register_assessment_routes
from cairn_api.routes_connections import register_connections_routes
from cairn_api.routes_projects import register_projects_routes

ReadinessProbe = Callable[[], Mapping[str, bool]]

_PUBLIC_PATHS = frozenset({"/healthz", "/readyz"})

# This monorepo has no separate packaging/distribution story yet for
# seed data (controls/, pricing/) -- these resolve relative to the repo
# root, same as the test suite's own fixtures. Revisit once a packaged
# deployment needs its own copy.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _default_control_catalogue() -> ControlCatalogueRelease:
    return load_control_catalogue_release(_REPO_ROOT / "controls" / "gcp-cis-seed.yaml")


def _default_price_list() -> PriceListRelease:
    return load_price_list_release(_REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml")


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


class _LocalEvidenceSigner:
    """Default console-wiring evidence signer.

    No real KMS adapter exists yet (``cairn_adapters.evidence_kms`` is a
    docstring stub -- R4/R5 scope); this mints a process-local HMAC key,
    the same shape as ``_default_assertion_secret`` below, so the
    evidence-package route still works without a cloud account. It
    signs with the same ``FAKE_ALGORITHM`` R0-11's own fake/test signer
    uses, so a chain sealed by this process verifies with
    ``cairn_kernel.evidence.verify`` the same way, but it is explicitly
    not a production signing key -- it does not survive a restart.
    """

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)
        self._key_id = f"local-evidence-key-{uuid.uuid4()}"

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def algorithm(self) -> str:
        return FAKE_ALGORITHM

    def sign(self, payload: bytes) -> bytes:
        return hmac.new(self._key, payload, hashlib.sha256).digest()


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
    assessment_checkpoint_store: CheckpointStore | None = None,
    assessment_outbox: OutboxStore | None = None,
    control_catalogue: ControlCatalogueRelease | None = None,
    price_list: PriceListRelease | None = None,
    connection_registry: ConnectionRegistry | None = None,
    audit_sink: AuditSink | None = None,
    evidence_signer: EvidenceSigner | None = None,
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

    sink = audit_sink or InMemoryAuditSink()

    assessment_service = AssessmentService(
        checkpoint_store=assessment_checkpoint_store or InMemoryCheckpointStore(),
        outbox=assessment_outbox or InMemoryOutboxStore(),
    )
    register_assessment_routes(
        app,
        service=assessment_service,
        control_catalogue=control_catalogue or _default_control_catalogue(),
        price_list=price_list or _default_price_list(),
        audit_sink=sink,
        evidence_signer=evidence_signer or _LocalEvidenceSigner(),
    )

    register_connections_routes(
        app, registry=connection_registry or ConnectionRegistry(audit_sink=sink)
    )

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
