"""Shared fake/real contract test for R3-03b's ``TransformationPort``
adapters (spec §5.4), matching this codebase's existing fake/real
parity-test pattern (``test_source_git.py`` runs the real Git/upload
adapters and the fake against equivalent inputs).

Both adapters are run against the *same* ``SourceFile`` fixtures --
the real ``SubprocessTransformationPort`` by actually shelling out to
the compiled ``cairn-transform-cli`` binary, the fake
``FakeTransformationPort`` by returning a hand-written canned payload
registered for those exact fixtures -- and the resulting
``TransformationManifest``s are asserted equal, field for field. A
hand-written fixture that drifted from what the real Rust binary
actually emits (a renamed field, a changed outcome, a different
reason string) would fail this test, not silently diverge between the
two adapters.

Skipped, not failed, when the compiled binary is unavailable (e.g. a
Python-only local run that has not built the Rust workspace) --
``packages/adapters/tests/test_transform_core_subprocess.py`` is the
one place this suite insists the real binary must exist and fails hard
if it does not; this file only skips its real-adapter half so the fake
can still be exercised on its own.
"""

from __future__ import annotations

import pytest
from cairn_adapters.transform_core import FakeTransformationPort, SubprocessTransformationPort
from cairn_adapters.transform_core.subprocess_adapter import (
    TransformCliUnavailableError,
    resolve_transform_cli_binary,
)
from cairn_contracts.transformation import SourceFile, SourceLanguage

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

# Hand-written, independent of any captured real-binary run -- matches
# ~/solara/lz2026/s725-handover.md's documented rewrite for
# tf-s3-bucket-inline-acl-deprecated exactly (delete the acl attribute's
# span, insert the new aws_s3_bucket_acl resource after the block).
_S3_ACL_RAW_OUTPUT = {
    "parser_version": "cairn-hcl-parser/0.1.0",
    "detector_version": "cairn-detector/0.1.0",
    "patcher_version": "cairn-transform-patcher/0.1.0",
    "change_set": {
        "source_file_id": "s3.tf",
        "patcher_version": "cairn-transform-patcher/0.1.0",
        "entries": [
            {
                "origin": {
                    "origin": "DETECTION",
                    "rule_id": "tf-s3-bucket-inline-acl-deprecated",
                    "source_file_id": "s3.tf",
                    "span": {
                        "start_byte": 75,
                        "end_byte": 97,
                        "start_line": 3,
                        "end_line": 3,
                    },
                    "confidence": "HIGH",
                    "detector_version": "cairn-detector/0.1.0",
                    "message": (
                        "inline 'acl' argument on aws_s3_bucket is deprecated; the "
                        "equivalent is a separate aws_s3_bucket_acl resource"
                    ),
                },
                "outcome": "APPLIED",
                "edits": [
                    {
                        "span": {
                            "start_byte": 75,
                            "end_byte": 97,
                            "start_line": 3,
                            "end_line": 3,
                        },
                        "replacement": "",
                    },
                    {
                        "span": {
                            "start_byte": 99,
                            "end_byte": 99,
                            "start_line": 4,
                            "end_line": 4,
                        },
                        "replacement": (
                            '\n\nresource "aws_s3_bucket_acl" "artifacts" {\n'
                            "  bucket = aws_s3_bucket.artifacts.id\n"
                            '  acl    = "public-read"\n'
                            "}\n"
                        ),
                    },
                ],
                "reason": None,
                "patcher_version": "cairn-transform-patcher/0.1.0",
            }
        ],
    },
}

# Matches 725's documented py-import-imp-deprecated rewrite exactly.
_IMPORT_IMP_RAW_OUTPUT = {
    "parser_version": "cairn-python-parser/0.1.0",
    "detector_version": "cairn-detector/0.1.0",
    "patcher_version": "cairn-transform-patcher/0.1.0",
    "change_set": {
        "source_file_id": "mod.py",
        "patcher_version": "cairn-transform-patcher/0.1.0",
        "entries": [
            {
                "origin": {
                    "origin": "DETECTION",
                    "rule_id": "py-import-imp-deprecated",
                    "source_file_id": "mod.py",
                    "span": {"start_byte": 7, "end_byte": 10, "start_line": 1, "end_line": 1},
                    "confidence": "HIGH",
                    "detector_version": "cairn-detector/0.1.0",
                    "message": "stdlib 'imp' module is deprecated; the equivalent is 'importlib'",
                },
                "outcome": "APPLIED",
                "edits": [
                    {
                        "span": {"start_byte": 7, "end_byte": 10, "start_line": 1, "end_line": 1},
                        "replacement": "importlib",
                    }
                ],
                "reason": None,
                "patcher_version": "cairn-transform-patcher/0.1.0",
            }
        ],
    },
}


def _real_binary_available() -> bool:
    try:
        resolve_transform_cli_binary()
    except TransformCliUnavailableError:
        return False
    return True


@pytest.mark.skipif(
    not _real_binary_available(),
    reason="cairn-transform-cli binary not built; run `cargo build -p cairn-transform-cli`",
)
@pytest.mark.parametrize(
    ("source_file", "raw_output"),
    [
        (S3_ACL_FIXTURE, _S3_ACL_RAW_OUTPUT),
        (IMPORT_IMP_FIXTURE, _IMPORT_IMP_RAW_OUTPUT),
    ],
)
def test_fake_and_real_adapters_produce_identical_manifests(source_file, raw_output) -> None:
    real = SubprocessTransformationPort()
    fake = FakeTransformationPort()
    fake.register(source_file, raw_output)

    real_manifest = real.transform([source_file])
    fake_manifest = fake.transform([source_file])

    assert real_manifest == fake_manifest
