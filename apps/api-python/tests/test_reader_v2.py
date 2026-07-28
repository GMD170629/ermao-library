import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.auth import hash_password
from app.models.auth import User
from app.bootstrap.reader import SqlAlchemyReaderProgressCursor
from app.modules.reader.public import ClaimClientSequence, ClaimClientSequenceCommand
from app.modules.reader.presentation.v2_schemas import (
    ReaderPreferences,
    ReaderServerPreferences,
)
from tests.test_worker_importer import create_worker_tables, write_comic_fixture


def test_reader_v2_openapi_exposes_generated_request_and_response_contracts(client):
    schema = client.get("/openapi.json").json()

    progress_path = schema["paths"]["/api/reader/v2/editions/{edition_id}/progress"]["put"]
    request_schema = progress_path["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/ReaderProgressPut")
    required = set(schema["components"]["schemas"]["ReaderProgressPut"]["required"])
    assert required == {
        "schemaVersion",
        "userId",
        "mutationId",
        "clientId",
        "clientSequence",
        "contentFingerprint",
        "location",
        "percent",
    }
    bootstrap_response = schema["paths"]["/api/reader/v2/editions/{edition_id}/bootstrap"]["get"]["responses"]["200"]
    assert bootstrap_response["content"]["application/json"]["schema"]["$ref"].endswith("/ReaderBootstrapResponse")
    edition_option = schema["components"]["schemas"]["ReaderEditionOption"]
    assert {"progress", "lastReadAt"}.issubset(edition_option["required"])
    assert edition_option["properties"]["progress"]["minimum"] == 0
    assert edition_option["properties"]["progress"]["maximum"] == 100
    comic_location = schema["components"]["schemas"]["ComicLocation"]
    assert set(comic_location["required"]) == {"type", "volumeId", "pageIndex"}
    appearance = schema["components"]["schemas"]["AppearancePreferences"]
    assert appearance["properties"]["theme"]["default"] == "warm"
    epub_preferences = schema["components"]["schemas"]["EpubPreferences"]["properties"]
    assert epub_preferences["spreadMode"]["default"] == "single"
    assert set(epub_preferences["pageTurnAnimation"]["enum"]) == {"slide", "off"}
    comic_preferences = schema["components"]["schemas"]["ComicPreferences"]["properties"]
    assert set(comic_preferences["pageTurnAnimation"]["enum"]) == {"slide", "off"}
    assert schema["components"]["schemas"]["ReaderPreferences"]["properties"]["schemaVersion"]["default"] == 3
    assert schema["components"]["schemas"]["ReaderServerPreferences"]["properties"]["schemaVersion"]["default"] == 3
    assert schema["components"]["schemas"]["ReaderBootstrapData"]["properties"]["schemaVersion"]["default"] == 2
    assert schema["components"]["schemas"]["ReaderProgressPut"]["properties"]["schemaVersion"]["const"] == 2
    assert schema["components"]["schemas"]["ReaderProgressRecord"]["properties"]["schemaVersion"]["default"] == 2


def test_reader_preferences_migrate_v2_documents_to_v3():
    preferences = ReaderPreferences.model_validate(
        {
            "schemaVersion": 2,
            "epub": {"pageTurnAnimation": "kindle"},
            "comic": {"mode": "double"},
        }
    )
    dumped = preferences.model_dump(by_alias=True, mode="json")

    assert dumped["schemaVersion"] == 3
    assert dumped["epub"]["spreadMode"] == "single"
    assert dumped["epub"]["pageTurnAnimation"] == "slide"
    assert dumped["comic"]["mode"] == "double"
    assert dumped["comic"]["pageTurnAnimation"] == "slide"

    server_preferences = ReaderServerPreferences.model_validate(
        {"schemaVersion": 2, "settings": {"schemaVersion": 2, "epub": {"pageTurnAnimation": "kindle"}}}
    )
    assert server_preferences.schema_version == 3
    assert server_preferences.settings.schema_version == 3
    assert server_preferences.settings.epub.page_turn_animation == "slide"


def _login(client, db_session, email: str = "reader-v2@example.com") -> str:
    user = User(email=email, name="Reader V2", password_hash=hash_password("starshipnas"), role="admin")
    db_session.add(user)
    db_session.commit()
    response = client.post("/api/auth/login", json={"email": email, "password": "starshipnas"})
    assert response.status_code == 200
    return user.id


