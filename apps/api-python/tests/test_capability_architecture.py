from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

APP_ROOT = Path(__file__).parents[1] / "app"
API_ROOT = APP_ROOT.parent
CAPABILITIES = (
    "auth",
    "backup",
    "download",
    "imports",
    "kindle",
    "library",
    "media",
    "metadata",
    "organize",
    "opds",
    "publications",
    "reader",
    "shelf",
    "system",
)


# Exact pre-P1-03/P1-04 debt.  Each capability migration removes its entries;
# the generic collectors below make newly introduced dependency edges fail.
_CROSS_CAPABILITY_PRIVATE_IMPORT_DEBT: set[tuple[str, str]] = set()

_APPLICATION_FRAMEWORK_IMPORT_DEBT: set[tuple[str, str]] = set()

_BOOTSTRAP_BEHAVIOR_DEBT = {
    "bootstrap/auth.py": set(),
    "bootstrap/system.py": set(),
    "bootstrap/opds.py": set(),
}

_PRESENTATION_DATABASE_CALL_DEBT = Counter({})


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    return tuple(imported)


def test_cross_capability_imports_use_public_or_contract_surfaces() -> None:
    violations: set[tuple[str, str]] = set()
    modules_root = APP_ROOT / "modules"
    for capability_root in modules_root.iterdir():
        if not capability_root.is_dir():
            continue
        capability = capability_root.name
        for path in capability_root.rglob("*.py"):
            for imported in _imported_modules(path):
                parts = imported.split(".")
                if (
                    len(parts) >= 4
                    and parts[:2] == ["app", "modules"]
                    and parts[2] != capability
                    and parts[3] != "public"
                ):
                    violations.add((path.relative_to(APP_ROOT).as_posix(), imported))
    assert violations == _CROSS_CAPABILITY_PRIVATE_IMPORT_DEBT


def test_application_modules_do_not_import_frameworks_or_orm() -> None:
    violations: set[tuple[str, str]] = set()
    for path in (APP_ROOT / "modules").glob("*/application/**/*.py"):
        for imported in _imported_modules(path):
            if imported.startswith(("fastapi", "sqlalchemy")):
                violations.add((path.relative_to(APP_ROOT).as_posix(), imported))
    assert violations == _APPLICATION_FRAMEWORK_IMPORT_DEBT


def test_target_bootstraps_only_define_composition_symbols() -> None:
    for relative_path, expected_debt in _BOOTSTRAP_BEHAVIOR_DEBT.items():
        path = APP_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        actual = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not node.name.startswith(("build_", "create_", "register_", "start_"))
        }
        assert actual == expected_debt, relative_path


def test_target_presentations_do_not_execute_database_operations() -> None:
    actual: Counter[tuple[str, str]] = Counter()
    targets = (
        "modules/auth/presentation/users.py",
        "modules/library/presentation/views.py",
        "modules/system/presentation/http.py",
    )
    database_methods = {"execute", "get", "scalar", "scalars", "commit", "rollback"}
    for relative_path in targets:
        path = APP_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "db"
                and node.func.attr in database_methods
            ):
                actual[(relative_path, f"db.{node.func.attr}")] += 1
    assert actual == _PRESENTATION_DATABASE_CALL_DEBT


def test_capability_public_modules_do_not_import_infrastructure() -> None:
    for capability in CAPABILITIES:
        source = (APP_ROOT / "modules" / capability / "public.py").read_text(
            encoding="utf-8"
        )
        assert ".infrastructure" not in source, capability


def test_capability_public_modules_do_not_import_presentation() -> None:
    for capability in CAPABILITIES:
        public_module = APP_ROOT / "modules" / capability / "public.py"
        if not public_module.exists():
            continue
        source = public_module.read_text(encoding="utf-8")
        assert ".presentation" not in source, capability


def test_library_application_contracts_do_not_import_infrastructure() -> None:
    application_root = APP_ROOT / "modules" / "library" / "application"
    for module in application_root.glob("*.py"):
        assert ".infrastructure" not in module.read_text(encoding="utf-8"), module.name


