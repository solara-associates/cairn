import pytest
from cairn_kernel import tenancy
from cairn_kernel.tenancy.classification import (
    PROJECT_OWNED_TABLES,
    PROJECT_POLICY,
    REQUIRED_POLICIES,
    RLS_TABLES,
    TABLE_CLASSIFICATIONS,
    TENANCY_CLASSIFICATION,
    TENANT_OWNED_TABLES,
    TENANT_POLICY,
    TenancyScope,
    classify_table,
)


def test_every_table_has_exactly_one_classification() -> None:
    assert len(TABLE_CLASSIFICATIONS) == len(TENANCY_CLASSIFICATION)
    for classification in TABLE_CLASSIFICATIONS:
        assert TENANCY_CLASSIFICATION[classification.table] is classification.scope


def test_tenancy_baseline_tables_are_classified() -> None:
    assert set(TENANT_OWNED_TABLES) == {
        "tenant",
        "app_user",
        "role_grant",
        "ledger_entry",
    }
    assert set(PROJECT_OWNED_TABLES) == {
        "project",
        "subject_revision",
        "approval",
        "execution_record",
    }
    assert TENANCY_CLASSIFICATION["schema_migration"] is TenancyScope.GLOBAL


def test_rls_tables_are_the_tenant_and_project_owned_tables() -> None:
    assert set(RLS_TABLES) == set(TENANT_OWNED_TABLES) | set(PROJECT_OWNED_TABLES)
    assert "schema_migration" not in RLS_TABLES


def test_required_policies_match_the_scope() -> None:
    assert REQUIRED_POLICIES[TenancyScope.GLOBAL] == ()
    assert REQUIRED_POLICIES[TenancyScope.TENANT] == (TENANT_POLICY,)
    assert REQUIRED_POLICIES[TenancyScope.PROJECT] == (TENANT_POLICY, PROJECT_POLICY)


def test_classify_table_rejects_unknown_tables() -> None:
    with pytest.raises(KeyError, match="no tenancy classification"):
        classify_table("unclassified_table")


def test_classification_is_exported_from_the_tenancy_package() -> None:
    assert tenancy.classify_table("project") is TenancyScope.PROJECT
    assert tenancy.TENANCY_CLASSIFICATION["app_user"] is TenancyScope.TENANT
