import pytest
from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security import AuditEntry
from cairn_kernel.testing.fakes import InMemoryAuditSink

TENANT = TenantId("11111111-1111-4111-8111-111111111111")
PROJECT = ProjectId("22222222-2222-4222-8222-222222222222")


def _entry(action: str = "project.update") -> AuditEntry:
    return AuditEntry(
        tenant_id=TENANT,
        project_id=PROJECT,
        actor="user-1",
        action=action,
        operation_class=OperationClass.WORKSPACE_MUTATION,
        payload={"changed": ["name"]},
    )


def test_fake_sink_records_entries_in_order() -> None:
    sink = InMemoryAuditSink()
    first = sink.append(_entry("project.create"))
    second = sink.append(_entry("project.update"))
    assert (first, second) == ("audit-1", "audit-2")
    assert [entry.action for entry in sink.entries] == [
        "project.create",
        "project.update",
    ]


def test_fake_sink_failure_raises_audit_unavailable() -> None:
    sink = InMemoryAuditSink()
    sink.fail_next = True
    with pytest.raises(AuditUnavailableError):
        sink.append(_entry())
    assert sink.entries == []


def test_audit_entry_is_immutable() -> None:
    entry = _entry()
    with pytest.raises(AttributeError):
        entry.action = "other"  # type: ignore[misc]
