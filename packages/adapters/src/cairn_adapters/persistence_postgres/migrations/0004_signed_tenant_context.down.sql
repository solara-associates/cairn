DROP POLICY tenant_isolation ON ledger_entry;
CREATE POLICY tenant_isolation ON ledger_entry
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

DROP POLICY tenant_isolation ON role_grant;
CREATE POLICY tenant_isolation ON role_grant
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

DROP POLICY tenant_isolation ON project;
DROP POLICY project_isolation ON project;
CREATE POLICY tenant_isolation ON project
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY project_isolation ON project
  AS RESTRICTIVE
  USING (project_id = nullif(current_setting('app.project_id', true), '')::uuid)
  WITH CHECK (project_id = nullif(current_setting('app.project_id', true), '')::uuid);

DROP POLICY tenant_isolation ON app_user;
CREATE POLICY tenant_isolation ON app_user
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

DROP POLICY tenant_isolation ON tenant;
CREATE POLICY tenant_isolation ON tenant
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

DROP FUNCTION IF EXISTS cairn_set_project_context(uuid);
DROP FUNCTION IF EXISTS cairn_set_tenant_context(text);
DROP FUNCTION IF EXISTS cairn_current_project();
DROP FUNCTION IF EXISTS cairn_current_tenant();
DROP FUNCTION IF EXISTS cairn_verify_assertion(text);
DROP TABLE IF EXISTS tenant_context_secret;
