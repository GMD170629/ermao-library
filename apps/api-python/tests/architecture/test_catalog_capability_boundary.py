from __future__ import annotations

import ast
from pathlib import Path

CATALOG_ROOT = Path(__file__).parents[2] / "app" / "modules" / "catalog"
AUTH_PRIVATE_INFRASTRUCTURE = "app.modules.auth.infrastructure"


def test_catalog_does_not_import_auth_private_infrastructure() -> None:
    violations: list[str] = []
    for path in CATALOG_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_modules: tuple[str, ...]
            if isinstance(node, ast.Import):
                imported_modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules = (node.module,)
            else:
                continue
            if any(
                module == AUTH_PRIVATE_INFRASTRUCTURE
                or module.startswith(f"{AUTH_PRIVATE_INFRASTRUCTURE}.")
                for module in imported_modules
            ):
                violations.append(f"{path.relative_to(CATALOG_ROOT)}:{node.lineno}")

    assert violations == []
