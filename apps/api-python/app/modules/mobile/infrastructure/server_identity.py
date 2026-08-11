"""SystemSetting-backed persistence for the stable mobile server identity."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.modules.mobile.domain.compatibility import SERVER_IDENTITY_SETTING_KEY


def new_server_identity() -> str:
    return f"server_{uuid4().hex}"


class SqlAlchemyServerIdentityReader:
    def __init__(self, db: Session) -> None:
        self._db = db

    def read_server_identity(self) -> str | None:
        value = self._db.scalar(
            select(SystemSetting.value).where(
                SystemSetting.key == SERVER_IDENTITY_SETTING_KEY
            )
        )
        return None if value is None else str(value)
