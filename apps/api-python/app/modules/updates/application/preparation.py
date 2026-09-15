"""System-manager authorization and version selection for update preparation."""

from __future__ import annotations

from typing import Protocol

from .models import (
    AvailableRelease,
    Environment,
    Package,
    PreparationState,
    UpdateCheck,
    UpdateError,
    version_parts,
)


class ReleaseSource(Protocol):
    def releases(self) -> list[tuple[str, list[Package]]]: ...


class PreparationPort(Protocol):
    def submit(self, package: Package) -> PreparationState: ...
    def status(self) -> PreparationState: ...
    def install(
        self, version: str, environment: Environment, current: str
    ) -> PreparationState: ...


class UpdatePreparation:
    def __init__(
        self,
        current: str,
        environment: Environment | None,
        source: ReleaseSource,
        worker: PreparationPort,
    ) -> None:
        self.current = current
        self.environment = environment
        self.source = source
        self.worker = worker

    @staticmethod
    def authorize(can_manage_system: bool) -> None:
        if not can_manage_system:
            raise UpdateError("SYSTEM_MANAGER_REQUIRED")

    def reason(self, version: str, packages: list[Package]) -> str | None:
        if self.environment is None:
            return "UNSUPPORTED_DEPLOYMENT"
        if version_parts(version) <= version_parts(self.current):
            return "NOT_NEWER"
        if not packages:
            return "PACKAGE_UNAVAILABLE"
        if not any(p.environment == self.environment for p in packages):
            return "INCOMPATIBLE_ENVIRONMENT"
        return None

    def check(self, can_manage_system: bool) -> UpdateCheck:
        self.authorize(can_manage_system)
        return UpdateCheck(
            current_version=self.current,
            supported=self.environment is not None,
            releases=[
                AvailableRelease(
                    version=version,
                    installable=self.reason(version, packages) is None,
                    reason=self.reason(version, packages),
                )
                for version, packages in self.source.releases()
            ],
        )

    def prepare(self, can_manage_system: bool, version: str) -> PreparationState:
        self.authorize(can_manage_system)
        for candidate, packages in self.source.releases():
            if candidate == version:
                reason = self.reason(candidate, packages)
                if reason:
                    raise UpdateError(reason)
                package = next(p for p in packages if p.environment == self.environment)
                return self.worker.submit(package)
        raise UpdateError("PACKAGE_UNAVAILABLE")

    def install(self, can_manage_system: bool, version: str) -> PreparationState:
        self.authorize(can_manage_system)
        if self.environment is None:
            raise UpdateError("UNSUPPORTED_DEPLOYMENT")
        if version_parts(version) <= version_parts(self.current):
            raise UpdateError("NOT_NEWER")
        return self.worker.install(version, self.environment, self.current)

    def status(self, can_manage_system: bool) -> PreparationState:
        self.authorize(can_manage_system)
        return (
            self.worker.status() if self.environment is not None else PreparationState()
        )
