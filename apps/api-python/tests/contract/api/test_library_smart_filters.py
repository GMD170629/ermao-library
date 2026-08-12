from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User, UserMonitorFolderAccess
from app.models.library import (
    LibraryFacet,
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
)
from app.models.settings import MonitorFolder
from app.models.shelf import Shelf, ShelfWork


def _login_admin(client: TestClient, db: Session) -> User:
    user = User(
        id="smart-filter-admin",
        email="smart-filter@example.com",
        name="Smart filter admin",
        password_hash=hash_password("smart-filter-password"),
        role="admin",
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": user.email,
            "password": "smart-filter-password",
        },
    )
    assert response.status_code == 200
    return user


def _add_work(
    db: Session,
    *,
    work_id: str,
    title: str,
    source_path: str,
    author: str | None = None,
) -> None:
    work = LibraryWork(
        id=work_id,
        title=title,
        normalized_title=title.casefold(),
        author=author,
        normalized_author=author.casefold() if author else None,
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id=f"media-{work_id}",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volume = LibraryVolume(
        id=f"volume-{work_id}",
        media_version_id=media_version.id,
        title=title,
        format="EPUB",
        resource_key=f"resource-{work_id}",
        import_status="COMPLETED",
    )
    file = LibraryFile(
        id=f"file-{work_id}",
        volume_id=volume.id,
        path=source_path,
        kind="BOOK",
        mime_type="application/epub+zip",
    )
    db.add_all([work, media_version, volume, file])


def _filtered_titles(client: TestClient, rules: dict[str, object]) -> list[str]:
    response = client.get(
        "/api/works",
        params={
            "filters": json.dumps(rules, ensure_ascii=False),
            "pageSize": "100",
            "view": "management",
        },
    )
    assert response.status_code == 200
    return [book["title"] for book in response.json()["data"]["books"]]


def _add_filter_matrix_fixture(db: Session, user: User) -> None:
    alpha_work = LibraryWork(
        id="alpha",
        monitor_folder_id="folder-alpha",
        origin="WATCH",
        title="星海列车",
        normalized_title="星海列车",
        author="林川",
        normalized_author="林川",
        description="Alpha 太空冒险 Suffix",
        publication_status="COMPLETED",
        tracking_status="TRACKING",
        tags='["科幻"]',
        series_name="星海系列",
        series_index=2,
        metadata_quality=92,
        organize_status="APPLIED",
        cover_path="covers/alpha.webp",
        cover_status="READY",
        organized=True,
        created_at=datetime(2026, 7, 10, 8, tzinfo=UTC),
        updated_at=datetime(2026, 7, 12, 8, tzinfo=UTC),
    )
    beta_work = LibraryWork(
        id="beta",
        monitor_folder_id="folder-beta",
        origin="MANUAL",
        title="平凡日记",
        normalized_title="平凡日记",
        author="周秋",
        normalized_author="周秋",
        description=None,
        publication_status="ONGOING",
        tracking_status="NOT_TRACKING",
        tags="[]",
        series_name=None,
        series_index=None,
        metadata_quality=10,
        organize_status="REVIEWING",
        cover_path=None,
        cover_status="PENDING",
        organized=False,
        created_at=datetime(2025, 1, 1, 8, tzinfo=UTC),
        updated_at=datetime(2025, 1, 2, 8, tzinfo=UTC),
    )
    empty_work = LibraryWork(
        id="empty",
        origin="MANUAL",
        title="空白样本",
        normalized_title="空白样本",
        author=None,
        normalized_author=None,
        description=None,
        tags="[]",
        series_name=None,
        series_index=None,
        metadata_quality=0,
    )
    alpha_media = LibraryMediaVersion(
        id="media-alpha",
        work_id=alpha_work.id,
        media_kind="EBOOK",
    )
    beta_media = LibraryMediaVersion(
        id="media-beta",
        work_id=beta_work.id,
        media_kind="COMIC",
    )
    empty_media = LibraryMediaVersion(
        id="media-empty",
        work_id=empty_work.id,
        media_kind="AUDIOBOOK",
    )
    alpha_volumes = [
        LibraryVolume(
            id="volume-alpha-1",
            media_version_id=alpha_media.id,
            monitor_folder_id="folder-alpha",
            origin="WATCH",
            title="星海列车 旗舰卷",
            volume_index=1,
            sort_order=0,
            format="EPUB",
            resource_key="resource-alpha-1",
            language="zh-CN",
            publisher="星海出版社",
            identifier="urn:starship:alpha",
            isbn="9780000000001",
            import_status="COMPLETED",
            size_bytes=2 * 1024 * 1024,
            page_count=320,
            chapter_count=30,
            duration_ms=90 * 60 * 1000,
            narrator="演播甲",
        ),
        LibraryVolume(
            id="volume-alpha-2",
            media_version_id=alpha_media.id,
            monitor_folder_id="folder-alpha",
            origin="WATCH",
            title="星海列车 第二卷",
            volume_index=2,
            sort_order=1,
            format="EPUB",
            resource_key="resource-alpha-2",
            language="zh-CN",
            publisher="星海出版社",
            import_status="COMPLETED",
            size_bytes=1024 * 1024,
            page_count=280,
            chapter_count=25,
        ),
    ]
    beta_volume = LibraryVolume(
        id="volume-beta",
        media_version_id=beta_media.id,
        monitor_folder_id="folder-beta",
        origin="MANUAL",
        title="平凡日记 第一卷",
        format="PDF",
        resource_key="resource-beta",
        language="en-US",
        publisher="普通出版社",
        identifier="urn:ordinary:beta",
        isbn="9780000000002",
        import_status="PARSING",
        size_bytes=512 * 1024,
        page_count=100,
        chapter_count=10,
    )
    empty_volume = LibraryVolume(
        id="volume-empty",
        media_version_id=empty_media.id,
        title="空白样本",
        format="AUDIO",
        resource_key="resource-empty",
        import_status="PENDING",
    )
    files = [
        LibraryFile(
            id="file-alpha-1",
            volume_id=alpha_volumes[0].id,
            path="/books/alpha/鸡皮疙瘩_100%/第一卷.epub",
            kind="BOOK",
            mime_type="application/epub+zip",
            size_bytes=2 * 1024 * 1024,
        ),
        LibraryFile(
            id="file-alpha-2",
            volume_id=alpha_volumes[1].id,
            path="/books/星海列车/第二卷.epub",
            kind="BOOK",
            mime_type="application/epub+zip",
            size_bytes=1024 * 1024,
        ),
        LibraryFile(
            id="file-beta",
            volume_id=beta_volume.id,
            path="/books/beta/鸡皮疙瘩X100Y/第一卷.pdf",
            kind="PDF",
            mime_type="application/pdf",
            size_bytes=512 * 1024,
        ),
        LibraryFile(
            id="file-empty",
            volume_id=empty_volume.id,
            path="/books/empty/sample.epub",
            kind="BOOK",
            mime_type="application/epub+zip",
            size_bytes=0,
        ),
    ]
    tag = LibraryFacet(
        id="tag-scifi",
        kind="TAG",
        name="科幻",
        normalized_name="科幻",
    )
    shelf = Shelf(
        id="shelf-alpha",
        owner_user_id=user.id,
        name="科幻收藏",
        kind="STATIC",
    )
    db.add_all(
        [
            MonitorFolder(
                id="folder-alpha",
                name="星海目录",
                root_path="/books/alpha",
            ),
            MonitorFolder(
                id="folder-beta",
                name="普通目录",
                root_path="/books/beta",
            ),
            alpha_work,
            beta_work,
            empty_work,
            alpha_media,
            beta_media,
            empty_media,
            *alpha_volumes,
            beta_volume,
            empty_volume,
            *files,
            tag,
            LibraryWorkFacet(facet_id=tag.id, work_id=alpha_work.id),
            shelf,
            ShelfWork(shelf_id=shelf.id, work_id=alpha_work.id),
            LibraryReadingProgress(
                id="progress-alpha",
                user_id=user.id,
                volume_id=alpha_volumes[0].id,
                reader_type="epub",
                position="chapter-10",
                percent=50,
                extra="{}",
                updated_at=datetime(2026, 7, 15, 8, tzinfo=UTC),
            ),
            LibraryReadingProgress(
                id="progress-beta",
                user_id=user.id,
                volume_id=beta_volume.id,
                reader_type="pdf",
                position="0",
                percent=0,
                extra="{}",
                updated_at=datetime(2025, 2, 1, 8, tzinfo=UTC),
            ),
        ]
    )
    db.commit()


def test_work_list_supports_statuses_csv_and_preserves_status_parameter(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _add_filter_matrix_fixture(db_session, user)

    response = client.get(
        "/api/works",
        params={
            "status": "UNREAD",
            "statuses": "READING,FINISHED,READING",
            "pageSize": 100,
            "view": "search",
        },
    )

    assert response.status_code == 200
    assert {book["id"] for book in response.json()["data"]["books"]} == {
        "alpha",
        "beta",
        "empty",
    }


def test_work_list_applies_source_path_smart_filter(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    _add_work(
        db_session,
        work_id="goosebumps",
        title="鸡皮疙瘩系列",
        source_path="/books/鸡皮疙瘩系列/第一卷.epub",
    )
    _add_work(
        db_session,
        work_id="unrelated",
        title="小屁孩日记",
        source_path="/books/小屁孩日记/第一卷.epub",
    )
    db_session.commit()

    assert _filtered_titles(
        client,
        {
            "combinator": "ALL",
            "conditions": [
                {
                    "field": "sourcePath",
                    "operator": "contains",
                    "value": "鸡皮疙瘩",
                }
            ],
        },
    ) == ["鸡皮疙瘩系列"]


def test_author_empty_filter_treats_unknown_author_placeholder_as_empty(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    _add_work(
        db_session,
        work_id="missing-author",
        title="缺失作者",
        source_path="/books/missing-author.epub",
    )
    _add_work(
        db_session,
        work_id="unknown-author",
        title="未知作者占位",
        source_path="/books/unknown-author.epub",
        author="未知作者",
    )
    _add_work(
        db_session,
        work_id="known-author",
        title="已知作者",
        source_path="/books/known-author.epub",
        author="林川",
    )
    db_session.commit()

    assert set(
        _filtered_titles(
            client,
            {
                "combinator": "ALL",
                "conditions": [{"field": "author", "operator": "is_empty"}],
            },
        )
    ) == {"缺失作者", "未知作者占位"}
    assert _filtered_titles(
        client,
        {
            "combinator": "ALL",
            "conditions": [{"field": "author", "operator": "is_not_empty"}],
        },
    ) == ["已知作者"]


def test_work_list_applies_every_smart_filter_field(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _add_filter_matrix_fixture(db_session, user)
    conditions_by_field: dict[str, dict[str, object]] = {
        "title": {"operator": "contains", "value": "星海"},
        "author": {"operator": "equals", "value": "林川"},
        "tag": {"operator": "equals", "value": "科幻"},
        "series": {"operator": "equals", "value": "星海系列"},
        "description": {"operator": "contains", "value": "太空冒险"},
        "seriesIndex": {"operator": "equals", "value": "2"},
        "metadataQuality": {"operator": "greater_or_equal", "value": "90"},
        "volumeTitle": {"operator": "contains", "value": "旗舰卷"},
        "narrator": {"operator": "contains", "value": "演播甲"},
        "mediaKind": {"operator": "equals", "value": "EBOOK"},
        "format": {"operator": "equals", "value": "EPUB"},
        "fileSize": {"operator": "greater_than", "value": "2.5"},
        "pageCount": {"operator": "greater_or_equal", "value": "300"},
        "chapterCount": {"operator": "greater_than", "value": "20"},
        "duration": {"operator": "greater_than", "value": "60"},
        "volumeCount": {"operator": "equals", "value": "2"},
        "sourcePath": {
            "operator": "contains",
            "value": "鸡皮疙瘩_100%",
        },
        "readingStatus": {"operator": "equals", "value": "READING"},
        "progress": {"operator": "between", "value": ["40", "60"]},
        "lastReadAt": {"operator": "equals", "value": "2026-07-15"},
        "publicationStatus": {"operator": "equals", "value": "COMPLETED"},
        "trackingStatus": {"operator": "equals", "value": "TRACKING"},
        "organizeStatus": {"operator": "equals", "value": "APPLIED"},
        "organized": {"operator": "is_true"},
        "hasCover": {"operator": "is_true"},
        "shelf": {"operator": "equals", "value": "shelf-alpha"},
        "monitorFolder": {"operator": "equals", "value": "folder-alpha"},
        "origin": {"operator": "equals", "value": "WATCH"},
        "importStatus": {"operator": "equals", "value": "COMPLETED"},
        "createdAt": {"operator": "equals", "value": "2026-07-10"},
        "updatedAt": {"operator": "equals", "value": "2026-07-12"},
    }
    schema_response = client.get("/api/library/filter-schema")
    assert schema_response.status_code == 200
    returned_fields = schema_response.json()["data"]["fields"]
    schema_fields = {field["key"] for field in returned_fields}
    assert set(conditions_by_field) == schema_fields
    field_keys = [field["key"] for field in returned_fields]
    monitor_folder_index = field_keys.index("monitorFolder")
    assert returned_fields[monitor_folder_index]["label"] == "监控文件夹"
    assert field_keys[monitor_folder_index + 1] == "sourcePath"
    assert returned_fields[monitor_folder_index + 1]["group"] == "来源与归档"

    for field, partial_condition in conditions_by_field.items():
        titles = _filtered_titles(
            client,
            {
                "combinator": "ALL",
                "conditions": [{"field": field, **partial_condition}],
            },
        )
        assert titles == ["星海列车"], field


def test_filter_schema_keeps_high_cardinality_options_out_of_payload(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _add_filter_matrix_fixture(db_session, user)

    response = client.get("/api/library/filter-schema")

    assert response.status_code == 200
    fields = {field["key"]: field for field in response.json()["data"]["fields"]}
    assert fields["author"]["options"] == []
    assert fields["tag"]["options"] == []
    assert fields["series"]["options"] == []
    assert {option["value"] for option in fields["format"]["options"]} == {
        "AUDIO",
        "EPUB",
        "PDF",
    }
    assert {option["value"] for option in fields["shelf"]["options"]} == {"shelf-alpha"}


def test_filter_options_are_bounded_and_author_uses_complete_raw_value(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _add_filter_matrix_fixture(db_session, user)
    alpha = db_session.get(LibraryWork, "alpha")
    assert alpha is not None
    alpha.author = "林川、周秋"
    db_session.commit()

    response = client.get(
        "/api/library/filter-options",
        params={"source": "authors", "query": " 林 ", "limit": 1},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "source": "authors",
        "query": "林",
        "options": [{"value": "林川、周秋", "label": "林川、周秋", "count": 1}],
        "hasMore": False,
        "indexReady": True,
    }


def test_tag_filter_options_wait_for_index_and_then_use_facet_links(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _add_filter_matrix_fixture(db_session, user)

    pending = client.get(
        "/api/library/filter-options",
        params={"source": "tags", "query": "科"},
    )
    assert pending.status_code == 200
    assert pending.json()["data"]["options"] == []
    assert pending.json()["data"]["indexReady"] is False

    for work in db_session.query(LibraryWork).all():
        work.facet_index_version = 1
    db_session.commit()

    ready = client.get(
        "/api/library/filter-options",
        params={"source": "tags", "query": "科"},
    )
    assert ready.status_code == 200
    assert ready.json()["data"] == {
        "source": "tags",
        "query": "科",
        "options": [{"value": "科幻", "label": "科幻", "count": 1}],
        "hasMore": False,
        "indexReady": True,
    }


def test_filter_options_validate_source_limit_and_authentication(
    client: TestClient,
    db_session: Session,
) -> None:
    anonymous = client.get(
        "/api/library/filter-options",
        params={"source": "authors", "query": "林"},
    )
    assert anonymous.status_code == 401

    _login_admin(client, db_session)
    invalid_source = client.get(
        "/api/library/filter-options",
        params={"source": "publishers", "query": "林"},
    )
    invalid_limit = client.get(
        "/api/library/filter-options",
        params={"source": "authors", "query": "林", "limit": 51},
    )
    assert invalid_source.status_code == 422
    assert invalid_source.json()["ok"] is False
    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["ok"] is False


def test_filter_schema_size_and_option_query_stay_bounded_at_high_cardinality(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)

    def add_works(start: int, stop: int) -> None:
        db_session.add_all(
            [
                LibraryWork(
                    id=f"large-filter-{index}",
                    title=f"Large filter {index}",
                    normalized_title=f"large filter {index}",
                    author=f"Unique Author {index}",
                    normalized_author=f"unique author {index}",
                    tags='["must-not-be-read"]',
                    facet_index_version=1,
                )
                for index in range(start, stop)
            ]
        )
        db_session.commit()

    add_works(0, 100)
    smaller_schema = client.get("/api/library/filter-schema")
    add_works(100, 1000)
    larger_schema = client.get("/api/library/filter-schema")
    assert smaller_schema.status_code == 200
    assert larger_schema.status_code == 200
    assert abs(len(larger_schema.content) - len(smaller_schema.content)) < 10

    statements: list[str] = []
    engine = db_session.get_bind()

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(" ".join(statement.split()).upper())

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = client.get(
            "/api/library/filter-options",
            params={"source": "authors", "query": "Unique", "limit": 20},
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    assert len(response.json()["data"]["options"]) == 20
    assert response.json()["data"]["hasMore"] is True
    assert len(statements) <= 5
    assert not any("LIBRARYWORK.TAGS" in statement for statement in statements)


def test_monitor_folder_filter_matches_real_volume_file_paths(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _add_filter_matrix_fixture(db_session, user)
    stored_folder_ids = {
        "volume-alpha-1": "folder-beta",
        "volume-alpha-2": None,
        "volume-beta": "folder-alpha",
    }
    for volume_id, folder_id in stored_folder_ids.items():
        volume = db_session.get(LibraryVolume, volume_id)
        assert volume is not None
        volume.monitor_folder_id = folder_id
    real_paths = {
        "file-alpha-1": "/books/alpha/星海列车/第一卷.epub",
        "file-alpha-2": "/outside/星海列车/第二卷.epub",
        "file-beta": "/books/beta/平凡日记/第一卷.pdf",
        "file-empty": "/books/alpha-archive/sample.epub",
    }
    for file_id, path in real_paths.items():
        library_file = db_session.get(LibraryFile, file_id)
        assert library_file is not None
        library_file.path = path
    db_session.commit()

    assert _filtered_titles(
        client,
        {
            "combinator": "ALL",
            "conditions": [
                {
                    "field": "monitorFolder",
                    "operator": "equals",
                    "value": "folder-alpha",
                }
            ],
        },
    ) == ["星海列车"]
    assert set(
        _filtered_titles(
            client,
            {
                "combinator": "ALL",
                "conditions": [
                    {
                        "field": "monitorFolder",
                        "operator": "not_equals",
                        "value": "folder-alpha",
                    }
                ],
            },
        )
    ) == {"平凡日记", "空白样本"}
    assert set(
        _filtered_titles(
            client,
            {
                "combinator": "ALL",
                "conditions": [{"field": "monitorFolder", "operator": "is_not_empty"}],
            },
        )
    ) == {"星海列车", "平凡日记"}
    assert _filtered_titles(
        client,
        {
            "combinator": "ALL",
            "conditions": [{"field": "monitorFolder", "operator": "is_empty"}],
        },
    ) == ["空白样本"]


def test_work_list_applies_all_operator_families_and_combinators(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    _add_filter_matrix_fixture(db_session, user)
    cases: list[tuple[str, dict[str, object], set[str]]] = [
        (
            "text contains",
            {"field": "description", "operator": "contains", "value": "太空"},
            {"星海列车"},
        ),
        (
            "text not contains",
            {"field": "description", "operator": "not_contains", "value": "太空"},
            {"平凡日记", "空白样本"},
        ),
        (
            "text equals",
            {
                "field": "description",
                "operator": "equals",
                "value": "Alpha 太空冒险 Suffix",
            },
            {"星海列车"},
        ),
        (
            "text not equals",
            {
                "field": "description",
                "operator": "not_equals",
                "value": "Alpha 太空冒险 Suffix",
            },
            {"平凡日记", "空白样本"},
        ),
        (
            "text starts with",
            {"field": "description", "operator": "starts_with", "value": "Alpha"},
            {"星海列车"},
        ),
        (
            "text ends with",
            {"field": "description", "operator": "ends_with", "value": "Suffix"},
            {"星海列车"},
        ),
        (
            "text empty",
            {"field": "description", "operator": "is_empty"},
            {"平凡日记", "空白样本"},
        ),
        (
            "text not empty",
            {"field": "description", "operator": "is_not_empty"},
            {"星海列车"},
        ),
        (
            "select equals",
            {"field": "series", "operator": "equals", "value": "星海系列"},
            {"星海列车"},
        ),
        (
            "select not equals",
            {"field": "series", "operator": "not_equals", "value": "星海系列"},
            {"平凡日记", "空白样本"},
        ),
        (
            "select empty",
            {"field": "series", "operator": "is_empty"},
            {"平凡日记", "空白样本"},
        ),
        (
            "select not empty",
            {"field": "series", "operator": "is_not_empty"},
            {"星海列车"},
        ),
        (
            "relation not equals",
            {"field": "format", "operator": "not_equals", "value": "EPUB"},
            {"平凡日记", "空白样本"},
        ),
        (
            "reading status empty",
            {"field": "readingStatus", "operator": "is_empty"},
            set(),
        ),
        (
            "reading status not empty",
            {"field": "readingStatus", "operator": "is_not_empty"},
            {"星海列车", "平凡日记", "空白样本"},
        ),
        (
            "number equals",
            {"field": "seriesIndex", "operator": "equals", "value": "2"},
            {"星海列车"},
        ),
        (
            "number not equals",
            {"field": "seriesIndex", "operator": "not_equals", "value": "3"},
            {"星海列车"},
        ),
        (
            "number greater",
            {"field": "seriesIndex", "operator": "greater_than", "value": "1"},
            {"星海列车"},
        ),
        (
            "number greater or equal",
            {"field": "seriesIndex", "operator": "greater_or_equal", "value": "2"},
            {"星海列车"},
        ),
        (
            "number less",
            {"field": "seriesIndex", "operator": "less_than", "value": "3"},
            {"星海列车"},
        ),
        (
            "number less or equal",
            {"field": "seriesIndex", "operator": "less_or_equal", "value": "2"},
            {"星海列车"},
        ),
        (
            "number between",
            {"field": "seriesIndex", "operator": "between", "value": ["1", "3"]},
            {"星海列车"},
        ),
        (
            "number empty",
            {"field": "seriesIndex", "operator": "is_empty"},
            {"平凡日记", "空白样本"},
        ),
        (
            "number not empty",
            {"field": "seriesIndex", "operator": "is_not_empty"},
            {"星海列车"},
        ),
        (
            "date equals",
            {"field": "lastReadAt", "operator": "equals", "value": "2026-07-15"},
            {"星海列车"},
        ),
        (
            "date not equals",
            {"field": "lastReadAt", "operator": "not_equals", "value": "2026-07-15"},
            {"平凡日记"},
        ),
        (
            "date after",
            {"field": "lastReadAt", "operator": "after", "value": "2026-01-01"},
            {"星海列车"},
        ),
        (
            "date on or after",
            {"field": "lastReadAt", "operator": "on_or_after", "value": "2026-07-15"},
            {"星海列车"},
        ),
        (
            "date before",
            {"field": "lastReadAt", "operator": "before", "value": "2026-01-01"},
            {"平凡日记"},
        ),
        (
            "date on or before",
            {"field": "lastReadAt", "operator": "on_or_before", "value": "2025-02-01"},
            {"平凡日记"},
        ),
        (
            "date between",
            {
                "field": "lastReadAt",
                "operator": "between",
                "value": ["2026-07-14", "2026-07-15"],
            },
            {"星海列车"},
        ),
        ("date empty", {"field": "lastReadAt", "operator": "is_empty"}, {"空白样本"}),
        (
            "date not empty",
            {"field": "lastReadAt", "operator": "is_not_empty"},
            {"星海列车", "平凡日记"},
        ),
        ("boolean true", {"field": "organized", "operator": "is_true"}, {"星海列车"}),
        (
            "boolean false",
            {"field": "organized", "operator": "is_false"},
            {"平凡日记", "空白样本"},
        ),
    ]
    for label, condition, expected_titles in cases:
        titles = set(
            _filtered_titles(
                client,
                {"combinator": "ALL", "conditions": [condition]},
            )
        )
        assert titles == expected_titles, label

    assert set(
        _filtered_titles(
            client,
            {
                "combinator": "ALL",
                "conditions": [
                    {"field": "title", "operator": "contains", "value": "星海"},
                    {"field": "format", "operator": "equals", "value": "EPUB"},
                ],
            },
        )
    ) == {"星海列车"}
    assert set(
        _filtered_titles(
            client,
            {
                "combinator": "ANY",
                "conditions": [
                    {"field": "title", "operator": "contains", "value": "星海"},
                    {"field": "title", "operator": "contains", "value": "平凡"},
                ],
            },
        )
    ) == {"星海列车", "平凡日记"}


def test_work_list_smart_filters_preserve_volume_authorization(
    client: TestClient,
    db_session: Session,
) -> None:
    user = User(
        id="smart-filter-member",
        email="smart-filter-member@example.com",
        name="Smart filter member",
        password_hash=hash_password("smart-filter-password"),
        role="member",
    )
    db_session.add(user)
    db_session.commit()
    _add_filter_matrix_fixture(db_session, user)
    db_session.add(
        UserMonitorFolderAccess(
            user_id=user.id,
            monitor_folder_id="folder-alpha",
        )
    )
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": user.email,
            "password": "smart-filter-password",
        },
    )
    assert response.status_code == 200

    assert _filtered_titles(
        client,
        {
            "combinator": "ANY",
            "conditions": [
                {"field": "title", "operator": "contains", "value": "星海"},
                {"field": "title", "operator": "contains", "value": "平凡"},
            ],
        },
    ) == ["星海列车"]


def test_work_list_rejects_invalid_smart_filter_expression(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)

    response = client.get(
        "/api/works",
        params={
            "filters": json.dumps(
                {
                    "combinator": "ALL",
                    "conditions": [
                        {
                            "field": "unsupportedField",
                            "operator": "equals",
                            "value": "anything",
                        }
                    ],
                }
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_work_list_rejects_removed_filter_dimensions_with_stable_code(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)

    for field in ("publishedYear", "publisher", "language", "isbn", "identifier"):
        response = client.get(
            "/api/works",
            params={
                "filters": json.dumps(
                    {
                        "combinator": "ALL",
                        "conditions": [
                            {"field": field, "operator": "equals", "value": "legacy"}
                        ],
                    }
                )
            },
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "UNSUPPORTED_FILTER_DIMENSION"


def test_legacy_smart_shelf_is_empty_and_can_remove_unsupported_rules(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    db_session.add(
        Shelf(
            id="legacy-publisher-shelf",
            owner_user_id=user.id,
            name="旧出版社书架",
            kind="SMART",
            rules_json=json.dumps(
                {
                    "combinator": "ALL",
                    "conditions": [
                        {
                            "field": "publisher",
                            "operator": "equals",
                            "value": "旧出版社",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
    )
    db_session.commit()

    response = client.get("/api/shelves/legacy-publisher-shelf")
    assert response.status_code == 200
    shelf = response.json()["data"]["shelf"]
    assert shelf["rulesStatus"] == "UNSUPPORTED"
    assert shelf["unsupportedRuleFields"] == ["publisher"]
    assert shelf["books"] == []

    repaired = client.patch(
        "/api/shelves/legacy-publisher-shelf",
        json={"rules": {"combinator": "ALL", "conditions": []}},
    )
    assert repaired.status_code == 200
    assert repaired.json()["data"]["shelf"]["rulesStatus"] == "VALID"

    rejected = client.post(
        "/api/shelves",
        json={
            "name": "不支持的书架",
            "kind": "SMART",
            "rules": {
                "combinator": "ALL",
                "conditions": [
                    {"field": "publisher", "operator": "equals", "value": "旧出版社"}
                ],
            },
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "UNSUPPORTED_FILTER_DIMENSION"
