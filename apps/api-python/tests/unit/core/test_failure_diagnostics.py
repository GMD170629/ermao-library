"""Observed causes and failure of diagnostic exits themselves."""
import errno
import json
import logging
import sqlite3
import subprocess
from unittest.mock import Mock
from urllib.error import URLError

import httpx
import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError

from app.core import exception_diagnostics as diagnostics
from app.core.logging_config import install_handler_fallback

LOGGER = logging.getLogger(__name__)


def test_url_error_reason_exposes_real_socket_cause():
    original = OSError(errno.ECONNREFUSED, "Connection refused")
    wrapper = RuntimeError("DOWNLOAD_FAILED")
    wrapper.__cause__ = URLError(original)
    result = diagnostics.format_exception_diagnostics(wrapper)
    assert result["rootCause"]["errno"] == errno.ECONNREFUSED
    assert result["rootCause"]["message"] == str(original)
    assert result["chain"][-1]["relationship"] == "reason"


def test_hidden_and_long_sql_parameters_survive_storage_projection():
    from app.modules.system.application.projections import serialize_system_event
    from app.modules.system.domain.events import prepare_event_metadata

    statement = "INSERT INTO books VALUES (?)"
    parameters = ("begin " + "x" * 80_000 + " end",)
    error = OperationalError(statement, parameters, sqlite3.OperationalError("database is locked"), hide_parameters=True)
    result = diagnostics.format_exception_diagnostics(error)
    stored = prepare_event_metadata({"diagnostics": result, "taskId": "import-123"})
    exported = serialize_system_event({"metadata": stored})
    operation = exported["metadata"]["diagnostics"]["databaseOperations"][0]
    assert operation["statement"] == statement
    assert operation["parameters"] == list(parameters)
    assert "taskId" not in exported["metadata"]


def test_long_transaction_trace_survives_event_metadata_projection():
    from app.modules.system.domain.events import prepare_event_metadata

    operation = {"statement": "INSERT INTO books VALUES (?)", "parameters": ["x" * 80_000]}
    error = OperationalError(operation["statement"], operation["parameters"], sqlite3.OperationalError("interrupted"))
    error.database_trace = {
        "transaction_id": "dbtx_probe",
        "statement_id": "dbstmt_probe",
        "transaction_statements": [operation],
    }
    trace = diagnostics.format_exception_diagnostics(error)["databaseTrace"]
    failure = prepare_event_metadata({"diagnostics": {"databaseTrace": trace}})
    slow = prepare_event_metadata({"databaseTrace": {"statements": [operation]}})
    assert failure["diagnostics"]["databaseTrace"]["transaction_statements"][0] == operation
    assert "transaction_id" not in failure["diagnostics"]["databaseTrace"]
    assert "statement_id" not in failure["diagnostics"]["databaseTrace"]
    assert slow["databaseTrace"]["statements"][0] == operation


def test_group_sql_and_each_root_survive_metadata_projection():
    from app.modules.system.domain.events import prepare_event_metadata

    sql = OperationalError("UPDATE books SET title = ?", ("x" * 80_000,), sqlite3.OperationalError("database is locked"))
    group = ExceptionGroup("parallel operations failed", [sql, OSError(errno.ENOSPC, "disk full")])
    snapshot = diagnostics.prepare_exception_diagnostic(LOGGER, "group.failed", group)
    stored = prepare_event_metadata(snapshot.metadata)["diagnostics"]
    assert stored["memberCount"] == 2
    assert stored["members"][1]["rootCause"]["errno"] == errno.ENOSPC
    assert stored["databaseOperations"][0]["parameters"] == ["x" * 80_000]


@pytest.mark.parametrize("number", [errno.EXDEV, errno.EACCES, errno.EROFS, errno.ENOSPC, errno.EIO])
def test_system_error_preserves_number_and_private_paths(number):
    underlying = OSError(number, "observed failure", "/private/books/title.epub")
    wrapper = RuntimeError("FILE_PUBLISH_FAILED")
    wrapper.__cause__ = underlying
    result = diagnostics.format_exception_diagnostics(wrapper)
    assert result["directException"]["type"] == "RuntimeError"
    assert result["directCause"]["errno"] == number
    assert result["rootCause"]["errorName"] == errno.errorcode[number]
    assert "observed failure" in result["rootCause"]["message"]
    assert "/private/books" in json.dumps(result)


