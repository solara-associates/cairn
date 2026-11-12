# CA-002: tenant isolation trust boundary

## Problem

RLS policies trusted `current_setting('app.tenant_id')`. Any holder of the application database credentials could call `set_config` itself and choose another tenant's context. The database had no way to tell a server-established context from a spoofed one.

## Decision

Tenant context is established from a signed assertion, not from a self-declared session value.

- The application server signs `{tenant_id, actor_id, exp, project_id?}` with HMAC-SHA256 using a secret that only the server and the database context function know. `sign_tenant_assertion` lives in `cairn_kernel.security`.
- `tenant_context_secret` stores the key. It has no RLS and no grants to the application role; only the migration role and the SECURITY DEFINER functions can read it.
- `cairn_set_tenant_context(assertion)` verifies the signature, expiry and claim shape, then sets `app.tenant_assertion`, `app.tenant_id` and `app.actor_id` for the transaction.
- RLS policies no longer read `app.tenant_id`. They call `cairn_current_tenant()`, which re-verifies the assertion on every evaluation. A spoofed session variable or forged assertion yields null and denies access.
- Project isolation uses `cairn_current_project()`, the signed `project_id` claim. `cairn_set_project_context` refuses a project id that is not in the assertion. The server performs the tenant-scoped project lookup before signing, as required by spec section 8.4.
- Application connections keep only table privileges they need. `ledger_entry` remains insert and select only. The application role is not a member of any administrative role and has `NOBYPASSRLS`.

## Operating notes

- Bootstrap the signing secret once per database, from the secret manager:
  `INSERT INTO tenant_context_secret (name, secret) VALUES ('tenant-context', :secret);`
- Rotate by updating that row. Existing assertions fail verification immediately and callers must re-authenticate.
- `AuthMiddleware` now requires `assertion_secret` and puts the signed assertion in `scope["state"]["tenant_assertion"]` with a five-minute TTL.

## Residual risk

A compromised signing secret or the database owner can mint valid assertions. The secret belongs in the platform secret manager, and the owner role is reserved for migrations and break-glass use, both audited.

## Acceptance evidence

`tests/integration/test_tenant_security.py` covers: valid binding, spoofed `app.tenant_id`, forged assertion, expired assertion, missing context, cross-tenant insert, cross-tenant update, project outside the assertion, project from another tenant, transaction-local reset, secret rotation, and application-role privileges.

`tests/integration/test_migrations.py`, `tests/integration/test_audit.py` and `apps/api/tests/test_auth_middleware.py` were updated to use signed assertions; all pass.
