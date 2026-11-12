DROP TRIGGER IF EXISTS ledger_entry_no_truncate ON ledger_entry;
DROP TRIGGER IF EXISTS ledger_entry_append_only ON ledger_entry;
DROP FUNCTION IF EXISTS ledger_entry_reject_mutation();
DROP TABLE IF EXISTS ledger_entry;
