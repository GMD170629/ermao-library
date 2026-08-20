from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import event, select, text

from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.modules.library.infrastructure import cover_publication, request_mutations
from app.services.book_identity import identity_merge_key
from tests.test_compat_api import _login, create_organize_detail_tables
from tests.test_worker_importer import create_worker_tables


def _insert_work(db, work_id, title, author):
    db.execute(
        text(
            """
            INSERT INTO LibraryWork (
                id, libraryId, origin, title, normalizedTitle, author, normalizedAuthor,
                publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverStatus,
                hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                :id, 'test-library', 'MANUAL', :title, :title, :author, :author, 'UNKNOWN',
                'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0, :merge_key, 'now', 'now'
            )
            """
        ),
        {
            "id": work_id,
            "title": title,
            "author": author,
            "merge_key": identity_merge_key(title, author),
        },
    )


def _png_cover() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 4), color=(20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


class _RemoteCoverResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._payload


def test_manual_identity_update_allows_same_title_and_author_without_merge_candidate(
    client, db_session
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _insert_work(db_session, "work-a", "原书名", "原作者")
    _insert_work(db_session, "work-b", "目标书名", "目标作者")
    db_session.commit()
    _login(client, db_session)

    duplicate = client.patch(
        "/api/works/work-a", json={"title": "目标书名", "author": "目标作者"}
    )

    assert duplicate.status_code == 200
    assert db_session.execute(
        text("SELECT mergeKey FROM LibraryWork WHERE id = 'work-a'")
    ).scalar() == identity_merge_key("目标书名", "目标作者")
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM DuplicateCandidate")).scalar()
        == 0
    )

    updated = client.patch(
        "/api/works/work-a", json={"title": " 新书名（典藏版） ", "author": "作者·甲"}
    )

    assert updated.status_code == 200
    row = (
        db_session.execute(
            text(
                "SELECT title, author, normalizedTitle, normalizedAuthor, mergeKey FROM LibraryWork WHERE id = 'work-a'"
            )
        )
        .mappings()
        .first()
    )
    assert row["title"] == "新书名（典藏版）"
    assert row["author"] == "作者·甲"
    assert row["normalizedTitle"] == "新书名典藏版"
    assert row["normalizedAuthor"] == "作者甲"
    assert row["mergeKey"] == "新书名典藏版:作者甲"


def test_metadata_recognition_applies_publisher_to_selected_volume(client, db_session):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _insert_work(db_session, "work-publisher", "出版测试", "测试作者")
    db_session.execute(
        text(
            """
            INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'media-publisher', 'work-publisher', 'EBOOK', 'now', 'now'
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryVolume (
                id, versionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'volume-publisher', 'media-publisher', 'MANUAL', 'EPUB', 0, 'EPUB',
                'epub:publisher', 'COMPLETED', 1, 'PENDING', 0, 'now', 'now'
            )
            """
        )
    )
    db_session.commit()
    _login(client, db_session)

    response = client.post(
        "/api/works/work-publisher/metadata/apply",
        json={
            "candidate": {"publisher": "新星出版社"},
            "fields": ["publisher"],
            "volumeId": "volume-publisher",
        },
    )

    assert response.status_code == 200
    assert (
        db_session.execute(
            text("SELECT publisher FROM LibraryVolume WHERE id = 'volume-publisher'")
        ).scalar()
        == "新星出版社"
    )


def test_remote_cover_download_holds_no_database_connection(
    client,
    db_session,
    test_settings,
    monkeypatch,
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _insert_work(db_session, "work-cover-pool", "封面连接", "作者")
    db_session.commit()
    _login(client, db_session)
    checked_out = 0

    def checkout(*_args: object) -> None:
        nonlocal checked_out
        checked_out += 1

    def checkin(*_args: object) -> None:
        nonlocal checked_out
        checked_out -= 1

    engine = db_session.get_bind()
    event.listen(engine.pool, "checkout", checkout)
    event.listen(engine.pool, "checkin", checkin)

    def remote_cover(*_args: object, **_kwargs: object) -> _RemoteCoverResponse:
        assert checked_out == 0
        assert db_session.in_transaction() is False
        return _RemoteCoverResponse(_png_cover())

    monkeypatch.setattr(cover_publication, "urlopen", remote_cover)
    try:
        response = client.post(
            "/api/works/work-cover-pool/metadata/apply",
            json={
                "candidate": {"coverUrl": "https://example.test/cover.png"},
                "fields": ["coverUrl"],
            },
        )
    finally:
        event.remove(engine.pool, "checkout", checkout)
        event.remove(engine.pool, "checkin", checkin)

    assert response.status_code == 200, response.text
    assert (
        test_settings.resolved_storage_root / "covers" / "work-cover-pool.png"
    ).is_file()


def test_remote_cover_database_failure_discards_the_unpublished_file(
    client,
    db_session,
    test_settings,
    monkeypatch,
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _insert_work(db_session, "work-cover-db-failure", "封面失败", "作者")
    db_session.commit()
    _login(client, db_session)
    monkeypatch.setattr(
        cover_publication,
        "urlopen",
        lambda *_args, **_kwargs: _RemoteCoverResponse(_png_cover()),
    )

    original_update = request_mutations.works.update_work_fields

    def fail_metadata_write(*args: object, **kwargs: object) -> None:
        original_update(*args, **kwargs)
        raise RuntimeError("metadata write failed")

    monkeypatch.setattr(
        request_mutations.works,
        "update_work_fields",
        fail_metadata_write,
    )
    with pytest.raises(RuntimeError, match="metadata write failed"):
        client.post(
            "/api/works/work-cover-db-failure/metadata/apply",
            json={
                "candidate": {"coverUrl": "https://example.test/cover.png"},
                "fields": ["coverUrl"],
            },
        )

    cover_dir = test_settings.resolved_storage_root / "covers"
    assert not (cover_dir / "work-cover-db-failure.png").exists()
    assert not list(cover_dir.glob(".work-cover-db-failure.*.part"))
    db_session.expire_all()
    work = db_session.get(LibraryWork, "work-cover-db-failure")
    assert work is not None
    assert work.cover_path is None


def test_remote_cover_publish_failure_uses_cas_compensation(
    client,
    db_session,
    test_settings,
    monkeypatch,
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _insert_work(db_session, "work-cover-publish-failure", "封面发布失败", "作者")
    db_session.commit()
    _login(client, db_session)
    monkeypatch.setattr(
        cover_publication,
        "urlopen",
        lambda *_args, **_kwargs: _RemoteCoverResponse(_png_cover()),
    )
    monkeypatch.setattr(
        cover_publication.RemoteCoverPublication,
        "publish",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("replace failed")),
    )

    response = client.post(
        "/api/works/work-cover-publish-failure/metadata/apply",
        json={
            "candidate": {"coverUrl": "https://example.test/cover.png"},
            "fields": ["coverUrl"],
        },
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    work = db_session.get(LibraryWork, "work-cover-publish-failure")
    assert work is not None
    assert work.cover_path is None
    assert work.cover_status == "FAILED"
    cover_dir = test_settings.resolved_storage_root / "covers"
    assert not (cover_dir / "work-cover-publish-failure.png").exists()
    assert list(cover_dir.glob(".work-cover-publish-failure.*.part"))


def test_manual_metadata_uses_representative_volume_to_update_entire_media_version(
    client, db_session
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    work = LibraryWork(
        library_id="test-library",
        id="work-version-metadata",
        title="多卷作品",
        normalized_title="多卷作品",
        author="作者",
        normalized_author="作者",
        tags="[]",
        merge_key=identity_merge_key("多卷作品", "作者"),
    )
    media_version = LibraryMediaVersion(
        id="media-version-metadata",
        work_id=work.id,
        media_kind="COMIC",
    )
    volumes = [
        LibraryVolume(
            id=f"volume-version-{index}",
            version_id=media_version.id,
            title=f"第 {index} 卷",
            sort_order=index,
            format="CBZ",
            resource_key=f"volume-version-{index}",
            import_status="READY",
        )
        for index in (1, 2)
    ]
    db_session.add_all([work, media_version, *volumes])
    db_session.commit()
    _login(client, db_session)

    response = client.post(
        "/api/works/work-version-metadata/metadata/apply",
        json={
            "candidate": {
                "volumeMetadata": {
                    "publisher": "全卷出版社",
                    "publishedAt": "2024-03-01T00:00:00Z",
                    "language": "ja",
                    "isbn": "9781234567897",
                }
            },
            "fields": ["publisher", "publishedAt", "language", "isbn"],
            "volumeId": "volume-version-1",
        },
    )

    assert response.status_code == 200, response.text
    refreshed_volumes = list(
        db_session.scalars(
            select(LibraryVolume)
            .where(LibraryVolume.version_id == media_version.id)
            .order_by(LibraryVolume.sort_order.asc())
        ).all()
    )
    assert len(refreshed_volumes) == 2
    assert all(volume.publisher == "全卷出版社" for volume in refreshed_volumes)
    assert all(volume.language == "ja" for volume in refreshed_volumes)
    assert all(volume.isbn == "9781234567897" for volume in refreshed_volumes)
    assert all(volume.published_at is not None for volume in refreshed_volumes)

    single_response = client.post(
        "/api/works/work-version-metadata/metadata/apply?applyToAllVolumes=false",
        json={
            "candidate": {"volumeMetadata": {"publisher": "第一卷出版社"}},
            "fields": ["publisher"],
            "volumeId": "volume-version-1",
        },
    )

    assert single_response.status_code == 200, single_response.text
    db_session.expire_all()
    assert db_session.get(LibraryVolume, "volume-version-1").publisher == "第一卷出版社"
    assert db_session.get(LibraryVolume, "volume-version-2").publisher == "全卷出版社"


def test_manual_metadata_apply_remains_available_after_organize_suggestion_apply_is_removed(
    client, db_session
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _insert_work(db_session, "work-target", "目标书名", "目标作者")
    _insert_work(db_session, "work-metadata", "元数据旧名", "旧作者")
    _insert_work(db_session, "work-organize", "整理旧名", "旧作者")
    db_session.execute(
        text(
            """
            INSERT INTO OrganizeJob (id, workId, status, issueCodes, summary, createdAt, updatedAt)
            VALUES ('job-identity', 'work-organize', 'REVIEWING', '[]', '等待确认', 'now', 'now')
            """
        )
    )
    for suggestion_id, field, value in (
        ("suggest-title", "title", "目标书名"),
        ("suggest-author", "author", "目标作者"),
    ):
        db_session.execute(
            text(
                """
                INSERT INTO MetadataSuggestion (
                    id, jobId, field, currentValue, suggestedValue, source, confidence,
                    reason, status, createdAt, updatedAt
                ) VALUES (
                    :id, 'job-identity', :field, 'null', :value, 'manual', 1.0,
                    'test', 'PENDING', 'now', 'now'
                )
                """
            ),
            {"id": suggestion_id, "field": field, "value": f'"{value}"'},
        )
    db_session.commit()
    _login(client, db_session)

    metadata = client.post(
        "/api/works/work-metadata/metadata/apply",
        json={
            "candidate": {"title": "目标书名", "author": "目标作者"},
            "fields": ["title", "author"],
        },
    )
    organized = client.post(
        "/api/organize/jobs/job-identity/apply",
        json={
            "suggestionIds": ["suggest-title", "suggest-author"],
            "markOrganized": True,
        },
    )

    assert metadata.status_code == 200
    assert organized.status_code == 404
    assert db_session.execute(
        text("SELECT mergeKey FROM LibraryWork WHERE id = 'work-metadata'")
    ).scalar() == identity_merge_key("目标书名", "目标作者")
    assert db_session.execute(
        text("SELECT mergeKey FROM LibraryWork WHERE id = 'work-organize'")
    ).scalar() == identity_merge_key("整理旧名", "旧作者")
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM MetadataSuggestion WHERE status = 'PENDING'")
        ).scalar()
        == 2
    )
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM DuplicateCandidate")).scalar()
        == 0
    )


def test_work_and_organize_views_expose_optional_lookup_status(client, db_session):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _insert_work(db_session, "work-status", "状态测试", "测试作者")
    db_session.execute(
        text(
            """
            INSERT INTO OrganizeJob (id, workId, status, issueCodes, summary, createdAt, updatedAt)
            VALUES ('job-status', 'work-status', 'REVIEWING', '[]', '等待检索', 'now', 'now')
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO MetadataLookupTask (
                id, workId, organizeJobId, status, providerOrder, attempts, resultSource,
                errorSummary, createdAt, updatedAt
            ) VALUES (
                'lookup-status', 'work-status', 'job-status', 'FAILED', '["douban","bangumi"]',
                4, 'douban', 'gateway timeout', 'now', 'now'
            )
            """
        )
    )
    db_session.commit()
    _login(client, db_session)

    work = client.get("/api/works/work-status")
    job = client.get("/api/organize/jobs/job-status")

    assert work.status_code == 200
    assert work.json()["data"]["book"]["id"] == "work-status"
    assert job.status_code == 200
    assert job.json()["data"]["job"]["metadataLookupStatus"] == "FAILED"
