from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from multiprocessing import Queue, get_context
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.bootstrap.current_first_admin import bootstrap_first_administrator
from app.db.current.bootstrap import initialize_current_database
from app.db.current.engine import create_current_engine
from app.modules.auth.application.first_admin import BootstrapFirstAdministrator
from app.modules.auth.domain.first_admin import (
    FirstAdministratorAlreadyInitialized,
    FirstAdministratorCommand,
)
from app.modules.auth.infrastructure.passwords import ScryptPasswordHasher
from app.modules.auth.infrastructure.persistence import (
    CurrentAuthIdentity,
    CurrentSession,
    CurrentUser,
    SqlAlchemyFirstAdministratorUnitOfWork,
)
from app.modules.system.infrastructure.persistence import SystemInstance


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class FixedIds:
    def __init__(self) -> None:
        self._values = iter(("user-1", "identity-1"))

    def new_id(self) -> str:
        return next(self._values)


class FailOnSecondFlushSession(Session):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._flush_count = 0

    def flush(self, objects: Sequence[object] | None = None) -> None:
        self._flush_count += 1
        if self._flush_count == 2:
            raise RuntimeError("injected persistence failure")
        super().flush(objects)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "current.sqlite3"
    initialize_current_database(path)
    return path


@pytest.fixture
def engine(database_path: Path):
    current_engine = create_current_engine(database_path)
    try:
        yield current_engine
    finally:
        current_engine.dispose()


def _use_case(
    engine, session_type: type[Session] = Session
) -> BootstrapFirstAdministrator:
    return BootstrapFirstAdministrator(
        unit_of_work_factory=lambda: SqlAlchemyFirstAdministratorUnitOfWork(
            session_type(engine)
        ),
        password_hasher=ScryptPasswordHasher(),
        clock=FixedClock(),
        id_generator=FixedIds(),
    )


def test_first_admin_atomically_writes_user_identity_and_marker_without_session(
    engine,
) -> None:
    result = _use_case(engine).execute(
        FirstAdministratorCommand("Admin@Example.com", "Administrator", "secret-pass")
    )

    with Session(engine) as session:
        user = session.get(CurrentUser, result.user_id)
        identity = session.get(CurrentAuthIdentity, result.identity_id)
        system = session.get(SystemInstance, 1)
        sessions = session.scalar(select(func.count()).select_from(CurrentSession))

    assert user is not None
    assert user.role == "admin"
    assert user.authz_version == 1
    assert identity is not None
    assert identity.provider == "PASSWORD"
    assert identity.subject == "admin@example.com"
    assert identity.password_hash is not None
    assert ":" in identity.password_hash
    assert system is not None
    assert system.identity_bootstrap_completed_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert sessions == 0


def test_existing_user_conflict_does_not_create_identity_or_change_marker(
    engine,
) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            CurrentUser(
                id="existing-user",
                display_name="Existing",
                role="admin",
                status="active",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

    with pytest.raises(FirstAdministratorAlreadyInitialized) as raised:
        _use_case(engine).execute(
            FirstAdministratorCommand("new@example.com", "New", "secret-pass")
        )

    assert raised.value.code == "FIRST_ADMINISTRATOR_ALREADY_INITIALIZED"
    with Session(engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(CurrentAuthIdentity)) == 0
        )
        system = session.get(SystemInstance, 1)
        assert system is not None
        assert system.identity_bootstrap_completed_at is None


def test_completed_marker_conflict_does_not_create_user(engine) -> None:
    completed_at = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        system = session.get(SystemInstance, 1)
        assert system is not None
        system.identity_bootstrap_completed_at = completed_at

    with pytest.raises(FirstAdministratorAlreadyInitialized) as raised:
        _use_case(engine).execute(
            FirstAdministratorCommand("new@example.com", "New", "secret-pass")
        )

    assert raised.value.code == "FIRST_ADMINISTRATOR_ALREADY_INITIALIZED"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CurrentUser)) == 0


def test_injected_second_flush_failure_rolls_back_user_identity_and_marker(
    engine,
) -> None:
    with pytest.raises(RuntimeError, match="injected persistence failure"):
        _use_case(engine, FailOnSecondFlushSession).execute(
            FirstAdministratorCommand("admin@example.com", "Admin", "secret-pass")
        )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CurrentUser)) == 0
        assert (
            session.scalar(select(func.count()).select_from(CurrentAuthIdentity)) == 0
        )
        system = session.get(SystemInstance, 1)
        assert system is not None
        assert system.identity_bootstrap_completed_at is None


def test_authz_version_is_positive(engine) -> None:
    with Session(engine) as session, pytest.raises(IntegrityError), session.begin():
        session.add(
            CurrentUser(
                id="invalid-user",
                authz_version=0,
                display_name="Invalid",
                role="admin",
                status="active",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )


def _run_concurrent_bootstrap(database_path: str, outcomes: Queue[str]) -> None:
    try:
        record = bootstrap_first_administrator(
            Path(database_path),
            FirstAdministratorCommand(
                "admin@example.com", "Administrator", "secret-pass"
            ),
        )
    except FirstAdministratorAlreadyInitialized as error:
        outcomes.put(f"conflict:{error.code}")
    except (IntegrityError, OperationalError, TimeoutError) as error:
        outcomes.put(f"error:{type(error).__name__}")
    else:
        outcomes.put(f"success:{record.user_id}")


def test_concurrent_cli_initialization_has_one_admin_and_one_stable_conflict(
    database_path: Path,
) -> None:
    context = get_context("spawn")
    outcomes: Queue[str] = context.Queue()
    processes = [
        context.Process(
            target=_run_concurrent_bootstrap,
            args=(str(database_path), outcomes),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    results = [outcomes.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    assert sorted(result.split(":", 1)[0] for result in results) == [
        "conflict",
        "success",
    ]
    assert all(
        result == "conflict:FIRST_ADMINISTRATOR_ALREADY_INITIALIZED"
        or result.startswith("success:")
        for result in results
    )
    verification_engine = create_current_engine(database_path)
    try:
        with Session(verification_engine) as session:
            assert session.scalar(select(func.count()).select_from(CurrentUser)) == 1
    finally:
        verification_engine.dispose()
