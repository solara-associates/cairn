DROP TRIGGER IF EXISTS execution_record_transition ON execution_record;
DROP FUNCTION IF EXISTS execution_record_enforce_transition();
DROP TRIGGER IF EXISTS execution_record_matches_approval ON execution_record;
DROP FUNCTION IF EXISTS execution_record_match_approval();
DROP TABLE IF EXISTS execution_record;

DROP TRIGGER IF EXISTS approval_transition ON approval;
DROP FUNCTION IF EXISTS approval_enforce_transition();
DROP TRIGGER IF EXISTS approval_recovery_precondition ON approval;
DROP FUNCTION IF EXISTS approval_enforce_recovery_precondition();
DROP TABLE IF EXISTS approval;

DROP TRIGGER IF EXISTS subject_revision_no_truncate ON subject_revision;
DROP TRIGGER IF EXISTS subject_revision_append_only ON subject_revision;
DROP FUNCTION IF EXISTS subject_revision_reject_mutation();
DROP TRIGGER IF EXISTS subject_revision_monotonic ON subject_revision;
DROP FUNCTION IF EXISTS subject_revision_check_monotonic();
DROP TABLE IF EXISTS subject_revision;
