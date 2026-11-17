"""R5-02a: a deterministic ``ModelPort`` fake (ADR-014: "A fake adapter is
mandatory for deterministic tests").

Never a network call, never a real credential. Each call pops the next
caller-configured canned response (or raises a caller-configured
exception) off a queue and records the request it was given, in order --
purely so a test can assert the adapter was, or was not, invoked (the
contract tests' "the fake's call counter stays at zero past the block
point" requirement reads ``call_count`` directly).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cairn_kernel.model import ModelRequest, ModelResponse

#: Not a real provider/model name -- this adapter never calls one.
FAKE_PROVIDER = "fake"
FAKE_MODEL = "fake-model-v1"


@dataclass
class FakeModelAdapter:
    """``ModelPort`` test double. Configure ``responses`` (and/or
    ``errors``, keyed by the 0-based call index at which they should raise)
    before exercising it; ``calls`` records every ``ModelRequest`` this
    adapter actually received, in order.
    """

    responses: list[ModelResponse] = field(default_factory=list)
    errors: dict[int, Exception] = field(default_factory=dict)
    calls: list[ModelRequest] = field(default_factory=list)

    def generate(self, request: ModelRequest) -> ModelResponse:
        index = len(self.calls)
        self.calls.append(request)
        if index in self.errors:
            raise self.errors[index]
        if not self.responses:
            raise LookupError("FakeModelAdapter has no canned response configured")
        return self.responses[min(index, len(self.responses) - 1)]

    @property
    def call_count(self) -> int:
        return len(self.calls)


__all__ = ["FAKE_MODEL", "FAKE_PROVIDER", "FakeModelAdapter"]
