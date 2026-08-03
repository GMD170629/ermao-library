from __future__ import annotations

import json

from app.core.auth import hash_password
from app.db.base import Base
from app.db.bootstrap import apply_schema
from app.models.auth import User
from app.models.import_pipeline import ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import MonitorFolder
from sqlalchemy import text

PASSWORD = "starshipnas"


def _prepare_schema(db_session) -> User:
    db_session.rollback()
    Base.metadata.create_all(db_session.get_bind())
    apply_schema(db_session.get_bind())
    admin = User(
        email="admin@example.com",
        name="管理员",
        password_hash=hash_password(PASSWORD),
        role="admin",
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def _login(client, email: str, password: str = PASSWORD) -> None:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text


def _logout(client) -> None:
    response = client.post("/api/auth/logout")
    assert response.status_code == 200


def _seed_library(db_session) -> None:
    folders = [
        MonitorFolder(id="folder-a", name="A 书库", root_path="/library/folder-a"),
        MonitorFolder(id="folder-b", name="B 书库", root_path="/library/folder-b"),
    ]
    works = [
        LibraryWork(
            id="work-a",
            monitor_folder_id="folder-a",
            origin="WATCH",
            title="A 范围作品",
            normalized_title="A 范围作品",
            author="作者",
            normalized_author="作者",
            tags="[]",
            organized=True,
        ),
        LibraryWork(
            id="work-b",
            monitor_folder_id="folder-b",
            origin="WATCH",
            title="B 范围作品",
            normalized_title="B 范围作品",
            author="作者",
            normalized_author="作者",
            tags="[]",
            organized=True,
        ),
        LibraryWork(
            id="work-merged",
            monitor_folder_id="folder-a",
            origin="WATCH",
            title="跨范围合并作品",
            normalized_title="跨范围合并作品",
            author="作者",
            normalized_author="作者",
            tags="[]",
            organized=True,
        ),
    ]
    media_versions = [
        LibraryMediaVersion(id="media-a", work_id="work-a", media_kind="EBOOK"),
        LibraryMediaVersion(id="media-b", work_id="work-b", media_kind="EBOOK"),
        LibraryMediaVersion(
            id="media-merged", work_id="work-merged", media_kind="EBOOK"
        ),
    ]
    volume_specs = (
        ("volume-a", "media-a", "folder-a", "A 电子书", 0),
        ("volume-b", "media-b", "folder-b", "B 电子书", 0),
        ("volume-merged-a", "media-merged", "folder-a", "合并 A 电子书", 0),
        ("volume-merged-b", "media-merged", "folder-b", "合并 B 电子书", 1),
    )
    volumes = [
        LibraryVolume(
            id=volume_id,
            media_version_id=media_version_id,
            monitor_folder_id=folder_id,
            origin="WATCH",
            title=title,
            sort_order=sort_order,
            format="EPUB",
            resource_key=f"test:{volume_id}",
            import_status="COMPLETED",
        )
        for volume_id, media_version_id, folder_id, title, sort_order in volume_specs
    ]
    files = [
        LibraryFile(
            id=f"file-{volume_id}",
            volume_id=volume_id,
            path=f"library/{folder_id}/{volume_id}.epub",
            hash_status="COMPLETED",
            mtime_ms=1,
            kind="EPUB",
            mime_type="application/epub+zip",
            size_bytes=10,
            sort_order=0,
        )
        for volume_id, _, folder_id, _, _ in volume_specs
    ]
    tasks = [
        ImportTask(
            id=task_id,
            monitor_folder_id=folder_id,
            origin="WATCH",
            status="COMPLETED",
            original_name=f"{task_id}.epub",
            source_path=f"/library/{folder_id}/{task_id}.epub",
            processed_asset_count=1,
            progress=100,
            attempts=1,
        )
        for task_id, folder_id in (("task-a", "folder-a"), ("task-b", "folder-b"))
    ]
    db_session.add_all(folders + works + media_versions + volumes + files + tasks)
    db_session.commit()


def _create_user(
    client,
    *,
    email: str,
    role: str = "member",
    can_manage_system: bool = False,
    folder_ids: list[str] | None = None,
    manual: bool = False,
    locale: str = "zh-CN",
) -> dict:
    response = client.post(
        "/api/admin/users",
        json={
            "name": email.split("@")[0],
            "email": email,
            "password": PASSWORD,
            "role": role,
            "canManageSystem": can_manage_system,
            "canViewManualImports": manual,
            "monitorFolderIds": folder_ids or [],
            "locale": locale,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["user"]


def test_admin_user_lifecycle_and_last_active_admin_guard(client, db_session) -> None:
    admin = _prepare_schema(db_session)
    _seed_library(db_session)
    _login(client, admin.email)

    member = _create_user(
        client,
        email="member@example.com",
        can_manage_system=True,
        folder_ids=["folder-a"],
        manual=True,
        locale="en-US",
    )
    assert member["role"] == "member"
    assert member["authorization"]["monitorFolderIds"] == ["folder-a"]
    assert member["authorization"]["canManageSystem"] is True
    assert member["locale"] == "en-US"

    self_demotion = client.patch(
        f"/api/admin/users/{admin.id}", json={"role": "member"}
    )
    assert self_demotion.status_code == 400
    assert self_demotion.json()["error"]["code"] == "CANNOT_CHANGE_SELF_ADMIN"

    second_admin = _create_user(client, email="admin2@example.com", role="admin")
    demoted = client.patch(
        f"/api/admin/users/{second_admin['id']}", json={"role": "member"}
    )
    assert demoted.status_code == 200
    last_admin_disable = client.patch(
        f"/api/admin/users/{admin.id}", json={"status": "disabled"}
    )
    assert last_admin_disable.status_code == 400

    reset = client.put(
        f"/api/admin/users/{member['id']}/password",
        json={"password": "new-starship-password"},
    )
    assert reset.status_code == 200
    assert reset.json()["data"]["sessionsRevoked"] is True

    disabled = client.patch(
        f"/api/admin/users/{member['id']}", json={"status": "disabled"}
    )
    assert disabled.status_code == 200
    _logout(client)
    rejected = client.post(
        "/api/auth/login",
        json={"email": member["email"], "password": "new-starship-password"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "ACCOUNT_DISABLED"
    _login(client, admin.email)
    deleted = client.request(
        "DELETE",
        f"/api/admin/users/{member['id']}",
        json={"confirmation": member["email"]},
    )
    assert deleted.status_code == 200
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM `UserPreference` WHERE `userId` = :user_id"),
            {"user_id": member["id"]},
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM `UserMonitorFolderAccess` WHERE `userId` = :user_id"
            ),
            {"user_id": member["id"]},
        ).scalar()
        == 0
    )
    deletion_audit_target = db_session.execute(
        text(
            "SELECT `targetId` FROM `SystemEvent` "
            "WHERE `action` = 'user.deleted' ORDER BY `createdAt` DESC LIMIT 1"
        )
    ).scalar()
    assert deletion_audit_target
    assert deletion_audit_target != member["id"]
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM `SystemEvent` "
                "WHERE `actorId` = :user_id OR `targetId` = :user_id"
            ),
            {"user_id": member["id"]},
        ).scalar()
        == 0
    )


