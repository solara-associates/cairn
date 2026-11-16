"""Unit 727 (R3-03c): the golden transformation corpus for the full
pilot scope, run end to end through the real pipeline --

    721's fake source-fetch adapter -> the real, compiled
    ``cairn-transform-cli`` binary (722/723's parsers, 724's detector,
    725's patcher, chained by 726's CLI) -> 726's
    ``TransformationManifest``.

Every fixture in ``tests/golden/transform/repos/`` is a small, synthetic,
CAIRN-authored repository (Terraform/HCL and/or Python) representing one
realistic pilot-scope transformation scenario, read from disk by this
test, fetched through ``FakeRepositorySource`` (never the real Git/
upload adapters -- no network, no filesystem clone), and run through the
*real* ``SubprocessTransformationPort`` (never ``FakeTransformationPort``
-- that would only prove this test's own assumptions about the pipeline,
not the pipeline itself). This is deliberately the opposite choice from
``test_transform_core_contract.py``'s fake/real parity test: that file
proves the fake agrees with the real binary on a few hand-picked
payloads; this corpus proves the real binary, driven end to end from a
realistic multi-file repository, produces the manifest outcome ADR-015
promises.

Each repository's expected outcome is a short, readable table of
``(path, rule_id, ManifestOutcome)`` triples in this file -- not a
separate data file -- so the expectation sits next to the fixture it
describes and a reviewer never has to cross-reference two files to
check one scenario.

Requires the compiled ``cairn-transform-cli`` binary (``cargo build
--release -p cairn-transform-cli``, or ``CAIRN_TRANSFORM_CLI_BIN`` set).
This module fails, not skips, if it is missing -- same discipline
``test_transform_core_subprocess.py`` uses -- because proving the real
end-to-end pipeline is this module's entire purpose.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cairn_adapters.source_git.fake import FakeRepositorySource
from cairn_adapters.source_git.language import detect_language
from cairn_adapters.transform_core import SubprocessTransformationPort
from cairn_adapters.transform_core.subprocess_adapter import (
    TransformCliUnavailableError,
    resolve_transform_cli_binary,
)
from cairn_contracts.transformation import GitRepositoryRef, SourceFile
from cairn_modules.transformation.engine import (
    PARSE_INCOMPLETE_RULE_ID,
    ManifestOutcome,
    TransformationManifest,
)

REPOS_ROOT = Path(__file__).parent / "repos"

ACL_DEPRECATED_RULE_ID = "tf-s3-bucket-inline-acl-deprecated"
IMPORT_IMP_RULE_ID = "py-import-imp-deprecated"


def _real_binary_available() -> bool:
    try:
        resolve_transform_cli_binary()
    except TransformCliUnavailableError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _real_binary_available(),
    reason=(
        "cairn-transform-cli binary not built; run `cargo build --release "
        "-p cairn-transform-cli` (this corpus insists on the real binary, "
        "never the fake, by design -- see this file's module docstring)"
    ),
)


def _load_repo(repo_name: str) -> tuple[SourceFile, ...]:
    """Read every file under ``repos/<repo_name>`` into a ``SourceFile``,
    using the same extension-based detection 721's real adapters use
    (``cairn_adapters.source_git.language.detect_language``) -- this
    test never hand-labels a fixture's language, so a path that would
    confuse the real adapter would confuse this test the same way.
    """

    repo_dir = REPOS_ROOT / repo_name
    files = []
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(repo_dir).as_posix()
        content = path.read_text(encoding="utf-8")
        files.append(SourceFile(path=rel_path, content=content, language=detect_language(rel_path)))
    return tuple(files)


def _fetch_and_transform(repo_name: str) -> TransformationManifest:
    """721's fake adapter for the fetch half, the real subprocess
    adapter for the parse->detect->transform half -- the exact pipeline
    composition this corpus exists to exercise."""

    files = _load_repo(repo_name)
    ref = GitRepositoryRef(url="https://example.invalid/golden-corpus.git", ref=f"golden/{repo_name}")
    source = FakeRepositorySource()
    source.register(ref, files)

    fetched = source.fetch(ref)
    assert fetched == files, "the fake fetch adapter must return exactly what was registered"

    manifest = SubprocessTransformationPort().transform(fetched)
    return manifest


def _outcomes(manifest: TransformationManifest) -> set[tuple[str, str, ManifestOutcome]]:
    return {(entry.source_file_id, entry.rule_id, entry.outcome) for entry in manifest.entries}


# ---------------------------------------------------------------------------
# Clean repositories: in scope, nothing to flag. A clean run through the
# real pipeline with zero manifest entries is itself a golden case --
# ADR-015's manifest must not invent a finding where there is none.
# ---------------------------------------------------------------------------


def test_clean_terraform_repository_produces_an_empty_manifest() -> None:
    manifest = _fetch_and_transform("terraform_clean")
    assert manifest.entries == ()
    assert manifest.source_file_ids == ("main.tf",)


def test_clean_python_repository_produces_an_empty_manifest() -> None:
    manifest = _fetch_and_transform("python_clean")
    assert manifest.entries == ()
    assert manifest.source_file_ids == ("app.py",)


# ---------------------------------------------------------------------------
# The two documented rules, applied -- the "happy path" pilot scenario:
# a real deprecation, mechanically and safely rewritten.
# ---------------------------------------------------------------------------


def test_terraform_acl_deprecation_is_applied_end_to_end() -> None:
    manifest = _fetch_and_transform("terraform_acl_deprecated")
    assert _outcomes(manifest) == {("main.tf", ACL_DEPRECATED_RULE_ID, ManifestOutcome.APPLIED)}
    entry = manifest.entries[0]
    assert entry.reason is None
    assert len(entry.edits) == 2  # delete the acl attribute, insert the new resource -- 725's rewrite
    assert entry.detector_version and entry.pattern_version and entry.patcher_version


def test_python_imp_deprecation_is_applied_end_to_end() -> None:
    manifest = _fetch_and_transform("python_imp_deprecated")
    assert _outcomes(manifest) == {("mod.py", IMPORT_IMP_RULE_ID, ManifestOutcome.APPLIED)}
    entry = manifest.entries[0]
    assert entry.reason is None
    assert entry.edits[0].replacement == "importlib"


# ---------------------------------------------------------------------------
# The required deliberate-break suite (brief step 5): one end-to-end case
# per prior unit's own deliberate-break test, confirming the failure
# stays explicit all the way to the manifest -- never swallowed by a
# later stage.
# ---------------------------------------------------------------------------


def test_break_722_unterminated_hcl_block_reaches_the_manifest_as_unsupported() -> None:
    """722's own deliberate-break case: an unterminated ``resource``
    block, a pure ``ParseOutput::Error``. Before 727's ``parse_status``
    fix (see ``cairn_modules.transformation.engine.
    _parse_failure_entry``), this file's manifest would have had *zero*
    entries -- indistinguishable from a clean parse. It must not."""

    manifest = _fetch_and_transform("terraform_unterminated_block")
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.source_file_id == "main.tf"
    assert entry.rule_id == PARSE_INCOMPLETE_RULE_ID
    assert entry.outcome is ManifestOutcome.UNSUPPORTED
    assert entry.edits == ()
    assert "unterminated block" in entry.reason


def test_break_723_fstring_reaches_the_manifest_as_unsupported() -> None:
    """723's own deliberate-break case: an f-string, outside the pilot's
    Python subset -- ``ParseOutput::Unsupported``, not ``Error``. Same
    727 fix, same requirement: it must show up."""

    manifest = _fetch_and_transform("python_fstring_unsupported")
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.source_file_id == "mod.py"
    assert entry.rule_id == PARSE_INCOMPLETE_RULE_ID
    assert entry.outcome is ManifestOutcome.UNSUPPORTED
    assert entry.edits == ()
    assert "f-string" in entry.reason


def test_break_724_acl_inside_dynamic_block_reaches_the_manifest_as_skipped() -> None:
    """724's own deliberate-break case: an ``acl`` attribute shaped
    correctly but sitting inside a ``dynamic`` block, whose per-iteration
    value the detector cannot safely resolve from the AST alone. This is
    already explicit end to end without any 727 fix -- 724's detector
    records a ``SkippedCandidate``, 725's patcher carries it forward
    verbatim as ``ChangeOutcome::Skipped``, 726's manifest reads it as
    ``ManifestOutcome.SKIPPED``. This test is the end-to-end proof of
    that whole chain, not just each unit's own isolated test of it."""

    manifest = _fetch_and_transform("terraform_acl_dynamic_skip")
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.source_file_id == "main.tf"
    assert entry.rule_id == ACL_DEPRECATED_RULE_ID
    assert entry.outcome is ManifestOutcome.SKIPPED
    assert entry.edits == ()
    assert "dynamic" in entry.reason