def _reader_tables(db_session) -> None:
    create_worker_tables(db_session)
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS ReaderPreference (
                id TEXT PRIMARY KEY, userId TEXT, readerType TEXT, settings TEXT,
                createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS LibraryReadingProgress (
                id TEXT PRIMARY KEY, userId TEXT, workId TEXT, editionId TEXT, volumeId TEXT,
                readerType TEXT, position TEXT, page INTEGER, percent REAL, extra TEXT,
                schemaVersion INTEGER DEFAULT 1, locationType TEXT, locationJson TEXT,
                contentFingerprint TEXT, mutationId TEXT, clientId TEXT, clientSequence INTEGER,
                createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS LibraryConsumptionState (
                id TEXT PRIMARY KEY, userId TEXT NOT NULL, workId TEXT NOT NULL,
                mediaKind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'UNREAD',
                lastEditionId TEXT, lastVolumeId TEXT, lastUnitId TEXT,
                createdAt TEXT, updatedAt TEXT,
                UNIQUE(userId, workId, mediaKind)
            )"""
        )
    )
    db_session.commit()


def _epub_fixture(db_session) -> None:
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, origin, title, normalizedTitle, author, normalizedAuthor, workType, status,
                publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverStatus,
                hidden, organized, primaryEditionId, mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-v2', 'MANUAL', 'V2 测试书', 'v2 测试书', '测试作者', '测试作者', 'EPUB', 'READING',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING',
                0, 1, 'edition-v2', 'epub:v2', '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryEdition (
                id, workId, origin, format, versionName, versionKey, importStatus, sizeBytes,
                pageCount, chapterCount, coverStatus, "primary", hidden, createdAt, updatedAt
            ) VALUES (
                'edition-v2', 'work-v2', 'MANUAL', 'EPUB', '默认版本', 'default', 'COMPLETED', 128,
                NULL, 2, 'PENDING', 1, 0, '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, editionId, title, volumeIndex, sortOrder, pageCount, chapterCount, createdAt, updatedAt
            ) VALUES (
                'volume-v2', 'edition-v2', '第 1 卷', 1, 1, NULL, 2,
                '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryFile (
                id, editionId, volumeId, path, filePathHash, fingerprint, fullHash, hashStatus,
                mtimeMs, kind, mimeType, sizeBytes, sortOrder, createdAt, updatedAt
            ) VALUES (
                'file-v2', 'edition-v2', 'volume-v2', '/library/v2.epub', 'path-v2',
                'partial-v2', NULL, 'PARTIAL_PENDING', 1720573200000, 'EPUB',
                'application/epub+zip', 128, 1, '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        )
    )
    for index, (title, href) in enumerate((("第一章", "one.xhtml"), ("第二章", "two.xhtml"))):
        db_session.execute(
            text(
                """INSERT INTO LibraryReadingUnit (
                    id, editionId, volumeId, fileId, unitType, title, href, sortOrder,
                    metadataJson, createdAt, updatedAt
                ) VALUES (
                    :id, 'edition-v2', 'volume-v2', 'file-v2', 'chapter', :title, :href, :sort_order,
                    '{}', '2026-07-10T01:00:00', '2026-07-10T01:00:00'
                )"""
            ),
            {"id": f"unit-v2-{index}", "title": title, "href": href, "sort_order": index},
        )
    db_session.commit()


def test_bootstrap_seeds_user_work_preferences_from_legacy_and_returns_typed_contract(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    db_session.execute(
        text(
            """INSERT INTO ReaderPreference (id, userId, readerType, settings, createdAt, updatedAt)
            VALUES ('legacy-pref', :user_id, 'ebook', :settings, '2026-07-01', '2026-07-01')"""
        ),
        {
            "user_id": user_id,
            "settings": json.dumps(
                {"theme": "warm", "fontSize": 21, "fontFamily": "songti", "ebookPageTurnAnimation": "off"},
                ensure_ascii=False,
            ),
        },
    )
    db_session.execute(
        text(
            """INSERT INTO ReaderPreference (id, userId, readerType, settings, createdAt, updatedAt)
            VALUES ('legacy-comic-pref', :user_id, 'comic', :settings, '2026-07-01', '2026-07-01')"""
        ),
        {"user_id": user_id, "settings": json.dumps({"zoom": 1.4})},
    )
    db_session.commit()

    response = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["schemaVersion"] == 2
    assert data["userId"] == user_id
    assert data["readerType"] == "epub"
    assert data["capabilities"]["supportsSpreads"] is True
    assert data["contentFingerprint"].startswith("sha256:")
    assert data["book"] == {
        "id": "work-v2",
        "title": "V2 测试书",
        "author": "测试作者",
        "coverUrl": "/api/works/work-v2/cover?size=large",
    }
    assert data["selectedVolume"]["id"] == "volume-v2"
    assert data["availableEditions"][0]["id"] == "edition-v2"
    assert data["availableEditions"][0]["volumes"][0]["id"] == "volume-v2"
    assert [unit["index"] for unit in data["units"]] == [1, 2]
    assert [unit["href"] for unit in data["units"]] == ["one.xhtml", "two.xhtml"]
    assert data["pages"] == []
    assert data["serverPreferences"]["schemaVersion"] == 3
    assert data["serverPreferences"]["settings"]["schemaVersion"] == 3
    assert data["serverPreferences"]["settings"]["appearance"]["theme"] == "warm"
    assert data["serverPreferences"]["settings"]["epub"]["fontSize"] == 21
    assert data["serverPreferences"]["settings"]["epub"]["pageWidth"] == 1350
    assert data["serverPreferences"]["settings"]["epub"]["fontFamily"] == "songti"
    assert data["serverPreferences"]["settings"]["epub"]["spreadMode"] == "single"
    assert data["serverPreferences"]["settings"]["epub"]["pageTurnAnimation"] == "off"
    assert data["serverPreferences"]["settings"]["comic"]["zoom"] == 1.4
    assert data["serverPreferences"]["settings"]["comic"]["pageTurnAnimation"] == "slide"

    stored = db_session.execute(
        text("SELECT userId, workId, schemaVersion, preferences FROM ReaderBookPreference")
    ).mappings().one()
    assert stored["userId"] == user_id
    assert stored["workId"] == "work-v2"
    assert stored["schemaVersion"] == 3
    stored_preferences = json.loads(stored["preferences"])
    assert stored_preferences["schemaVersion"] == 3
    assert stored_preferences["appearance"]["theme"] == "warm"

    db_session.execute(
        text("UPDATE ReaderPreference SET settings = :settings WHERE id = 'legacy-pref'"),
        {"settings": json.dumps({"theme": "black"})},
    )
    db_session.commit()
    inherited_again = client.get("/api/reader/v2/editions/edition-v2/bootstrap").json()["data"]
    assert inherited_again["serverPreferences"]["settings"]["appearance"]["theme"] == "warm"


def test_epub_locations_are_generated_once_and_shared_through_server_cache(client, db_session, test_settings):
    _reader_tables(db_session)
    _login(client, db_session)
    _epub_fixture(db_session)
    bootstrap = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2")
    fingerprint = bootstrap.json()["data"]["contentFingerprint"]
    request = {
        "cacheVersion": 2,
        "contentFingerprint": fingerprint,
        "breakSize": 1200,
    }

    first = client.post(
        "/api/reader/v2/editions/edition-v2/epub-locations/claim?volume=volume-v2",
        json=request,
    )
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "claimed"
    lease_token = first.json()["data"]["leaseToken"]

    concurrent = client.post(
        "/api/reader/v2/editions/edition-v2/epub-locations/claim?volume=volume-v2",
        json=request,
    )
    assert concurrent.status_code == 200
    assert concurrent.json()["data"]["status"] == "generating"

    serialized = json.dumps(["epubcfi(/6/2!/4/2:0)", "epubcfi(/6/4!/4/2:0)"])
    saved = client.put(
        "/api/reader/v2/editions/edition-v2/epub-locations?volume=volume-v2",
        json={**request, "leaseToken": lease_token, "serialized": serialized},
    )
    assert saved.status_code == 200
    assert saved.json()["data"] == {"status": "ready", "serialized": serialized}

    reused = client.post(
        "/api/reader/v2/editions/edition-v2/epub-locations/claim?volume=volume-v2",
        json=request,
    )
    assert reused.status_code == 200
    assert reused.json()["data"] == {"status": "ready", "serialized": serialized}
    assert list((test_settings.resolved_storage_root / "reader-indexes" / "epub-locations" / "v2").glob("*.json"))


def test_epub_locations_reject_wrong_content_and_invalid_payload(client, db_session):
    _reader_tables(db_session)
    _login(client, db_session)
    _epub_fixture(db_session)
    wrong = client.post(
        "/api/reader/v2/editions/edition-v2/epub-locations/claim?volume=volume-v2",
        json={"cacheVersion": 2, "contentFingerprint": "sha256:wrong", "breakSize": 1200},
    )
    assert wrong.status_code == 409

    bootstrap = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2")
    fingerprint = bootstrap.json()["data"]["contentFingerprint"]
    claim = client.post(
        "/api/reader/v2/editions/edition-v2/epub-locations/claim?volume=volume-v2",
        json={"cacheVersion": 2, "contentFingerprint": fingerprint, "breakSize": 1200},
    ).json()["data"]
    invalid = client.put(
        "/api/reader/v2/editions/edition-v2/epub-locations?volume=volume-v2",
        json={
            "cacheVersion": 2,
            "contentFingerprint": fingerprint,
            "breakSize": 1200,
            "leaseToken": claim["leaseToken"],
            "serialized": "[]",
        },
    )
    assert invalid.status_code == 422


def test_bootstrap_normalizes_and_rewrites_stored_v2_preferences(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    db_session.execute(
        text(
            """INSERT INTO ReaderBookPreference (
                id, userId, workId, schemaVersion, preferences, createdAt, updatedAt
            ) VALUES (
                :preference_id, :user_id, :work_id, 2, :preferences,
                :created_at, :updated_at
            )"""
        ),
        {
            "preference_id": "legacy-book-pref",
            "user_id": user_id,
            "work_id": "work-v2",
            "created_at": "2026-07-02T01:00:00",
            "updated_at": "2026-07-02T01:00:00",
            "preferences": json.dumps(
                {
                    "schemaVersion": 2,
                    "appearance": {"theme": "night"},
                    "epub": {"fontSize": 22, "pageTurnAnimation": "kindle"},
                    "comic": {"mode": "double"},
                }
            ),
        },
    )
    db_session.commit()

    response = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["schemaVersion"] == 2
    assert data["serverPreferences"]["schemaVersion"] == 3
    preferences = data["serverPreferences"]["settings"]
    assert preferences["schemaVersion"] == 3
    assert preferences["appearance"]["theme"] == "night"
    assert preferences["epub"]["fontSize"] == 22
    assert preferences["epub"]["spreadMode"] == "single"
    assert preferences["epub"]["pageTurnAnimation"] == "slide"
    assert preferences["comic"]["mode"] == "double"
    assert preferences["comic"]["pageTurnAnimation"] == "slide"

    stored = db_session.execute(
        text("SELECT schemaVersion, preferences, updatedAt FROM ReaderBookPreference WHERE id = :preference_id"),
        {"preference_id": "legacy-book-pref"},
    ).mappings().one()
    assert stored["schemaVersion"] == 3
    rewritten = json.loads(stored["preferences"])
    assert rewritten["schemaVersion"] == 3
    assert rewritten["epub"]["spreadMode"] == "single"
    assert rewritten["epub"]["pageTurnAnimation"] == "slide"
    assert rewritten["comic"]["pageTurnAnimation"] == "slide"
    assert stored["updatedAt"] == 1782954000000


def test_bootstrap_preserves_valid_fields_in_partially_invalid_stored_preferences(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    db_session.execute(
        text(
            """INSERT INTO ReaderBookPreference (
                id, userId, workId, schemaVersion, preferences, createdAt, updatedAt
            ) VALUES (
                :preference_id, :user_id, :work_id, 3, :preferences,
                :created_at, :updated_at
            )"""
        ),
        {
            "preference_id": "partially-corrupt-book-pref",
            "user_id": user_id,
            "work_id": "work-v2",
            "created_at": "2026-07-03T01:00:00",
            "updated_at": "2026-07-03T01:00:00",
            "preferences": json.dumps(
                {
                    "schemaVersion": 3,
                    "futureRoot": True,
                    "appearance": {"theme": "night", "futureAppearance": True},
                    "epub": {
                        "fontSize": 22,
                        "lineHeight": 99,
                        "flow": "scrolled",
                        "spreadMode": "double",
                        "pageTurnAnimation": "kindle",
                        "futureEpub": True,
                    },
                    "comic": {"mode": "double", "zoom": 99},
                    "pdf": "invalid-section",
                }
            ),
        },
    )
    db_session.commit()

    response = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2")

    assert response.status_code == 200
    preferences = response.json()["data"]["serverPreferences"]["settings"]
    assert preferences["schemaVersion"] == 3
    assert preferences["appearance"]["theme"] == "night"
    assert preferences["epub"]["fontSize"] == 22
    assert preferences["epub"]["lineHeight"] == 1.9
    assert preferences["epub"]["flow"] == "scrolled"
    assert preferences["epub"]["spreadMode"] == "double"
    assert preferences["epub"]["pageTurnAnimation"] == "slide"
    assert preferences["comic"]["mode"] == "double"
    assert preferences["comic"]["zoom"] == 1.0
    assert preferences["pdf"] == {"zoom": 1.0, "fit": "width"}

    stored = db_session.execute(
        text("SELECT schemaVersion, preferences, updatedAt FROM ReaderBookPreference WHERE id = :preference_id"),
        {"preference_id": "partially-corrupt-book-pref"},
    ).mappings().one()
    rewritten = json.loads(stored["preferences"])
    assert stored["schemaVersion"] == 3
    assert rewritten == preferences
    assert "futureRoot" not in rewritten
    assert "futureAppearance" not in rewritten["appearance"]
    assert "futureEpub" not in rewritten["epub"]
    assert stored["updatedAt"] == 1783040400000


def test_bootstrap_returns_each_edition_latest_progress_for_version_navigation(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryEdition (
                id, workId, origin, format, versionName, versionKey, importStatus, sizeBytes,
                pageCount, chapterCount, coverStatus, "primary", hidden, createdAt, updatedAt
            ) VALUES
                ('edition-v2-alt', 'work-v2', 'MANUAL', 'EPUB', '修订版', 'revision', 'COMPLETED', 256,
                 NULL, 3, 'PENDING', 0, 0, '2026-07-10T02:00:00', '2026-07-10T02:00:00'),
                ('edition-v2-unread', 'work-v2', 'MANUAL', 'PDF', '未读版', 'unread', 'COMPLETED', 512,
                 12, NULL, 'PENDING', 0, 0, '2026-07-10T03:00:00', '2026-07-10T03:00:00')
            """
        )
    )
    progress_rows = [
        {
            "id": "progress-current",
            "user_id": user_id,
            "edition_id": "edition-v2",
            "volume_id": "volume-v2",
            "percent": 31,
            "updated_at": "2026-07-08T04:00:00",
        },
        {
            "id": "progress-alt-older",
            "user_id": user_id,
            "edition_id": "edition-v2-alt",
            "volume_id": "alt-volume-1",
            "percent": 18,
            "updated_at": "2026-07-08T05:00:00",
        },
        {
            "id": "progress-alt-latest",
            "user_id": user_id,
            "edition_id": "edition-v2-alt",
            "volume_id": "alt-volume-2",
            "percent": 73.5,
            "updated_at": "2026-07-09T06:00:00",
        },
        {
            "id": "progress-other-user",
            "user_id": "another-user",
            "edition_id": "edition-v2-alt",
            "volume_id": "alt-volume-3",
            "percent": 99,
            "updated_at": "2026-07-10T07:00:00",
        },
    ]
    db_session.execute(
        text(
            """INSERT INTO LibraryReadingProgress (
                id, userId, workId, editionId, volumeId, readerType, position, page, percent,
                extra, createdAt, updatedAt
            ) VALUES (
                :id, :user_id, 'work-v2', :edition_id, :volume_id, 'epub', '0', NULL,
                :percent, '{}', :updated_at, :updated_at
            )"""
        ),
        progress_rows,
    )
    db_session.commit()

    response = client.get("/api/reader/v2/editions/edition-v2/bootstrap")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["selectedVolume"]["id"] == "volume-v2"
    editions = {item["id"]: item for item in data["availableEditions"]}
    assert editions["edition-v2"]["progress"] == 31
    assert editions["edition-v2"]["lastReadAt"] == "2026-07-08T04:00:00Z"
    assert editions["edition-v2-alt"]["progress"] == 73.5
    assert editions["edition-v2-alt"]["lastReadAt"] == "2026-07-09T06:00:00Z"
    assert editions["edition-v2-unread"]["progress"] == 0
    assert editions["edition-v2-unread"]["lastReadAt"] is None


