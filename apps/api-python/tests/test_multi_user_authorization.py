from __future__ import annotations

import json

from sqlalchemy import text

from app.core.auth import hash_password
from app.db.base import Base
from app.db.bootstrap import apply_schema
from app.models.auth import User

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
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _logout(client) -> None:
    response = client.post("/api/auth/logout")
    assert response.status_code == 200


def _seed_library(db_session) -> None:
    for folder_id, name in (("folder-a", "A 书库"), ("folder-b", "B 书库")):
        db_session.execute(
            text(
                "INSERT INTO `MonitorFolder` "
                "(`id`, `name`, `rootPath`, `enabled`, `ignoreHidden`, `minFileSizeBytes`, "
                "`createdAt`, `updatedAt`) "
                "VALUES (:id, :name, :path, 1, 1, 10240, "
                "'2026-07-23T00:00:00Z', '2026-07-23T00:00:00Z')"
            ),
            {"id": folder_id, "name": name, "path": f"/library/{folder_id}"},
        )
    for work_id, title, folder_id in (
        ("work-a", "A 范围作品", "folder-a"),
        ("work-b", "B 范围作品", "folder-b"),
        ("work-merged", "跨范围合并作品", "folder-a"),
    ):
        db_session.execute(
            text(
                "INSERT INTO `LibraryWork` "
                "(`id`, `monitorFolderId`, `origin`, `title`, `normalizedTitle`, `author`, `workType`, "
                "`status`, `tags`, `hidden`, `organized`, `createdAt`, `updatedAt`) "
                "VALUES (:id, :folder_id, 'WATCH', :title, :title, '作者', 'EPUB', "
                "'UNREAD', '[]', 0, 1, '2026-07-23T00:00:00Z', '2026-07-23T00:00:00Z')"
            ),
            {"id": work_id, "folder_id": folder_id, "title": title},
        )
    editions = (
        ("edition-a", "work-a", "folder-a", "A 版本"),
        ("edition-b", "work-b", "folder-b", "B 版本"),
        ("edition-merged-a", "work-merged", "folder-a", "合并 A 版本"),
        ("edition-merged-b", "work-merged", "folder-b", "合并 B 版本"),
    )
    for index, (edition_id, work_id, folder_id, version_name) in enumerate(editions):
        db_session.execute(
            text(
                "INSERT INTO `LibraryEdition` "
                "(`id`, `workId`, `monitorFolderId`, `origin`, `mediaKind`, `format`, `versionName`, "
                "`versionKey`, `importStatus`, `primary`, `hidden`, `createdAt`, `updatedAt`) "
                "VALUES (:id, :work_id, :folder_id, 'WATCH', 'EBOOK', 'EPUB', :version_name, "
                ":version_key, 'COMPLETED', :primary, 0, "
                "'2026-07-23T00:00:00Z', '2026-07-23T00:00:00Z')"
            ),
            {
                "id": edition_id,
                "work_id": work_id,
                "folder_id": folder_id,
                "version_name": version_name,
                "version_key": f"key-{edition_id}",
                "primary": 1 if index != 3 else 0,
            },
        )
        db_session.execute(
            text(
                "INSERT INTO `LibraryFile` "
                "(`id`, `editionId`, `path`, `kind`, `mimeType`, `sizeBytes`, `sortOrder`, "
                "`createdAt`, `updatedAt`) "
                "VALUES (:id, :edition_id, :path, 'EPUB', 'application/epub+zip', 10, 0, "
                "'2026-07-23T00:00:00Z', '2026-07-23T00:00:00Z')"
            ),
            {
                "id": f"file-{edition_id}",
                "edition_id": edition_id,
                "path": f"library/{folder_id}/{edition_id}.epub",
            },
        )
    for task_id, folder_id in (("task-a", "folder-a"), ("task-b", "folder-b")):
        db_session.execute(
            text(
                "INSERT INTO `ImportTask` "
                "(`id`, `monitorFolderId`, `origin`, `status`, `originalName`, `sourcePath`, "
                "`taskKind`, `assetCount`, `processedAssetCount`, `progress`, `duplicate`, "
                "`duration`, `retryable`, `attempts`, `createdAt`, `updatedAt`) "
                "VALUES (:id, :folder_id, 'WATCH', 'COMPLETED', :name, :path, "
                "'FILE', 1, 1, 100, 0, 0, 0, 1, "
                "'2026-07-23T00:00:00Z', '2026-07-23T00:00:00Z')"
            ),
            {
                "id": task_id,
                "folder_id": folder_id,
                "name": f"{task_id}.epub",
                "path": f"/library/{folder_id}/{task_id}.epub",
            },
        )
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

    self_demotion = client.patch(f"/api/admin/users/{admin.id}", json={"role": "member"})
    assert self_demotion.status_code == 400
    assert self_demotion.json()["error"]["code"] == "CANNOT_CHANGE_SELF_ADMIN"

    second_admin = _create_user(client, email="admin2@example.com", role="admin")
    demoted = client.patch(f"/api/admin/users/{second_admin['id']}", json={"role": "member"})
    assert demoted.status_code == 200
    last_admin_disable = client.patch(f"/api/admin/users/{admin.id}", json={"status": "disabled"})
    assert last_admin_disable.status_code == 400

    reset = client.put(
        f"/api/admin/users/{member['id']}/password",
        json={"password": "new-starship-password"},
    )
    assert reset.status_code == 200
    assert reset.json()["data"]["sessionsRevoked"] is True

    disabled = client.patch(f"/api/admin/users/{member['id']}", json={"status": "disabled"})
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
    assert db_session.execute(
        text("SELECT COUNT(*) FROM `UserPreference` WHERE `userId` = :user_id"),
        {"user_id": member["id"]},
    ).scalar() == 0
    assert db_session.execute(
        text("SELECT COUNT(*) FROM `UserMonitorFolderAccess` WHERE `userId` = :user_id"),
        {"user_id": member["id"]},
    ).scalar() == 0
    deletion_audit_target = db_session.execute(
        text(
            "SELECT `targetId` FROM `SystemEvent` "
            "WHERE `action` = 'user.deleted' ORDER BY `createdAt` DESC LIMIT 1"
        )
    ).scalar()
    assert deletion_audit_target
    assert deletion_audit_target != member["id"]
    assert db_session.execute(
        text(
            "SELECT COUNT(*) FROM `SystemEvent` "
            "WHERE `actorId` = :user_id OR `targetId` = :user_id"
        ),
        {"user_id": member["id"]},
    ).scalar() == 0


