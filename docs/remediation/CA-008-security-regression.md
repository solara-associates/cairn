# CA-008: security regression suite

## Problem

Each remediation finding was proven by its own adversarial tests, but there was no single place that guaranteed those tests and their evidence documents stayed present and linked.

## Decision

`tests/security/test_regression_inventory.py` is the regression manifest. It maps CA-001 to CA-007 to their evidence documents, implementation files and test files, and fails if any of them disappear or stop containing test cases.

`make security-regression` runs the adversarial set in one command:

- migration safety and migration serialization;
- tenant assertions and adversarial RLS;
- transactional audit boundary and rollback behavior;
- canonical payloads, ledger verification and tamper detection;
- conformance enforcement;
- authentication middleware.

`uv run pytest` still runs the same tests inside CI; the target is for local and incident use when a fast, targeted run is wanted.

## Acceptance evidence

- The inventory test passes against the current tree.
- `make security-regression` runs the listed files and exits 0.
- README status now describes the implemented R0 foundation.
