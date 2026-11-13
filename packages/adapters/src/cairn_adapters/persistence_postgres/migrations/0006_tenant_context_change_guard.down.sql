-- Revert cairn_set_tenant_context to its pre-guard (0004) definition, which
-- unconditionally (re-)binds the tenant context on every call.
CREATE OR REPLACE FUNCTION cairn_set_tenant_context(p_assertion text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  document jsonb;
BEGIN
  document := cairn_verify_assertion(p_assertion);
  IF document IS NULL THEN
    RAISE EXCEPTION 'invalid tenant assertion' USING ERRCODE = '42501';
  END IF;
  PERFORM set_config('app.tenant_assertion', p_assertion, true);
  PERFORM set_config('app.tenant_id', document->>'tenant_id', true);
  PERFORM set_config('app.actor_id', document->>'actor_id', true);
  PERFORM set_config('app.project_id', '', true);
END;
$$;
