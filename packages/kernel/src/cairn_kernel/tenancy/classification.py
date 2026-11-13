from dataclasses import dataclass
from enum import Enum


class TenancyScope(str, Enum):
    GLOBAL = "GLOBAL"
    TENANT = "TENANT"
    PROJECT = "PROJECT"


@dataclass(frozen=True, slots=True)
class TableClassification:
    table: str
    scope: TenancyScope


TENANT_COLUMN = "tenant_id"
PROJECT_COLUMN = "project_id"

TENANT_POLICY = "tenant_isolation"
PROJECT_POLICY = "project_isolation"

REQUIRED_POLICIES: dict[TenancyScope, tuple[str, ...]] = {
    TenancyScope.GLOBAL: (),
    TenancyScope.TENANT: (TENANT_POLICY,),
    TenancyScope.PROJECT: (TENANT_POLICY, PROJECT_POLICY),
}

TABLE_CLASSIFICATIONS: tuple[TableClassification, ...] = (
    TableClassification(table="tenant", scope=TenancyScope.TENANT),
    TableClassification(table="app_user", scope=TenancyScope.TENANT),
    TableClassification(table="project", scope=TenancyScope.PROJECT),
    TableClassification(table="role_grant", scope=TenancyScope.TENANT),
    TableClassification(table="ledger_entry", scope=TenancyScope.TENANT),
    TableClassification(table="subject_revision", scope=TenancyScope.PROJECT),
    TableClassification(table="approval", scope=TenancyScope.PROJECT),
    TableClassification(table="execution_record", scope=TenancyScope.PROJECT),
    TableClassification(table="schema_migration", scope=TenancyScope.GLOBAL),
    TableClassification(table="schema_migration_history", scope=TenancyScope.GLOBAL),
    TableClassification(table="tenant_context_secret", scope=TenancyScope.GLOBAL),
)

TENANCY_CLASSIFICATION: dict[str, TenancyScope] = {
    classification.table: classification.scope for classification in TABLE_CLASSIFICATIONS
}

TENANT_OWNED_TABLES: tuple[str, ...] = tuple(
    classification.table
    for classification in TABLE_CLASSIFICATIONS
    if classification.scope is TenancyScope.TENANT
)

PROJECT_OWNED_TABLES: tuple[str, ...] = tuple(
    classification.table
    for classification in TABLE_CLASSIFICATIONS
    if classification.scope is TenancyScope.PROJECT
)

RLS_TABLES: tuple[str, ...] = TENANT_OWNED_TABLES + PROJECT_OWNED_TABLES


def classify_table(table: str) -> TenancyScope:
    try:
        return TENANCY_CLASSIFICATION[table]
    except KeyError:
        raise KeyError(f"table {table!r} has no tenancy classification") from None
