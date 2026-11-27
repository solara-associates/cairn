"""R6-06 acceptance: ``VertexGeminiAdapter`` request/response translation
against an injected stub client -- no network, no real credential, no
GCP project needed to run this file.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from cairn_adapters.model import FAKE_MODEL, FAKE_PROVIDER, FakeModelAdapter
from cairn_adapters.model.selection import (
    ADAPTER_FAKE,
    ADAPTER_VERTEX,
    ENV_MODEL_ADAPTER,
    resolve_model_adapter,
)
from cairn_adapters.model.vertex_gemini import (
    ENV_LOCATION,
    ENV_MODEL,
    ENV_PROJECT,
    PROVIDER,
    VertexGeminiAdapter,
    VertexGeminiSettings,
    price_rate_for_model,
    register_vertex_price,
)
from cairn_kernel.errors import (
    ConfigurationError,
    ModelPriceUnavailableError,
    ProviderUnavailableError,
)
from cairn_kernel.model import (
    ModelRequest,
    SafetyParameters,
    StructuredOutputExpectation,
    default_price_table,
)

ENV = {
    ENV_PROJECT: "cairn-demo",
    ENV_LOCATION: "europe-west2",
    ENV_MODEL: "gemini-2.5-pro-002",
}


def _settings(**overrides: str) -> VertexGeminiSettings:
    values = {**ENV, **overrides}
    return VertexGeminiSettings(
        project=values[ENV_PROJECT], location=values[ENV_LOCATION], model=values[ENV_MODEL]
    )


def _request(*, agent_run_id: str | None = None) -> ModelRequest:
    return ModelRequest(
        prompt="Explain the disposition for workload w-1.",
        structured_output=StructuredOutputExpectation(
            schema_name="assessment.v1",
            schema={
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
            },
        ),
        safety=SafetyParameters(max_output_tokens=512, disallowed_categories=("HATE_SPEECH",)),
        tenant_id="tenant-1",
        correlation_id="corr-1",
        agent_run_id=agent_run_id,
    )


class _UsageMetadata:
    def __init__(self, prompt_tokens: int, output_tokens: int) -> None:
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = output_tokens


class _SafetyRating:
    def __init__(self, category: str, blocked: bool) -> None:
        self.category = category
        self.blocked = blocked


class _Candidate:
    def __init__(self, finish_reason: str = "STOP", safety_ratings: list | None = None) -> None:
        self.finish_reason = finish_reason
        self.safety_ratings = safety_ratings or []


class _PromptFeedback:
    def __init__(self, block_reason: str | None = None) -> None:
        self.block_reason = block_reason


class _StubResponse:
    def __init__(
        self,
        *,
        text: str = '{"summary": "ok"}',
        prompt_tokens: int = 40,
        output_tokens: int = 12,
        model_version: str = "gemini-2.5-pro-002-exact",
        candidates: list | None = None,
        prompt_feedback: _PromptFeedback | None = None,
    ) -> None:
        self.text = text
        self.usage_metadata = _UsageMetadata(prompt_tokens, output_tokens)
        self.model_version = model_version
        self.candidates = candidates if candidates is not None else [_Candidate()]
        self.prompt_feedback = prompt_feedback or _PromptFeedback()


class _StubModels:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._error is not None:
            raise self._error
        return self._response


class _StubClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.models = _StubModels(response=response, error=error)


def test_translates_request_and_response() -> None:
    client = _StubClient(response=_StubResponse())
    adapter = VertexGeminiAdapter(_settings(), client=client)

    result = adapter.generate(_request())

    assert result.output == {"summary": "ok"}
    assert result.provider == PROVIDER
    assert result.model == "gemini-2.5-pro-002-exact"
    assert result.input_tokens == 40
    assert result.output_tokens == 12
    assert result.safety.flagged is False

    [call] = client.models.calls
    assert call["model"] == "gemini-2.5-pro-002"
    assert call["contents"] == "Explain the disposition for workload w-1."
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["max_output_tokens"] == 512
    assert {"category": "HATE_SPEECH", "threshold": "BLOCK_LOW_AND_ABOVE"} in call["config"][
        "safety_settings"
    ]


def test_surfaces_blocked_prompt_safety_flag_never_swallowed() -> None:
    client = _StubClient(
        response=_StubResponse(prompt_feedback=_PromptFeedback(block_reason="SAFETY"))
    )
    adapter = VertexGeminiAdapter(_settings(), client=client)

    result = adapter.generate(_request())

    assert result.safety.flagged is True
    assert "SAFETY" in result.safety.categories


def test_surfaces_candidate_safety_rating_block() -> None:
    client = _StubClient(
        response=_StubResponse(
            candidates=[_Candidate(safety_ratings=[_SafetyRating("DANGEROUS_CONTENT", True)])]
        )
    )
    adapter = VertexGeminiAdapter(_settings(), client=client)

    result = adapter.generate(_request())

    assert result.safety.flagged is True
    assert "DANGEROUS_CONTENT" in result.safety.categories


def test_provider_error_maps_to_typed_kernel_error() -> None:
    client = _StubClient(error=RuntimeError("quota exceeded"))
    adapter = VertexGeminiAdapter(_settings(), client=client)

    with pytest.raises(ProviderUnavailableError):
        adapter.generate(_request())


def test_non_json_response_maps_to_typed_kernel_error() -> None:
    client = _StubClient(response=_StubResponse(text="not json"))
    adapter = VertexGeminiAdapter(_settings(), client=client)

    with pytest.raises(ProviderUnavailableError):
        adapter.generate(_request())


def test_location_outside_residency_set_raises_at_construction() -> None:
    with pytest.raises(ConfigurationError):
        _settings(**{ENV_LOCATION: "us-central1"})


def test_settings_from_env_reports_every_missing_value() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        VertexGeminiSettings.from_env({ENV_PROJECT: "cairn-demo"})
    assert ENV_LOCATION in str(excinfo.value)
    assert ENV_MODEL in str(excinfo.value)


def test_model_adapter_unset_resolves_to_fake() -> None:
    assert isinstance(resolve_model_adapter({}), FakeModelAdapter)
    assert isinstance(resolve_model_adapter({ENV_MODEL_ADAPTER: ADAPTER_FAKE}), FakeModelAdapter)


def test_selecting_vertex_with_missing_config_fails_at_startup() -> None:
    with pytest.raises(ConfigurationError):
        resolve_model_adapter({ENV_MODEL_ADAPTER: ADAPTER_VERTEX})


def test_selecting_vertex_with_full_config_builds_real_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cairn_adapters.model.vertex_gemini._default_client", lambda settings: _StubClient()
    )
    env = {**ENV, ENV_MODEL_ADAPTER: ADAPTER_VERTEX}

    adapter = resolve_model_adapter(env)

    assert isinstance(adapter, VertexGeminiAdapter)


def test_register_vertex_price_adds_a_real_rate() -> None:
    table = register_vertex_price(default_price_table(), _settings())
    rate = table.rate_for(PROVIDER, "gemini-2.5-pro-002")
    assert rate.input_micro_usd_per_1k_tokens > 0
    assert rate.output_micro_usd_per_1k_tokens > 0
    # the fake adapter's own pair is untouched
    assert table.rate_for(FAKE_PROVIDER, FAKE_MODEL) is not None


def test_price_rate_for_unknown_model_fails_closed() -> None:
    with pytest.raises(ConfigurationError):
        price_rate_for_model("gemini-unreleased-model")
    with pytest.raises(ModelPriceUnavailableError):
        default_price_table().rate_for(PROVIDER, "gemini-unreleased-model")


def test_adapter_module_contains_no_api_key_or_credential_literal() -> None:
    """A7.secrets, at the code level rather than the docstring that
    explains it: no call anywhere in this module passes an ``api_key``
    keyword, no name assignment is called ``GOOGLE_API_KEY`` or
    ``api_key``, and no string literal names the env var CAIRN never
    reads.
    """

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "cairn_adapters"
        / "model"
        / "vertex_gemini.py"
    )
    text = source.read_text(encoding="utf-8")

    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                assert keyword.arg not in {"api_key", "google_api_key"}
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assert node.id.lower() not in {"api_key", "google_api_key"}
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "GOOGLE_API_KEY"
            assert node.value != "api_key"
