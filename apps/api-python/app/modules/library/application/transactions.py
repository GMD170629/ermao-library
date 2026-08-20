from __future__ import annotations

from sqlalchemy.orm import Session


def flush_library_changes(session: Session) -> None:
    """Publish pending ORM state inside the caller-owned library use case."""
    session.flush()


def commit_library_changes(session: Session) -> None:
    """Commit a completed library mutation."""
    session.commit()


def rollback_library_changes(session: Session) -> None:
    """Roll back a failed library mutation before compensation runs."""
    session.rollback()
