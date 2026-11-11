import ast
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_kernel.errors import ErrorCode, NotFoundError, ValidationError
from cairn_kernel.hex import (
    CommandContext,
    MutationClass,
    OperationClass,
    ProjectId,
    TenantId,
)
from cairn_kernel.testing import FixedClock, FixedIdGenerator

from tests.contract import sample_module
from tests.contract.sample_module import (
    CreateNote,
    CreateNoteUseCase,
    InMemoryNoteRepository,
    Note,
    NoteRepository,
)

SAMPLE_PATH = Path(sample_module.__file__)


def make_context() -> CommandContext:
    return CommandContext(
        tenant_id=TenantId("tenant-1"),
        project_id=ProjectId("project-1"),
        actor_id="user-1",
        actor_roles=("ARCHITECT",),
        correlation_id="corr-1",
        operation_class=OperationClass.WORKSPACE_MUTATION,
        mutation_class=MutationClass.INTERNAL_MUTATION,
    )


def make_use_case() -> tuple[CreateNoteUseCase, InMemoryNoteRepository]:
    repository = InMemoryNoteRepository()
    use_case = CreateNoteUseCase(
        repository,
        clock=FixedClock(datetime(2026, 11, 11, 9, 30, tzinfo=UTC)),
        id_generator=FixedIdGenerator(),
    )
    return use_case, repository


def test_create_note_persists_and_returns_entity() -> None:
    use_case, repository = make_use_case()
    note = use_case.execute(CreateNote(text="confirm RLS coverage"), make_context())
    assert note.id == "id-1"
    assert note.text == "confirm RLS coverage"
    assert note.created_by == "user-1"
    assert note.created_at == datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    assert repository.get("id-1") is note


def test_create_note_rejects_blank_text() -> None:
    use_case, _ = make_use_case()
    with pytest.raises(ValidationError) as exc_info:
        use_case.execute(CreateNote(text="   "), make_context())
    assert exc_info.value.code is ErrorCode.VALIDATION_FAILED


def test_repository_reports_missing_note() -> None:
    _, repository = make_use_case()
    with pytest.raises(NotFoundError) as exc_info:
        repository.get("id-404")
    assert exc_info.value.code is ErrorCode.NOT_FOUND


def test_sample_types_follow_kernel_conventions() -> None:
    assert issubclass(Note, sample_module.Entity)
    assert sample_module.Port in NoteRepository.__mro__
    note_a = Note(id="n-1", text="a", created_by="u", created_at=datetime.now(UTC))
    note_b = Note(id="n-1", text="b", created_by="u", created_at=datetime.now(UTC))
    assert note_a == note_b


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_sample_module_imports_only_kernel_and_stdlib() -> None:
    tree = ast.parse(SAMPLE_PATH.read_text(encoding="utf-8"))
    roots = _imported_roots(tree)
    assert roots, "sample module must import something"
    violations = {
        root
        for root in roots
        if not root.startswith("cairn_kernel") and root not in sys.stdlib_module_names
    }
    assert not violations, f"non-kernel imports: {sorted(violations)}"
