"""R1-05: a read-only GCP inventory adapter.

Walks a connected project's regions and resources through a
``GcpHttpClient`` (R0-13's adapter port, satisfied here for ``INVENTORY``
only), with rate limiting and retry on every call to the GCP API client.

ADR-010 / R1-02: before collecting anything, the adapter refuses to run
unless the connection is read-only-scoped. It does this by asking the
R1-02 ``ConnectionRegistry`` to ``validate()`` the connection, acting as
that connection's ``ProviderScopeValidator`` itself -- the adapter never
issues anything but read calls, so a reachable probe is read-only by
construction. A revoked, unknown, or non-read-only connection raises before
a single inventory call is made.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cairn_contracts.estate import FactStatus, Provenance, Resource
from cairn_kernel.errors import ProviderUnavailableError, ValidationError
from cairn_modules.connections.ports import ScopeCheckResult
from cairn_modules.connections.service import ConnectionRegistry

from cairn_adapters.provider_core.ports import (
    CoverageReport,
    InventoryPage,
    InventoryRequest,
    ProviderCapability,
    ProviderConnection,
    ProviderDescriptor,
)
from cairn_adapters.provider_gcp.client import (
    GcpHttpClient,
    RateLimiter,
    RetryConfig,
    call_with_retry,
)

PROVIDER = "gcp"
PARSER_VERSION = "r1-05-gcp-inventory-1"
_MAX_GCP_PAGES = 1_000


@dataclass(frozen=True, slots=True)
class GcpInventoryAdapter:
    """Implements R0-13's ``InventorySourcePort`` for GCP, read-only."""

    client: GcpHttpClient
    registry: ConnectionRegistry
    rate_limiter: RateLimiter
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider=PROVIDER,
            display_name="Google Cloud Platform",
            capabilities=frozenset({ProviderCapability.INVENTORY}),
        )

    def read_inventory(self, request: InventoryRequest) -> InventoryPage:
        connection = request.connection
        if connection.provider != PROVIDER:
            raise ValidationError(
                f"connection provider {connection.provider} is not {PROVIDER}"
            )
        self._refuse_unless_read_only(connection)

        services = set(request.services)
        resources = self._collect_resources(connection, services=services)
        page, next_cursor = _offset_page(resources, request.cursor, request.page_size)
        observed = tuple(sorted({resource.service for resource in resources}))
        skipped = tuple(
            sorted(service for service in services if service not in observed)
        )
        return InventoryPage(
            resources=page,
            next_cursor=next_cursor,
            coverage=CoverageReport(
                observed_services=observed, skipped_services=skipped
            ),
            observed_at=self.clock(),
        )

    def _refuse_unless_read_only(self, connection: ProviderConnection) -> None:
        # Raises NotFoundError (unknown connection), ValidationError (already
        # revoked), ForbiddenError (not read-only), or ProviderUnavailableError
        # (probe unreachable) -- any of which refuses the collection.
        self.registry.validate(connection.connection_id, validator=self)

    def check_scope(
        self, *, provider: str, account_id: str, credential_ref: str
    ) -> ScopeCheckResult:
        """Implements ``ProviderScopeValidator`` for the registry's own
        validate() call. This adapter only ever issues read ("list"/"get")
        calls, so a reachable probe is read-only by construction."""

        if provider != PROVIDER:
            return ScopeCheckResult(
                read_only=True, reachable=False, detail=f"not a {PROVIDER} connection"
            )
        try:
            response = call_with_retry(
                lambda: self.client.get(f"/v1/projects/{account_id}"),
                rate_limiter=self.rate_limiter,
                retry_config=self.retry_config,
            )
        except ProviderUnavailableError as exc:
            return ScopeCheckResult(read_only=True, reachable=False, detail=str(exc))
        if response.status_code != 200:
            return ScopeCheckResult(
                read_only=True,
                reachable=False,
                detail=f"project probe returned status {response.status_code}",
            )
        return ScopeCheckResult(read_only=True, reachable=True)

    def _collect_resources(
        self, connection: ProviderConnection, *, services: set[str]
    ) -> tuple[Resource, ...]:
        project_id = connection.account_id
        self._fetch_project(project_id)
        regions = self._list_regions(project_id)
        resources: list[Resource] = []
        for region in regions:
            resources.extend(
                self._list_resources(connection, project_id, region, services)
            )
        return tuple(sorted(resources, key=lambda resource: resource.resource_id))

    def _get(self, path: str, *, params: dict[str, str] | None = None):
        return call_with_retry(
            lambda: self.client.get(path, params=params),
            rate_limiter=self.rate_limiter,
            retry_config=self.retry_config,
        )

    def _fetch_project(self, project_id: str) -> None:
        response = self._get(f"/v1/projects/{project_id}")
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"gcp project {project_id} could not be read"
                f" (status {response.status_code})"
            )

    def _list_regions(self, project_id: str) -> tuple[str, ...]:
        response = self._get(f"/compute/v1/projects/{project_id}/regions")
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"gcp regions for project {project_id} could not be read"
                f" (status {response.status_code})"
            )
        items = response.body.get("items", [])
        return tuple(str(item["name"]) for item in items)  # type: ignore[union-attr]

    def _list_resources(
        self,
        connection: ProviderConnection,
        project_id: str,
        region: str,
        services: set[str],
    ) -> list[Resource]:
        resources: list[Resource] = []
        page_token: str | None = None
        for _ in range(_MAX_GCP_PAGES):
            params = {"pageToken": page_token} if page_token else None
            response = self._get(
                f"/compute/v1/projects/{project_id}/regions/{region}/resources",
                params=params,
            )
            if response.status_code != 200:
                raise ProviderUnavailableError(
                    f"gcp resources for {project_id}/{region} could not be read"
                    f" (status {response.status_code})"
                )
            for item in response.body.get("items", []):  # type: ignore[union-attr]
                resource = _to_resource(connection, region, item)  # type: ignore[arg-type]
                if not services or resource.service in services:
                    resources.append(resource)
            next_token = response.body.get("nextPageToken")  # type: ignore[union-attr]
            if not next_token:
                return resources
            page_token = str(next_token)
        raise ProviderUnavailableError(
            f"gcp resource pagination for {project_id}/{region} did not terminate"
        )


