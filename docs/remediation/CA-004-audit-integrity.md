# CA-004 / CA-005: audit integrity and immutable payloads

## Problem

The audit ledger was append-only by trigger, but nothing could prove that the stored chain was intact. Payloads were plain dictionaries: callers could mutate them after the entry was built, and the hash input was not canonical, so a verifier could compute a different digest for the same data.

## Decision

### Canonical, immutable payloads (CA-005)

`cairn_kernel.security.canonical_json` produces one canonical byte sequence for a value:

- object keys sorted by UTF-16 code units, as required by RFC 8785 style canonical JSON;
- non-finite numbers, unsafe integers, non-string keys, bytes and arbitrary objects are rejected;
- strings are emitted as UTF-8 JSON with minimal escaping.

`AuditEntry` canonicalises and deep-freezes its payload at construction. Nested mappings become `MappingProxyType`, sequences become tuples, and later mutation of the caller's dictionary cannot change the entry. `entry.payload_json` is the exact string that is hashed and stored, and the correlation id is merged into it.

`entry_hash` lives in the kernel, so the writer and the verifier share one implementation.

### Verification (CA-004)

`cairn_adapters.persistence_postgres.ledger_verifier.verify_ledger(connection, tenant_id, assertion, expected_latest_hash=...)`:

- binds the signed tenant context and refuses to verify a tenant other than the assertion's;
- reads the tenant's entries in sequence order with a read-only SELECT;
- checks sequence continuity, first-entry `previous_hash` = NULL, per-entry linkage, and recomputes every hash;
- reports `valid`, `entries_checked`, `first_invalid_sequence`, `reason` and `latest_hash`;
- optionally compares `latest_hash` to a trusted external anchor.

CLI: `python -m cairn_adapters.persistence_postgres.ledger_verifier --tenant ... --assertion ... [--expected-hash ...]`, exit 0 valid, 1 invalid.

Timestamp `created_at` is now set by the writer and included in the hash, so a modified timestamp is detected as well.

## Threat model

A privileged identity (table owner, superuser) can disable the append-only trigger and rewrite rows. Tests exercise exactly that: tamper helpers run as the owner, disable `ledger_entry_append_only`, modify rows and re-enable the trigger. Verification detects payload edits, actor edits, deleted entries, and inserted entries with a broken link, and reports the first invalid sequence.

A privileged attacker who rewrites the whole chain and recomputes every hash is only detectable against an anchor the database cannot rewrite. The latest hash must therefore be published to WORM storage or an external log, and verification must pass `expected_latest_hash`. This residual risk is accepted until the anchoring service exists.

## Acceptance evidence

- `packages/kernel/tests/test_canonical.py`: canonical ordering, unicode, rejected values, deep freezing, input mutation isolation, correlation id in the hashed payload.
- `tests/integration/test_ledger_verification.py`: empty and valid chains, payload tamper, actor tamper, deleted entry, forged inserted entry, tenant scoping, forged assertion, trusted anchor.
- Full suite green, `make lint` green.
