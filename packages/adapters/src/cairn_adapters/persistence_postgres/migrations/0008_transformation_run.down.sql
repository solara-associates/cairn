DROP TRIGGER IF EXISTS transformation_run_no_truncate ON transformation_run;
DROP TRIGGER IF EXISTS transformation_run_append_only ON transformation_run;
DROP FUNCTION IF EXISTS transformation_run_reject_mutation();
DROP TRIGGER IF EXISTS transformation_run_monotonic ON transformation_run;
DROP FUNCTION IF EXISTS transformation_run_check_monotonic();
DROP TABLE IF EXISTS transformation_run;
