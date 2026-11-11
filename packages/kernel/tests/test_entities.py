from dataclasses import FrozenInstanceError, dataclass

import pytest
from cairn_kernel.hex import Entity, ValueObject


@dataclass(frozen=True, slots=True)
class Money(ValueObject):
    amount: int
    currency: str


@dataclass(eq=False)
class Workload(Entity):
    name: str


@dataclass(eq=False)
class OtherEntity(Entity):
    name: str


def test_value_object_is_immutable() -> None:
    money = Money(100, "GBP")
    assert money == Money(100, "GBP")
    with pytest.raises(FrozenInstanceError):
        money.amount = 200


def test_entity_equality_is_identity_based() -> None:
    assert Workload(id="w-1", name="billing") == Workload(id="w-1", name="other")
    assert Workload(id="w-1", name="billing") != Workload(id="w-2", name="billing")
    assert Workload(id="w-1", name="billing") != OtherEntity(id="w-1", name="billing")


def test_entity_is_hashable_by_identity() -> None:
    assert len({Workload(id="w-1", name="a"), Workload(id="w-1", name="b")}) == 1


def test_entity_not_comparable_to_other_types() -> None:
    assert Workload(id="w-1", name="billing") != "w-1"
