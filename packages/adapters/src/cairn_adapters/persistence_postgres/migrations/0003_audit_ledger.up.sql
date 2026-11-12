CREATE TABLE ledger_entry (
  entry_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  project_id       uuid,
  package_id       uuid,
  sequence         bigint NOT NULL,
  entry_hash       text NOT NULL,
  previous_hash    text,
  actor            text NOT NULL,
  action           text NOT NULL,
  operation_class  text NOT NULL CHECK (operation_class IN ('READ','WORKSPACE_MUTATION','GOVERNED_ENV_MUTATION')),
  payload          jsonb NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sequence),
  UNIQUE (tenant_id, project_id, sequence),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id)
);

CREATE FUNCTION ledger_entry_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ledger_entry is append-only';
END;
$$;

CREATE TRIGGER ledger_entry_append_only
  BEFORE UPDATE OR DELETE ON ledger_entry
  FOR EACH ROW EXECUTE FUNCTION ledger_entry_reject_mutation();

CREATE TRIGGER ledger_entry_no_truncate
  BEFORE TRUNCATE ON ledger_entry
  FOR EACH STATEMENT EXECUTE FUNCTION ledger_entry_reject_mutation();

ALTER TABLE ledger_entry ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_entry FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON ledger_entry
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
