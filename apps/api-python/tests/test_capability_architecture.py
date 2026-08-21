from pathlib import Path

APP_ROOT = Path(__file__).parents[1] / "app"
CAPABILITIES = (
    "auth",
    "download",
    "imports",
    "kindle",
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
            if path.name == "uow.py":
                continue
            source = path.read_text(encoding="utf-8")
            assert ".commit(" not in source, path.name
            assert ".rollback(" not in source, path.name


def test_legacy_route_package_has_been_removed() -> None:
    assert not (APP_ROOT / "api" / "routes").exists()


def test_api_router_registers_capability_presentations_only() -> None:
    source = (APP_ROOT / "api" / "router.py").read_text(encoding="utf-8")
    assert "app.api.routes" not in source
    for capability in ("auth", "kindle", "reader", "system"):
        assert f"app.modules.{capability}.presentation" in source


def test_capability_presentations_do_not_import_legacy_routes_or_infrastructure() -> None:
    for capability in CAPABILITIES:
        presentation = APP_ROOT / "modules" / capability / "presentation"
        if not presentation.exists():
            continue
        for path in presentation.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "app.api.routes" not in source, path
            assert f"app.modules.{capability}.infrastructure" not in source, path


def test_migrated_route_schemas_are_capability_owned() -> None:
    retired = (
        "auth.py",
        "auth_responses.py",
        "user_responses.py",
        "kindle_responses.py",
        "reader_v2.py",
    )
    for filename in retired:
        assert not (APP_ROOT / "schemas" / filename).exists(), filename


def test_reader_presentation_does_not_import_compat_or_infrastructure() -> None:
    presentation = APP_ROOT / "modules" / "reader" / "presentation"
    for path in presentation.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.api.routes.compat" not in source, path.name
        assert ".infrastructure" not in source, path.name


def test_system_and_metadata_presentation_do_not_import_compat_or_infrastructure() -> (
    None
):
    for capability in ("system", "metadata"):
        presentation = APP_ROOT / "modules" / capability / "presentation"
        if not presentation.exists():
            continue
        for path in presentation.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "from app.api.routes.compat" not in source, path.name
            assert ".infrastructure" not in source, path.name


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
    source = (APP_ROOT / "modules" / "media" / "presentation" / "http.py").read_text(
        encoding="utf-8"
    )
    assert "db.commit(" not in source
    assert "db.rollback(" not in source


def test_media_presentation_does_not_import_compat_or_infrastructure() -> None:
    presentation = APP_ROOT / "modules" / "media" / "presentation"
    for path in presentation.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.api.routes.compat" not in source, path.name
        assert ".infrastructure" not in source, path.name


def test_library_presentation_does_not_import_compat_or_infrastructure() -> None:
    presentation = APP_ROOT / "modules" / "library" / "presentation"
    for path in presentation.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app.api.routes.compat" not in source, path.name
        assert ".infrastructure" not in source, path.name


def test_download_shelf_organize_presentation_do_not_import_compat_or_infrastructure() -> (
    None
):
    for capability in ("download", "shelf", "organize"):
        presentation = APP_ROOT / "modules" / capability / "presentation"
        assert presentation.exists(), capability
        for path in presentation.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "from app.api.routes.compat" not in source, path.name
            assert ".infrastructure" not in source, path.name


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
        APP_ROOT / "modules" / "system" / "infrastructure" / "queue_runtime.py"
    ).read_text(encoding="utf-8")
    assert "PRAGMA" not in source
    assert "_set_busy_timeout" not in source


def test_select_compat_adapter_has_been_removed() -> None:
    path = APP_ROOT / "modules" / "library" / "infrastructure" / "select_compat.py"
    assert not path.exists()


