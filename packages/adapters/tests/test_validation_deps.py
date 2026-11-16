"""R3-05: the "dependency" ``ValidationPort`` adapter -- real and fake,
their parity, and the "never a live package-index lookup" construction
proof the brief's step 6 requires.
"""

from __future__ import annotations

import pytest
from cairn_adapters.validation_deps import (
    DEPENDENCY_CHECK_ID,
    DependencyValidationAdapter,
    FakeDependencyValidationAdapter,
)
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_kernel.errors import NotFoundError
from cairn_modules.transformation.diff import render_transformation_diff
from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.validation import ValidationRequest, ValidationResult

DETECTOR_VERSION = "cairn-detector/0.1.0"
PATTERN_VERSION = "cairn-python-parser/0.1.0"
PATCHER_VERSION = "cairn-transform-patcher/0.1.0"


def _build_request(
    *,
    run_id: str,
    source_path: str,
    original: str,
    replacement: str,
    start: int,
    end: int,
    extra_files: tuple[SourceFile, ...] = (),
) -> ValidationRequest:
    source_file = SourceFile(path=source_path, content=original, language=SourceLanguage.PYTHON)
    entry = ManifestEntry(
        source_file_id=source_path,
        rule_id="py-import-imp-deprecated",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(ManifestEdit(start_byte=start, end_byte=end, start_line=1, end_line=1, replacement=replacement),),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )
    files = (source_file, *extra_files)
    manifest = TransformationManifest(source_file_ids=(source_path,), entries=(entry,))
    diff = render_transformation_diff(run_id=run_id, files=files, manifest=manifest)
    return ValidationRequest(run_id=run_id, files=files, manifest=manifest, diff=diff)


def test_a_stdlib_only_rewrite_introduces_no_undeclared_dependency() -> None:
    original = "import imp\n"
    request = _build_request(
        run_id="run-1",
        source_path="mod.py",
        original=original,
        replacement="importlib",
        start=len("import "),
        end=len("import imp"),
    )
    adapter = DependencyValidationAdapter()
    results = adapter.validate(request)
    assert len(results) == 1
    assert results[0].check_id == DEPENDENCY_CHECK_ID
    assert results[0].passed is True
    assert results[0].reason is None


def test_a_rewrite_introducing_an_undeclared_third_party_import_fails() -> None:
    original = "import imp\n"
    request = _build_request(
        run_id="run-2",
        source_path="mod.py",
        original=original,
        replacement="shinynewpackage",
        start=len("import "),
        end=len("import imp"),
    )
    adapter = DependencyValidationAdapter()
    results = adapter.validate(request)
    assert results[0].passed is False
    assert "shinynewpackage" in results[0].reason


def test_an_undeclared_import_already_listed_in_requirements_txt_is_allowed() -> None:
    original = "import imp\n"
    requirements = SourceFile(
        path="requirements.txt", content="shinynewpackage==1.0\n", language=SourceLanguage.UNSUPPORTED
    )
    request = _build_request(
        run_id="run-3",
        source_path="mod.py",
        original=original,
        replacement="shinynewpackage",
        start=len("import "),
        end=len("import imp"),
        extra_files=(requirements,),
    )
    adapter = DependencyValidationAdapter()
    results = adapter.validate(request)
    assert results[0].passed is True


def test_an_undeclared_import_already_listed_in_pyproject_toml_is_allowed() -> None:
    original = "import imp\n"
    pyproject = SourceFile(
        path="pyproject.toml",
        content='[project]\nname = "demo"\ndependencies = ["shinynewpackage>=2.0"]\n',
        language=SourceLanguage.UNSUPPORTED,
    )
    request = _build_request(
        run_id="run-4",
        source_path="mod.py",
        original=original,
        replacement="shinynewpackage",
        start=len("import "),
        end=len("import imp"),
        extra_files=(pyproject,),
    )
    adapter = DependencyValidationAdapter()
    results = adapter.validate(request)
    assert results[0].passed is True


def test_a_new_terraform_module_source_not_already_used_is_flagged() -> None:
    original = 'module "a" {\n  source = "./modules/a"\n}\n'
    rewritten_source_literal = '"./modules/new-undeclared-module"'
    start = original.index('"./modules/a"')
    end = start + len('"./modules/a"')
    source_file = SourceFile(path="main.tf", content=original, language=SourceLanguage.TERRAFORM)
    entry = ManifestEntry(
        source_file_id="main.tf",
        rule_id="tf-module-source-bump",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(
            ManifestEdit(
                start_byte=start, end_byte=end, start_line=2, end_line=2, replacement=rewritten_source_literal
            ),
        ),
        detector_version=DETECTOR_VERSION,
        pattern_version="cairn-hcl-parser/0.1.0",
        patcher_version=PATCHER_VERSION,
    )
    manifest = TransformationManifest(source_file_ids=("main.tf",), entries=(entry,))
    diff = render_transformation_diff(run_id="run-5", files=(source_file,), manifest=manifest)
    request = ValidationRequest(run_id="run-5", files=(source_file,), manifest=manifest, diff=diff)

    adapter = DependencyValidationAdapter()
    results = adapter.validate(request)
    assert results[0].passed is False
    assert "./modules/new-undeclared-module" in results[0].reason


def test_fake_adapter_replays_registered_results() -> None:
    fake_adapter = FakeDependencyValidationAdapter()
    request = _build_request(
        run_id="run-6",
        source_path="mod.py",
        original="import imp\n",
        replacement="importlib",
        start=len("import "),
        end=len("import imp"),
    )
    results = (ValidationResult(check_id=DEPENDENCY_CHECK_ID, passed=True),)
    fake_adapter.register(request.run_id, results)
    assert fake_adapter.validate(request) == results
    assert fake_adapter.calls == [request]


def test_fake_adapter_raises_for_an_unregistered_run() -> None:
    fake_adapter = FakeDependencyValidationAdapter()
    request = _build_request(
        run_id="run-7",
        source_path="mod.py",
        original="import imp\n",
        replacement="importlib",
        start=len("import "),
        end=len("import imp"),
    )
    with pytest.raises(NotFoundError):
        fake_adapter.validate(request)


def test_real_adapter_module_never_performs_a_live_package_index_lookup() -> None:
    """Construction proof: this module never imports anything that could
    reach a package index or the network at all."""

    from pathlib import Path

    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "cairn_adapters"
        / "validation_deps"
        / "real.py"
    )
    text = source_path.read_text()
    for forbidden in ("socket", "urllib", "http.client", "requests", "pip", "boto3", "google.cloud"):
        assert forbidden not in text, f"{forbidden!r} must not appear in {source_path}"
