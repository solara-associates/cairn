"""R6-01: ``cairn_kits.loop.PromptRegistry`` and the A6.prompts check
(ADR-019 §9)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cairn_kernel.errors import MissingDependencyError, NotFoundError, ValidationError
from cairn_kits.loop import PromptRegistry, find_prompt_literal_violations

REPO_ROOT = Path(__file__).parents[3]
PROMPTS_DIR = REPO_ROOT / "prompts"


def _write_prompt(directory: Path, agent: str, name: str, version: int, declared_id: str | None = None) -> Path:
    agent_dir = directory / agent
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / f"{name}.v{version}.md"
    path.write_text(
        f"---\nid: {declared_id if declared_id is not None else f'{agent}/{name}'}\nversion: {version}\n---\n\nbody text\n",
        encoding="utf-8",
    )
    return path


def test_load_resolves_prompts_by_id_and_version(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "assessment-explainer", "system", 1)
    _write_prompt(tmp_path, "assessment-explainer", "system", 2)

    registry = PromptRegistry.load(tmp_path)

    v1 = registry.get("assessment-explainer/system", 1)
    v2 = registry.get("assessment-explainer/system", 2)
    assert v1.body == "body text"
    assert v1.version == 1
    assert v2.version == 2


def test_get_unknown_prompt_raises_not_found(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "assessment-explainer", "system", 1)
    registry = PromptRegistry.load(tmp_path)

    with pytest.raises(NotFoundError):
        registry.get("assessment-explainer/system", 99)


def test_validate_references_raises_for_a_missing_reference_at_validation_time(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "assessment-explainer", "system", 1)
    registry = PromptRegistry.load(tmp_path)

    with pytest.raises(MissingDependencyError):
        registry.validate_references(
            [("assessment-explainer/system", 1), ("assessment-explainer/missing", 1)]
        )

    # the reference that does exist is untouched -- validation never
    # raises for a resolvable reference, so this would not raise alone.
    registry.validate_references([("assessment-explainer/system", 1)])


def test_a_prompt_file_whose_declared_id_disagrees_with_its_path_raises(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "assessment-explainer", "system", 1, declared_id="design-proposer/system")

    with pytest.raises(ValidationError):
        PromptRegistry.load(tmp_path)


def test_duplicate_id_and_version_raises(tmp_path: Path) -> None:
    from cairn_kits.loop.prompt_registry import PromptArtifact

    path = _write_prompt(tmp_path, "assessment-explainer", "system", 1)
    first = PromptRegistry.load(tmp_path).get("assessment-explainer/system", 1)
    duplicate = PromptArtifact(
        prompt_id="assessment-explainer/system",
        version=1,
        path=path.with_name("other.md"),
        body="duplicate",
    )
    with pytest.raises(ValidationError):
        PromptRegistry([first, duplicate])


def test_the_real_prompts_directory_loads_and_has_the_ten_design_artefacts() -> None:
    registry = PromptRegistry.load(PROMPTS_DIR)
    assert len(registry) == 10
    for agent, name, version in [
        ("assessment-explainer", "system", 1),
        ("assessment-explainer", "explain-disposition", 1),
        ("assessment-explainer", "detect-anomalies", 1),
        ("assessment-explainer", "draft-summary", 1),
        ("design-proposer", "system", 1),
        ("design-proposer", "select-pattern", 1),
        ("design-proposer", "assign-waves", 1),
        ("modernize-proposer", "system", 1),
        ("modernize-proposer", "scope-transformation", 1),
        ("modernize-proposer", "explain-diff", 1),
    ]:
        registry.get(f"{agent}/{name}", version)


def test_a6_prompts_check_finds_no_prompt_literal_above_the_threshold() -> None:
    violations = find_prompt_literal_violations([REPO_ROOT / "packages", REPO_ROOT / "apps"])
    assert violations == []
