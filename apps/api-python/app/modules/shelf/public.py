"""Stable shelf application contracts."""

from app.modules.shelf.application.catalog import (
    CatalogShelf,
    CatalogShelfPage,
    CatalogShelfQueryPort,
    CatalogShelfBookPage,
    ListCatalogShelfBookIds,
    ListCatalogShelves,
)
from app.modules.shelf.application.commands import (
    CreateShelf,
    CreateShelfCommand,
    DeleteShelf,
    DeleteShelfCommand,
    UpdateShelf,
    UpdateShelfCommand,
)
from app.modules.shelf.domain.policies import ShelfKind

__all__ = [
    "CatalogShelf",
    "CatalogShelfPage",
    "CatalogShelfQueryPort",
    "CatalogShelfBookPage",
    "CreateShelf",
    "CreateShelfCommand",
    "DeleteShelf",
    "DeleteShelfCommand",
    "ListCatalogShelfBookIds",
    "ListCatalogShelves",
    "ShelfKind",
    "UpdateShelf",
    "UpdateShelfCommand",
]
