#!/usr/bin/env python3
"""Print a read-only quality snapshot for the Shuku Python backend."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from pathlib import Path


def resolve_backend_root(value: str | None) -> Path:
    if value:
        candidate = Path(value).resolve()
    else:
        repository = Path(__file__).resolve().parents[4]
        candidate = repository / "apps" / "api-python"
    if not (candidate / "app").is_dir() or not (candidate / "pyproject.toml").is_file():
        raise SystemExit(f"Not a Shuku Python backend: {candidate}")
    return candidate


def python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if ".venv" not in path.parts)


def analyze(path: Path) -> tuple[int, Counter[str]]:
    source = path.read_text(encoding="utf-8")
    lines = len(source.splitlines())
    signals: Counter[str] = Counter()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        signals["syntax_errors"] += 1
        return lines, signals

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signals["functions"] += 1
        elif isinstance(node, ast.ClassDef):
            signals["classes"] += 1
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                signals["bare_except"] += 1
            elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                signals["broad_exception"] += 1
        elif isinstance(node, ast.Name) and node.id == "Any":
            signals["any_references"] += 1
    return lines, signals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend-root", help="Path containing app/, tests/, and pyproject.toml"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Number of largest application files to show",
    )
    args = parser.parse_args()

    backend = resolve_backend_root(args.backend_root)
    app_files = python_files(backend / "app")
    test_files = python_files(backend / "tests")
    rows: list[tuple[int, Path, Counter[str]]] = []
    totals: Counter[str] = Counter()

    for path in app_files:
        lines, signals = analyze(path)
        rows.append((lines, path, signals))
        totals["app_lines"] += lines
        totals.update(signals)

    test_lines = sum(analyze(path)[0] for path in test_files)
    print(f"Backend: {backend}")
    print(
        f"Application: {len(app_files)} files, {totals['app_lines']} lines | "
        f"Tests: {len(test_files)} files, {test_lines} lines"
    )
    print(
        "Signals: "
        f"{totals['functions']} functions, {totals['classes']} classes, "
        f"{totals['broad_exception']} broad Exception handlers, "
        f"{totals['bare_except']} bare handlers, {totals['any_references']} Any references"
    )
    print("\nLargest application modules:")
    for lines, path, signals in sorted(rows, reverse=True)[: max(args.top, 0)]:
        relative = path.relative_to(backend)
        print(
            f"{lines:6}  {relative}  "
            f"(functions={signals['functions']}, broad_except={signals['broad_exception']}, "
            f"Any={signals['any_references']})"
        )


if __name__ == "__main__":
    main()
