CREATE TABLE tenant_context_secret (
  name             text PRIMARY KEY,
  secret           bytea NOT NULL
);

CREATE FUNCTION cairn_verify_assertion(p_assertion text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  parts text[];
  encoded_payload text;
  encoded_payload_b64 text;
  encoded_signature text;
  payload text;
  expected_signature text;
  stored_secret bytea;
  document jsonb;
BEGIN
  IF p_assertion IS NULL OR p_assertion = '' THEN
    RETURN NULL;
  END IF;
  parts := string_to_array(p_assertion, '.');
  IF coalesce(array_length(parts, 1), 0) <> 2 THEN
    RETURN NULL;
  END IF;
  encoded_payload := parts[1];
  encoded_signature := parts[2];
  SELECT secret INTO stored_secret
    FROM tenant_context_secret WHERE name = 'tenant-context';
  IF stored_secret IS NULL THEN
    RETURN NULL;
  END IF;
  BEGIN
    encoded_payload_b64 := translate(encoded_payload, '-_', '+/');
    encoded_payload_b64 := encoded_payload_b64
      || repeat('=', (4 - length(encoded_payload_b64) % 4) % 4);
    payload := convert_from(decode(encoded_payload_b64, 'base64'), 'UTF8');
    expected_signature := rtrim(
      translate(
        encode(
          hmac(convert_to(payload, 'UTF8'), stored_secret, 'sha256'),
          'base64'
        ),
        '+/',
        '-_'
      ),
      '='
    );
    IF expected_signature <> encoded_signature THEN
      RETURN NULL;
    END IF;
    document := payload::jsonb;
  EXCEPTION WHEN others THEN
    RETURN NULL;
  END;
  IF document->>'tenant_id' IS NULL OR document->>'actor_id' IS NULL THEN
    RETURN NULL;
  END IF;
  IF (document->>'exp') IS NULL
    OR (document->>'exp')::bigint <= extract(epoch FROM now())::bigint THEN
    RETURN NULL;
  END IF;
  IF (document->>'tenant_id') !~*
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
    RETURN NULL;
  END IF;
  IF document ? 'project_id'
    AND document->>'project_id' IS NOT NULL
    AND (document->>'project_id') !~*
      '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
    RETURN NULL;
  END IF;
  RETURN document;
END;
$$;

CREATE FUNCTION cairn_current_tenant() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT nullif(
    cairn_verify_assertion(current_setting('app.tenant_assertion', true))->>'tenant_id',
    ''
  )::uuid
$$;

CREATE FUNCTION cairn_current_project() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT nullif(
    cairn_verify_assertion(current_setting('app.tenant_assertion', true))->>'project_id',
    ''
  )::uuid
$$;

CREATE FUNCTION cairn_set_tenant_context(p_assertion text) RETURNS void
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

CREATE FUNCTION cairn_set_project_context(p_project uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF cairn_current_tenant() IS NULL THEN
    RAISE EXCEPTION 'tenant context is not established' USING ERRCODE = '42501';
  END IF;
  IF cairn_current_project() IS DISTINCT FROM p_project THEN
    RAISE EXCEPTION 'project is outside the tenant context' USING ERRCODE = '42501';
  END IF;
  PERFORM set_config('app.project_id', p_project::text, true);
END;
$$;

DROP POLICY tenant_isolation ON tenant;
CREATE POLICY tenant_isolation ON tenant
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());

DROP POLICY tenant_isolation ON app_user;
CREATE POLICY tenant_isolation ON app_user
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());

DROP POLICY tenant_isolation ON project;
DROP POLICY project_isolation ON project;
CREATE POLICY tenant_isolation ON project
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());
CREATE POLICY project_isolation ON project
  AS RESTRICTIVE
  USING (project_id = cairn_current_project())
  WITH CHECK (project_id = cairn_current_project());

DROP POLICY tenant_isolation ON role_grant;
CREATE POLICY tenant_isolation ON role_grant
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());

DROP POLICY tenant_isolation ON ledger_entry;
CREATE POLICY tenant_isolation ON ledger_entry
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());
