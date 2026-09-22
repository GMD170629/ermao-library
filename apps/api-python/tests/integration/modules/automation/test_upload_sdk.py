"""Pure tools/call transfers against the pinned official SDK over real HTTP."""

import asyncio
import base64
import hashlib
import logging
import socket
from contextlib import asynccontextmanager
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import httpx2
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from PIL import Image
from sqlalchemy.orm import sessionmaker

from app.bootstrap.automation import build_automation_settings, build_grant_manager
from app.main import create_app
from app.models import LibrarySourceNode
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import ALL_SCOPES
from tests.integration.modules.automation.test_file_reads import add_file
from tests.integration.modules.automation.test_uploads import upload_access


def test_sdk_upload_disconnect_server_restart_cover_and_redaction(
    db_session, tmp_path, monkeypatch, test_settings, caplog
):
    caplog.set_level(logging.INFO)
    access, root = upload_access(db_session, tmp_path, monkeypatch, test_settings)
    build_automation_settings(db_session).update(access.user_id, AutomationServiceSettings(True, ALL_SCOPES, "http://localhost"))
    grant = build_grant_manager(db_session).create(user_id=access.user_id, name="six scopes SDK", permissions=replace(access.permissions, scopes=ALL_SCOPES))
    access = replace(access, grant_id=grant.grant.id, permissions=grant.grant.permissions)
    comic = BytesIO()
    with ZipFile(comic, "w") as archive:
        archive.writestr("ComicInfo.xml", "<ComicInfo><Title>Original</Title></ComicInfo>")
        archive.writestr("page.png", b"page-bytes")
    (root / "allowed/sdk.cbz").write_bytes(comic.getvalue())
    add_file(db_session, "sdk-replace", "allowed/sdk.cbz")
    observed = (root / "allowed/sdk.cbz").stat()
    node = db_session.get(LibrarySourceNode, "sdk-replace")
    node.observed_size_bytes, node.observed_mtime_ns = observed.st_size, observed.st_mtime_ns
    db_session.commit()
    token = build_grant_manager(db_session).reveal(
        user_id=access.user_id, grant_id=access.grant_id
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    data = b"private-attachment-exact-bytes" * 20000
    block = 256 * 1024

    @asynccontextmanager
    async def server():
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        with factory() as db:
            build_automation_settings(db).update(
                access.user_id,
                AutomationServiceSettings(True, access.permissions.scopes, base),
            )
        host = uvicorn.Server(
            uvicorn.Config(
                create_app(test_settings, session_factory=factory),
                log_level="error",
                lifespan="off",
                ws="none",
            )
        )
        task = asyncio.create_task(host.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not host.started:
                    assert not task.done()
                    await asyncio.sleep(0.01)
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + token}
                ) as http,
                Client(
                    streamable_http_client(base + "/api/mcp", http_client=http),
                    read_timeout_seconds=10,
                ) as client,
            ):
                yield client
        finally:
            host.should_exit = True
            async with asyncio.timeout(10):
                await task
            listener.close()

    async def call(client, name, arguments):
        result = await client.call_tool(name, arguments)
        assert not result.is_error, result
        return result.structured_content

    async def exercise():
        async with server() as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {
                "begin_upload",
                "upload_chunk",
                "complete_upload",
                "get_operation",
                "cancel_operation",
            } <= names
            assert {"update_site_settings", "plan_file_deletions", "execute_file_deletions", "update_shelf", "delete_shelf"} <= names
            await call(client, "list_import_queue", {})
            await call(client, "get_system_queue_status", {})
            await call(client, "list_system_logs", {})
            await call(client, "update_site_settings", {"settings": {"language": "en-US"}})
            assert (await call(client, "get_system_configuration", {"group": "site"}))["language"] == "en-US"
            smart = await call(client, "create_shelf", {"request_id": "sdk-smart", "name": "Smart", "kind": "SMART", "rules": {"search": "二毛"}})
            await call(client, "update_shelf", {"request_id": "sdk-smart-update", "shelf_id": smart["shelf_id"], "name": "Updated", "kind": "SMART", "rules": {"search": "none"}})
            await call(client, "delete_shelf", {"request_id": "sdk-smart-delete", "shelf_id": smart["shelf_id"]})
            nodes = await call(client, "list_source_nodes", {"library_id": "test-library", "parent_id": "allowed-node"})
            version = next(node["source_version"] for node in nodes["nodes"] if node["node_id"] == "sdk-replace")
            replacement = BytesIO()
            with ZipFile(replacement, "w") as archive:
                archive.writestr("ComicInfo.xml", "<ComicInfo><Title>Replacement</Title></ComicInfo>")
                archive.writestr("page.png", b"page-bytes")
            replacement_bytes = replacement.getvalue()
            transfer = await call(client, "begin_upload", {"request_id": "sdk-replace", "purpose": "replace", "filename": "sdk.cbz", "library_id": "test-library", "source_node_id": "sdk-replace", "expected_source_version": version, "size_bytes": len(replacement_bytes), "sha256": hashlib.sha256(replacement_bytes).hexdigest()})
            await call(client, "upload_chunk", {"upload_id": transfer["upload_id"], "offset": 0, "data_base64": base64.b64encode(replacement_bytes).decode()})
            replaced = await call(client, "complete_upload", {"upload_id": transfer["upload_id"]})
            assert replaced["file_saved"]
            with ZipFile(root / "allowed/sdk.cbz") as archive:
                assert b"Replacement" in archive.read("ComicInfo.xml")
                assert archive.read("page.png") == b"page-bytes"
            deletion = await call(client, "plan_file_deletions", {"source_node_ids": ["sdk-replace"]})
            deleted = await call(client, "execute_file_deletions", {"plan_id": deletion["plan_id"]})
            assert deleted["targets"][0]["stage"] == "INDEX_PENDING"
            assert not (root / "allowed/sdk.cbz").exists()
            limits = (await call(client, "get_context", {}))["limits"]
            assert limits["upload_chunk_bytes"] == block
            begin = await call(
                client,
                "begin_upload",
                {
                    "purpose": "book",
                    "filename": "sdk.epub",
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "library_id": "test-library",
                    "request_id": "sdk-book",
                },
            )
            upload_id = begin["upload_id"]
            first = {
                "upload_id": upload_id,
                "offset": 0,
                "data_base64": base64.b64encode(data[:block]).decode(),
            }
            assert (await call(client, "upload_chunk", first))[
                "received_bytes"
            ] == block
            assert (await call(client, "upload_chunk", first))[
                "received_bytes"
            ] == block
            assert (
                await client.call_tool("upload_chunk", dict(first, offset=block + 1))
            ).is_error
            assert (
                await client.call_tool(
                    "upload_chunk", dict(first, data_base64="X" * 400000)
                )
            ).is_error
        async with server() as client:
            assert (await call(client, "get_operation", {"operation_id": upload_id}))[
                "received_bytes"
            ] == block
            for offset in range(block, len(data), block):
                await call(
                    client,
                    "upload_chunk",
                    {
                        "upload_id": upload_id,
                        "offset": offset,
                        "data_base64": base64.b64encode(
                            data[offset : offset + block]
                        ).decode(),
                    },
                )
            result = await call(client, "complete_upload", {"upload_id": upload_id})
            assert result["status"] == "QUEUED" and result["file_saved"]
            assert (
                await call(client, "complete_upload", {"upload_id": upload_id})
            ) == result
            assert (root / "sdk.epub").read_bytes() == data
            bad = await call(
                client,
                "begin_upload",
                {
                    "purpose": "book",
                    "filename": "digest.epub",
                    "size_bytes": 1,
                    "sha256": "0" * 64,
                    "library_id": "test-library",
                    "request_id": "sdk-digest",
                },
            )
            await call(
                client,
                "upload_chunk",
                {"upload_id": bad["upload_id"], "offset": 0, "data_base64": "YQ=="},
            )
            assert (
                await call(client, "complete_upload", {"upload_id": bad["upload_id"]})
            )["error_code"] == "UPLOAD_DIGEST_MISMATCH"
            assert (
                await client.call_tool(
                    "begin_upload",
                    {
                        "purpose": "book",
                        "filename": "large.epub",
                        "size_bytes": 8 * 1024**3 + 1,
                        "sha256": "0" * 64,
                        "library_id": "test-library",
                        "request_id": "sdk-limit",
                    },
                )
            ).is_error
            output = BytesIO()
            Image.effect_noise((800, 800), 100).convert("RGB").save(
                output, format="PNG"
            )
            cover = output.getvalue()
            revision = (
                await call(
                    client,
                    "get_metadata_schema",
                    {"target_type": "book", "target_id": "allowed"},
                )
            )["expected_revision"]
            begin = await call(
                client,
                "begin_upload",
                {
                    "purpose": "cover",
                    "filename": "image.png",
                    "size_bytes": len(cover),
                    "sha256": hashlib.sha256(cover).hexdigest(),
                    "book_id": "allowed",
                    "expected_revision": revision,
                    "request_id": "sdk-cover",
                },
            )
            for offset in range(0, len(cover), block):
                await call(
                    client,
                    "upload_chunk",
                    {
                        "upload_id": begin["upload_id"],
                        "offset": offset,
                        "data_base64": base64.b64encode(
                            cover[offset : offset + block]
                        ).decode(),
                    },
                )
            result = await call(
                client, "complete_upload", {"upload_id": begin["upload_id"]}
            )
            assert result["status"] == "COMPLETED"
            assert result["result"]["cover_url"].startswith(
                "/api/books/allowed/cover?v="
            )

    asyncio.run(exercise())
    assert token not in caplog.text
    assert "private-attachment-exact-bytes" not in caplog.text
    assert base64.b64encode(data[:30]).decode() not in caplog.text
