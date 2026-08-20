from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.auth import hash_password
from app.main import create_app
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from sqlalchemy import inspect

FORBIDDEN_WORK_DETAIL_FIELDS = {
    "mediaVersions",
    "availableMediaKinds",
    "detailTabs",
    "selectedDetailTab",
    "recentMediaKind",
    "activeMedia",
}


def _login(client, db_session, *, email: str = "detail@example.com") -> User:
    user = User(
        email=email,
        name="Detail reader",
        password_hash=hash_password("detail-password"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "detail-password"},
    )
    assert response.status_code == 200
    return user


def _add_work(
    db_session,
    *,
    work_id: str = "detail-work",
    title: str = "Detail work",
) -> LibraryWork:
    work = LibraryWork(
        library_id="test-library",
        id=work_id,
        title=title,
        normalized_title=title.lower(),
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    db_session.add(work)
    db_session.flush()
    return work


def _add_version(
    db_session,
    *,
    work_id: str,
    version_id: str,
    source_key: str = IMPLICIT_VERSION_SOURCE_KEY,
    source_name: str | None = None,
) -> LibraryVersion:
    version = LibraryVersion(
        id=version_id,
        work_id=work_id,
        source_key=source_key,
        source_name=source_name,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _add_volume(
    db_session,
    *,
    version_id: str,
    volume_id: str,
    title: str,
    fmt: str,
    sort_order: int,
    size_bytes: int = 100,
    page_count: int | None = 2,
) -> LibraryVolume:
    volume = LibraryVolume(
        id=volume_id,
        version_id=version_id,
        title=title,
        volume_index=sort_order + 1,
        sort_order=sort_order,
        format=fmt,
        resource_key=f"detail:{volume_id}",
        import_status="COMPLETED",
        size_bytes=size_bytes,
        page_count=page_count,
    )
    file = LibraryFile(
        id=f"{volume_id}-file",
        volume_id=volume.id,
        path=f"/library/{volume_id}.bin",
        kind=fmt,
        mime_type="application/octet-stream",
        size_bytes=size_bytes,
        sort_order=0,
    )
    db_session.add(volume)
    db_session.flush()
    db_session.add(file)
    return volume


def _add_progress(
    db_session,
    *,
    user_id: str,
    volume_id: str,
    percent: float,
    updated_at: datetime,
) -> None:
    db_session.add(
        LibraryReadingProgress(
            user_id=user_id,
            volume_id=volume_id,
            reader_type="reflowable",
            position="0",
            percent=percent,
            extra="{}",
            schema_version=4,
            location_type="reflowable",
            location_json="{}",
            created_at=updated_at,
            updated_at=updated_at,
        )
    )


def _add_work_with_volumes(db_session, *, volume_count: int = 12) -> None:
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="detail-version")
    for index in range(volume_count):
        volume_number = index + 1
        _add_volume(
            db_session,
            version_id="detail-version",
            volume_id=f"detail-volume-{volume_number:02d}",
            title=f"第 {volume_number} 卷",
            fmt="COMIC",
            sort_order=index,
            size_bytes=volume_number * 100,
        )
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


def _assert_no_legacy_detail_fields(payload: object) -> None:
    if isinstance(payload, dict):
        assert FORBIDDEN_WORK_DETAIL_FIELDS.isdisjoint(payload)
        for value in payload.values():
            _assert_no_legacy_detail_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_legacy_detail_fields(item)


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
        "continueVolumeId",
        "continueVolumeProgress",
        "completed",
        "versions",
    }
    _assert_no_legacy_detail_fields(data)
    version = data["book"]["versions"][0]
    assert version["id"] == "detail-version"
    assert version["sourceKey"] == IMPLICIT_VERSION_SOURCE_KEY
    assert version["sourceName"] is None
    assert version["volumeCount"] == 12
    assert version["sizeBytes"] == sum(number * 100 for number in range(1, 13))
    assert [volume["id"] for volume in version["volumes"]] == [
        f"detail-volume-{number:02d}" for number in range(1, 11)
    ]
    assert [volume["versionId"] for volume in version["volumes"]] == [
        "detail-version"
    ] * 10
    assert [volume["files"][0]["path"] for volume in version["volumes"]] == [
        f"/library/detail-volume-{number:02d}.bin" for number in range(1, 11)
    ]


