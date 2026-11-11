from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from cairn_kernel.errors import NotFoundError, ValidationError
from cairn_kernel.hex import (
    Clock,
    CommandContext,
    Entity,
    IdGenerator,
    Port,
    ValueObject,
)


@dataclass(frozen=True, slots=True)
class NoteId(ValueObject):
    value: str


@dataclass(eq=False)
class Note(Entity):
    id: str
    text: str
    created_by: str
    created_at: datetime


class NoteRepository(Port, Protocol):
    def add(self, note: Note) -> None: ...

    def get(self, note_id: str) -> Note: ...


class InMemoryNoteRepository:
    def __init__(self) -> None:
        self._notes: dict[str, Note] = {}

    def add(self, note: Note) -> None:
        self._notes[note.id] = note

    def get(self, note_id: str) -> Note:
        try:
            return self._notes[note_id]
        except KeyError:
            raise NotFoundError(f"note {note_id} does not exist") from None


@dataclass(frozen=True, slots=True)
class CreateNote:
    text: str


class CreateNoteUseCase:
    def __init__(
        self,
        repository: NoteRepository,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_generator = id_generator

    def execute(self, command: CreateNote, context: CommandContext) -> Note:
        if not command.text.strip():
            raise ValidationError("note text must not be blank")
        note = Note(
            id=self._id_generator.new_id(),
            text=command.text,
            created_by=context.actor_id,
            created_at=self._clock.now(),
        )
        self._repository.add(note)
        return note