def test_long_chain_keeps_outer_direct_and_root():
    current = OSError(errno.ENOSPC, "root disk full")
    for index in range(20):
        outer = RuntimeError(f"wrapper {index}")
        outer.__cause__ = current
        current = outer
    result = diagnostics.format_exception_diagnostics(current)
    assert result["chainTruncated"] is False
    assert result["chainLength"] == 21
    assert len(result["chain"]) == 21
    assert result["chain"][0]["message"] == "wrapper 19"
    assert result["directCause"]["message"] == "wrapper 18"
    assert any(item.get("errno") == errno.ENOSPC for item in result["chain"])


def test_nested_group_inside_cause_keeps_every_group_frame_and_note():
    leaf = ValueError("token=raw-leaf")
    leaf.add_note("raw note /private/path")
    try:
        raise ExceptionGroup("inner group", [leaf])
    except ExceptionGroup as inner:
        group = ExceptionGroup("outer group", [inner, OSError("second leaf")])
    wrapper = RuntimeError("wrapper")
    wrapper.__cause__ = group
    result = diagnostics.format_exception_diagnostics(wrapper)
    for value in ("wrapper", "outer group", "inner group", "token=raw-leaf", "raw note /private/path", "second leaf", "test_nested_group_inside_cause"):
        assert value in result["traceback"]
    assert result["chainLength"] == 5


def test_database_original_code_protocol_and_exit_status():
    original = sqlite3.OperationalError("database is locked")
    original.sqlite_errorcode = sqlite3.SQLITE_BUSY
    original.sqlite_errorname = "SQLITE_BUSY"
    db = OperationalError("SELECT * FROM t WHERE secret = ?", ("parameter-secret",), original)
    facts = diagnostics.format_exception_diagnostics(db)
    assert facts["rootCause"]["databaseCode"] == sqlite3.SQLITE_BUSY
    assert facts["directException"]["parameters"] == ["parameter-secret"]
    request = httpx.Request("GET", "https://example.test/?token=secret")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("upstream rejected", request=request, response=response)
    assert diagnostics.format_exception_diagnostics(error)["directException"]["protocolStatus"] == 503
    process = subprocess.CalledProcessError(17, ["cmd", "unlabelled-secret"], stderr="private-body")
    result = diagnostics.format_exception_diagnostics(process)
    assert result["directException"]["exitCode"] == 17
    assert "unlabelled-secret" in json.dumps(result)
    assert "private-body" in json.dumps(result)


def test_validation_records_original_error():
    class Input(BaseModel):
        count: int
    with pytest.raises(ValidationError) as caught:
        Input(count="body-secret")
    result = diagnostics.format_exception_diagnostics(caught.value)
    assert "body-secret" in json.dumps(result)
    assert "int_parsing" in result["message"]


def test_unknown_has_actual_type_and_no_invented_cause():
    result = diagnostics.format_exception_diagnostics(LookupError("unexpected state"))
    assert result["exceptionType"] == "LookupError"
    assert result["message"] == "unexpected state"
    assert result["causeStatus"] == "NOT_PROVIDED"
    assert result["directCause"] is None


def test_new_wrapper_keeps_its_stack_and_same_exception_is_deduplicated(caplog):
    error = OSError(errno.EIO, "read failed")
    first = diagnostics.prepare_exception_diagnostic(LOGGER, "read", error)
    wrapper = RuntimeError("unavailable")
    wrapper.__cause__ = error
    second = diagnostics.prepare_exception_diagnostic(LOGGER, "converted", wrapper)
    third = diagnostics.prepare_exception_diagnostic(LOGGER, "read", error)
    assert first is not second
    assert second.metadata["diagnostics"]["directCause"]["message"] == str(error)
    assert first is third
    assert first.diagnostic_id not in caplog.text


def test_deferred_scope_waits_for_transaction_owner():
    factory = Mock(side_effect=AssertionError("must not open log database yet"))
    with diagnostics.deferred_exception_persistence() as pending:  # noqa: SIM117 - deliberately exercise nested scope ownership
        with diagnostics.deferred_exception_persistence() as nested:
            snapshot = diagnostics.prepare_exception_diagnostic(LOGGER, "publish", OSError(errno.EROFS, "read only"))
            assert not diagnostics.persist_exception_diagnostic(LOGGER, snapshot, factory)
            assert nested is pending
    factory.assert_not_called()
    assert pending == [snapshot]
    assert "taskId" not in snapshot.metadata
    assert "step" not in snapshot.metadata