def test_new_library_query_path_contains_no_textual_sql() -> None:
    paths = (
        APP_ROOT / "modules" / "library" / "infrastructure" / "queries.py",
        APP_ROOT / "modules" / "library" / "infrastructure" / "filter_query.py",
        APP_ROOT / "modules" / "library" / "infrastructure" / "book_list.py",
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


def test_capability_presentations_do_not_import_legacy_routes_or_infrastructure() -> (
    None
):
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


def test_legacy_persistent_import_worker_has_been_removed() -> None:
    path = APP_ROOT / "worker" / "persistent_import_queue.py"
    assert not path.exists()


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

    query_port = APP_ROOT / "modules" / "imports" / "application" / "query_ports.py"
    if query_port.exists():
        source = query_port.read_text(encoding="utf-8")
        assert "__getattr__" not in source
        assert "Callable[..., Any]" not in source

    dto_path = APP_ROOT / "modules" / "imports" / "application" / "dto.py"
    if dto_path.exists():
        dto = dto_path.read_text(encoding="utf-8")
        for token in ("to_legacy_dict", "def __getitem__", "def get("):
            assert token not in dto

    bootstrap = (APP_ROOT / "bootstrap" / "imports.py").read_text(encoding="utf-8")
    assert "_coerce_import_task" not in bootstrap
    assert "ImportTaskDTO | dict" not in bootstrap


def test_persistent_import_worker_does_not_reexport_commands() -> None:
    assert not (APP_ROOT / "worker" / "persistent_import_queue.py").exists()


def test_retired_source_http_persistence_has_been_removed() -> None:
    assert not (
        APP_ROOT / "modules" / "metadata" / "infrastructure" / "sources_http.py"
    ).exists()


def test_remaining_compat_migration_adapters_use_typed_expressions() -> None:
    paths = (
        APP_ROOT / "modules" / "library" / "infrastructure" / "projections.py",
        APP_ROOT / "modules" / "library" / "infrastructure" / "storage.py",
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


def test_readable_resource_migrations_are_linear_and_baseline_is_self_contained() -> (
    None
):
    versions_dir = APP_ROOT / "db" / "alembic" / "versions"
    revision_files = sorted(versions_dir.glob("*.py"))
    assert [path.name for path in revision_files] == [
        "0001_library_topology_baseline.py",
        "0002_library_scan_queue_uniqueness.py",
        "0003_audio_asset_title.py",
        "0004_remove_media_kind.py",
    ]
    path = versions_dir / "0001_library_topology_baseline.py"
    source = path.read_text(encoding="utf-8")
    assert 'revision: str = "0001_library_topology_baseline"' in source
    assert "down_revision: str | Sequence[str] | None = None" in source
    assert "_build_overlay_metadata" in source
    assert "LibrarySourceNode" in source
    assert "LibraryImportTask" in source
    assert "coverPath" in source
    assert "coverStatus" in source
    forbidden = (
        "app.models",
        "app.db.base",
        "Base.metadata",
        "create_all",
        "sqlalchemy.text",
        "from sqlalchemy import text",
        "importlib",
        "__import__",
        "exec_driver_sql",
        "import sqlite3",
        "0002_version_covers",
        "0003_readable_resource_overlay_schema",
    )
    for token in forbidden:
        # Docstring may name retired revisions as unsupported; only ban imports/code paths.
        if token in {
            "0002_version_covers",
            "0003_readable_resource_overlay_schema",
        }:
            # Allowed only in module docstring describing unsupported upgrades.
            body = source.split('"""', 2)[-1]
            assert token not in body, token
            continue
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
            return _is_string_expression(node.left) or _is_string_expression(node.right)
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


def test_readable_resource_baseline_overlay_check_constraints_use_typed_expressions() -> (
    None
):
    import ast

    path = (
        APP_ROOT / "db" / "alembic" / "versions" / "0001_library_topology_baseline.py"
    )
    source = path.read_text(encoding="utf-8")
    start = source.index("def _build_overlay_metadata()")
    end = source.index("\ndef upgrade()")
    tree = ast.parse(source[start:end], filename=str(path))

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
            return _is_string_expression(node.left) or _is_string_expression(node.right)
        return False

    check_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_check_constraint_call(node):
            continue
        check_count += 1
        expression: ast.AST | None = node.args[0] if node.args else None
        for keyword in node.keywords:
            if keyword.arg == "sqltext":
                expression = keyword.value
        assert not _is_string_expression(expression), (
            f"overlay CheckConstraint must use typed SQLAlchemy expressions "
            f"(line {node.lineno})"
        )
    assert check_count >= 10
    assert "sqlite_where" in source[start:end]


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
        APP_ROOT / "db" / "alembic" / "versions" / "0001_library_topology_baseline.py",
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
        if path.name == "0001_library_topology_baseline.py":
            # Only the overlay builder is an ADR 0018 target; the rest of the
            # baseline still contains unrelated legacy writeback lease columns.
            start = source.index("def _build_overlay_metadata()")
            end = source.index("\ndef upgrade()")
            source = source[start:end]
            assert "LibraryImportTask" in source
            assert "leaseExpiresAt" not in source
            assert "heartbeat" not in source
        for token in forbidden:
            assert token not in source, f"{path}: forbidden {token}"
        if path.name in {"task_queue.py", "worker.py", "ports.py"}:
            for token in heartbeat_paths_extra:
                assert token not in source, f"{path}: forbidden {token}"


def test_adr0018_target_config_forbids_unused_queue_and_observed_refresh() -> None:
    """Target config/repository must not revive high-water or observed refresh."""

    paths = (
        APP_ROOT / "modules" / "library" / "application" / "source_tree_ports.py",
        APP_ROOT
        / "modules"
        / "library"
        / "infrastructure"
        / "persistence"
        / "source_tree_repository.py",
        APP_ROOT / "modules" / "imports" / "application" / "readable_resource",
        APP_ROOT / "modules" / "imports" / "infrastructure" / "readable_resource",
        APP_ROOT / "bootstrap" / "readable_resource_pipeline.py",
    )
    forbidden = ("queue_high_water", "refresh_observed")
    files: list[Path] = []
    for root in paths:
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
        APP_ROOT / "modules" / "imports" / "infrastructure" / "library_queries.py",
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


def test_adr0019_cross_capability_adapters_use_public_surfaces() -> None:
    forbidden_imports = {
        APP_ROOT
        / "modules"
        / "imports"
        / "infrastructure"
        / "readable_resource"
        / "adapter_registry.py": ("app.modules.metadata.application",),
        APP_ROOT / "modules" / "media" / "infrastructure" / "resource_repository.py": (
            "app.modules.library.infrastructure",
        ),
        APP_ROOT / "modules" / "organize" / "infrastructure" / "eligibility.py": (
            "app.modules.library.infrastructure",
        ),
        APP_ROOT / "modules" / "organize" / "infrastructure" / "job_queries.py": (
            "app.modules.library.infrastructure",
        ),
        APP_ROOT / "modules" / "reader" / "infrastructure" / "resource_repository.py": (
            "app.modules.library.infrastructure",
        ),
        APP_ROOT / "modules" / "reader" / "presentation" / "v4.py": (
            "app.modules.publications.application",
            "app.modules.publications.domain",
        ),
    }
    for path, tokens in forbidden_imports.items():
        source = path.read_text(encoding="utf-8")
        for token in tokens:
            assert token not in source, f"{path}: private import {token}"

    public_imports = {
        APP_ROOT
        / "modules"
        / "imports"
        / "infrastructure"
        / "readable_resource"
        / "adapter_registry.py": "app.modules.metadata.public",
        APP_ROOT
        / "modules"
        / "reader"
        / "presentation"
        / "v4.py": "app.modules.publications.public",
    }
    for path, token in public_imports.items():
        assert token in path.read_text(encoding="utf-8"), (
            f"{path}: expected public capability surface {token}"
        )

    for relative_path in (
        "modules/download/infrastructure/tasks.py",
        "modules/media/infrastructure/resource_repository.py",
        "modules/reader/infrastructure/resource_repository.py",
    ):
        source = (APP_ROOT / relative_path).read_text(encoding="utf-8")
        assert "app.models" in source, relative_path


_LEGACY_IDENTITY_NAMES = frozenset(
    {
        "LibraryWork",
        "LibraryVersion",
        "LibraryVolume",
        "LibraryFile",
        "LibraryReadingUnit",
        "LibraryReadingProgress",
        "WorkQueuePort",
        "SqlAlchemyReadableResourceWorkQueue",
        "WorkRecordMutation",
        "UpdateWorkRecord",
        "ApplyWorkMetadata",
        "IMPLICIT_VERSION_SOURCE_KEY",
        "sync_work_facets",
        "metadata_context_for_work",
        "update_work",
        "get_work",
        "work_entity_record",
        "for_visible_work",
        "mark_work_organize_status",
        "work_id",
        "version_id",
        "volume_id",
        "file_id",
    }
)

_LEGACY_IDENTITY_WIRE_KEYS = frozenset(
    {
        "workId",
        "versionId",
        "volumeId",
        "fileId",
        "work_id",
        "version_id",
        "volume_id",
        "file_id",
    }
)


def _runtime_python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and not (
            "modules" in path.parts
            and path.parts[path.parts.index("modules") + 1] == "mobile"
        )
    )


def _legacy_identity_hits(
    path: Path,
    *,
    include_string_literals: bool = True,
) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        value: str | None = None
        if isinstance(node, (ast.Name, ast.Attribute)):
            value = node.id if isinstance(node, ast.Name) else node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            value = node.name
        elif include_string_literals and isinstance(node, ast.Constant):
            value = node.value if isinstance(node.value, str) else None
        if value in _LEGACY_IDENTITY_NAMES or value in _LEGACY_IDENTITY_WIRE_KEYS:
            hits.append(f"{path}:{getattr(node, 'lineno', 0)}:{value}")
    return hits


def test_runtime_and_target_fixture_have_no_legacy_identity_references() -> None:
    hits = [
        hit for path in _runtime_python_files() for hit in _legacy_identity_hits(path)
    ]
    fixture = (
        API_ROOT / "tests" / "contract" / "api" / "test_openapi_runtime_regressions.py"
    )
    hits.extend(_legacy_identity_hits(fixture, include_string_literals=False))
    assert hits == [], "legacy identity references:\n" + "\n".join(hits)


def test_runtime_has_no_dynamic_table_presence_detection() -> None:
    hits: list[str] = []
    for path in _runtime_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_has_table"
            ):
                hits.append(f"{path}:{node.lineno}:_has_table")
            if isinstance(node, ast.Attribute) and node.attr == "has_table":
                hits.append(f"{path}:{node.lineno}:has_table")
    assert hits == [], "dynamic table detection remains:\n" + "\n".join(hits)


