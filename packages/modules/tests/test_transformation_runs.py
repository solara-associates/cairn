"""Tests for R3-03b's ``FakeTransformationRunRepository``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cairn_kernel.hex import TenantId
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_modules.transformation.engine import (
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.runs import FakeTransformationRunRepository

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _ambient_tenant_context() -> Iterator[None]:
    with tenant_scope(
        TenantContext(
            tenant_id=TenantId(TENANT_ID),
            project_id=None,
            actor_id="alice",
            actor_roles=("ARCHITECT",),
            correlation_id="r3-03b-transformation-runs-test",
        )
    ):
        yield


def _manifest(rule_id: str) -> TransformationManifest:
    return TransformationManifest(
        source_file_ids=("mod.py",),
        entries=(
            ManifestEntry(
                source_file_id="mod.py",
                rule_id=rule_id,
                outcome=ManifestOutcome.APPLIED,
                reason=None,
                edits=(),
                detector_version="cairn-detector/0.1.0",
                pattern_version="cairn-python-parser/0.1.0",
                patcher_version="cairn-transform-patcher/0.1.0",
            ),
        ),
    )


def test_record_run_assigns_sequential_run_numbers() -> None:
    repo = FakeTransformationRunRepository()
    first = repo.record_run(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        manifest=_manifest("py-import-imp-deprecated"),
        created_by="alice",
    )
    second = repo.record_run(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        manifest=_manifest("py-import-imp-deprecated"),
        created_by="alice",
    )
    assert first.run_number == 1
    assert second.run_number == 2


def test_list_runs_is_ordered_and_latest_run_returns_the_last_one() -> None:
    repo = FakeTransformationRunRepository()
    repo.record_run(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        manifest=_manifest("py-import-imp-deprecated"),
        created_by="alice",
    )
    second = repo.record_run(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        manifest=_manifest("tf-s3-bucket-inline-acl-deprecated"),
        created_by="alice",
    )

    runs = repo.list_runs(tenant_id=TENANT_ID, project_id=PROJECT_ID)
    assert [r.run_number for r in runs] == [1, 2]
    assert repo.latest_run(tenant_id=TENANT_ID, project_id=PROJECT_ID) == second


def test_latest_run_is_none_when_nothing_recorded_yet() -> None:
    repo = FakeTransformationRunRepository()
    assert repo.latest_run(tenant_id=TENANT_ID, project_id=PROJECT_ID) is None


def test_runs_are_scoped_per_project() -> None:
    repo = FakeTransformationRunRepository()
    repo.record_run(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        manifest=_manifest("py-import-imp-deprecated"),
        created_by="alice",
    )
    other_project_runs = repo.list_runs(tenant_id=TENANT_ID, project_id="other-project")
    assert other_project_runs == ()
