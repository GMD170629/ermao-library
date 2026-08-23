"""Shared helpers for declarative models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import ColumnElement, func


def cuid() -> str:
    return f"py_{uuid4().hex}"


def db_timestamp() -> datetime:
    return datetime.now(UTC)


def timestamp_ms_server_default() -> ColumnElement[int]:
    """Return SQLite's current Unix time expressed in milliseconds."""

    return func.unixepoch() * 1000
