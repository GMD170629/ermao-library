"""System-event writer adapter used by import commands."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.system.public import PreparedSystemEvent
from app.services.system_events import write_prepared_system_events


class SqlAlchemyPreparedImportEventStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def write(self, events: tuple[PreparedSystemEvent, ...]) -> None:
        write_prepared_system_events(self._db, events)
