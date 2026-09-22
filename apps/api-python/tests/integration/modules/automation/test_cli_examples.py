"""Run the shipped CLIs against real HTTP SDK and disposable library files."""

import asyncio
import os
import socket
import sys
from pathlib import Path

import uvicorn
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.bootstrap.automation import build_automation_settings, build_grant_manager
from app.bootstrap.file_moves import build_file_move_worker
from app.bootstrap.standard_writeback import process_standard_writeback
from app.main import create_app
from app.models import Library, LibraryBookMetadata
from app.models.shelf import Shelf
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import (
    ALL_SCOPES,
    GrantPermissions,
)
from app.services.metadata_file_writeback import process_next_metadata_writeback
from tests.integration.modules.automation.test_mcp_catalog import seed

EXAMPLES = Path(__file__).resolve().parents[6] / "examples/mcp"


def test_five_shipped_examples_default_preview_and_explicit_execution(
    db_session, test_settings, tmp_path
):
    seed(db_session)
    root = tmp_path / "library"
    (root / "allowed").mkdir(parents=True)
    original = b'<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Original</dc:title></metadata></package>'
    (root / "allowed/metadata.opf").write_bytes(original)
    library = db_session.get(Library, "test-library")
    library.root_path = str(root)
    library.organization_mode = "VOLUMES"
    db_session.commit()
    grant = build_grant_manager(db_session).create(
        user_id="mcp-owner",
        name="examples",
        permissions=GrantPermissions(
            ALL_SCOPES,
            frozenset({"test-library"}),
        ),
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    app = create_app(test_settings, session_factory=factory)

    async def exercise():
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        with factory() as db:
            build_automation_settings(db).update(
                "mcp-owner",
                AutomationServiceSettings(
                    enabled=True, enabled_scopes=ALL_SCOPES, public_base_url=base
                ),
            )
        host = uvicorn.Server(
            uvicorn.Config(app, log_level="error", lifespan="off", ws="none")
        )
        task = asyncio.create_task(host.serve(sockets=[listener]))
        env = {
            **os.environ,
            "ERMAO_MCP_URL": base + "/api/mcp",
            "ERMAO_MCP_TOKEN": grant.token,
        }

        async def run_script(name, *args):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(EXAMPLES / name),
                *args,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(30):
                    # Exercise the same queued consumers used by the worker while
                    # the real CLI independently submits and polls over HTTP.
                    communicate = asyncio.create_task(process.communicate())
                    while not communicate.done():
                        with factory() as db:
                            build_file_move_worker(db).process_once()
                            process_next_metadata_writeback(
                                db,
                                test_settings,
                                standard_handler=process_standard_writeback,
                            )
                        await asyncio.sleep(0.05)
                    out, err = await communicate
                assert grant.token.encode() not in out + err
                assert process.returncode == 0, (name, out.decode(), err.decode())
                return out
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

        try:
            async with asyncio.timeout(10):
                while not host.started:
                    assert not task.done()
                    await asyncio.sleep(0.01)
            metadata = (
                "--target-type",
                "book",
                "--target-id",
                "allowed",
                "--set",
                'title="CLI title"',
            )
            move = (
                "--node-id",
                "allowed-node",
                "--destination-library-id",
                "test-library",
                "--destination-path",
                "renamed",
            )
            write = (
                "--target-type",
                "book",
                "--target-id",
                "allowed",
                "--node-id",
                "allowed-node",
                "--mode",
                "opf",
                "--field",
                "title",
            )
            await run_script("smoke_read.py")
            await run_script("create_shelf_example.py", "--name", "CLI shelf")
            await run_script("update_metadata_example.py", *metadata)
            await run_script("move_books_example.py", *move)
            await run_script("writeback_metadata_example.py", *write)
            with factory() as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(Shelf)
                        .where(Shelf.name == "CLI shelf")
                    )
                    == 0
                )
                assert db.get(LibraryBookMetadata, "allowed").title == "二毛"
            assert (root / "allowed/metadata.opf").read_bytes() == original
            assert not (root / "renamed").exists()
            await run_script(
                "create_shelf_example.py",
                "--name",
                "CLI shelf",
                "--execute",
                "--request-id",
                "cli-shelf",
            )
            await run_script(
                "update_metadata_example.py",
                *metadata,
                "--execute",
                "--request-id",
                "cli-metadata",
            )
            await run_script(
                "move_books_example.py", *move, "--execute", "--request-id", "cli-move"
            )
            await run_script(
                "writeback_metadata_example.py",
                *write,
                "--execute",
                "--request-id",
                "cli-write",
            )
            with factory() as db:
                assert db.get(LibraryBookMetadata, "allowed").title == "CLI title"
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(Shelf)
                        .where(Shelf.name == "CLI shelf")
                    )
                    == 1
                )
            assert b"CLI title" in (root / "renamed/metadata.opf").read_bytes()
            assert not (root / "allowed").exists()
        finally:
            host.should_exit = True
            await task
            listener.close()

    asyncio.run(exercise())
