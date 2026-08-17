from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.current.registry import CurrentBase
from app.modules.system.infrastructure.persistence import SystemInstance


def test_system_instance_accepts_only_id_one_and_stores_marker() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    CurrentBase.metadata.create_all(
        engine, tables=[cast(Table, SystemInstance.__table__)]
    )
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)

    with Session(engine) as session, session.begin():
        session.add(
            SystemInstance(
                id=1,
                created_at=timestamp,
                identity_bootstrap_completed_at=timestamp,
            )
        )

    with Session(engine) as session:
        row = session.get(SystemInstance, 1)
        assert row is not None
        assert row.identity_bootstrap_completed_at == timestamp

    with Session(engine) as session, pytest.raises(IntegrityError), session.begin():
        session.add(SystemInstance(id=2, created_at=timestamp))
