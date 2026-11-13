"""Transactional outbox dispatcher (R1-23).

Reads pending outbox messages and publishes them, marking a message
delivered only after a confirmed publish (``EventPublisher.publish`` returns
without raising). A message that fails ``max_attempts`` times is
dead-lettered. Dead-letter replay is tenant-scoped (ADR-012): a cross-tenant
replay attempt is rejected and audited via the R0-10 audit sink, never
silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cairn_kernel.errors import TenantScopeViolationError
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.hex.ports import Clock
from cairn_kernel.outbox.model import OutboxMessage, OutboxStatus
from cairn_kernel.outbox.ports import EventPublisher, OutboxPublishError, OutboxStore
from cairn_kernel.security.audit import AuditEntry, AuditSink

DEFAULT_MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class DispatchReport:
    dispatched: list[str] = field(default_factory=list)
    retrying: list[str] = field(default_factory=list)
    dead_lettered: list[str] = field(default_factory=list)


class OutboxDispatcher:
    def __init__(
        self,
        *,
        store: OutboxStore,
        publisher: EventPublisher,
        audit_sink: AuditSink,
        clock: Clock,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._audit = audit_sink
        self._clock = clock
        self._max_attempts = max_attempts

    def dispatch_pending(self, *, limit: int = 100) -> DispatchReport:
        report = DispatchReport()
        for message in self._store.claim_pending(limit=limit):
            self._dispatch_one(message, report)
        return report

    def _dispatch_one(self, message: OutboxMessage, report: DispatchReport) -> None:
        try:
            self._publisher.publish(message)
        except OutboxPublishError:
            updated = self._store.record_failure(
                message.message_id, at=self._clock.now(), max_attempts=self._max_attempts
            )
            if updated.status is OutboxStatus.DEAD_LETTERED:
                self._audit.append(self._dead_letter_entry(updated))
                report.dead_lettered.append(updated.message_id)
            else:
                report.retrying.append(updated.message_id)
            return
        self._store.mark_dispatched(message.message_id, at=self._clock.now())
        report.dispatched.append(message.message_id)

    def replay_dead_letter(
        self, message_id: str, *, tenant_id: str, actor: str
    ) -> OutboxMessage:
        message = self._store.get(message_id)
        owning_tenant = message.tenant_id if message is not None else tenant_id
        owning_project = message.project_id if message is not None else None
        try:
            replayed = self._store.replay(message_id, tenant_id=tenant_id)
        except TenantScopeViolationError:
            self._audit.append(
                AuditEntry(
                    tenant_id=TenantId(owning_tenant),
                    project_id=_project_id(owning_project),
                    actor=actor,
                    action="outbox.dead_letter.replay_denied_cross_tenant",
                    operation_class=OperationClass.WORKSPACE_MUTATION,
                    payload={
                        "message_id": message_id,
                        "requested_by_tenant_id": tenant_id,
                        "owning_tenant_id": owning_tenant,
                    },
                )
            )
            raise
        self._audit.append(
            AuditEntry(
                tenant_id=TenantId(replayed.tenant_id),
                project_id=_project_id(replayed.project_id),
                actor=actor,
                action="outbox.dead_letter.replayed",
                operation_class=OperationClass.WORKSPACE_MUTATION,
                payload={"message_id": message_id, "event_type": replayed.event_type},
            )
        )
        return replayed

    def _dead_letter_entry(self, message: OutboxMessage) -> AuditEntry:
        return AuditEntry(
            tenant_id=TenantId(message.tenant_id),
            project_id=_project_id(message.project_id),
            actor="outbox-dispatcher",
            action="outbox.message.dead_lettered",
            operation_class=OperationClass.WORKSPACE_MUTATION,
            payload={
                "message_id": message.message_id,
                "event_type": message.event_type,
                "attempts": message.attempts,
            },
        )


def _project_id(project_id: str | None) -> ProjectId | None:
    return ProjectId(project_id) if project_id is not None else None
