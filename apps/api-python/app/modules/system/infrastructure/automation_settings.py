"""Automation configuration in the existing SystemSetting store."""

from dataclasses import asdict

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.modules.automation.public import (
    AUTOMATION_SETTINGS_KEY,
    AutomationServiceSettings,
    normalize_service_settings,
)
from app.modules.system.infrastructure.settings import (
    get_setting,
    prepare_settings_write,
    write_prepared_settings,
)

_SETTINGS = TypeAdapter(AutomationServiceSettings)


class SqlAlchemyAutomationSettings:
    def __init__(self, db: Session) -> None:
        self._db = db

    def load(self) -> AutomationServiceSettings:
        return normalize_service_settings(
            _SETTINGS.validate_python(
                get_setting(self._db, AUTOMATION_SETTINGS_KEY, {})
            )
        )

    def save(self, settings: AutomationServiceSettings) -> None:
        payload = asdict(settings)
        payload["enabled_scopes"] = sorted(settings.enabled_scopes)
        prepared = prepare_settings_write({AUTOMATION_SETTINGS_KEY: payload})
        write_prepared_settings(self._db, prepared)
