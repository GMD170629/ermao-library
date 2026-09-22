"""Resolve an owned automation operation across its four explicit job kinds."""

from dataclasses import dataclass

from app.contracts.automation_upload import UploadError
from app.modules.automation.application.deletions import AutomationDeletions
from app.modules.automation.application.file_moves import AutomationFileMoves
from app.modules.automation.application.uploads import AutomationUploads
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
    uploads: AutomationUploads
    deletions: AutomationDeletions

    def progress(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        if Scope.FILES_MODIFY in access.permissions.scopes:
            try:
                return self.deletions.progress(access, operation_id)
            except FileMoveError as error:
                # diagnostics-control-flow: no owned deletion with this ID means try upload progress; all other deletion errors propagate.
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if {
            Scope.FILES_UPLOAD,
            Scope.BOOKS_WRITE,
            Scope.FILES_MODIFY,
        } & access.permissions.scopes:
            try:
                return self.uploads.progress(access, operation_id)
            except UploadError as error:
                # diagnostics-control-flow: no owned upload with this ID means try move progress; all other upload errors propagate.
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if Scope.FILES_MODIFY in access.permissions.scopes:
            try:
                return self.moves.progress(access, operation_id)
            except FileMoveError as error:
                # diagnostics-control-flow: no owned move with this ID means try writeback progress; all other move errors propagate.
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if Scope.FILES_MODIFY in access.permissions.scopes:
            return self.writebacks.progress(access, operation_id)
        raise AutomationAccessError("RESOURCE_NOT_FOUND")

    def cancel(self, access: EffectiveAccess, operation_id: str) -> dict[str, object]:
        if Scope.FILES_MODIFY in access.permissions.scopes:
            try:
                return self.deletions.cancel(access, operation_id)
            except FileMoveError as error:
                # diagnostics-control-flow: no owned deletion with this ID means try upload cancellation; all other deletion errors propagate.
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if {
            Scope.FILES_UPLOAD,
            Scope.BOOKS_WRITE,
            Scope.FILES_MODIFY,
        } & access.permissions.scopes:
            try:
                return self.uploads.cancel(access, operation_id)
            except UploadError as error:
                # diagnostics-control-flow: no owned upload with this ID means try move cancellation; all other upload errors propagate.
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if Scope.FILES_MODIFY in access.permissions.scopes:
            try:
                return self.moves.cancel(access, operation_id)
            except FileMoveError as error:
                # diagnostics-control-flow: no owned move with this ID means try writeback cancellation; all other move errors propagate.
                if str(error) != "RESOURCE_NOT_FOUND":
                    raise
        if Scope.FILES_MODIFY in access.permissions.scopes:
            return self.writebacks.cancel(access, operation_id)
        raise AutomationAccessError("RESOURCE_NOT_FOUND")
