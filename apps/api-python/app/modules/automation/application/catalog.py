"""Bounded catalog operations using existing library and shelf public contracts."""

from dataclasses import asdict, dataclass

from app.core.authorization import AuthorizationContext
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.automation.domain.tools import QUERY_MAX_LIMIT
from app.modules.library.public import (
    CatalogBookFilter,
    CatalogLibraryQueryPort,
    CatalogQueryPort,
    ListCatalogBooks,
    ListCatalogFacets,
)
from app.modules.shelf.public import (
    CatalogShelfQueryPort,
    ListCatalogShelfBookIds,
    ListCatalogShelves,
)


def scoped_context(access: EffectiveAccess) -> AuthorizationContext:
    # Administration must never bypass the fixed grant's library scope.
    return AuthorizationContext(
        user_id=access.user_id,
        is_admin=False,
        can_manage_system=False,
        can_view_manual_imports=False,
        library_ids=tuple(sorted(access.permissions.library_ids)),
        authz_version=0,
    )


def validate_page(page: int, page_size: int) -> None:
    if (
        type(page) is not int
        or page < 1
        or type(page_size) is not int
        or not 1 <= page_size <= QUERY_MAX_LIMIT
    ):
        raise AutomationAccessError("INVALID_PAGINATION")


@dataclass(frozen=True)
class AutomationCatalog:
    libraries: CatalogLibraryQueryPort
    books: CatalogQueryPort
    shelves: CatalogShelfQueryPort

    def list_libraries(self, access: EffectiveAccess) -> dict[str, object]:
        access.require(Scope.LIBRARY_READ)
        return {
            "libraries": [
                asdict(item)
                for item in self.libraries.list_libraries(scoped_context(access))
            ]
        }

    def search_books(
        self,
        access: EffectiveAccess,
        filters: CatalogBookFilter,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        access.require(Scope.LIBRARY_READ)
        validate_page(page, page_size)
        return asdict(
            ListCatalogBooks(self.books).execute(
                context=scoped_context(access),
                filters=filters,
                page=page,
                page_size=page_size,
            )
        )

    def get_books(
        self, access: EffectiveAccess, book_ids: list[str]
    ) -> dict[str, object]:
        access.require(Scope.LIBRARY_READ)
        if (
            not 1 <= len(book_ids) <= QUERY_MAX_LIMIT
            or len(set(book_ids)) != len(book_ids)
            or any(not item.strip() for item in book_ids)
        ):
            raise AutomationAccessError("INVALID_BOOK_SELECTION")
        result = ListCatalogBooks(self.books).execute(
            context=scoped_context(access),
            filters=CatalogBookFilter(book_ids=tuple(book_ids)),
            page_size=QUERY_MAX_LIMIT,
        )
        if result.total != len(book_ids):
            raise AutomationAccessError("RESOURCE_NOT_FOUND")
        return asdict(result)

    def list_facets(
        self, access: EffectiveAccess, kind: str, search: str, page: int, page_size: int
    ) -> dict[str, object]:
        access.require(Scope.LIBRARY_READ)
        validate_page(page, page_size)
        return asdict(
            ListCatalogFacets(self.books).execute(
                context=scoped_context(access),
                kind=kind,
                search=search,
                page=page,
                page_size=page_size,
            )
        )

    def list_shelves(
        self, access: EffectiveAccess, page: int, page_size: int
    ) -> dict[str, object]:
        access.require(Scope.LIBRARY_READ)
        validate_page(page, page_size)
        return asdict(
            ListCatalogShelves(self.shelves).execute(
                context=scoped_context(access), page=page, page_size=page_size
            )
        )

    def get_shelf(
        self, access: EffectiveAccess, shelf_id: str, page: int, page_size: int
    ) -> dict[str, object]:
        access.require(Scope.LIBRARY_READ)
        validate_page(page, page_size)
        result = ListCatalogShelfBookIds(self.shelves).execute(
            context=scoped_context(access),
            shelf_id=shelf_id,
            page=page,
            page_size=page_size,
        )
        if result is None:
            raise AutomationAccessError("RESOURCE_NOT_FOUND")
        return asdict(result)
