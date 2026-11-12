.PHONY: bootstrap lint test conformance migrate migrate-down build clean

bootstrap:
	uv sync --all-packages
	cargo fetch
	pnpm install

lint:
	uv run ruff check .
	uv run lint-imports
	cargo fmt --all --check
	cargo clippy --workspace --all-targets -- -D warnings
	pnpm -r run lint

test:
	uv run pytest
	cargo test --workspace

conformance:
	uv run python -m cairn_kernel.conformance

migrate:
	uv run python -m cairn_adapters.persistence_postgres.migrator up

migrate-down:
	uv run python -m cairn_adapters.persistence_postgres.migrator down

build:
	cargo build --workspace

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	cargo clean
