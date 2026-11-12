# CA-007: conformance enforcement

## Problem

The conformance runner treated every unmapped mandatory rule as PENDING and still exited successfully. A pending rule could therefore persist indefinitely with no owner, no expiry and no evidence, and a release could ship with mandatory controls unimplemented.

## Decision

Pending is now an explicit, expiring exception.

- `tools/conformance/exceptions.yaml` records each pending mandatory rule with owner, reason, evidence reference and `expires_on`.
- The runner fails when:
  - a mandatory rule is pending without an exception;
  - an exception has expired;
  - an exception references an unknown rule;
  - an exception exists for a rule that is no longer pending (stale exception).
- `--release` fails on any pending mandatory rule, even with a valid exception.
- Active rules must declare `evidence`, and `tests/conformance/test_rule_map.py` checks that every evidence path exists and that the exception set exactly matches the pending set.
- CI runs the normal conformance pass on every push and `--release` for tags.

The exception list is a burn-down list, not an allowlist. Removing a rule from it means the story landed and the check must pass.

## Acceptance evidence

- `packages/kernel/tests/test_conformance.py`: pending without exception fails, pending with exception passes, release fails with exception, stale exception fails, expired exception fails, unknown rule and duplicates rejected.
- `tests/conformance/test_rule_map.py`: exceptions match pending rules exactly, every evidence path exists.
- Current state: 5 passed, 0 failed, 15 pending, 0 errors; `--release` exits 1 until all mandatory rules have checks.
- Full suite green, `make lint` green.
