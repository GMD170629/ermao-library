from pathlib import Path

APP_ROOT = Path(__file__).parents[1] / "app"
CAPABILITIES = ("system", "metadata", "library", "organize")


def test_capability_public_modules_do_not_import_infrastructure() -> None:
    for capability in CAPABILITIES:
        source = (APP_ROOT / "modules" / capability / "public.py").read_text(
            encoding="utf-8"
        )
        assert ".infrastructure" not in source, capability


def test_library_application_contracts_do_not_import_infrastructure() -> None:
    application_root = APP_ROOT / "modules" / "library" / "application"
    for module in application_root.glob("*.py"):
        assert ".infrastructure" not in module.read_text(encoding="utf-8"), module.name


def test_new_library_query_path_contains_no_textual_sql() -> None:
    paths = (
        APP_ROOT / "modules" / "library" / "infrastructure" / "queries.py",
        APP_ROOT / "modules" / "library" / "infrastructure" / "filter_query.py",
        APP_ROOT / "modules" / "library" / "infrastructure" / "work_list.py",
        APP_ROOT / "bootstrap" / "library.py",
    )
    forbidden = (
        "sqlalchemy.text",
        "from sqlalchemy import text",
        "exec_driver_sql",
        ".cursor(",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.name}: {token}"


def test_capability_repositories_do_not_own_transactions() -> None:
    for capability in ("download", "imports", "library", "organize"):
        root = APP_ROOT / "modules" / capability / "infrastructure"
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert ".commit(" not in source, path.name
            assert ".rollback(" not in source, path.name


def test_reader_v2_route_does_not_import_compat_privately() -> None:
    source = (APP_ROOT / "api" / "routes" / "reader_v2.py").read_text(encoding="utf-8")
    assert "from app.api.routes.compat" not in source
    assert "import compat" not in source


def test_media_page_index_contains_no_textual_sql() -> None:
    path = APP_ROOT / "modules" / "media" / "infrastructure" / "page_index.py"
    forbidden = (
        "sqlalchemy.text",
        "from sqlalchemy import text",
        "exec_driver_sql",
        ".cursor(",
    )
    source = path.read_text(encoding="utf-8")
    for token in forbidden:
        assert token not in source, f"{path.name}: {token}"


def test_queue_heartbeat_does_not_change_busy_timeout_at_runtime() -> None:
    source = (
        APP_ROOT
        / "modules"
        / "system"
        / "infrastructure"
        / "queue_runtime.py"
    ).read_text(encoding="utf-8")
    assert "PRAGMA" not in source
    assert "_set_busy_timeout" not in source


def test_compat_route_has_no_legacy_database_bridge() -> None:
    source = (APP_ROOT / "api" / "routes" / "compat.py").read_text(encoding="utf-8")
    assert ".infrastructure" not in source
    forbidden = (
        "def _row(",
        "def _rows(",
        "def _scalar(",
        "def _table_count(",
        "def _insert(",
        "def _update(",
        "def _update_where(",
        "def _delete(",
        "def _list_table_response(",
        "select_compat",
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
    )
    for token in forbidden:
        assert token not in source, token


def test_select_compat_adapter_has_been_removed() -> None:
    path = (
        APP_ROOT
        / "modules"
        / "library"
        / "infrastructure"
        / "select_compat.py"
    )
    assert not path.exists()


def test_remaining_compat_migration_adapters_use_typed_expressions() -> None:
    paths = (
        APP_ROOT / "modules" / "library" / "infrastructure" / "projections.py",
        APP_ROOT / "modules" / "library" / "infrastructure" / "storage.py",
        APP_ROOT
        / "modules"
        / "library"
        / "infrastructure"
        / "structural_operations.py",
        APP_ROOT / "modules" / "imports" / "infrastructure" / "import_http.py",
        APP_ROOT / "modules" / "download" / "infrastructure" / "download_http.py",
    )
    forbidden = (
        "sqlalchemy.text",
        "from sqlalchemy import text",
        "exec_driver_sql",
        ".cursor(",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.name}: {token}"
