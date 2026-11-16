"""Tests for R3-03b's ``FakeTransformationPort`` -- the fake never
shells out, never touches the filesystem for a binary, and raises a
clear error (not a silent empty manifest) for an unregistered fixture,
matching ``FakeRepositorySource``'s (721) "exact registration, no
fuzzy matching" discipline.
"""

from __future__ import annotations

import pytest
from cairn_adapters.transform_core import FakeTransformationPort
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_kernel.errors import NotFoundError

FIXTURE = SourceFile(path="mod.py", content="import imp\n", language=SourceLanguage.PYTHON)

RAW_OUTPUT = {
    "parser_version": "cairn-python-parser/0.1.0",
    "detector_version": "cairn-detector/0.1.0",
    "patcher_version": "cairn-transform-patcher/0.1.0",
    "change_set": {
        "source_file_id": "mod.py",
        "patcher_version": "cairn-transform-patcher/0.1.0",
        "entries": [],
    },
}


def test_unregistered_source_file_raises_not_found_not_an_empty_manifest() -> None:
    fake = FakeTransformationPort()
    with pytest.raises(NotFoundError):
        fake.transform([FIXTURE])


def test_registered_source_file_returns_its_canned_manifest() -> None:
    fake = FakeTransformationPort()
    fake.register(FIXTURE, RAW_OUTPUT)
    manifest = fake.transform([FIXTURE])
    assert manifest.source_file_ids == ("mod.py",)
    assert manifest.entries == ()


def test_fake_records_every_call_in_order() -> None:
    fake = FakeTransformationPort()
    fake.register(FIXTURE, RAW_OUTPUT)
    fake.transform([FIXTURE])
    fake.transform([FIXTURE])
    assert fake.calls == [[FIXTURE], [FIXTURE]]


def test_fake_never_imports_subprocess() -> None:
    import ast

    import cairn_adapters.transform_core.fake as fake_module

    with open(fake_module.__file__) as handle:
        tree = ast.parse(handle.read())
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "subprocess" not in imported_names
