ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tenant
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE app_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_user FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON app_user
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE role_grant ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_grant FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON role_grant
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE project ENABLE ROW LEVEL SECURITY;
ALTER TABLE project FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON project
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY project_isolation ON project
  AS RESTRICTIVE
  USING (project_id = nullif(current_setting('app.project_id', true), '')::uuid)
  WITH CHECK (project_id = nullif(current_setting('app.project_id', true), '')::uuid);
