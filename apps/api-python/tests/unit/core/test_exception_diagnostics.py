from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from uvicorn.logging import AccessFormatter

from app.api.diagnostics_middleware import DiagnosticBoundaryMiddleware
from app.core.exception_diagnostics import (
    format_exception_diagnostics,
    install_loop_exception_handler,
    prepare_exception_diagnostic,
    sanitize_diagnostic_text,
)
from app.core.logging_config import (
    ContextFormatter,
    configure_logging,
    install_uvicorn_sanitizer,
)
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


def test_sanitize_redacts_cookie_after_exception_prefix() -> None:
    cleaned = sanitize_diagnostic_text(
        "RuntimeError: Cookie: shuku_session=runtime-cookie-secret"
    )

    assert "runtime-cookie-secret" not in cleaned
    assert "RuntimeError: Cookie:" in cleaned


def test_sanitize_redacts_json_and_dict_cookie_and_authorization() -> None:
    text = (
        '{"Cookie": "shuku_session=json-cookie", '
        '"Set-Cookie": "shuku_session=json-set-cookie", '
        '"Authorization": "Basic json-basic-credential"}\n'
        "{'cookie': 'shuku_session=dict-cookie', "
        "'authorization': 'Bearer dict-bearer-credential'}"
    )

    cleaned = sanitize_diagnostic_text(text)

    for secret in (
        "json-cookie",
        "json-set-cookie",
        "json-basic-credential",
        "dict-cookie",
        "dict-bearer-credential",
    ):
        assert secret not in cleaned
    assert '"Cookie"' in cleaned
    assert "'authorization'" in cleaned


def test_sanitize_redacts_basic_and_bearer_authorization() -> None:
    text = (
        "RuntimeError: Authorization: Basic dXNlcjpwYXNzd29yZA==\n"
        "ValueError: Authorization: Bearer header.payload.signature"
    )

    cleaned = sanitize_diagnostic_text(text)

    assert "dXNlcjpwYXNzd29yZA" not in cleaned
    assert "header.payload.signature" not in cleaned
    assert "RuntimeError:" in cleaned


def test_sanitize_redacts_full_sql_parameters_with_brackets_and_newlines() -> None:
    text = (
        "[parameters: (('a]b', 'sql-secret'), [1, 2, 3])]\n"
        "[parameters: (1,\n  'sql-multiline-secret')]\n"
        "trailing-safe-value"
    )

    cleaned = sanitize_diagnostic_text(text)

    assert "sql-secret" not in cleaned
    assert "sql-multiline-secret" not in cleaned
    assert cleaned.count("[parameters: [redacted]]") == 2
    assert "trailing-safe-value" in cleaned


def test_redact_sql_parameters_handles_escaped_quotes_and_multiple_segments() -> None:
    text = (
        "[parameters: (1, 'a\\']b\"c', 'must-not-leak-3f9a')]\n"
        "[parameters: (\"x\\\"y]z\", 'other-secret')]\n"
        "safe-tail"
    )

    cleaned = sanitize_diagnostic_text(text)

    assert "must-not-leak-3f9a" not in cleaned
    assert "other-secret" not in cleaned
    assert "a']b" not in cleaned
    assert cleaned.count("[parameters: [redacted]]") == 2
    assert "safe-tail" in cleaned


def test_redact_sql_parameters_conservative_when_unclosed() -> None:
    cleaned = sanitize_diagnostic_text(
        "[parameters: (1, 'unclosed-secret') trailing-sensitive"
    )

    assert "unclosed-secret" not in cleaned
    assert "trailing-sensitive" not in cleaned
    assert "[parameters: [redacted]]" in cleaned


