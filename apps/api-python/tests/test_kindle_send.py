from __future__ import annotations

import hashlib
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select

from app.bootstrap.kindle import recover_interrupted_kindle_tasks_command
from app.core.auth import hash_password
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.auth import User
from app.models.import_pipeline import KindleSendTask
from app.models.settings import SystemEvent
from app.services import kindle_queue
from app.services.kindle_queue import (
    process_next_kindle_send_task,
    recover_interrupted_tasks,
)


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=Path(path).name or node_id,
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 1,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _login(client, db_session, *, user_id: str = "kindle-admin") -> User:
    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
        password_hash=hash_password("starshipnas"),
        role="admin" if user_id == "kindle-admin" else "member",
        can_view_manual_imports=True,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200, response.text
    return user


def _seed_book_resource_asset(db_session, test_settings) -> tuple[Path, str]:
    path = test_settings.resolved_storage_root / "books" / "book-kindle" / "book.epub"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"epub fixture")
    library = db_session.get(Library, "test-library")
    assert library is not None
    library.root_path = str(test_settings.resolved_storage_root)
    book_node = _node("kindle-book-node", "books/book-kindle", directory=True)
    resource_node = _node("kindle-resource-node", "books/book-kindle/book.epub")
    book = LibraryBook(
        id="book-kindle",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    resource = LibraryReadableResource(
        id="resource-kindle",
        library_id="test-library",
        book_id=book.id,
        source_node_id=resource_node.id,
        adapter_id="epub",
        adapter_version="1",
        media_kind="EBOOK",
        format="EPUB",
        enablement_state="ENABLED",
        import_state="READY",
    )
    asset = LibraryResourceAsset(
        id="asset-kindle",
        library_id="test-library",
        resource_id=resource.id,
        source_node_id=resource_node.id,
        source_node_physical_kind="REGULAR_FILE",
        role="PRIMARY",
        import_state="READY",
    )
    # The canonical graph uses non-null foreign keys at every identity edge;
    # flush each level explicitly so fixture ordering does not depend on
    # relationship discovery inside the unit of work.
    db_session.add_all([book_node, resource_node, book])
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book.id,
            title="Kindle Test Book",
            normalized_title="kindle test book",
            author="Author",
            normalized_author="author",
        )
    )
    db_session.add(resource)
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(resource_id=resource.id, title="EPUB")
    )
    db_session.add(asset)
    db_session.flush()
    db_session.commit()
    return path, asset.id


def _prepare(
    client, db_session, test_settings, *, max_attachment_mb: float | None = None
):
    _login(client, db_session)
    _seed_book_resource_asset(db_session, test_settings)
    saved = client.put(
        "/api/email-settings",
        json={
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "security": "starttls",
                "username": "sender@example.com",
                "password": "smtp-secret",
                "fromEmail": "sender@example.com",
                "fromName": "二毛图书",
                "maxAttachmentMb": max_attachment_mb,
            },
            "kindle": {"email": "reader_123@kindle.com"},
        },
    )
    assert saved.status_code == 200, saved.text
    personal = client.put(
        "/api/kindle-settings", json={"email": "reader_123@kindle.com"}
    )
    assert personal.status_code == 200, personal.text


