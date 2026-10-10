from tests.support.log_events import find_log

"""Official SDK errors keep their business code; authorized logs retain raw causes."""

import asyncio
import errno
import logging
import socket

import httpx2
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import sessionmaker

from app.main import create_app
from app.modules.automation.infrastructure.runtime import DatabaseAutomationRuntime
from tests.integration.modules.automation.test_mcp_catalog import seed


def test_official_sdk_failure_to_diagnostic_query(
    db_session, test_settings, monkeypatch, caplog
):
    grant = seed(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    app = create_app(test_settings, session_factory=factory)

    def failure_during_handling():
        try:
            raise PermissionError(errno.EACCES, "original operation denied", "/private/library/book.epub")
        except PermissionError:
            try:
                raise RuntimeError("rollback handling failed")
            except RuntimeError as error:
                return error

    contextual_failure = failure_during_handling()

    async def exercise():
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        host = uvicorn.Server(
            uvicorn.Config(app, log_level="error", lifespan="off", ws="none")
        )
        task = asyncio.create_task(host.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not host.started:
                    assert not task.done()
                    await asyncio.sleep(0.01)
            async with (
                httpx2.AsyncClient(
                    headers={
                        "Authorization": "Bearer " + grant.token,
                        "X-Request-Id": "mcp-real-failure",
                    }
                ) as http,
                Client(
                    streamable_http_client(
                        f"http://127.0.0.1:{port}/api/mcp", http_client=http
                    ),
                    read_timeout_seconds=5,
                ) as client,
            ):
                for failure, expected in (
                    (
                        ValueError("program defect token=must-remain-secret"),
                        "ValueError",
                    ),
                    (
                        PermissionError(
                            errno.EACCES,
                            "Permission denied",
                            "/private/library/book.epub",
                        ),
                        "PermissionError",
                    ),
                    (contextual_failure, "RuntimeError"),
                ):

                    def fail_invoke(*_args, observed=failure):
                        raise observed

                    with monkeypatch.context() as patch:
                        patch.setattr(DatabaseAutomationRuntime, "invoke", fail_invoke)
                        result = await client.call_tool("get_context", {})
                    assert result.is_error
                    text = result.content[0].text
                    assert "INTERNAL_ERROR" in text
                    assert "INVALID_ARGUMENT" not in text
                    assert "must-remain-secret" not in text
                    assert "diagnostic_id=" not in text
                    async with asyncio.timeout(5):
                        while True:
                            found = await client.call_tool(
                                "list_system_logs", {"search": "automation.request_failed"}
                            )
                            assert not found.is_error
                            events = [event for event in found.structured_content["events"] if event["action"] == "automation.request_failed" and str(failure) in event["diagnostics"]["traceback"]]
                            if events:
                                break
                            await asyncio.sleep(0.01)
                    assert len(events) == 1
                    assert events[0]["diagnostics"]["rootCause"]["type"] == expected
                    summary = events[0]["diagnostics"]
                    root = summary["rootCause"]
                    assert root["relationship"] == "cause"
                    assert isinstance(root["chainIndex"], int)
                    assert isinstance(root["parentIndex"], int)
                    assert isinstance(summary["causeProvided"], bool)
                    assert isinstance(summary["contextProvided"], bool)
                    assert isinstance(summary["contextsTruncated"], bool)
                    for name in ("directException", "directCause", "rootCause"):
                        assert "location" in summary.get(name, {})
                    assert str(failure) in summary["traceback"]
                    if failure is contextual_failure:
                        assert summary["contextProvided"] is True
                        assert summary["contextsTruncated"] is False
                        context = next(item for item in summary["contexts"] if item["type"] == "PermissionError")
                        assert context["relationship"] == "context"
                        assert context["parentIndex"] == root["chainIndex"]
                        assert context["errno"] == errno.EACCES
                        assert "location" in context
                        assert root["message"] == "rollback handling failed"
                    assert "correlation" not in events[0]
                    with factory() as _db:
                        persisted = find_log(events[0]['id'])
                        assert persisted is not None
                        assert (
                            persisted.metadata_json["diagnostics"]["rootCause"]["type"]
                            == expected
                        )
                invalid = await client.call_tool("get_books", {"book_ids": []})
                assert invalid.is_error
                assert "INVALID_ARGUMENT" in invalid.content[0].text
                assert "diagnostic_id=" not in invalid.content[0].text
                invalid_sensitive = await client.call_tool(
                    "get_books", {"book_ids": "PRIVATE-REQUEST-BODY-SENTINEL"}
                )
                assert invalid_sensitive.is_error
                assert "PRIVATE-REQUEST-BODY-SENTINEL" not in str(invalid_sensitive)
        finally:
            host.should_exit = True
            await task
            listener.close()

    with caplog.at_level(logging.WARNING):
        asyncio.run(exercise())
    assert "ValueError: program defect" in caplog.text
    assert "PermissionError: [Errno 13] Permission denied" in caplog.text
    assert "must-remain-secret" in caplog.text
    assert "/private/library" in caplog.text
    assert "PRIVATE-REQUEST-BODY-SENTINEL" in caplog.text