def test_file_write_failure_retains_original_and_outlet_error(monkeypatch, capsys):
    from app.modules.system.infrastructure import log_files
    def broken_lock():
        raise OSError(errno.EIO, "log file write failed")
    monkeypatch.setattr(log_files, "log_file_lock", broken_lock)
    snapshot = diagnostics.prepare_exception_diagnostic(LOGGER, "original", OSError(errno.ENOSPC, "disk full"))
    factory = Mock(side_effect=AssertionError("diagnostics must not open a database"))
    assert not diagnostics.persist_exception_diagnostic(LOGGER, snapshot, factory)
    factory.assert_not_called()
    output = capsys.readouterr().err
    assert "log file write failed" in output and "disk full" in output
    assert "Traceback" in output
    assert snapshot.metadata["diagnostics"]["rootCause"]["errno"] == errno.ENOSPC


def test_broken_logger_uses_stderr_with_original_and_logger_cause(capsys):
    logger = Mock()
    logger.log.side_effect = OSError(errno.ENOSPC, "log disk full")
    snapshot = diagnostics.prepare_exception_diagnostic(logger, "operation", ValueError("original error token=private-token"))
    output = capsys.readouterr().err
    assert snapshot.diagnostic_id not in output
    assert "original error" in output
    assert "log disk full" in output
    assert "private-token" in output


def test_standard_logging_swallowed_emit_failure_keeps_primary(capsys):
    handler = logging.StreamHandler(Mock())
    handler.stream.write.side_effect = OSError(errno.ENOSPC, "log disk full")
    install_handler_fallback(handler)
    logger = logging.getLogger("test.broken.handler")
    logger.handlers = [handler]
    logger.propagate = False
    try:
        snapshot = diagnostics.prepare_exception_diagnostic(logger, "operation", OSError(errno.EROFS, "read only"))
    finally:
        logger.handlers = []
        logger.propagate = True
    output = capsys.readouterr().err
    assert "log disk full" in output
    assert "read only" in output
    assert snapshot.diagnostic_id not in output


def test_formatter_failure_does_not_erase_original(monkeypatch, capsys):
    def broken(error):
        raise TypeError("formatter broken")
    monkeypatch.setattr(diagnostics, "format_exception_diagnostics", broken)
    snapshot = diagnostics.prepare_exception_diagnostic(LOGGER, "operation", OSError(errno.EIO, "disk error"))
    assert "disk error" in snapshot.message
    output = capsys.readouterr().err
    assert "formatter broken" in output
    assert "[Errno 5] disk error" in output


def test_broken_exception_str_records_original_type_and_formatter_failure(capsys):
    class BrokenMessage(Exception):
        def __str__(self):
            raise TypeError("message renderer broke password=private-value")
    result = diagnostics.format_exception_diagnostics(BrokenMessage())
    assert result["exceptionType"].endswith("BrokenMessage")
    assert "message unavailable" in result["message"]
    output = capsys.readouterr().err
    assert "message renderer broke" in output
    assert "TypeError" in output
    assert "private-value" in output


def test_validation_wrapper_preserves_original_input_value():
    class Input(BaseModel):
        count: int
    with pytest.raises(ValidationError) as caught:
        Input(count="secret-invalid-input")
    wrapper = RuntimeError(str(caught.value))
    wrapper.__cause__ = caught.value
    result = diagnostics.format_exception_diagnostics(wrapper)
    assert result["exceptionType"] == "RuntimeError"
    assert "int_parsing" in result["message"]
    assert "secret-invalid-input" in json.dumps(result)