def _to_resource(
    connection: ProviderConnection, region: str, item: dict[str, object]
) -> Resource:
    resource_id = str(item["id"])
    observed_at = datetime.now(UTC)
    return Resource(
        resource_id=resource_id,
        tenant_id=connection.tenant_id,
        project_id=connection.project_id,
        provider=PROVIDER,
        account_id=connection.account_id,
        region=region,
        service=str(item["service"]),
        resource_type=str(item["resourceType"]),
        native_id=str(item.get("nativeId", resource_id)),
        name=str(item["name"]) if item.get("name") is not None else None,
        tags={str(k): str(v) for k, v in dict(item.get("tags") or {}).items()},
        facts={},
        provenance=(
            Provenance(
                source_system=PROVIDER,
                source_id=resource_id,
                source_version=None,
                observed_at=observed_at,
                ingested_at=observed_at,
                parser_version=PARSER_VERSION,
                ingest_run_id=connection.connection_id,
                raw_ref=f"gcp://{connection.account_id}/{region}/{resource_id}",
            ),
        ),
        status=FactStatus.OBSERVED,
    )


def _offset_page(
    items: Sequence[Resource], cursor: str | None, page_size: int
) -> tuple[tuple[Resource, ...], str | None]:
    if cursor is None:
        offset = 0
    else:
        try:
            offset = int(cursor)
        except ValueError as exc:
            raise ValidationError("gcp inventory cursor is not valid") from exc
        if offset < 0 or offset > len(items):
            raise ValidationError("gcp inventory cursor is out of range")
    page = tuple(items[offset : offset + page_size])
    end = offset + len(page)
    next_cursor = None if end >= len(items) else str(end)
    return page, next_cursor


__all__ = ["GcpInventoryAdapter"]
