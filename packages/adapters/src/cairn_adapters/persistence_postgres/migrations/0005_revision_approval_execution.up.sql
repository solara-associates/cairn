-- R1-21: immutable revisions, approval binding and the execution state
-- machine (ADR-009, ADR-010). See docs/adr/ADR-009-approval-binding.md and
-- docs/adr/ADR-010-gated-writes.md for the decisions this schema encodes.

CREATE TABLE subject_revision (
  revision_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid NOT NULL,
  project_id        uuid NOT NULL,
  subject_kind      text NOT NULL,
  subject_id        uuid NOT NULL,
  revision_number   integer NOT NULL CHECK (revision_number >= 1),
  content_hash      text NOT NULL CHECK (length(content_hash) > 0),
  input_versions    jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by        text NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  UNIQUE (tenant_id, project_id, revision_id),
  UNIQUE (tenant_id, project_id, revision_id, content_hash),
  UNIQUE (tenant_id, project_id, subject_kind, subject_id, revision_number)
);

-- Monotonic revision_number per subject, enforced at the database, not only
-- in application code (ADR-009: "Revisions are append-only. A change
-- creates a new revision and never mutates an approved revision.").
CREATE FUNCTION subject_revision_check_monotonic() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  expected integer;
BEGIN
  SELECT coalesce(max(revision_number), 0) + 1 INTO expected
    FROM subject_revision
    WHERE tenant_id = NEW.tenant_id
      AND project_id = NEW.project_id
      AND subject_kind = NEW.subject_kind
      AND subject_id = NEW.subject_id;
  IF NEW.revision_number <> expected THEN
    RAISE EXCEPTION
      'subject_revision.revision_number must be monotonic per subject (expected %, got %)',
      expected, NEW.revision_number
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER subject_revision_monotonic
  BEFORE INSERT ON subject_revision
  FOR EACH ROW EXECUTE FUNCTION subject_revision_check_monotonic();

-- subject_revision is append-only: a change creates a new revision, it
-- never mutates or removes an existing one (same pattern as ledger_entry in
-- migration 0003).
CREATE FUNCTION subject_revision_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'subject_revision is append-only' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER subject_revision_append_only
  BEFORE UPDATE OR DELETE ON subject_revision
  FOR EACH ROW EXECUTE FUNCTION subject_revision_reject_mutation();

CREATE TRIGGER subject_revision_no_truncate
  BEFORE TRUNCATE ON subject_revision
  FOR EACH STATEMENT EXECUTE FUNCTION subject_revision_reject_mutation();

ALTER TABLE subject_revision ENABLE ROW LEVEL SECURITY;
ALTER TABLE subject_revision FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON subject_revision
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());
CREATE POLICY project_isolation ON subject_revision
  AS RESTRICTIVE
  USING (project_id = cairn_current_project())
  WITH CHECK (project_id = cairn_current_project());

-- Approval: binds to one exact revision row and hash (ADR-009). The
-- composite foreign key is the DB-enforced half of "approve once, apply
-- anything" being impossible: a wrong revision_id/revision_hash pair is a
-- foreign-key violation, not an application bug.
CREATE TABLE approval (
  approval_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                uuid NOT NULL,
  project_id               uuid NOT NULL,
  subject_kind             text NOT NULL,
  subject_id               uuid NOT NULL,
  revision_id              uuid NOT NULL,
  revision_hash            text NOT NULL,
  mutation_class           text NOT NULL CHECK (mutation_class IN (
                              'READ_ONLY', 'INTERNAL_MUTATION',
                              'REVERSIBLE_EXTERNAL_MUTATION',
                              'COMPENSATABLE_EXTERNAL_MUTATION',
                              'IRREVERSIBLE_EXTERNAL_MUTATION'
                            )),
  risk_tier                text NOT NULL,
  state                    text NOT NULL DEFAULT 'DRAFT' CHECK (state IN (
                              'DRAFT', 'PENDING_APPROVAL', 'APPROVED',
                              'REJECTED', 'CANCELLED', 'CONSUMED', 'EXPIRED'
                            )),
  proposer_actor_id        text NOT NULL,
  approver_actor_id        text,
  decided_at               timestamptz,
  reason                   text,
  evidence_ref             text,
  compensation_strategy    text CHECK (compensation_strategy IN (
                              'ROLLBACK', 'COMPENSATE', 'ACCEPT_IRREVERSIBLE'
                            )),
  compensation_plan_ref    text,
  compensation_preconditions text,
  compensation_authority   text,
  compensation_evidence    text,
  compensation_failure_handling text,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, project_id, revision_id, revision_hash)
    REFERENCES subject_revision (tenant_id, project_id, revision_id, content_hash),
  UNIQUE (tenant_id, project_id, approval_id),
  UNIQUE (tenant_id, project_id, approval_id, revision_id, revision_hash, mutation_class),
  -- ADR-009 "Separation of duties": the proposer cannot be the sole approver.
  CHECK (approver_actor_id IS NULL OR approver_actor_id <> proposer_actor_id)
);

