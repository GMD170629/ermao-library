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
        assert "writebackTargets" not in columns
        assert "allowCrossLibrary" not in columns
        assert "token" not in columns
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
                    scopes=["system:read"],
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


def test_six_capabilities_reset_preserves_credentials_and_history(tmp_path):
    import json

    engine = create_sqlite_engine(tmp_path / "capabilities.sqlite")
    try:
        config = alembic_config_for_engine(engine)
        command.upgrade(config, "0027_automation_uploads")
        metadata = sa.MetaData()
        grants = sa.Table("AutomationGrant", metadata, autoload_with=engine)
        users = sa.Table("User", metadata, autoload_with=engine)
        settings = sa.Table("SystemSetting", metadata, autoload_with=engine)
        receipts = sa.Table("AutomationReceipt", metadata, autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                users.insert().values(
                    id="owner",
                    email="owner@example.com",
                    name="Owner",
                    passwordHash="test",
                    updatedAt=datetime.now(UTC),
                )
            )
            connection.execute(
                grants.insert().values(
                    id="retained",
                    userId="owner",
                    name="Retained",
                    tokenDigest="d" * 64,
                    tokenCiphertext="encrypted-test-value",
                    libraryScope="all",
                    libraryIds=[],
                    scopes=["library:read", "files:move", "metadata:writeback"],
                    writebackTargets=["embedded"],
                    allowCrossLibrary=True,
                    createdAt=42,
                    expiresAt=0,
                )
            )
            connection.execute(receipts.insert().values(grantId="retained", requestId="historical", tool="update_metadata", fingerprint="f"*64, createdAt=42, result={"updated":1}))
            connection.execute(
                settings.insert().values(
                    key="automation.mcp",
                    updatedAt=datetime.now(UTC),
                    value=json.dumps(
                        {
                            "enabled": True,
                            "enabled_scopes": ["library:read", "files:move"],
                            "public_base_url": "http://localhost/books",
                        }
                    ),
                )
            )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        current = sa.Table("AutomationGrant", sa.MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            grant = connection.execute(sa.select(current)).mappings().one()
            assert grant["id"] == "retained" and grant["name"] == "Retained"
            assert (
                grant["tokenDigest"] == "d" * 64
                and grant["tokenCiphertext"] == "encrypted-test-value"
            )
            assert grant["libraryScope"] == "all" and grant["libraryIds"] == []
            assert grant["createdAt"] == 42 and grant["expiresAt"] == 0
            assert grant["scopes"] == ["system:read"]
            assert connection.execute(sa.select(receipts.c.result)).scalar_one() == {"updated":1}
            assert "writebackTargets" not in grant and "allowCrossLibrary" not in grant
            value = json.loads(
                connection.execute(
                    sa.select(settings.c.value).where(
                        settings.c.key == "automation.mcp"
                    )
                ).scalar_one()
            )
            assert value == {
                "enabled": True,
                "enabled_scopes": ["system:read"],
                "public_base_url": "http://localhost/books",
            }
    finally:
        engine.dispose()