def test_work_volume_query_pages_deterministically_and_includes_file_summaries(
    client, db_session
):
    _login(client, db_session)
    _add_work_with_volumes(db_session)

    response = client.get(
        "/api/works/detail-work/versions/detail-version/volumes",
        params={"page": 2, "pageSize": 5},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["versionId"] == "detail-version"
    assert data["sourceKey"] == IMPLICIT_VERSION_SOURCE_KEY
    assert data["sourceName"] is None
    assert data["page"] == 2
    assert data["pageSize"] == 5
    assert data["total"] == 12
    assert data["totalPages"] == 3
    assert "mediaKind" not in data
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
        "currentChapterTitle",
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


def test_work_reading_units_query_projects_exact_readium_chapter_location(
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
            schema_version=4,
            location_type="reflowable",
            location_json='{"engine":"readium","platform":"web","version":"readium-ts:2.8.2","publication":{"originalFileHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","parser":"shuku-txt-parser-v1","normalization":"shuku-txt-publication-v2"},"payload":{"href":"002.jpg","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-2"},"text":{"highlight":"第二章"}}}',
        )
    )
    db_session.commit()

    response = client.get(
        "/api/works/detail-work/volumes/detail-volume-01/reading-units",
        params={"page": 1, "pageSize": 1},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [unit["id"] for unit in data["units"]] == ["detail-page-1"]
    assert data["currentHref"] == "002.jpg"
    assert data["currentChapterIndex"] == 1
    assert data["currentChapterSortOrder"] == 1


def test_work_detail_queries_preserve_authentication_and_not_found_contracts(
    client, db_session
):
    _add_work_with_volumes(db_session)
    assert client.get("/api/works/detail-work").status_code == 401

    _login(client, db_session)
    missing_page = client.get("/api/works/detail-work/versions/missing-version/volumes")
    missing_units = client.get(
        "/api/works/detail-work/volumes/missing-volume/reading-units"
    )
    assert missing_page.status_code == 404
    assert missing_units.status_code == 404
    assert (
        client.get(
            "/api/works/detail-work/media-versions/detail-version/volumes"
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/api/works/detail-work/detail-preference", json={"selectedTab": "EBOOK"}
        ).status_code
        == 404
    )


def test_work_detail_groups_implicit_and_named_versions(client, db_session):
    _login(client, db_session)
    work = _add_work(db_session, work_id="mixed-versions")
    _add_version(
        db_session,
        work_id=work.id,
        version_id="named-version",
        source_key="calibre",
        source_name="Calibre",
    )
    _add_version(db_session, work_id=work.id, version_id="implicit-version")
    _add_volume(
        db_session,
        version_id="named-version",
        volume_id="named-volume",
        title="Named",
        fmt="EPUB",
        sort_order=0,
        size_bytes=20,
    )
    _add_volume(
        db_session,
        version_id="implicit-version",
        volume_id="implicit-volume",
        title="Implicit",
        fmt="PDF",
        sort_order=0,
        size_bytes=10,
    )
    db_session.commit()

    book = client.get("/api/works/mixed-versions").json()["data"]["book"]
    assert [version["id"] for version in book["versions"]] == [
        "implicit-version",
        "named-version",
    ]
    assert book["versions"][0]["sourceKey"] == IMPLICIT_VERSION_SOURCE_KEY
    assert book["versions"][1]["sourceName"] == "Calibre"


def test_work_detail_keeps_mixed_formats_in_one_version(client, db_session):
    _login(client, db_session)
    work = _add_work(db_session, work_id="mixed-formats")
    _add_version(db_session, work_id=work.id, version_id="mixed-version")
    for index, (volume_id, fmt) in enumerate(
        (
            ("epub-volume", "EPUB"),
            ("pdf-volume", "PDF"),
            ("cbz-volume", "CBZ"),
            ("audio-volume", "AUDIO"),
        )
    ):
        _add_volume(
            db_session,
            version_id="mixed-version",
            volume_id=volume_id,
            title=fmt,
            fmt=fmt,
            sort_order=index,
        )
    db_session.commit()

    book = client.get("/api/works/mixed-formats").json()["data"]["book"]
    assert [version["id"] for version in book["versions"]] == ["mixed-version"]
    assert [volume["id"] for volume in book["versions"][0]["volumes"]] == [
        "epub-volume",
        "pdf-volume",
        "cbz-volume",
        "audio-volume",
    ]
    assert [volume["format"] for volume in book["versions"][0]["volumes"]] == [
        "EPUB",
        "PDF",
        "CBZ",
        "AUDIO",
    ]


def test_work_detail_returns_directory_versions(client, db_session):
    _login(client, db_session)
    work = _add_work(db_session, work_id="no-media-rows")
    _add_version(db_session, work_id=work.id, version_id="plain-version")
    _add_volume(
        db_session,
        version_id="plain-version",
        volume_id="plain-volume",
        title="Plain",
        fmt="EPUB",
        sort_order=0,
    )
    db_session.commit()
    book = client.get("/api/works/no-media-rows").json()["data"]["book"]
    assert [version["id"] for version in book["versions"]] == ["plain-version"]
    units = client.get("/api/works/no-media-rows/volumes/plain-volume/reading-units")
    assert units.status_code == 200


def test_version_completed_is_scoped_to_own_volumes(client, db_session):
    user = _login(client, db_session)
    work = _add_work(db_session, work_id="scoped-complete")
    _add_version(db_session, work_id=work.id, version_id="finished-version")
    _add_version(
        db_session,
        work_id=work.id,
        version_id="open-version",
        source_key="named",
        source_name="Named",
    )
    _add_volume(
        db_session,
        version_id="finished-version",
        volume_id="finished-volume",
        title="Finished",
        fmt="EPUB",
        sort_order=0,
    )
    _add_volume(
        db_session,
        version_id="open-version",
        volume_id="open-volume",
        title="Open",
        fmt="PDF",
        sort_order=0,
    )
    now = datetime.now(UTC)
    _add_progress(
        db_session,
        user_id=user.id,
        volume_id="finished-volume",
        percent=100,
        updated_at=now - timedelta(hours=2),
    )
    _add_progress(
        db_session,
        user_id=user.id,
        volume_id="open-volume",
        percent=40,
        updated_at=now,
    )
    db_session.commit()

    book = client.get("/api/works/scoped-complete").json()["data"]["book"]
    by_id = {version["id"]: version for version in book["versions"]}
    assert by_id["finished-version"]["completed"] is True
    assert by_id["open-version"]["completed"] is False
    assert book["completed"] is False
    assert book["continueVolumeId"] == "open-volume"


def test_continue_volume_can_cross_versions(client, db_session):
    user = _login(client, db_session)
    work = _add_work(db_session, work_id="cross-continue")
    _add_version(db_session, work_id=work.id, version_id="first-version")
    _add_version(
        db_session,
        work_id=work.id,
        version_id="second-version",
        source_key="named",
        source_name="Named",
    )
    _add_volume(
        db_session,
        version_id="first-version",
        volume_id="first-volume",
        title="First",
        fmt="EPUB",
        sort_order=0,
    )
    _add_volume(
        db_session,
        version_id="second-version",
        volume_id="second-volume",
        title="Second",
        fmt="PDF",
        sort_order=0,
    )
    now = datetime.now(UTC)
    _add_progress(
        db_session,
        user_id=user.id,
        volume_id="first-volume",
        percent=20,
        updated_at=now - timedelta(hours=1),
    )
    _add_progress(
        db_session,
        user_id=user.id,
        volume_id="second-volume",
        percent=55,
        updated_at=now,
    )
    db_session.commit()

    book = client.get("/api/works/cross-continue").json()["data"]["book"]
    assert book["continueVolumeId"] == "second-volume"
    assert book["continueVolumeProgress"] == 55


def test_version_volume_page_does_not_leak_other_versions(client, db_session):
    _login(client, db_session)
    work = _add_work(db_session, work_id="page-scope")
    _add_version(db_session, work_id=work.id, version_id="alpha-version")
    _add_version(
        db_session,
        work_id=work.id,
        version_id="beta-version",
        source_key="beta",
        source_name="Beta",
    )
    _add_volume(
        db_session,
        version_id="alpha-version",
        volume_id="alpha-volume",
        title="Alpha",
        fmt="EPUB",
        sort_order=0,
    )
    _add_volume(
        db_session,
        version_id="beta-version",
        volume_id="beta-volume",
        title="Beta",
        fmt="PDF",
        sort_order=0,
    )
    db_session.commit()

    data = client.get("/api/works/page-scope/versions/alpha-version/volumes").json()[
        "data"
    ]
    assert data["versionId"] == "alpha-version"
    assert [volume["id"] for volume in data["volumes"]] == ["alpha-volume"]
    assert data["total"] == 1
    other_work = client.get("/api/works/page-scope/versions/beta-version/volumes")
    assert [volume["id"] for volume in other_work.json()["data"]["volumes"]] == [
        "beta-volume"
    ]


def test_reading_units_membership_uses_library_version_work_id(client, db_session):
    _login(client, db_session)
    work = _add_work(db_session, work_id="units-owner")
    other = _add_work(db_session, work_id="units-other", title="Other")
    _add_version(db_session, work_id=work.id, version_id="owner-version")
    _add_version(db_session, work_id=other.id, version_id="other-version")
    _add_volume(
        db_session,
        version_id="owner-version",
        volume_id="owner-volume",
        title="Owner",
        fmt="EPUB",
        sort_order=0,
    )
    _add_volume(
        db_session,
        version_id="other-version",
        volume_id="other-volume",
        title="Other",
        fmt="EPUB",
        sort_order=0,
    )
    db_session.commit()
    inspector = inspect(db_session.connection())
    assert "workId" not in {
        column["name"] for column in inspector.get_columns("LibraryVolume")
    }

    owned = client.get("/api/works/units-owner/volumes/owner-volume/reading-units")
    leaked = client.get("/api/works/units-owner/volumes/other-volume/reading-units")
    assert owned.status_code == 200
    assert leaked.status_code == 404


def test_work_detail_openapi_exposes_versions_instead_of_media_tabs() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]
    components = schema["components"]["schemas"]
    assert "/api/works/{work_id}/versions/{version_id}/volumes" in paths
    assert "/api/works/{work_id}/media-versions/{version_id}/volumes" not in paths
    assert "/api/works/{work_id}/detail-preference" not in paths
    get_work = paths["/api/works/{work_id}"]["get"]
    parameter_names = {item["name"] for item in get_work.get("parameters", [])}
    assert parameter_names.isdisjoint(
        {"detailTab", "unitPage", "chapterPage", "chapterPageSize", "volumeId"}
    )
    for name in (
        "WorkDetailTab",
        "ActiveMedia",
        "WorkDetailPayload",
        "WorkDetailMediaVersion",
        "SaveDetailPreferenceRequest",
        "DetailPreferencePayload",
        "LibraryMediaVersion",
    ):
        assert name not in components
    book_schema = components["WorkDetailBook"]["properties"]
    assert "versions" in book_schema
    assert FORBIDDEN_WORK_DETAIL_FIELDS.isdisjoint(book_schema)
    version_page = components["WorkVolumePagePayload"]["properties"]
    assert "versionId" in version_page
    assert "sourceKey" in version_page
    assert "mediaKind" not in version_page
