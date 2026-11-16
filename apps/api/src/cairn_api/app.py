import hashlib
import hmac
import os
import secrets
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_adapters.diagram_drawio import DrawioXmlDiagramRenderer
from cairn_adapters.evidence_kms import KmsEvidenceSigner, KmsKeyVersion
from cairn_adapters.iac_terraform import TerraformHclGenerator
from cairn_adapters.source_git import ArchiveLoader, CompositeSourceAdapter, UploadSourceAdapter
from cairn_adapters.transform_core.subprocess_adapter import (
    SubprocessTransformationPort,
    TransformCliUnavailableError,
)
from cairn_adapters.validation_deps import DependencyValidationAdapter
from cairn_adapters.validation_static.subprocess_adapter import (
    StaticValidationAdapter,
    ValidatorCliUnavailableError,
)
from cairn_adapters.validation_tests import TestSuiteValidationAdapter
from cairn_contracts.finops import PriceListRelease
from cairn_contracts.mapping import MappingRelease
from cairn_contracts.mapping.pattern import PatternCatalogueRelease
from cairn_contracts.posture import ControlCatalogueRelease
from cairn_kernel.errors import CairnError, UnauthenticatedError
from cairn_kernel.evidence import FAKE_ALGORITHM, EvidenceSigner
from cairn_kernel.outbox import InMemoryOutboxStore, OutboxStore
from cairn_kernel.security import AuditSink, InMemoryAuditSink, Principal
from cairn_modules.assessment import AssessmentService, CheckpointStore, InMemoryCheckpointStore
from cairn_modules.connections import ConnectionRegistry
from cairn_modules.design import load_pattern_catalogue
from cairn_modules.finops import load_price_list_release
from cairn_modules.mappings import FakeMappingRepository, MappingRepository, MappingService
from cairn_modules.mappings.seed import load_mapping_release
from cairn_modules.posture import load_control_catalogue_release
from cairn_modules.projects import InMemoryProjectRepository, ProjectRepository, ProjectService
from cairn_modules.transformation.engine import TransformationPort
from cairn_modules.transformation.runs import (
    FakeTransformationRunRepository,
    TransformationRunRepository,
)
from cairn_modules.transformation.source import RepositorySourcePort
from cairn_modules.transformation.validation import ValidationPort, ValidationRequest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cairn_api.errors import problem_from_error
from cairn_api.middleware import AuthMiddleware, CairnErrorMiddleware
from cairn_api.routes_approval_console import PlanApprovalRegistry, register_approval_console_routes
from cairn_api.routes_assessment import register_assessment_routes
from cairn_api.routes_connections import register_connections_routes
from cairn_api.routes_design import DesignRegistry, register_design_routes
from cairn_api.routes_mappings import register_mapping_routes
from cairn_api.routes_projects import register_projects_routes
from cairn_api.routes_transformations import TransformationRegistry, register_transformation_routes

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


