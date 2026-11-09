# ADR-007: PostgreSQL for OLTP and registry metadata, BigQuery for analytics

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §8, ADR-003, ADR-012

## Context

CAIRN needs transactional guarantees for tenancy, projects, jobs, approvals, audit indices and mapping metadata, and it needs scalable analytical queries over raw inventory, findings and cost facts. Using one store for both either weakens transactions or weakens analytics.

## Decision

- **PostgreSQL (Cloud SQL):** source of truth for tenants, projects, users, roles, connections, job state, approvals, evidence indices, mapping release metadata and audit. The instance is Cloud SQL for PostgreSQL, primary region `europe-west2` (London).
- **BigQuery:** raw, curated and consumption datasets for estate observations, findings, cost facts and analytics.
- **No dual source of truth.** Analytical tables are derived from Postgres or ingestion via events/ELT; they are not written independently as authoritative state.
- Tenant scoping and RLS apply in Postgres; BigQuery access is scoped by dataset and authorized views.

## Consequences

**Positive**

- Clear source-of-truth boundaries and strong transactional behaviour.
- Analytics scale without loading the OLTP database.
- Retention and cost controls are separable per store.

**Negative**

- Two systems to operate, secure and back up.
- Cross-store consistency is eventual and must be designed for.
- Analytics latency for freshly written state.

**Neutral**

- Registry and evidence metadata stay in Postgres; bulk facts and observations go to BigQuery.

## Alternatives considered

1. **BigQuery only.** Great analytics, poor fit for queues, approvals and fine-grained transactional tenancy.
2. **Postgres only.** Simple, but costly and awkward for large scan and cost fact volumes.
3. **Warehouse-first with a separate metadata store.** Similar outcome with more moving parts.

## If rejected

Expect either duplicate truth or an analytics platform that cannot answer estate-wide questions at acceptable cost.
