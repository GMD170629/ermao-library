from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

APP_ROOT = Path(__file__).parents[2] / "app"
TRANSACTION_METHODS = frozenset({"begin", "commit", "rollback"})
SESSION_FLUSH_RECEIVERS = frozenset({"db", "session", "probe", "uow", "unit_of_work"})
WRITE_SCOPE_BUSINESS_CALLS = frozenset(
    {
        "Path",
        "cuid",
        "dict",
        "datetime.now",
        "datetime.utcnow",
        "db_timestamp",
        "float",
        "hashlib.md5",
        "hashlib.sha1",
        "hashlib.sha256",
        "int",
        "json.dump",
        "json.dumps",
        "json.load",
        "json.loads",
        "list",
        "now_timestamp_ms",
        "os.replace",
        "set",
        "str",
        "_now",
        "now",
        "sorted",
        "time.time_ns",
        "timedelta",
        "tuple",
        "uuid4",
    }
)
WRITE_SCOPE_BUSINESS_METHODS = frozenset(
    {
        "append",
        "extend",
        "get",
        "items",
        "is_dir",
        "is_file",
        "keys",
        "mkdir",
        "open",
        "read_bytes",
        "read_text",
        "replace",
        "resolve",
        "rmdir",
        "stat",
        "unlink",
        "update",
        "values",
        "write_bytes",
        "write_text",
    }
)


def _python_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    return root.rglob("*.py")


def _receiver_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _transaction_controls(path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        receiver = _receiver_name(node.func.value)
        if method in TRANSACTION_METHODS or (
            method == "flush" and receiver in SESSION_FLUSH_RECEIVERS
        ):
            violations.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}:{method}")
    return violations


def _callable_parameter_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    result: set[str] = set()
    arguments = (
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    )
    for argument in arguments:
        if argument.annotation is None:
            continue
        annotation = ast.unparse(argument.annotation)
        if "Callable" in annotation:
            result.add(argument.arg)
    return result


def _callback_transaction_wrappers(path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        callback_names = _callable_parameter_names(node)
        if not callback_names:
            continue
        calls_callback = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id in callback_names
            for child in ast.walk(node)
        )
        owns_transaction = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in {"commit", "rollback"}
            for child in ast.walk(node)
        )
        if calls_callback and owns_transaction:
            violations.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}:{node.name}")
    return violations


def _begin_scope_business_calls(path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        owns_begin = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "begin"
            for item in node.items
        )
        if not owns_begin:
            continue
        for statement in node.body:
            for child in ast.walk(statement):
                if not isinstance(child, ast.Call):
                    continue
                if isinstance(child.func, ast.Attribute):
                    receiver = _receiver_name(child.func.value)
                    if receiver in SESSION_FLUSH_RECEIVERS and child.func.attr in {
                        "execute",
                        "scalar",
                        "scalars",
                        "flush",
                    }:
                        continue
                if isinstance(child.func, ast.Name) and (
                    child.func.id in {"len", "range"}
                    or child.func.id.startswith("write_")
                    or (
                        child.func.id.startswith("execute_")
                        and child.func.id.endswith("_write")
                    )
                ):
                    continue
                violations.append(
                    f"{path.relative_to(APP_ROOT)}:{child.lineno}:"
                    f"{ast.unparse(child.func)}"
                )
    return violations


