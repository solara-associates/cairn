from typing import Protocol, TypeVar

from cairn_kernel.hex.primitives import CommandContext

CommandT = TypeVar("CommandT")
ResultT = TypeVar("ResultT")


class UseCase(Protocol[CommandT, ResultT]):
    def execute(self, command: CommandT, context: CommandContext) -> ResultT: ...
