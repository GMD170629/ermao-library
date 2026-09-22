"""Catch boundaries retain actual errors; control-flow exemptions live beside code.

This supplements fault-injection tests: syntax cannot establish whether every
branch really records the right cause or whether a control-flow explanation is true.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
APP = ROOT / "apps/api-python/app"
SCRIPT_NAMES = (
    "container-entry.py",
    "container_install.py",
    "container_image.py",
    "dependency_install.py",
    "dependency_environment.py",
)
RECORDERS = {
    "record_exception",
    "prepare_exception_diagnostic",
    "emergency_diagnostic",
    "update_warning",
    "_write_fd_fallback",
    "_write_fd_warning",
}


def _direct_nodes(node: ast.AST):
    """Do not credit a handler for logging inside an uncalled nested function."""
    if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    ):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            yield from _direct_nodes(child)


def _call_name(call: ast.Call) -> str:
    return ast.unparse(call.func)


def _preserves_error(node: ast.Raise, error_name: str | None) -> bool:
    if node.exc is None:
        return True
    if error_name and isinstance(node.exc, ast.Name) and node.exc.id == error_name:
        return True
    return bool(
        error_name
        and node.cause is not None
        and any(
            isinstance(part, ast.Name) and part.id == error_name
            for part in ast.walk(node.cause)
        )
    )


def _source_fail_import(tree: ast.Module) -> set[str]:
    # This exact response owner records sys.exception() before constructing JSON.
    return {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "app.schemas.responses"
        for alias in node.names
        if alias.name == "fail"
    }


def _recording_helpers(tree: ast.Module, ambient: set[str]) -> set[str]:
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    helpers = set(RECORDERS)
    changed = True
    while changed:
        changed = False
        for function in functions:
            parameters = {
                argument.arg
                for argument in function.args.args + function.args.kwonlyargs
            }
            nodes = [
                node for statement in function.body for node in _direct_nodes(statement)
            ]
            records = any(
                isinstance(node, ast.Call)
                and (
                    _call_name(node) in ambient
                    or _call_name(node).split(".")[-1] in helpers
                    and any(
                        isinstance(argument, ast.Name) and argument.id in parameters
                        for value in (
                            *node.args,
                            *(keyword.value for keyword in node.keywords),
                        )
                        for argument in ast.walk(value)
                    )
                )
                for node in nodes
            )
            propagates = any(
                isinstance(node, ast.Raise)
                and node.exc is not None
                and any(_preserves_error(node, parameter) for parameter in parameters)
                for node in nodes
            )
            if (records or propagates) and function.name not in helpers:
                helpers.add(function.name)
                changed = True
    return helpers


def _silent_paths(statements, recorded_call, error_name, recorded=False):
    """Follow conditional exits so one re-raise cannot excuse a silent fallback."""
    continuing = [recorded]
    silent = False
    for statement in statements:
        remaining = []
        for already_recorded in continuing:
            if isinstance(statement, ast.If):
                for branch in (statement.body, statement.orelse):
                    exits, active = _silent_paths(
                        branch, recorded_call, error_name, already_recorded
                    )
                    silent |= exits
                    remaining.extend(active)
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                exits, active = _silent_paths(
                    statement.body, recorded_call, error_name, already_recorded
                )
                silent |= exits
                remaining.extend(active)
                continue
            observed = already_recorded or any(
                isinstance(node, ast.Call) and recorded_call(node)
                for node in _direct_nodes(statement)
            )
            if isinstance(statement, ast.Return):
                silent |= not observed
            elif isinstance(statement, ast.Raise):
                silent |= not observed and not _preserves_error(statement, error_name)
            else:
                remaining.append(observed)
        continuing = remaining
    return silent, continuing


def _violations(source: str, name: str) -> list[str]:
    tree = ast.parse(source, filename=name)
    lines = source.splitlines()
    ambient = _source_fail_import(tree)
    helpers = _recording_helpers(tree, ambient)
    # This imported MCP boundary is a named, audited diagnostics owner. A
    # similarly named function from any other module gets no exemption.
    helpers.update(
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.modules.automation.presentation.diagnostics"
        for alias in node.names
        if alias.name == "record_mcp_failure"
    )
    failures = []
    suppressors = {"contextlib.suppress"}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "contextlib":
            suppressors.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "suppress"
            )
        if isinstance(node, ast.Import):
            suppressors.update(
                f"{alias.asname or alias.name}.suppress"
                for alias in node.names
                if alias.name == "contextlib"
            )
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            if (
                isinstance(item.context_expr, ast.Call)
                and _call_name(item.context_expr) in suppressors
            ):
                explanations = [
                    line.split("diagnostics-control-flow:", 1)[1].strip()
                    for line in lines[node.lineno - 1 : node.body[0].lineno]
                    if "diagnostics-control-flow:" in line
                ]
                if not explanations or any(len(reason) < 12 for reason in explanations):
                    failures.append(
                        f"{name}:{node.lineno}: contextlib.suppress stops errors without diagnostics or a justified control-flow annotation"
                    )
    for handler in (
        node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
    ):
        # Only an explanation attached to this handler can exempt it; never a directory.
        first_statement = handler.body[0].lineno
        explanation = [
            line.split("diagnostics-control-flow:", 1)[1].strip()
            for line in lines[handler.lineno - 1 : first_statement]
            if "diagnostics-control-flow:" in line
        ]
        if explanation and all(len(reason) >= 12 for reason in explanation):
            continue
        nodes = [
            node for statement in handler.body for node in _direct_nodes(statement)
        ]
        propagates = any(
            isinstance(node, ast.Raise) and _preserves_error(node, handler.name)
            for node in nodes
        )
        hides_cause = any(
            isinstance(node, ast.Raise)
            and node.exc is not None
            and isinstance(node.cause, ast.Constant)
            and node.cause.value is None
            for node in nodes
        )

        def records_original(call, error_name=handler.name):
            call_name = _call_name(call)
            if call_name in ambient:
                return True
            elif call_name.split(".")[-1] in helpers or call_name in {
                "diagnostics.prepare",
                "self.diagnostics.prepare",
                "self._diagnostics.prepare",
                "self._log.emit",
            }:
                return bool(
                    error_name
                    and any(
                        isinstance(part, ast.Name) and part.id == error_name
                        for value in (
                            *call.args,
                            *(keyword.value for keyword in call.keywords),
                        )
                        for part in ast.walk(value)
                    )
                )
            elif call_name.endswith(".exception") or any(
                keyword.arg == "exc_info"
                and not (
                    isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False
                )
                for keyword in call.keywords
            ):
                return True
            return False

        recorded = any(
            records_original(node) for node in nodes if isinstance(node, ast.Call)
        )
        silent_exit, continuing = _silent_paths(
            handler.body, records_original, handler.name
        )
        if (
            (not recorded and (not propagates or hides_cause))
            or silent_exit
            or any(not state for state in continuing)
        ):
            failures.append(
                f"{name}:{handler.lineno}: {ast.unparse(handler.type) if handler.type else 'bare except'} stops without original-error diagnostics or a justified control-flow annotation"
            )
    return failures


def test_server_exception_boundaries_keep_diagnostics() -> None:
    files = sorted(APP.rglob("*.py")) + [
        ROOT / "scripts" / name for name in SCRIPT_NAMES
    ]
    failures = [
        failure
        for path in files
        for failure in _violations(path.read_text(), str(path.relative_to(ROOT)))
    ]
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize(
    "handler",
    [
        "except OSError: return None",
        "except Exception as error: logger.error('operation failed')",
        "except Exception as error: raise RuntimeError('FAILED') from None",
        "except Exception as error:\n if retry: raise\n raise RuntimeError('FAILED') from None",
        "except Exception as error: record_exception(logger, 'failed', RuntimeError('FAILED'))",
        "except Exception as error:\n def unused(): record_exception(logger, 'failed', error)\n return None",
        "except Exception as error:\n if retry: raise\n return None",
        "except Exception as error:\n if verbose: record_exception(logger, 'failed', error)\n return {'status': 'FAILED', 'code': 'FILE_PUBLISH_FAILED'}",
        "except Exception as error:\n if retry: raise\n task.status = 'FAILED'",
    ],
)
def test_guard_rejects_swallowed_or_replaced_errors(handler: str) -> None:
    assert _violations(
        "def operation():\n try: run()\n " + handler.replace("\n", "\n ") + "\n",
        "fixture.py",
    )


@pytest.mark.parametrize(
    "handler",
    [
        "except OSError as error: record_exception(logger, 'failed', error)",
        "except OSError as error: raise RuntimeError('FAILED') from error",
        "except OSError: raise",
        "except OSError as error:\n if retry: raise\n record_exception(logger, 'failed', error)\n return None",
        "except BlockingIOError:\n # diagnostics-control-flow: lock contention is a normal ownership probe.\n return False",
    ],
)
def test_guard_accepts_diagnostics_and_explicit_control_flow(handler: str) -> None:
    assert not _violations(
        "def operation():\n try: run()\n " + handler.replace("\n", "\n ") + "\n",
        "fixture.py",
    )


@pytest.mark.parametrize(
    "imports,call",
    [
        ("import contextlib", "contextlib.suppress"),
        ("import contextlib as contexts", "contexts.suppress"),
        ("from contextlib import suppress as ignore", "ignore"),
    ],
)
def test_guard_rejects_suppressed_errors(imports: str, call: str) -> None:
    assert _violations(f"{imports}\nwith {call}(OSError):\n delete()\n", "fixture.py")


def test_guard_checks_exact_imported_mcp_diagnostics_owner() -> None:
    function = "\ndef operation():\n try: run()\n except Exception as error: record_mcp_failure(error, stage='mcp')\n"
    assert not _violations(
        "from app.modules.automation.presentation.diagnostics import record_mcp_failure"
        + function,
        "fixture.py",
    )
    assert _violations(
        "from unrelated import record_mcp_failure" + function, "fixture.py"
    )