-- Recovery precondition + compensation-contract completeness, enforced
-- before an approval can reach APPROVED (ADR-009, ADR-010): a reversible
-- mutation without a rollback reference, or a compensatable mutation
-- without a compensation reference, or any external mutation with an
-- incomplete contract element, cannot be approved.
CREATE FUNCTION approval_enforce_recovery_precondition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  expected_strategy text;
BEGIN
  IF NEW.state NOT IN ('APPROVED', 'CONSUMED') THEN
    RETURN NEW;
  END IF;

  IF NEW.mutation_class IN ('READ_ONLY', 'INTERNAL_MUTATION') THEN
    IF NEW.compensation_strategy IS NOT NULL THEN
      RAISE EXCEPTION
        '% must not carry a compensation contract', NEW.mutation_class
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;

  expected_strategy := CASE NEW.mutation_class
    WHEN 'REVERSIBLE_EXTERNAL_MUTATION' THEN 'ROLLBACK'
    WHEN 'COMPENSATABLE_EXTERNAL_MUTATION' THEN 'COMPENSATE'
    WHEN 'IRREVERSIBLE_EXTERNAL_MUTATION' THEN 'ACCEPT_IRREVERSIBLE'
  END;

  IF NEW.compensation_strategy IS DISTINCT FROM expected_strategy
    OR coalesce(length(NEW.compensation_plan_ref), 0) = 0
    OR coalesce(length(NEW.compensation_preconditions), 0) = 0
    OR coalesce(length(NEW.compensation_authority), 0) = 0
    OR coalesce(length(NEW.compensation_evidence), 0) = 0
    OR coalesce(length(NEW.compensation_failure_handling), 0) = 0
  THEN
    RAISE EXCEPTION
      '% requires a complete compensation contract (strategy %) before approval',
      NEW.mutation_class, expected_strategy
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER approval_recovery_precondition
  BEFORE INSERT OR UPDATE ON approval
  FOR EACH ROW EXECUTE FUNCTION approval_enforce_recovery_precondition();

-- Invalid approval state transitions are rejected at the database too (the
-- application layer, cairn_modules.approvals.model, enforces the identical
-- table so both can be tested and neither can silently drift).
CREATE FUNCTION approval_enforce_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  allowed text[];
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.state <> 'DRAFT' THEN
      RAISE EXCEPTION 'a new approval must start in DRAFT, got %', NEW.state
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.state = OLD.state THEN
    RAISE EXCEPTION 'approval % is already %', OLD.approval_id, OLD.state
      USING ERRCODE = '23514';
  END IF;

  allowed := CASE OLD.state
    WHEN 'DRAFT' THEN ARRAY['PENDING_APPROVAL', 'CANCELLED']
    WHEN 'PENDING_APPROVAL' THEN ARRAY['APPROVED', 'REJECTED', 'CANCELLED']
    WHEN 'APPROVED' THEN ARRAY['CONSUMED', 'EXPIRED']
    ELSE ARRAY[]::text[]
  END;

  IF NOT (NEW.state = ANY(allowed)) THEN
    RAISE EXCEPTION 'approval cannot move from % to %', OLD.state, NEW.state
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER approval_transition
  BEFORE INSERT OR UPDATE ON approval
  FOR EACH ROW EXECUTE FUNCTION approval_enforce_transition();

ALTER TABLE approval ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON approval
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());
CREATE POLICY project_isolation ON approval
  AS RESTRICTIVE
  USING (project_id = cairn_current_project())
  WITH CHECK (project_id = cairn_current_project());

