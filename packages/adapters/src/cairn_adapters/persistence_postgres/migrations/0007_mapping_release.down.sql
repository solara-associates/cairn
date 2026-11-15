DROP TRIGGER IF EXISTS mapping_proposal_no_truncate ON mapping_proposal;
DROP TRIGGER IF EXISTS mapping_proposal_append_only ON mapping_proposal;
DROP FUNCTION IF EXISTS mapping_proposal_reject_mutation();
DROP TABLE IF EXISTS mapping_proposal;

DROP TRIGGER IF EXISTS mapping_release_review_sequence ON mapping_release_review;
DROP FUNCTION IF EXISTS mapping_release_review_enforce_sequence();
DROP TRIGGER IF EXISTS mapping_release_review_no_truncate ON mapping_release_review;
DROP TRIGGER IF EXISTS mapping_release_review_append_only ON mapping_release_review;
DROP FUNCTION IF EXISTS mapping_release_review_reject_mutation();
DROP INDEX IF EXISTS mapping_release_review_version_idx;
DROP TABLE IF EXISTS mapping_release_review;

DROP TRIGGER IF EXISTS mapping_release_no_truncate ON mapping_release;
DROP TRIGGER IF EXISTS mapping_release_append_only ON mapping_release;
DROP FUNCTION IF EXISTS mapping_release_reject_mutation();
DROP TABLE IF EXISTS mapping_release;