def test_progress_v2_validates_fingerprint_and_writes_v2_and_legacy_projections(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    bootstrap = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]
    fingerprint = bootstrap["contentFingerprint"]
    body = {
        "schemaVersion": 2,
        "userId": user_id,
        "mutationId": "mutation-1",
        "clientId": "client-a",
        "clientSequence": 7,
        "contentFingerprint": fingerprint,
        "volumeId": "volume-v2",
        "location": {
            "type": "epub",
            "cfi": "epubcfi(/6/2!/4/1:0)",
            "href": "two.xhtml",
            "spineIndex": 1,
            "progression": 0.5,
        },
        "percent": 50,
    }

    saved = client.put("/api/reader/v2/editions/edition-v2/progress", json=body)

    assert saved.status_code == 200
    assert saved.json()["data"]["applied"] is True
    progress = saved.json()["data"]["progress"]
    assert progress["readerType"] == "epub"
    assert progress["workId"] == "work-v2"
    assert progress["editionId"] == "edition-v2"
    assert progress["clientSequence"] == 7
    row = db_session.execute(text("SELECT * FROM LibraryReadingProgress")).mappings().one()
    assert row["userId"] == user_id
    assert row["schemaVersion"] == 2
    assert row["locationType"] == "epub"
    assert json.loads(row["locationJson"])["href"] == "two.xhtml"
    assert row["position"] == "epubcfi(/6/2!/4/1:0)"
    assert row["page"] == 2
    assert row["percent"] == 50
    assert row["contentFingerprint"] == fingerprint
    assert row["mutationId"] == "mutation-1"
    assert row["clientId"] == "client-a"
    assert row["clientSequence"] == 7

    mismatched = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={**body, "mutationId": "mutation-2", "clientSequence": 8, "contentFingerprint": "sha256:stale"},
    )
    assert mismatched.status_code == 409
    assert mismatched.json()["error"]["message"] == "CONTENT_FINGERPRINT_MISMATCH"
    assert mismatched.json()["error"]["details"]["expectedContentFingerprint"] == fingerprint
    assert db_session.execute(text("SELECT mutationId FROM LibraryReadingProgress")).scalar() == "mutation-1"

    stale_sequence = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={**body, "mutationId": "mutation-stale", "clientSequence": 6, "percent": 10},
    )
    assert stale_sequence.status_code == 200
    assert stale_sequence.json()["data"]["applied"] is False
    persisted = db_session.execute(text("SELECT mutationId, percent FROM LibraryReadingProgress")).mappings().one()
    assert dict(persisted) == {"mutationId": "mutation-1", "percent": 50.0}


