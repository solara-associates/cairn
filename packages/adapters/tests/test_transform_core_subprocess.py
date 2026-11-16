"""Integration tests for R3-03b's real ``TransformationPort`` adapter
(``SubprocessTransformationPort``), run against the actual compiled
``cairn-transform-cli`` binary -- not the fake. This file insists the
binary exists (``cargo build -p cairn-transform-cli`` first, or set
``CAIRN_TRANSFORM_CLI_BIN``); it fails, rather than skips, if it does
not, because this is specifically the test that proves the subprocess
boundary resolution (``~/solara/lz2026/cairn-r3-briefs.md`` §7's
open-question 1) actually works end to end.

Also carries the construction-proof checks (no shell, no network
module import, no cloud command anywhere in the adapter's own source)
required by the brief's step 6.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from cairn_adapters.transform_core import SubprocessTransformationPort, TransformCliUnavailableError
from cairn_adapters.transform_core.subprocess_adapter import resolve_transform_cli_binary
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_modules.transformation.engine import ManifestOutcome

SUBPROCESS_ADAPTER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "cairn_adapters"
    / "transform_core"
    / "subprocess_adapter.py"
)

S3_ACL_FIXTURE = SourceFile(
    path="s3.tf",
    content=(
        'resource "aws_s3_bucket" "artifacts" {\n'
        '  bucket = "cairn-demo-artifacts"\n'
        '  acl    = "public-read"\n'
        "}\n"
    ),
    language=SourceLanguage.TERRAFORM,
)

IMPORT_IMP_FIXTURE = SourceFile(path="mod.py", content="import imp\n", language=SourceLanguage.PYTHON)

INTERPOLATED_ACL_FIXTURE = SourceFile(
    path="interpolated.tf",
    content=(
        'resource "aws_s3_bucket" "interpolated" {\n'
        '  bucket = "demo-bucket"\n'
        '  acl    = "${var.environment}-public-read"\n'
        "}\n"
    ),
    language=SourceLanguage.TERRAFORM,
)

UNSUPPORTED_LANGUAGE_FIXTURE = SourceFile(
    path="notes.md", content="# just some notes\n", language=SourceLanguage.UNSUPPORTED
)


@pytest.fixture(scope="module")
def real_adapter() -> SubprocessTransformationPort:
    try:
        resolve_transform_cli_binary()
    except TransformCliUnavailableError as exc:
        pytest.fail(
            "cairn-transform-cli is not built -- this test requires the real "
            f"binary, not a skip: {exc}"
        )
    return SubprocessTransformationPort()


def test_real_binary_applies_the_tf_s3_acl_rewrite(real_adapter: SubprocessTransformationPort) -> None:
    manifest = real_adapter.transform([S3_ACL_FIXTURE])
    assert manifest.source_file_ids == ("s3.tf",)
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.rule_id == "tf-s3-bucket-inline-acl-deprecated"
    assert entry.outcome is ManifestOutcome.APPLIED
    assert entry.reason is None
    assert len(entry.edits) == 2
    assert entry.pattern_version == "cairn-hcl-parser/0.1.0"
    assert entry.detector_version == "cairn-detector/0.1.0"
    assert entry.patcher_version == "cairn-transform-patcher/0.1.0"


def test_real_binary_applies_the_py_import_imp_rewrite(
    real_adapter: SubprocessTransformationPort,
) -> None:
    manifest = real_adapter.transform([IMPORT_IMP_FIXTURE])
    entry = manifest.entries[0]
    assert entry.rule_id == "py-import-imp-deprecated"
    assert entry.outcome is ManifestOutcome.APPLIED
    assert entry.edits[0].replacement == "importlib"
    assert entry.pattern_version == "cairn-python-parser/0.1.0"


def test_real_binary_marks_runtime_interpolated_acl_unsupported(
    real_adapter: SubprocessTransformationPort,
) -> None:
    manifest = real_adapter.transform([INTERPOLATED_ACL_FIXTURE])
    entry = manifest.entries[0]
    assert entry.outcome is ManifestOutcome.UNSUPPORTED
    assert entry.edits == ()
    assert "runtime string interpolation" in entry.reason


def test_unsupported_language_files_are_never_sent_to_the_subprocess_at_all(
    real_adapter: SubprocessTransformationPort,
) -> None:
    manifest = real_adapter.transform([UNSUPPORTED_LANGUAGE_FIXTURE])
    assert manifest.entries == ()
    assert manifest.source_file_ids == ()


def test_multiple_files_in_one_call_produce_one_manifest_covering_both(
    real_adapter: SubprocessTransformationPort,
) -> None:
    manifest = real_adapter.transform([S3_ACL_FIXTURE, IMPORT_IMP_FIXTURE])
    assert manifest.source_file_ids == ("s3.tf", "mod.py")
    assert manifest.applied_count == 2


def test_running_the_pipeline_twice_produces_byte_identical_manifests(
    real_adapter: SubprocessTransformationPort,
) -> None:
    first = real_adapter.transform([S3_ACL_FIXTURE])
    second = real_adapter.transform([S3_ACL_FIXTURE])
    assert first == second


def test_unresolvable_binary_path_raises_a_clean_error_not_a_crash() -> None:
    adapter = SubprocessTransformationPort(binary_path=Path("/no/such/binary/here"))
    with pytest.raises(TransformCliUnavailableError):
        adapter.transform([IMPORT_IMP_FIXTURE])


# -- Construction-proof: no shell, no network, no cloud command --------


def _code_only(source: str) -> str:
    """Strip the module's own leading docstring (which, to explain what
    this check does, necessarily mentions the forbidden substrings)
    before scanning -- matching the same self-reference-safe approach
    722/723/724/725's Rust ``no_network_imports_in_*_source`` tests use
    for their own doc comments."""

    tree = ast.parse(source)
    docstring_node = tree.body[0] if tree.body and isinstance(tree.body[0], ast.Expr) else None
    if docstring_node is None:
        return source
    lines = source.splitlines(keepends=True)
    return "".join(lines[docstring_node.end_lineno :])


def test_subprocess_call_never_uses_a_shell_or_network_module() -> None:
    source = _code_only(SUBPROCESS_ADAPTER_SOURCE.read_text())
    assert ("shell" + "=True") not in source
    for forbidden in ("socket", "urllib", "http.client", "requests", "boto3", "google.cloud"):
        assert forbidden not in source, f"{forbidden!r} must not appear in {SUBPROCESS_ADAPTER_SOURCE}"


def test_subprocess_run_is_called_with_a_fixed_argv_list_not_a_string() -> None:
    """Static AST check: every ``subprocess.run`` call site passes a list
    literal (or a name bound to one) as its first positional argument,
    never a format string that could admit shell metacharacters or an
    injected command."""

    tree = ast.parse(SUBPROCESS_ADAPTER_SOURCE.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
    ]
    assert calls, "expected at least one subprocess.run call site"
    for call in calls:
        assert call.args, "subprocess.run must be called with a positional argv"
        assert isinstance(call.args[0], ast.List), "argv must be a list literal, never a string"
