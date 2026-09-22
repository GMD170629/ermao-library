"""Automation library configuration through the existing library command."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.imports.application.library_commands import (
    PreparedLibraryUpdate,
    UpdateLibrary,
    prepare_library_update_values,
)
from app.modules.imports.infrastructure.library_queries import (
    get_library,
    get_library_by_root_path,
    library_has_topology,
)
from app.modules.imports.infrastructure.library_root import resolve_library_root_path
from app.modules.imports.infrastructure.library_write import SqlAlchemyLibraryWriteStore
from app.services.system_events import prepare_system_event


class AutomationLibraryConfiguration:
    def __init__(self, db: Session) -> None:
        self.db = db

    def read(self, library_id: str) -> dict[str, object]:
        library = get_library(self.db, library_id)
        if library is None:
            raise ValueError("LIBRARY_NOT_FOUND")
        fields = {
            "id",
            "name",
            "rootPath",
            "organizationMode",
            "enabled",
            "ignorePatterns",
            "ignoreHidden",
            "minFileSizeBytes",
            "description",
            "allowEmptyLibraryCleanup",
        }
        return {key: value for key, value in library.items() if key in fields}

    def write(
        self, library_id: str, values: dict[str, object], user_id: str
    ) -> dict[str, object]:
        existing = self.read(library_id)
        if any(
            key in values and values[key] != existing.get(key)
            for key in ("rootPath", "organizationMode")
        ) and library_has_topology(self.db, library_id):
            raise ValueError("LIBRARY_TOPOLOGY_LOCKED")
        if "rootPath" in values:
            root = str(resolve_library_root_path(values["rootPath"]))
            if (
                get_library_by_root_path(self.db, root, exclude_id=library_id)
                is not None
            ):
                raise ValueError("ROOT_CONFLICT")
            values = {**values, "rootPath": root}
        event = prepare_system_event(
            source="automation",
            action="automation.library.updated",
            actor_type="user",
            actor_id=user_id,
            target_type="library",
            target_id=library_id,
            message="书库配置已更新 / Library configuration updated",
        )
        UpdateLibrary(SqlAlchemyLibraryWriteStore(self.db), self.db).execute(
            PreparedLibraryUpdate(
                library_id,
                prepare_library_update_values(
                    {**values, "updatedAt": datetime.now(UTC)}
                ),
                event,
            )
        )
        return self.read(library_id)
