from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest

from app.api.diagnostics_middleware import DiagnosticBoundaryMiddleware
from app.core.exception_diagnostics import (
    format_exception_diagnostics,
    install_loop_exception_handler,
    prepare_exception_diagnostic,
    sanitize_diagnostic_text,
)
from app.core.logging_config import ContextFormatter, configure_logging
from app.modules.system.application.projections import (
    serialize_system_event,
    summarize_diagnostic_metadata,
)
from app.modules.system.domain.events import (
    prepare_event_metadata,
    truncate_event_message,
)

LOGGER = logging.getLogger("tests.diagnostics")


def test_sanitize_redacts_credentials_and_sql_parameters() -> None:
    text = (
        "Authorization: Bearer abc123\n"
        "Cookie: shuku_session=deadbeef\n"
        "password=hunter2 token=xyz api_key=sekret\n"
        "[parameters: ('a@example.com', 'hunter2')]\n"
        "(Background on this error at: https://sqlalche.me/e/20/abc)"
    )

    cleaned = sanitize_diagnostic_text(text)

    assert "abc123" not in cleaned
    assert "deadbeef" not in cleaned
    assert "hunter2" not in cleaned
    assert "xyz" not in cleaned
    assert "sekret" not in cleaned
    assert "[parameters: [redacted]]" in cleaned
    assert "Background on this error" not in cleaned


def _raise_marker() -> None:
    raise ValueError("boom-marker")


def test_format_uses_original_traceback_not_current_stack() -> None:
    try:
        _raise_marker()
    except ValueError as error:
        diagnostics = format_exception_diagnostics(error)

    assert diagnostics["exceptionType"].endswith("ValueError")
    assert diagnostics["message"] == "boom-marker"
    assert "_raise_marker" in diagnostics["traceback"]
    assert "ValueError: boom-marker" in diagnostics["traceback"]
    # The recording frame must not be presented as the original failure.
    assert "format_exception_diagnostics" not in diagnostics["traceback"]
    assert diagnostics["location"]
    assert "test_exception_diagnostics.py" in diagnostics["location"]


def test_format_preserves_exception_chain() -> None:
    def _outer() -> None:
        try:
            raise ValueError("root-cause")
        except ValueError as root:
            raise RuntimeError("outer-error") from root

    try:
        _outer()
    except RuntimeError as error:
        diagnostics = format_exception_diagnostics(error)

    chained = [entry["message"] for entry in diagnostics["chain"]]
    assert chained[0] == "outer-error"
    assert "root-cause" in chained
    assert diagnostics["chain"][0]["type"].endswith("RuntimeError")


def test_long_traceback_is_explicitly_truncated_and_keeps_tail() -> None:
    try:
        raise RuntimeError("HEAD-" + ("z" * 5_000) + "-TAIL")
    except RuntimeError as error:
        diagnostics = format_exception_diagnostics(error, max_traceback_chars=1_500)

    assert diagnostics["truncated"] is True
    assert "[diagnostic truncated]" in diagnostics["traceback"]
    assert diagnostics["traceback"].startswith("Traceback")
    assert diagnostics["traceback"].rstrip().endswith("-TAIL")


def test_prepare_event_metadata_preserves_tail_when_over_limit() -> None:
    metadata = {
        "diagnostics": {
            "id": "diag_1",
            "exceptionType": "builtins.RuntimeError",
            "message": "root cause",
            "location": "app/x.py:10",
            "traceback": "x" * 80_000,
        },
        "context": "y" * 80_000,
    }

    prepared = prepare_event_metadata(metadata)

    assert prepared["truncated"] is True
    assert prepared["originalChars"] > 64 * 1024
    assert prepared["preview"]
    assert prepared["tail"]
    assert prepared["diagnostics"]["exceptionType"] == "builtins.RuntimeError"
    assert prepared["diagnostics"]["location"] == "app/x.py:10"


def test_truncate_event_message_keeps_both_ends() -> None:
    text = "开头" + ("中" * 5_000) + "结尾标记"

    truncated = truncate_event_message(text)

    assert len(truncated) <= 4_000
    assert truncated.startswith("开头")
    assert truncated.endswith("结尾标记")
    assert "[message truncated]" in truncated


