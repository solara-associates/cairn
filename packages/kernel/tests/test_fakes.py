from datetime import UTC, datetime

from cairn_kernel.hex import Clock, IdGenerator
from cairn_kernel.testing import FixedClock, FixedIdGenerator, InMemoryUnitOfWork


def test_fixed_clock_returns_constant_time() -> None:
    now = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    clock: Clock = FixedClock(now)
    assert clock.now() is now
    assert clock.now() is now


def test_fixed_id_generator_yields_sequential_ids() -> None:
    generator: IdGenerator = FixedIdGenerator()
    assert [generator.new_id() for _ in range(3)] == ["id-1", "id-2", "id-3"]


def test_fixed_id_generator_respects_start_offset() -> None:
    generator: IdGenerator = FixedIdGenerator(start=41)
    assert generator.new_id() == "id-41"


def test_in_memory_unit_of_work_records_outcome() -> None:
    unit_of_work = InMemoryUnitOfWork()
    unit_of_work.commit()
    unit_of_work.commit()
    unit_of_work.rollback()
    assert unit_of_work.commits == 2
    assert unit_of_work.rollbacks == 1
