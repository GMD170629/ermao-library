from __future__ import annotations

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)


def _login(client, db_session) -> User:
    user = User(
        email="detail@example.com",
        name="Detail reader",
        password_hash=hash_password("detail-password"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "detail@example.com", "password": "detail-password"},
    )
    assert response.status_code == 200
    return user


def _add_work_with_volumes(db_session, *, volume_count: int = 12) -> None:
    work = LibraryWork(
        id="detail-work",
        title="Detail work",
        normalized_title="detail work",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id="detail-media",
        work_id=work.id,
        media_kind="COMIC",
    )
    db_session.add_all([work, media_version])
    for index in range(volume_count):
        volume_number = index + 1
        volume = LibraryVolume(
            id=f"detail-volume-{volume_number:02d}",
            media_version_id=media_version.id,
            title=f"第 {volume_number} 卷",
            volume_index=volume_number,
            sort_order=index,
            format="COMIC",
            resource_key=f"detail:{volume_number}",
            import_status="COMPLETED",
            size_bytes=volume_number * 100,
            page_count=2,
        )
        file = LibraryFile(
            id=f"detail-file-{volume_number:02d}",
            volume_id=volume.id,
            path=f"/library/detail-{volume_number:02d}.zip",
            kind="COMIC",
            mime_type="application/zip",
            size_bytes=volume_number * 100,
            sort_order=0,
        )
        db_session.add_all([volume, file])
    db_session.add_all(
        [
            LibraryReadingUnit(
                id="detail-page-1",
                volume_id="detail-volume-01",
                unit_type="page",
                title="001.jpg",
                href="001.jpg",
                sort_order=0,
                metadata_json="{}",
            ),
            LibraryReadingUnit(
                id="detail-page-2",
                volume_id="detail-volume-01",
                unit_type="page",
                title="002.jpg",
                href="002.jpg",
                sort_order=1,
                metadata_json="{}",
            ),
        ]
    )
    db_session.commit()


def test_default_work_detail_is_bounded_and_includes_file_paths(client, db_session):
    _login(client, db_session)
    _add_work_with_volumes(db_session)

    response = client.get("/api/works/detail-work")

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {"book"}
    assert set(data["book"]) == {
        "id",
        "title",
        "author",
        "description",
        "tags",
        "seriesName",
        "seriesIndex",
        "seriesFacet",
        "authorFacets",
        "coverStatus",
        "coverUrl",
        "recentMediaKind",
        "continueVolumeId",
        "completed",
        "mediaVersions",
        "availableMediaKinds",
        "detailTabs",
        "selectedDetailTab",
    }
    media_version = data["book"]["mediaVersions"][0]
    assert media_version["volumeCount"] == 12
    assert media_version["sizeBytes"] == sum(number * 100 for number in range(1, 13))
    assert [volume["id"] for volume in media_version["volumes"]] == [
        f"detail-volume-{number:02d}" for number in range(1, 11)
    ]
    assert [volume["files"][0]["path"] for volume in media_version["volumes"]] == [
        f"/library/detail-{number:02d}.zip" for number in range(1, 11)
    ]


def test_work_volume_query_pages_deterministically_and_includes_file_summaries(
    client, db_session
):
    _login(client, db_session)
    _add_work_with_volumes(db_session)

    response = client.get(
        "/api/works/detail-work/media-versions/detail-media/volumes",
        params={"page": 2, "pageSize": 5},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page"] == 2
    assert data["pageSize"] == 5
    assert data["total"] == 12
    assert data["totalPages"] == 3
    assert [volume["id"] for volume in data["volumes"]] == [
        f"detail-volume-{number:02d}" for number in range(6, 11)
    ]
    assert set(data["volumes"][0]["files"][0]) == {
        "id",
        "path",
        "sizeBytes",
        "size",
    }


def test_work_reading_units_query_returns_only_requested_navigation(client, db_session):
    _login(client, db_session)
    _add_work_with_volumes(db_session)

    response = client.get(
        "/api/works/detail-work/volumes/detail-volume-01/reading-units",
        params={"page": 1, "pageSize": 1},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {
        "units",
        "page",
        "progress",
        "currentHref",
        "currentChapterIndex",
        "currentChapterSortOrder",
        "currentPageNumber",
    }
    assert [unit["id"] for unit in data["units"]] == ["detail-page-1"]
    assert data["page"] == {
        "page": 1,
        "pageSize": 1,
        "total": 2,
        "totalPages": 2,
    }


def test_work_reading_units_query_projects_reader_v3_chapter_location(
    client, db_session
):
    user = _login(client, db_session)
    _add_work_with_volumes(db_session)
    db_session.add(
        LibraryReadingProgress(
            user_id=user.id,
            volume_id="detail-volume-01",
            reader_type="reflowable",
            position="0",
            percent=12.5,
            extra="{}",
            schema_version=3,
            location_type="reflowable",
            location_json='{"type":"reflowable","format":"txt","href":"002.jpg","foliate":{"toc":{"index":1,"title":"第二章","href":"002.jpg"},"section":{"current":1,"total":2}}}',
        )
    )
    db_session.commit()

    response = client.get(
        "/api/works/detail-work/volumes/detail-volume-01/reading-units",
        params={"page": 1, "pageSize": 2},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["currentHref"] == "002.jpg"
    assert data["currentChapterIndex"] == 1
    assert data["currentChapterSortOrder"] == 1


def test_work_detail_queries_preserve_authentication_and_not_found_contracts(
    client, db_session
):
    _add_work_with_volumes(db_session)
    assert client.get("/api/works/detail-work").status_code == 401

    _login(client, db_session)
    missing_page = client.get(
        "/api/works/detail-work/media-versions/missing-media/volumes"
    )
    missing_units = client.get(
        "/api/works/detail-work/volumes/missing-volume/reading-units"
    )
    assert missing_page.status_code == 404
    assert missing_units.status_code == 404
