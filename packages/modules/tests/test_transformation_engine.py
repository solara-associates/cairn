"""Tests for R3-03b's ``TransformationPort`` protocol shape and the
manifest ADR-015 requires.

``build_manifest`` is exercised against hand-constructed raw
``CliOutput`` payloads shaped exactly like 725/726's real Rust pipeline
serializes (``ChangeSet``/``ChangeEntry``/``ChangeOrigin``), matching
``~/solara/lz2026/s725-handover.md``'s documented shape, not a
simplified stand-in for it. Applied/skipped/unsupported counts and
reasons are checked against exactly what 725's handover says the
engine produces for its two documented rules plus its one documented
deliberate-break case, so this test also doubles as the "manifest
correctness ... matches what 725's ChangeSet reported" acceptance item.
"""

from __future__ import annotations

from cairn_modules.transformation.engine import (
    ManifestOutcome,
    TransformationPort,
    build_manifest,
)

DETECTOR_VERSION = "cairn-detector/0.1.0"
PATCHER_VERSION = "cairn-transform-patcher/0.1.0"
HCL_PARSER_VERSION = "cairn-hcl-parser/0.1.0"
PYTHON_PARSER_VERSION = "cairn-python-parser/0.1.0"


def _detection_origin(rule_id: str) -> dict:
    return {
        "origin": "DETECTION",
        "rule_id": rule_id,
        "source_file_id": "s3.tf",
        "span": {"start_byte": 10, "end_byte": 20, "start_line": 2, "end_line": 2},
        "confidence": "HIGH",
        "detector_version": DETECTOR_VERSION,
        "message": "deprecated inline acl",
    }


def _skipped_origin(rule_id: str, reason: str) -> dict:
    return {
        "origin": "SKIPPED_CANDIDATE",
        "rule_id": rule_id,
        "source_file_id": "s3.tf",
        "span": {"start_byte": 30, "end_byte": 40, "start_line": 5, "end_line": 5},
        "detector_version": DETECTOR_VERSION,
        "reason": reason,
    }


def _applied_entry(rule_id: str) -> dict:
    return {
        "origin": _detection_origin(rule_id),
        "outcome": "APPLIED",
        "edits": [
            {
                "span": {"start_byte": 10, "end_byte": 20, "start_line": 2, "end_line": 2},
                "replacement": "",
            }
        ],
        "reason": None,
        "patcher_version": PATCHER_VERSION,
    }


def _skipped_entry(rule_id: str, reason: str) -> dict:
    return {
        "origin": _skipped_origin(rule_id, reason),
        "outcome": "SKIPPED",
        "edits": [],
        "reason": reason,
        "patcher_version": PATCHER_VERSION,
    }


def _unsupported_entry(rule_id: str, reason: str) -> dict:
    return {
        "origin": _detection_origin(rule_id),
        "outcome": "UNSUPPORTED",
        "edits": [],
        "reason": reason,
        "patcher_version": PATCHER_VERSION,
    }


def test_the_port_has_exactly_one_method_and_it_is_transform() -> None:
    public_members = {
        name
        for name in vars(TransformationPort)
        if not name.startswith("_") and callable(getattr(TransformationPort, name))
    }
    assert public_members == {"transform"}


def test_build_manifest_counts_applied_skipped_unsupported_matching_change_set() -> None:
    raw_output = {
        "parser_version": HCL_PARSER_VERSION,
        "detector_version": DETECTOR_VERSION,
        "patcher_version": PATCHER_VERSION,
        "change_set": {
            "source_file_id": "s3.tf",
            "patcher_version": PATCHER_VERSION,
            "entries": [
                _applied_entry("tf-s3-bucket-inline-acl-deprecated"),
                _skipped_entry(
                    "tf-s3-bucket-inline-acl-deprecated",
                    "candidate is inside a dynamic block",
                ),
                _unsupported_entry(
                    "tf-s3-bucket-inline-acl-deprecated",
                    "unsupported: acl value contains a runtime string interpolation",
                ),
            ],
        },
    }

    manifest = build_manifest([("s3.tf", raw_output)])

    assert manifest.source_file_ids == ("s3.tf",)
    assert len(manifest.entries) == 3
    assert manifest.applied_count == 1
    assert manifest.skipped_count == 1
    assert manifest.unsupported_count == 1

    applied, skipped, unsupported = manifest.entries
    assert applied.outcome is ManifestOutcome.APPLIED
    assert applied.reason is None
    assert len(applied.edits) == 1
    assert skipped.outcome is ManifestOutcome.SKIPPED
    assert skipped.reason == "candidate is inside a dynamic block"
    assert skipped.edits == ()
    assert unsupported.outcome is ManifestOutcome.UNSUPPORTED
    assert "runtime string interpolation" in unsupported.reason
    assert unsupported.edits == ()


def test_version_fields_are_recorded_per_entry_not_hardcoded() -> None:
    raw_output = {
        "parser_version": PYTHON_PARSER_VERSION,
        "detector_version": DETECTOR_VERSION,
        "patcher_version": PATCHER_VERSION,
        "change_set": {
            "source_file_id": "mod.py",
            "patcher_version": PATCHER_VERSION,
            "entries": [_applied_entry("py-import-imp-deprecated")],
        },
    }

    manifest = build_manifest([("mod.py", raw_output)])
    entry = manifest.entries[0]

    assert entry.source_file_id == "mod.py"
    assert entry.rule_id == "py-import-imp-deprecated"
    assert entry.detector_version == DETECTOR_VERSION
    assert entry.pattern_version == PYTHON_PARSER_VERSION
    assert entry.patcher_version == PATCHER_VERSION
    # No rule in today's corpus needs R2-01's mapping resolver (confirmed
    # in ~/solara/lz2026/s725-handover.md by reading 725's actual Rust
    # source, not assumed) -- this field is None for every entry, not a
    # fabricated value.
    assert entry.mapping_release_version is None


def test_build_manifest_covers_multiple_source_files_in_given_order() -> None:
    hcl_output = {
        "parser_version": HCL_PARSER_VERSION,
        "detector_version": DETECTOR_VERSION,
        "patcher_version": PATCHER_VERSION,
        "change_set": {
            "source_file_id": "s3.tf",
            "patcher_version": PATCHER_VERSION,
            "entries": [_applied_entry("tf-s3-bucket-inline-acl-deprecated")],
        },
    }
    python_output = {
        "parser_version": PYTHON_PARSER_VERSION,
        "detector_version": DETECTOR_VERSION,
        "patcher_version": PATCHER_VERSION,
        "change_set": {
            "source_file_id": "mod.py",
            "patcher_version": PATCHER_VERSION,
            "entries": [_applied_entry("py-import-imp-deprecated")],
        },
    }

    manifest = build_manifest([("s3.tf", hcl_output), ("mod.py", python_output)])

    assert manifest.source_file_ids == ("s3.tf", "mod.py")
    assert [entry.source_file_id for entry in manifest.entries] == ["s3.tf", "mod.py"]
    assert manifest.applied_count == 2


def test_empty_change_set_produces_an_empty_manifest_not_an_error() -> None:
    raw_output = {
        "parser_version": HCL_PARSER_VERSION,
        "detector_version": DETECTOR_VERSION,
        "patcher_version": PATCHER_VERSION,
        "change_set": {
            "source_file_id": "clean.tf",
            "patcher_version": PATCHER_VERSION,
            "entries": [],
        },
    }

    manifest = build_manifest([("clean.tf", raw_output)])

    assert manifest.entries == ()
    assert manifest.applied_count == 0
    assert manifest.skipped_count == 0
    assert manifest.unsupported_count == 0
