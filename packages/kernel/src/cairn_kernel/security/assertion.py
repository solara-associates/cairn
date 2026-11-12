import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from cairn_kernel.hex import ProjectId, TenantId


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def tenant_assertion_payload(
    *,
    tenant_id: TenantId,
    actor_id: str,
    expires_at: datetime,
    project_id: ProjectId | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "actor_id": actor_id,
        "exp": int(expires_at.astimezone(UTC).timestamp()),
        "tenant_id": tenant_id.value,
    }
    if project_id is not None:
        payload["project_id"] = project_id.value
    return payload


def sign_tenant_assertion(
    *,
    secret: bytes,
    tenant_id: TenantId,
    actor_id: str,
    expires_at: datetime,
    project_id: ProjectId | None = None,
) -> str:
    payload = json.dumps(
        tenant_assertion_payload(
            tenant_id=tenant_id,
            actor_id=actor_id,
            expires_at=expires_at,
            project_id=project_id,
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64url(payload)}.{_b64url(signature)}"
