"""R3-04: ``cairn_modules.transformation.diff``.

Exercises diff correctness against known ``TransformationManifest``
fixtures built the same way ``test_transformation_engine.py`` builds
them (hand-constructed ``ManifestEntry``/``ManifestEdit`` values, not a
simplified stand-in for 725/726's real shape), plus a construction-proof
test that no code path in this module writes to any real file anywhere
on disk -- the diff is computed, never applied.
"""

from __future__ import annotations

import ast
from pathlib import Path

from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_modules.transformation.diff import (
    FileDiff,
    TransformationDiff,
    render_file_diff,
    render_transformation_diff,
)
from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)

DETECTOR_VERSION = "cairn-detector/0.1.0"
PATTERN_VERSION = "cairn-hcl-parser/0.1.0"
PATCHER_VERSION = "cairn-transform-patcher/0.1.0"

S3_TF_CONTENT = 'resource "aws_s3_bucket" "b" {\n  acl = "public-read"\n}\n'


def _applied_entry() -> ManifestEntry:
    return ManifestEntry(
        source_file_id="s3.tf",
        rule_id="tf-s3-bucket-inline-acl-deprecated",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(
            ManifestEdit(
                start_byte=33,
                end_byte=52,
                start_line=2,
                end_line=2,
                replacement='acl = "private"',
            ),
        ),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )


def _skipped_entry() -> ManifestEntry:
    return ManifestEntry(
        source_file_id="s3.tf",
        rule_id="tf-s3-bucket-inline-acl-deprecated",
        outcome=ManifestOutcome.SKIPPED,
        reason="candidate is inside a dynamic block",
        edits=(),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )


def _unsupported_entry() -> ManifestEntry:
    return ManifestEntry(
        source_file_id="s3.tf",
        rule_id="tf-s3-bucket-inline-acl-deprecated",
        outcome=ManifestOutcome.UNSUPPORTED,
        reason="unsupported: acl value contains a runtime string interpolation",
        edits=(),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )


def _source_file() -> SourceFile:
    return SourceFile(path="s3.tf", content=S3_TF_CONTENT, language=SourceLanguage.TERRAFORM)


def test_render_file_diff_applies_only_applied_edits() -> None:
    manifest = TransformationManifest(
        source_file_ids=("s3.tf",),
        entries=(_applied_entry(), _skipped_entry(), _unsupported_entry()),
    )

    file_diff = render_file_diff(_source_file(), manifest)

    assert file_diff.source_file_id == "s3.tf"
    assert file_diff.original_content == S3_TF_CONTENT
    assert file_diff.rendered_content == 'resource "aws_s3_bucket" "b" {\n  acl = "private"\n}\n'
    assert file_diff.changed is True
    assert file_diff.applied_count == 1
    assert file_diff.skipped_count == 1
    assert file_diff.unsupported_count == 1
    assert len(file_diff.entries) == 3


def test_unified_diff_text_shows_the_exact_removed_and_added_lines() -> None:
    manifest = TransformationManifest(source_file_ids=("s3.tf",), entries=(_applied_entry(),))

    file_diff = render_file_diff(_source_file(), manifest)

    assert "--- a/s3.tf" in file_diff.unified_diff
    assert "+++ b/s3.tf" in file_diff.unified_diff
    assert '-  acl = "public-read"' in file_diff.unified_diff
    assert '+  acl = "private"' in file_diff.unified_diff


def test_no_change_produces_an_empty_unified_diff_not_a_noop_hunk() -> None:
    manifest = TransformationManifest(source_file_ids=("s3.tf",), entries=(_skipped_entry(),))

    file_diff = render_file_diff(_source_file(), manifest)

    assert file_diff.unified_diff == ""
    assert file_diff.changed is False
    assert file_diff.rendered_content == file_diff.original_content


def test_multiple_applied_edits_apply_back_to_front_without_shifting_offsets() -> None:
    content = "AAAA\nBBBB\nCCCC\n"
    source_file = SourceFile(path="multi.py", content=content, language=SourceLanguage.PYTHON)
    first_edit = ManifestEntry(
        source_file_id="multi.py",
        rule_id="rule-one",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(ManifestEdit(start_byte=0, end_byte=4, start_line=1, end_line=1, replacement="ZZ"),),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )
    second_edit = ManifestEntry(
        source_file_id="multi.py",
        rule_id="rule-two",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(ManifestEdit(start_byte=5, end_byte=9, start_line=2, end_line=2, replacement="YY"),),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )
    manifest = TransformationManifest(
        source_file_ids=("multi.py",), entries=(first_edit, second_edit)
    )

    file_diff = render_file_diff(source_file, manifest)

    assert file_diff.rendered_content == "ZZ\nYY\nCCCC\n"


