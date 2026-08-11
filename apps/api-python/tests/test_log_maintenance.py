import logging
from datetime import timedelta
from unittest.mock import Mock

from app.core.auth import hash_password, utcnow
from app.models.auth import Session as UserSession
from app.models.auth import User
from app.services.log_maintenance import SystemEventMaintenanceWorker
from sqlalchemy.exc import OperationalError


def test_system_maintenance_prunes_invalid_sessions_with_set_based_delete(
    db_session,
):
    active_user = User(
        email="active@example.com",
        name="Active",
        password_hash=hash_password("active-password"),
        role="admin",
    )
    disabled_user = User(
        email="disabled@example.com",
        name="Disabled",
        password_hash=hash_password("disabled-password"),
        role="member",
        status="disabled",
    )
    db_session.add_all([active_user, disabled_user])
    db_session.commit()
    now = utcnow()
    valid_session = UserSession(
        token_hash="valid-maintenance-session",
        user_id=active_user.id,
        expires_at=now + timedelta(days=10),
    )
    expired_session = UserSession(
        token_hash="expired-maintenance-session",
        user_id=active_user.id,
        expires_at=now - timedelta(minutes=1),
    )
    disabled_session = UserSession(
        token_hash="disabled-maintenance-session",
        user_id=disabled_user.id,
        expires_at=now + timedelta(days=10),
    )
    db_session.add_all([valid_session, expired_session, disabled_session])
    db_session.commit()
    valid_session_id = valid_session.id

    result = SystemEventMaintenanceWorker(lambda: db_session).run_once()

    db_session.expire_all()
    assert result["expiredSessionsDeleted"] == 2
    assert db_session.get(UserSession, valid_session_id) is not None
    assert (
        db_session.query(UserSession)
        .filter(UserSession.token_hash != "valid-maintenance-session")
        .count()
        == 0
    )


def test_system_maintenance_defers_database_busy_without_stack_trace(
    db_session,
    caplog,
):
    worker = SystemEventMaintenanceWorker(lambda: db_session, interval_seconds=1)
    worker.run_once = Mock(
        side_effect=OperationalError(
            "DELETE",
            {},
            Exception("database is locked"),
        )
    )
    worker._stop.wait = Mock(side_effect=[False, True])

    with caplog.at_level(logging.INFO):
        worker._run()

    assert "outcome=deferred reason=database_busy" in caplog.text
    assert "Traceback" not in caplog.text
