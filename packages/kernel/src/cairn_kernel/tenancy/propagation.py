from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from cairn_kernel.errors import TenantScopeViolationError
from cairn_kernel.tenancy.context import TenantContext

_current_context: ContextVar[TenantContext | None] = ContextVar(
    "cairn_tenant_context", default=None
)


def _ensure_compatible(current: TenantContext | None, context: TenantContext) -> None:
    if current is not None and current != context:
        raise TenantScopeViolationError(
            "tenant context is already bound to another tenant"
        )


def set_tenant_context(context: TenantContext) -> None:
    _ensure_compatible(_current_context.get(), context)
    _current_context.set(context)


def current_tenant_context() -> TenantContext:
    context = _current_context.get()
    if context is None:
        raise TenantScopeViolationError("missing tenant context")
    return context


def has_tenant_context() -> bool:
    return _current_context.get() is not None


@contextmanager
def tenant_scope(context: TenantContext) -> Iterator[TenantContext]:
    _ensure_compatible(_current_context.get(), context)
    token = _current_context.set(context)
    try:
        yield context
    finally:
        _current_context.reset(token)
