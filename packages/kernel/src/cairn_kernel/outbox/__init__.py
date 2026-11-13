"""CAIRN cairn_kernel.outbox — transactional outbox dispatcher (R1-23)."""

from cairn_kernel.outbox.dispatcher import DEFAULT_MAX_ATTEMPTS, DispatchReport, OutboxDispatcher
from cairn_kernel.outbox.model import OutboxMessage, OutboxStatus
from cairn_kernel.outbox.ports import EventPublisher, OutboxPublishError, OutboxStore
from cairn_kernel.outbox.store import InMemoryOutboxStore

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DispatchReport",
    "EventPublisher",
    "InMemoryOutboxStore",
    "OutboxDispatcher",
    "OutboxMessage",
    "OutboxPublishError",
    "OutboxStatus",
    "OutboxStore",
]