def test_import_legacy_persistence_and_schema_adapters_have_been_removed() -> None:
    infrastructure = APP_ROOT / "modules" / "imports" / "infrastructure"
    assert not (infrastructure / "legacy_persistence.py").exists()
    assert not (infrastructure / "schema.py").exists()
    assert not (infrastructure / "import_records.py").exists()

    roots = (
        APP_ROOT / "modules" / "imports",
        APP_ROOT / "modules" / "library",
        APP_ROOT / "worker",
        APP_ROOT / "bootstrap",
    )
    forbidden = (
        "legacy_persistence",
        "import_records",
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


def test_persistent_import_worker_does_not_touch_session_orm_or_field_dicts() -> None:
    path = APP_ROOT / "worker" / "persistent_import_queue.py"
    source = path.read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "from sqlalchemy",
        "orm.Session",
        "dict[str, Any]",
        "task_repository",
        "library_repository",
        "import_records",
        ".infrastructure",
    )
    for token in forbidden:
        assert token not in source, f"{path.name}: {token}"


def test_worker_importer_compatibility_shim_has_been_removed() -> None:
    path = APP_ROOT / "worker" / "importer.py"
    assert not path.exists()


def test_import_application_has_no_framework_or_concrete_adapter_dependencies() -> None:
    application = APP_ROOT / "modules" / "imports" / "application"
    forbidden = (
        "from sqlalchemy",
        "import sqlalchemy",
        "from fastapi",
        "import fastapi",
        "from PIL",
        "app.core.config",
        "app.services",
        ".infrastructure",
    )
    for path in application.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.name}: {token}"


def test_import_legacy_query_and_task_compatibility_are_removed() -> None:
    infrastructure = APP_ROOT / "modules" / "imports" / "infrastructure"
    assert not (infrastructure / "library_query_gateway.py").exists()

    query_port = (
        APP_ROOT / "modules" / "imports" / "application" / "query_ports.py"
    ).read_text(encoding="utf-8")
    assert "__getattr__" not in query_port
    assert "Callable[..., Any]" not in query_port

    dto = (APP_ROOT / "modules" / "imports" / "application" / "dto.py").read_text(
        encoding="utf-8"
    )
    for token in ("to_legacy_dict", "def __getitem__", "def get("):
        assert token not in dto

    bootstrap = (APP_ROOT / "bootstrap" / "imports.py").read_text(encoding="utf-8")
    assert "_coerce_import_task" not in bootstrap
    assert "ImportTaskDTO | dict" not in bootstrap


def test_persistent_import_worker_does_not_reexport_commands() -> None:
    source = (
        APP_ROOT / "worker" / "persistent_import_queue.py"
    ).read_text(encoding="utf-8")
    for command in (
        "claim_next_import_task",
        "enqueue_import_task",
        "fail_claimed_import_task",
        "process_import_task",
        "recover_stale_import_tasks",
        "stage_import_task",
    ):
        assert command not in source


def test_retired_source_http_persistence_has_been_removed() -> None:
    assert not (
        APP_ROOT / "modules" / "metadata" / "infrastructure" / "sources_http.py"
    ).exists()