def _enqueue(client, *, book_id: str = "book-kindle", asset_id: str = "asset-kindle"):
    response = client.post(
        "/api/kindle-send-tasks",
        json={"bookId": book_id, "assetId": asset_id},
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["data"]["task"]


def test_kindle_asset_path_must_remain_inside_its_library_root(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    asset = root / "book.epub"
    asset.write_bytes(b"book")

    assert (
        kindle_queue._library_asset_path(
            {"libraryRoot": str(root), "sourceRelativePath": "book.epub"}
        )
        == asset.resolve()
    )
    assert (
        kindle_queue._library_asset_path(
            {"libraryRoot": str(root), "sourceRelativePath": "../outside.epub"}
        )
        is None
    )
    assert (
        kindle_queue._library_asset_path(
            {"libraryRoot": str(root), "sourceRelativePath": str(asset.resolve())}
        )
        is None
    )


def test_recover_interrupted_kindle_tasks_uses_set_based_dml(db_session) -> None:
    task_ids = tuple(f"bulk-kindle-{index}" for index in range(25))
    db_session.add_all(
        [
            KindleSendTask(
                id=task_id,
                book_title=f"Book {index}",
                file_name=f"book-{index}.epub",
                format="EPUB",
                mime_type="application/epub+zip",
                size_bytes=1,
                recipient_email="reader@example.test",
                subject=f"Book {index}",
                status="sending",
            )
            for index, task_id in enumerate(task_ids)
        ]
    )
    db_session.commit()

    recover_interrupted_kindle_tasks_command(
        db_session,
        task_ids=task_ids,
        error_message="interrupted",
        timestamp=datetime.now(UTC),
        events=(),
    )

    rows = db_session.scalars(
        select(KindleSendTask).where(KindleSendTask.id.in_(task_ids))
    ).all()
    assert {row.status for row in rows} == {"unknown"}
    assert {row.error_message for row in rows} == {"interrupted"}


def test_enqueue_deduplicates_and_rejects_unsupported_assets(
    client, db_session, test_settings
) -> None:
    _prepare(client, db_session, test_settings)
    created = _enqueue(client)
    assert created["status"] == "queued"
    assert created["assetId"] == "asset-kindle"
    duplicate = _enqueue(client)
    assert duplicate["id"] == created["id"]
    assert client.get("/api/kindle-send-tasks").json()["data"]["total"] == 1

    comic_path = (
        test_settings.resolved_storage_root / "books" / "book-kindle" / "comic.cbz"
    )
    comic_path.write_bytes(b"comic")
    comic_node = _node("kindle-comic-node", "books/book-kindle/comic.cbz")
    comic_resource = LibraryReadableResource(
        id="resource-comic",
        library_id="test-library",
        book_id="book-kindle",
        source_node_id=comic_node.id,
        adapter_id="comic-archive",
        adapter_version="1",
        media_kind="COMIC",
        format="CBZ",
        enablement_state="ENABLED",
        import_state="READY",
    )
    db_session.add_all([comic_node, comic_resource])
    db_session.flush()
    db_session.add_all(
        [
            LibraryReadableResourceMetadata(
                resource_id=comic_resource.id,
                title="Comic",
            ),
            LibraryResourceAsset(
                id="asset-comic",
                library_id="test-library",
                resource_id=comic_resource.id,
                source_node_id=comic_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            ),
        ]
    )
    db_session.flush()
    db_session.commit()
    unsupported = client.post(
        "/api/kindle-send-tasks",
        json={"bookId": "book-kindle", "assetId": "asset-comic"},
    )
    assert unsupported.status_code == 400
    assert "EPUB 和 PDF" in unsupported.json()["error"]["message"]


def test_worker_submits_resource_asset_and_masks_recipient_in_events(
    client, db_session, test_settings, monkeypatch
) -> None:
    _prepare(client, db_session, test_settings)
    task = _enqueue(client)

    class FakeSmtp:
        def __init__(self) -> None:
            self.messages: list[EmailMessage] = []

        def send_message(self, message: EmailMessage):
            self.messages.append(message)
            return {}

        def quit(self):
            return 221, b"bye"

        def close(self):
            return None

    fake = FakeSmtp()
    monkeypatch.setattr(kindle_queue, "open_smtp_connection", lambda _config: fake)

    assert process_next_kindle_send_task(db_session, test_settings) is True
    stored = db_session.get(KindleSendTask, task["id"])
    assert stored is not None
    assert stored.status == "sent"
    assert stored.asset_id == "asset-kindle"
    assert stored.resource_id == "resource-kindle"
    assert len(fake.messages) == 1
    assert fake.messages[0]["To"] == "reader_123@kindle.com"
    assert fake.messages[0].get_payload()[-1].get_filename() == "book.epub"
    event_metadata = "\n".join(
        str(row.metadata_json)
        for row in db_session.scalars(
            select(SystemEvent).where(SystemEvent.source == "kindle")
        ).all()
    )
    assert "reader_123@kindle.com" not in event_metadata
    assert "r***3@kindle.com" in event_metadata


def test_worker_does_not_retry_permanent_authentication_failure(
    client, db_session, test_settings, monkeypatch
) -> None:
    _prepare(client, db_session, test_settings)
    task = _enqueue(client)

    class FailingSmtp:
        def send_message(self, _message):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

        def quit(self):
            return 221, b"bye"

        def close(self):
            return None

    monkeypatch.setattr(
        kindle_queue,
        "open_smtp_connection",
        lambda _config: FailingSmtp(),
    )
    assert process_next_kindle_send_task(db_session, test_settings) is True

    stored = db_session.get(KindleSendTask, task["id"])
    assert stored is not None
    assert stored.status == "failed"
    assert stored.attempt_count == 1
    assert stored.next_attempt_at is None


def test_worker_retries_transient_failure_and_recovers_interrupted_send(
    client, db_session, test_settings, monkeypatch
) -> None:
    _prepare(client, db_session, test_settings)
    task = _enqueue(client)

    class FailingSmtp:
        def send_message(self, _message):
            raise smtplib.SMTPServerDisconnected("temporary outage")

        def quit(self):
            return 221, b"bye"

        def close(self):
            return None

    monkeypatch.setattr(
        kindle_queue, "open_smtp_connection", lambda _config: FailingSmtp()
    )
    for expected_attempt in (1, 2, 3):
        assert process_next_kindle_send_task(db_session, test_settings) is True
        stored = db_session.get(KindleSendTask, task["id"])
        assert stored is not None
        assert stored.attempt_count == expected_attempt
        if expected_attempt < 3:
            stored.next_attempt_at = None
            db_session.commit()
    assert stored.status == "failed"

    stored.status = "sending"
    db_session.commit()
    assert recover_interrupted_tasks(db_session) == 1
    # Recovery deliberately closes/opens the unit-of-work boundary; reload
    # the canonical task rather than refreshing an expunged ORM instance.
    stored = db_session.get(KindleSendTask, task["id"])
    assert stored is not None
    assert stored.status == "unknown"
    assert "结果未知" in str(stored.error_message)

    retried = client.post(f"/api/kindle-send-tasks/{task['id']}/retry")
    assert retried.status_code == 200
    cancelled = client.post(f"/api/kindle-send-tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200
    deleted = client.delete(f"/api/kindle-send-tasks/{task['id']}")
    assert deleted.status_code == 200
