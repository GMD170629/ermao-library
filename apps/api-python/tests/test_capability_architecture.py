from pathlib import Path

APP_ROOT = Path(__file__).parents[1] / "app"
CAPABILITIES = (
    "download",
    "imports",
    "library",
    "media",
    "metadata",
    "organize",
    "reader",
    "shelf",
    "system",
)


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
    for root in (APP_ROOT / "modules").glob("*/infrastructure"):
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert ".commit(" not in source, path.name
            assert ".rollback(" not in source, path.name


def test_reader_v2_route_does_not_import_compat_privately() -> None:
    source = (APP_ROOT / "api" / "routes" / "reader_v2.py").read_text(encoding="utf-8")
    assert "from app.api.routes.compat" not in source
    assert "import compat" not in source


def test_reader_presentation_does_not_import_compat_or_infrastructure() -> None:
    presentation = APP_ROOT / "modules" / "reader" / "presentation"
    for path in presentation.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.api.routes.compat" not in source, path.name
        assert ".infrastructure" not in source, path.name


def test_compat_does_not_define_reader_progress_helpers() -> None:
    source = (APP_ROOT / "api" / "routes" / "compat.py").read_text(encoding="utf-8")
    forbidden = (
        "def _progress_navigation(",
        "def _progress_percent_with_navigation(",
        "def _raw_progress_percent(",
        "def _reader_v1_retired(",
        '@router.get("/reader/preferences"',
        '@router.get("/editions/{edition_id}/progress"',
    )
    for token in forbidden:
        assert token not in source, token


def test_system_and_metadata_presentation_do_not_import_compat_or_infrastructure() -> None:
    for capability in ("system", "metadata"):
        presentation = APP_ROOT / "modules" / capability / "presentation"
        if not presentation.exists():
            continue
        for path in presentation.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "from app.api.routes.compat" not in source, path.name
            assert ".infrastructure" not in source, path.name


def test_compat_no_longer_owns_system_settings_or_events_routes() -> None:
    source = (APP_ROOT / "api" / "routes" / "compat.py").read_text(encoding="utf-8")
    forbidden = (
        '@router.get("/app-config")',
        '@router.get("/system-settings")',
        '@router.get("/management/events")',
        '@router.get("/dashboard/system-status")',
        '@router.get("/metadata/providers")',
        '@router.get("/backups")\n',
        "def _public_system_settings(",
        "def _normalize_detail_tab_order(",
        '@router.get("/monitor-folders")',
        "def list_import_tasks(",
        "def get_import_task(",
        "def _import_task_view(",
        "def _monitor_directory_tree_node(",
    )
    for token in forbidden:
        assert token not in source, repr(token)


def test_imports_presentation_does_not_import_compat_or_infrastructure() -> None:
    presentation = APP_ROOT / "modules" / "imports" / "presentation"
    for path in presentation.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.api.routes.compat" not in source, path.name
        assert ".infrastructure" not in source, path.name
        assert "from app.worker" not in source, path.name
        assert "import app.worker" not in source, path.name
        assert "db.commit(" not in source, path.name
        assert "db.rollback(" not in source, path.name


def test_media_get_routes_do_not_commit_database_transactions() -> None:
    source = (
        APP_ROOT / "modules" / "media" / "presentation" / "http.py"
    ).read_text(encoding="utf-8")
    assert "db.commit(" not in source
    assert "db.rollback(" not in source


def test_media_presentation_does_not_import_compat_or_infrastructure() -> None:
    presentation = APP_ROOT / "modules" / "media" / "presentation"
    for path in presentation.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.api.routes.compat" not in source, path.name
        assert ".infrastructure" not in source, path.name


def test_compat_no_longer_owns_media_file_routes() -> None:
    source = (APP_ROOT / "api" / "routes" / "compat.py").read_text(encoding="utf-8")
    forbidden = (
        '@router.get("/files/{file_id}")',
        '@router.get("/volumes/{volume_id}/pages")',
        '@router.get("/metadata/cover-proxy")',
        "def _send_file(",
        "def _file_response(",
        "def _stored_path(",
    )
    for token in forbidden:
        assert token not in source, repr(token)


def test_library_presentation_does_not_import_compat_or_infrastructure() -> None:
    presentation = APP_ROOT / "modules" / "library" / "presentation"
    for path in presentation.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.api.routes.compat" not in source, path.name
        assert ".infrastructure" not in source, path.name


def test_compat_no_longer_owns_library_catalog_routes() -> None:
    source = (APP_ROOT / "api" / "routes" / "compat.py").read_text(encoding="utf-8")
    forbidden = (
        '@router.get("/dashboard/summary")',
        '@router.get("/works")',
        '@router.get("/library/facets")',
        '@router.get("/series")',
        '@router.get("/management/overview")',
        "def _work_view(",
        "def _cover_url(",
        "def _management_work_views(",
    )
    for token in forbidden:
        assert token not in source, repr(token)