def test_multibyte_content_is_edited_by_utf8_byte_offset_not_str_index() -> None:
    # "café" is 4 Python characters but 5 UTF-8 bytes (the "é" is 2
    # bytes) -- a byte-offset edit placed after it must land correctly
    # whether or not this module's own arithmetic naively used str
    # indices instead of byte offsets.
    content = 'name = "café"\nacl = "public-read"\n'
    source_file = SourceFile(path="multibyte.tf", content=content, language=SourceLanguage.TERRAFORM)
    encoded = content.encode("utf-8")
    start = encoded.index(b'acl = "public-read"')
    end = start + len(b'acl = "public-read"')
    entry = ManifestEntry(
        source_file_id="multibyte.tf",
        rule_id="rule",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(
            ManifestEdit(
                start_byte=start, end_byte=end, start_line=2, end_line=2, replacement='acl = "private"'
            ),
        ),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )
    manifest = TransformationManifest(source_file_ids=("multibyte.tf",), entries=(entry,))

    file_diff = render_file_diff(source_file, manifest)

    assert file_diff.rendered_content == 'name = "café"\nacl = "private"\n'


def test_render_transformation_diff_covers_every_manifest_file_in_order() -> None:
    tf_file = _source_file()
    py_file = SourceFile(path="mod.py", content="import imp\n", language=SourceLanguage.PYTHON)
    py_entry = ManifestEntry(
        source_file_id="mod.py",
        rule_id="py-import-imp-deprecated",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(ManifestEdit(start_byte=7, end_byte=10, start_line=1, end_line=1, replacement="importlib"),),
        detector_version=DETECTOR_VERSION,
        pattern_version="cairn-python-parser/0.1.0",
        patcher_version=PATCHER_VERSION,
    )
    manifest = TransformationManifest(
        source_file_ids=("s3.tf", "mod.py"), entries=(_applied_entry(), py_entry)
    )

    diff = render_transformation_diff(
        run_id="run-1", files=[tf_file, py_file], manifest=manifest
    )

    assert isinstance(diff, TransformationDiff)
    assert diff.run_id == "run-1"
    assert diff.source_file_ids == ("s3.tf", "mod.py")
    assert [file_diff.source_file_id for file_diff in diff.files] == ["s3.tf", "mod.py"]
    assert diff.applied_count == 2
    assert all(isinstance(file_diff, FileDiff) for file_diff in diff.files)


def test_render_transformation_diff_ignores_files_the_manifest_never_covered() -> None:
    """An UNSUPPORTED-language file 726's port never sent to the
    TransformationPort is absent from manifest.source_file_ids -- it
    must not be given a (fabricated, "nothing changed") FileDiff."""

    tf_file = _source_file()
    unrelated_file = SourceFile(
        path="README.md", content="# hello\n", language=SourceLanguage.UNSUPPORTED
    )
    manifest = TransformationManifest(source_file_ids=("s3.tf",), entries=(_applied_entry(),))

    diff = render_transformation_diff(
        run_id="run-2", files=[tf_file, unrelated_file], manifest=manifest
    )

    assert diff.source_file_ids == ("s3.tf",)
    assert len(diff.files) == 1


def test_render_transformation_diff_raises_if_a_covered_file_is_missing() -> None:
    manifest = TransformationManifest(source_file_ids=("s3.tf",), entries=(_applied_entry(),))

    try:
        render_transformation_diff(run_id="run-3", files=[], manifest=manifest)
    except ValueError as exc:
        assert "s3.tf" in str(exc)
    else:
        raise AssertionError("expected a ValueError for a missing SourceFile")


def test_rendering_a_diff_never_mutates_the_original_source_file_object() -> None:
    source_file = _source_file()
    original_content = source_file.content
    manifest = TransformationManifest(source_file_ids=("s3.tf",), entries=(_applied_entry(),))

    render_file_diff(source_file, manifest)

    # SourceFile is a frozen pydantic model; this is also a direct,
    # explicit check that render_file_diff returned a new string rather
    # than mutating anything reachable from the SourceFile it was given.
    assert source_file.content == original_content == S3_TF_CONTENT


def test_no_file_write_call_anywhere_in_the_diff_module_source() -> None:
    """Construction-proof: statically scan this module's own source for
    any call that could write to a real path on disk (``open`` in a
    write mode, ``Path.write_text``/``write_bytes``,
    ``shutil``/``os`` write helpers) -- the diff artefact this module
    renders is derived purely in memory from values it is given, never
    written back to any file. Mirrors the same AST-scan discipline
    ``cairn_adapters.transform_core``'s ``no_network_imports_in_cli_
    source``-style tests already use elsewhere in this corpus."""

    diff_module_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "cairn_modules"
        / "transformation"
        / "diff.py"
    )
    tree = ast.parse(diff_module_path.read_text(encoding="utf-8"))

    forbidden_write_attrs = {"write_text", "write_bytes", "unlink", "rmtree", "remove", "rename"}
    forbidden_modules = {"shutil", "os", "subprocess", "socket", "urllib", "requests"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {alias.name for alias in node.names}
            module_name = getattr(node, "module", None)
            assert not (names & forbidden_modules), f"unexpected import: {names}"
            assert module_name not in forbidden_modules, f"unexpected import: {module_name}"
        if isinstance(node, ast.Attribute) and node.attr in forbidden_write_attrs:
            raise AssertionError(f"unexpected file-mutating attribute access: {node.attr}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            raise AssertionError("unexpected open() call in diff.py")
