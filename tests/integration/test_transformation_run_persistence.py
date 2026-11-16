"""R3-03b: ``PostgresTransformationRunRepository`` writes correctly into
migration 0008's ``transformation_run`` table.

This does not re-prove monotonic-per-project numbering or append-only
enforcement in the abstract -- those are exactly the same trigger
discipline migration 0005's ``subject_revision`` already uses, proven
generically for that table in ``test_revision_approval_execution_schema.py``.
This proves this adapter's own responsibility: binding the tenant/
project RLS context correctly, round-tripping a full
``TransformationManifest`` through ``jsonb`` without losing any field,
and the table's own monotonic/append-only triggers actually firing for
*this* table (not assumed to work merely because an identically-shaped
table elsewhere has the same trigger functions).
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.runs import PostgresTransformationRunRepository
from conftest import signed_assertion


def _seed_project(dsn: str) -> dict[str, uuid.UUID]:
    ids = {"tenant": uuid.uuid4(), "project": uuid.uuid4()}
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenant (tenant_id, name) VALUES (%s, 'Tenant')", (ids["tenant"],)
        )
        connection.execute(
            "INSERT INTO project (project_id, tenant_id, customer_name, name)"
            " VALUES (%s, %s, 'Customer', 'Project')",
            (ids["project"], ids["tenant"]),
        )
    return ids


def _manifest(*, rule_id: str = "tf-s3-bucket-inline-acl-deprecated") -> TransformationManifest:
    return TransformationManifest(
        source_file_ids=("s3.tf",),
        entries=(
            ManifestEntry(
                source_file_id="s3.tf",
                rule_id=rule_id,
                outcome=ManifestOutcome.APPLIED,
                reason=None,
                edits=(
                    ManifestEdit(
                        start_byte=75,
                        end_byte=97,
                        start_line=3,
                        end_line=3,
                        replacement="",
                    ),
                ),
                detector_version="cairn-detector/0.1.0",
                pattern_version="cairn-hcl-parser/0.1.0",
                patcher_version="cairn-transform-patcher/0.1.0",
                mapping_release_version=None,
            ),
        ),
    )


def test_transformation_run_insert_succeeds_and_is_readable(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    repo = PostgresTransformationRunRepository(
        migrated_database,
        assertion=signed_assertion(ids["tenant"], ids["project"]),
    )
    manifest = _manifest()

    record = repo.record_run(
        tenant_id=str(ids["tenant"]),
        project_id=str(ids["project"]),
        manifest=manifest,
        created_by="alice",
    )

    assert record.run_number == 1
    assert record.manifest == manifest


def test_second_run_is_number_two_not_a_mutation(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    repo = PostgresTransformationRunRepository(
        migrated_database,
        assertion=signed_assertion(ids["tenant"], ids["project"]),
    )
    first_manifest = _manifest(rule_id="tf-s3-bucket-inline-acl-deprecated")
    second_manifest = _manifest(rule_id="py-import-imp-deprecated")

    first = repo.record_run(
        tenant_id=str(ids["tenant"]),
        project_id=str(ids["project"]),
        manifest=first_manifest,
        created_by="alice",
    )
    second = repo.record_run(
        tenant_id=str(ids["tenant"]),
        project_id=str(ids["project"]),
        manifest=second_manifest,
        created_by="alice",
    )

    assert first.run_number == 1
    assert second.run_number == 2

    runs = repo.list_runs(tenant_id=str(ids["tenant"]), project_id=str(ids["project"]))
    assert [r.run_number for r in runs] == [1, 2]
    assert runs[1].manifest.entries[0].rule_id == "py-import-imp-deprecated"

    latest = repo.latest_run(tenant_id=str(ids["tenant"]), project_id=str(ids["project"]))
    assert latest is not None
    assert latest.run_number == 2

    with (
        pytest.raises(psycopg.errors.CheckViolation, match="append-only"),
        psycopg.connect(migrated_database, autocommit=True) as connection,
    ):
        connection.execute(
            "UPDATE transformation_run SET applied_count = 99"
            " WHERE tenant_id = %s AND project_id = %s AND run_number = 1",
            (ids["tenant"], ids["project"]),
        )
