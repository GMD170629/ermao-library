from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from fastapi.routing import APIRoute

APP_ROOT = Path(__file__).parents[2] / "app"
CATALOG_ROOT = APP_ROOT / "modules" / "catalog"
WATCHER_ROOT = CATALOG_ROOT / "infrastructure" / "watcher"
WATCHER_DOMAIN = CATALOG_ROOT / "domain" / "watcher.py"
PERSISTENCE_ROOT = CATALOG_ROOT / "infrastructure" / "persistence"
WATCHER_APPLICATION_FILES = tuple(
    path
    for path in sorted((CATALOG_ROOT / "application").glob("*.py"))
    if "watcher" in path.stem or "reconcile" in path.stem
)
PURE_FORBIDDEN_IMPORTS = (
    "os",
    "pathlib",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "watchdog",
    "asyncio",
    "sched",
    "threading",
    "time",
    "app.db",
    "app.models",
    "app.worker",
    "app.modules.catalog.infrastructure",
    "app.modules.catalog.presentation",
)
WATCHER_ADAPTER_FORBIDDEN_IMPORTS = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "asyncio",
    "sched",
    "threading",
    "time",
    "app.db",
    "app.models",
    "app.worker",
    "app.modules.catalog.presentation",
    "app.modules.catalog.infrastructure.persistence",
)
PRIVATE_CAPABILITY_ROOTS = tuple(
    f"app.modules.{capability}"
    for capability in ("imports", "media", "metadata", "publications")
)
NEW_WATCHER_FIXED_ROOTS = (
    "app.modules.catalog.domain.watcher",
    "app.modules.catalog.infrastructure.watcher",
)
OPAQUE_IDENTITY_FILES = (
    CATALOG_ROOT / "application" / "full_scan_execution.py",
    CATALOG_ROOT / "application" / "scan_ports.py",
    PERSISTENCE_ROOT / "source_observation_repositories.py",
    PERSISTENCE_ROOT / "reconcile_source_repository.py",
    PERSISTENCE_ROOT / "source_path_resolution.py",
    PERSISTENCE_ROOT / "topology_repository.py",
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


def _is_new_watcher_module(module: str) -> bool:
    if any(_matches_root(module, root) for root in NEW_WATCHER_FIXED_ROOTS):
        return True
    application_prefix = "app.modules.catalog.application."
    if not module.startswith(application_prefix):
        return False
    local_module = module.removeprefix(application_prefix).casefold()
    return "watch" in local_module or "reconcile" in local_module


def test_watcher_domain_and_application_remain_platform_and_framework_free() -> None:
    violations: list[str] = []
    for path in (WATCHER_DOMAIN, *WATCHER_APPLICATION_FILES):
        source = path.read_text(encoding="utf-8")
        for marker in ("threading.Timer(", "asyncio.sleep("):
            if marker in source:
                violations.append(f"{path.relative_to(CATALOG_ROOT)}: {marker}")
        for module, _names, line in _imports(path):
            if any(_matches_root(module, root) for root in PURE_FORBIDDEN_IMPORTS):
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}")

    assert violations == []


def test_watchdog_mapper_uses_events_contract_without_observer_or_legacy_worker() -> (
    None
):
    """PR11 must select a health-aware, parent-move-ordered runtime backend."""

    violations: list[str] = []
    watchdog_imports: list[str] = []
    for path in _python_files(WATCHER_ROOT):
        source = path.read_text(encoding="utf-8")
        for marker in ("Observer(", "threading.Timer(", "asyncio.sleep("):
            if marker in source:
                violations.append(f"{path.relative_to(CATALOG_ROOT)}: {marker}")
        for module, _names, line in _imports(path):
            if _matches_root(module, "watchdog"):
                watchdog_imports.append(module)
                if module != "watchdog.events":
                    violations.append(
                        f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}"
                    )
            if any(
                _matches_root(module, root)
                for root in (
                    *WATCHER_ADAPTER_FORBIDDEN_IMPORTS,
                    *PRIVATE_CAPABILITY_ROOTS,
                )
            ):
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{line}: {module}")

    assert watchdog_imports == ["watchdog.events"]
    assert violations == []


