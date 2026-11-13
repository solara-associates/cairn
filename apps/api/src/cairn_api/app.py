from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

ReadinessProbe = Callable[[], Mapping[str, bool]]


def _service_version() -> str:
    try:
        return version("cairn-api")
    except PackageNotFoundError:
        return "0.1.0"


def _run_probe(probe: ReadinessProbe) -> dict[str, bool]:
    try:
        return {str(name): bool(ok) for name, ok in probe().items()}
    except Exception:  # noqa: BLE001 - readiness must fail closed on any probe error
        return {"readiness_probe": False}


def create_app(*, readiness: ReadinessProbe | None = None) -> FastAPI:
    service_version = _service_version()
    probe = readiness or (dict)
    app = FastAPI(title="CAIRN API", version=service_version)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "api", "version": service_version}

    @app.get("/readyz", response_model=None)
    def readyz() -> dict[str, Any] | JSONResponse:
        checks = _run_probe(probe)
        if not all(checks.values()):
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": "api",
                    "version": service_version,
                    "checks": checks,
                },
            )
        return {
            "status": "ready",
            "service": "api",
            "version": service_version,
            "checks": checks,
        }

    return app


__all__ = ["ReadinessProbe", "create_app"]
