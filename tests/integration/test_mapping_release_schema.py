"""R2-01: migration 0007's mapping_release/mapping_release_review/
mapping_proposal schema, proven live against Postgres (ADR-004).

Same patterns as ``test_revision_approval_execution_schema.py``: append-
only triggers proven directly (superuser bypass), the sequence trigger
proven as the database half of
``cairn_modules.mappings.domain.require_legal_transition``, and tenant
isolation on ``mapping_proposal`` proven under the application role with
RLS forced -- the DB-level half of
``packages/modules/tests/test_mapping_workflow.py``'s ``FakeMappingRepository``
isolation tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_kernel.errors import MappingUnavailableError, ValidationError
from cairn_modules.mappings import FakeMappingRepository  # noqa: F401  (import sanity only)
from cairn_modules.mappings.registry import PostgresMappingRepository
from conftest import signed_assertion

APP_ROLE = "cairn_app"


def _seed_tenant(dsn: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO tenant (tenant_id, name) VALUES (%s, 'Tenant')", (tenant_id,)
        )
    return tenant_id


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
                equivalence=Equivalence.APPROXIMATE,
                caveat="Consistency semantics differ",
                regions=("europe-west2",),
                evidence="public documentation",
            ),
        ),
    )


# --- append-only, proven directly against the trigger (superuser bypass) ---


def test_mapping_release_append_only_trigger_rejects_update(migrated_database: str) -> None:
    tenant_id = _seed_tenant(migrated_database)
    repo = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_id)
    )
    release = _release()
    repo.propose(release, tenant_id=str(tenant_id), proposer_actor_id="architect-1", rationale="r")

    with (
        psycopg.connect(migrated_database, autocommit=True) as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="append-only"),
    ):
        connection.execute(
            "UPDATE mapping_release SET content_hash = 'tampered' WHERE version = %s",
            (release.version,),
        )


def test_mapping_release_review_append_only_trigger_rejects_delete(
    migrated_database: str,
) -> None:
    tenant_id = _seed_tenant(migrated_database)
    repo = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_id)
    )
    release = _release()
    repo.propose(release, tenant_id=str(tenant_id), proposer_actor_id="architect-1", rationale="r")

    with (
        psycopg.connect(migrated_database, autocommit=True) as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="append-only"),
    ):
        connection.execute(
            "DELETE FROM mapping_release_review WHERE version = %s", (release.version,)
        )


def test_mapping_proposal_append_only_trigger_rejects_update(migrated_database: str) -> None:
    tenant_id = _seed_tenant(migrated_database)
    repo = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_id)
    )
    release = _release()
    repo.propose(release, tenant_id=str(tenant_id), proposer_actor_id="architect-1", rationale="r")

    with (
        psycopg.connect(migrated_database, autocommit=True) as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="append-only"),
    ):
        connection.execute(
            "UPDATE mapping_proposal SET rationale = 'tampered' WHERE version = %s",
            (release.version,),
        )


# --- the ADR-004 sequence trigger -------------------------------------------


def test_sequence_trigger_rejects_a_transition_out_of_order(migrated_database: str) -> None:
    tenant_id = _seed_tenant(migrated_database)
    repo = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_id)
    )
    release = _release()
    repo.propose(release, tenant_id=str(tenant_id), proposer_actor_id="architect-1", rationale="r")

    with (
        psycopg.connect(migrated_database, autocommit=True) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            "INSERT INTO mapping_release_review"
            " (version, from_status, to_status, actor_id, rationale)"
            " VALUES (%s, 'IN_REVIEW', 'PUBLISHED', 'operator-1', 'skip ahead')",
            (release.version,),
        )


def test_sequence_trigger_rejects_mutation_after_retired(migrated_database: str) -> None:
    tenant_id = _seed_tenant(migrated_database)
    repo = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_id)
    )
    release = _release()
    repo.propose(release, tenant_id=str(tenant_id), proposer_actor_id="architect-1", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")
    repo.retire(release.version, actor_id="operator-1", rationale="superseded")

    with (
        psycopg.connect(migrated_database, autocommit=True) as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="RETIRED"),
    ):
        connection.execute(
            "INSERT INTO mapping_release_review"
            " (version, from_status, to_status, actor_id, rationale)"
            " VALUES (%s, 'RETIRED', 'DRAFT', 'operator-1', 'resurrect')",
            (release.version,),
        )


# --- PostgresMappingRepository round trip -----------------------------------


def test_repository_propose_review_publish_retire_round_trip(migrated_database: str) -> None:
    tenant_id = _seed_tenant(migrated_database)
    repo = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_id)
    )
    release = _release()

    proposed = repo.propose(
        release, tenant_id=str(tenant_id), proposer_actor_id="architect-1", rationale="pilot gap"
    )
    assert proposed.status is ReleaseStatus.IN_REVIEW

    approved = repo.review(
        release.version, approved=True, reviewer_actor_id="approver-1", rationale="looks right"
    )
    assert approved.status is ReleaseStatus.APPROVED

    published = repo.publish(
        release.version, content_hash=release.content_hash, actor_id="operator-1"
    )
    assert published.status is ReleaseStatus.PUBLISHED
    assert published.release.entries[0].caveat == "Consistency semantics differ"

    retired = repo.retire(release.version, actor_id="operator-1", rationale="superseded")
    assert retired.status is ReleaseStatus.RETIRED

    fetched = repo.get(release.version)
    assert fetched.status is ReleaseStatus.RETIRED
    assert len(fetched.reviews) == 5  # DRAFT, IN_REVIEW, APPROVED, PUBLISHED, RETIRED


def test_repository_publish_immutability_same_hash_noop_different_hash_raises(
    migrated_database: str,
) -> None:
    tenant_id = _seed_tenant(migrated_database)
    repo = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_id)
    )
    release = _release()
    repo.propose(release, tenant_id=str(tenant_id), proposer_actor_id="architect-1", rationale="r")
    repo.review(release.version, approved=True, reviewer_actor_id="approver-1", rationale="ok")
    repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")

    # same version, same hash -> no-op
    again = repo.publish(release.version, content_hash=release.content_hash, actor_id="operator-1")
    assert again.status is ReleaseStatus.PUBLISHED

    # same version, different hash -> still raises, even though already PUBLISHED
    with pytest.raises(ValidationError, match="immutable"):
        repo.publish(release.version, content_hash="not-the-real-hash", actor_id="operator-1")


def test_repository_get_unknown_version_is_unavailable(migrated_database: str) -> None:
    repo = PostgresMappingRepository(migrated_database)
    with pytest.raises(MappingUnavailableError):
        repo.get("2099.1.1")


# --- tenant isolation on mapping_proposal (RLS, under the app role) --------


def test_mapping_proposal_cross_tenant_read_returns_no_rows(migrated_database: str) -> None:
    tenant_a = _seed_tenant(migrated_database)
    tenant_b = _seed_tenant(migrated_database)
    repo_a = PostgresMappingRepository(
        migrated_database, assertion=signed_assertion(tenant_a)
    )
    release = _release()
    repo_a.propose(
        release, tenant_id=str(tenant_a), proposer_actor_id="architect-1", rationale="pilot gap"
    )

    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(f"SET ROLE {APP_ROLE}")
        with connection.transaction():
            connection.execute(
                "SELECT cairn_set_tenant_context(%s)", (signed_assertion(tenant_b),)
            )
            rows = connection.execute(
                "SELECT * FROM mapping_proposal WHERE version = %s", (release.version,)
            ).fetchall()
    assert rows == []


def test_mapping_proposal_rls_is_enabled_and_forced(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        row = connection.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = 'mapping_proposal'"
        ).fetchone()
    assert row == (True, True)


def test_mapping_release_has_no_rls(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        row = connection.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = 'mapping_release'"
        ).fetchone()
    assert row == (False, False)
