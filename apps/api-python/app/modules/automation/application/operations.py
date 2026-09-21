"""Resolve an owned automation operation across its two explicit job kinds."""

from dataclasses import dataclass

from app.modules.automation.application.file_moves import AutomationFileMoves
from app.modules.automation.application.writebacks import AutomationWritebacks
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.library.public import FileMoveError


@dataclass(frozen=True)
class AutomationOperations:
    moves: AutomationFileMoves
    writebacks: AutomationWritebacks

    def progress(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        if Scope.FILES_MOVE in access.permissions.scopes:
            try:
                return self.moves.progress(access, operation_id)
            except FileMoveError as error:
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if Scope.METADATA_WRITEBACK in access.permissions.scopes:
            return self.writebacks.progress(access, operation_id)
        raise AutomationAccessError("RESOURCE_NOT_FOUND")

    def cancel(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        if Scope.FILES_MOVE in access.permissions.scopes:
            try:
                return self.moves.cancel(access, operation_id)
            except FileMoveError as error:
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if Scope.METADATA_WRITEBACK in access.permissions.scopes:
            return self.writebacks.cancel(access, operation_id)
        raise AutomationAccessError("RESOURCE_NOT_FOUND")
