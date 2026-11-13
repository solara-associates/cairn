-- R1-19 (early slice, R-TENANT-03): reject a tenant-context *change*
-- attempt mid-transaction. ADR-012 requires that "tenant-context change
-- attempts, including session-variable and SET LOCAL tricks, are rejected
-- and audited." cairn_set_tenant_context previously overwrote the bound
-- context unconditionally on every call, so a second call within the same
-- transaction that named a *different* tenant silently pivoted the
-- already-established context instead of being rejected.
--
-- Re-asserting the *same* tenant within one transaction stays legal and
-- is a no-op write (idempotent) -- ledger_verifier.verify_ledger and other
-- read-only utilities call cairn_set_tenant_context defensively on every
-- use and may be invoked more than once per connection/transaction for
-- the same tenant; that is not a context-change attempt. Changing tenant
-- (or the embedded actor) mid-transaction always is, and is now refused;
-- the caller must open a new transaction to change tenant context
-- (already proven transaction-local by test_context_is_transaction_local).
CREATE OR REPLACE FUNCTION cairn_set_tenant_context(p_assertion text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  document jsonb;
  existing_assertion text;
  existing_document jsonb;
BEGIN
  document := cairn_verify_assertion(p_assertion);
  IF document IS NULL THEN
    RAISE EXCEPTION 'invalid tenant assertion' USING ERRCODE = '42501';
  END IF;
  existing_assertion := current_setting('app.tenant_assertion', true);
  IF existing_assertion IS NOT NULL AND existing_assertion <> '' THEN
    existing_document := cairn_verify_assertion(existing_assertion);
    IF existing_document IS NULL
      OR existing_document->>'tenant_id' IS DISTINCT FROM document->>'tenant_id'
      OR existing_document->>'actor_id' IS DISTINCT FROM document->>'actor_id'
    THEN
      RAISE EXCEPTION
        'tenant context change rejected: context is already bound for this transaction'
        USING ERRCODE = '42501';
    END IF;
  END IF;
  PERFORM set_config('app.tenant_assertion', p_assertion, true);
  PERFORM set_config('app.tenant_id', document->>'tenant_id', true);
  PERFORM set_config('app.actor_id', document->>'actor_id', true);
  PERFORM set_config('app.project_id', '', true);
END;
$$;
