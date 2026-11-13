FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev --package cairn-worker

EXPOSE 8081

CMD ["uv", "run", "--no-sync", "uvicorn", "cairn_worker.main:app", "--host", "0.0.0.0", "--port", "8081"]
