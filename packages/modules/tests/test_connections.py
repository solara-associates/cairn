"""R1-02: provider connection create/validate/revoke for GCP.

Acceptance (spec 16.0, R1-02): read-only scope only; no execution
credentials or write scope before R4; secret never returned; revoke
audited.

Validation here round-trips against R0-13's deterministic
``FakeProviderAdapter`` via a small test-only adapter (``FakeScopeValidator``
below) that implements ``cairn_modules.connections.ProviderScopeValidator``.
That wiring deliberately lives in this test file, not in ``cairn_modules``:
the domain module must not import a concrete provider adapter (ADR-010;
the ``domain-purity`` import-linter contract forbids ``cairn_modules`` ->
``cairn_adapters``), matching how an app layer would wire a real adapter.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import count

import pytest
from cairn_adapters.provider_core.fake import FakeProviderAdapter
from cairn_adapters.provider_core.ports import InventoryRequest, ProviderConnection
from cairn_kernel.errors import (
    AuditUnavailableError,
    ForbiddenError,
    NotFoundError,
    ProviderUnavailableError,
    ValidationError,
)
from cairn_kernel.security.audit import AuditEntry
from cairn_modules.connections import (
    ConnectionRegistry,
    ConnectionScope,
    ConnectionStatus,
    ScopeCheckResult,
)

TENANT_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = "22222222-2222-4222-8222-222222222222"
ACCOUNT_ID = "gcp-project-123"
SECRET = "super-secret-service-account-key"
ACTOR = "user-1"


@dataclass
class FakeScopeValidator:
    """Test-only adapter bridging a ``FakeProviderAdapter`` to
    ``ProviderScopeValidator``. Round-trips a minimal ``read_inventory`` call
    and reports the adapter's declared scope."""

    adapter: FakeProviderAdapter
    tenant_id: str
    project_id: str
    force_write_scope: bool = False

    def check_scope(
        self, *, provider: str, account_id: str, credential_ref: str
    ) -> ScopeCheckResult:
        if self.force_write_scope:
            return ScopeCheckResult(read_only=False, reachable=True, detail="write scope granted")

        descriptor = self.adapter.descriptor
        if descriptor.provider != provider:
            return ScopeCheckResult(read_only=True, reachable=False, detail="provider mismatch")

        connection = ProviderConnection(
            connection_id="probe",
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            provider=provider,
            account_id=account_id,
            credential_ref=credential_ref,
        )
        try:
            self.adapter.read_inventory(InventoryRequest(connection=connection, page_size=1))
        except (ProviderUnavailableError, ValidationError) as exc:
            return ScopeCheckResult(read_only=descriptor.read_only, reachable=False, detail=str(exc))
        return ScopeCheckResult(read_only=descriptor.read_only, reachable=True)


class InMemoryAuditSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[AuditEntry] = []
        self.fail = fail
        self._counter = count(1)

    def append(self, entry: AuditEntry) -> str:
        if self.fail:
            raise AuditUnavailableError("audit sink unavailable")
        self.entries.append(entry)
        return f"audit-{next(self._counter)}"


class OrderTrackingAuditSink:
    """Records, at the moment ``append`` is called, whatever the probe
    reports -- used to prove audit-before-effect ordering."""

    def __init__(self, status_probe) -> None:
        self._status_probe = status_probe
        self.status_at_append: list[ConnectionStatus] = []

    def append(self, entry: AuditEntry) -> str:
        self.status_at_append.append(self._status_probe())
        return "audit-ordered-1"


def _registry(audit_sink=None, clock=None) -> ConnectionRegistry:
    return ConnectionRegistry(audit_sink=audit_sink or InMemoryAuditSink(), clock=clock)


def _create(registry: ConnectionRegistry, connection_id: str = "conn-1", secret: str = SECRET):
    return registry.create(
        connection_id=connection_id,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        provider="gcp",
        account_id=ACCOUNT_ID,
        secret=secret,
        actor_id=ACTOR,
    )


# --- create -----------------------------------------------------------------


def test_create_happy_path_returns_active_read_only_connection() -> None:
    registry = _registry()

    summary = _create(registry)

    assert summary.connection_id == "conn-1"
    assert summary.scope is ConnectionScope.READ_ONLY
    assert summary.status is ConnectionStatus.ACTIVE
    assert summary.last_validated_at is None
    assert summary.revoked_at is None


def test_create_rejects_write_scope_outright() -> None:
    registry = _registry()

    with pytest.raises(ForbiddenError, match="R4"):
        registry.create(
            connection_id="conn-write",
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            provider="gcp",
            account_id=ACCOUNT_ID,
            secret=SECRET,
            actor_id=ACTOR,
            scope=ConnectionScope.WRITE,
        )
    with pytest.raises(NotFoundError):
        registry.get("conn-write")


def test_create_rejects_execute_scope_outright() -> None:
    registry = _registry()

    with pytest.raises(ForbiddenError, match="R4"):
        registry.create(
            connection_id="conn-exec",
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            provider="gcp",
            account_id=ACCOUNT_ID,
            secret=SECRET,
            actor_id=ACTOR,
            scope=ConnectionScope.EXECUTE,
        )


def test_create_rejects_duplicate_connection_id() -> None:
    registry = _registry()
    _create(registry)

    with pytest.raises(ValidationError, match="already exists"):
        _create(registry)


def test_create_rejects_blank_secret() -> None:
    registry = _registry()

    with pytest.raises(ValidationError):
        _create(registry, secret="   ")


# --- secret never returned ---------------------------------------------------