def test_subprocess_diagnostics_preserve_localized_reason_and_spaced_paths():
    source = "/private/books/書名 with spaces/第一卷.epub"
    target = "/private/目的地 with spaces/第一卷.epub"
    child = subprocess.CalledProcessError(
        1, ["/bin/mv", source, target],
        stderr=f"mv: 无法将 {source} 移动至 {target}: 只读文件系统\n",
        output="private stdout body",
    )
    result = diagnostics.format_exception_diagnostics(child)
    facts = result["directException"]
    assert facts["exitCode"] == 1
    assert "只读文件系统" in facts["stderrSummary"]
    assert "只读文件系统" in result["traceback"]
    serialized = json.dumps(result, ensure_ascii=False)
    for private in ("書名", "目的地", "第一卷", "with spaces", "private stdout"):
        assert private in serialized
    filesystem = diagnostics.format_exception_diagnostics(OSError(errno.EROFS, "read only", source))
    assert "書名" in json.dumps(filesystem, ensure_ascii=False)
    assert "spaces" in json.dumps(filesystem)


def test_logging_formatter_failure_retains_original_and_secondary(monkeypatch, capsys):
    from app.core import logging_config
    original = OSError(errno.EROFS, "original read only", "/private/a.epub")
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "operation", (), (type(original), original, None))
    monkeypatch.setattr(logging_config, "format_exception_diagnostics", Mock(side_effect=TypeError("formatter failed")))
    stream = __import__("io").StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging_config.ExceptionFormatter("%(message)s"))
    logging_config.install_handler_fallback(handler)
    handler.emit(record)
    output = capsys.readouterr().err
    assert "original read only" in output
    assert "formatter failed" in output
    assert "/private/a.epub" in output


def test_plain_logger_exception_keeps_primary_when_handler_swallows_emit_failure(capsys):
    handler = logging.StreamHandler(Mock())
    handler.stream.write.side_effect = OSError(errno.ENOSPC, "log device full")
    install_handler_fallback(handler)
    logger = logging.getLogger("test.broken.plain.handler")
    original_handlers, original_propagate = logger.handlers, logger.propagate
    logger.handlers, logger.propagate = [handler], False
    try:
        try:
            raise OSError(errno.EROFS, "original filesystem read only", "/private/library/book.epub")
        except OSError:
            logger.exception("processing failed")
    finally:
        logger.handlers, logger.propagate = original_handlers, original_propagate
    output = capsys.readouterr().err
    assert "original filesystem read only" in output
    assert "log device full" in output
    assert "/private/library/book.epub" in output


def test_group_formatter_failure_retains_every_leaf(monkeypatch, capsys):
    group = ExceptionGroup("batch", [OSError(errno.EROFS, "read only"), ValueError("bad input")])
    monkeypatch.setattr(diagnostics, "format_exception_diagnostics", Mock(side_effect=TypeError("formatter failed")))
    snapshot = diagnostics.prepare_exception_diagnostic(LOGGER, "batch", group)
    assert snapshot.metadata["diagnostics"]["formattingErrorType"] == "TypeError"
    output = capsys.readouterr().err
    assert "formatter failed" in output
    assert "read only" in output
    assert "bad input" in output


def test_diagnostic_storage_failure_cannot_recursively_persist(monkeypatch, caplog):
    session = Mock()
    session.info = {}
    factory = Mock(return_value=session)
    nested = []
    def write(_event):
        error = ValueError("corrupt event retention setting")
        nested.append(diagnostics.record_exception(LOGGER, "settings.read_failed", error))
        return False
    monkeypatch.setattr("app.modules.system.infrastructure.log_files.append_log_event", write)
    diagnostics.configure_exception_storage(factory)
    try:
        parent = diagnostics.record_exception(LOGGER, "business.failed", OSError(errno.EIO, "original IO"))
    finally:
        diagnostics.reset_exception_storage(expected_factory=factory)
    factory.assert_not_called()
    session.commit.assert_not_called()
    assert len(nested) == 1
    record = next(record for record in caplog.records if "corrupt event retention setting" in record.message)
    assert not hasattr(record, "parent_diagnostic_id")
    assert parent not in record.message
    assert "corrupt event retention setting" in record.message
    assert diagnostics._persisting.get() is None


def test_factory_reset_does_not_clear_newer_app_factory():
    old_factory, new_factory = Mock(), Mock()
    diagnostics.configure_exception_storage(new_factory)
    try:
        diagnostics.reset_exception_storage(expected_factory=old_factory)
        assert diagnostics._session_factory is new_factory
        diagnostics.reset_exception_storage(expected_factory=new_factory)
        assert diagnostics._session_factory is None
    finally:
        diagnostics.reset_exception_storage()


