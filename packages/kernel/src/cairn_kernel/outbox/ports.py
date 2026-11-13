"""Ports for the transactional outbox dispatcher (R1-23).

``OutboxStore`` is the durable side: it is the port a real persistence
adapter implements so ``enqueue_with_effect`` runs inside the same database
transaction as the domain effect it accompanies. ``EventPublisher`` is the
transport side: a confirmed, synchronous publish (raise ``OutboxPublishError``
on failure — there is no "maybe delivered").

No real producer exists yet (that is R1-15's scope); this story's own tests
exercise these ports with a synthetic producer/consumer pair.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from cairn_kernel.hex.primitives import Port
from cairn_kernel.outbox.model import OutboxMessage


class OutboxPublishError(Exception):
    """Raised by an ``EventPublisher`` when a publish attempt is not confirmed."""


class OutboxStore(Port, Protocol):
    def enqueue_with_effect(self, message: OutboxMessage, effect: Callable[[], None]) -> None:
        """Run ``effect`` and persist ``message`` as one atomic unit.

        If ``effect`` raises, ``message`` must not be observable afterwards —
        the same guarantee a real adapter gets from writing both inside one
        database transaction.
        """

    def claim_pending(self, *, limit: int = 100) -> list[OutboxMessage]: ...

    def get(self, message_id: str) -> OutboxMessage | None: ...

    def mark_dispatched(self, message_id: str, *, at: object) -> OutboxMessage: ...

    def record_failure(
        self, message_id: str, *, at: object, max_attempts: int
    ) -> OutboxMessage: ...

    def dead_letters(self, *, tenant_id: str) -> list[OutboxMessage]: ...

    def replay(self, message_id: str, *, tenant_id: str) -> OutboxMessage:
        """Reset a dead-lettered message to ``PENDING`` for redispatch.

        Must raise ``TenantScopeViolationError`` (never silently no-op) when
        ``tenant_id`` does not match the message's owning tenant — a
        cross-tenant replay attempt (ADR-012).
        """


class EventPublisher(Port, Protocol):
    def publish(self, message: OutboxMessage) -> None:
        """Publish ``message``. Raise ``OutboxPublishError`` unless confirmed."""
