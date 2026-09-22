"""Automation uses the existing system event log and application transaction."""

from typing import Literal, Protocol

from app.modules.system.public import PreparedSystemEvent

AutomationAuditAction = Literal[
    "grant.updated",
    "grant.created",
    "grant.revoked",
    "grant.revealed",
    "settings.updated",
]


class AutomationAuditPort(Protocol):
    def prepare(
        self, action: AutomationAuditAction, actor_id: str, target_id: str
    ) -> PreparedSystemEvent: ...
    def write(self, event: PreparedSystemEvent) -> None: ...