def test_download_shelf_organize_presentation_do_not_import_compat_or_infrastructure() -> None:
    for capability in ("download", "shelf", "organize"):
        presentation = APP_ROOT / "modules" / capability / "presentation"
        assert presentation.exists(), capability
        for path in presentation.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "from app.api.routes.compat" not in source, path.name
            assert ".infrastructure" not in source, path.name


def test_compat_router_is_empty_after_capability_migration() -> None:
    source = (APP_ROOT / "api" / "routes" / "compat.py").read_text(encoding="utf-8")
    forbidden = (
        '@router.get(',
        '@router.post(',
        '@router.put(',
        '@router.patch(',
        '@router.delete(',
        '@router.head(',
        '@router.get("/sources")',
        '@router.get("/download-tasks")',
        '@router.get("/shelves")',
        '@router.get("/organize/policy")',
        '@router.post("/works/import")',
        '@router.get("/tracking/release-title-parser")',
        '@router.get("/backups/{backup_id}/download")',
    )
    for token in forbidden:
        assert token not in source, repr(token)


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


def test_migrated_capability_repositories_do_not_reflect_or_commit() -> None:
    paths = (
        APP_ROOT / "modules" / "backup" / "infrastructure" / "persistence.py",
        APP_ROOT / "modules" / "media" / "infrastructure" / "page_index.py",
        APP_ROOT / "modules" / "shelf" / "infrastructure" / "shelves.py",
        APP_ROOT / "modules" / "system" / "infrastructure" / "events.py",
        APP_ROOT / "modules" / "system" / "infrastructure" / "queue_runtime.py",
    )
    forbidden = (
        "autoload_with",
        "reflected_table",
        "legacy_persistence",
        ".commit(",
        ".rollback(",
        "sqlalchemy.text",
        "from sqlalchemy import text",
        "exec_driver_sql",
        ".cursor(",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.name}: {token}"


def test_runtime_models_use_typed_partial_index_predicates() -> None:
    for relative_path in (
        "models/library.py",
        "models/import_pipeline.py",
        "models/organize.py",
    ):
        source = (APP_ROOT / relative_path).read_text(encoding="utf-8")
        assert "from sqlalchemy import text" not in source, relative_path
        assert "sqlite_where=text(" not in source, relative_path


def test_sqlite_raw_access_is_confined_to_kernel_adapters() -> None:
    allowed = {
        APP_ROOT / "db" / "runner.py",
        APP_ROOT / "db" / "sqlite.py",
        APP_ROOT / "db" / "timestamp_triggers.py",
    }
    for path in (APP_ROOT / "db").glob("*.py"):
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for token in ("exec_driver_sql", ".cursor(", "sqlite3.connect("):
            assert token not in source, f"{path.name}: {token}"


def test_runtime_business_code_does_not_reflect_tables() -> None:
    for path in APP_ROOT.rglob("*.py"):
        if "db/alembic/versions" in path.as_posix():
            continue
        source = path.read_text(encoding="utf-8")
        assert "autoload_with=" not in source, path
        assert "reflected_table" not in source, path


def test_delivery_and_workers_do_not_deep_import_infrastructure() -> None:
    for root in (APP_ROOT / "api", APP_ROOT / "worker"):
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert ".infrastructure" not in source, path


def test_workers_do_not_own_database_transactions() -> None:
    for path in (APP_ROOT / "worker").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "db.commit(" not in source, path
        assert "db.rollback(" not in source, path


def test_compatibility_composition_adapter_has_been_removed() -> None:
    assert not (APP_ROOT / "bootstrap" / "compat_adapters.py").exists()


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


def test_import_legacy_persistence_and_schema_adapters_have_been_removed() -> None:
    infrastructure = APP_ROOT / "modules" / "imports" / "infrastructure"
    assert not (infrastructure / "legacy_persistence.py").exists()
    assert not (infrastructure / "schema.py").exists()

    roots = (
        APP_ROOT / "modules" / "imports",
        APP_ROOT / "modules" / "library",
        APP_ROOT / "worker",
        APP_ROOT / "bootstrap",
    )
    forbidden = (
        "legacy_persistence",
        "TABLE_MODELS",
        "model_for_table",
        "mapped_table(",
        "modules.imports.infrastructure.schema",
    )
    for root in roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in source, f"{path}: {token}"


def test_retired_source_http_persistence_has_been_removed() -> None:
    assert not (
        APP_ROOT
        / "modules"
        / "metadata"
        / "infrastructure"
        / "sources_http.py"
    ).exists()


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
