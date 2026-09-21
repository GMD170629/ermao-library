"""Transport-neutral invocation port; no sessions or SDK objects escape adapters."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.application.writes import AutomationWrites
from app.modules.automation.domain.access import EffectiveAccess

CatalogInvocation = Callable[[AutomationCatalog, EffectiveAccess], dict[str, object]]


@dataclass(frozen=True)
class AutomationRequest:
    access: EffectiveAccess
    settings: AutomationServiceSettings


WriteInvocation = Callable[[AutomationWrites, EffectiveAccess], dict[str, object]]


class AutomationRuntime(Protocol):
    def authenticate(self, authorization: str | None) -> AutomationRequest: ...
    def invoke(
        self, access: EffectiveAccess, operation: CatalogInvocation
    ) -> dict[str, object]: ...

    def write(
        self, access: EffectiveAccess, operation: WriteInvocation
    ) -> dict[str, object]: ...
