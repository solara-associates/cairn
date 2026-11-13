"""R1-23: transactional outbox dispatcher, proven by failure injection.

R-OUTBOX-01's acceptance text asks for exactly five failure modes, each
proven against a real failure injection rather than described in prose:

  1. crash after commit, before dispatch — no message is lost
  2. duplicate delivery — idempotent, no double-effect
  3. consumer crash after effect, before acknowledgement — redelivery
     does not repeat the effect
  4. dead-letter replay — succeeds, within the owning tenant
  5. replay tenant isolation — a cross-tenant replay is rejected and audited

No real event producer exists yet (R1-15, a late-wave story, is what wires
one in) — exactly the position R1-21 was in for the execution gate, proven
there against synthetic mutations of each class
(``packages/modules/tests/test_execution_transitions.py``). This file
defines its own synthetic producer and consumer, used nowhere else, so the
dispatcher's failure-mode guarantees are proven against the
``OutboxStore``/``EventPublisher`` ports a real producer will later be
wired into.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import TenantScopeViolationError
from cairn_kernel.outbox import (
    InMemoryOutboxStore,
    OutboxDispatcher,
    OutboxMessage,
    OutboxPublishError,
    OutboxStatus,
    OutboxStore,
)
from cairn_kernel.testing.fakes import FixedClock, InMemoryAuditSink

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)


# --- synthetic event producer/consumer, used only by this file ------------


class SyntheticEventProducer:
    """Writes a domain effect and its outbox row in one atomic unit.

    Stands in for a real producer (R1-15's assessment orchestration, or any
    later Class A/B writer): the mechanism under test — same-transaction
    enqueue — does not depend on what triggered it.
    """

    def __init__(self, store: OutboxStore) -> None:
        self._store = store
        self.effect_log: list[str] = []
        self._counter = 0

    def emit(
        self,
        *,
        tenant_id: str,
        event_type: str,
        payload: dict[str, object],
        message_id: str | None = None,
        effect: Callable[[], None] | None = None,
    ) -> OutboxMessage:
        self._counter += 1
        message = OutboxMessage(
            message_id=message_id or f"msg-{self._counter}",
            tenant_id=tenant_id,
            project_id=None,
            event_type=event_type,
            payload=payload,
            created_at=NOW,
        )

        def _effect() -> None:
            self.effect_log.append(message.message_id)
            if effect is not None:
                effect()

        self._store.enqueue_with_effect(message, _effect)
        return message


class ConsumerCrashError(Exception):
    """Raised to simulate a consumer process dying before it acknowledges."""


class SyntheticConsumer:
    """Applies an effect for a delivered message, deduplicating by message id.

    Models the "inbox" half of the pattern: the set of processed ids is the
    durable record that makes a redelivered message a no-op.
    """

    def __init__(self) -> None:
        self._processed: set[str] = set()
        self.effect_applications = 0
        self.acknowledgements = 0

    def apply_effect_and_ack(
        self, message: OutboxMessage, *, crash_before_ack: bool = False
    ) -> None:
        if message.message_id not in self._processed:
            self.effect_applications += 1
            self._processed.add(message.message_id)
        if crash_before_ack:
            raise ConsumerCrashError("simulated crash before acknowledgement")
        self.acknowledgements += 1


@dataclass
class FakePublisher:
    """Publishes straight to a consumer, confirming only on success.

    ``fail_times`` lets a test inject N confirmed-failed publish attempts
    before a message starts succeeding.
    """

    consumer: SyntheticConsumer
    fail_times: int = 0
    publish_attempts: list[str] = field(default_factory=list)

    def publish(self, message: OutboxMessage) -> None:
        self.publish_attempts.append(message.message_id)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise OutboxPublishError("synthetic transport failure")
        self.consumer.apply_effect_and_ack(message)


def _dispatcher(
    store: OutboxStore, publisher: FakePublisher, *, max_attempts: int = 3
) -> tuple[OutboxDispatcher, InMemoryAuditSink]:
    audit = InMemoryAuditSink()
    dispatcher = OutboxDispatcher(
        store=store,
        publisher=publisher,
        audit_sink=audit,
        clock=FixedClock(NOW),
        max_attempts=max_attempts,
    )
    return dispatcher, audit


# --- 1. crash after commit, before dispatch --------------------------------


def test_crash_after_commit_before_dispatch_loses_nothing() -> None:
    store = InMemoryOutboxStore()
    producer = SyntheticEventProducer(store)
    message = producer.emit(
        tenant_id=TENANT_A, event_type="assessment.completed.v1", payload={"ok": True}
    )
    # "Crash": the row is committed (it is in the store) but nothing has
    # dispatched it yet. Simulate the process restarting by constructing a
    # *new* dispatcher/consumer against the *same, already-committed* store.
    consumer = SyntheticConsumer()
    publisher = FakePublisher(consumer=consumer)
    dispatcher, _audit = _dispatcher(store, publisher)

    report = dispatcher.dispatch_pending()

    assert report.dispatched == [message.message_id]
    assert consumer.effect_applications == 1
    assert store.get(message.message_id).status is OutboxStatus.DISPATCHED


def test_effect_that_fails_never_enqueues_an_outbox_row() -> None:
    store = InMemoryOutboxStore()
    producer = SyntheticEventProducer(store)

    def _boom() -> None:
        raise RuntimeError("domain effect failed")

    with pytest.raises(RuntimeError):
        producer.emit(
            tenant_id=TENANT_A,
            event_type="assessment.completed.v1",
            payload={},
            message_id="doomed-1",
            effect=_boom,
        )

    assert store.get("doomed-1") is None
    assert store.claim_pending() == []


# --- 2. duplicate delivery is idempotent -----------------------------------


def test_duplicate_delivery_does_not_double_the_effect() -> None:
    store = InMemoryOutboxStore()
    producer = SyntheticEventProducer(store)
    message = producer.emit(
        tenant_id=TENANT_A, event_type="finding.recorded.v1", payload={"id": "f-1"}
    )
    consumer = SyntheticConsumer()
    publisher = FakePublisher(consumer=consumer)
    dispatcher, _audit = _dispatcher(store, publisher)

    dispatcher.dispatch_pending()
    assert consumer.effect_applications == 1

    # A broker-level duplicate delivery of the *same already-dispatched*
    # message — independent of the outbox store's own state.
    publisher.publish(store.get(message.message_id))
    publisher.publish(store.get(message.message_id))

    assert consumer.effect_applications == 1
    assert consumer.acknowledgements == 3  # every delivery still acks cleanly


# --- 3. consumer crash after effect, before acknowledgement ----------------


def test_consumer_crash_after_effect_before_ack_does_not_repeat_effect() -> None:
    consumer = SyntheticConsumer()
    message = OutboxMessage(
        message_id="msg-crash-1",
        tenant_id=TENANT_A,
        project_id=None,
        event_type="finding.recorded.v1",
        payload={},
        created_at=NOW,
    )

    with pytest.raises(ConsumerCrashError):
        consumer.apply_effect_and_ack(message, crash_before_ack=True)

    assert consumer.effect_applications == 1
    assert consumer.acknowledgements == 0  # ack never reached the broker

    # The broker, having received no ack, redelivers the same message.
    consumer.apply_effect_and_ack(message)

    assert consumer.effect_applications == 1  # not repeated
    assert consumer.acknowledgements == 1


# --- 4 & 5. dead-letter replay, and replay tenant isolation ----------------


def test_message_is_dead_lettered_after_max_attempts_and_audited() -> None:
    store = InMemoryOutboxStore()
    producer = SyntheticEventProducer(store)
    message = producer.emit(
        tenant_id=TENANT_A, event_type="finding.recorded.v1", payload={"id": "f-2"}
    )
    consumer = SyntheticConsumer()
    publisher = FakePublisher(consumer=consumer, fail_times=3)
    dispatcher, audit = _dispatcher(store, publisher, max_attempts=3)

    report = dispatcher.dispatch_pending()
    report = dispatcher.dispatch_pending()
    report = dispatcher.dispatch_pending()
    assert report.dead_lettered == [message.message_id]
    assert store.get(message.message_id).status is OutboxStatus.DEAD_LETTERED
    assert consumer.effect_applications == 0  # effect never ran; publish never succeeded

    dead_letter_entries = [e for e in audit.entries if e.action == "outbox.message.dead_lettered"]
    assert len(dead_letter_entries) == 1
    assert dead_letter_entries[0].tenant_id.value == TENANT_A


def test_dead_letter_replay_succeeds_within_the_owning_tenant() -> None:
    store = InMemoryOutboxStore()
    producer = SyntheticEventProducer(store)
    message = producer.emit(
        tenant_id=TENANT_A, event_type="finding.recorded.v1", payload={"id": "f-3"}
    )
    consumer = SyntheticConsumer()
    publisher = FakePublisher(consumer=consumer, fail_times=3)
    dispatcher, audit = _dispatcher(store, publisher, max_attempts=3)
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()
    assert store.get(message.message_id).status is OutboxStatus.DEAD_LETTERED

    replayed = dispatcher.replay_dead_letter(
        message.message_id, tenant_id=TENANT_A, actor="support-agent"
    )
    assert replayed.status is OutboxStatus.PENDING

    # Redispatch now succeeds (the fake publisher's injected failures are spent).
    report = dispatcher.dispatch_pending()
    assert report.dispatched == [message.message_id]
    assert consumer.effect_applications == 1

    replay_entries = [e for e in audit.entries if e.action == "outbox.dead_letter.replayed"]
    assert len(replay_entries) == 1
    assert replay_entries[0].tenant_id.value == TENANT_A


def test_cross_tenant_replay_is_rejected_and_audited() -> None:
    store = InMemoryOutboxStore()
    producer = SyntheticEventProducer(store)
    message = producer.emit(
        tenant_id=TENANT_A, event_type="finding.recorded.v1", payload={"id": "f-4"}
    )
    consumer = SyntheticConsumer()
    publisher = FakePublisher(consumer=consumer, fail_times=3)
    dispatcher, audit = _dispatcher(store, publisher, max_attempts=3)
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()
    assert store.get(message.message_id).status is OutboxStatus.DEAD_LETTERED

    with pytest.raises(TenantScopeViolationError):
        dispatcher.replay_dead_letter(
            message.message_id, tenant_id=TENANT_B, actor="attacker"
        )

    # The message stays dead-lettered, scoped to its real owner.
    assert store.get(message.message_id).status is OutboxStatus.DEAD_LETTERED
    assert store.dead_letters(tenant_id=TENANT_A) != []
    assert store.dead_letters(tenant_id=TENANT_B) == []

    denied_entries = [
        e for e in audit.entries if e.action == "outbox.dead_letter.replay_denied_cross_tenant"
    ]
    assert len(denied_entries) == 1
    denied = denied_entries[0]
    # Audited against the *owning* tenant, so the victim tenant sees the
    # attempt in its own audit trail, with the requester recorded in the payload.
    assert denied.tenant_id.value == TENANT_A
    assert denied.payload["requested_by_tenant_id"] == TENANT_B


def test_dead_letters_are_listed_tenant_scoped() -> None:
    store = InMemoryOutboxStore()
    producer = SyntheticEventProducer(store)
    msg_a = producer.emit(tenant_id=TENANT_A, event_type="finding.recorded.v1", payload={})
    msg_b = producer.emit(tenant_id=TENANT_B, event_type="finding.recorded.v1", payload={})
    consumer = SyntheticConsumer()
    publisher = FakePublisher(consumer=consumer, fail_times=99)
    dispatcher, _audit = _dispatcher(store, publisher, max_attempts=1)
    dispatcher.dispatch_pending()

    tenant_a_ids = {m.message_id for m in store.dead_letters(tenant_id=TENANT_A)}
    tenant_b_ids = {m.message_id for m in store.dead_letters(tenant_id=TENANT_B)}
    assert tenant_a_ids == {msg_a.message_id}
    assert tenant_b_ids == {msg_b.message_id}