def test_serialize_system_event_is_backward_compatible_with_legacy_metadata() -> None:
    serialized = serialize_system_event(
        {
            "id": "old-1",
            "level": "error",
            "source": "import",
            "actorType": "system",
            "action": "scan.failed",
            "message": "旧日志",
            "metadata": None,
            "createdAt": 1_700_000_000_000,
        }
    )

    assert serialized["metadata"] == {}
    assert serialized["message"] == "旧日志"


def test_sanitize_redacts_quoted_json_and_python_dict_credentials() -> None:
    text = (
        "{\"password\": \"json-secret\", \"apiKey\": \"key-secret\"}\n"
        "{'refresh_token': 'dict-secret', 'nested': {'token': 'nested-secret'}}\n"
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
    )

    cleaned = sanitize_diagnostic_text(text)

    for secret in ("json-secret", "key-secret", "dict-secret", "nested-secret"):
        assert secret not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned


def test_running_log_redacts_secrets_and_keeps_id_and_context() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ContextFormatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("tests.diagnostics.handler")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    def _raise_secret() -> None:
        raise RuntimeError(
            'password="s3cr3t-value" token=bare-token '
            '{"apiKey": "json-secret"} [parameters: ("p@ss",)]'
        )

    try:
        _raise_secret()
    except RuntimeError as error:
        prepare_exception_diagnostic(
            logger,
            "handler.test_failed",
            error,
            context={"stage": "unit", "task_id": "task-7"},
        )
    finally:
        logger.handlers = []

    output = stream.getvalue()
    assert "handler.test_failed" in output
    assert "diag_" in output
    assert "stage=unit" in output
    assert "task_id=task-7" in output
    assert "_raise_secret" in output
    for secret in ("s3cr3t-value", "bare-token", "json-secret", "p@ss"):
        assert secret not in output


def test_configure_logging_preserves_existing_handler_and_emits_context() -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    stream = io.StringIO()
    existing = logging.StreamHandler(stream)
    existing.setFormatter(logging.Formatter("%(message)s"))
    root.handlers = [existing]
    root.setLevel(logging.WARNING)
    try:
        configure_logging(force=True)
        assert existing in root.handlers

        try:
            raise RuntimeError('password="existing-secret"')
        except RuntimeError as error:
            prepare_exception_diagnostic(
                logging.getLogger("ermao.test.existing_handler"),
                "existing.handler.test",
                error,
                context={"stage": "unit", "task_id": "task-9"},
            )
        output = stream.getvalue()
        assert existing.stream is stream
        assert "existing.handler.test" in output
        assert "diagnostic_id=diag_" in output
        assert "stage=unit" in output
        assert "task_id=task-9" in output
        assert "existing-secret" not in output
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


def test_chain_and_context_secrets_are_redacted() -> None:
    def _inner() -> None:
        raise ValueError("token=chain-secret")

    def _outer() -> None:
        try:
            _inner()
        except ValueError as root:
            raise RuntimeError("outer failure") from root

    try:
        _outer()
    except RuntimeError as error:
        diagnostics = format_exception_diagnostics(error)

    blob = diagnostics["traceback"] + json.dumps(diagnostics["chain"])
    assert "chain-secret" not in blob
    assert "outer failure" in diagnostics["traceback"]


class _FakeLoop:
    def __init__(self) -> None:
        self.handler = None
        self.default_calls: list[dict] = []

    def set_exception_handler(self, handler) -> None:
        self.handler = handler

    def get_exception_handler(self):
        return None

    def default_exception_handler(self, context: dict) -> None:
        self.default_calls.append(context)


def test_loop_handler_records_without_default_double_print(
    caplog: pytest.LogCaptureFixture,
) -> None:
    loop = _FakeLoop()
    install_loop_exception_handler(loop)
    try:
        raise ValueError("loop boom")
    except ValueError as error:
        with caplog.at_level(logging.ERROR, logger="ermao.unhandled"):
            loop.handler(loop, {"exception": error})

    assert "loop boom" in caplog.text
    assert loop.default_calls == []


