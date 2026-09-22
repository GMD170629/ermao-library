"""Wire standard-file writeback into the existing metadata worker queue."""

from typing import Any

from sqlalchemy.orm import Session

from app.bootstrap.automation import (
    build_automation_authorizer,
    build_automation_catalog,
)
from app.core.config import get_settings
from app.core.time import now_timestamp_ms
from app.modules.automation.application.writeback_access import (
    RecheckStandardWriteAccess,
)
from app.modules.library.infrastructure.metadata_file_targets import (
    SqlAlchemyMetadataFileTargets,
)
from app.modules.library.infrastructure.source_file_access import (
    open_library_directory,
    open_library_file,
)
from app.modules.library.infrastructure.standard_writeback_index import (
    SqlAlchemyStandardWriteIndex,
)
from app.modules.metadata.application.execute_standard_writeback import (
    ExecuteStandardWrite,
)
from app.modules.metadata.application.standard_writeback_maintenance import (
    MaintainStandardBackups,
)
from app.modules.metadata.infrastructure.standard_publication import (
    StandardMetadataPublication,
)
from app.modules.metadata.infrastructure.standard_writeback_store import (
    SqlAlchemyStandardWritePlans,
)
from app.modules.system.infrastructure.automation_settings import (
    SqlAlchemyAutomationSettings,
)


def process_standard_writeback(
    db: Session, target: dict[str, Any], owner_id: str
) -> None:
    payload = target["payload"]
    operation_id = payload.get("standard_operation_id")
    ordinal = payload.get("ordinal")
    if not isinstance(operation_id, str) or type(ordinal) is not int or ordinal < 0:
        raise ValueError("INVALID_STANDARD_WRITE_TARGET")
    ExecuteStandardWrite(
        SqlAlchemyStandardWritePlans(
            db, queue_capacity=get_settings().metadata_opf_queue_max_pending
        ),
        StandardMetadataPublication(open_library_directory, open_library_file),
        RecheckStandardWriteAccess(
            build_automation_authorizer(db),
            SqlAlchemyAutomationSettings(db),
            build_automation_catalog(db),
            SqlAlchemyMetadataFileTargets(db),
        ),
        SqlAlchemyStandardWriteIndex(db).record,
        db,
        now_timestamp_ms,
    ).execute(operation_id, ordinal, owner_id)


def maintain_standard_writeback(db: Session) -> None:
    MaintainStandardBackups(
        SqlAlchemyStandardWritePlans(
            db, queue_capacity=get_settings().metadata_opf_queue_max_pending
        ),
        StandardMetadataPublication(open_library_directory, open_library_file),
        db,
        now_timestamp_ms,
    ).execute()