def test_folder_scope_system_manager_boundary_and_atomic_bulk_rejection(client, db_session) -> None:
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
    assert {item["id"] for item in works.json()["data"]["books"]} == {"work-a", "work-merged"}

    merged = client.get("/api/works/work-merged")
    assert merged.status_code == 200
    merged_payload = merged.json()["data"]["book"]
    assert {edition["id"] for edition in merged_payload["editions"]} == {"edition-merged-a"}
    assert "folder-b" not in json.dumps(merged_payload)

    assert client.get("/api/works/work-b").status_code == 404
    assert client.get("/api/files/file-edition-b").status_code == 404
    assert client.get("/api/management/overview").status_code == 200
    assert client.get("/api/admin/users").status_code == 403
    import_tasks = client.get("/api/import-tasks?pageSize=100")
    assert import_tasks.status_code == 200
    assert {item["id"] for item in import_tasks.json()["data"]["tasks"]} == {"task-a"}
    rescan = client.post("/api/import-tasks/rescan")
    assert rescan.status_code == 200
    rescan_request = json.loads(
        db_session.execute(
            text("SELECT `value` FROM `SystemSetting` WHERE `key` = 'monitor.rescanRequestedAt'")
        ).scalar()
    )
    assert rescan_request["monitorFolderIds"] == ["folder-a"]

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
    assert db_session.execute(
        text("SELECT `author` FROM `LibraryWork` WHERE `id` = 'work-a'")
    ).scalar() == "新作者"
    _logout(client)

    _login(client, member["email"])
    assert client.get("/api/management/overview").status_code == 403
    assert client.get("/api/organize/jobs").status_code == 403
    assert client.get("/api/import-tasks").status_code == 403
    kindle_tasks = client.get("/api/kindle-send-tasks")
    assert kindle_tasks.status_code == 200
    assert kindle_tasks.json()["data"]["tasks"] == []
    assert client.get("/api/email-settings").status_code == 403
    assert client.patch("/api/works/work-a", json={"author": "普通用户"}).status_code == 403
    personal_status = client.patch("/api/works/work-a", json={"status": "FINISHED"})
    assert personal_status.status_code == 200
    assert db_session.execute(
        text("SELECT `status` FROM `LibraryWork` WHERE `id` = 'work-a'")
    ).scalar() == "UNREAD"
    bulk_status = client.post(
        "/api/works/bulk",
        json={"ids": ["work-a"], "action": "set_status", "status": "FINISHED"},
    )
    assert bulk_status.status_code == 200
    assert db_session.execute(
        text("SELECT `status` FROM `LibraryWork` WHERE `id` = 'work-a'")
    ).scalar() == "UNREAD"
    finished_shelf = client.post(
        "/api/shelves",
        json={"name": "已读", "kind": "SMART", "rules": {"statuses": ["FINISHED"]}},
    )
    assert finished_shelf.status_code == 201
    assert finished_shelf.json()["data"]["shelf"]["bookIds"] == ["work-a"]
    inaccessible_source_shelf = client.post(
        "/api/shelves",
        json={
            "name": "未授权来源",
            "kind": "SMART",
            "rules": {
                "conditions": [
                    {"field": "monitorFolder", "operator": "equals", "value": "folder-b"}
                ]
            },
        },
    )
    assert inaccessible_source_shelf.status_code == 201
    assert inaccessible_source_shelf.json()["data"]["shelf"]["bookIds"] == []


