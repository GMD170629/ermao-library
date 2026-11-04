"""Stable shelf application contracts."""

from app.modules.shelf.application.catalog import (
    CatalogShelf,
    CatalogShelfBookPage,
    CatalogShelfPage,
    CatalogShelfQueryPort,
    ListCatalogShelfBookIds,
    ListCatalogShelves,
    ListShelfNavigation,
    ShelfNavigationItem,
    ShelfNavigationQueryPort,
)
from app.modules.shelf.application.commands import (
    CreateShelf,
    CreateShelfCommand,
    DeleteShelf,
    DeleteShelfCommand,
    UpdateShelf,
    UpdateShelfCommand,
)
from app.modules.shelf.application.memberships import ShelfBookMembershipPort
from app.modules.shelf.domain.policies import ShelfKind

__all__ = [
    "CatalogShelf",
    "CatalogShelfBookPage",
    "CatalogShelfPage",
    "CatalogShelfQueryPort",
    "CreateShelf",
    "CreateShelfCommand",
    "DeleteShelf",
    "DeleteShelfCommand",
    "ListCatalogShelfBookIds",
    "ListCatalogShelves",
    "ListShelfNavigation",
    "ShelfBookMembershipPort",
    "ShelfKind",
    "ShelfNavigationItem",
    "ShelfNavigationQueryPort",
    "UpdateShelf",
    "UpdateShelfCommand",
]
