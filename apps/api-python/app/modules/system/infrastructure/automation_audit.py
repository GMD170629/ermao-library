"""Redacted automation lifecycle events in the existing system audit store."""

from sqlalchemy.orm import Session

from app.modules.automation.public import AutomationAuditAction
from app.modules.system.domain.events import PreparedSystemEvent
from app.modules.system.infrastructure.events import (
    prepare_system_event,
    write_prepared_system_events,
)
from app.modules.system.infrastructure.settings import get_setting

_MESSAGES = {
    "grant.created": ("已创建自动化授权", "Automation grant created"),
    "grant.revoked": ("已撤销自动化授权", "Automation grant revoked"),
    "settings.updated": ("已更新 MCP 服务设置", "MCP service settings updated"),
}


class SqlAlchemyAutomationAudit:
    def __init__(self, db: Session) -> None:
        self._db = db

    def prepare(
        self, action: AutomationAuditAction, actor_id: str, target_id: str
    ) -> PreparedSystemEvent:
        language = get_setting(self._db, "language", "zh-CN")
        message = _MESSAGES[action][1 if language == "en-US" else 0]
        return prepare_system_event(
            source="automation",
            action=f"automation.{action}",
            message=message,
            actor_type="user",
            actor_id=actor_id,
            target_type="settings"
            if action == "settings.updated"
            else "automationGrant",
            target_id=target_id,
        )

    def write(self, event: PreparedSystemEvent) -> None:
        write_prepared_system_events(self._db, (event,))
