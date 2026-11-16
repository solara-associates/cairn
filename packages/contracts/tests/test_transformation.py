"""Tests for the R3-01 transformation contracts: ``RepositoryRef`` (a
tagged union of a Git ref and an uploaded-archive id) and ``SourceFile``.
"""

from __future__ import annotations

import pytest
from cairn_contracts.transformation import (
    GitRepositoryRef,
    SourceFile,
    SourceLanguage,
    UploadRepositoryRef,
)
from cairn_contracts.transformation.model import RepositoryRef
from pydantic import TypeAdapter, ValidationError

REF_ADAPTER: TypeAdapter[object] = TypeAdapter(RepositoryRef)


def test_git_repository_ref_round_trips_through_the_tagged_union() -> None:
    ref = GitRepositoryRef(url="https://example.invalid/repo.git", ref="main")
    parsed = REF_ADAPTER.validate_python({"kind": "GIT", "url": ref.url, "ref": ref.ref})
    assert parsed == ref
    assert isinstance(parsed, GitRepositoryRef)


def test_upload_repository_ref_round_trips_through_the_tagged_union() -> None:
    ref = UploadRepositoryRef(archive_id="archive-123")
    parsed = REF_ADAPTER.validate_python({"kind": "UPLOAD", "archive_id": "archive-123"})
    assert parsed == ref
    assert isinstance(parsed, UploadRepositoryRef)


def test_tagged_union_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        REF_ADAPTER.validate_python({"kind": "FTP", "url": "ftp://example.invalid"})


def test_git_repository_ref_requires_a_non_blank_url_and_ref() -> None:
    with pytest.raises(ValidationError):
        GitRepositoryRef(url="", ref="main")
    with pytest.raises(ValidationError):
        GitRepositoryRef(url="https://example.invalid/repo.git", ref="")


def test_upload_repository_ref_requires_a_non_blank_archive_id() -> None:
    with pytest.raises(ValidationError):
        UploadRepositoryRef(archive_id="")


def test_repository_refs_are_frozen() -> None:
    ref = GitRepositoryRef(url="https://example.invalid/repo.git", ref="main")
    with pytest.raises(ValidationError):
        ref.ref = "other"  # type: ignore[misc]


def test_source_file_carries_a_detected_language() -> None:
    terraform_file = SourceFile(path="main.tf", content="", language=SourceLanguage.TERRAFORM)
    python_file = SourceFile(path="app.py", content="", language=SourceLanguage.PYTHON)
    other_file = SourceFile(path="README.md", content="", language=SourceLanguage.UNSUPPORTED)

    assert terraform_file.language is SourceLanguage.TERRAFORM
    assert python_file.language is SourceLanguage.PYTHON
    assert other_file.language is SourceLanguage.UNSUPPORTED


def test_source_file_is_never_required_to_drop_an_out_of_scope_file() -> None:
    # A file in neither ADR-015 language is still a valid, constructible
    # SourceFile -- UNSUPPORTED is a legal language, not a rejection.
    unsupported = SourceFile(path="notes.txt", content="some notes", language=SourceLanguage.UNSUPPORTED)
    assert unsupported.content == "some notes"


def test_source_file_is_frozen() -> None:
    source_file = SourceFile(path="main.tf", content="x", language=SourceLanguage.TERRAFORM)
    with pytest.raises(ValidationError):
        source_file.content = "y"  # type: ignore[misc]