def test_real_sqlalchemy_exception_parameters_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tricky = "a']b\"c"
    sensitive = "must-not-leak-3f9a"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT, b TEXT)"
        )

    with pytest.raises(IntegrityError) as excinfo, engine.begin() as connection:
        statement = text(
            "INSERT INTO t (id, a, b) VALUES (:id, :a, :b)"
        )
        connection.execute(
            statement, {"id": 1, "a": "safe", "b": "safe"}
        )
        connection.execute(
            statement, {"id": 1, "a": tricky, "b": sensitive}
        )

    error = excinfo.value
    # The raw database exception genuinely contains the parameters.
    assert sensitive in str(error)

    diagnostics = format_exception_diagnostics(error)
    blob = (
        diagnostics["message"]
        + diagnostics["traceback"]
        + json.dumps(diagnostics["chain"], ensure_ascii=False)
    )
    assert sensitive not in blob
    assert "a']b" not in blob
    assert diagnostics["exceptionType"].endswith("IntegrityError")
    assert "UNIQUE constraint failed" in diagnostics["message"]
    assert diagnostics["traceback"]

    with caplog.at_level(logging.ERROR):
        snapshot = prepare_exception_diagnostic(LOGGER, "sql.integrity", error)
    assert sensitive not in json.dumps(snapshot.metadata, ensure_ascii=False)
    assert sensitive not in caplog.text
    assert snapshot.message == diagnostics["message"]


def test_secrets_absent_from_message_traceback_chain_and_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _inner() -> None:
        raise ValueError("cause Cookie: shuku_session=cause-cookie-secret")

    def _outer() -> None:
        try:
            _inner()
        except ValueError as root:
            raise RuntimeError(
                "outer Authorization: Basic b3V0ZXI6b3V0ZXItc2VjcmV0"
            ) from root

    try:
        _outer()
    except RuntimeError as error:
        with caplog.at_level(logging.ERROR):
            snapshot = prepare_exception_diagnostic(LOGGER, "embedded.secrets", error)

    diagnostics = snapshot.metadata["diagnostics"]
    persisted_blob = json.dumps(snapshot.metadata, ensure_ascii=False)
    for secret in ("cause-cookie-secret", "b3V0ZXI6b3V0ZXItc2VjcmV0"):
        assert secret not in diagnostics["message"]
        assert secret not in diagnostics["traceback"]
        assert secret not in json.dumps(diagnostics["chain"], ensure_ascii=False)
        assert secret not in persisted_blob
        assert secret not in caplog.text
    assert diagnostics["message"].startswith("outer Authorization:")
    assert diagnostics["chain"]


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


def _new_error(error_type, message: str) -> BaseException:
    try:
        raise error_type(message)
    except error_type as error:
        return error


def test_exception_group_reuses_leaf_diagnostic_id() -> None:
    leaf = _new_error(ValueError, "leaf failure")
    inner = prepare_exception_diagnostic(LOGGER, "leaf.failure", leaf)
    group = ExceptionGroup("group failure", [leaf])
    outer = prepare_exception_diagnostic(LOGGER, "group.failure", group)

    assert outer is inner
    assert outer.diagnostic_id == inner.diagnostic_id
    # Repeated propagation of the same group must not create a second event.
    assert (
        prepare_exception_diagnostic(LOGGER, "group.failure.again", group) is inner
    )


def test_exception_group_records_unrecorded_member_with_recorded_sibling() -> None:
    recorded_leaf = _new_error(ValueError, "A token=alpha-secret")
    recorded_snapshot = prepare_exception_diagnostic(
        LOGGER, "leaf.recorded", recorded_leaf
    )
    unrecorded_leaf = _new_error(RuntimeError, "B token=beta-secret")
    group = ExceptionGroup("group", [recorded_leaf, unrecorded_leaf])

    snapshot = prepare_exception_diagnostic(LOGGER, "group", group)

    assert snapshot is not recorded_snapshot
    diagnostics = snapshot.metadata["diagnostics"]
    assert diagnostics["memberCount"] == 2
    assert len(diagnostics["members"]) == 1
    assert diagnostics["members"][0]["exceptionType"].endswith("RuntimeError")
    assert diagnostics["relatedIds"] == [recorded_snapshot.diagnostic_id]
    assert "beta-secret" not in json.dumps(snapshot.metadata, ensure_ascii=False)
    # The previously unrecorded leaf now carries the aggregate diagnostic.
    assert (
        prepare_exception_diagnostic(LOGGER, "leaf.later", unrecorded_leaf)
        is snapshot
    )


