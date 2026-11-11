from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

from cairn_kernel.errors import MissingDependencyError

T = TypeVar("T")


class DIContainer:
    def __init__(self) -> None:
        self._registrations: dict[type, object] = {}

    def register(self, interface: type[T], implementation: T) -> None:
        self._registrations[interface] = implementation

    def resolve(self, interface: type[T]) -> T:
        try:
            implementation = self._registrations[interface]
        except KeyError:
            name = f"{interface.__module__}.{interface.__qualname__}"
            raise MissingDependencyError(f"no registration for {name}") from None
        return implementation  # type: ignore[no-any-return]

    def has(self, interface: type) -> bool:
        return interface in self._registrations

    @contextmanager
    def override(self, interface: type[T], implementation: T) -> Iterator[None]:
        previous = self._registrations.get(interface)
        self._registrations[interface] = implementation
        try:
            yield
        finally:
            if previous is None:
                self._registrations.pop(interface, None)
            else:
                self._registrations[interface] = previous