def test_remaining_compat_migration_adapters_use_typed_expressions() -> None:
    paths = (
        APP_ROOT / "modules" / "library" / "infrastructure" / "projections.py",
        APP_ROOT / "modules" / "library" / "infrastructure" / "storage.py",
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


def test_readable_resource_overlay_migration_is_immutable_and_self_contained() -> None:
    path = (
        APP_ROOT
        / "db"
        / "alembic"
        / "versions"
        / "0003_readable_resource_overlay_schema.py"
    )
    source = path.read_text(encoding="utf-8")
    forbidden = (
        "app.models",
        "app.db.base",
        "Base.metadata",
        "create_all",
        "sqlalchemy.text",
        "from sqlalchemy import text",
        "importlib",
        "__import__",
    )
    for token in forbidden:
        assert token not in source, token


def test_readable_resource_orm_check_constraints_use_typed_expressions() -> None:
    import ast

    paths = (
        APP_ROOT
        / "modules"
        / "library"
        / "infrastructure"
        / "readable_resource_schema.py",
        APP_ROOT
        / "modules"
        / "imports"
        / "infrastructure"
        / "readable_resource_import_schema.py",
    )

    def _is_check_constraint_call(node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == "CheckConstraint"
        if isinstance(func, ast.Attribute):
            return func.attr == "CheckConstraint"
        return False

    def _is_string_expression(node: ast.AST | None) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return True
        if isinstance(node, ast.JoinedStr):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return _is_string_expression(node.left) or _is_string_expression(
                node.right
            )
        return False

    check_count = 0
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_check_constraint_call(node):
                continue
            check_count += 1
            expression: ast.AST | None = node.args[0] if node.args else None
            for keyword in node.keywords:
                if keyword.arg == "sqltext":
                    expression = keyword.value
            assert not _is_string_expression(expression), (
                f"{path.name}: CheckConstraint must use typed SQLAlchemy "
                f"expressions, not string SQL (line {node.lineno})"
            )
    assert check_count == 16


def test_adr0018_target_modules_forbid_legacy_queue_concepts() -> None:
    """Target overlay must not reintroduce Run/candidate/lease/WorkItem bridge."""

    forbidden = (
        "LibraryImportRun",
        "ResourceCandidate",
        "AssetCandidate",
        "ClaimedWork",
        "activeImportRunId",
        "publishedRunId",
        "ownerImportRunId",
        "leaseOwner",
        "leaseExpiresAt",
        "fence_claim",
        "ImportWorkItem",
        "DurableSidecarWriteback",
        "ReimportSourceNode",
        "RetryReadableResourceImport",
        "worker_id",
        "run_id",
        "UNHANDLED_ERROR",
    )
    # heartbeat as a method name is also banned in target queue code
    heartbeat_paths_extra = ("heartbeat",)

    roots = (
        APP_ROOT / "bootstrap" / "readable_resource_pipeline.py",
        APP_ROOT / "modules" / "imports" / "application" / "readable_resource",
        APP_ROOT / "modules" / "imports" / "infrastructure" / "readable_resource",
        APP_ROOT
        / "modules"
        / "imports"
        / "infrastructure"
        / "readable_resource_import_schema.py",
        APP_ROOT
        / "modules"
        / "library"
        / "infrastructure"
        / "readable_resource_schema.py",
        APP_ROOT
        / "db"
        / "alembic"
        / "versions"
        / "0003_readable_resource_overlay_schema.py",
    )
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        else:
            files.extend(root.rglob("*.py"))

    for path in files:
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path}: forbidden {token}"
        if path.name in {"work_queue.py", "worker.py", "ports.py"}:
            for token in heartbeat_paths_extra:
                assert token not in source, f"{path}: forbidden {token}"


def test_library_and_imports_do_not_deep_import_peer_private_modules() -> None:
    # library modules (except bootstrap) must not contain:
    #   app.modules.imports.application
    #   app.modules.imports.infrastructure
    #   app.modules.imports.domain
    # except allow app.modules.imports.public
    # imports modules must not contain:
    #   app.modules.library.application
    #   app.modules.library.infrastructure
    # except allow app.modules.library.public and app.modules.library.domain
    # Exclude TYPE_CHECKING-only is hard; simply forbid the import strings in library/**/*.py
    # Note: library infrastructure must NOT import imports.*
    #
    # Relationship string names like "LibraryImportRun" are allowed without imports.
    # Pre-ADR0018 legacy adapters retain deep library imports; exclude them only.
    legacy_imports_deep_library = {
        APP_ROOT
        / "modules"
        / "imports"
        / "infrastructure"
        / "library_queries.py",
        APP_ROOT
        / "modules"
        / "imports"
        / "infrastructure"
        / "orchestration_services.py",
    }

    library_forbidden = (
        "app.modules.imports.application",
        "app.modules.imports.infrastructure",
        "app.modules.imports.domain",
    )
    library_root = APP_ROOT / "modules" / "library"
    for path in library_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in library_forbidden:
            assert token not in source, f"{path}: {token}"
        if "infrastructure" in path.relative_to(library_root).parts:
            assert "app.modules.imports" not in source, path

    imports_forbidden = (
        "app.modules.library.application",
        "app.modules.library.infrastructure",
    )
    imports_root = APP_ROOT / "modules" / "imports"
    for path in imports_root.rglob("*.py"):
        if path in legacy_imports_deep_library:
            continue
        source = path.read_text(encoding="utf-8")
        for token in imports_forbidden:
            assert token not in source, f"{path}: {token}"
