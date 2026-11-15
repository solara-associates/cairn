-- R2-01: the mapping registry's workflow tables (ADR-004, spec section 7).
-- Published global mapping releases are global, CAIRN-operated control
-- data (spec 8.1) -- so mapping_release/mapping_release_review carry no
-- tenant_id/project_id or FK to project, and get no RLS; both are
-- classified GLOBAL in cairn_kernel.tenancy.classification.
-- TABLE_CLASSIFICATIONS, which requires zero RLS policies
-- (REQUIRED_POLICIES[TenancyScope.GLOBAL] = ()). mapping_proposal is the
-- other half of spec 8.1's classification table: "tenant mapping
-- proposals" is listed as Tenant-owned, not Global -- a proposal is
-- tenant-scoped even though the release content it carries becomes part
-- of the global workflow the moment it is proposed (see below).

-- mapping_release: the content of one release version, written exactly
-- once. Append-only like ledger_entry (migration 0003) -- a version's
-- content never changes after it is proposed, which is immutability
-- enforced from the moment of proposal, not only once published
-- (ADR-004: "Published versions are immutable. Corrections create a new
-- version."). The release's current lifecycle status is deliberately NOT
-- a column here: it is derived from the latest row in
-- mapping_release_review for this version, so there is exactly one place
-- that records "what happened to version V and when" and no risk of the
-- two ever disagreeing.
CREATE TABLE mapping_release (
  version        text PRIMARY KEY CHECK (version ~ '^\d{4}\.\d{2}\.\d+$'),
  content_hash   text NOT NULL CHECK (length(content_hash) > 0),
  released_at    timestamptz NOT NULL,
  entries        jsonb NOT NULL,
  proposed_by    text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION mapping_release_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mapping_release is append-only' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER mapping_release_append_only
  BEFORE UPDATE OR DELETE ON mapping_release
  FOR EACH ROW EXECUTE FUNCTION mapping_release_reject_mutation();

CREATE TRIGGER mapping_release_no_truncate
  BEFORE TRUNCATE ON mapping_release
  FOR EACH STATEMENT EXECUTE FUNCTION mapping_release_reject_mutation();

-- mapping_release_review: the ADR-004 propose/review/approve/publish/
-- retire audit trail for one release version. Append-only like
-- mapping_release and ledger_entry above -- a transition is recorded,
-- never edited or removed. ``review_seq`` is the sole ordering key for
-- "what happened, in what order" -- ``propose()`` inserts its two rows
-- (DRAFT then IN_REVIEW) inside one transaction with the identical
-- ``occurred_at`` timestamp, so ``occurred_at`` alone (or paired with the
-- random ``review_id``) cannot reliably order same-instant rows; a
-- monotonic identity column can.
CREATE TABLE mapping_release_review (
  review_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_seq   bigint GENERATED ALWAYS AS IDENTITY,
  version      text NOT NULL REFERENCES mapping_release(version),
  from_status  text CHECK (from_status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'PUBLISHED')),
  to_status    text NOT NULL CHECK (
                 to_status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'PUBLISHED', 'RETIRED')
               ),
  actor_id     text NOT NULL,
  rationale    text,
  occurred_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX mapping_release_review_version_idx
  ON mapping_release_review (version, review_seq);

CREATE FUNCTION mapping_release_review_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mapping_release_review is append-only' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER mapping_release_review_append_only
  BEFORE UPDATE OR DELETE ON mapping_release_review
  FOR EACH ROW EXECUTE FUNCTION mapping_release_review_reject_mutation();

CREATE TRIGGER mapping_release_review_no_truncate
  BEFORE TRUNCATE ON mapping_release_review
  FOR EACH STATEMENT EXECUTE FUNCTION mapping_release_review_reject_mutation();

-- ADR-004's sequence, enforced at the database: every new transition row
-- for a version must follow
--   DRAFT -> IN_REVIEW -> (APPROVED | DRAFT) -> PUBLISHED -> RETIRED
-- (IN_REVIEW -> DRAFT is a reviewer's rejection, sending the proposal back
-- to its author). No further row may be added once a version's latest
-- status is RETIRED (terminal), and PUBLISHED accepts only the final
-- RETIRED transition -- it never returns to an earlier status. This is
-- the database half of the identical check
-- cairn_modules.mappings.registry.PostgresMappingRepository makes before
-- ever issuing the INSERT below, so neither can silently drift from the
-- other.
CREATE FUNCTION mapping_release_review_enforce_sequence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_status text;
  allowed text[];
BEGIN
  SELECT to_status INTO current_status
    FROM mapping_release_review
    WHERE version = NEW.version
    ORDER BY review_seq DESC
    LIMIT 1;

  IF NEW.from_status IS DISTINCT FROM current_status THEN
    RAISE EXCEPTION
      'mapping_release_review.from_status (%) does not match % current status (%)',
      NEW.from_status, NEW.version, current_status
      USING ERRCODE = '23514';
  END IF;

  IF current_status IS NULL THEN
    IF NEW.to_status <> 'DRAFT' THEN
      RAISE EXCEPTION 'the first transition for mapping_release % must be DRAFT, got %',
        NEW.version, NEW.to_status
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;

  IF current_status = 'RETIRED' THEN
    RAISE EXCEPTION 'mapping_release % is RETIRED; no further transition is allowed', NEW.version
      USING ERRCODE = '23514';
  END IF;

  allowed := CASE current_status
    WHEN 'DRAFT' THEN ARRAY['IN_REVIEW']
    WHEN 'IN_REVIEW' THEN ARRAY['APPROVED', 'DRAFT']
    WHEN 'APPROVED' THEN ARRAY['PUBLISHED']
    WHEN 'PUBLISHED' THEN ARRAY['RETIRED']
    ELSE ARRAY[]::text[]
  END;

  IF NOT (NEW.to_status = ANY(allowed)) THEN
    RAISE EXCEPTION 'mapping_release % cannot move from % to %',
      NEW.version, current_status, NEW.to_status
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER mapping_release_review_sequence
  BEFORE INSERT ON mapping_release_review
  FOR EACH ROW EXECUTE FUNCTION mapping_release_review_enforce_sequence();

-- mapping_proposal: the tenant-scoped audit record of "which tenant asked
-- for this, and why" (ADR-004's "propose" step). Append-only, same reason
-- as the tables above -- a proposal is a historical request, never
-- edited after the fact. Tenant-owned (spec 8.1): RLS forced with only
-- tenant_isolation (no project_isolation -- proposals are not project-
-- scoped, same list spec 8.1 puts "tenant mapping proposals" on
-- alongside "tenant, app_user, tenant-wide role grants, tenant
-- settings"). The release content a proposal carries also lands in the
-- global mapping_release/mapping_release_review tables above, in the
-- same transaction -- that global row is what every tenant's VIEWER+ can
-- read once it exists; this row is what makes the *request* itself
-- visible only to the tenant that made it.
CREATE TABLE mapping_proposal (
  proposal_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid NOT NULL REFERENCES tenant(tenant_id),
  version           text NOT NULL REFERENCES mapping_release(version),
  proposer_actor_id text NOT NULL,
  rationale         text NOT NULL,
  proposed_at       timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION mapping_proposal_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mapping_proposal is append-only' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER mapping_proposal_append_only
  BEFORE UPDATE OR DELETE ON mapping_proposal
  FOR EACH ROW EXECUTE FUNCTION mapping_proposal_reject_mutation();

CREATE TRIGGER mapping_proposal_no_truncate
  BEFORE TRUNCATE ON mapping_proposal
  FOR EACH STATEMENT EXECUTE FUNCTION mapping_proposal_reject_mutation();

ALTER TABLE mapping_proposal ENABLE ROW LEVEL SECURITY;
ALTER TABLE mapping_proposal FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON mapping_proposal
  USING (tenant_id = cairn_current_tenant())
  WITH CHECK (tenant_id = cairn_current_tenant());
