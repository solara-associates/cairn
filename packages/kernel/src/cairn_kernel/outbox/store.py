"""In-memory ``OutboxStore`` adapter (R1-23).

Durable in the sense this story needs: the store is a separate object from
the dispatcher, so constructing a *new* dispatcher against an *existing*
store reproduces "the process restarted/crashed, but committed data
survived" without needing a real database. A later story swaps this adapter
for a Postgres-backed one behind the same ``OutboxStore`` port; nothing
above the port changes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from cairn_kernel.errors import NotFoundError, TenantScopeViolationError, ValidationError
from cairn_kernel.outbox.model import OutboxMessage, OutboxStatus


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._messages: dict[str, OutboxMessage] = {}
        self._order: list[str] = []

    def enqueue_with_effect(self, message: OutboxMessage, effect: Callable[[], None]) -> None:
        # The effect runs first; if it raises, nothing below executes and the
        # message is never observable — the same atomicity a single database
        # transaction gives a real adapter.
        effect()
        if message.message_id in self._messages:
            raise ValidationError(f"outbox message {message.message_id} already enqueued")
        self._messages[message.message_id] = message
        self._order.append(message.message_id)

    def claim_pending(self, *, limit: int = 100) -> list[OutboxMessage]:
        pending = [
            self._messages[message_id]
            for message_id in self._order
            if self._messages[message_id].status is OutboxStatus.PENDING
        ]
        return pending[:limit]

    def get(self, message_id: str) -> OutboxMessage | None:
        return self._messages.get(message_id)

    def mark_dispatched(self, message_id: str, *, at: datetime) -> OutboxMessage:
        message = self._require(message_id)
        if message.status is OutboxStatus.DISPATCHED:
            return message  # already delivered; marking again is a no-op, not an error
        updated = message.as_dispatched(at=at)
        self._messages[message_id] = updated
        return updated

    def record_failure(self, message_id: str, *, at: datetime, max_attempts: int) -> OutboxMessage:
        message = self._require(message_id)
        updated = message.as_failed(at=at, max_attempts=max_attempts)
        self._messages[message_id] = updated
        return updated

    def dead_letters(self, *, tenant_id: str) -> list[OutboxMessage]:
        return [
            message
            for message in self._messages.values()
            if message.tenant_id == tenant_id and message.status is OutboxStatus.DEAD_LETTERED
        ]

    def replay(self, message_id: str, *, tenant_id: str) -> OutboxMessage:
        message = self._require(message_id)
        if message.tenant_id != tenant_id:
            raise TenantScopeViolationError(
                f"outbox message {message_id} belongs to a different tenant"
            )
        if message.status is not OutboxStatus.DEAD_LETTERED:
            raise ValidationError(f"outbox message {message_id} is not dead-lettered")
        updated = message.as_replayed()
        self._messages[message_id] = updated
        return updated

    def _require(self, message_id: str) -> OutboxMessage:
        message = self._messages.get(message_id)
        if message is None:
            raise NotFoundError(f"outbox message {message_id} not found")
        return message
