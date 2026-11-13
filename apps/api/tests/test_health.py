from cairn_api import create_app
from fastapi.testclient import TestClient


def test_healthz_reports_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"
    assert body["version"]


def test_readyz_reports_ready_with_no_checks() -> None:
    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {}


def test_readyz_reports_dependency_checks() -> None:
    client = TestClient(create_app(readiness=lambda: {"database": True, "queue": True}))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": True, "queue": True}


def test_readyz_fails_when_a_check_fails() -> None:
    client = TestClient(create_app(readiness=lambda: {"database": False, "queue": True}))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"] == {"database": False, "queue": True}


def test_readyz_fails_when_probe_raises() -> None:
    def probe() -> dict[str, bool]:
        raise RuntimeError("database unavailable")

    client = TestClient(create_app(readiness=probe))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {"readiness_probe": False}
