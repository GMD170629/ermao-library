"""Real HTTP SDK calls, fresh grant checks and bounded catalog visibility."""

import asyncio
import hashlib
import socket
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.orm import sessionmaker

from app.bootstrap.automation import build_automation_settings, build_grant_manager
from app.main import create_app
from app.models import (
    Library,
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibrarySourceNode,
)
from app.models.auth import User
from app.models.shelf import Shelf, ShelfBook
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import GrantPermissions, Scope


def seed(db):
    db.add(
        User(
            id="mcp-owner",
            email="mcp@example.invalid",
            name="Owner",
            password_hash="unused",
            role="admin",
        )
    )
    db.add(
        Library(
            id="private-library",
            name="Private Library",
            root_path="/private/secret",
            organization_mode="FLAT",
        )
    )
    db.flush()
    for book_id, library_id in (
        ("allowed", "test-library"),
        ("secret", "private-library"),
    ):
        db.add(
            LibrarySourceNode(
                id=book_id + "-node",
                library_id=library_id,
                relative_path=book_id,
                path_key="v1:" + hashlib.sha256(book_id.encode()).hexdigest(),
                name=book_id,
                physical_kind="DIRECTORY",
                observed_mtime_ns=0,
                observed_at=datetime.now(UTC),
            )
        )
        db.flush()
        db.add(
            LibraryBook(
                id=book_id, library_id=library_id, source_node_id=book_id + "-node"
            )
        )
        db.flush()
        db.add(
            LibraryBookMetadata(
                book_id=book_id,
                title="二毛" if book_id == "allowed" else "SECRET TITLE",
                normalized_title=book_id,
            )
        )
        db.add(
            LibraryFacet(
                id=book_id + "-tag", kind="TAG", name=book_id, normalized_name=book_id
            )
        )
        db.flush()
        db.add(LibraryBookFacet(book_id=book_id, facet_id=book_id + "-tag"))
    db.add_all(
        [
            Shelf(id="static", owner_user_id="mcp-owner", name="Static", kind="STATIC"),
            Shelf(
                id="smart",
                owner_user_id="mcp-owner",
                name="Smart",
                kind="SMART",
                rules_json="{}",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            ShelfBook(shelf_id="static", book_id="allowed"),
            ShelfBook(shelf_id="static", book_id="secret"),
        ]
    )
    db.commit()
    return build_grant_manager(db).create(
        user_id="mcp-owner",
        name="client",
        permissions=GrantPermissions(
            frozenset({Scope.LIBRARY_READ}), frozenset({"test-library"})
        ),
    )


@pytest.mark.parametrize("prefix", ["", "/books"])
def test_official_sdk_real_catalog_and_revocation(db_session, test_settings, prefix):
    created = seed(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    app = create_app(test_settings, session_factory=factory)

    async def exercise():
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with factory() as db:
            build_automation_settings(db).update(
                "mcp-owner",
                AutomationServiceSettings(enabled=True, public_base_url=base),
            )
        host = uvicorn.Server(
            uvicorn.Config(app, log_level="error", lifespan="off", ws="none")
        )
        task = asyncio.create_task(host.serve(sockets=[listener]))
        gateway = None
        try:
            async with asyncio.timeout(10):
                while not host.started:
                    assert not task.done()
                    await asyncio.sleep(0.01)
            if prefix:
                script = (
                    Path(__file__).resolve().parents[6]
                    / "scripts/unified-http-gateway.mjs"
                )
                gateway = await asyncio.create_subprocess_exec(
                    "node",
                    "--input-type=module",
                    "-e",
                    "import {createUnifiedGateway} from "
                    + repr(script.as_uri())
                    + "; const server=createUnifiedGateway({apiPort:"
                    + str(port)
                    + ",basePath:'/books'}); server.listen(0,'127.0.0.1',()=>console.log(server.address().port));",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                async with asyncio.timeout(10):
                    gateway_port = int((await gateway.stdout.readline()).strip())
                base = f"http://127.0.0.1:{gateway_port}"
                with factory() as db:
                    build_automation_settings(db).update(
                        "mcp-owner",
                        AutomationServiceSettings(
                            enabled=True, public_base_url=base + prefix
                        ),
                    )
            url = base + prefix + "/api/mcp"
            headers = {"Authorization": "Bearer " + created.token}
            async with (
                httpx2.AsyncClient(headers=headers) as http,
                Client(
                    streamable_http_client(url, http_client=http),
                    read_timeout_seconds=5,
                ) as client,
            ):
                listed = await client.list_tools()
                assert {item.name for item in listed.tools} == {
                    "get_context",
                    "list_libraries",
                    "search_books",
                    "get_books",
                    "list_facets",
                    "list_shelves",
                    "get_shelf",
                }
                for name, args in (
                    ("get_context", {}),
                    ("list_libraries", {}),
                    ("search_books", {}),
                    ("get_books", {"book_ids": ["allowed"]}),
                    ("list_facets", {"kind": "TAG"}),
                    ("get_shelf", {"shelf_id": "static"}),
                    ("get_shelf", {"shelf_id": "smart"}),
                ):
                    result = await client.call_tool(name, args)
                    assert not result.is_error, result
                    serialized = str(result.structured_content)
                    assert "secret" not in serialized.lower(), (name, result)
                    assert "/test-library" not in serialized
                    if name == "search_books":
                        assert result.structured_content["total"] == 1
                        assert result.structured_content["books"][0]["title"] == "二毛"
                        assert result.structured_content["books"][0]["resources"] == []
                    if name == "get_shelf":
                        assert result.structured_content["total"] == 1
                for args in (
                    {"book_ids": []},
                    {"book_ids": ["allowed", "secret"]},
                    {"book_ids": ["missing"]},
                ):
                    assert (await client.call_tool("get_books", args)).is_error
                assert (
                    await client.call_tool("search_books", {"page_size": 51})
                ).is_error
                assert (
                    await client.call_tool("search_books", {"page_size": True})
                ).is_error
                with factory() as db:
                    build_grant_manager(db).revoke(
                        user_id="mcp-owner", grant_id=created.grant.id
                    )
                response = await http.post(url, json={})
                assert response.status_code == 401
                assert response.headers["cache-control"] == "no-store"
            with factory() as db:
                fresh = build_grant_manager(db).create(
                    user_id="mcp-owner",
                    name="another",
                    permissions=created.grant.permissions,
                )
            async with httpx2.AsyncClient() as http:
                assert (
                    await http.post(
                        url, headers={"Cookie": "shuku_session=anything"}, json={}
                    )
                ).status_code == 401
                auth = {"Authorization": "Bearer " + fresh.token}
                assert (
                    await http.post(
                        url, headers={**auth, "Host": "evil.invalid"}, json={}
                    )
                ).status_code == 421
                assert (
                    await http.post(
                        url, headers={**auth, "Origin": "https://evil.invalid"}, json={}
                    )
                ).status_code == 403
        finally:
            if gateway is not None and gateway.returncode is None:
                gateway.terminate()
                async with asyncio.timeout(10):
                    await gateway.wait()
            host.should_exit = True
            async with asyncio.timeout(10):
                await task
            listener.close()

    asyncio.run(exercise())