def test_reading_status_is_user_scoped_and_finishes_only_on_last_volume(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    db_session.execute(text("UPDATE LibraryWork SET status = 'UNREAD' WHERE id = 'work-v2'"))
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, editionId, title, volumeIndex, sortOrder, pageCount, chapterCount, createdAt, updatedAt
            ) VALUES (
                'volume-v2-final', 'edition-v2', '第 2 卷', 2, 2, NULL, 1,
                '2026-07-10T02:00:00', '2026-07-10T02:00:00'
            )"""
        )
    )
    db_session.commit()

    first = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]
    assert db_session.execute(text("SELECT status FROM LibraryWork WHERE id = 'work-v2'")).scalar_one() == "UNREAD"
    assert db_session.execute(
        text(
            "SELECT status FROM LibraryConsumptionState "
            "WHERE userId = :user_id AND workId = 'work-v2' AND mediaKind = 'EBOOK'"
        ),
        {"user_id": user_id},
    ).scalar_one() == "READING"

    first_finished = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={
            "schemaVersion": 2,
            "userId": user_id,
            "mutationId": "status-first-volume",
            "clientId": "status-client",
            "clientSequence": 1,
            "contentFingerprint": first["contentFingerprint"],
            "volumeId": "volume-v2",
            "location": {"type": "epub", "href": "two.xhtml", "progression": 1},
            "percent": 100,
        },
    )
    assert first_finished.status_code == 200
    assert db_session.execute(text("SELECT status FROM LibraryWork WHERE id = 'work-v2'")).scalar_one() == "UNREAD"

    final = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2-final").json()["data"]
    final_finished = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={
            "schemaVersion": 2,
            "userId": user_id,
            "mutationId": "status-final-volume",
            "clientId": "status-client",
            "clientSequence": 2,
            "contentFingerprint": final["contentFingerprint"],
            "volumeId": "volume-v2-final",
            "location": {"type": "epub", "href": "final.xhtml", "progression": 1},
            "percent": 100,
        },
    )
    assert final_finished.status_code == 200
    assert db_session.execute(text("SELECT status FROM LibraryWork WHERE id = 'work-v2'")).scalar_one() == "UNREAD"
    assert db_session.execute(
        text(
            "SELECT status FROM LibraryConsumptionState "
            "WHERE userId = :user_id AND workId = 'work-v2' AND mediaKind = 'EBOOK'"
        ),
        {"user_id": user_id},
    ).scalar_one() == "FINISHED"

    client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2-final")
    assert db_session.execute(text("SELECT status FROM LibraryWork WHERE id = 'work-v2'")).scalar_one() == "UNREAD"
    assert client.get("/api/dashboard/continue-reading").json()["data"]["item"] is None


def test_progress_cursor_survives_other_client_overwriting_progress_projection(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    bootstrap = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]
    base = {
        "schemaVersion": 2,
        "userId": user_id,
        "contentFingerprint": bootstrap["contentFingerprint"],
        "volumeId": "volume-v2",
        "location": {"type": "epub", "cfi": "epubcfi(/6/2!/4/1:0)"},
        "percent": 20,
    }

    client_a = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={**base, "mutationId": "a-7", "clientId": "client-a", "clientSequence": 7},
    )
    assert client_a.json()["data"]["applied"] is True

    client_b = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={**base, "mutationId": "b-1", "clientId": "client-b", "clientSequence": 1, "percent": 60},
    )
    assert client_b.json()["data"]["applied"] is True
    assert db_session.execute(text("SELECT clientId FROM LibraryReadingProgress")).scalar() == "client-b"

    duplicate_a = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={**base, "mutationId": "a-7-duplicate", "clientId": "client-a", "clientSequence": 7, "percent": 5},
    )
    assert duplicate_a.json()["data"]["applied"] is False
    projection = db_session.execute(text("SELECT clientId, mutationId, percent FROM LibraryReadingProgress")).mappings().one()
    assert dict(projection) == {"clientId": "client-b", "mutationId": "b-1", "percent": 60.0}
    cursors = db_session.execute(
        text("SELECT clientId, highWater FROM ReaderProgressCursor ORDER BY clientId")
    ).mappings().all()
    assert [dict(item) for item in cursors] == [
        {"clientId": "client-a", "highWater": 7},
        {"clientId": "client-b", "highWater": 1},
    ]

    next_a = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={**base, "mutationId": "a-8", "clientId": "client-a", "clientSequence": 8, "percent": 80},
    )
    assert next_a.json()["data"]["applied"] is True
    assert db_session.execute(
        text("SELECT highWater FROM ReaderProgressCursor WHERE clientId = 'client-a'")
    ).scalar() == 8


def test_progress_cursor_atomically_rejects_concurrent_duplicate_sequence(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'reader-cursor.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """CREATE TABLE IF NOT EXISTS ReaderProgressCursor (
                    id TEXT PRIMARY KEY, userId TEXT NOT NULL, workId TEXT NOT NULL, clientId TEXT NOT NULL,
                    highWater INTEGER NOT NULL, lastMutationId TEXT, createdAt TEXT, updatedAt TEXT,
                    UNIQUE(userId, workId, clientId)
                )"""
            )
        )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    barrier = Barrier(2)

    def claim(mutation_id: str):
        with factory() as db:
            barrier.wait()
            accepted = ClaimClientSequence(SqlAlchemyReaderProgressCursor(db)).execute(
                ClaimClientSequenceCommand(
                    user_id="user-1",
                    work_id="work-1",
                    client_id="client-1",
                    client_sequence=11,
                    mutation_id=mutation_id,
                    now=datetime.now(timezone.utc),
                )
            )
            db.commit()
            return mutation_id, accepted

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ("mutation-a", "mutation-b")))

        assert sorted(accepted for _mutation, accepted in results) == [False, True]
        winner = next(mutation for mutation, accepted in results if accepted)
        with factory() as db:
            cursor = db.execute(text("SELECT highWater, lastMutationId FROM ReaderProgressCursor")).mappings().one()
            assert dict(cursor) == {"highWater": 11, "lastMutationId": winner}

            assert ClaimClientSequence(SqlAlchemyReaderProgressCursor(db)).execute(
                ClaimClientSequenceCommand(
                    user_id="user-1",
                    work_id="work-1",
                    client_id="client-1",
                    client_sequence=12,
                    mutation_id="rolled-back",
                    now=datetime.now(timezone.utc),
                )
            ) is True
            db.rollback()
            assert db.execute(text("SELECT highWater FROM ReaderProgressCursor")).scalar() == 11
    finally:
        engine.dispose()


def test_progress_cursor_lazily_backfills_visible_legacy_client_sequence(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    bootstrap = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]
    db_session.execute(
        text(
            """INSERT INTO LibraryReadingProgress (
                id, userId, workId, editionId, volumeId, readerType, position, page, percent, extra,
                schemaVersion, locationType, locationJson, contentFingerprint, mutationId,
                clientId, clientSequence, createdAt, updatedAt
            ) VALUES (
                'legacy-visible-progress', :user_id, 'work-v2', 'edition-v2', 'volume-v2', 'epub',
                'legacy-cfi', 1, 25, '{}', 2, 'epub', :location, :fingerprint,
                'legacy-mutation', 'legacy-client', 4, '2026-07-09', '2026-07-09'
            )"""
        ),
        {
            "user_id": user_id,
            "location": json.dumps({"type": "epub", "cfi": "legacy-cfi"}),
            "fingerprint": bootstrap["contentFingerprint"],
        },
    )
    db_session.commit()

    duplicate = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={
            "schemaVersion": 2,
            "userId": user_id,
            "mutationId": "duplicate-after-upgrade",
            "clientId": "legacy-client",
            "clientSequence": 4,
            "contentFingerprint": bootstrap["contentFingerprint"],
            "volumeId": "volume-v2",
            "location": {"type": "epub", "cfi": "should-not-write"},
            "percent": 1,
        },
    )

    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["applied"] is False
    cursor = db_session.execute(
        text("SELECT highWater FROM ReaderProgressCursor WHERE clientId = 'legacy-client'")
    ).scalar()
    assert cursor == 4
    progress = db_session.execute(text("SELECT mutationId, position FROM LibraryReadingProgress")).mappings().one()
    assert dict(progress) == {"mutationId": "legacy-mutation", "position": "legacy-cfi"}


def test_all_reader_v1_preferences_bootstrap_and_progress_protocols_are_gone(client, db_session):
    _reader_tables(db_session)
    assert client.get("/api/reader/preferences").status_code == 410
    _login(client, db_session)
    _epub_fixture(db_session)

    retired_calls = [
        (client.get, "/api/reader/preferences", None, "Reader V2 stores per-work client preferences locally"),
        (client.put, "/api/reader/preferences", {"preferences": {}}, "Reader V2 stores per-work client preferences locally"),
        (client.get, "/api/reader/preferences/ebook", None, "Reader V2 stores per-work client preferences locally"),
        (client.put, "/api/reader/preferences/ebook", {"settings": {}}, "Reader V2 stores per-work client preferences locally"),
        (client.patch, "/api/reader/preferences/ebook", {"settings": {}}, "Reader V2 stores per-work client preferences locally"),
        (client.get, "/api/reader/edition-v2/bootstrap", None, "/api/reader/v2/editions/edition-v2/bootstrap"),
        (client.get, "/api/editions/edition-v2/progress", None, "/api/reader/v2/editions/edition-v2/progress"),
        (client.post, "/api/editions/edition-v2/progress", {"percent": 10}, "/api/reader/v2/editions/edition-v2/progress"),
        (client.put, "/api/editions/edition-v2/progress", {"percent": 10}, "/api/reader/v2/editions/edition-v2/progress"),
        (client.patch, "/api/editions/edition-v2/progress", {"percent": 10}, "/api/reader/v2/editions/edition-v2/progress"),
    ]
    for call, path, body, replacement in retired_calls:
        response = call(path) if body is None else call(path, json=body)
        assert response.status_code == 410, path
        assert response.json()["error"]["message"] == "READER_V1_RETIRED"
        assert response.json()["error"]["details"]["replacement"] == replacement


def test_progress_v2_rejects_wrong_location_type_before_writing(client, db_session):
    _reader_tables(db_session)
    _login(client, db_session)
    _epub_fixture(db_session)
    fingerprint = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]["contentFingerprint"]

    response = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={
            "schemaVersion": 2,
            "userId": client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]["userId"],
            "mutationId": "mutation-wrong-type",
            "clientId": "client-a",
            "clientSequence": 1,
            "contentFingerprint": fingerprint,
            "volumeId": "volume-v2",
            "location": {"type": "pdf", "pageNumber": 1},
            "percent": 0,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "位置类型与版本格式不匹配"
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryReadingProgress")).scalar() == 0


def test_progress_v2_rejects_stale_tab_user_assertion_before_writing(client, db_session):
    _reader_tables(db_session)
    _login(client, db_session)
    _epub_fixture(db_session)
    bootstrap = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]

    response = client.put(
        "/api/reader/v2/editions/edition-v2/progress",
        json={
            "schemaVersion": 2,
            "userId": "stale-tab-user",
            "mutationId": "stale-tab-mutation",
            "clientId": "stale-tab-client",
            "clientSequence": 1,
            "contentFingerprint": bootstrap["contentFingerprint"],
            "volumeId": "volume-v2",
            "location": {"type": "epub", "cfi": "epubcfi(/6/2!/4/1:0)"},
            "percent": 10,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "READER_USER_MISMATCH"
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryReadingProgress")).scalar() == 0


def test_epub_bootstrap_discards_resume_location_after_fingerprint_change(client, db_session):
    _reader_tables(db_session)
    user_id = _login(client, db_session)
    _epub_fixture(db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryReadingProgress (
                id, userId, workId, editionId, volumeId, readerType, position, page, percent, extra,
                schemaVersion, locationType, locationJson, contentFingerprint, mutationId,
                clientId, clientSequence, createdAt, updatedAt
            ) VALUES (
                'progress-old-content', :user_id, 'work-v2', 'edition-v2', 'volume-v2', 'epub',
                'epubcfi(/6/2!/4/1:0)', 2, 50, '{}', 2, 'epub', :location,
                'sha256:old-content', 'old-mutation', 'client-a', 1,
                '2026-07-09T01:00:00', '2026-07-09T01:00:00'
            )"""
        ),
        {
            "user_id": user_id,
            "location": json.dumps({"type": "epub", "cfi": "epubcfi(/6/2!/4/1:0)", "href": "two.xhtml", "spineIndex": 1, "progression": 0.5}),
        },
    )
    db_session.commit()

    data = client.get("/api/reader/v2/editions/edition-v2/bootstrap?volume=volume-v2").json()["data"]

    assert data["resumeFingerprintMismatch"] is True
    assert data["resumeDiscardedReason"] == "content_fingerprint_mismatch"
    assert data["resumeLocation"] is None
    assert data["progressPercent"] == 0


