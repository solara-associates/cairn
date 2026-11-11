from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValueObject:
    pass


@dataclass(eq=False)
class Entity:
    id: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return type(self) is type(other) and self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self), self.id))