def test_emergency_fallback_keeps_stream_failure_and_both_failed_exits_do_not_raise(monkeypatch):
    sink = Mock()
    sink.write.side_effect = OSError(errno.ENOSPC, "stderr stream full")
    raw_write = Mock()
    monkeypatch.setattr(diagnostics.sys, "stderr", sink)
    monkeypatch.setattr(diagnostics.os, "write", raw_write)
    original = OSError(errno.EIO, "original device failure")
    diagnostics.emergency_diagnostic("operation", original)
    output = raw_write.call_args.args[1].decode()
    assert "original device failure" in output
    assert "stderr stream full" in output
    raw_write.side_effect = OSError(errno.EBADF, "fd closed")
    diagnostics.emergency_diagnostic("operation", original)


def test_fd_fallback_keeps_all_members_of_deep_log_sink_failure(monkeypatch):
    members = [OSError(f"raw sink failure {index:03}") for index in range(30)]
    failure = ExceptionGroup("sink group", members)
    for depth in range(15):
        failure = ExceptionGroup(f"nested sink {depth}", [failure])
    sink = Mock()
    sink.write.side_effect = failure
    raw_write = Mock()
    monkeypatch.setattr(diagnostics.sys, "stderr", sink)
    monkeypatch.setattr(diagnostics.os, "write", raw_write)
    diagnostics.emergency_diagnostic("operation", RuntimeError("original operation failure"))
    output = raw_write.call_args.args[1].decode()
    assert "original operation failure" in output
    for member in members:
        assert str(member) in output
    assert "max_group_depth" not in output
    assert "and 15 more" not in output


def test_existing_root_handler_preserves_plain_logger_exception():
    import io

    from app.core.logging_config import configure_logging

    root = logging.getLogger()
    original_handlers, original_level = root.handlers, root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    root.handlers = [handler]
    try:
        configure_logging(force=True)
        try:
            raise OSError(errno.EIO, "device error password=private-secret", "/private/a b/book.epub")
        except OSError:
            logging.getLogger("plain.failure").exception("failed to process")
    finally:
        root.handlers, root.level = original_handlers, original_level
    assert handler.formatter is formatter
    output = stream.getvalue()
    assert "device error" in output
    assert "private-secret" in output
    assert "a b" in output
    assert "/private" in output


def test_immutable_exception_attachment_does_not_lose_diagnostic(caplog):
    class ImmutableError(Exception):
        def __setattr__(self, name, value):
            if name == diagnostics._DIAGNOSTIC_ATTR:
                raise AttributeError("immutable exception")
            super().__setattr__(name, value)
    snapshot = diagnostics.prepare_exception_diagnostic(LOGGER, "immutable", ImmutableError("original failure"))
    assert "original failure" in caplog.text
    assert snapshot.diagnostic_id not in caplog.text
    assert snapshot.message == "original failure"


def test_validation_context_does_not_replace_distinct_cleanup_cause():
    class Input(BaseModel):
        count: int
    with pytest.raises(ValidationError) as caught:
        Input(count="secret-invalid-input")
    cleanup = OSError(errno.EIO, "rollback device failed")
    cleanup.__context__ = caught.value
    result = diagnostics.format_exception_diagnostics(cleanup)
    assert "rollback device failed" in result["directException"]["message"]
    assert result["directException"]["errno"] == errno.EIO
    assert "secret-invalid-input" in json.dumps(result)


def test_database_sql_literals_survive_diagnostics_through_wrapper():
    original = sqlite3.OperationalError("no such table: absent")
    original.sqlite_errorcode = sqlite3.SQLITE_ERROR
    statement = "INSERT INTO absent VALUES ('inline-secret-one', 'value ] two',\n'inline-secret-three')"
    database = OperationalError(statement, {"extra": "bound-secret"}, original)
    wrapper = RuntimeError(str(database))
    wrapper.__cause__ = database
    result = diagnostics.format_exception_diagnostics(wrapper)
    serialized = json.dumps(result)
    for secret in ("inline-secret-one", "value ] two", "inline-secret-three", "bound-secret"):
        assert secret in serialized
    assert "no such table: absent" in serialized
    assert result["directCause"]["statement"] == statement
    assert result["directCause"]["parameters"] == {"extra": "bound-secret"}
    assert result["rootCause"]["databaseCode"] == sqlite3.SQLITE_ERROR
    assert statement in result["message"]