def test_comic_bootstrap_reuses_lazy_archive_index_and_returns_one_based_pages(client, db_session, test_settings):
    _reader_tables(db_session)
    _login(client, db_session)
    archive = test_settings.resolved_storage_root / "library" / "comic-v2.zip"
    archive.parent.mkdir(parents=True)
    write_comic_fixture(archive)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, origin, title, normalizedTitle, workType, status, publicationStatus, trackingStatus,
                tags, metadataQuality, organizeStatus, coverStatus, hidden, organized, primaryEditionId,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'comic-work-v2', 'MANUAL', 'V2 漫画', 'v2 漫画', 'COMIC', 'READING', 'UNKNOWN',
                'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 1, 'comic-edition-v2',
                'comic:v2', '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryEdition (
                id, workId, origin, format, versionName, versionKey, importStatus, sizeBytes,
                pageCount, coverStatus, "primary", hidden, createdAt, updatedAt
            ) VALUES (
                'comic-edition-v2', 'comic-work-v2', 'MANUAL', 'COMIC', '漫画版本', 'default',
                'COMPLETED', 128, 2, 'PENDING', 1, 0, '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, editionId, title, volumeIndex, sortOrder, pageCount, createdAt, updatedAt
            ) VALUES (
                'comic-volume-v2', 'comic-edition-v2', '第 1 卷', 1, 1, NULL,
                '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryFile (
                id, editionId, volumeId, path, filePathHash, fingerprint, hashStatus, mtimeMs,
                kind, mimeType, sizeBytes, sortOrder, createdAt, updatedAt
            ) VALUES (
                'comic-file-v2', 'comic-edition-v2', 'comic-volume-v2', :path, 'comic-path-v2',
                'comic-fingerprint-v2', 'PARTIAL_PENDING', 1720573200000, 'COMIC',
                'application/zip', 128, 1, '2026-07-10T01:00:00', '2026-07-10T01:00:00'
            )"""
        ),
        {"path": str(archive)},
    )
    db_session.commit()

    response = client.get("/api/reader/v2/editions/comic-edition-v2/bootstrap?volume=comic-volume-v2")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["readerType"] == "comic"
    assert data["capabilities"]["canZoom"] is True
    assert data["totalPages"] == 2
    assert data["selectedVolume"]["pageCount"] == 2
    assert [page["pageIndex"] for page in data["pages"]] == [1, 2]
    assert db_session.execute(
        text("SELECT COUNT(*) FROM LibraryReadingUnit WHERE volumeId = 'comic-volume-v2'")
    ).scalar() == 2

    common_progress = {
        "schemaVersion": 2,
        "userId": data["userId"],
        "mutationId": "comic-mutation-v2",
        "clientId": "comic-client-v2",
        "clientSequence": 1,
        "contentFingerprint": data["contentFingerprint"],
        "percent": 100,
    }
    missing_location_volume = client.put(
        "/api/reader/v2/editions/comic-edition-v2/progress",
        json={**common_progress, "location": {"type": "comic", "pageIndex": 2}},
    )
    assert missing_location_volume.status_code == 422

    mismatched_location_volume = client.put(
        "/api/reader/v2/editions/comic-edition-v2/progress",
        json={
            **common_progress,
            "volumeId": "comic-volume-v2",
            "location": {"type": "comic", "volumeId": "another-volume", "pageIndex": 2},
        },
    )
    assert mismatched_location_volume.status_code == 422
    assert mismatched_location_volume.json()["error"]["message"] == "漫画位置的 volumeId 与进度目标不匹配"

    saved = client.put(
        "/api/reader/v2/editions/comic-edition-v2/progress",
        json={
            **common_progress,
            "location": {"type": "comic", "volumeId": "comic-volume-v2", "pageIndex": 2},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["progress"]["volumeId"] == "comic-volume-v2"
    assert saved.json()["data"]["progress"]["location"] == {
        "type": "comic",
        "volumeId": "comic-volume-v2",
        "pageIndex": 2,
    }
    stored_location = db_session.execute(
        text("SELECT locationJson FROM LibraryReadingProgress WHERE editionId = 'comic-edition-v2'")
    ).scalar_one()
    assert json.loads(stored_location) == {
        "type": "comic",
        "volumeId": "comic-volume-v2",
        "pageIndex": 2,
    }

    resumed = client.get(
        "/api/reader/v2/editions/comic-edition-v2/bootstrap?volume=comic-volume-v2"
    ).json()["data"]
    assert resumed["resumeLocation"] == {
        "type": "comic",
        "volumeId": "comic-volume-v2",
        "pageIndex": 2,
    }