def test_secret_never_returned_in_summary_or_its_serialized_form() -> None:
    registry = _registry()

    summary = _create(registry)

    summary_text = json.dumps(
        {field: str(value) for field, value in asdict(summary).items()}
    )
    assert SECRET not in summary_text
    assert not hasattr(summary, "secret")
    assert not hasattr(summary, "secret_digest")
    assert not hasattr(summary, "credential_ref")


def test_secret_never_returned_from_get() -> None:
    registry = _registry()
    _create(registry)

    summary = registry.get("conn-1")

    assert SECRET not in repr(summary)
    assert SECRET not in str(summary)


def test_secret_never_appears_in_audit_log_on_revoke() -> None:
    sink = InMemoryAuditSink()
    registry = _registry(audit_sink=sink)
    _create(registry)

    registry.revoke("conn-1", actor_id=ACTOR)

    assert len(sink.entries) == 1
    entry = sink.entries[0]
    assert SECRET not in json.dumps(dict(entry.payload))
    assert SECRET not in repr(entry)


# --- validate -----------------------------------------------------------------


def test_validate_happy_path_round_trips_against_fake_adapter() -> None:
    registry = _registry()
    _create(registry)
    adapter = FakeProviderAdapter(provider="gcp")
    validator = FakeScopeValidator(adapter=adapter, tenant_id=TENANT_ID, project_id=PROJECT_ID)

    summary = registry.validate("conn-1", validator=validator)

    assert summary.last_validated_at is not None
    assert summary.status is ConnectionStatus.ACTIVE


def test_validate_rejects_non_read_only_scope() -> None:
    registry = _registry()
    _create(registry)
    adapter = FakeProviderAdapter(provider="gcp")
    validator = FakeScopeValidator(
        adapter=adapter, tenant_id=TENANT_ID, project_id=PROJECT_ID, force_write_scope=True
    )

    with pytest.raises(ForbiddenError, match="non-read-only"):
        registry.validate("conn-1", validator=validator)

    # rejecting the scope must not mark the connection validated
    assert registry.get("conn-1").last_validated_at is None


def test_validate_surfaces_provider_unavailable_when_round_trip_fails() -> None:
    registry = _registry()
    _create(registry)
    adapter = FakeProviderAdapter(provider="gcp", fail_inventory=True)
    validator = FakeScopeValidator(adapter=adapter, tenant_id=TENANT_ID, project_id=PROJECT_ID)

    with pytest.raises(ProviderUnavailableError):
        registry.validate("conn-1", validator=validator)


def test_validate_rejects_unknown_connection() -> None:
    registry = _registry()
    adapter = FakeProviderAdapter(provider="gcp")
    validator = FakeScopeValidator(adapter=adapter, tenant_id=TENANT_ID, project_id=PROJECT_ID)

    with pytest.raises(NotFoundError):
        registry.validate("missing", validator=validator)


def test_validate_rejects_revoked_connection() -> None:
    registry = _registry()
    _create(registry)
    registry.revoke("conn-1", actor_id=ACTOR)
    adapter = FakeProviderAdapter(provider="gcp")
    validator = FakeScopeValidator(adapter=adapter, tenant_id=TENANT_ID, project_id=PROJECT_ID)

    with pytest.raises(ValidationError, match="revoked"):
        registry.validate("conn-1", validator=validator)


# --- revoke / audit -----------------------------------------------------------


def test_revoke_happy_path_marks_connection_revoked() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    registry = _registry(clock=lambda: now)
    _create(registry)

    summary = registry.revoke("conn-1", actor_id=ACTOR)

    assert summary.status is ConnectionStatus.REVOKED
    assert summary.revoked_at == now


def test_revoke_is_audited() -> None:
    sink = InMemoryAuditSink()
    registry = _registry(audit_sink=sink)
    _create(registry)

    registry.revoke("conn-1", actor_id=ACTOR)

    assert len(sink.entries) == 1
    entry = sink.entries[0]
    assert entry.action == "provider_connection.revoke"
    assert entry.actor == ACTOR
    assert entry.payload["connection_id"] == "conn-1"


def test_revoke_audits_before_marking_the_connection_revoked() -> None:
    registry = _registry()
    _create(registry)
    sink = OrderTrackingAuditSink(status_probe=lambda: registry.get("conn-1").status)
    registry = _registry(audit_sink=sink)
    _create(registry)

    registry.revoke("conn-1", actor_id=ACTOR)

    # at the moment the audit sink was called, the connection was still ACTIVE
    assert sink.status_at_append == [ConnectionStatus.ACTIVE]
    # only after the audited append did the connection become REVOKED
    assert registry.get("conn-1").status is ConnectionStatus.REVOKED


def test_revoke_fails_closed_when_audit_sink_unavailable() -> None:
    sink = InMemoryAuditSink(fail=True)
    registry = _registry(audit_sink=sink)
    _create(registry)

    with pytest.raises(AuditUnavailableError):
        registry.revoke("conn-1", actor_id=ACTOR)

    # the connection must remain ACTIVE: revoke failed closed, not silently
    assert registry.get("conn-1").status is ConnectionStatus.ACTIVE


def test_revoke_is_idempotent_and_does_not_re_audit() -> None:
    sink = InMemoryAuditSink()
    registry = _registry(audit_sink=sink)
    _create(registry)
    registry.revoke("conn-1", actor_id=ACTOR)

    second = registry.revoke("conn-1", actor_id=ACTOR)

    assert second.status is ConnectionStatus.REVOKED
    assert len(sink.entries) == 1


def test_revoke_rejects_unknown_connection() -> None:
    registry = _registry()

    with pytest.raises(NotFoundError):
        registry.revoke("missing", actor_id=ACTOR)


def test_revoke_requires_an_actor_id() -> None:
    registry = _registry()
    _create(registry)

    with pytest.raises(ValidationError):
        registry.revoke("conn-1", actor_id="   ")
