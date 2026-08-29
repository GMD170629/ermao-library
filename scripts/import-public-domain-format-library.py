#!/usr/bin/env python3
"""Scan the public-format fixtures and place their Books on one personal shelf."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
sys.path.insert(0, str(API_ROOT))

from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
)
from app.db.session import SessionLocal
from app.models import (
    LibraryBook,
    LibraryImportTask,
    LibraryReadableResource,
    LibrarySourceNode,
)
from app.models.common import cuid
from app.models.shelf import Shelf, ShelfBook
from app.modules.shelf.application.commands import (
    CreateShelf,
    CreateShelfCommand,
)
from app.modules.shelf.domain.policies import ShelfKind
from app.modules.shelf.infrastructure import shelves as shelf_store
from app.modules.shelf.infrastructure.memberships import (
    SqlAlchemyShelfBookMembership,
)


def process_fixture_tasks(prefix: str) -> dict[str, int]:
    outcomes: dict[str, int] = {}
    with SessionLocal() as session:
        pipeline = build_readable_resource_pipeline(session)
        pipeline.scan_library_source_tree.execute_library(args.library_id)
        for _attempt in range(3):
            task_ids = session.scalars(
                select(LibraryImportTask.id)
                .join(
                    LibrarySourceNode,
                    LibraryImportTask.source_node_id == LibrarySourceNode.id,
                )
                .where(
                    LibraryImportTask.library_id == args.library_id,
                    LibraryImportTask.kind == "IMPORT_ASSET",
                    LibraryImportTask.state.in_(("QUEUED", "FAILED")),
                    LibrarySourceNode.relative_path.startswith(prefix),
                )
                .order_by(
                    LibraryImportTask.created_at.asc(), LibraryImportTask.id.asc()
                )
            ).all()
            if not task_ids:
                break
            for task_id in task_ids:
                result = pipeline.process_import_task.execute(str(task_id))
                outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
    return outcomes


def fixture_book_ids(prefix: str) -> tuple[str, ...]:
    with SessionLocal() as session:
        return tuple(
            str(book_id)
            for book_id in session.scalars(
                select(LibraryBook.id)
                .join(
                    LibrarySourceNode,
                    LibraryBook.source_node_id == LibrarySourceNode.id,
                )
                .where(
                    LibraryBook.library_id == args.library_id,
                    LibrarySourceNode.relative_path.startswith(prefix),
                )
                .order_by(LibrarySourceNode.relative_path.asc(), LibraryBook.id.asc())
            ).all()
        )


def ensure_shelf(book_ids: tuple[str, ...]) -> str:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        shelf = session.scalar(
            select(Shelf).where(
                Shelf.owner_user_id == args.owner_user_id,
                Shelf.name == args.shelf_name,
                Shelf.kind == ShelfKind.STATIC.value,
            )
        )
        if shelf is None:
            shelf_id = cuid()
            CreateShelf(shelf_store, session).execute(
                CreateShelfCommand(
                    values={
                        "id": shelf_id,
                        "ownerUserId": args.owner_user_id,
                        "name": args.shelf_name,
                        "description": "公版读物全格式导入测试 / Public-domain format import fixtures",
                        "kind": ShelfKind.STATIC.value,
                        "rulesJson": "{}",
                        "pinned": True,
                        "createdAt": now,
                        "updatedAt": now,
                    },
                    kind=ShelfKind.STATIC,
                    book_ids=book_ids,
                    member_shelf_ids=(),
                    collection_ids=(),
                    now=now,
                )
            )
            return shelf_id
        SqlAlchemyShelfBookMembership(session).add_books(
            shelf_id=shelf.id,
            book_ids=book_ids,
            now=now,
        )
        session.commit()
        return str(shelf.id)


def verification(shelf_id: str, prefix: str) -> dict[str, object]:
    with SessionLocal() as session:
        membership_count = int(
            session.scalar(
                select(func.count())
                .select_from(ShelfBook)
                .where(ShelfBook.shelf_id == shelf_id)
            )
            or 0
        )
        resource_rows = session.execute(
            select(LibraryReadableResource.format, LibraryReadableResource.import_state)
            .join(
                LibrarySourceNode,
                LibraryReadableResource.source_node_id == LibrarySourceNode.id,
            )
            .where(
                LibraryReadableResource.library_id == args.library_id,
                LibrarySourceNode.relative_path.startswith(prefix),
            )
            .order_by(LibraryReadableResource.format.asc())
        ).all()
        return {
            "shelfId": shelf_id,
            "membershipCount": membership_count,
            "resourceCount": len(resource_rows),
            "formats": [str(row.format) for row in resource_rows],
            "states": {
                state: sum(1 for row in resource_rows if row.import_state == state)
                for state in sorted({str(row.import_state) for row in resource_rows})
            },
        }


parser = argparse.ArgumentParser()
parser.add_argument("--library-id", required=True)
parser.add_argument("--owner-user-id", required=True)
parser.add_argument("--prefix", default="公开格式测试")
parser.add_argument("--shelf-name", default="公开格式测试书架")
args = parser.parse_args()

outcomes = process_fixture_tasks(args.prefix)
book_ids = fixture_book_ids(args.prefix)
if not book_ids:
    raise RuntimeError("No imported fixture books were found")
shelf_id = ensure_shelf(book_ids)
print(
    json.dumps(
        {"taskOutcomes": outcomes, **verification(shelf_id, args.prefix)},
        ensure_ascii=False,
    )
)
