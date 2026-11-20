"""Demo pack companion script for use case 2 (migration).

Runs the real R3 clean-room transformation pipeline against one golden
fixture repository (`tests/golden/transform/repos/terraform_acl_deprecated`,
the same fixture `tests/golden/transform/test_golden_corpus.py` and the
console's own `tests/e2e/transform-journey.test.ts` already prove this
pipeline against) end to end:

1. Fetch -- `FakeRepositorySource` (721's fake fetch adapter; never a real
   Git clone or upload -- this demo's "connected source" is a small
   in-memory fixture, not a live repository).
2. Transform -- the real, compiled `cairn-transform-cli` binary via
   `SubprocessTransformationPort` (722-726's engine: real HCL parse, real
   deprecation detection, real patch). Not `FakeTransformationPort`.
3. Diff -- `render_transformation_diff` (728), the real unified diff.
4. Validate -- the real, compiled `cairn-transform-validator-cli` binary
   via `StaticValidationAdapter` (731's real static re-parse check). Not
   `FakeStaticValidationAdapter`.
5. Seal and verify evidence offline -- `build_transformation_evidence_package`
   + `verify_envelope` with an independent verifier, same discipline as
   the use-case-3 and use-case-1 scripts.

What this script does **not** do, and the demo must say plainly: no
`ProviderExecutionPort` adapter runs anywhere here. R4's real-cloud
execution adapter (`cairn_adapters.provider_execution`) does not exist
yet -- only a fake/deterministic one does (see README's R4 status row).
There is no "apply this transformation to a live project" step in this
pipeline at all today; "run" in this use case's console journey means
scan-and-produce-preview (transform-run.ts's own label), never an
execution against a customer's cloud account.

Run: uv run python docs/demo/uc2_verify_transform_pipeline.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cairn_adapters.source_git.fake import FakeRepositorySource
from cairn_adapters.source_git.language import detect_language
from cairn_adapters.transform_core import SubprocessTransformationPort
from cairn_adapters.validation_static.subprocess_adapter import StaticValidationAdapter
from cairn_contracts.transformation import GitRepositoryRef, SourceFile
from cairn_kernel.evidence import verify_envelope
from cairn_kernel.testing.fakes import FakeEvidenceSigner, FakeEvidenceVerifier
from cairn_modules.transformation.diff import render_transformation_diff
from cairn_modules.transformation.evidence import build_transformation_evidence_package
from cairn_modules.transformation.runs import TransformationRunRecord
from cairn_modules.transformation.validation import ValidationRequest, run_validation

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "golden" / "transform" / "repos" / "terraform_acl_deprecated"
MOMENT = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
TENANT = "demo-tenant"
PROJECT = "uc2-migration-demo"


def _load_fixture_files() -> tuple[SourceFile, ...]:
    files = []
    for path in sorted(FIXTURE_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(FIXTURE_DIR).as_posix()
        files.append(
            SourceFile(
                path=rel_path,
                content=path.read_text(encoding="utf-8"),
                language=detect_language(rel_path),
            )
        )
    return tuple(files)


def main() -> None:
    files = _load_fixture_files()
    print(f"fixture: terraform_acl_deprecated ({len(files)} file(s))")

    ref = GitRepositoryRef(
        url="https://example.invalid/golden-corpus.git", ref="golden/terraform_acl_deprecated"
    )
    source = FakeRepositorySource()
    source.register(ref, files)
    fetched = source.fetch(ref)

    manifest = SubprocessTransformationPort().transform(fetched)
    print("manifest entries:")
    for entry in manifest.entries:
        print(
            f"  {entry.source_file_id}: {entry.rule_id} -> {entry.outcome.value} ({len(entry.edits)} edit(s))"
        )

    run_id = "uc2-demo-run-1"
    diff = render_transformation_diff(run_id=run_id, files=list(fetched), manifest=manifest)

    validation = run_validation(
        ValidationRequest(run_id=run_id, files=fetched, manifest=manifest, diff=diff),
        checks=(StaticValidationAdapter(),),
    )
    print(f"validation: approved={validation.approved}")
    for result in validation.results:
        print(
            f"  {result.check_id}: {'PASS' if result.passed else 'FAIL'}"
            + (f" -- {result.reason}" if result.reason else "")
        )

    run = TransformationRunRecord(
        run_id=run_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        run_number=1,
        manifest=manifest,
        created_by="demo",
        created_at=MOMENT,
    )
    envelope = build_transformation_evidence_package(
        run,
        package_id="uc2-demo-pkg-1",
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
        files=list(fetched),
        repository_ref=ref,
        diff=diff,
        validation=validation,
    )
    print(f"evidence package sealed: {envelope.package_id} (outcome={envelope.outcome})")

    result = verify_envelope(envelope, verifier=FakeEvidenceVerifier())
    print(f"offline verification: {result.outcome}")
    assert result.valid, f"verification failed: {result.reason}"


if __name__ == "__main__":
    main()
