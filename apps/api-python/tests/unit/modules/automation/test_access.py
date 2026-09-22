from dataclasses import replace

import pytest

from app.modules.automation.domain.access import (
    ALL_SCOPES,
    AutomationAccessError,
    AutomationActor,
    GrantPermissions,
    Scope,
    WritebackTarget,
    effective_access,
    validate_permissions,
)
from app.modules.automation.domain.tools import visible_tools

MANAGER = AutomationActor("manager", True, True, frozenset({"L1", "L2"}))
MEMBER = replace(MANAGER, can_manage_system=False)
READ = GrantPermissions(frozenset({Scope.SYSTEM_READ}), frozenset({"L1"}))


def access(permissions=READ, actor=MANAGER, enabled=ALL_SCOPES):
    return effective_access(
        grant_id="grant",
        user_id="manager",
        permissions=permissions,
        actor=actor,
        enabled_scopes=enabled,
    )


def test_admin_grant_stays_bounded_when_new_library_is_added():
    current = access(actor=replace(MANAGER, library_ids=frozenset({"L1", "L2", "L3"})))
    assert current.permissions.library_ids == frozenset({"L1"})
    with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
        current.require(Scope.SYSTEM_READ, library_ids=frozenset({"L2"}))


@pytest.mark.parametrize(
    "scope", ALL_SCOPES - {Scope.SYSTEM_READ, Scope.SHELVES_WRITE}
)
def test_members_cannot_issue_high_risk_grants(scope):
    with pytest.raises(AutomationAccessError, match="SYSTEM_MANAGER_REQUIRED"):
        validate_permissions(replace(READ, scopes=READ.scopes | {scope}), MEMBER)


def test_six_capabilities_have_no_legacy_subpermissions():
    assert {scope.value for scope in ALL_SCOPES} == {"system:read", "system:manage", "books:write", "shelves:write", "files:upload", "files:modify"}
    for scope in ALL_SCOPES:
        validate_permissions(replace(READ, scopes=READ.scopes | {scope}), MANAGER)


def test_file_modification_requires_both_libraries_and_covers_both_formats():
    permission = replace(READ, scopes=READ.scopes | {Scope.FILES_MODIFY})
    current = access(permission)
    current.require_move("L1", "L1")
    with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
        current.require_move("L1", "L2")
    access(replace(permission, library_ids=MANAGER.library_ids)).require_move("L1", "L2")
    for target in WritebackTarget:
        current.require_writeback(target, "L1")
    with pytest.raises(AutomationAccessError, match="SCOPE_REQUIRED"):
        current.require_metadata(changes_tags=False, overrides_protection=True)


def test_book_metadata_covers_tags_and_protection_but_not_files():
    current = access(replace(READ, scopes=READ.scopes | {Scope.BOOKS_WRITE}))
    current.require_metadata(changes_tags=True, overrides_protection=True)
    with pytest.raises(AutomationAccessError, match="SCOPE_REQUIRED"):
        current.require_writeback(WritebackTarget.EMBEDDED, "L1")


def test_current_role_and_service_remove_effective_permissions():
    permission = replace(READ, scopes=ALL_SCOPES)
    assert access(permission, actor=MEMBER).permissions.scopes == {Scope.SYSTEM_READ, Scope.SHELVES_WRITE}
    assert Scope.FILES_MODIFY not in access(permission, enabled=ALL_SCOPES - {Scope.FILES_MODIFY}).permissions.scopes
    with pytest.raises(AutomationAccessError):
        access(permission, actor=replace(MANAGER, active=False))


def test_discovery_requires_implemented_and_granted_tool():
    assert visible_tools(access(), frozenset({"get_context", "execute_file_operations", "future_tool"})) == ("get_context",)
    uploads = frozenset({"begin_upload", "upload_chunk", "complete_upload"})
    for scope in (Scope.BOOKS_WRITE, Scope.FILES_UPLOAD, Scope.FILES_MODIFY):
        assert set(visible_tools(access(replace(READ, scopes=READ.scopes | {scope})), uploads)) == uploads
    assert not visible_tools(access(), uploads)
