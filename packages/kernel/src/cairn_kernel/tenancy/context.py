from dataclasses import dataclass

from cairn_kernel.hex import (
    CommandContext,
    MutationClass,
    OperationClass,
    ProjectId,
    TenantId,
)


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: TenantId
    project_id: ProjectId | None
    actor_id: str
    actor_roles: tuple[str, ...]
    correlation_id: str

    def to_command_context(
        self,
        operation_class: OperationClass,
        mutation_class: MutationClass,
        idempotency_key: str | None = None,
        source: str = "api",
    ) -> CommandContext:
        return CommandContext(
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            actor_id=self.actor_id,
            actor_roles=self.actor_roles,
            correlation_id=self.correlation_id,
            operation_class=operation_class,
            mutation_class=mutation_class,
            idempotency_key=idempotency_key,
            source=source,
        )
