"""Declarative registry for the fresh current database schema."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class CurrentBase(DeclarativeBase):
    """Base class for ORM models owned by the current database lineage."""


# Keep this list explicit. Importing an arbitrary package tree would make the
# migration metadata depend on import order and would pull runtime services
# into the schema boundary. New current ORM model modules are added here as
# their capabilities land.
CURRENT_MODEL_MODULES: tuple[str, ...] = (
    "app.modules.system.infrastructure.persistence.models",
    "app.modules.auth.infrastructure.persistence.models",
    "app.modules.catalog.infrastructure.persistence.models",
)


def load_current_models() -> tuple[ModuleType, ...]:
    """Import the explicitly registered current ORM model modules.

    The function performs no engine creation or filesystem/network work. It
    is called by metadata consumers (Alembic and tests), never at module
    import time.
    """

    return tuple(import_module(module_name) for module_name in CURRENT_MODEL_MODULES)


def current_metadata() -> MetaData:
    """Return metadata after loading all explicitly registered models."""

    load_current_models()
    return CurrentBase.metadata