-- Execution record: references the exact approval and the exact revision
-- it was approved against (ADR-009).
CREATE TABLE execution_record (
  execution_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid NOT NULL,
  project_id        uuid NOT NULL,
  approval_id       uuid NOT NULL,
  revision_id       uuid NOT NULL,
  approved_hash     text NOT NULL,
  mutation_class    text NOT NULL CHECK (mutation_class IN (
                       'READ_ONLY', 'INTERNAL_MUTATION',
                       'REVERSIBLE_EXTERNAL_MUTATION',
                       'COMPENSATABLE_EXTERNAL_MUTATION',
                       'IRREVERSIBLE_EXTERNAL_MUTATION'
                     )),
  state             text NOT NULL DEFAULT 'PROPOSED' CHECK (state IN (
                       'PROPOSED', 'AUTHORIZED', 'EXECUTING', 'SUCCEEDED',
                       'FAILED', 'ROLLED_BACK', 'CANCELLED'
                     )),
  actor_id          text NOT NULL,
  correlation_id    text NOT NULL,
  reason            text,
  evidence_ref      text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, project_id),
  FOREIGN KEY (tenant_id, project_id, approval_id)
    REFERENCES approval (tenant_id, project_id, approval_id),
  UNIQUE (tenant_id, project_id, execution_id)
);

-- The execution must name exactly the revision/hash/mutation class its
-- approval is bound to, and the approval must be APPROVED when execution is
-- first proposed (ADR-009: "Execution is permitted only when approval state
-- is APPROVED and the referenced revision is current for that approval.").
CREATE FUNCTION execution_record_match_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  bound_revision_id uuid;
  bound_hash text;
  bound_class text;
  bound_state text;
BEGIN
  SELECT revision_id, revision_hash, mutation_class, state
    INTO bound_revision_id, bound_hash, bound_class, bound_state
    FROM approval
    WHERE tenant_id = NEW.tenant_id
      AND project_id = NEW.project_id
      AND approval_id = NEW.approval_id;

  IF TG_OP = 'INSERT' THEN
    IF bound_state <> 'APPROVED' THEN
      RAISE EXCEPTION 'approval % is %, not APPROVED', NEW.approval_id, bound_state
        USING ERRCODE = '23514';
    END IF;
  END IF;

  IF NEW.revision_id IS DISTINCT FROM bound_revision_id
    OR NEW.approved_hash IS DISTINCT FROM bound_hash
    OR NEW.mutation_class IS DISTINCT FROM bound_class
  THEN
    RAISE EXCEPTION
      'execution_record does not match the revision/hash/mutation_class bound by approval %',
      NEW.approval_id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER execution_record_matches_approval
  BEFORE INSERT OR UPDATE ON execution_record
  FOR EACH ROW EXECUTE FUNCTION execution_record_match_approval();

CREATE FUNCTION execution_record_enforce_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  allowed text[];
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.state <> 'PROPOSED' THEN
      RAISE EXCEPTION 'a new execution_record must start in PROPOSED, got %', NEW.state
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.state = OLD.state THEN
    RAISE EXCEPTION 'execution_record % is already %', OLD.execution_id, OLD.state
      USING ERRCODE = '23514';
  END IF;

  allowed := CASE OLD.state
    WHEN 'PROPOSED' THEN ARRAY['AUTHORIZED', 'CANCELLED']
    WHEN 'AUTHORIZED' THEN ARRAY['EXECUTING', 'CANCELLED']
    WHEN 'EXECUTING' THEN ARRAY['SUCCEEDED', 'FAILED', 'ROLLED_BACK']
    WHEN 'SUCCEEDED' THEN ARRAY['ROLLED_BACK']
    ELSE ARRAY[]::text[]
  END;

  IF NOT (NEW.state = ANY(allowed)) THEN
    RAISE EXCEPTION 'execution_record cannot move from % to %', OLD.state, NEW.state
      USING ERRCODE = '23514';
  END IF;

  -- ADR-010 Class C rule 8: an irreversible mutation cannot roll back.
  IF NEW.state = 'ROLLED_BACK' AND NEW.mutation_class = 'IRREVERSIBLE_EXTERNAL_MUTATION' THEN
    RAISE EXCEPTION 'an IRREVERSIBLE_EXTERNAL_MUTATION execution cannot transition to ROLLED_BACK'
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER execution_record_transition
  BEFORE INSERT OR UPDATE ON execution_record
  FOR EACH ROW EXECUTE FUNCTION execution_record_enforce_transition();

ALTER TABLE execution_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_record FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON execution_record
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());
CREATE POLICY project_isolation ON execution_record
  AS RESTRICTIVE
  USING (project_id = cairn_current_project())
  WITH CHECK (project_id = cairn_current_project());
