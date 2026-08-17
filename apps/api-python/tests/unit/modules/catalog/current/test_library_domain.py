from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.catalog.domain.access import GrantLevel, LibraryGrant, grant_allows
from app.modules.catalog.domain.errors import (
    DuplicateIgnoreRule,
    FinalAdministratorRequired,
    InvalidIgnoreRule,
    LibraryConfigurationFrozen,
    RootOverlapConflict,
)
from app.modules.catalog.domain.ignore_rules import (
    IgnoreRule,
    IgnoreRuleKind,
    replace_rules,
)
from app.modules.catalog.domain.library import (
    Library,
    LibraryControlState,
    WritePolicy,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import (
    RootClaim,
    RootObservation,
    RootRelation,
    ensure_root_is_disjoint,
    root_relation,
)

NOW = datetime(2026, 8, 18, tzinfo=UTC)


def root(*components: str) -> RootObservation:
    path = "/".join(components)
    return RootObservation(path, path, components, f"dev:{path}", True)


def library() -> Library:
    return Library.create(
        library_id="library-1",
        name="  我的书库 ",
        root=root("srv", "books").registered_root,
        organization_mode=OrganizationMode.VOLUMES,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_WRITE,
        now=NOW,
    )


def test_root_overlap_uses_complete_components() -> None:
    candidate = root("srv", "bookshelf")
    existing = root("srv", "books")
    assert root_relation(candidate.claim, existing.claim) is RootRelation.DISJOINT
    with pytest.raises(RootOverlapConflict) as raised:
        ensure_root_is_disjoint(root("srv").claim, (existing.claim,))
    assert raised.value.code == "ROOT_PATH_OVERLAP"


def test_persisted_root_claim_needs_no_filesystem_observation_fields() -> None:
    claim = RootClaim(root_path_key="srv/books", components=("srv", "books"))
    assert root("srv", "books").claim == claim


def test_library_name_is_normalized_and_activation_freezes_layout() -> None:
    current = library()
    assert current.name == "我的书库"
    active_request = current.activate(now=NOW)
    assert active_request.control_state is LibraryControlState.ACTIVATING
    with pytest.raises(LibraryConfigurationFrozen):
        active_request.update_draft(
            organization_mode=OrganizationMode.FLAT,
            now=NOW,
        )


def test_ignore_rules_are_nfc_exact_and_path_is_root_relative() -> None:
    name_rule = IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="封面")
    path_rule = IgnoreRule.create(kind=IgnoreRuleKind.PATH, pattern="assets/covers")
    assert name_rule.pattern == "封面"
    assert path_rule.pattern == "assets/covers"
    assert name_rule.rule_key != path_rule.rule_key
    with pytest.raises(InvalidIgnoreRule):
        IgnoreRule.create(kind=IgnoreRuleKind.PATH, pattern="../outside")
    with pytest.raises(InvalidIgnoreRule):
        IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="a/b")
    with pytest.raises(DuplicateIgnoreRule):
        replace_rules((name_rule, name_rule))


@pytest.mark.parametrize(
    ("kind", "pattern"),
    (
        (IgnoreRuleKind.NAME, "x" * 256),
        (IgnoreRuleKind.PATH, "x" * 4097),
        (IgnoreRuleKind.NAME, "line\nbreak"),
        (IgnoreRuleKind.PATH, "C:/outside"),
    ),
)
def test_ignore_rule_value_object_enforces_direct_use_bounds(
    kind: IgnoreRuleKind, pattern: str
) -> None:
    with pytest.raises(InvalidIgnoreRule):
        IgnoreRule(kind=kind, pattern=pattern)


def test_ignore_rule_key_is_derived_and_replace_is_bounded() -> None:
    rule = IgnoreRule(kind=IgnoreRuleKind.NAME, pattern="cover.jpg")
    with pytest.raises(InvalidIgnoreRule):
        IgnoreRule(
            kind=IgnoreRuleKind.NAME,
            pattern="cover.jpg",
            rule_key="client-controlled",
        )
    with pytest.raises(InvalidIgnoreRule):
        replace_rules(tuple(rule for _ in range(201)))


def test_acl_hierarchy_and_last_admin_rule() -> None:
    read = LibraryGrant("user-1", "library-1", GrantLevel.READ, 1)
    admin = LibraryGrant("user-2", "library-1", GrantLevel.ADMIN, 2)
    assert grant_allows(admin, GrantLevel.READ)
    assert not grant_allows(read, GrantLevel.ADMIN)
    from app.modules.catalog.domain.access import ensure_not_last_administrator

    with pytest.raises(FinalAdministratorRequired):
        ensure_not_last_administrator(target=admin, active_administrator_count=1)
