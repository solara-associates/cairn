from dataclasses import dataclass

import pytest
from cairn_kernel.errors import ErrorCode, NotFoundError, TenantScopeViolationError
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.tenancy import (
    TenantContext,
    assert_project_allowed,
    assert_tenant_allowed,
    current_tenant_context,
    tenant_scope,
)


def make_context(
    tenant: str,
    project: str | None = "project-1",
    correlation: str = "corr-1",
) -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(tenant),
        project_id=ProjectId(project) if project else None,
        actor_id="user-1",
        actor_roles=("ARCHITECT",),
        correlation_id=correlation,
    )


def test_assert_tenant_allowed_passes_within_scope() -> None:
    context = make_context("tenant-1")
    assert_tenant_allowed(context, TenantId("tenant-1"))


def test_assert_tenant_allowed_rejects_cross_tenant() -> None:
    context = make_context("tenant-1")
    with pytest.raises(TenantScopeViolationError) as exc_info:
        assert_tenant_allowed(context, TenantId("tenant-2"))
    assert exc_info.value.code is ErrorCode.TENANT_SCOPE_VIOLATION


def test_assert_project_allowed_requires_project_scope() -> None:
    context = make_context("tenant-1", project=None)
    with pytest.raises(TenantScopeViolationError):
        assert_project_allowed(context, ProjectId("project-1"))


def test_assert_project_allowed_rejects_cross_project() -> None:
    context = make_context("tenant-1", project="project-1")
    with pytest.raises(TenantScopeViolationError):
        assert_project_allowed(context, ProjectId("project-2"))


@dataclass(frozen=True, slots=True)
class Record:
    tenant_id: TenantId
    project_id: ProjectId | None
    record_id: str
    payload: str


class RecordRepository:
    def __init__(self) -> None:
        self._records: dict[str, Record] = {}

    def save(self, record: Record) -> None:
        context = current_tenant_context()
        assert_tenant_allowed(context, record.tenant_id)
        if record.project_id is not None:
            assert_project_allowed(context, record.project_id)
        self._records[record.record_id] = record

    def get(self, record_id: str) -> Record:
        context = current_tenant_context()
        record = self._records.get(record_id)
        if record is None:
            raise NotFoundError(f"record {record_id} does not exist")
        assert_tenant_allowed(context, record.tenant_id)
        if record.project_id is not None:
            assert_project_allowed(context, record.project_id)
        return record


def make_record(tenant: str, record_id: str, project: str | None = "project-1") -> Record:
    return Record(
        tenant_id=TenantId(tenant),
        project_id=ProjectId(project) if project else None,
        record_id=record_id,
        payload="payload",
    )


def test_repository_round_trips_within_scope() -> None:
    repository = RecordRepository()
    with tenant_scope(make_context("tenant-1")):
        repository.save(make_record("tenant-1", "record-1"))
        assert repository.get("record-1").payload == "payload"


def test_repository_read_without_context_fails_closed() -> None:
    repository = RecordRepository()
    with tenant_scope(make_context("tenant-1")):
        repository.save(make_record("tenant-1", "record-1"))
    with pytest.raises(TenantScopeViolationError):
        repository.get("record-1")


def test_repository_write_without_context_fails_closed() -> None:
    repository = RecordRepository()
    with pytest.raises(TenantScopeViolationError):
        repository.save(make_record("tenant-1", "record-1"))
    with tenant_scope(make_context("tenant-1")), pytest.raises(NotFoundError):
        repository.get("record-1")


def test_cross_tenant_read_returns_no_data() -> None:
    repository = RecordRepository()
    with tenant_scope(make_context("tenant-1")):
        repository.save(make_record("tenant-1", "record-1"))
    with tenant_scope(make_context("tenant-2")):
        with pytest.raises(TenantScopeViolationError) as exc_info:
            repository.get("record-1")
        assert exc_info.value.code is ErrorCode.TENANT_SCOPE_VIOLATION


def test_cross_tenant_write_is_rejected_before_persistence() -> None:
    repository = RecordRepository()
    with tenant_scope(make_context("tenant-1")), pytest.raises(TenantScopeViolationError):
        repository.save(make_record("tenant-2", "record-1"))
    with tenant_scope(make_context("tenant-2")), pytest.raises(NotFoundError):
        repository.get("record-1")


def test_cross_project_read_is_denied() -> None:
    repository = RecordRepository()
    with tenant_scope(make_context("tenant-1", project="project-1")):
        repository.save(make_record("tenant-1", "record-1", project="project-1"))
    with (
        tenant_scope(make_context("tenant-1", project="project-2")),
        pytest.raises(TenantScopeViolationError),
    ):
        repository.get("record-1")


def test_missing_project_context_denies_project_rows() -> None:
    repository = RecordRepository()
    with tenant_scope(make_context("tenant-1", project="project-1")):
        repository.save(make_record("tenant-1", "record-1", project="project-1"))
    with (
        tenant_scope(make_context("tenant-1", project=None)),
        pytest.raises(TenantScopeViolationError),
    ):
        repository.get("record-1")


def test_persistence_boundary_reasserts_context() -> None:
    repository = RecordRepository()

    def job_body() -> None:
        with tenant_scope(make_context("tenant-1")):
            repository.save(make_record("tenant-1", "record-1"))
        repository.get("record-1")

    with pytest.raises(TenantScopeViolationError):
        job_body()


def test_pool_reuse_cannot_leak_between_tenants() -> None:
    repository = RecordRepository()
    with tenant_scope(make_context("tenant-1", correlation="corr-a")):
        repository.save(make_record("tenant-1", "record-1"))
    with (
        tenant_scope(make_context("tenant-2", correlation="corr-b")),
        pytest.raises(TenantScopeViolationError),
    ):
        repository.get("record-1")
    with tenant_scope(make_context("tenant-1", correlation="corr-c")):
        assert repository.get("record-1").payload == "payload"
