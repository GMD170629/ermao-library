from datetime import UTC, datetime

import sqlalchemy as sa
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


def test_existing_grants_keep_fixed_scope_and_hash_through_migration(tmp_path):
    engine = create_sqlite_engine(tmp_path / "migration.sqlite")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0025_standard_writeback_plans")
        metadata = sa.MetaData()
        users = sa.Table("User", metadata, autoload_with=engine)
        grants = sa.Table("AutomationGrant", metadata, autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                users.insert().values(
                    id="owner",
                    email="owner@test.invalid",
                    name="Owner",
                    passwordHash="unused",
                    updatedAt=datetime.now(UTC),
                )
            )
            connection.execute(
                grants.insert().values(
                    id="legacy",
                    userId="owner",
                    name="Legacy",
                    tokenDigest="a" * 64,
                    scopes=["library:read"],
                    libraryIds=["fixed"],
                    writebackTargets=[],
                    allowCrossLibrary=False,
                    createdAt=1,
                    expiresAt=2000000000000,
                )
            )
        for _ in range(2):
            command.upgrade(config, "0026_automation_grant_secrets")
            current = sa.Table("AutomationGrant", sa.MetaData(), autoload_with=engine)
            with engine.connect() as connection:
                row = connection.execute(sa.select(current)).mappings().one()
                assert row["libraryScope"] == "selected"
                assert row["tokenCiphertext"] is None
                assert row["libraryIds"] == ["fixed"]
                assert row["tokenDigest"] == "a" * 64
            command.downgrade(config, "0025_standard_writeback_plans")
    finally:
        engine.dispose()
