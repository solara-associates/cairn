"""Transactional outbox domain model (R1-23, R0-20 gate 6 "outbox" half).

An ``OutboxMessage`` is written in the same application transaction as the
domain effect that produced it (``OutboxStore.enqueue_with_effect``): either
both are persisted or neither is. A separate dispatcher later reads pending
messages and publishes them, marking a message delivered only after a
confirmed publish. A message that keeps failing is dead-lettered after
``max_attempts`` and can later be replayed — but only within the tenant that
owns it (ADR-012).

This module defines the message and its states only. It has no dependency on
any real event producer: a later story wires a real producer into the
``OutboxStore``/``EventPublisher`` ports this story defines (see
``cairn_kernel.outbox.ports``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DEAD_LETTERED = "DEAD_LETTERED"


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """One row of the outbox. Immutable: every state change returns a new value."""

    message_id: str
    tenant_id: str
    project_id: str | None
    event_type: str
    payload: Mapping[str, Any]
    created_at: datetime
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    dispatched_at: datetime | None = None
    dead_lettered_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise ValueError("message_id must not be blank")
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be blank")
        if not self.event_type.strip():
            raise ValueError("event_type must not be blank")
        if self.attempts < 0:
            raise ValueError("attempts cannot be negative")

    def as_dispatched(self, *, at: datetime) -> OutboxMessage:
        return replace(self, status=OutboxStatus.DISPATCHED, dispatched_at=at)

    def as_failed(self, *, at: datetime, max_attempts: int) -> OutboxMessage:
        attempts = self.attempts + 1
        if attempts >= max_attempts:
            return replace(
                self,
                attempts=attempts,
                status=OutboxStatus.DEAD_LETTERED,
                dead_lettered_at=at,
            )
        return replace(self, attempts=attempts)

    def as_replayed(self) -> OutboxMessage:
        return replace(
            self,
            status=OutboxStatus.PENDING,
            attempts=0,
            dead_lettered_at=None,
            dispatched_at=None,
        )