def test_watcher_adapter_owns_no_router_schema_queue_or_runtime_observer() -> None:
    forbidden_names = {
        "http.py",
        "orm.py",
        "queue.py",
        "router.py",
        "runtime.py",
        "schema.py",
        "schemas.py",
        "worker.py",
    }

    assert {path.name for path in _python_files(WATCHER_ROOT)}.isdisjoint(
        forbidden_names
    )


def test_new_watcher_capability_remains_absent_from_production_composition() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        if path.is_relative_to(CATALOG_ROOT):
            continue
        for module, names, line in _imports(path):
            imports_watcher_module = _is_new_watcher_module(module)
            imports_watcher_from_public = (
                module == "app.modules.catalog.public"
                and any("watch" in name.casefold() for name in names)
            )
            if imports_watcher_module or imports_watcher_from_public:
                violations.append(f"{path.relative_to(APP_ROOT)}:{line}: {module}")

    from app.api.router import api_router

    routes = tuple(route for route in api_router.routes if isinstance(route, APIRoute))
    watcher_routes = sorted(
        str(route.path)
        for route in routes
        if "watch" in str(route.path).casefold()
        or "reconcile" in str(route.path).casefold()
        or _is_new_watcher_module(getattr(route.endpoint, "__module__", ""))
    )

    assert violations == []
    assert watcher_routes == []


def test_persistent_catalog_identity_never_consumes_domain_path_keys() -> None:
    """Raw paths describe slots; only opaque Source/owner IDs may own identity."""

    violations: list[str] = []
    forbidden_helper_names = {
        "_source_entry_id",
        "source_entry_id",
        "_work_id",
        "_version_id",
        "_volume_id",
        "_unit_id",
    }
    for path in OPAQUE_IDENTITY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name in forbidden_helper_names:
                    violations.append(
                        f"{path.relative_to(CATALOG_ROOT)}:{node.lineno}: {node.name}"
                    )
                if node.name in {
                    "_work_stable_id",
                    "_version_stable_id",
                    "_volume_stable_id",
                    "_asset_stable_id",
                    "_unit_stable_id",
                }:
                    parameter_names = {argument.arg for argument in node.args.args} | {
                        argument.arg for argument in node.args.kwonlyargs
                    }
                    unsafe_parameters = sorted(
                        name
                        for name in parameter_names
                        if "path" in name.casefold() or name.casefold().endswith("key")
                    )
                    if unsafe_parameters:
                        violations.append(
                            f"{path.relative_to(CATALOG_ROOT)}:{node.lineno}: "
                            f"{node.name}{tuple(unsafe_parameters)}"
                        )
            elif isinstance(node, ast.Attribute) and node.attr == "unit_key":
                violations.append(
                    f"{path.relative_to(CATALOG_ROOT)}:{node.lineno}: .unit_key"
                )
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "structure_key"
                and isinstance(node.value, ast.Name)
                and node.value.id in {"plan", "row"}
            ):
                violations.append(
                    f"{path.relative_to(CATALOG_ROOT)}:{node.lineno}: "
                    f"{node.value.id}.structure_key"
                )

    allocator_path = PERSISTENCE_ROOT / "source_path_resolution.py"
    allocator_tree = ast.parse(
        allocator_path.read_text(encoding="utf-8"), filename=str(allocator_path)
    )
    allocators = tuple(
        node
        for node in allocator_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "new_opaque_source_id"
    )
    if len(allocators) != 1 or allocators[0].args.args or allocators[0].args.kwonlyargs:
        violations.append(
            "infrastructure/persistence/source_path_resolution.py: "
            "new_opaque_source_id must accept no path-derived input"
        )

    assert violations == []
