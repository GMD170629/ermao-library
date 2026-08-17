from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from fastapi.routing import APIRoute

APP_ROOT = Path(__file__).parents[2] / "app"
CATALOG_ROOT = APP_ROOT / "modules" / "catalog"
DISCOVERY_ROOT = CATALOG_ROOT / "infrastructure" / "discovery"
SCAN_FILES = (
    CATALOG_ROOT / "domain" / "scan.py",
    CATALOG_ROOT / "application" / "scan_dto.py",
    CATALOG_ROOT / "application" / "scan_lifecycle.py",
    CATALOG_ROOT / "application" / "scan_ports.py",
    CATALOG_ROOT / "application" / "full_scan_execution.py",
)
SCAN_PERSISTENCE_FILES = (
    CATALOG_ROOT / "infrastructure" / "persistence" / "scan_fencing.py",
    CATALOG_ROOT / "infrastructure" / "persistence" / "scan_run_repositories.py",
    CATALOG_ROOT / "infrastructure" / "persistence" / "scan_uow.py",
    CATALOG_ROOT
    / "infrastructure"
    / "persistence"
    / "source_observation_repositories.py",
    CATALOG_ROOT / "infrastructure" / "persistence" / "topology_repository.py",
)

DISCOVERY_FORBIDDEN_IMPORTS = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "watchdog",
    "app.db",
    "app.models",
    "app.modules.catalog.presentation",
    "app.modules.catalog.infrastructure.persistence",
)
PRIVATE_CAPABILITY_ROOTS = tuple(
    f"app.modules.{capability}"
    for capability in ("imports", "media", "metadata", "publications")
)
LEGACY_GROUPING_MARKERS = (
    "audio_metadata",
    "book_identity",
    "recognize_book",
    "filename_group",
    "metadata_group",
    "title_group",
)
PRODUCTION_SCAN_MODULES = (
    "app.modules.catalog.application.full_scan_execution",
    "app.modules.catalog.application.scan_lifecycle",
    "app.modules.catalog.infrastructure.discovery",
)
SCAN_CORE_FORBIDDEN_IMPORTS = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "pathlib",
    "os",
    "app.db",
    "app.models",
    "app.modules.catalog.infrastructure",
    "app.modules.catalog.presentation",
)
RAW_DATABASE_MARKERS = (
    "exec_driver_sql(",
    "sqlalchemy.text(",
    "sqlite3.connect(",
    ".cursor(",
)


def _python_files(root: Path) -> Iterator[Path]:
    return iter(sorted(root.rglob("*.py")))


def _imports(path: Path) -> Iterator[tuple[str, tuple[str, ...], int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, (), node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module, tuple(alias.name for alias in node.names), node.lineno


def _matches_root(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}.")


def test_directory_discovery_has_no_delivery_persistence_or_private_imports() -> None:
    violations: list[str] = []
    for path in _python_files(DISCOVERY_ROOT):
        for module, _names, line in _imports(path):
            forbidden = any(
                _matches_root(module, root) for root in DISCOVERY_FORBIDDEN_IMPORTS
            )
            private = any(
                _matches_root(module, root) for root in PRIVATE_CAPABILITY_ROOTS
            )
            if forbidden or private:
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}")

    assert violations == []


def test_scan_does_not_restore_legacy_filename_or_metadata_grouping() -> None:
    violations: list[str] = []
    for path in (*SCAN_FILES, *SCAN_PERSISTENCE_FILES, *_python_files(DISCOVERY_ROOT)):
        source = path.read_text(encoding="utf-8").casefold()
        for marker in LEGACY_GROUPING_MARKERS:
            if marker in source:
                violations.append(f"{path.relative_to(CATALOG_ROOT)}: {marker}")

    assert violations == []


def test_scan_domain_and_application_remain_framework_and_io_free() -> None:
    violations: list[str] = []
    for path in SCAN_FILES:
        for module, _names, line in _imports(path):
            if any(_matches_root(module, root) for root in SCAN_CORE_FORBIDDEN_IMPORTS):
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}")

    assert violations == []


def test_scan_persistence_uses_typed_orm_and_no_private_capability_imports() -> None:
    violations: list[str] = []
    for path in SCAN_PERSISTENCE_FILES:
        source = path.read_text(encoding="utf-8")
        source_folded = source.casefold()
        for marker in RAW_DATABASE_MARKERS:
            if marker.casefold() in source_folded:
                violations.append(f"{path.relative_to(CATALOG_ROOT)}: {marker}")
        for module, _names, line in _imports(path):
            if any(_matches_root(module, root) for root in PRIVATE_CAPABILITY_ROOTS):
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}")

    assert violations == []


def test_directory_discovery_owns_no_router_schema_orm_or_scanner() -> None:
    forbidden_names = {
        "http.py",
        "orm.py",
        "router.py",
        "scan.py",
        "scanner.py",
        "schema.py",
        "schemas.py",
    }

    assert {path.name for path in _python_files(DISCOVERY_ROOT)}.isdisjoint(
        forbidden_names
    )


def test_full_scan_remains_absent_from_production_composition() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        if path.is_relative_to(CATALOG_ROOT):
            continue
        for module, names, line in _imports(path):
            imports_scan_module = any(
                _matches_root(module, root) for root in PRODUCTION_SCAN_MODULES
            )
            imports_scan_from_public = module == "app.modules.catalog.public" and any(
                "scan" in name.casefold() for name in names
            )
            if imports_scan_module or imports_scan_from_public:
                violations.append(f"{path.relative_to(APP_ROOT)}:{line}: {module}")

    from app.api.router import api_router

    routes = tuple(route for route in api_router.routes if isinstance(route, APIRoute))
    scan_routes = sorted(
        str(route.path)
        for route in routes
        if (
            "scan" in str(route.path).casefold()
            and "librar" in str(route.path).casefold()
        )
        or getattr(route.endpoint, "__module__", "").startswith(
            "app.modules.catalog.application.scan"
        )
    )

    assert violations == []
    assert scan_routes == []
