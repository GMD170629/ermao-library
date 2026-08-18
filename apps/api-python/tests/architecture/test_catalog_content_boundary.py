from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from fastapi.routing import APIRoute

APP_ROOT = Path(__file__).parents[2] / "app"
CATALOG_ROOT = APP_ROOT / "modules" / "catalog"
CONTENT_DOMAIN = CATALOG_ROOT / "domain" / "content.py"
CONTENT_APPLICATION_FILES = tuple(
    sorted((CATALOG_ROOT / "application").glob("content_*.py"))
)
CONTENT_ADAPTER_ROOT = CATALOG_ROOT / "infrastructure" / "content"

PURE_FORBIDDEN_IMPORTS = (
    "os",
    "pathlib",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "app.db",
    "app.models",
    "app.modules.catalog.infrastructure",
    "app.modules.catalog.presentation",
)
ADAPTER_FORBIDDEN_IMPORTS = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "app.db",
    "app.models",
    "app.modules.catalog.presentation",
)
CONTENT_RUNTIME_MODULES = (
    "app.modules.catalog.application.content_processing",
    "app.modules.catalog.infrastructure.content",
)
CONTENT_RUNTIME_PUBLIC_NAMES = {
    "ContentUnitOfWork",
    "ContentUowFactory",
    "RequiredOpeningPort",
    "RunNextContentTopologyProjection",
    "RunNextContentTopologyProjectionCommand",
    "RunNextRequiredManifest",
    "RunNextRequiredManifestCommand",
    "RunNextRequiredOpening",
    "RunNextRequiredOpeningCommand",
    "RunNextSourceDigest",
    "RunNextSourceDigestCommand",
    "SourceDigestPort",
}


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


def _is_external_business_capability(module: str) -> bool:
    modules_root = "app.modules."
    if not module.startswith(modules_root):
        return False
    return not _matches_root(module, "app.modules.catalog")


def test_content_domain_and_application_are_framework_io_and_persistence_free() -> None:
    violations: list[str] = []
    for path in (CONTENT_DOMAIN, *CONTENT_APPLICATION_FILES):
        for module, _names, line in _imports(path):
            forbidden = any(
                _matches_root(module, root) for root in PURE_FORBIDDEN_IMPORTS
            )
            if forbidden or _is_external_business_capability(module):
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}")

    assert violations == []


def test_content_adapter_does_not_deep_import_legacy_business_capabilities() -> None:
    violations: list[str] = []
    for path in _python_files(CONTENT_ADAPTER_ROOT):
        for module, _names, line in _imports(path):
            forbidden = any(
                _matches_root(module, root) for root in ADAPTER_FORBIDDEN_IMPORTS
            )
            if forbidden or _is_external_business_capability(module):
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}")

    assert violations == []


def test_pr6_content_workers_remain_absent_from_production_composition() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        if path.is_relative_to(CATALOG_ROOT):
            continue
        for module, names, line in _imports(path):
            imports_runtime = any(
                _matches_root(module, root) for root in CONTENT_RUNTIME_MODULES
            )
            imports_runtime_public = (
                module == "app.modules.catalog.public"
                and not CONTENT_RUNTIME_PUBLIC_NAMES.isdisjoint(names)
            )
            if imports_runtime or imports_runtime_public:
                violations.append(f"{path.relative_to(APP_ROOT)}:{line}: {module}")

    from app.api.router import api_router

    routes = tuple(route for route in api_router.routes if isinstance(route, APIRoute))
    content_routes = sorted(
        str(route.path)
        for route in routes
        if _matches_root(
            getattr(route.endpoint, "__module__", ""),
            "app.modules.catalog.application.content_processing",
        )
    )

    assert violations == []
    assert content_routes == []
