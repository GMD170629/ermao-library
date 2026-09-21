"""Real HTTP SDK calls, fresh grant checks and bounded catalog visibility."""

import asyncio
import hashlib
import socket
from dataclasses import replace
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
from app.modules.automation.domain.access import (
    GrantPermissions,
    Scope,
    WritebackTarget,
)


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
    source_root = test_settings.resolved_storage_root.parent / "mcp-library"
    (source_root / "allowed").mkdir(parents=True)
    source_opf = source_root / "allowed/metadata.opf"
    source_opf.write_bytes(
        b'<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>File title</dc:title><dc:creator>File author</dc:creator></metadata></package>'
    )
    db_session.get(Library, "test-library").root_path = str(source_root)
    db_session.commit()

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
                    "get_operation",
                    "cancel_operation",
                    "get_metadata_schema",
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
            scopes = frozenset(
                {
                    Scope.LIBRARY_READ,
                    Scope.SHELVES_WRITE,
                    Scope.TAGS_WRITE,
                    Scope.METADATA_WRITE,
                    Scope.FILES_READ,
                    Scope.FILES_MOVE,
                    Scope.METADATA_WRITEBACK,
                }
            )
            with factory() as db:
                writer = build_grant_manager(db).create(
                    user_id="mcp-owner",
                    name="writer",
                    permissions=replace(
                        created.grant.permissions,
                        scopes=scopes,
                        writeback_targets=frozenset({WritebackTarget.SIDECAR}),
                    ),
                )
                build_automation_settings(db).update(
                    "mcp-owner",
                    AutomationServiceSettings(
                        enabled=True,
                        enabled_scopes=scopes,
                        public_base_url=base + prefix,
                    ),
                )
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + writer.token}
                ) as http,
                Client(
                    streamable_http_client(url, http_client=http),
                    read_timeout_seconds=5,
                ) as client,
            ):
                tools = {tool.name for tool in (await client.list_tools()).tools}
                assert {
                    "create_shelf",
                    "add_shelf_books",
                    "remove_shelf_books",
                    "add_book_tags",
                    "remove_book_tags",
                } <= tools
                args = {"request_id": "sdk-create", "name": "SDK 书架"}
                first = await client.call_tool("create_shelf", args)
                assert not first.is_error, first
                again = await client.call_tool("create_shelf", args)
                assert first.structured_content == again.structured_content
                shelf_id = first.structured_content["shelf_id"]
                added = await client.call_tool(
                    "add_shelf_books",
                    {
                        "request_id": "sdk-add",
                        "shelf_id": shelf_id,
                        "book_ids": ["allowed"],
                    },
                )
                assert not added.is_error, added
                assert added.structured_content["updated"] == 1
                changed = await client.call_tool(
                    "add_book_tags",
                    {
                        "request_id": "sdk-tag",
                        "book_ids": ["allowed"],
                        "tags": ["文学"],
                    },
                )
                assert not changed.is_error, changed
                assert changed.structured_content["updated"] == 1
                schema = await client.call_tool(
                    "get_metadata_schema",
                    {"target_type": "book", "target_id": "allowed"},
                )
                assert not schema.is_error, schema
                metadata_args = {
                    "request_id": "sdk-metadata",
                    "changes": [
                        {
                            "target_type": "book",
                            "target_id": "allowed",
                            "expected_revision": schema.structured_content[
                                "expected_revision"
                            ],
                            "fields": {"title": "来自 MCP"},
                        }
                    ],
                }
                metadata_result = await client.call_tool(
                    "update_metadata", metadata_args
                )
                assert not metadata_result.is_error, metadata_result
                assert metadata_result.structured_content["updated"] == 1
                repeat = await client.call_tool("update_metadata", metadata_args)
                assert repeat.structured_content == metadata_result.structured_content
                stale = await client.call_tool(
                    "update_metadata", {**metadata_args, "request_id": "sdk-stale"}
                )
                assert stale.is_error and "CONFLICT" in str(stale)
                listing = await client.call_tool(
                    "list_source_nodes", {"library_id": "test-library"}
                )
                assert not listing.is_error, listing
                assert listing.structured_content["total"] == 1
                assert str(source_root) not in str(listing)
                observed = await client.call_tool(
                    "read_file_metadata",
                    {"node_id": "allowed-node", "source": "sidecar"},
                )
                assert not observed.is_error, observed
                assert observed.structured_content["metadata"]["title"] == "File title"
                current_book = await client.call_tool(
                    "get_books", {"book_ids": ["allowed"]}
                )
                assert (
                    current_book.structured_content["books"][0]["title"] == "来自 MCP"
                )
                assert list((source_root / "allowed").iterdir()) == [source_opf]
                refresh_schema = await client.call_tool(
                    "get_metadata_schema",
                    {"target_type": "book", "target_id": "allowed"},
                )
                refreshed = await client.call_tool(
                    "refresh_metadata",
                    {
                        "request_id": "sdk-refresh",
                        "changes": [
                            {
                                "target_type": "book",
                                "target_id": "allowed",
                                "expected_revision": refresh_schema.structured_content[
                                    "expected_revision"
                                ],
                                "node_id": "allowed-node",
                                "source": "sidecar",
                                "expected_file_revision": observed.structured_content[
                                    "file_revision"
                                ],
                                "fields": ["author"],
                            }
                        ],
                    },
                )
                assert not refreshed.is_error, refreshed
                after_refresh = await client.call_tool(
                    "get_books", {"book_ids": ["allowed"]}
                )
                assert (
                    after_refresh.structured_content["books"][0]["author"]
                    == "File author"
                )
                assert (
                    after_refresh.structured_content["books"][0]["title"] == "来自 MCP"
                )

                with factory() as db:
                    db.get(Library, "test-library").organization_mode = "VOLUMES"
                    db.commit()
                planned = await client.call_tool(
                    "plan_file_operations",
                    {
                        "moves": [
                            {
                                "source_node_id": "allowed-node",
                                "destination_library_id": "test-library",
                                "template": "{title}",
                                "template_values": {"title": "renamed"},
                            }
                        ]
                    },
                )
                assert not planned.is_error, planned
                assert str(source_root) not in str(planned)
                assert source_opf.exists()
                move_args = {
                    "plan_id": planned.structured_content["plan_id"],
                    "request_id": "sdk-move",
                }
                submitted = await client.call_tool("execute_file_operations", move_args)
                assert not submitted.is_error, submitted
                assert (
                    await client.call_tool("execute_file_operations", move_args)
                ).structured_content == submitted.structured_content
                operation_id = submitted.structured_content["operation_id"]
                queued = await client.call_tool(
                    "get_operation", {"operation_id": operation_id}
                )
                assert queued.structured_content["status"] == "QUEUED"

                def run_worker():
                    from app.bootstrap.file_moves import build_file_move_worker

                    with factory() as db:
                        assert build_file_move_worker(db).process_once()

                await asyncio.to_thread(run_worker)
                completed = await client.call_tool(
                    "get_operation", {"operation_id": operation_id}
                )
                assert not completed.is_error, completed
                assert completed.structured_content["status"] == "COMPLETED"
                assert (source_root / "renamed/metadata.opf").exists()
                assert not source_opf.exists()
                second_plan = await client.call_tool(
                    "plan_file_operations",
                    {
                        "moves": [
                            {
                                "source_node_id": "allowed-node",
                                "destination_library_id": "test-library",
                                "destination_relative_path": "cancelled",
                            }
                        ]
                    },
                )
                assert not second_plan.is_error, second_plan
                second_task = await client.call_tool(
                    "execute_file_operations",
                    {
                        "plan_id": second_plan.structured_content["plan_id"],
                        "request_id": "sdk-cancel-move",
                    },
                )
                assert not second_task.is_error, second_task
                cancelled = await client.call_tool(
                    "cancel_operation",
                    {"operation_id": second_task.structured_content["operation_id"]},
                )
                assert not cancelled.is_error, cancelled
                assert cancelled.structured_content["status"] == "CANCELLED"
                assert not (source_root / "cancelled").exists()
                schema = await client.call_tool(
                    "get_metadata_schema",
                    {"target_type": "book", "target_id": "allowed"},
                )
                before_writeback = (source_root / "renamed/metadata.opf").read_bytes()
                standard_plan = await client.call_tool(
                    "plan_metadata_writeback",
                    {
                        "targets": [
                            {
                                "target_type": "book",
                                "target_id": "allowed",
                                "node_id": "allowed-node",
                                "expected_revision": schema.structured_content[
                                    "expected_revision"
                                ],
                                "mode": "opf",
                                "fields": ["title"],
                            }
                        ]
                    },
                )
                assert not standard_plan.is_error, standard_plan
                assert str(source_root) not in str(standard_plan)
                assert (
                    source_root / "renamed/metadata.opf"
                ).read_bytes() == before_writeback
                writeback_args = {
                    "plan_id": standard_plan.structured_content["plan_id"],
                    "request_id": "sdk-writeback",
                }
                standard_task = await client.call_tool(
                    "execute_metadata_writeback", writeback_args
                )
                assert not standard_task.is_error, standard_task
                assert (
                    await client.call_tool("execute_metadata_writeback", writeback_args)
                ).structured_content == standard_task.structured_content
                standard_id = standard_task.structured_content["operation_id"]

                def writeback_worker():
                    from app.bootstrap.standard_writeback import (
                        process_standard_writeback,
                    )
                    from app.services.metadata_file_writeback import (
                        process_next_metadata_writeback,
                    )

                    with factory() as db:
                        assert process_next_metadata_writeback(
                            db,
                            test_settings,
                            standard_handler=process_standard_writeback,
                        )

                await asyncio.to_thread(writeback_worker)
                standard_result = await client.call_tool(
                    "get_operation", {"operation_id": standard_id}
                )
                assert not standard_result.is_error, standard_result
                assert (
                    standard_result.structured_content["targets"][0]["stage"]
                    == "COMPLETED"
                )
                assert "来自 MCP" in (source_root / "renamed/metadata.opf").read_text()

                assert (
                    await client.call_tool("create_shelf", {**args, "name": "Changed"})
                ).is_error
            # A previously created read-only grant must not inherit write tools
            # when deployment permissions or another grant's discovery changes.
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + fresh.token}
                ) as http,
                Client(
                    streamable_http_client(url, http_client=http),
                    read_timeout_seconds=5,
                ) as client,
            ):
                assert "create_shelf" not in {
                    tool.name for tool in (await client.list_tools()).tools
                }
                assert (
                    await client.call_tool(
                        "create_shelf", {"request_id": "forbidden", "name": "Denied"}
                    )
                ).is_error
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
