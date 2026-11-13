.PHONY: bootstrap lint test security-regression conformance migrate migrate-down build clean

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

security-regression:
	uv run pytest tests/integration/test_migration_safety.py tests/integration/test_tenant_security.py tests/integration/test_mutation_boundary.py tests/integration/test_ledger_verification.py tests/integration/test_migration_lock.py tests/integration/test_migrations.py tests/integration/test_audit.py packages/kernel/tests/test_canonical.py packages/kernel/tests/test_evidence.py packages/kernel/tests/test_conformance.py tests/conformance/test_rule_map.py apps/api/tests/test_auth_middleware.py -q

conformance:
	uv run python -m cairn_kernel.conformance

migrate:
	uv run python -m cairn_adapters.persistence_postgres.migrator up

migrate-down:
	uv run python -m cairn_adapters.persistence_postgres.migrator down --to "$${VERSION:?set VERSION}"

build:
	cargo build --workspace

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	cargo clean