def _default_pattern_catalogue() -> PatternCatalogueRelease:
    return load_pattern_catalogue(
        _REPO_ROOT / "patterns",
        version="2026.11.1",
        released_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


def _default_mapping_release() -> MappingRelease:
    return load_mapping_release(_REPO_ROOT / "mappings" / "service-map.yaml")


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
    # Overridable because not every OIDC provider puts the tenant/role
    # claims under CAIRN's own default names -- a provider's own claim
    # mapping rules usually make this unnecessary in production, but
    # the bundled local dex quickstart (see docs/identity.md) needs it
    # pointed at whatever claim it actually populates.
    tenant_claim = os.environ.get("CAIRN_OIDC_TENANT_CLAIM", "tenant_id")
    roles_claim = os.environ.get("CAIRN_OIDC_ROLES_CLAIM", "roles")
    return JwtAuthenticator(
        OidcSettings(
            issuer=issuer,
            audience=audience,
            algorithms=algorithms,
            secret=secret,
            jwks_url=jwks_url,
            tenant_claim=tenant_claim,
            roles_claim=roles_claim,
        )
    )


class _LocalEvidenceSigner:
    """Fallback evidence signer for tests, CI and any deployment without a
    configured KMS key.

    Mints a process-local HMAC key, the same shape as
    ``_default_assertion_secret`` below, so the evidence-package route
    still works without a cloud account. It signs with the same
    ``FAKE_ALGORITHM`` R0-11's own fake/test signer uses, so a chain
    sealed by this process verifies with ``cairn_kernel.evidence.verify``
    the same way, but it is explicitly not a production signing key -- it
    does not survive a restart. ``_default_evidence_signer`` below prefers
    a real KMS-backed signer (``cairn_adapters.evidence_kms``) whenever one
    is configured.
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


def _default_evidence_signer() -> EvidenceSigner:
    project_id = os.environ.get("CAIRN_KMS_PROJECT_ID")
    location = os.environ.get("CAIRN_KMS_LOCATION")
    key_ring = os.environ.get("CAIRN_KMS_KEY_RING")
    key_name = os.environ.get("CAIRN_KMS_KEY_NAME")
    if not (project_id and location and key_ring and key_name):
        return _LocalEvidenceSigner()
    key_version = KmsKeyVersion(
        project_id=project_id,
        location=location,
        key_ring=key_ring,
        key_name=key_name,
        key_version=os.environ.get("CAIRN_KMS_KEY_VERSION", "1"),
    )
    return KmsEvidenceSigner(key_version)


class _ClosedTransformationPort:
    """Fails closed: no ``cairn-transform-cli`` binary is configured or
    built yet in this process. Mirrors ``_ClosedAuthenticator`` above --
    the app still starts (route discovery, OpenAPI schema generation
    and every other route's tests must not depend on this binary
    existing), and the failure only surfaces if a caller actually tries
    to run a transformation."""

    def transform(self, files: Any) -> Any:
        raise TransformCliUnavailableError(
            "cairn-transform-cli is not configured or built in this process; "
            "set CAIRN_TRANSFORM_CLI_BIN or run "
            "`cargo build --release -p cairn-transform-cli` first"
        )


def _default_transformation_port() -> TransformationPort:
    try:
        return SubprocessTransformationPort()
    except TransformCliUnavailableError:
        return _ClosedTransformationPort()


class _ClosedStaticValidationAdapter:
    """Fails closed: no ``cairn-transform-validator-cli`` binary is
    configured or built yet in this process. Mirrors
    ``_ClosedTransformationPort`` above -- the app still starts, and the
    failure only surfaces if a caller actually asks for validation."""

    def validate(self, request: ValidationRequest) -> Any:
        raise ValidatorCliUnavailableError(
            "cairn-transform-validator-cli is not configured or built in this process; "
            "set CAIRN_TRANSFORM_VALIDATOR_CLI_BIN or run "
            "`cargo build --release -p cairn-transform-validator` first"
        )


def _default_validation_checks() -> tuple[ValidationPort, ...]:
    """729/R3-05's three configured ``ValidationPort`` checks, in the
    order ``cairn_modules.transformation.validation.run_validation``
    reports them: static (fails closed the same way
    ``_default_transformation_port`` does if its Rust binary is not
    built), the repo's own declared test suite, and the dependency-
    manifest check (neither of the latter two depends on a compiled
    binary, so both are always constructible)."""

    try:
        static_check: ValidationPort = StaticValidationAdapter()
    except ValidatorCliUnavailableError:
        static_check = _ClosedStaticValidationAdapter()
    return (static_check, TestSuiteValidationAdapter(), DependencyValidationAdapter())


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
    mapping_repository: MappingRepository | None = None,
    mapping_outbox: OutboxStore | None = None,
    design_registry: DesignRegistry | None = None,
    pattern_catalogue: PatternCatalogueRelease | None = None,
    design_mapping_release: MappingRelease | None = None,
    transformation_registry: TransformationRegistry | None = None,
    transformation_source_port: RepositorySourcePort | None = None,
    transformation_archive_loader: ArchiveLoader | None = None,
    transformation_port: TransformationPort | None = None,
    transformation_run_repository: TransformationRunRepository | None = None,
    transformation_validation_checks: tuple[ValidationPort, ...] | None = None,
    approval_console_registry: PlanApprovalRegistry | None = None,
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
    resolved_evidence_signer = evidence_signer or _default_evidence_signer()

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
        evidence_signer=resolved_evidence_signer,
    )

    register_connections_routes(
        app, registry=connection_registry or ConnectionRegistry(audit_sink=sink)
    )

    mapping_service = MappingService(
        mapping_repository or FakeMappingRepository(),
        outbox=mapping_outbox or InMemoryOutboxStore(),
    )
    register_mapping_routes(app, service=mapping_service)

    resolved_design_registry = design_registry or DesignRegistry()
    register_design_routes(
        app,
        registry=resolved_design_registry,
        pattern_catalogue=pattern_catalogue or _default_pattern_catalogue(),
        mapping_release=design_mapping_release or _default_mapping_release(),
        diagram_renderer=DrawioXmlDiagramRenderer(),
        iac_generator=TerraformHclGenerator(),
    )

    register_approval_console_routes(
        app,
        registry=approval_console_registry or PlanApprovalRegistry(),
        design_registry=resolved_design_registry,
    )

    register_transformation_routes(
        app,
        registry=transformation_registry or TransformationRegistry(),
        source_port=transformation_source_port
        or CompositeSourceAdapter(
            upload_adapter=UploadSourceAdapter(transformation_archive_loader)
            if transformation_archive_loader is not None
            else None
        ),
        transformation_port=transformation_port or _default_transformation_port(),
        run_repository=transformation_run_repository or FakeTransformationRunRepository(),
        evidence_signer=resolved_evidence_signer,
        validation_checks=transformation_validation_checks
        if transformation_validation_checks is not None
        else _default_validation_checks(),
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
