from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]

REGRESSIONS: dict[str, tuple[str, ...]] = {
    "CA-001": (
        "docs/remediation/CA-001-migration-safety.md",
        "tests/integration/test_migration_safety.py",
    ),
    "CA-002": (
        "docs/remediation/CA-002-tenant-isolation.md",
        "tests/integration/test_tenant_security.py",
        "packages/kernel/src/cairn_kernel/security/assertion.py",
    ),
    "CA-003": (
        "docs/remediation/CA-003-audit-boundary.md",
        "tests/integration/test_mutation_boundary.py",
    ),
    "CA-004": (
        "docs/remediation/CA-004-audit-integrity.md",
        "tests/integration/test_ledger_verification.py",
        "packages/kernel/tests/test_canonical.py",
    ),
    "CA-005": (
        "docs/remediation/CA-004-audit-integrity.md",
        "packages/kernel/src/cairn_kernel/security/canonical.py",
        "packages/kernel/tests/test_canonical.py",
    ),
    "CA-006": (
        "docs/remediation/CA-006-migration-lock.md",
        "tests/integration/test_migration_lock.py",
    ),
    "CA-007": (
        "docs/remediation/CA-007-conformance-enforcement.md",
        "packages/kernel/tests/test_conformance.py",
        "tests/conformance/test_rule_map.py",
    ),
}


def test_every_remediation_has_documented_adversarial_evidence() -> None:
    for finding, references in REGRESSIONS.items():
        for reference in references:
            path = REPO_ROOT / reference
            assert path.exists(), f"{finding} references missing {reference}"


def test_every_remediation_has_at_least_one_executable_test() -> None:
    for finding, references in REGRESSIONS.items():
        tests = [reference for reference in references if "test" in reference]
        assert tests, f"{finding} has no test evidence"
        for reference in tests:
            text = (REPO_ROOT / reference).read_text(encoding="utf-8")
            assert "def test_" in text, f"{reference} has no test cases"


def test_security_regression_target_covers_every_test_file() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("security-regression:", 1)[1].split("\n\n", 1)[0]
    for references in REGRESSIONS.values():
        for reference in references:
            if reference.endswith(".py") and "tests/" in reference:
                assert reference in target, f"{reference} is not in security-regression"
