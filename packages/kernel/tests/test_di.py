import pytest
from cairn_kernel.errors import ErrorCode, MissingDependencyError
from cairn_kernel.hex import Clock, DIContainer, IdGenerator, SystemClock
from cairn_kernel.testing import FixedIdGenerator


def test_register_and_resolve() -> None:
    container = DIContainer()
    clock = SystemClock()
    container.register(Clock, clock)
    assert container.resolve(Clock) is clock


def test_resolve_unregistered_interface_raises() -> None:
    container = DIContainer()
    with pytest.raises(MissingDependencyError) as exc_info:
        container.resolve(IdGenerator)
    assert exc_info.value.code is ErrorCode.INTERNAL
    assert "IdGenerator" in exc_info.value.detail


def test_has_reports_registration_state() -> None:
    container = DIContainer()
    assert not container.has(IdGenerator)
    container.register(IdGenerator, FixedIdGenerator())
    assert container.has(IdGenerator)


def test_override_restores_previous_registration() -> None:
    container = DIContainer()
    container.register(IdGenerator, FixedIdGenerator(start=10))
    with container.override(IdGenerator, FixedIdGenerator(start=100)):
        assert container.resolve(IdGenerator).new_id() == "id-100"
    assert container.resolve(IdGenerator).new_id() == "id-10"


def test_override_removes_temporary_registration() -> None:
    container = DIContainer()
    with container.override(IdGenerator, FixedIdGenerator(start=100)):
        assert container.has(IdGenerator)
    assert not container.has(IdGenerator)
