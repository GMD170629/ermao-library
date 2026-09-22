"""Converted HTTP failures remain traceable after transaction cleanup."""

import asyncio
import errno
import logging
import socket
from typing import Annotated

import httpx
import pytest
import uvicorn
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.http import MessageError
from app.contracts.http_errors import BasicConflictError
from app.db.session import get_db
from app.main import create_app
from app.models.settings import SystemEvent, SystemSetting
from app.modules.system.infrastructure.events import list_system_events_page
from app.schemas.responses import fail


def test_http_conversion_validation_and_rejection_capture_causes(
    db_session, test_settings, caplog
):
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    app = create_app(test_settings, session_factory=factory)

    @app.get("/diagnostic-conversion")
    def converted(db: Annotated[Session, Depends(get_db)]):
        db.add(SystemSetting(key="diagnostic-uncommitted", value="true"))
        db.flush()
        try:
            raise OSError(
                errno.EROFS, "Read-only file system", "/private/library/book.epub"
            )
        except OSError:
            return fail("操作失败", status_code=500, code="FILE_PUBLISH_FAILED")

    @app.get("/diagnostic-conflict")
    def conflict():
        raise BasicConflictError(
            MessageError(message="Revision does not match", code="REVISION_CONFLICT")
        )

    @app.get("/diagnostic-validation")
    def validation(count: int):
        return {"count": count}

    with caplog.at_level(logging.WARNING), TestClient(app) as client:
        converted_response = client.get(
            "/diagnostic-conversion", headers={"X-Request-Id": "request-original-io"}
        )
        conflict_response = client.get("/diagnostic-conflict")
        validation_response = client.get("/diagnostic-validation?count=not-an-integer")
    assert [
        r.status_code
        for r in (converted_response, conflict_response, validation_response)
    ] == [500, 409, 422]
    with factory() as db:
        assert db.get(SystemSetting, "diagnostic-uncommitted") is None
        for response in (converted_response, conflict_response, validation_response):
            event = db.get(SystemEvent, response.headers["X-Error-Id"])
            assert event is not None
            assert event.metadata_json["requestId"] == response.headers["X-Request-Id"]
        event = db.get(SystemEvent, converted_response.headers["X-Error-Id"])
        diagnostic = event.metadata_json["diagnostics"]
        assert diagnostic["exceptionType"] == "OSError"
        assert diagnostic["directException"]["errno"] == errno.EROFS
        assert diagnostic["directException"]["errorName"] == "EROFS"
        assert "Read-only file system" in diagnostic["message"]
        assert "/private/library" not in str(event.metadata_json)
        found = list_system_events_page(
            db, page=1, page_size=20, search="request-original-io"
        )
        assert found.total == 1
        assert found.events[0]["id"] == event.id
        assert (
            len(db.scalars(select(SystemEvent).where(SystemEvent.id == event.id)).all())
            == 1
        )
    assert "[Errno 30] Read-only file system" in caplog.text


def test_loopback_http_failure_can_be_queried_by_diagnostic_and_request_id(
    db_session, test_settings, caplog
):
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    app = create_app(test_settings, session_factory=factory)

    @app.get("/diagnostic-real-http")
    def disk_failure():
        raise OSError(
            errno.ENOSPC, "No space left on device", "/private/library/book.epub"
        )

    async def exercise():
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", lifespan="off", ws="none")
        )
        running = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    assert not running.done()
                    await asyncio.sleep(0.01)
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://127.0.0.1:{port}/diagnostic-real-http",
                    headers={"X-Request-Id": "real-http-disk-failure"},
                )
            return response
        finally:
            server.should_exit = True
            await running
            listener.close()

    response = asyncio.run(exercise())
    assert response.status_code == 500
    diagnostic_id = response.headers["X-Error-Id"]
    assert "/private/library" not in response.text
    assert "No space" not in response.text
    with factory() as db:
        for search in (diagnostic_id, "real-http-disk-failure"):
            page = list_system_events_page(db, page=1, page_size=20, search=search)
            assert page.total == 1
            assert page.events[0]["id"] == diagnostic_id
        diagnostic = db.get(SystemEvent, diagnostic_id).metadata_json["diagnostics"]
    assert diagnostic["directException"]["errno"] == errno.ENOSPC
    assert "No space left on device" in diagnostic["message"]
    assert diagnostic_id in caplog.text


@pytest.mark.parametrize(
    ("target", "method", "path", "payload"),
    [
        (
            "app.modules.library.application.catalog.ListCatalogFacets.execute",
            "GET",
            "/api/library/facets?kind=TAG",
            None,
        ),
        (
            "app.modules.metadata.presentation.http.prepare_metadata_provider_update",
            "PATCH",
            "/api/metadata/providers/douban",
            {"config": {}},
        ),
        (
            "app.modules.organize.presentation.http.update_organize_policy_command",
            "PUT",
            "/api/organize/policy",
            {},
        ),
        (
            "app.modules.backup.application.operations.RestoreBackup.execute",
            "POST",
            "/api/backups/test-backup/restore",
            {},
        ),
    ],
)
def test_unknown_value_error_is_internal_failure_not_request_validation(
    client, db_session, monkeypatch, caplog, target, method, path, payload
):
    setup = client.post(
        "/api/auth/setup",
        json={
            "name": "Diagnostic admin",
            "email": "diagnostic-admin@example.com",
            "password": "diagnostic-password",
        },
    )
    assert setup.status_code == 201

    def unexpected(*_args, **_kwargs):
        raise ValueError(
            "unexpected invariant failure /private/library/private-book.epub"
        )

    monkeypatch.setattr(target, unexpected)
    response = client.request(method, path, json=payload)
    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    event = db_session.get(SystemEvent, response.headers["X-Error-Id"])
    assert event is not None
    assert event.metadata_json["diagnostics"]["directException"]["type"] == "ValueError"
    assert (
        "unexpected invariant failure" in event.metadata_json["diagnostics"]["message"]
    )
    assert event.id in caplog.text
    assert "private-book" not in response.text + caplog.text
