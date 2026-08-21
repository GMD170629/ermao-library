"""Stable contract for the target LibraryImportTask projection."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ImportTaskKind = Literal["SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_ASSET"]
ImportTaskState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
ImportTaskRole = Literal["PRIMARY", "TRACK", "PAGE", "SIDECAR", "SUPPLEMENT"]


class LibraryImportTaskContract(BaseModel):
    """Wire projection; no importer lease or legacy work identity is exposed."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    kind: ImportTaskKind
    library_id: str = Field(alias="libraryId")
    resource_id: str | None = Field(default=None, alias="resourceId")
    source_node_id: str | None = Field(default=None, alias="sourceNodeId")
    role: ImportTaskRole | None = None
    state: ImportTaskState
    error_summary: str | None = Field(default=None, alias="errorSummary")
    created_at: datetime | str = Field(alias="createdAt")
    started_at: datetime | str | None = Field(default=None, alias="startedAt")
    finished_at: datetime | str | None = Field(default=None, alias="finishedAt")

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(by_alias=True)


__all__ = [
    "ImportTaskKind",
    "ImportTaskRole",
    "ImportTaskState",
    "LibraryImportTaskContract",
]
