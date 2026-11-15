"""R2-04: ``PostgresDesignRevisionRepository`` writes correctly into
migration 0005's ``subject_revision`` table with ``subject_kind=
"design"``.

This does not re-prove the monotonic-per-subject or append-only triggers
themselves -- that is already done generically in
``test_revision_approval_execution_schema.py``. It proves this adapter's
own responsibility: binding the tenant/project RLS context correctly and
using the table the way R2-04's brief requires (one new row per
generation, read back in order, never mutated).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from cairn_contracts.estate import Equivalence, FactStatus, Resource
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_contracts.mapping.pattern import Pattern, PatternCategory
from cairn_kernel.errors import ValidationError
from cairn_modules.design.revisions import DESIGN_SUBJECT_KIND, PostgresDesignRevisionRepository
from cairn_modules.design.target_model import generate_target_model
from conftest import signed_assertion

DESIGN_ID = "11111111-1111-1111-1111-111111111111"

PATTERN_PAYLOAD = {
    "id": "web-app",
    "name": "Web application",
    "category": PatternCategory.WEB_APP,
    "description": "A simple web app pattern for this test.",
    "parameters": (),
    "preconditions": ("estate contains at least one resource",),
    "outputs": ({"capability": "hosting", "description": "Serves the app"},),
    "validation_rules": (
        {"id": "r1", "description": "at least one resource", "severity": "error"},
    ),
    "evidence": "test fixture",
}


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


def _release(version: str = "2026.11.1") -> MappingRelease:
    return MappingRelease(
        version=version,
        released_at=datetime(2026, 11, 9, tzinfo=UTC),
        status=ReleaseStatus.DRAFT,
        entries=(
            MappingEntry(
                id="s3-to-gcs",
                source_provider="aws",
                source_service="s3",
                target_provider="gcp",
                target_service="cloud-storage",
                equivalence=Equivalence.EXACT,
                caveat=None,
                regions=(),
                evidence="public documentation",
            ),
        ),
    )


def _target_model(ids: dict[str, uuid.UUID], *, resource_id: str = "res-1"):
    pattern = Pattern.model_validate(PATTERN_PAYLOAD)
    resource = Resource(
        resource_id=resource_id,
        tenant_id=str(ids["tenant"]),
        project_id=str(ids["project"]),
        provider="aws",
        account_id="111111111111",
        region="eu-west-2",
        service="s3",
        resource_type="bucket",
        native_id="arn:aws:s3:::my-bucket",
        name="my-bucket",
        tags={},
        facts={},
        provenance=(),
        status=FactStatus.OBSERVED,
    )
    return generate_target_model(
        tenant_id=str(ids["tenant"]),
        project_id=str(ids["project"]),
        design_id=DESIGN_ID,
        estate=(resource,),
        pattern=pattern,
        pattern_catalogue_version="2026.11.1",
        mapping_release=_release(),
        target_provider="gcp",
        parameters={},
    )


def test_design_revision_insert_succeeds_and_is_readable(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    repo = PostgresDesignRevisionRepository(
        migrated_database,
        assertion=signed_assertion(ids["tenant"], ids["project"]),
    )
    model = _target_model(ids)

    record = repo.create_revision(design_id=DESIGN_ID, target_model=model, created_by="alice")

    assert record.revision_number == 1
    assert record.subject_kind == DESIGN_SUBJECT_KIND
    assert record.subject_id == DESIGN_ID
    assert record.content_hash == model.content_hash
    assert dict(record.input_versions)["mapping_release_version"] == "2026.11.1"


def test_second_generation_is_revision_two_not_a_mutation(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    repo = PostgresDesignRevisionRepository(
        migrated_database,
        assertion=signed_assertion(ids["tenant"], ids["project"]),
    )
    first_model = _target_model(ids, resource_id="res-1")
    second_model = _target_model(ids, resource_id="res-2")

    first = repo.create_revision(design_id=DESIGN_ID, target_model=first_model, created_by="alice")
    second = repo.create_revision(
        design_id=DESIGN_ID, target_model=second_model, created_by="alice"
    )

    assert first.revision_number == 1
    assert second.revision_number == 2
    assert first.content_hash != second.content_hash

    revisions = repo.list_revisions(
        tenant_id=str(ids["tenant"]), project_id=str(ids["project"]), design_id=DESIGN_ID
    )
    assert [r.revision_number for r in revisions] == [1, 2]
    assert revisions[0].content_hash == first.content_hash

    with (
        pytest.raises(psycopg.errors.CheckViolation, match="append-only"),
        psycopg.connect(migrated_database, autocommit=True) as connection,
    ):
        connection.execute(
            "UPDATE subject_revision SET content_hash = 'tampered'"
            " WHERE subject_kind = %s AND subject_id = %s AND revision_number = 1",
            (DESIGN_SUBJECT_KIND, DESIGN_ID),
        )


def test_latest_revision_reflects_the_most_recent_generation(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    repo = PostgresDesignRevisionRepository(
        migrated_database,
        assertion=signed_assertion(ids["tenant"], ids["project"]),
    )
    repo.create_revision(
        design_id=DESIGN_ID, target_model=_target_model(ids, resource_id="res-1"), created_by="a"
    )
    second_model = _target_model(ids, resource_id="res-2")
    repo.create_revision(design_id=DESIGN_ID, target_model=second_model, created_by="a")

    latest = repo.latest_revision(
        tenant_id=str(ids["tenant"]), project_id=str(ids["project"]), design_id=DESIGN_ID
    )
    assert latest is not None
    assert latest.revision_number == 2
    assert latest.content_hash == second_model.content_hash


def test_create_revision_without_an_assertion_is_rejected(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    repo = PostgresDesignRevisionRepository(migrated_database)
    model = _target_model(ids)

    with pytest.raises(ValidationError, match="tenant assertion"):
        repo.create_revision(design_id=DESIGN_ID, target_model=model, created_by="alice")