def test_loop_handler_skips_normal_cancellation() -> None:
    loop = _FakeLoop()
    install_loop_exception_handler(loop)
    loop.handler(loop, {"exception": asyncio.CancelledError()})
    assert len(loop.default_calls) == 1


def test_exception_group_reuses_leaf_diagnostic_id() -> None:
    try:
        raise ValueError("leaf failure")
    except ValueError as leaf:
        inner = prepare_exception_diagnostic(LOGGER, "leaf.failure", leaf)
        group = ExceptionGroup("group failure", [leaf])
        outer = prepare_exception_diagnostic(LOGGER, "group.failure", group)

    assert outer is inner
    assert outer.diagnostic_id == inner.diagnostic_id


def test_json_metadata_payload_contains_no_secrets() -> None:
    try:
        raise RuntimeError('password="meta-secret" token=meta-token')
    except RuntimeError as error:
        snapshot = prepare_exception_diagnostic(
            LOGGER, "metadata.test", error, context={"token_secret": "ctx-secret"}
        )

    serialized = json.dumps(snapshot.metadata, ensure_ascii=False)
    assert "meta-secret" not in serialized
    assert "meta-token" not in serialized
    # Unknown context keys are not persisted at all.
    assert "ctx-secret" not in serialized
    assert snapshot.metadata["diagnostics"]["exceptionType"].endswith("RuntimeError")


def _asgi_scope() -> dict:
    return {"type": "http", "method": "GET", "path": "/stream", "headers": []}


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def test_inner_asgi_boundary_sends_correlation_json_before_response_start() -> None:
    sent: list[dict] = []

    async def app(scope, receive, send):
        raise RuntimeError("early route failure")

    async def send(message):
        sent.append(message)

    middleware = DiagnosticBoundaryMiddleware(
        app, session_factory=None, respond_with_json=True
    )
    asyncio.run(middleware(_asgi_scope(), _empty_receive, send))

    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 500
    headers = dict(starts[0]["headers"])
    assert headers[b"x-error-id"].startswith(b"diag_")
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    ).decode("utf-8")
    assert "INTERNAL_ERROR" in body
    assert "early route failure" not in body


def test_outer_asgi_boundary_re_raises_without_sending_a_response() -> None:
    sent: list[dict] = []

    async def app(scope, receive, send):
        raise RuntimeError("boundary database failure")

    async def send(message):
        sent.append(message)

    middleware = DiagnosticBoundaryMiddleware(
        app, session_factory=None, respond_with_json=False
    )
    with pytest.raises(RuntimeError, match="boundary database failure"):
        asyncio.run(middleware(_asgi_scope(), _empty_receive, send))
    assert sent == []


def test_asgi_boundary_records_after_response_started_without_second_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send(
            {"type": "http.response.body", "body": b"partial", "more_body": True}
        )
        raise RuntimeError("post-start failure token=leaky-token")

    async def send(message):
        sent.append(message)

    middleware = DiagnosticBoundaryMiddleware(
        app, session_factory=None, respond_with_json=True
    )
    with (
        caplog.at_level(logging.ERROR, logger="ermao.api_diagnostics"),
        pytest.raises(RuntimeError, match="post-start failure"),
    ):
        asyncio.run(middleware(_asgi_scope(), _empty_receive, send))

    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
    ]
    assert sum(message["type"] == "http.response.start" for message in sent) == 1
    assert "post-start failure" in caplog.text
    assert "leaky-token" not in caplog.text


def test_list_projection_omits_traceback_but_keeps_summary() -> None:
    metadata = {
        "stage": "scan",
        "diagnostics": {
            "exceptionType": "builtins.OSError",
            "traceback": "Traceback ... very long",
            "chain": [{"type": "builtins.OSError", "message": "disk"}],
            "location": "app/x.py:1",
        },
    }

    summary = summarize_diagnostic_metadata(metadata)

    assert summary["stage"] == "scan"
    assert summary["diagnostics"]["exceptionType"] == "builtins.OSError"
    assert summary["diagnostics"]["location"] == "app/x.py:1"
    assert "traceback" not in summary["diagnostics"]
    assert "chain" not in summary["diagnostics"]
