"""R3-05: the static ``ValidationPort`` adapter -- real (against the
actual compiled ``cairn-transform-validator-cli`` binary, not the fake)
and the fake, plus their parity and the construction-proof checks the
brief's step 6 requires (no shell, no network module import anywhere in
the real adapter's own source).

This file insists the binary exists (``cargo build -p
cairn-transform-validator`` first, or set
``CAIRN_TRANSFORM_VALIDATOR_CLI_BIN``); it fails, rather than skips, if
it does not -- the same discipline ``test_transform_core_subprocess.py``
already uses, because this is specifically the test that proves the
subprocess boundary actually works end to end, not merely that the Rust
crate's own unit tests pass.
"""

from __future__ import annotations

import ast
from pathlib import Path

from cairn_adapters.validation_static import FakeStaticValidationAdapter, StaticValidationAdapter
from cairn_adapters.validation_static.subprocess_adapter import resolve_validator_cli_binary
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_modules.transformation.diff import render_transformation_diff
from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.validation import ValidationRequest, ValidationResult

SUBPROCESS_ADAPTER_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "cairn_adapters"
    / "validation_static"
    / "subprocess_adapter.py"
)

DETECTOR_VERSION = "cairn-detector/0.1.0"
PATTERN_VERSION = "cairn-hcl-parser/0.1.0"
PATCHER_VERSION = "cairn-transform-patcher/0.1.0"

SAFE_REWRITE_CONTENT = 'resource "aws_s3_bucket" "b" {\n  acl = "public-read"\n}\n'


def _code_only(source: str) -> str:
    return source.split('if __name__ == "__main__"')[0]


def _safe_rewrite_request() -> ValidationRequest:
    source_file = SourceFile(
        path="s3.tf", content=SAFE_REWRITE_CONTENT, language=SourceLanguage.TERRAFORM
    )
    # Byte offsets of the `"public-read"` literal within SAFE_REWRITE_CONTENT.
    start = SAFE_REWRITE_CONTENT.index('"public-read"')
    end = start + len('"public-read"')
    entry = ManifestEntry(
        source_file_id="s3.tf",
        rule_id="tf-s3-bucket-inline-acl-deprecated",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(
            ManifestEdit(
                start_byte=start, end_byte=end, start_line=2, end_line=2, replacement='"private"'
            ),
        ),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )
    manifest = TransformationManifest(source_file_ids=("s3.tf",), entries=(entry,))
    diff = render_transformation_diff(run_id="run-1", files=(source_file,), manifest=manifest)
    return ValidationRequest(run_id="run-1", files=(source_file,), manifest=manifest, diff=diff)


def _breaking_rewrite_request() -> ValidationRequest:
    source_file = SourceFile(
        path="broken.tf", content=SAFE_REWRITE_CONTENT, language=SourceLanguage.TERRAFORM
    )
    brace_pos = SAFE_REWRITE_CONTENT.rindex("}")
    entry = ManifestEntry(
        source_file_id="broken.tf",
        rule_id="tf-s3-bucket-inline-acl-deprecated",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(
            ManifestEdit(
                start_byte=brace_pos, end_byte=brace_pos + 1, start_line=3, end_line=3, replacement=""
            ),
        ),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )
    manifest = TransformationManifest(source_file_ids=("broken.tf",), entries=(entry,))
    diff = render_transformation_diff(run_id="run-2", files=(source_file,), manifest=manifest)
    return ValidationRequest(run_id="run-2", files=(source_file,), manifest=manifest, diff=diff)


def test_resolve_validator_cli_binary_finds_the_compiled_binary() -> None:
    path = resolve_validator_cli_binary()
    assert path.is_file()


def test_real_adapter_passes_a_safe_rewrite() -> None:
    adapter = StaticValidationAdapter()
    results = adapter.validate(_safe_rewrite_request())
    assert len(results) == 1
    assert results[0].passed, results[0]
    assert results[0].check_id == "s3.tf:static-reparse"


def test_real_adapter_fails_a_syntax_breaking_rewrite() -> None:
    adapter = StaticValidationAdapter()
    results = adapter.validate(_breaking_rewrite_request())
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].reason is not None
    assert "no longer parses" in results[0].reason


def test_fake_adapter_replays_registered_results_for_the_same_run() -> None:
    """Real/fake parity: whatever the real adapter would report for a
    run, the fake can faithfully replay when a test registers exactly
    that -- the same registration-based parity ``FakeRepositorySource``/
    ``FakeTransformationPort`` already provide for their own ports."""

    real_adapter = StaticValidationAdapter()
    request = _safe_rewrite_request()
    real_results = real_adapter.validate(request)

    fake_adapter = FakeStaticValidationAdapter()
    fake_adapter.register(request.run_id, real_results)

    assert fake_adapter.validate(request) == real_results
    assert fake_adapter.calls == [request]


def test_fake_adapter_raises_for_an_unregistered_run() -> None:
    from cairn_kernel.errors import NotFoundError

    fake_adapter = FakeStaticValidationAdapter()
    try:
        fake_adapter.validate(_safe_rewrite_request())
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError for an unregistered run")


def test_validation_result_round_trips_the_rust_shape() -> None:
    """The adapter's own translation from raw CLI JSON into
    ``ValidationResult`` never drops a failing check's reason."""

    adapter = StaticValidationAdapter()
    results = adapter.validate(_breaking_rewrite_request())
    assert isinstance(results[0], ValidationResult)
    assert results[0].reason


def test_subprocess_call_never_uses_a_shell_or_network_module() -> None:
    source = _code_only(SUBPROCESS_ADAPTER_SOURCE.read_text())
    assert ("shell" + "=True") not in source
    for forbidden in ("socket", "urllib", "http.client", "requests", "boto3", "google.cloud"):
        assert forbidden not in source, f"{forbidden!r} must not appear in {SUBPROCESS_ADAPTER_SOURCE}"


def test_subprocess_run_is_called_with_a_fixed_argv_list_not_a_string() -> None:
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
