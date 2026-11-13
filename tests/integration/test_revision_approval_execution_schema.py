"""R1-21: the immutable revision/approval/execution schema (migration 0005),
proven live against Postgres under the application role (R-REV-01,
R-MUT-02). ADR-009, ADR-010.

These are the DB half of the invariants
packages/modules/tests/test_approvals_transitions.py and
test_execution_transitions.py prove in the application layer: the database
is the source of truth, so every check here runs under ``cairn_app`` with
RLS forced, never as the migration superuser.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from conftest import signed_assertion

APP_ROLE = "cairn_app"


@contextmanager
def app_role_session(
    dsn: str, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"SET ROLE {APP_ROLE}")
        with connection.transaction():
            connection.execute(
                "SELECT cairn_set_tenant_context(%s)",
                (signed_assertion(tenant_id, project_id),),
            )
            connection.execute("SELECT cairn_set_project_context(%s)", (project_id,))
            yield connection


def _seed_project(dsn: str) -> dict[str, uuid.UUID]:
    ids = {
        "tenant": uuid.uuid4(),
        "project": uuid.uuid4(),
        "subject": uuid.uuid4(),
    }
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


def _insert_revision(
    connection: psycopg.Connection,
    ids: dict[str, uuid.UUID],
    *,
    revision_number: int,
    content_hash: str = "sha256:abc123",
) -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO subject_revision"
        " (tenant_id, project_id, subject_kind, subject_id, revision_number,"
        "  content_hash, created_by)"
        " VALUES (%s, %s, 'MIGRATION_PLAN', %s, %s, %s, 'alice')"
        " RETURNING revision_id",
        (ids["tenant"], ids["project"], ids["subject"], revision_number, content_hash),
    ).fetchone()
    assert row is not None
    return row[0]


def _insert_approval(
    connection: psycopg.Connection,
    ids: dict[str, uuid.UUID],
    revision_id: uuid.UUID,
    *,
    revision_hash: str = "sha256:abc123",
    mutation_class: str = "INTERNAL_MUTATION",
    proposer: str = "bob",
) -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO approval"
        " (tenant_id, project_id, subject_kind, subject_id, revision_id, revision_hash,"
        "  mutation_class, risk_tier, proposer_actor_id)"
        " VALUES (%s, %s, 'MIGRATION_PLAN', %s, %s, %s, %s, 'LOW', %s)"
        " RETURNING approval_id",
        (
            ids["tenant"],
            ids["project"],
            ids["subject"],
            revision_id,
            revision_hash,
            mutation_class,
            proposer,
        ),
    ).fetchone()
    assert row is not None
    return row[0]


# --- subject_revision is append-only and DB-bound -------------------------


def test_revision_insert_succeeds_and_is_readable(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        row = connection.execute(
            "SELECT content_hash FROM subject_revision WHERE revision_id = %s",
            (revision_id,),
        ).fetchone()
        assert row == ("sha256:abc123",)


def test_revision_update_is_rejected_under_app_role(migrated_database: str) -> None:
    """The application role has no UPDATE grant on subject_revision at all
    (least privilege); the append-only trigger is the second, independent
    layer, proven directly against the trigger function itself below."""

    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE subject_revision SET content_hash = 'tampered' WHERE revision_id = %s",
                (revision_id,),
            )


def test_revision_append_only_trigger_rejects_mutation_even_with_privilege(
    migrated_database: str,
) -> None:
    """Prove the trigger itself (not only the role grant) rejects mutation,
    by running as the migration superuser, which still has UPDATE/DELETE."""

    ids = _seed_project(migrated_database)
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO subject_revision"
            " (tenant_id, project_id, subject_kind, subject_id, revision_number,"
            "  content_hash, created_by)"
            " VALUES (%s, %s, 'MIGRATION_PLAN', %s, 1, 'sha256:abc123', 'alice')"
            " RETURNING revision_id",
            (ids["tenant"], ids["project"], ids["subject"]),
        )
        revision_id = connection.execute(
            "SELECT revision_id FROM subject_revision WHERE tenant_id = %s", (ids["tenant"],)
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
            connection.execute(
                "UPDATE subject_revision SET content_hash = 'tampered' WHERE revision_id = %s",
                (revision_id,),
            )


def test_revision_delete_is_rejected_under_app_role(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "DELETE FROM subject_revision WHERE revision_id = %s", (revision_id,)
            )


def test_revision_number_must_be_monotonic_per_subject(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        _insert_revision(connection, ids, revision_number=1)
        # a gap (2 skipped) is rejected, not only a duplicate
        with pytest.raises(psycopg.errors.CheckViolation, match="monotonic"):
            connection.execute(
                "INSERT INTO subject_revision"
                " (tenant_id, project_id, subject_kind, subject_id, revision_number,"
                "  content_hash, created_by)"
                " VALUES (%s, %s, 'MIGRATION_PLAN', %s, 3, 'sha256:def456', 'alice')",
                (ids["tenant"], ids["project"], ids["subject"]),
            )


def test_revision_number_rejects_a_repeat(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        _insert_revision(connection, ids, revision_number=1)
        with pytest.raises(psycopg.errors.CheckViolation, match="monotonic"):
            connection.execute(
                "INSERT INTO subject_revision"
                " (tenant_id, project_id, subject_kind, subject_id, revision_number,"
                "  content_hash, created_by)"
                " VALUES (%s, %s, 'MIGRATION_PLAN', %s, 1, 'sha256:def456', 'alice')",
                (ids["tenant"], ids["project"], ids["subject"]),
            )


def test_second_revision_is_accepted_in_sequence(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        _insert_revision(connection, ids, revision_number=1)
        second = _insert_revision(connection, ids, revision_number=2, content_hash="sha256:v2")
        assert second is not None


# --- approval binds to the exact revision row and hash, DB-enforced -------


def test_approval_binds_to_the_exact_revision_and_hash(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id)
        assert approval_id is not None


def test_approval_with_wrong_hash_violates_the_composite_foreign_key(
    migrated_database: str,
) -> None:
    """The core ADR-009 claim: the revision hash is DB-bound, not only
    application-checked. Proven under the application role, the same role
    production traffic uses — a superuser bypass would not prove this."""

    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _insert_approval(connection, ids, revision_id, revision_hash="sha256:not-the-hash")


def test_approval_with_unknown_revision_id_violates_the_foreign_key(
    migrated_database: str,
) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        _insert_revision(connection, ids, revision_number=1)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _insert_approval(connection, ids, uuid.uuid4())


# --- compensation-contract completeness blocks APPROVED -------------------


def test_internal_mutation_approves_without_a_compensation_contract(
    migrated_database: str,
) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        connection.execute(
            "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
            (approval_id,),
        )
        connection.execute(
            "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice'"
            " WHERE approval_id = %s",
            (approval_id,),
        )
        row = connection.execute(
            "SELECT state FROM approval WHERE approval_id = %s", (approval_id,)
        ).fetchone()
        assert row == ("APPROVED",)


def test_external_mutation_without_recovery_plan_cannot_reach_approved(
    migrated_database: str,
) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(
            connection,
            ids,
            revision_id,
            mutation_class="REVERSIBLE_EXTERNAL_MUTATION",
            proposer="bob",
        )
        connection.execute(
            "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
            (approval_id,),
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="compensation contract"):
            connection.execute(
                "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice'"
                " WHERE approval_id = %s",
                (approval_id,),
            )


def test_external_mutation_with_complete_contract_reaches_approved(
    migrated_database: str,
) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(
            connection,
            ids,
            revision_id,
            mutation_class="REVERSIBLE_EXTERNAL_MUTATION",
            proposer="bob",
        )
        connection.execute(
            "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
            (approval_id,),
        )
        connection.execute(
            "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice',"
            " compensation_strategy = 'ROLLBACK',"
            " compensation_plan_ref = 'recovery-plan://1',"
            " compensation_preconditions = 'scoped',"
            " compensation_authority = 'PROJECT_OWNER',"
            " compensation_evidence = 'before/after',"
            " compensation_failure_handling = 'escalate'"
            " WHERE approval_id = %s",
            (approval_id,),
        )
        row = connection.execute(
            "SELECT state FROM approval WHERE approval_id = %s", (approval_id,)
        ).fetchone()
        assert row == ("APPROVED",)


def test_irreversible_mutation_requires_accept_irreversible_strategy(
    migrated_database: str,
) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(
            connection,
            ids,
            revision_id,
            mutation_class="IRREVERSIBLE_EXTERNAL_MUTATION",
            proposer="bob",
        )
        connection.execute(
            "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
            (approval_id,),
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="compensation contract"):
            connection.execute(
                "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice',"
                " compensation_strategy = 'ROLLBACK',"
                " compensation_plan_ref = 'recovery-plan://1',"
                " compensation_preconditions = 'scoped',"
                " compensation_authority = 'PROJECT_OWNER',"
                " compensation_evidence = 'before/after',"
                " compensation_failure_handling = 'escalate'"
                " WHERE approval_id = %s",
                (approval_id,),
            )


# --- separation of duties, DB-enforced -------------------------------------


def test_approver_cannot_equal_proposer(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        connection.execute(
            "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
            (approval_id,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'bob'"
                " WHERE approval_id = %s",
                (approval_id,),
            )


# --- approval state transitions, DB-enforced --------------------------------


def test_approval_cannot_skip_pending_approval(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        with pytest.raises(psycopg.errors.CheckViolation, match="cannot move"):
            connection.execute(
                "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice'"
                " WHERE approval_id = %s",
                (approval_id,),
            )


def test_approval_cannot_leave_a_terminal_state(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        connection.execute(
            "UPDATE approval SET state = 'CANCELLED' WHERE approval_id = %s", (approval_id,)
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="cannot move"):
            connection.execute(
                "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
                (approval_id,),
            )


# --- execution_record matches its approval and respects the state machine --


def _approve(connection: psycopg.Connection, approval_id: uuid.UUID) -> None:
    connection.execute(
        "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
        (approval_id,),
    )
    connection.execute(
        "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice'"
        " WHERE approval_id = %s",
        (approval_id,),
    )


def test_execution_record_requires_an_approved_approval(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        with pytest.raises(psycopg.errors.CheckViolation, match="not APPROVED"):
            connection.execute(
                "INSERT INTO execution_record"
                " (tenant_id, project_id, approval_id, revision_id, approved_hash,"
                "  mutation_class, actor_id, correlation_id)"
                " VALUES (%s, %s, %s, %s, 'sha256:abc123', 'INTERNAL_MUTATION', 'bob', 'corr-1')",
                (ids["tenant"], ids["project"], approval_id, revision_id),
            )


def test_execution_record_rejects_a_mismatched_hash(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        _approve(connection, approval_id)
        with pytest.raises(psycopg.errors.CheckViolation, match="does not match"):
            connection.execute(
                "INSERT INTO execution_record"
                " (tenant_id, project_id, approval_id, revision_id, approved_hash,"
                "  mutation_class, actor_id, correlation_id)"
                " VALUES (%s, %s, %s, %s, 'sha256:tampered', 'INTERNAL_MUTATION',"
                " 'bob', 'corr-1')",
                (ids["tenant"], ids["project"], approval_id, revision_id),
            )


def test_execution_record_succeeds_when_bound_correctly(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        _approve(connection, approval_id)
        row = connection.execute(
            "INSERT INTO execution_record"
            " (tenant_id, project_id, approval_id, revision_id, approved_hash,"
            "  mutation_class, actor_id, correlation_id)"
            " VALUES (%s, %s, %s, %s, 'sha256:abc123', 'INTERNAL_MUTATION', 'bob', 'corr-1')"
            " RETURNING execution_id",
            (ids["tenant"], ids["project"], approval_id, revision_id),
        ).fetchone()
        assert row is not None


def test_execution_record_cannot_skip_authorized(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        _approve(connection, approval_id)
        execution_id = connection.execute(
            "INSERT INTO execution_record"
            " (tenant_id, project_id, approval_id, revision_id, approved_hash,"
            "  mutation_class, actor_id, correlation_id)"
            " VALUES (%s, %s, %s, %s, 'sha256:abc123', 'INTERNAL_MUTATION', 'bob', 'corr-1')"
            " RETURNING execution_id",
            (ids["tenant"], ids["project"], approval_id, revision_id),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation, match="cannot move"):
            connection.execute(
                "UPDATE execution_record SET state = 'EXECUTING' WHERE execution_id = %s",
                (execution_id,),
            )


def test_execution_record_full_lifecycle_to_succeeded(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(connection, ids, revision_id, proposer="bob")
        _approve(connection, approval_id)
        execution_id = connection.execute(
            "INSERT INTO execution_record"
            " (tenant_id, project_id, approval_id, revision_id, approved_hash,"
            "  mutation_class, actor_id, correlation_id)"
            " VALUES (%s, %s, %s, %s, 'sha256:abc123', 'INTERNAL_MUTATION', 'bob', 'corr-1')"
            " RETURNING execution_id",
            (ids["tenant"], ids["project"], approval_id, revision_id),
        ).fetchone()[0]
        for target in ("AUTHORIZED", "EXECUTING", "SUCCEEDED"):
            connection.execute(
                "UPDATE execution_record SET state = %s WHERE execution_id = %s",
                (target, execution_id),
            )
        row = connection.execute(
            "SELECT state FROM execution_record WHERE execution_id = %s", (execution_id,)
        ).fetchone()
        assert row == ("SUCCEEDED",)


def test_irreversible_execution_cannot_roll_back(migrated_database: str) -> None:
    ids = _seed_project(migrated_database)
    with app_role_session(migrated_database, ids["tenant"], ids["project"]) as connection:
        revision_id = _insert_revision(connection, ids, revision_number=1)
        approval_id = _insert_approval(
            connection,
            ids,
            revision_id,
            mutation_class="IRREVERSIBLE_EXTERNAL_MUTATION",
            proposer="bob",
        )
        connection.execute(
            "UPDATE approval SET state = 'PENDING_APPROVAL' WHERE approval_id = %s",
            (approval_id,),
        )
        connection.execute(
            "UPDATE approval SET state = 'APPROVED', approver_actor_id = 'alice',"
            " compensation_strategy = 'ACCEPT_IRREVERSIBLE',"
            " compensation_plan_ref = 'risk-acceptance://1',"
            " compensation_preconditions = 'blast radius declared',"
            " compensation_authority = 'TENANT_ADMIN',"
            " compensation_evidence = 'preflight dry-run',"
            " compensation_failure_handling = 'escalate; residual risk recorded'"
            " WHERE approval_id = %s",
            (approval_id,),
        )
        execution_id = connection.execute(
            "INSERT INTO execution_record"
            " (tenant_id, project_id, approval_id, revision_id, approved_hash,"
            "  mutation_class, actor_id, correlation_id)"
            " VALUES (%s, %s, %s, %s, 'sha256:abc123', 'IRREVERSIBLE_EXTERNAL_MUTATION',"
            " 'bob', 'corr-1')"
            " RETURNING execution_id",
            (ids["tenant"], ids["project"], approval_id, revision_id),
        ).fetchone()[0]
        for target in ("AUTHORIZED", "EXECUTING"):
            connection.execute(
                "UPDATE execution_record SET state = %s WHERE execution_id = %s",
                (target, execution_id),
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="cannot transition"):
            connection.execute(
                "UPDATE execution_record SET state = %s WHERE execution_id = %s",
                ("ROLLED_BACK", execution_id),
            )
