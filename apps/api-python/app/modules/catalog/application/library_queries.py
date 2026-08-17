"""Actor-scoped current Library queries."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.catalog.application.dto import (
    IgnoreRulesResult,
    LibraryAdminDetails,
    LibraryGrantPage,
    LibraryPage,
    LibrarySummary,
    admin_details_from_library,
    summary_from_library,
)
from app.modules.catalog.application.ports import (
    LibraryGrantPageQuery,
    LibraryPageQuery,
    LibraryQueryRepository,
)
from app.modules.catalog.domain.access import GrantLevel
from app.modules.catalog.domain.errors import InvalidPageLimit, LibraryNotFound


@dataclass(frozen=True, slots=True)
class ListLibraries:
    query_port: LibraryQueryRepository

    def execute(self, query: LibraryPageQuery) -> LibraryPage:
        if query.limit < 1 or query.limit > 100:
            raise InvalidPageLimit()
        return self.query_port.list_visible(query)


@dataclass(frozen=True, slots=True)
class GetLibrary:
    query_port: LibraryQueryRepository

    def execute(self, *, actor_id: str, library_id: str) -> LibrarySummary:
        visible = self.query_port.get_visible(actor_id, library_id)
        if visible is None:
            raise LibraryNotFound()
        return summary_from_library(visible.library, visible.grant.level)


@dataclass(frozen=True, slots=True)
class GetAdminLibrary:
    query_port: LibraryQueryRepository

    def execute(self, *, actor_id: str, library_id: str) -> LibraryAdminDetails:
        visible = self.query_port.get_manageable(actor_id, library_id)
        if visible is None or visible.grant.level is not GrantLevel.ADMIN:
            raise LibraryNotFound()
        return admin_details_from_library(visible.library, visible.grant.level)


@dataclass(frozen=True, slots=True)
class ListLibraryGrants:
    query_port: LibraryQueryRepository

    def execute(self, query: LibraryGrantPageQuery) -> LibraryGrantPage:
        if query.limit < 1 or query.limit > 100:
            raise InvalidPageLimit()
        visible = self.query_port.get_manageable(query.actor_id, query.library_id)
        if visible is None or visible.grant.level is not GrantLevel.ADMIN:
            raise LibraryNotFound()
        return self.query_port.list_grants(query)


@dataclass(frozen=True, slots=True)
class GetLibraryIgnoreRules:
    query_port: LibraryQueryRepository

    def execute(self, *, actor_id: str, library_id: str) -> IgnoreRulesResult:
        result = self.query_port.get_ignore_rules(actor_id, library_id)
        if result is None:
            raise LibraryNotFound()
        return result
