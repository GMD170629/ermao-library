"""Map current catalog application DTOs to wire contracts."""

from __future__ import annotations

from datetime import datetime

from app.modules.catalog.application.dto import (
    LibraryAdminDetails,
    LibraryGrantView,
)
from app.modules.catalog.application.dto import (
    LibrarySummary as LibrarySummaryDTO,
)
from app.modules.catalog.domain.access import LibraryGrant as LibraryGrantDomain
from app.modules.catalog.domain.ignore_rules import IgnoreRule as IgnoreRuleDomain

from .schemas import (
    IgnoreRule as IgnoreRuleContract,
)
from .schemas import (
    LibraryAdminView,
    LibraryGrant,
    LibrarySummary,
)


def _timestamp(value: object) -> datetime:
    """Validate the application timestamp boundary before HTTP serialization."""

    if not isinstance(value, datetime):
        raise TypeError("library DTO timestamp must be a datetime")
    return value


def library_summary(dto: LibrarySummaryDTO) -> LibrarySummary:
    return LibrarySummary(
        id=dto.id,
        name=dto.name,
        organizationMode=dto.organization_mode.value,
        topologyVersion=dto.topology_version,
        pathComparison=dto.path_comparison.value,
        writePolicy=dto.write_policy.value,
        controlState=dto.control_state.value,
        observedHealth=dto.observed_health.value,
        configRevision=dto.config_revision,
        grantLevel=dto.grant_level.value,
        createdAt=_timestamp(dto.created_at),
        updatedAt=_timestamp(dto.updated_at),
    )


def library_admin(dto: LibraryAdminDetails) -> LibraryAdminView:
    return LibraryAdminView(
        **library_summary(dto).model_dump(),
        rootPath=dto.root_path,
    )


def library_grant(dto: LibraryGrantView | LibraryGrantDomain) -> LibraryGrant:
    return LibraryGrant(
        userId=dto.user_id,
        libraryId=dto.library_id,
        level=dto.level.value,
    )


def ignore_rule(rule: IgnoreRuleDomain) -> IgnoreRuleContract:
    return IgnoreRuleContract(
        kind=rule.kind.value,
        pattern=rule.pattern,
        enabled=rule.enabled,
    )


__all__ = ["ignore_rule", "library_admin", "library_grant", "library_summary"]