def test_rollback_context_does_not_become_cause_or_root():
    primary = OSError(errno.ENOSPC, "original publication device full")
    try:
        raise primary
    except OSError:
        try:
            raise OSError(errno.EIO, "rollback device read failed")
        except OSError as rollback:
            result = diagnostics.format_exception_diagnostics(rollback)
    assert result["directException"]["errno"] == errno.EIO
    assert result["directCause"] is None
    assert result["rootCause"]["errno"] == errno.EIO
    assert result["causeProvided"] is False
    assert result["causeStatus"] == "NOT_PROVIDED"
    assert result["contextProvided"] is True
    assert result["contexts"][0]["errno"] == errno.ENOSPC
    assert result["contexts"][0]["relationship"] == "context"
    assert result["contexts"][0]["parentIndex"] == 0
    assert "context, parent=0" in result["traceback"]


def test_explicit_wrapper_keeps_causal_root_separate_from_earlier_context():
    earlier = OSError(errno.ENOSPC, "earlier business error")
    rollback = OSError(errno.EIO, "rollback failed")
    rollback.__context__ = earlier
    wrapper = RuntimeError("compensation failed")
    wrapper.__cause__ = rollback
    wrapper.__context__ = earlier
    result = diagnostics.format_exception_diagnostics(wrapper)
    assert result["directCause"]["errno"] == errno.EIO
    assert result["directCause"]["relationship"] == "cause"
    assert result["rootCause"]["errno"] == errno.EIO
    assert result["causeStatus"] == "PROVIDED"
    assert result["contexts"][0]["errno"] == errno.ENOSPC
    assert len([entry for entry in result["chain"] if entry.get("errno") == errno.ENOSPC]) == 1


def test_database_orig_is_causal_but_distinct_context_is_history():
    original = sqlite3.OperationalError("database is locked")
    database = OperationalError("UPDATE t SET v = ?", ("private-value",), original)
    database.__context__ = ValueError("earlier operation rejected")
    result = diagnostics.format_exception_diagnostics(database)
    assert result["directCause"]["type"] == "sqlite3.OperationalError"
    assert result["directCause"]["relationship"] == "original"
    assert result["rootCause"]["message"] == "database is locked"
    assert result["contexts"][0]["type"] == "ValueError"
    assert result["directException"]["parameters"] == ["private-value"]


def test_long_causal_chain_preserves_middle_root_before_context():
    root = OSError(errno.EIO, "actual causal root")
    root.__context__ = OSError(errno.ENOSPC, "separate earlier event")
    current = root
    for index in range(20):
        wrapper = RuntimeError(f"wrapper {index}")
        wrapper.__cause__ = current
        current = wrapper
    result = diagnostics.format_exception_diagnostics(current)
    assert result["chainTruncated"] is False
    assert result["directException"]["message"] == "wrapper 19"
    assert result["directCause"]["message"] == "wrapper 18"
    assert result["rootCause"]["errno"] == errno.EIO
    assert any(item.get("errno") == errno.EIO for item in result["chain"])
    assert result["contexts"][0]["errno"] == errno.ENOSPC


def test_group_member_is_not_falsely_reported_as_aggregate_cause():
    earlier = OSError(errno.ENOSPC, "previous operation failed")
    rollback = OSError(errno.EIO, "rollback failed")
    rollback.__context__ = earlier
    group = ExceptionGroup("independent failures", [rollback, ValueError("another operation failed")])
    snapshot = diagnostics.prepare_exception_diagnostic(LOGGER, "group.failed", group)
    aggregate = snapshot.metadata["diagnostics"]
    assert aggregate["directException"]["type"] == "ExceptionGroup"
    assert aggregate["directCause"] is None
    assert aggregate["causeStatus"] == "NOT_PROVIDED"
    assert aggregate["rootCause"]["type"] == "ExceptionGroup"
    member = aggregate["members"][0]
    assert member["rootCause"]["errno"] == errno.EIO
    assert member["directCause"] is None
    assert member["contexts"][0]["errno"] == errno.ENOSPC
