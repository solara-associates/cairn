-- R3-03b: persisting one transformation run (ADR-015's manifest
-- requirement) as a dedicated, append-only table.
--
-- 721/722/723's `tests/test_source_git.py` explicitly left this as 726's
-- job: "726 is expected to add that persistence layer when it needs to
-- reference a fetched source set from a transformation run."
--
-- Checked first, per the brief's step 4: does `subject_revision`
-- (migration 0005) fit? It does not, cleanly. `subject_revision` is
-- shaped for one subject producing one content_hash per revision
-- (`UNIQUE (tenant_id, project_id, revision_id, content_hash)`) -- a
-- design or plan is one artefact with one hash. A transformation run is
-- structurally different: it takes an ordered *set* of source files (a
-- `RepositoryRef`, R3-01) and produces one manifest with many entries
-- (one per detection/skipped candidate, across every file), not one
-- content hash describing "the" artefact. Forcing that into
-- `subject_revision.content_hash` would mean either hashing the whole
-- manifest into a single opaque value (losing the per-file,
-- per-rule-id structure 727/728/729/730 need to query directly) or
-- fabricating a `subject_id` for something that is not really one
-- subject at all. A new table, scoped and append-only the same way
-- `subject_revision` is, is the honest fit.
--
-- Classified PROJECT-scoped (cairn_kernel.tenancy.classification),
-- same as subject_revision/approval/execution_record: a transformation
-- run belongs to one tenant's one project.
CREATE TABLE transformation_run (
  run_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL,
  project_id          uuid NOT NULL,
  run_number          integer NOT NULL CHECK (run_number >= 1),
  source_file_ids     jsonb NOT NULL,
  manifest            jsonb NOT NULL,
  applied_count       integer NOT NULL CHECK (applied_count >= 0),
  skipped_count       integer NOT NULL CHECK (skipped_count >= 0),
  unsupported_count   integer NOT NULL CHECK (unsupported_count >= 0),
  created_by          text NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  UNIQUE (tenant_id, project_id, run_id),
  UNIQUE (tenant_id, project_id, run_number)
);

-- Monotonic run_number per (tenant_id, project_id), same discipline as
-- subject_revision_check_monotonic (migration 0005) -- a run is an
-- append-only fact about what the engine actually did, not a value a
-- caller gets to assign.
CREATE FUNCTION transformation_run_check_monotonic() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  expected integer;
BEGIN
  SELECT coalesce(max(run_number), 0) + 1 INTO expected
    FROM transformation_run
    WHERE tenant_id = NEW.tenant_id
      AND project_id = NEW.project_id;
  IF NEW.run_number <> expected THEN
    RAISE EXCEPTION
      'transformation_run.run_number must be monotonic per project (expected %, got %)',
      expected, NEW.run_number
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER transformation_run_monotonic
  BEFORE INSERT ON transformation_run
  FOR EACH ROW EXECUTE FUNCTION transformation_run_check_monotonic();

-- Append-only: a transformation run record, once written, is never
-- edited or removed (same pattern as subject_revision/ledger_entry).
CREATE FUNCTION transformation_run_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'transformation_run is append-only' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER transformation_run_append_only
  BEFORE UPDATE OR DELETE ON transformation_run
  FOR EACH ROW EXECUTE FUNCTION transformation_run_reject_mutation();

CREATE TRIGGER transformation_run_no_truncate
  BEFORE TRUNCATE ON transformation_run
  FOR EACH STATEMENT EXECUTE FUNCTION transformation_run_reject_mutation();

ALTER TABLE transformation_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE transformation_run FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON transformation_run
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());
CREATE POLICY project_isolation ON transformation_run
  AS RESTRICTIVE
  USING (project_id = cairn_current_project())
  WITH CHECK (project_id = cairn_current_project());