def test_nested_exception_groups_diagnose_every_leaf() -> None:
    leaf_c = _new_error(ValueError, "C token=gamma-secret")
    leaf_d = _new_error(RuntimeError, "D token=delta-secret")
    nested = ExceptionGroup(
        "outer",
        [ExceptionGroup("inner", [leaf_c, leaf_d])],
    )

    snapshot = prepare_exception_diagnostic(LOGGER, "nested.group", nested)

    diagnostics = snapshot.metadata["diagnostics"]
    assert diagnostics["memberCount"] == 2
    assert len(diagnostics["members"]) == 2
    types = {member["exceptionType"] for member in diagnostics["members"]}
    assert any(item.endswith("ValueError") for item in types)
    assert any(item.endswith("RuntimeError") for item in types)
    blob = json.dumps(snapshot.metadata, ensure_ascii=False)
    assert "gamma-secret" not in blob
    assert "delta-secret" not in blob
    # Each leaf now resolves to the aggregate diagnostic.
    assert prepare_exception_diagnostic(LOGGER, "leaf.c", leaf_c) is snapshot
    assert prepare_exception_diagnostic(LOGGER, "leaf.d", leaf_d) is snapshot


def test_nested_group_does_not_rerecord_recorded_inner_group() -> None:
    leaf_c = _new_error(ValueError, "C token=gamma-secret")
    leaf_d = _new_error(RuntimeError, "D token=delta-secret")
    inner_group = ExceptionGroup("inner", [leaf_c, leaf_d])
    inner_snapshot = prepare_exception_diagnostic(LOGGER, "inner.group", inner_group)

    leaf_e = _new_error(KeyError, "E token=epsilon-secret")
    outer_group = ExceptionGroup("outer", [inner_group, leaf_e])
    snapshot = prepare_exception_diagnostic(LOGGER, "outer.group", outer_group)

    assert snapshot is not inner_snapshot
    diagnostics = snapshot.metadata["diagnostics"]
    assert diagnostics["relatedIds"] == [inner_snapshot.diagnostic_id]
    assert len(diagnostics["members"]) == 1
    assert diagnostics["members"][0]["exceptionType"].endswith("KeyError")
    assert prepare_exception_diagnostic(LOGGER, "leaf.e", leaf_e) is snapshot
    # The already recorded inner group is not expanded into new events.
    assert (
        prepare_exception_diagnostic(LOGGER, "inner.again", inner_group)
        is inner_snapshot
    )


def test_distinct_groups_are_not_merged() -> None:
    first = prepare_exception_diagnostic(
        LOGGER,
        "group.one",
        ExceptionGroup("one", [_new_error(ValueError, "first attempt")]),
    )
    second = prepare_exception_diagnostic(
        LOGGER,
        "group.two",
        ExceptionGroup("two", [_new_error(ValueError, "first attempt")]),
    )

    assert first.diagnostic_id != second.diagnostic_id


def test_uvicorn_sanitizer_redacts_exc_info_and_message() -> None:
    logger = logging.getLogger("uvicorn.error")
    original_handlers = logger.handlers[:]
    original_filters = logger.filters[:]
    original_propagate = logger.propagate
    original_level = logger.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    try:
        install_uvicorn_sanitizer()
        try:
            raise RuntimeError("Cookie: shuku_session=uvicorn-unit-secret")
        except RuntimeError:
            logger.exception("Exception in ASGI application")
    finally:
        logger.handlers = original_handlers
        logger.filters = original_filters
        logger.propagate = original_propagate
        logger.setLevel(original_level)

    output = stream.getvalue()
    assert "Exception in ASGI application" in output
    assert "RuntimeError" in output
    assert "uvicorn-unit-secret" not in output


def test_uvicorn_sanitizer_preserves_access_formatter_args() -> None:
    logger = logging.getLogger("uvicorn.access")
    original_handlers = logger.handlers[:]
    original_filters = logger.filters[:]
    original_propagate = logger.propagate
    original_level = logger.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s')
    )
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        install_uvicorn_sanitizer()
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            "/ok?token=unit-query-secret",
            "1.1",
            200,
        )
    finally:
        logger.handlers = original_handlers
        logger.filters = original_filters
        logger.propagate = original_propagate
        logger.setLevel(original_level)

    output = stream.getvalue()
    assert "127.0.0.1:5000" in output
    assert '"GET /ok?token=[redacted] HTTP/1.1"' in output
    assert "200" in output
    assert "unit-query-secret" not in output


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
