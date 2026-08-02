from app.services.book_identity import identity_merge_key
from sqlalchemy import text
from tests.test_compat_api import _login, create_organize_detail_tables
from tests.test_worker_importer import create_worker_tables


def _insert_work(db, work_id, title, author):
    db.execute(
        text(
            """
            INSERT INTO LibraryWork (
                id, origin, title, normalizedTitle, author, normalizedAuthor, workType,
                publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverStatus,
                hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                :id, 'MANUAL', :title, :title, :author, :author, 'EPUB', 'UNKNOWN',
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


def test_manual_metadata_apply_writes_publisher_to_selected_volume(client, db_session):
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
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
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
    assert work.json()["data"]["book"]["metadataLookupStatus"] == "FAILED"
    assert work.json()["data"]["book"]["metadataLookupSource"] == "douban"
    assert work.json()["data"]["book"]["metadataLookupError"] == "gateway timeout"
    assert job.status_code == 200
    assert job.json()["data"]["job"]["metadataLookupStatus"] == "FAILED"
