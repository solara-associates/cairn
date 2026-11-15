"""R2-01 application service: RBAC-gated use cases over a
``MappingRepository``, plus the R1-23 outbox publish for the two state
changes spec 11.2's ``cairn.mapping`` topic names.

Role requirements (spec 12.1):

- resolving/reading releases (Class A) requires any granted tenant role --
  an authenticated principal always carries at least one, same as
  ``cairn_modules.projects.ProjectService.READ_ROLES``.
- proposing a mapping change (Class B, tenant-scoped) requires
  ``TENANT_ADMIN`` or ``ARCHITECT`` -- spec 12.1 lists "propose mappings"
  as a capability of both roles.
- publishing (Class B, platform-level) carries **no** ``require_roles``
  check here at all: PLATFORM_OPERATOR gating already happened at the HTTP
  layer (``cairn_api.security.require_platform_operator``) before this
  method is ever reached. Spec 12.1 is explicit that PLATFORM_OPERATOR is
  "not a tenant role and not reachable from tenant APIs" -- ``Role``/
  ``TENANT_ROLES`` play no part in it, by design.

``review``/``retire`` are not exposed over HTTP in this story (spec 9.2's
endpoint table lists no route for either) -- callers exercise them
directly against the ``MappingRepository``, not through this service.
"""

from __future__ import annotations

from cairn_contracts.events.model import EventEnvelope, OperationClass
from cairn_contracts.mapping import MappingRelease
from cairn_kernel.hex.ports import Clock, IdGenerator, SystemClock, UuidIdGenerator
from cairn_kernel.outbox import OutboxMessage, OutboxStore
from cairn_kernel.security import Principal, Role, require_roles

from cairn_modules.mappings.domain import MappingReleaseRecord
from cairn_modules.mappings.ports import MappingRepository
from cairn_modules.mappings.resolver import ResolvedMapping, resolve_mapping

PROPOSE_ROLES: tuple[Role, ...] = (Role.TENANT_ADMIN, Role.ARCHITECT)
READ_ROLES: tuple[Role, ...] = tuple(Role)

# mapping.release.published.v1 is global, platform-operated data (spec 8.1)
# with no owning tenant -- but OutboxMessage.tenant_id must be non-blank
# (cairn_kernel.outbox.model.OutboxMessage.__post_init__). This sentinel
# marks a global event in the outbox; it is never a real tenant_id and
# never compared against one (EventEnvelope.tenant_id for this event is
# None, not this sentinel -- see ``publish`` below).
GLOBAL_OUTBOX_TENANT = "GLOBAL"


class MappingService:
    def __init__(
        self,
        repository: MappingRepository,
        *,
        outbox: OutboxStore,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._outbox = outbox
        self._clock = clock or SystemClock()
        self._ids = id_generator or UuidIdGenerator()

    def resolve(
        self,
        principal: Principal,
        *,
        mapping_version: str,
        source_provider: str,
        source_service: str,
        target_provider: str,
        region: str | None = None,
    ) -> ResolvedMapping:
        require_roles(principal, *READ_ROLES)
        release = self._repository.get_published(mapping_version)
        return resolve_mapping(
            release,
            source_provider=source_provider,
            source_service=source_service,
            target_provider=target_provider,
            region=region,
        )

    def get_release(self, principal: Principal, version: str) -> MappingReleaseRecord:
        require_roles(principal, *READ_ROLES)
        return self._repository.get(version)

    def list_releases(self, principal: Principal) -> tuple[MappingReleaseRecord, ...]:
        require_roles(principal, *READ_ROLES)
        return self._repository.list_releases()

    def propose(
        self, principal: Principal, *, release: MappingRelease, rationale: str
    ) -> MappingReleaseRecord:
        require_roles(principal, *PROPOSE_ROLES)
        message_id = self._ids.new_id()
        occurred_at = self._clock.now()
        envelope = EventEnvelope(
            event_id=message_id,
            event_type="mapping.proposed.v1",
            event_version=1,
            tenant_id=principal.tenant_id.value,
            project_id=None,
            operation_class=OperationClass.WORKSPACE_MUTATION,
            occurred_at=occurred_at,
            correlation_id=message_id,
            causation_id=None,
            producer="mapping-service",
            payload={
                "version": release.version,
                "proposer_actor_id": principal.subject,
                "rationale": rationale,
            },
            evidence_ref=None,
        )
        message = OutboxMessage(
            message_id=message_id,
            tenant_id=principal.tenant_id.value,
            project_id=None,
            event_type=envelope.event_type,
            payload=envelope.model_dump(mode="json"),
            created_at=occurred_at,
        )
        records: list[MappingReleaseRecord] = []

        def _effect() -> None:
            records.append(
                self._repository.propose(
                    release,
                    tenant_id=principal.tenant_id.value,
                    proposer_actor_id=principal.subject,
                    rationale=rationale,
                )
            )

        self._outbox.enqueue_with_effect(message, effect=_effect)
        return records[0]

    def publish(
        self, principal: Principal, *, version: str, content_hash: str, rationale: str = ""
    ) -> MappingReleaseRecord:
        # Peek first: a no-op (already PUBLISHED, matching hash) or a
        # failure (already PUBLISHED, mismatched hash) is not a state
        # transition either way, so neither warrants a fresh
        # mapping.release.published.v1 event -- this short-circuits before
        # ever touching the outbox. ``self._repository.publish`` makes
        # the identical check again below; this one only decides whether
        # an event is due.
        current = self._repository.get(version)
        if current.is_published:
            return self._repository.publish(
                version, content_hash=content_hash, actor_id=principal.subject, rationale=rationale
            )

        message_id = self._ids.new_id()
        occurred_at = self._clock.now()
        envelope = EventEnvelope(
            event_id=message_id,
            event_type="mapping.release.published.v1",
            event_version=1,
            tenant_id=None,
            project_id=None,
            operation_class=OperationClass.WORKSPACE_MUTATION,
            occurred_at=occurred_at,
            correlation_id=message_id,
            causation_id=None,
            producer="mapping-service",
            payload={"version": version, "actor_id": principal.subject, "rationale": rationale},
            evidence_ref=None,
        )
        message = OutboxMessage(
            message_id=message_id,
            tenant_id=GLOBAL_OUTBOX_TENANT,
            project_id=None,
            event_type=envelope.event_type,
            payload=envelope.model_dump(mode="json"),
            created_at=occurred_at,
        )
        records: list[MappingReleaseRecord] = []

        def _effect() -> None:
            records.append(
                self._repository.publish(
                    version,
                    content_hash=content_hash,
                    actor_id=principal.subject,
                    rationale=rationale,
                )
            )

        self._outbox.enqueue_with_effect(message, effect=_effect)
        return records[0]


__all__ = ["GLOBAL_OUTBOX_TENANT", "PROPOSE_ROLES", "READ_ROLES", "MappingService"]