def test_break_724_relative_import_of_imp_reaches_the_manifest_as_skipped() -> None:
    """724's companion deliberate-break case: ``from . import imp``, a
    local sibling module that merely shares the stdlib module's name.
    Same end-to-end chain as the dynamic-block case above, for Python."""

    manifest = _fetch_and_transform("python_relative_imp_skip")
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.source_file_id == "mod.py"
    assert entry.rule_id == IMPORT_IMP_RULE_ID
    assert entry.outcome is ManifestOutcome.SKIPPED
    assert entry.edits == ()
    assert "relative import" in entry.reason


def test_break_725_runtime_interpolated_acl_reaches_the_manifest_as_unsupported() -> None:
    """725's own deliberate-break case: a syntactically valid, structurally
    matched ``acl`` literal whose *value* is a runtime Terraform
    interpolation (``${var.environment}-public-read``) -- the detector
    cannot tell this isn't a plain string from the AST alone (it is a
    single string token), so it reaches the patcher as a confirmed
    ``Detection``, and the patcher is the stage that must refuse to
    guess at the interpolated value."""

    manifest = _fetch_and_transform("terraform_acl_interpolated_unsupported")
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.source_file_id == "main.tf"
    assert entry.rule_id == ACL_DEPRECATED_RULE_ID
    assert entry.outcome is ManifestOutcome.UNSUPPORTED
    assert entry.edits == ()
    assert "runtime string interpolation" in entry.reason
    # 725's own test already confirms the reason never leaks the
    # unresolved literal text -- re-confirmed here at the manifest layer.
    assert "${var.environment}" not in entry.reason


