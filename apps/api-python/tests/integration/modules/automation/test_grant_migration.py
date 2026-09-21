from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.db.runner import alembic_config_for_engine, apply_schema
from app.db.sqlite import create_sqlite_engine
from app.models.auth import User
from app.modules.automation.infrastructure.models import AutomationGrantRow


def test_upgrade_creates_no_grants_and_is_reentrant(tmp_path):
    engine = create_sqlite_engine(tmp_path / "migration.sqlite")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0020_recheck_scan_gaps")
        with Session(engine) as db:
            db.add(
                User(
                    id="existing",
                    email="existing@test.invalid",
                    name="Existing",
                    password_hash="unused",
                )
            )
            db.commit()
        apply_schema(engine)
        apply_schema(engine)
        with Session(engine) as db:
            assert db.get(User, "existing") is not None
            assert list(db.scalars(select(AutomationGrantRow))) == []
        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("AutomationGrant")
        }
        assert columns["writebackTargets"]["default"] == "'[]'"
        assert columns["allowCrossLibrary"]["default"] == "'0'"
        assert "token" not in columns
        command.downgrade(config, "0020_recheck_scan_gaps")
        assert "AutomationGrant" not in inspect(engine).get_table_names()
        with Session(engine) as db:
            assert db.get(User, "existing") is not None
    finally:
        engine.dispose()


def test_fresh_database_includes_grants(tmp_path):
    engine = create_sqlite_engine(tmp_path / "fresh.sqlite")
    try:
        apply_schema(engine)
        assert "AutomationGrant" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
