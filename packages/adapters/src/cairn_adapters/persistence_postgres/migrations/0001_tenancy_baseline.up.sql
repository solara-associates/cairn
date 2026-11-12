CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE tenant (
  tenant_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name             text NOT NULL,
  status           text NOT NULL DEFAULT 'ACTIVE',
  retention_days   integer NOT NULL DEFAULT 365,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
  user_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  subject          text NOT NULL,
  email            text,
  status           text NOT NULL DEFAULT 'ACTIVE',
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, subject),
  UNIQUE (tenant_id, user_id)
);

CREATE TABLE project (
  project_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  customer_name    text NOT NULL,
  name             text NOT NULL,
  scope            text,
  providers        text[] NOT NULL DEFAULT '{}',
  regions          text[] NOT NULL DEFAULT '{}',
  assessment_start date,
  assessment_end   date,
  selected_modules text[] NOT NULL DEFAULT '{}',
  retention_days   integer,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, project_id)
);

CREATE TABLE role_grant (
  grant_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenant(tenant_id),
  user_id          uuid NOT NULL,
  project_id       uuid,
  role             text NOT NULL CHECK (role IN ('TENANT_ADMIN','PROJECT_OWNER','ARCHITECT','ENGINEER','REVIEWER','AUDITOR','VIEWER')),
  granted_by       uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app_user(tenant_id, user_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  UNIQUE NULLS NOT DISTINCT (tenant_id, user_id, project_id)
);