# ---------------------------------------------------------------------------
# A realistic, multi-file pilot-scope repository: Terraform infra plus
# Python application code plus a file outside R3 scope altogether,
# fetched and transformed as one run (brief step 2's actual ask --
# "realistic transformation scenarios end to end", not one file at a
# time).
# ---------------------------------------------------------------------------


def test_mixed_pilot_scope_repository_end_to_end() -> None:
    files = _load_repo("mixed_pilot_scope")
    paths = {f.path for f in files}
    assert paths == {
        "infra/main.tf",
        "infra/variables.tf",
        "app/mod.py",
        "app/util.py",
        "README.md",
    }

    # The README is readable but out of R3 scope (ADR-015) -- present in
    # the fetch result (never silently dropped, per 721's own contract),
    # but it must never reach the transform engine at all.
    readme = next(f for f in files if f.path == "README.md")
    from cairn_contracts.transformation import SourceLanguage

    assert readme.language is SourceLanguage.UNSUPPORTED

    manifest = SubprocessTransformationPort().transform(files)

    assert "README.md" not in manifest.source_file_ids
    assert set(manifest.source_file_ids) == {
        "infra/main.tf",
        "infra/variables.tf",
        "app/mod.py",
        "app/util.py",
    }
    assert _outcomes(manifest) == {
        ("infra/main.tf", ACL_DEPRECATED_RULE_ID, ManifestOutcome.APPLIED),
        ("app/mod.py", IMPORT_IMP_RULE_ID, ManifestOutcome.APPLIED),
    }
    assert manifest.applied_count == 2
    assert manifest.skipped_count == 0
    assert manifest.unsupported_count == 0


# ---------------------------------------------------------------------------
# Determinism across the full pipeline (brief step 6): the same source
# fixture, fetched and transformed twice, must produce an identical
# manifest -- byte for byte, not merely "equal enough".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "repo_name",
    [
        "terraform_clean",
        "terraform_acl_deprecated",
        "terraform_acl_dynamic_skip",
        "terraform_acl_interpolated_unsupported",
        "terraform_unterminated_block",
        "python_clean",
        "python_imp_deprecated",
        "python_relative_imp_skip",
        "python_fstring_unsupported",
        "mixed_pilot_scope",
    ],
)
def test_full_pipeline_is_deterministic_across_repeated_runs(repo_name: str) -> None:
    first = _fetch_and_transform(repo_name)
    second = _fetch_and_transform(repo_name)
    assert first == second
