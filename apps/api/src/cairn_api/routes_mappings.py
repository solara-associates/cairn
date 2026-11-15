"""R2-01: the mapping registry HTTP routes (spec 9.2's `/v1/mappings*` rows,
9.3's "Resolve mapping" contract).

Delegates to ``cairn_modules.mappings.MappingService``, which enforces
tenant roles (``cairn_kernel.security.require_roles``) for ``resolve``/
``proposals``. ``:publish`` is gated by ``cairn_api.security.
require_platform_operator`` instead -- PLATFORM_OPERATOR (spec 12.1) is
"not a tenant role and not reachable from tenant APIs", so this route
never resolves a tenant ``Principal`` via the local ``get_principal``
every other route in this file uses.
"""

from __future__ import annotations

from datetime import datetime

from cairn_contracts.mapping import MappingRelease
from cairn_kernel.errors import UnauthenticatedError
from cairn_kernel.security import Principal
from cairn_modules.mappings import MappingReleaseRecord, MappingService, ResolvedMapping
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from cairn_api.security import require_platform_operator


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


class ResolveMappingRequest(BaseModel):
    mapping_version: str
    source_provider: str
    source_service: str
    target_provider: str
    region: str | None = None


class _EndpointRef(BaseModel):
    provider: str
    service: str


class ResolveMappingResponse(BaseModel):
    source: _EndpointRef
    target: _EndpointRef
    equivalence: str
    caveat: str | None
    region_supported: bool
    mapping_version: str
    evidence: str

    @classmethod
    def from_domain(cls, resolved: ResolvedMapping) -> ResolveMappingResponse:
        return cls(
            source=_EndpointRef(provider=resolved.source_provider, service=resolved.source_service),
            target=_EndpointRef(
                provider=resolved.target_provider, service=resolved.target_service or ""
            ),
            equivalence=resolved.equivalence.value,
            caveat=resolved.caveat,
            region_supported=resolved.region_supported,
            mapping_version=resolved.mapping_version,
            evidence=resolved.evidence,
        )


class ProposeMappingRequest(BaseModel):
    release: MappingRelease
    rationale: str


class PublishMappingRequest(BaseModel):
    content_hash: str
    rationale: str = ""


class MappingReviewResponse(BaseModel):
    from_status: str | None
    to_status: str
    actor_id: str
    rationale: str
    occurred_at: datetime


class MappingReleaseResponse(BaseModel):
    version: str
    status: str
    content_hash: str
    released_at: datetime
    reviews: list[MappingReviewResponse]

    @classmethod
    def from_domain(cls, record: MappingReleaseRecord) -> MappingReleaseResponse:
        return cls(
            version=record.version,
            status=record.status.value,
            content_hash=record.content_hash,
            released_at=record.release.released_at,
            reviews=[
                MappingReviewResponse(
                    from_status=review.from_status.value if review.from_status else None,
                    to_status=review.to_status.value,
                    actor_id=review.actor_id,
                    rationale=review.rationale,
                    occurred_at=review.occurred_at,
                )
                for review in record.reviews
            ],
        )


def register_mapping_routes(app: FastAPI, *, service: MappingService) -> None:
    """Register the R2-01 mapping-registry routes directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.
    """
    router = app

    @router.get("/v1/mappings", response_model=list[MappingReleaseResponse])
    def list_mappings(principal: Principal = Depends(get_principal)) -> list[MappingReleaseResponse]:
        return [
            MappingReleaseResponse.from_domain(record)
            for record in service.list_releases(principal)
        ]

    @router.get("/v1/mappings/{version}", response_model=MappingReleaseResponse)
    def get_mapping(
        version: str, principal: Principal = Depends(get_principal)
    ) -> MappingReleaseResponse:
        return MappingReleaseResponse.from_domain(service.get_release(principal, version))

    @router.post("/v1/mappings/resolve", response_model=ResolveMappingResponse)
    def resolve_mapping_route(
        payload: ResolveMappingRequest, principal: Principal = Depends(get_principal)
    ) -> ResolveMappingResponse:
        resolved = service.resolve(
            principal,
            mapping_version=payload.mapping_version,
            source_provider=payload.source_provider,
            source_service=payload.source_service,
            target_provider=payload.target_provider,
            region=payload.region,
        )
        return ResolveMappingResponse.from_domain(resolved)

    @router.post(
        "/v1/mappings/proposals", response_model=MappingReleaseResponse, status_code=201
    )
    def propose_mapping(
        payload: ProposeMappingRequest, principal: Principal = Depends(get_principal)
    ) -> MappingReleaseResponse:
        record = service.propose(principal, release=payload.release, rationale=payload.rationale)
        return MappingReleaseResponse.from_domain(record)

    @router.post("/v1/mappings/{version}:publish", response_model=MappingReleaseResponse)
    def publish_mapping(
        version: str,
        payload: PublishMappingRequest,
        principal: Principal = Depends(require_platform_operator),
    ) -> MappingReleaseResponse:
        record = service.publish(
            principal,
            version=version,
            content_hash=payload.content_hash,
            rationale=payload.rationale,
        )
        return MappingReleaseResponse.from_domain(record)


__all__ = ["get_principal", "register_mapping_routes"]
