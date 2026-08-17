from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

APP_ROOT = Path(__file__).parents[2] / "app"
CATALOG_ROOT = APP_ROOT / "modules" / "catalog"
ADMISSION_ADAPTER_ROOT = CATALOG_ROOT / "infrastructure" / "admission"

PURE_LAYER_FORBIDDEN_IMPORTS = (
    "os",
    "pathlib",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "app.db",
    "app.models",
)
PRIVATE_CAPABILITY_ROOTS = tuple(
    f"app.modules.{capability}"
    for capability in ("imports", "media", "metadata", "publications")
)
ADAPTER_FORBIDDEN_IMPORTS = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "app.db",
    "app.models",
    "app.modules.catalog.presentation",
    "app.modules.catalog.infrastructure.persistence",
)


def _python_files(root: Path) -> Iterator[Path]:
    return iter(sorted(root.rglob("*.py")))


def _imported_modules(path: Path) -> Iterator[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module, node.lineno


def _matches_root(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}.")


def test_catalog_domain_and_application_remain_platform_and_framework_free() -> None:
    violations: list[str] = []
    for layer in ("domain", "application"):
        root = CATALOG_ROOT / layer
        for path in _python_files(root):
            for module, line in _imported_modules(path):
                if any(
                    _matches_root(module, forbidden)
                    for forbidden in PURE_LAYER_FORBIDDEN_IMPORTS
                ):
                    relative_path = path.relative_to(CATALOG_ROOT)
                    violations.append(f"{relative_path}:{line}: {module}")

    assert violations == []


def test_source_admission_adapter_uses_only_public_cross_capability_apis() -> None:
    violations: list[str] = []
    for path in _python_files(ADMISSION_ADAPTER_ROOT):
        for module, line in _imported_modules(path):
            for capability_root in PRIVATE_CAPABILITY_ROOTS:
                if _matches_root(module, capability_root) and module != (
                    f"{capability_root}.public"
                ):
                    relative_path = path.relative_to(CATALOG_ROOT)
                    violations.append(f"{relative_path}:{line}: {module}")

    assert violations == []


def test_source_admission_adapter_has_no_delivery_or_persistence_dependencies() -> None:
    violations: list[str] = []
    for path in _python_files(ADMISSION_ADAPTER_ROOT):
        for module, line in _imported_modules(path):
            if any(
                _matches_root(module, forbidden)
                for forbidden in ADAPTER_FORBIDDEN_IMPORTS
            ):
                relative_path = path.relative_to(CATALOG_ROOT)
                violations.append(f"{relative_path}:{line}: {module}")

    assert violations == []


def test_source_admission_adapter_does_not_own_scan_or_delivery_modules() -> None:
    forbidden_module_names = {
        "http.py",
        "orm.py",
        "router.py",
        "scan.py",
        "scanner.py",
        "schema.py",
        "schemas.py",
    }

    assert {path.name for path in _python_files(ADMISSION_ADAPTER_ROOT)}.isdisjoint(
        forbidden_module_names
    )


def test_production_router_does_not_register_catalog_source_admission() -> None:
    from fastapi.routing import APIRoute

    from app.api.router import api_router

    routes = tuple(route for route in api_router.routes if isinstance(route, APIRoute))
    exposed_catalog_endpoints = sorted(
        f"{route.path}:{getattr(route.endpoint, '__module__', '')}"
        for route in routes
        if getattr(route.endpoint, "__module__", "").startswith("app.modules.catalog")
    )
    exposed_admission_paths = sorted(
        str(route.path)
        for route in routes
        if any(
            fragment in str(route.path).casefold()
            for fragment in ("admission", "probe")
        )
    )

    assert exposed_catalog_endpoints == []
    assert exposed_admission_paths == []
