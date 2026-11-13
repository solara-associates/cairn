"""Checks backing R-SEC-01 / R-SEC-02.

R0-17 (PRs #13, #16) landed the CI security baseline: container image
scanning, SBOM generation, keyless signing, Python dependency scanning and
secret scanning, plus a Rust dependency scan step inside the `rust` job.
This asserts those jobs still exist and are wired the way R-SEC-01
("no critical/high findings; high needs risk acceptance") and R-SEC-02
("SBOM and image signature present") require, so the conformance rule map
can point at real, running CI jobs instead of a `pending_story`.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parents[2]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"


def _load_jobs() -> dict:
    data = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return data["jobs"]


def _step_commands(job: dict) -> list[str]:
    commands = []
    for step in job.get("steps", []):
        for key in ("run", "name"):
            value = step.get(key)
            if value:
                commands.append(str(value))
    return commands


def test_image_scan_job_runs_trivy_and_fails_on_critical_high() -> None:
    jobs = _load_jobs()
    assert "image-scan" in jobs, "R-SEC-01 needs the image-scan job"
    steps = jobs["image-scan"]["steps"]
    trivy_steps = [s for s in steps if "trivy-action" in str(s.get("uses", ""))]
    assert trivy_steps, "image-scan must run aquasecurity/trivy-action"
    trivy_with = trivy_steps[0]["with"]
    assert "CRITICAL" in trivy_with["severity"] and "HIGH" in trivy_with["severity"]
    assert str(trivy_with["exit-code"]) == "1", (
        "trivy must fail the job on CRITICAL/HIGH findings for R-SEC-01"
    )


def test_python_deps_scan_job_runs_pip_audit() -> None:
    jobs = _load_jobs()
    assert "python-deps-scan" in jobs, "R-SEC-01 needs the python-deps-scan job"
    commands = " ".join(_step_commands(jobs["python-deps-scan"]))
    assert "pip-audit" in commands or "pip_audit" in commands


def test_secrets_scan_job_runs_gitleaks() -> None:
    jobs = _load_jobs()
    assert "secrets-scan" in jobs, "R-SEC-01 needs the secrets-scan job"
    commands = " ".join(_step_commands(jobs["secrets-scan"]))
    assert "gitleaks" in commands


def test_rust_job_runs_cargo_audit() -> None:
    jobs = _load_jobs()
    assert "rust" in jobs
    commands = " ".join(_step_commands(jobs["rust"]))
    assert "cargo-audit" in commands or "cargo audit" in commands


def test_sbom_sign_job_generates_and_signs_sboms() -> None:
    jobs = _load_jobs()
    assert "sbom-sign" in jobs, "R-SEC-02 needs the sbom-sign job"
    steps = jobs["sbom-sign"]["steps"]
    uses_values = " ".join(str(s.get("uses", "")) for s in steps)
    commands = " ".join(_step_commands(jobs["sbom-sign"]))
    assert "sbom-action" in uses_values, "sbom-sign must generate an SBOM"
    assert "cosign-installer" in uses_values, "sbom-sign must install cosign"
    assert "cosign sign-blob" in commands, "sbom-sign must sign the SBOM"


def test_image_scan_job_also_generates_and_signs_a_per_image_sbom() -> None:
    jobs = _load_jobs()
    steps = jobs["image-scan"]["steps"]
    uses_values = " ".join(str(s.get("uses", "")) for s in steps)
    commands = " ".join(_step_commands(jobs["image-scan"]))
    assert "sbom-action" in uses_values
    assert "cosign-installer" in uses_values
    assert "cosign sign-blob" in commands