def test_folder_scope_system_manager_boundary_and_atomic_bulk_rejection(
    client, db_session
) -> None:
    admin = _prepare_schema(db_session)
    _seed_library(db_session)
    _login(client, admin.email)
    manager = _create_user(
        client,
        email="manager@example.com",
        can_manage_system=True,
        folder_ids=["folder-a"],
    )
    member = _create_user(client, email="reader@example.com", folder_ids=["folder-a"])
    _logout(client)

    _login(client, manager["email"])
    works = client.get("/api/works?pageSize=100")
    assert works.status_code == 200
    assert {item["id"] for item in works.json()["data"]["books"]} == {
        "work-a",
        "work-merged",
    }

    db_session.execute(
        text(
            "UPDATE `LibraryVolume` SET `publisher` = CASE "
            "WHEN `id` = 'volume-a' THEN 'Middle Press' "
            "WHEN `id` = 'volume-merged-a' THEN 'Zulu Press' "
            "WHEN `id` = 'volume-merged-b' THEN 'Alpha Private Press' "
            "ELSE `publisher` END "
            "WHERE `id` IN ('volume-a', 'volume-merged-a', 'volume-merged-b')"
        )
    )
    db_session.commit()
    publisher_sorted = client.get(
        "/api/works",
        params={
            "sort": "publisher",
            "sortDirection": "asc",
            "view": "management",
            "pageSize": 100,
        },
    )
    assert publisher_sorted.status_code == 200
    assert [item["id"] for item in publisher_sorted.json()["data"]["books"]] == [
        "work-a",
        "work-merged",
    ]

    merged = client.get("/api/works/work-merged")
    assert merged.status_code == 200
    merged_payload = merged.json()["data"]["book"]
    assert {item["mediaKind"] for item in merged_payload["mediaVersions"]} == {"EBOOK"}
    merged_volumes = merged_payload["mediaVersions"][0]["volumes"]
    assert {volume["id"] for volume in merged_volumes} == {"volume-merged-a"}
    assert "folder-b" not in json.dumps(merged_payload)

    assert client.get("/api/works/work-b").status_code == 404
    assert client.get("/api/files/file-volume-b").status_code == 404
    assert client.get("/api/management/overview").status_code == 200
    assert client.get("/api/admin/users").status_code == 403
    import_tasks = client.get("/api/import-tasks?pageSize=100")
    assert import_tasks.status_code == 200
    assert {item["id"] for item in import_tasks.json()["data"]["tasks"]} == {"task-a"}
    rescan = client.post("/api/import-tasks/rescan")
    assert rescan.status_code == 202
    assert {job["monitorFolderId"] for job in rescan.json()["data"]["jobs"]} == {
        "folder-a"
    }

    allowed_edit = client.patch("/api/works/work-a", json={"author": "新作者"})
    assert allowed_edit.status_code == 200
    denied_edit = client.patch("/api/works/work-b", json={"author": "越权作者"})
    assert denied_edit.status_code == 404
    atomic_bulk = client.post(
        "/api/works/bulk",
        json={
            "ids": ["work-a", "work-b"],
            "action": "update_metadata",
            "fields": {"author": "不应写入"},
        },
    )
    assert atomic_bulk.status_code in {403, 404}
    assert (
        db_session.execute(
            text("SELECT `author` FROM `LibraryWork` WHERE `id` = 'work-a'")
        ).scalar()
        == "新作者"
    )
    _logout(client)

    _login(client, member["email"])
    assert client.get("/api/management/overview").status_code == 403
    assert client.get("/api/organize/jobs").status_code == 403
    assert client.get("/api/import-tasks").status_code == 403
    kindle_tasks = client.get("/api/kindle-send-tasks")
    assert kindle_tasks.status_code == 200
    assert kindle_tasks.json()["data"]["tasks"] == []
    assert client.get("/api/email-settings").status_code == 403
    assert (
        client.patch("/api/works/work-a", json={"author": "普通用户"}).status_code
        == 403
    )
    inaccessible_source_shelf = client.post(
        "/api/shelves",
        json={
            "name": "未授权来源",
            "kind": "SMART",
            "rules": {
                "conditions": [
                    {
                        "field": "monitorFolder",
                        "operator": "equals",
                        "value": "folder-b",
                    }
                ]
            },
        },
    )
    assert inaccessible_source_shelf.status_code == 201
    assert inaccessible_source_shelf.json()["data"]["shelf"]["bookIds"] == []


