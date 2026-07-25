from __future__ import annotations

import ast
import sys
from pathlib import Path

APPV2 = Path(__file__).resolve().parents[1] / "appv2"
MODULES = APPV2 / "modules"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_appv2_never_imports_legacy_app() -> None:
    violations: list[str] = []
    for path in _python_files(APPV2):
        for imported in _imports(path):
            if imported == "app" or imported.startswith("app."):
                violations.append(f"{path.relative_to(APPV2)} imports {imported}")
    assert violations == []


def test_platform_never_imports_business_modules() -> None:
    violations = [
        f"{path.relative_to(APPV2)} imports {imported}"
        for path in _python_files(APPV2 / "platform")
        for imported in _imports(path)
        if imported.startswith("appv2.modules.")
    ]
    assert violations == []


def test_domains_only_use_standard_library_and_own_domain() -> None:
    violations: list[str] = []
    for domain in sorted(MODULES.glob("*/domain")):
        module_name = domain.parent.name
        allowed_prefix = f"appv2.modules.{module_name}.domain"
        for path in _python_files(domain):
            for imported in _imports(path):
                root = imported.split(".", 1)[0]
                if (
                    root not in sys.stdlib_module_names
                    and root != "__future__"
                    and not imported.startswith(allowed_prefix)
                ):
                    violations.append(f"{path.relative_to(APPV2)} imports {imported}")
    assert violations == []


def test_cross_module_imports_only_target_contracts() -> None:
    violations: list[str] = []
    for module_root in sorted(MODULES.iterdir()):
        if not module_root.is_dir():
            continue
        source_module = module_root.name
        for path in _python_files(module_root):
            for imported in _imports(path):
                parts = imported.split(".")
                if len(parts) < 4 or parts[:2] != ["appv2", "modules"]:
                    continue
                target_module = parts[2]
                if target_module != source_module and (len(parts) < 4 or parts[3] != "contracts"):
                    violations.append(f"{path.relative_to(APPV2)} imports {imported}")
    assert violations == []


def test_framework_and_io_dependencies_stay_out_of_domain_and_application() -> None:
    forbidden_roots = {
        "aiofiles",
        "alembic",
        "fastapi",
        "httpx",
        "psycopg",
        "sqlalchemy",
        "starlette",
    }
    violations: list[str] = []
    for module_root in sorted(MODULES.iterdir()):
        for layer in ("domain", "application"):
            for path in _python_files(module_root / layer):
                for imported in _imports(path):
                    if imported.split(".", 1)[0] in forbidden_roots:
                        violations.append(f"{path.relative_to(APPV2)} imports {imported}")
    assert violations == []


def test_api_and_entrypoints_do_not_import_sqlalchemy() -> None:
    roots = [*MODULES.glob("*/api"), APPV2 / "entrypoints"]
    violations = [
        f"{path.relative_to(APPV2)} imports {imported}"
        for root in roots
        for path in _python_files(root)
        for imported in _imports(path)
        if imported.startswith(("sqlalchemy", "psycopg"))
    ]
    assert violations == []


def test_repository_classes_never_commit_transactions() -> None:
    violations: list[str] = []
    for path in MODULES.glob("*/infrastructure/repositories.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Repository"):
                continue
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "commit"
                ):
                    violations.append(f"{path.relative_to(APPV2)}:{child.lineno} {node.name}")
    assert violations == []
