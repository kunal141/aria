"""Physically isolated runtime composition for one authenticated tenant.

Every mutable store, artifact, and Work Ledger path is rooted below the
validated tenant directory.  The bundle does not mutate process environment or
the legacy default-writer singleton, so one tenant cannot redirect another.
"""
from __future__ import annotations

from pathlib import Path
from typing import Self

from aria.employee import EmployeeOrchestratorService, EmployeeRegistry, EmployeeRunStore
from aria.goals import AgentSupervisorService, AgentWorkforceService, GoalService, GoalStore
from aria.identity.models import validate_structural_id
from aria.ledger.writer import LedgerWriter
from aria.memory_v2.paths import aria_data_dir, ensure_confined, tenant_data_dir
from aria.memory_v2.store import DomainMemoryStore
from aria.memory_v2.workspace import WorkspaceStore
from aria.model_routing import ModelRoutingService, ModelRoutingStore
from aria.runtime_adapters import RuntimeAdapterService, RuntimeAdapterStore


class TenantRuntime:
    """Open the employee-workflow authorities for exactly one tenant."""

    def __init__(self, tenant_id: str, *, execution_mode: str = "offline_mock") -> None:
        self.tenant_id = validate_structural_id(tenant_id, field_name="tenant_id")
        self.execution_mode = execution_mode
        self.root = tenant_data_dir(self.tenant_id)
        expected_root = aria_data_dir().resolve() / "tenants" / self.tenant_id
        if self.root.resolve() != expected_root:
            raise TenantIsolationError("tenant runtime root is aliased outside its tenant scope")
        self.ledger_path = self._path("ledger", "work_ledger_v2.jsonl")
        self.writer = LedgerWriter(self.ledger_path)

        self.memory = DomainMemoryStore(
            self._path("memory", "store.sqlite"),
            writer=self.writer,
            execution_mode=execution_mode,
        )
        self.workspaces = WorkspaceStore(
            self._path("workspaces", "store.sqlite"),
            writer=self.writer,
            execution_mode=execution_mode,
            artifact_root=self._path("workspaces", "artifacts"),
        )
        self.goals = GoalStore(
            self._path("goals", "store.sqlite"),
            writer=self.writer,
            execution_mode=execution_mode,
        )
        self.routing = ModelRoutingStore(
            self._path("model_routing", "store.sqlite"),
            writer=self.writer,
            execution_mode=execution_mode,
        )
        self.adapters = RuntimeAdapterStore(
            self._path("runtime_adapters", "store.sqlite"),
            writer=self.writer,
            execution_mode=execution_mode,
        )
        self.employee_registry = EmployeeRegistry(
            self._path("employee_registry", "store.sqlite")
        )
        self.employee_runs = EmployeeRunStore(
            self._path("employee_runs", "store.sqlite"),
            writer=self.writer,
            execution_mode=execution_mode,
            routing_store=self.routing,
            adapter_store=self.adapters,
            goal_store=self.goals,
            workspace_store=self.workspaces,
            employee_registry=self.employee_registry,
        )

    def _path(self, *parts: str) -> Path:
        path = ensure_confined(self.root.joinpath(*parts))
        path.resolve().relative_to(self.root.resolve())
        return path

    @property
    def store_paths(self) -> tuple[Path, ...]:
        return (
            self.memory.db_path,
            self.workspaces.db_path,
            self.goals.db_path,
            self.routing.db_path,
            self.adapters.db_path,
            self.employee_runs.db_path,
            self.employee_registry.db_path,
        )

    def credential_vault(self, cipher):
        """Open this tenant's encrypted credential authority on demand."""
        from aria.credentials import CredentialVaultStore

        return CredentialVaultStore(
            self._path("credentials", "store.sqlite"),
            tenant_id=self.tenant_id,
            cipher=cipher,
            writer=self.writer,
        )

    def employee_service(self, *, actor: str) -> EmployeeOrchestratorService:
        return EmployeeOrchestratorService(
            self.employee_runs,
            goal_service=GoalService(
                self.goals,
                workspace_store=self.workspaces,
                execution_mode=self.execution_mode,
                actor=actor,
            ),
            goal_store=self.goals,
            workforce_service=AgentWorkforceService(
                self.goals,
                workspace_store=self.workspaces,
                execution_mode=self.execution_mode,
                actor=actor,
            ),
            supervisor_service=AgentSupervisorService(
                self.goals,
                workspace_store=self.workspaces,
                execution_mode=self.execution_mode,
                actor=actor,
            ),
            routing_service=ModelRoutingService(
                self.routing, execution_mode=self.execution_mode, actor=actor
            ),
            routing_store=self.routing,
            adapter_service=RuntimeAdapterService(
                self.adapters,
                workspace_store=self.workspaces,
                execution_mode=self.execution_mode,
                actor=actor,
            ),
            adapter_store=self.adapters,
            workspace_store=self.workspaces,
            actor=actor,
            execution_mode=self.execution_mode,
            employee_registry=self.employee_registry,
        )

    def close(self) -> None:
        for store in (
            self.employee_runs,
            self.employee_registry,
            self.adapters,
            self.routing,
            self.goals,
            self.workspaces,
            self.memory,
        ):
            store.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


class TenantIsolationError(ValueError):
    """A tenant runtime path was aliased into a different tenant scope."""


__all__ = ["TenantIsolationError", "TenantRuntime"]
