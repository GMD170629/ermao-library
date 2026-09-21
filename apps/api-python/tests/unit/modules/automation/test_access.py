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
READ = GrantPermissions(frozenset({Scope.LIBRARY_READ}), frozenset({"L1"}))


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
        current.require(Scope.LIBRARY_READ, library_ids=frozenset({"L2"}))


@pytest.mark.parametrize(
    "scope", ALL_SCOPES - {Scope.LIBRARY_READ, Scope.SHELVES_WRITE}
)
def test_members_cannot_issue_high_risk_grants(scope):
    with pytest.raises(AutomationAccessError, match="SYSTEM_MANAGER_REQUIRED"):
        validate_permissions(replace(READ, scopes=READ.scopes | {scope}), MEMBER)


def test_scope_prerequisites_and_missing_suboptions_fail_closed():
    for scope in (Scope.FILES_MOVE, Scope.METADATA_WRITEBACK):
        with pytest.raises(AutomationAccessError, match="FILES_READ_REQUIRED"):
            validate_permissions(replace(READ, scopes=READ.scopes | {scope}), MANAGER)
    with pytest.raises(AutomationAccessError, match="WRITEBACK_TARGET_REQUIRED"):
        validate_permissions(
            replace(
                READ, scopes=READ.scopes | {Scope.FILES_READ, Scope.METADATA_WRITEBACK}
            ),
            MANAGER,
        )
    with pytest.raises(AutomationAccessError, match="FILES_MOVE_REQUIRED"):
        validate_permissions(replace(READ, allow_cross_library=True), MANAGER)


def test_cross_library_requires_both_libraries_and_explicit_option():
    permission = replace(
        READ, scopes=READ.scopes | {Scope.FILES_READ, Scope.FILES_MOVE}
    )
    access(permission).require_move("L1", "L1")
    with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
        access(replace(permission, allow_cross_library=True)).require_move("L1", "L2")
    permission = replace(permission, library_ids=MANAGER.library_ids)
    with pytest.raises(AutomationAccessError, match="CROSS_LIBRARY_NOT_ALLOWED"):
        access(permission).require_move("L1", "L2")
    access(replace(permission, allow_cross_library=True)).require_move("L1", "L2")


def test_sidecar_never_implies_embedded_or_system_metadata_write():
    permission = replace(
        READ,
        scopes=READ.scopes | {Scope.FILES_READ, Scope.METADATA_WRITEBACK},
        writeback_targets=frozenset({WritebackTarget.SIDECAR}),
    )
    validate_permissions(permission, MANAGER)
    current = access(permission)
    current.require_writeback(WritebackTarget.SIDECAR, "L1")
    with pytest.raises(AutomationAccessError, match="WRITEBACK_TARGET_NOT_ALLOWED"):
        current.require_writeback(WritebackTarget.EMBEDDED, "L1")
    with pytest.raises(AutomationAccessError, match="SCOPE_REQUIRED"):
        current.require_metadata(changes_tags=False, overrides_protection=True)


def test_metadata_cannot_bypass_tags_or_protection_scope():
    current = access(replace(READ, scopes=READ.scopes | {Scope.METADATA_WRITE}))
    current.require_metadata(changes_tags=False, overrides_protection=False)
    for tags, override in ((True, False), (False, True)):
        with pytest.raises(AutomationAccessError, match="SCOPE_REQUIRED"):
            current.require_metadata(changes_tags=tags, overrides_protection=override)


def test_downgrade_and_deployment_switch_remove_effective_access():
    permission = replace(READ, scopes=ALL_SCOPES)
    assert access(permission, MEMBER).permissions.scopes == frozenset(
        {Scope.LIBRARY_READ, Scope.SHELVES_WRITE}
    )
    current = access(permission, enabled=ALL_SCOPES - {Scope.FILES_READ})
    assert Scope.FILES_MOVE not in current.permissions.scopes
    assert Scope.METADATA_WRITEBACK not in current.permissions.scopes
    assert (
        access(actor=replace(MANAGER, library_ids=frozenset())).permissions.library_ids
        == frozenset()
    )
    with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
        access(actor=replace(MANAGER, active=False))


def test_discovery_filters_by_permission_and_actual_implementation():
    assert visible_tools(
        access(), frozenset({"get_context", "execute_file_operations", "future_tool"})
    ) == ("get_context",)
