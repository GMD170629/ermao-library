"""Transport-neutral invocation port; no sessions or SDK objects escape adapters."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.modules.automation.application.catalog import AutomationCatalog
from app.modules.automation.application.deletions import AutomationDeletions
from app.modules.automation.application.file_moves import AutomationFileMoves
from app.modules.automation.application.operations import AutomationOperations
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.application.system import AutomationSystem
from app.modules.automation.application.uploads import AutomationUploads
from app.modules.automation.application.writebacks import AutomationWritebacks
from app.modules.automation.application.writes import AutomationWrites
from app.modules.automation.domain.access import EffectiveAccess

DeletionInvocation = Callable[[AutomationDeletions, EffectiveAccess], dict[str, object]]

SystemInvocation = Callable[[AutomationSystem, EffectiveAccess], dict[str, object]]

UploadInvocation = Callable[[AutomationUploads, EffectiveAccess], dict[str, object]]

WritebackInvocation = Callable[
    [AutomationWritebacks, EffectiveAccess], dict[str, object]
]
OperationInvocation = Callable[
    [AutomationOperations, EffectiveAccess], dict[str, object]
]

CatalogInvocation = Callable[[AutomationCatalog, EffectiveAccess], dict[str, object]]


@dataclass(frozen=True)
class AutomationRequest:
    access: EffectiveAccess
    settings: AutomationServiceSettings


FileInvocation = Callable[[AutomationFileMoves, EffectiveAccess], dict[str, object]]


WriteInvocation = Callable[[AutomationWrites, EffectiveAccess], dict[str, object]]


class AutomationRuntime(Protocol):
    def deletions(
        self, access: EffectiveAccess, operation: DeletionInvocation
    ) -> dict[str, object]: ...

    def system(
        self, access: EffectiveAccess, operation: SystemInvocation
    ) -> dict[str, object]: ...

    def authenticate(self, authorization: str | None) -> AutomationRequest: ...
    def invoke(
        self, access: EffectiveAccess, operation: CatalogInvocation
    ) -> dict[str, object]: ...

    def write(
        self, access: EffectiveAccess, operation: WriteInvocation
    ) -> dict[str, object]: ...

    def files(
        self, access: EffectiveAccess, operation: FileInvocation
    ) -> dict[str, object]: ...

    def writebacks(
        self, access: EffectiveAccess, operation: WritebackInvocation
    ) -> dict[str, object]: ...
    def uploads(
        self, access: EffectiveAccess, operation: UploadInvocation
    ) -> dict[str, object]: ...

    def operations(
        self, access: EffectiveAccess, operation: OperationInvocation
    ) -> dict[str, object]: ...
