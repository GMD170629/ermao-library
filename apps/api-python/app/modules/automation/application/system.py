"""Grant-scoped system management, with account authority rechecked per invocation."""

from typing import Literal, Protocol

from app.modules.automation.application.catalog import validate_page
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)

ConfigurationGroup = Literal["site", "email", "library", "organize", "opds"]


class AutomationSystemPort(Protocol):
    def import_queue(
        self, library_ids: frozenset[str], page: int, limit: int
    ) -> dict[str, object]: ...
    def queue_status(self) -> dict[str, object]: ...
    def logs(self, page: int, limit: int) -> dict[str, object]: ...
    def configuration(
        self, group: ConfigurationGroup, library_id: str | None
    ) -> dict[str, object]: ...
    def configure(
        self,
        group: ConfigurationGroup,
        library_id: str | None,
        values: dict[str, object],
        user_id: str,
    ) -> dict[str, object]: ...


class AutomationSystem:
    def __init__(self, port: AutomationSystemPort) -> None:
        self._port = port

    def _manager(self, access: EffectiveAccess, *, write: bool = False) -> None:
        access.require(Scope.SYSTEM_MANAGE if write else Scope.SYSTEM_READ)
        if not access.can_manage_system:
            raise AutomationAccessError("SYSTEM_MANAGER_REQUIRED")

    def import_queue(
        self, access: EffectiveAccess, page: int, limit: int
    ) -> dict[str, object]:
        self._manager(access)
        validate_page(page, limit)
        return self._port.import_queue(access.permissions.library_ids, page, limit)

    def queue_status(self, access: EffectiveAccess) -> dict[str, object]:
        self._manager(access)
        return self._port.queue_status()

    def logs(self, access: EffectiveAccess, page: int, limit: int) -> dict[str, object]:
        self._manager(access)
        validate_page(page, limit)
        return self._port.logs(page, limit)

    def configuration(
        self, access: EffectiveAccess, group: ConfigurationGroup, library_id: str | None
    ) -> dict[str, object]:
        self._manager(access)
        self._library(access, group, library_id)
        return self._port.configuration(group, library_id)

    def configure(
        self,
        access: EffectiveAccess,
        group: ConfigurationGroup,
        library_id: str | None,
        values: dict[str, object],
    ) -> dict[str, object]:
        self._manager(access, write=True)
        self._library(access, group, library_id)
        return self._port.configure(group, library_id, values, access.user_id)

    def _library(
        self, access: EffectiveAccess, group: ConfigurationGroup, library_id: str | None
    ) -> None:
        if group == "library":
            if library_id is None:
                raise AutomationAccessError("LIBRARY_REQUIRED")
            access.require(library_ids=frozenset({library_id}))
        elif library_id is not None:
            raise AutomationAccessError("INVALID_ARGUMENT")
