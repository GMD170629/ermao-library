import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.authorization import AuthorizationContext
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNode,
)
from app.models.auth import User
from app.modules.imports.infrastructure.library_queries import list_import_tasks_page


@pytest.fixture()
def import_history(db_session: Session) -> None:
    now = datetime.now(UTC)
    for index in range(3):
        library_id = f"history-{index}"
        db_session.add(
            Library(
                id=library_id,
                name=library_id,
                root_path=f"/{library_id}",
                organization_mode="FLAT",
                enabled=index != 1,
            )
        )
        db_session.flush()
        db_session.add(
            LibrarySourceNode(
                id=f"node-{index}",
                library_id=library_id,
                name=f"SourceName-{index}",
                relative_path=f"目录/100%_Title-{index}.epub",
                path_key="v1:"
                + hashlib.sha256(f"目录/100%_Title-{index}.epub".encode()).hexdigest(),
                physical_kind="REGULAR_FILE",
                observed_size_bytes=0,
                observed_mtime_ns=0,
                observed_at=now,
            )
        )
        db_session.flush()
        db_session.add(
            LibraryBook(
                id=f"book-{index}",
                library_id=library_id,
                source_node_id=f"node-{index}",
            )
        )
        db_session.flush()
        db_session.add(
            LibraryBookMetadata(
                book_id=f"book-{index}",
                title=f"书名-{index}",
                normalized_title=f"书名-{index}",
            )
        )
        db_session.add(
            LibraryReadableResource(
                id=f"resource-{index}",
                library_id=library_id,
                book_id=f"book-{index}",
                source_node_id=f"node-{index}",
                adapter_id="epub",
                adapter_version="1",
                format="EPUB",
                import_state="READY",
            )
        )
        db_session.flush()
        db_session.add(
            LibraryReadableResourceMetadata(
                resource_id=f"resource-{index}", title=f"ResourceTitle-{index}"
            )
        )
        db_session.add(
            LibraryImportTask(
                id=f"task-{index}",
                kind="IMPORT_ASSET",
                role="PRIMARY",
                library_id=library_id,
                source_node_id=f"node-{index}",
                resource_id=f"resource-{index}",
                state="FAILED" if index == 1 else "QUEUED",
                error_summary="not-searchable",
                created_at=now - timedelta(seconds=index),
            )
        )
    db_session.commit()


def context(admin: bool = True) -> AuthorizationContext:
    return AuthorizationContext(
        user_id="history-user",
        is_admin=admin,
        can_manage_system=admin,
        can_view_manual_imports=True,
        library_ids=("history-0",),
        authz_version=1,
    )


@pytest.mark.parametrize(
    "keyword",
    ["书名-1", "resourcetitle-1", "sOURCEnAME-1", "目录/100%_Title-1", "  %_title-1  "],
)
def test_keyword_searches_all_display_fields_before_pagination(
    db_session: Session, import_history: None, keyword: str
) -> None:
    tasks, total, summary = list_import_tasks_page(
        db_session, context(), page=1, page_size=1, keyword=keyword, state="FAILED"
    )
    assert [task["id"] for task in tasks] == ["task-1"]
    assert total == 1
    assert summary == {"queued": 2, "running": 0, "completed": 0, "failed": 1}


def test_scope_pagination_and_literal_matching(
    db_session: Session, import_history: None
) -> None:
    tasks, total, _ = list_import_tasks_page(
        db_session, context(), page=2, page_size=1, keyword="  "
    )
    assert total == 3
    assert tasks[0]["id"] == "task-1"
    for keyword in ("not-searchable", "100__Title", "missing"):
        assert (
            list_import_tasks_page(
                db_session, context(), page=1, page_size=10, keyword=keyword
            )[1]
            == 0
        )
    assert (
        list_import_tasks_page(
            db_session,
            context(),
            page=1,
            page_size=10,
            library_id="history-0",
            state="FAILED",
            keyword="Title",
        )[1]
        == 0
    )
    tasks, total, summary = list_import_tasks_page(
        db_session, context(False), page=1, page_size=10, keyword="Title"
    )
    assert total == 1
    assert [task["id"] for task in tasks] == ["task-0"]
    assert summary["queued"] == 1
    assert summary["failed"] == 0


def test_collection_and_library_http_filters(
    client: TestClient, db_session: Session, import_history: None
) -> None:
    db_session.add(
        User(
            email="history@example.com",
            name="History",
            password_hash=hash_password("HistoryPassword123!"),
            role="admin",
            can_manage_system=True,
        )
    )
    db_session.commit()
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "history@example.com", "password": "HistoryPassword123!"},
        ).status_code
        == 200
    )
    for path in ("/api/library-import-tasks", "/api/libraries/history-1/import-tasks"):
        response = client.get(
            path,
            params={"keyword": "书名-1", "state": "FAILED", "pageSize": 1, "page": 9},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 1
        assert data["page"] == 1
        assert data["tasks"][0]["id"] == "task-1"
    assert client.get("/api/libraries/missing/import-tasks").status_code == 404
    assert (
        client.get("/api/library-import-tasks", params={"state": "INVALID"}).status_code
        == 422
    )


def test_collection_http_does_not_expose_other_libraries(
    client: TestClient, db_session: Session, import_history: None
) -> None:
    from app.models.auth import UserLibraryAccess

    user = User(
        email="history-member@example.com",
        name="Member",
        password_hash=hash_password("HistoryPassword123!"),
        role="member",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserLibraryAccess(user_id=user.id, library_id="history-0"))
    db_session.commit()
    assert (
        client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "HistoryPassword123!"},
        ).status_code
        == 200
    )
    response = client.get("/api/library-import-tasks", params={"keyword": "Title"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["queued"] == 1
    assert data["failed"] == 0
    assert [task["id"] for task in data["tasks"]] == ["task-0"]
    forbidden = client.get("/api/libraries/history-1/import-tasks")
    missing = client.get("/api/libraries/missing/import-tasks")
    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()