def test_preferences_progress_bookmarks_and_shelves_are_isolated(client, db_session) -> None:
    admin = _prepare_schema(db_session)
    _seed_library(db_session)
    _login(client, admin.email)
    first = _create_user(client, email="first@example.com", folder_ids=["folder-a"], locale="en-US")
    second = _create_user(client, email="second@example.com", folder_ids=["folder-a"], locale="zh-CN")
    _logout(client)

    _login(client, first["email"])
    preferences = client.patch(
        "/api/auth/preferences",
        json={"preferences": {"locale": "en-US", "library.view": "list", "audio.playbackRate": 1.5}},
    )
    assert preferences.status_code == 200
    shelf = client.post("/api/shelves", json={"name": "First shelf", "bookIds": ["work-a"]})
    assert shelf.status_code == 201
    bookmark = client.put(
        "/api/reader/v2/editions/edition-a/bookmarks",
        json={
            "contentFingerprint": "sha256:test",
            "bookmarks": [
                {
                    "id": "epub:position:chapter.xhtml:0:0.25",
                    "location": {
                        "kind": "epub",
                        "href": "chapter.xhtml",
                        "spineIndex": 0,
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
    db_session.execute(
        text(
            "INSERT INTO `LibraryReadingProgress` "
            "(`id`, `userId`, `workId`, `editionId`, `readerType`, `position`, `percent`, `extra`, "
            "`schemaVersion`, `createdAt`, `updatedAt`) "
            "VALUES ('progress-first', :user_id, 'work-a', 'edition-a', 'EPUB', 'chapter.xhtml', "
            "50, '{}', 2, '2026-07-23T00:00:00Z', '2026-07-23T00:00:00Z')"
        ),
        {"user_id": first["id"]},
    )
    db_session.commit()
    first_work = client.get("/api/works/work-a").json()["data"]["book"]
    assert first_work["progress"] == 50
    _logout(client)

    _login(client, second["email"])
    second_preferences = client.get("/api/auth/preferences").json()["data"]["preferences"]
    assert second_preferences["locale"] == "zh-CN"
    assert "library.view" not in second_preferences
    assert client.get("/api/shelves").json()["data"]["shelves"] == []
    second_bookmarks = client.get(
        "/api/reader/v2/editions/edition-a/bookmarks?contentFingerprint=sha256%3Atest"
    )
    assert second_bookmarks.status_code == 200
    assert second_bookmarks.json()["data"]["bookmarks"] == []
    second_work = client.get("/api/works/work-a").json()["data"]["book"]
    assert second_work["progress"] == 0
    assert second_work["statusValue"] == "UNREAD"