def _write_scope_business_calls(path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local_functions = {
            child.name
            for child in function.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(function):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            owns_write_scope = any(
                isinstance(item.context_expr, ast.Call)
                and (
                    (
                        isinstance(item.context_expr.func, ast.Name)
                        and item.context_expr.func.id.endswith("WriteTransaction")
                    )
                    or (
                        isinstance(item.context_expr.func, ast.Attribute)
                        and item.context_expr.func.attr.endswith("WriteTransaction")
                    )
                )
                for item in node.items
            )
            if not owns_write_scope:
                continue
            for statement in node.body:
                for child in ast.walk(statement):
                    if not isinstance(child, ast.Call):
                        continue
                    call_name = ast.unparse(child.func)
                    calls_business_method = (
                        isinstance(child.func, ast.Attribute)
                        and child.func.attr in WRITE_SCOPE_BUSINESS_METHODS
                    )
                    if (
                        call_name in WRITE_SCOPE_BUSINESS_CALLS
                        or calls_business_method
                        or (
                            isinstance(child.func, ast.Name)
                            and child.func.id in local_functions
                        )
                    ):
                        violations.append(
                            f"{path.relative_to(APP_ROOT)}:{child.lineno}:{call_name}"
                        )
    return violations


def _row_by_row_orm_writes(path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    session_receiver_names = SESSION_FLUSH_RECEIVERS | {"_db", "_session"}
    for loop in ast.walk(tree):
        if not isinstance(loop, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for child in ast.walk(loop):
            if not isinstance(child, ast.Call) or not isinstance(
                child.func, ast.Attribute
            ):
                continue
            receiver = child.func.value
            receiver_name = (
                receiver.id
                if isinstance(receiver, ast.Name)
                else receiver.attr
                if isinstance(receiver, ast.Attribute)
                else None
            )
            if receiver_name in session_receiver_names and child.func.attr in {
                "add",
                "add_all",
                "flush",
            }:
                violations.append(
                    f"{path.relative_to(APP_ROOT)}:{child.lineno}:{child.func.attr}"
                )
    return violations


def test_delivery_bootstrap_and_workers_do_not_control_transactions() -> None:
    violations: list[str] = []
    roots = [APP_ROOT / "bootstrap", APP_ROOT / "worker", APP_ROOT / "services"]
    roots.extend((APP_ROOT / "modules").glob("*/presentation"))
    for root in roots:
        for path in _python_files(root):
            violations.extend(_transaction_controls(path))
    assert violations == []


def test_transaction_wrappers_do_not_execute_unknown_callbacks() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        if "db/alembic/versions" in path.as_posix():
            continue
        violations.extend(_callback_transaction_wrappers(path))
    assert violations == []


def test_explicit_begin_scopes_contain_only_prepared_sql_execution() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        if path == APP_ROOT / "db" / "runner.py":
            continue
        if "db/alembic/versions" in path.as_posix():
            continue
        violations.extend(_begin_scope_business_calls(path))
    assert violations == []


def test_named_write_scopes_do_not_run_business_preparation() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        if "db/alembic/versions" in path.as_posix():
            continue
        violations.extend(_write_scope_business_calls(path))
    assert violations == []


def test_bulk_paths_do_not_write_orm_rows_one_at_a_time() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        if "db/alembic/versions" in path.as_posix():
            continue
        violations.extend(_row_by_row_orm_writes(path))
    assert violations == []


def test_session_observer_cannot_add_work_during_flush_or_commit() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        source = path.read_text(encoding="utf-8")
        observer_tokens = (
            '"after_flush"',
            '"before_commit"',
            "'after_flush'",
            "'before_commit'",
        )
        for token in observer_tokens:
            if token in source:
                violations.append(f"{path.relative_to(APP_ROOT)}:{token}")
    assert violations == []


def test_system_events_do_not_hide_an_independent_commit() -> None:
    violations: list[str] = []
    for path in _python_files(APP_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name == "record_system_event"
                and any(
                    argument.arg == "commit"
                    for argument in (
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    )
                )
            ):
                violations.append(
                    f"{path.relative_to(APP_ROOT)}:{node.lineno}:commit-parameter"
                )
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "commit"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    violations.append(
                        f"{path.relative_to(APP_ROOT)}:{node.lineno}:commit=True"
                    )
    assert violations == []


def test_library_infrastructure_uses_public_shelf_contracts() -> None:
    library_infrastructure = APP_ROOT / "modules" / "library" / "infrastructure"
    violations: list[str] = []
    for path in _python_files(library_infrastructure):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("app.modules.shelf.infrastructure"):
                    violations.append(
                        f"{path.relative_to(APP_ROOT)}:{node.lineno}:{node.module}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.modules.shelf.infrastructure"):
                        violations.append(
                            f"{path.relative_to(APP_ROOT)}:{node.lineno}:{alias.name}"
                        )
    assert violations == []


def test_library_bootstrap_does_not_import_pipeline_directly() -> None:
    path = APP_ROOT / "bootstrap" / "library.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.bootstrap.readable_resource_pipeline":
                violations.append(node.lineno)
        elif isinstance(node, ast.Import) and any(
            alias.name == "app.bootstrap.readable_resource_pipeline"
            for alias in node.names
        ):
            violations.append(node.lineno)
    assert violations == []
