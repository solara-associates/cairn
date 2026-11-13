from cairn_worker import create_app
from fastapi.testclient import TestClient


def test_healthz_reports_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "worker"
    assert body["version"]


def test_readyz_reports_ready_with_no_checks() -> None:
    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readyz_fails_when_a_check_fails() -> None:
    client = TestClient(create_app(readiness=lambda: {"queue": False}))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
