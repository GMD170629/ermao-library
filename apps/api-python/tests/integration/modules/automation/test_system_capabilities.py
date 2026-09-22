"""System queries and management respect account authority and redact secrets."""

from dataclasses import replace

import pytest

from app.bootstrap.automation import build_automation_system
from app.modules.automation.domain.access import AutomationAccessError, Scope
from app.modules.automation.presentation.system import EmailSettings, LibrarySettings
from tests.integration.modules.automation.test_metadata_patches import setup_metadata


def test_manager_read_write_scopes_and_redacted_email(db_session):
    access = replace(setup_metadata(db_session), can_manage_system=True)
    service = build_automation_system(db_session)
    assert "queues" in service.queue_status(access)
    assert service.import_queue(access, 1, 20)["tasks"] == []
    with pytest.raises(AutomationAccessError, match="SCOPE_REQUIRED"):
        service.configure(access, "site", None, {"language": "en-US"})
    access = replace(
        access,
        permissions=replace(
            access.permissions, scopes=access.permissions.scopes | {Scope.SYSTEM_MANAGE}
        ),
    )
    assert service.configure(access, "site", None, {"language": "en-US"}) == {
        "language": "en-US"
    }
    result = service.configure(
        access,
        "email",
        None,
        {
            "smtp": {
                "host": "smtp.example.com",
                "password": "never-return-this",
                "fromEmail": "sender@example.com",
            }
        },
    )
    assert "never-return-this" not in str(result)
    assert "never-return-this" not in str(service.logs(access, 1, 50))
    with pytest.raises(AutomationAccessError):
        service.configure(access, "site", None, {"automation.mcp": True})
    with pytest.raises(AutomationAccessError):
        service.configuration(access, "library", "secret-library")
    with pytest.raises(ValueError):
        EmailSettings.model_validate({"smtp": {"shell": "invalid"}})
    with pytest.raises(ValueError):
        LibrarySettings.model_validate({"userRole": "ADMIN"})


def test_member_cannot_read_global_logs_queues_or_configuration(db_session):
    access = setup_metadata(db_session)
    service = build_automation_system(db_session)
    for operation in (
        lambda: service.logs(access, 1, 20),
        lambda: service.queue_status(access),
        lambda: service.configuration(access, "site", None),
        lambda: service.import_queue(access, 1, 20),
    ):
        with pytest.raises(AutomationAccessError, match="SYSTEM_MANAGER_REQUIRED"):
            operation()