def test_target_import_pipeline_has_one_queue_and_no_legacy_controls() -> None:
    queue_directory = (
        APP_ROOT / "modules" / "imports" / "infrastructure" / "readable_resource"
    )
    assert (queue_directory / "task_queue.py").exists()
    assert not (queue_directory / "work_queue.py").exists()

    forbidden_files = {
        "legacy_persistence.py",
        "import_records.py",
        "queue_maintenance.py",
        "maintenance_write.py",
        "library_import_store.py",
        "managed_pipeline.py",
        "orchestration_services.py",
    }
    import_root = APP_ROOT / "modules" / "imports"
    assert not {
        path.name for path in import_root.rglob("*.py") if path.name in forbidden_files
    }

    forbidden_tokens = (
        "WorkQueuePort",
        "work_queue",
        "SqlAlchemyReadableResourceWorkQueue",
        "ImportTaskDTO",
        "ImportTaskPayload",
        "claim_next_import_task",
        "cancel_import_task",
        "retry_import_task",
        "clear_import_tasks",
        "leaseOwner",
        "leaseExpiresAt",
        "fencing",
        "fence_claim",
        "heartbeat",
        "candidateRawJson",
        "ImportWorkItem",
        "ResourceCandidate",
        "AssetCandidate",
    )
    files = (
        APP_ROOT / "bootstrap" / "readable_resource_pipeline.py",
        APP_ROOT / "modules" / "imports" / "application" / "readable_resource",
        APP_ROOT / "modules" / "imports" / "infrastructure" / "readable_resource",
        APP_ROOT / "modules" / "imports" / "presentation",
    )
    paths = [
        path
        for root in files
        for path in (root.rglob("*.py") if root.is_dir() else (root,))
        if "__pycache__" not in path.parts
    ]
    hits = [
        f"{path}:{token}"
        for path in paths
        for token in forbidden_tokens
        if token in path.read_text(encoding="utf-8")
    ]
    assert hits == [], "legacy importer controls remain:\n" + "\n".join(hits)


def test_mobile_is_excluded_from_target_backend_capability_changes() -> None:
    roots = (
        APP_ROOT / "bootstrap",
        APP_ROOT / "worker",
        APP_ROOT / "modules" / "imports",
        APP_ROOT / "modules" / "library",
        APP_ROOT / "modules" / "metadata",
        APP_ROOT / "modules" / "organize",
    )
    hits = [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
        and "app.modules.mobile" in path.read_text(encoding="utf-8")
    ]
    assert hits == [], (
        "target backend imports a Mobile compatibility shim: "
        + ", ".join(str(path) for path in hits)
    )


def test_fresh_runtime_metadata_matches_the_single_baseline(tmp_path: Path) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.core.config import Settings
    from app.db.base import Base
    from app.db.bootstrap import bootstrap_database
    from app.db.sqlite import create_sqlite_engine

    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()
