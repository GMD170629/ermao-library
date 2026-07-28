from __future__ import annotations

from datetime import datetime

from pydantic import Field, RootModel

from app.contracts.http import HttpContractModel


class EventMetadataValue(
    RootModel[
        str
        | int
        | float
        | bool
        | None
        | list["EventMetadataValue"]
        | dict[str, "EventMetadataValue"]
    ]
):
    """A recursively typed JSON value stored with a system event."""


EventMetadataValue.model_rebuild()


class SystemEvent(HttpContractModel):
    id: str
    level: str
    source: str
    actor_type: str = Field(alias="actorType")
    actor_id: str | None = Field(alias="actorId")
    action: str
    target_type: str | None = Field(alias="targetType")
    target_id: str | None = Field(alias="targetId")
    message: str
    metadata: dict[str, EventMetadataValue]
    created_at: datetime | None = Field(alias="createdAt")
