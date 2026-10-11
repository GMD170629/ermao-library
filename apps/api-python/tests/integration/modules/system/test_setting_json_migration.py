from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.runtime.migration import MigrationContext
from sqlalchemy.orm import Session

from app.core.setting_values import decode_setting_value, encode_setting_value
from app.db.runner import alembic_config_for_engine
from app.db.sqlite import create_sqlite_engine
from app.models.settings import SystemSetting
from app.modules.backup.infrastructure.persistence import prepare_table_records
from app.modules.mobile.infrastructure.server_identity import (
    SqlAlchemyServerIdentityReader,
)
from app.modules.system.infrastructure.settings import get_setting, parse_setting_value


@pytest.mark.parametrize("interrupted", [False, True])
def test_upgrade_normalizes_literals_preserves_values_and_rejects_new_literals(
    tmp_path, interrupted
):
    engine = create_sqlite_engine(tmp_path / "settings.sqlite3")
    config = alembic_config_for_engine(engine)
    original = {
        "language": "zh-CN",
        "systemName": "书库\nwith \\\"quotes\\\"",
        "mobile.serverIdentity": "server_unchanged",
        "empty": "",
        "string": '"already JSON"',
        "numeric-string": '"123"',
        "boolean": "false",
        "number": "123",
        "null": "null",
        "array": '["中文",true,3]',
        "object": '{"nested":[1,2]}',
    }
    timestamp = 1_790_000_000_000
    try:
        command.upgrade(config, "0040_periodic_scan_admission")
        table = sa.Table("SystemSetting", sa.MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(sa.insert(table), [
                {"key": key, "value": value, "createdAt": timestamp, "updatedAt": timestamp}
                for key, value in original.items()
            ])

        if interrupted:
            def fail_after_normalizing(_connection, _clause, *_args):
                if isinstance(_clause, sa.sql.dml.Update):
                    raise RuntimeError("interrupted settings migration")  # noqa: TRY004 - injected migration interruption

            with engine.connect() as connection:
                config.attributes["connection"] = connection
                sa.event.listen(connection, "after_execute", fail_after_normalizing)
                try:
                    with pytest.raises(RuntimeError, match="interrupted settings migration"):
                        command.upgrade(config, "head")
                finally:
                    sa.event.remove(connection, "after_execute", fail_after_normalizing)
                    config.attributes.pop("connection")
            with engine.connect() as connection:
                assert MigrationContext.configure(connection).get_current_revision() == "0040_periodic_scan_admission"
                assert dict(connection.execute(sa.select(table.c.key, table.c.value)).all()) == original

        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = connection.execute(sa.select(table)).mappings().all()
            assert all(row["createdAt"] == timestamp and row["updatedAt"] == timestamp for row in rows)
            stored = {row["key"]: row["value"] for row in rows}
        for key, raw in original.items():
            expected = raw if key in {"language", "systemName", "mobile.serverIdentity", "empty"} else json.loads(raw)
            assert decode_setting_value(stored[key]) == expected
        with Session(engine) as db:
            assert get_setting(db, "language") == "zh-CN"
            assert SqlAlchemyServerIdentityReader(db).read_server_identity() == "server_unchanged"
        with engine.begin() as connection, pytest.raises(sa.exc.IntegrityError, match="SystemSetting_value_json"):
            connection.execute(sa.update(table).where(table.c.key == "language").values(value="en-US"))
        with engine.begin() as connection, pytest.raises(sa.exc.IntegrityError, match="SystemSetting_value_json"):
            connection.execute(sa.insert(table).values(key="invalid-new", value="literal", createdAt=timestamp, updatedAt=timestamp))
    finally:
        engine.dispose()


@pytest.mark.parametrize("value", ["zh-CN", "", "123", 123, False, None, [1, "中文"], {"a": True}])
def test_only_json_round_trips_through_settings(db_session, value):
    from app.modules.system.infrastructure.settings import upsert_setting

    upsert_setting(db_session, "format.test", value)
    assert db_session.get(SystemSetting, "format.test").value == encode_setting_value(value)
    assert get_setting(db_session, "format.test") == value


def test_runtime_rejects_literal_text_and_nonfinite_json():
    for raw in ("zh-CN", "", "NaN", "Infinity"):
        with pytest.raises(ValueError):
            parse_setting_value(raw)
    with pytest.raises(ValueError):
        encode_setting_value(float("nan"))


def test_old_backup_settings_are_converted_before_writing(db_session):
    records = prepare_table_records("SystemSetting", [
        {"key": "language", "value": "en-US"},
        {"key": "mobile.serverIdentity", "value": "server_backup_identity"},
        {"key": "empty", "value": ""},
        {"key": "object", "value": '{"enabled":false}'},
        {"key": "encoded", "value": '"123"'},
    ], legacy_setting_values=True)
    for record in records:
        db_session.add(SystemSetting(**record))
    db_session.flush()
    assert get_setting(db_session, "language") == "en-US"
    assert get_setting(db_session, "empty") == ""
    assert get_setting(db_session, "object") == {"enabled": False}
    assert get_setting(db_session, "encoded") == "123"
    assert SqlAlchemyServerIdentityReader(db_session).read_server_identity() == "server_backup_identity"


def test_setting_consumers_decode_once_without_literal_fallback(db_session, caplog):
    from app.modules.imports.infrastructure.readable_resource.global_ignore_patterns import (
        load_global_ignore_patterns,
    )
    from app.modules.system.infrastructure.settings import upsert_settings
    from app.services.download_executor import system_setting
    from app.services.import_preferences import (
        load_raw_import_preferences_projection,
        normalize_import_setting_value,
        prepare_import_preferences,
    )

    upsert_settings(db_session, {
        "import.allowedExtensions": [".epub", ".pdf"],
        "import.ignorePatterns": "false",
        "download.qbittorrent.url": "http://localhost:8080",
    })
    preferences = prepare_import_preferences(load_raw_import_preferences_projection(db_session))
    assert preferences.allowed_extensions == (".epub", ".pdf")
    assert preferences.ignore_patterns == "false"
    assert load_global_ignore_patterns(db_session) == "false"
    assert normalize_import_setting_value("import.ignorePatterns", "false") == "false"
    assert system_setting(db_session, "download.qbittorrent.url") == "http://localhost:8080"
    assert not caplog.records
