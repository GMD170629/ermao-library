"""Assemble preparation next to the existing API-owned background lifecycles."""

from __future__ import annotations

from app.core.config import Settings
from app.modules.updates.application.preparation import UpdatePreparation
from app.modules.updates.infrastructure.environment import (
    fixed_environment,
    fixed_protocol,
)
from app.modules.updates.infrastructure.official_source import (
    OfficialHTTP,
    OfficialReleases,
)
from app.modules.updates.infrastructure.preparation_worker import PreparationWorker


class UpdateRuntime:
    def __init__(self, settings: Settings) -> None:
        transport = OfficialHTTP()
        environment = fixed_environment(settings.resolved_storage_root)
        protocol = fixed_protocol()
        self.worker = PreparationWorker(
            settings.resolved_storage_root, transport, environment
        )
        self.use_cases = UpdatePreparation(
            settings.app_version,
            environment,
            OfficialReleases(transport, protocol),
            self.worker,
            protocol,
        )

    def close(self) -> None:
        self.worker.close()
