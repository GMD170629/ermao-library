"""Pure resource-scoped completion and continue-reading rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class ResourceReadingState:
    resource_id: str
    sort_order: int
    percent: float = 0
    last_read_at: datetime | None = None
    visible: bool = True
    authorized: bool = True
    explicit_status: Literal["UNREAD", "FINISHED"] | None = None

    @property
    def available(self) -> bool:
        return self.visible and self.authorized

    @property
    def completed(self) -> bool:
        if self.explicit_status is not None:
            return self.explicit_status == "FINISHED"
        return self.percent >= 100

    @property
    def started(self) -> bool:
        if self.explicit_status is not None:
            return self.explicit_status == "FINISHED"
        return self.percent > 0


def completed_for_available_resources(resources: list[ResourceReadingState]) -> bool:
    """Return completion only when the non-empty authorized projection is done."""

    available = [resource for resource in resources if resource.available]
    return bool(available) and all(resource.completed for resource in available)


def reading_status_for_available_resources(
    resources: list[ResourceReadingState],
) -> Literal["UNREAD", "READING", "FINISHED"]:
    """Project independent status without altering the engine's real position."""

    if completed_for_available_resources(resources):
        return "FINISHED"
    if any(resource.available and resource.started for resource in resources):
        return "READING"
    return "UNREAD"


def choose_continue_resource_id(resources: list[ResourceReadingState]) -> str | None:
    """Choose the most recently read unfinished resource, if any."""

    available = [resource for resource in resources if resource.available]
    if not available:
        return None

    unfinished = [resource for resource in available if not resource.completed]
    candidates = unfinished or available
    with_history = [resource for resource in candidates if resource.last_read_at]
    if with_history:
        return max(
            with_history,
            key=lambda resource: (
                resource.last_read_at or datetime.min.replace(tzinfo=UTC),
                -resource.sort_order,
                resource.resource_id,
            ),
        ).resource_id
    return min(
        candidates, key=lambda resource: (resource.sort_order, resource.resource_id)
    ).resource_id
