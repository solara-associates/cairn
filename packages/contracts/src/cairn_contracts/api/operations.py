from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Progress = Annotated[float | None, Field(ge=0, le=1)]


class OperationState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Operation(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_id: str
    state: OperationState
    progress: Progress
    result_ref: str | None
