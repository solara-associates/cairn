from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True)

    items: list[T]
    next_cursor: str | None
