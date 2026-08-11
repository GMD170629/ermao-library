"""Stable shelf application contracts."""

from app.modules.shelf.application.catalog import (
    CatalogShelf,
    CatalogShelfPage,
    CatalogShelfQueryPort,
    CatalogShelfWorkPage,
    ListCatalogShelfWorkIds,
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
    "CatalogShelfWorkPage",
    "CreateShelf",
    "CreateShelfCommand",
    "DeleteShelf",
    "DeleteShelfCommand",
    "ListCatalogShelfWorkIds",
    "ListCatalogShelves",
    "ShelfKind",
    "UpdateShelf",
    "UpdateShelfCommand",
]
