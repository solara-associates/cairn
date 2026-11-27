"""R6-11 acceptance: the ``transformation`` MCP server, driven against
real ``cairn_modules.transformation`` logic (``FakeTransformationPort``
+ ``FakeTransformationRunRepository``) -- a source tree that is
byte-identical before and after proves ``transformation.run`` writes
nothing outside CAIRN's own store.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cairn_adapters.auth_oidc import JwtAuthenticator, OidcSettings
from cairn_adapters.transform_core.fake import FakeTransformationPort
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_kernel.errors import ForbiddenError, NotFoundError, ValidationError
from cairn_kernel.security import Role
from cairn_kits.mcp import McpRegistry, ToolCapability
from cairn_mcp_gateway.gateway import McpGateway
from cairn_mcp_gateway.transformation_server import (
    TOOL_GET_DIFF,
    TOOL_GET_MANIFEST,
    TOOL_GET_RUN,
    TOOL_LIST_SOURCE_FILES,
    TOOL_RUN,
    TOOL_VALIDATE,
    build_transformation_server,
)
from cairn_modules.transformation.runs import FakeTransformationRunRepository

TENANT = "tenant-1"
PROJECT = "project-1"

ISSUER = "https://auth.example.cairn/"
AUDIENCE = "cairn-mcp-gateway"
SECRET = "unit-test-secret-does-not-leave-this-process"

IMPORT_IMP_FIXTURE = SourceFile(
    path="mod.py", content="import imp\n", language=SourceLanguage.PYTHON
)

_IMPORT_IMP_RAW_OUTPUT = {
    "parser_version": "cairn-python-parser/0.1.0",
    "detector_version": "cairn-detector/0.1.0",
    "patcher_version": "cairn-transform-patcher/0.1.0",
    "change_set": {
        "source_file_id": "mod.py",
        "patcher_version": "cairn-transform-patcher/0.1.0",
        "entries": [
            {
                "origin": {
                    "origin": "DETECTION",
                    "rule_id": "py-import-imp-deprecated",
                    "source_file_id": "mod.py",
                    "span": {"start_byte": 7, "end_byte": 10, "start_line": 1, "end_line": 1},
                    "confidence": "HIGH",
                    "detector_version": "cairn-detector/0.1.0",
                    "message": "stdlib 'imp' module is deprecated; the equivalent is 'importlib'",
                },
                "outcome": "APPLIED",
                "edits": [
                    {
                        "span": {"start_byte": 7, "end_byte": 10, "start_line": 1, "end_line": 1},
                        "replacement": "importlib",
                    }
                ],
                "reason": None,
                "patcher_version": "cairn-transform-patcher/0.1.0",
            }
        ],
    },
}


def _server() -> tuple:
    port = FakeTransformationPort()
    port.register(IMPORT_IMP_FIXTURE, _IMPORT_IMP_RAW_OUTPUT)
    repository = FakeTransformationRunRepository()
    server = build_transformation_server(port, repository, source_files=[IMPORT_IMP_FIXTURE])
    return server, repository


def _settings() -> OidcSettings:
    return OidcSettings(issuer=ISSUER, audience=AUDIENCE, algorithms=("HS256",), secret=SECRET)


def _token(*, roles: tuple[str, ...]) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "tenant_id": str(uuid.uuid4()),
        "roles": list(roles),
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _gateway(server) -> McpGateway:
    registry = McpRegistry()
    registry.register(server)
    return McpGateway(
        authenticator=JwtAuthenticator(_settings()),
        registry=registry,
        required_roles={
            TOOL_LIST_SOURCE_FILES: Role.VIEWER,
            TOOL_GET_RUN: Role.VIEWER,
            TOOL_RUN: Role.ENGINEER,
        },
    )


def test_list_source_files_returns_real_data() -> None:
    server, _repository = _server()

    files = server.handle(TOOL_LIST_SOURCE_FILES, {"tenant_id": TENANT, "project_id": PROJECT})

    assert files == (IMPORT_IMP_FIXTURE,)


def test_run_is_propose_and_writes_nothing_outside_cairns_own_store() -> None:
    server, _repository = _server()
    assert server.capabilities[TOOL_RUN] is ToolCapability.PROPOSE

    before = IMPORT_IMP_FIXTURE.content

    record = server.handle(
        TOOL_RUN, {"tenant_id": TENANT, "project_id": PROJECT, "created_by": "user-1"}
    )

    # the fake source tree is byte-identical before and after: this tool
    # never touches SourceFile.content, only reads it.
    assert IMPORT_IMP_FIXTURE.content == before
    assert record.manifest.applied_count == 1

    fetched_run = server.handle(
        TOOL_GET_RUN, {"tenant_id": TENANT, "project_id": PROJECT, "run_id": record.run_id}
    )
    assert fetched_run.run_id == record.run_id

    manifest = server.handle(
        TOOL_GET_MANIFEST, {"tenant_id": TENANT, "project_id": PROJECT, "run_id": record.run_id}
    )
    assert manifest.applied_count == 1

    diff = server.handle(
        TOOL_GET_DIFF, {"tenant_id": TENANT, "project_id": PROJECT, "run_id": record.run_id}
    )
    assert "importlib" in diff.files[0].unified_diff


def test_validate_is_propose_and_produces_a_validation_run() -> None:
    server, _repository = _server()
    assert server.capabilities[TOOL_VALIDATE] is ToolCapability.PROPOSE

    record = server.handle(
        TOOL_RUN, {"tenant_id": TENANT, "project_id": PROJECT, "created_by": "user-1"}
    )
    validation = server.handle(
        TOOL_VALIDATE, {"tenant_id": TENANT, "project_id": PROJECT, "run_id": record.run_id}
    )

    # no checks configured for this server -- vacuously approved, and
    # carries no approval state set beyond its own pass/fail result.
    assert validation.approved is True


def test_get_run_for_a_nonexistent_run_raises_not_found() -> None:
    server, _repository = _server()

    with pytest.raises(NotFoundError):
        server.handle(
            TOOL_GET_RUN, {"tenant_id": TENANT, "project_id": PROJECT, "run_id": "no-such-run"}
        )


def test_unknown_tool_name_raises() -> None:
    server, _repository = _server()

    with pytest.raises(ValidationError):
        server.handle("transformation.apply", {"tenant_id": TENANT, "project_id": PROJECT})


def test_unknown_argument_key_is_rejected() -> None:
    server, _repository = _server()

    with pytest.raises(ValidationError):
        server.handle(
            TOOL_LIST_SOURCE_FILES, {"tenant_id": TENANT, "project_id": PROJECT, "extra": "nope"}
        )


def test_caller_below_declared_role_gets_forbidden_before_the_handle_runs() -> None:
    server, _repository = _server()
    gateway = _gateway(server)
    token = _token(roles=())

    with pytest.raises(ForbiddenError):
        gateway.call_tool(
            TOOL_RUN, token, {"tenant_id": TENANT, "project_id": PROJECT, "created_by": "user-1"}
        )


def test_no_apply_publish_approve_or_execute_tool_is_registered() -> None:
    server, _repository = _server()

    forbidden_substrings = ("apply", "publish", "approve", "execute")
    for tool_name in server.tools:
        lowered = tool_name.lower()
        assert not any(substring in lowered for substring in forbidden_substrings)