def test_preferences_progress_bookmarks_and_shelves_are_isolated(
    client, db_session
) -> None:
    admin = _prepare_schema(db_session)
    _seed_library(db_session)
    _login(client, admin.email)
    first = _create_user(
        client, email="first@example.com", folder_ids=["folder-a"], locale="en-US"
    )
    second = _create_user(
        client, email="second@example.com", folder_ids=["folder-a"], locale="zh-CN"
    )
    _logout(client)

    _login(client, first["email"])
    preferences = client.patch(
        "/api/auth/preferences",
        json={
            "preferences": {
                "locale": "en-US",
                "library.view": "list",
                "library.sort": "title",
                "library.sortDirection": "desc",
                "audio.playbackRate": 1.5,
            }
        },
    )
    assert preferences.status_code == 200
    assert preferences.json()["data"]["preferences"]["library.sort"] == "title"
    assert preferences.json()["data"]["preferences"]["library.sortDirection"] == "desc"
    shelf = client.post(
        "/api/shelves", json={"name": "First shelf", "bookIds": ["work-a"]}
    )
    assert shelf.status_code == 201
    bootstrap = client.get("/api/reader/v3/volumes/volume-a/bootstrap")
    assert bootstrap.status_code == 200
    content_fingerprint = bootstrap.json()["data"]["contentFingerprint"]
    bookmark = client.put(
        "/api/reader/v3/volumes/volume-a/bookmarks",
        json={
            "contentFingerprint": content_fingerprint,
            "bookmarks": [
                {
                    "id": "reflowable:epub:position:chapter.xhtml:0.25",
                    "location": {
                        "type": "epub",
                        "cfi": "epubcfi(/6/2!/4/1:0)",
                        "href": "chapter.xhtml",
                        "progression": 0.25,
                    },
                    "label": "第一章",
                    "percent": 25,
                    "createdAt": "2026-07-23T00:00:00Z",
                }
            ],
        },
    )
    assert bookmark.status_code == 200, bookmark.text
    assert (
        bookmark.json()["data"]["bookmarks"][0]["location"]["cfi"]
        == "epubcfi(/6/2!/4/1:0)"
    )
    db_session.add(
        LibraryReadingProgress(
            id="progress-first",
            user_id=first["id"],
            volume_id="volume-a",
            reader_type="epub",
            position="chapter.xhtml",
            percent=50,
            extra="{}",
            schema_version=3,
            content_fingerprint=content_fingerprint,
            location_type="epub",
            location_json=json.dumps(
                {"type": "epub", "href": "chapter.xhtml", "progression": 0.5}
            ),
            mutation_id="seed-first-progress",
            client_id="test",
            client_sequence=1,
        )
    )
    db_session.commit()
    first_work = client.get("/api/works/work-a").json()["data"]["book"]
    assert first_work["completed"] is False
    assert first_work["mediaVersions"][0]["volumes"][0]["progress"] == 50
    _logout(client)

    _login(client, second["email"])
    second_preferences = client.get("/api/auth/preferences").json()["data"][
        "preferences"
    ]
    assert second_preferences["locale"] == "zh-CN"
    assert "library.view" not in second_preferences
    assert "library.sort" not in second_preferences
    assert "library.sortDirection" not in second_preferences
    second_shelves = client.get("/api/shelves").json()["data"]["shelves"]
    assert second_shelves == []
    second_bookmarks = client.get(
        "/api/reader/v3/volumes/volume-a/bookmarks",
        params={"contentFingerprint": content_fingerprint},
    )
    assert second_bookmarks.status_code == 200
    assert second_bookmarks.json()["data"]["bookmarks"] == []
    second_work = client.get("/api/works/work-a").json()["data"]["book"]
    assert second_work["completed"] is False
    assert second_work["mediaVersions"][0]["volumes"][0]["progress"] == 0
