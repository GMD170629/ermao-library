import json

import pytest
from app.services import metadata_lookup_queue as queue
from app.services.metadata_lookup_queue import (
    process_metadata_lookup_task,
    recover_stale_metadata_lookup_tasks,
)
from app.services.organize_service import (
    external_metadata_cache_get,
    external_metadata_cache_put,
    metadata_candidate_title_exact_match,
    metadata_search_candidates,
    run_bangumi_metadata_provider,
    run_douban_metadata_provider,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tests.test_worker_importer import create_worker_tables


def _insert_lookup_fixture(
    db,
    *,
    title="黑暗坡食人树",
    author="岛田庄司",
    provider_order=None,
    local_cover="covers/local.jpg",
):
    for statement in (
        "ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT",
        "ALTER TABLE LibraryWork ADD COLUMN seriesIndex REAL",
        "ALTER TABLE LibraryWork ADD COLUMN publishedYear INTEGER",
        "ALTER TABLE OrganizeJob ADD COLUMN startedAt TEXT",
        "ALTER TABLE OrganizeJob ADD COLUMN finishedAt TEXT",
    ):
        try:
            db.execute(text(statement))
        except OperationalError:
            pass
    db.execute(
        text(
            """
            INSERT INTO LibraryWork (
                id, origin, title, normalizedTitle, author, normalizedAuthor, workType,
                publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverPath,
                coverStatus, hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-lookup', 'MANUAL', :title, :title, :author, :author,
                'EPUB', 'UNKNOWN', 'NOT_TRACKING', '["epub"]', 0, 'LOOKUP_PENDING',
                :cover_path, :cover_status, 0, 0, :merge_key, 'now', 'now'
            )
            """
        ),
        {
            "title": title,
            "author": author,
            "merge_key": f"{title}:{author}",
            "cover_path": local_cover,
            "cover_status": "READY" if local_cover else "PENDING",
        },
    )
    db.execute(
        text(
            """
            INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'media-lookup', 'work-lookup', 'EBOOK', 'now', 'now'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey, publisher,
                importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'volume-lookup', 'media-lookup', 'MANUAL', 'EPUB', 0, 'EPUB', 'epub:test', NULL,
                'COMPLETED', 1, 'PENDING', 0, 'now', 'now'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO ImportTask (
                id, workId, volumeId, origin, status, sourcePath, progress, duplicate, duration,
                createdAt, updatedAt
            ) VALUES (
                'import-lookup', 'work-lookup', 'volume-lookup', 'MANUAL', 'COMPLETED', '/book.epub',
                100, 0, 1, 'now', 'now'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO OrganizeJob (
                id, workId, volumeId, importTaskId, status, issueCodes, summary, createdAt, updatedAt
            ) VALUES (
                'job-lookup', 'work-lookup', 'volume-lookup', 'import-lookup', 'LOOKUP_PENDING', '[]',
                '等待元数据', 'now', 'now'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO MetadataLookupTask (
                id, workId, volumeId, importTaskId, organizeJobId, status, providerOrder, attempts,
                nextAttemptAt, startedAt, createdAt, updatedAt
            ) VALUES (
                'lookup-1', 'work-lookup', 'volume-lookup', 'import-lookup', 'job-lookup', 'RUNNING',
                :provider_order, 0, 'now', 'now', 'now', 'now'
            )
            """
        ),
        {"provider_order": json.dumps(provider_order or ["douban", "bangumi"])},
    )
    db.commit()
    return dict(
        db.execute(text("SELECT * FROM MetadataLookupTask WHERE id = 'lookup-1'"))
        .mappings()
        .first()
    )


def test_lookup_applies_exact_candidate_without_overwriting_identity_or_local_cover(
    db_session, test_settings, monkeypatch
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(db_session)
    candidate = {
        "id": "douban-1",
        "source": "douban",
        "title": "黑暗坡食人树",
        "author": "岛田庄司",
        "description": "外部简介",
        "tags": ["推理", "本格"],
        "publisher": "新星出版社",
        "seriesName": "午夜文库",
        "publishedYear": 2024,
        "coverUrl": "https://example.invalid/cover.jpg",
    }
    monkeypatch.setattr(
        queue,
        "search_with_metadata_provider",
        lambda *_args, **_kwargs: {
            "enabled": True,
            "cacheHit": False,
            "candidates": [candidate],
        },
    )
    monkeypatch.setattr(
        queue,
        "_download_remote_cover",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local cover must win")
        ),
    )

    assert process_metadata_lookup_task(db_session, test_settings, task) == "COMPLETED"

    work = (
        db_session.execute(text("SELECT * FROM LibraryWork WHERE id = 'work-lookup'"))
        .mappings()
        .first()
    )
    assert work["title"] == "黑暗坡食人树"
    assert work["author"] == "岛田庄司"
    assert work["description"] == "外部简介"
    assert work["coverPath"] == "covers/local.jpg"
    assert json.loads(work["tags"]) == ["epub"]
    assert work["seriesName"] == "午夜文库"
    assert work["publishedYear"] == 2024
    assert work["organized"] == 1
    assert work["organizeStatus"] == "APPLIED"
    assert (
        db_session.execute(
            text("SELECT status FROM OrganizeJob WHERE id = 'job-lookup'")
        ).scalar()
        == "APPLIED"
    )
    assert (
        db_session.execute(
            text("SELECT publisher FROM LibraryVolume WHERE id = 'volume-lookup'")
        ).scalar()
        == "新星出版社"
    )
    lookup = (
        db_session.execute(
            text(
                "SELECT status, resultSource, appliedFields FROM MetadataLookupTask WHERE id = 'lookup-1'"
            )
        )
        .mappings()
        .first()
    )
    assert lookup["status"] == "COMPLETED"
    assert lookup["resultSource"] == "douban"
    assert "publisher" in json.loads(lookup["appliedFields"])
    assert (
        db_session.execute(
            text(
                "SELECT source FROM LibraryMetadata WHERE volumeId = 'volume-lookup' ORDER BY createdAt DESC LIMIT 1"
            )
        ).scalar()
        == "douban"
    )


def test_single_exact_title_match_completes_organizing_with_unknown_author(
    db_session, test_settings, monkeypatch
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(db_session, author="未知作者")
    candidate = {
        "id": "douban-unknown-author",
        "source": "douban",
        "title": "黑暗坡食人树",
        "author": "岛田庄司",
    }
    monkeypatch.setattr(
        queue,
        "search_with_metadata_provider",
        lambda *_args, **_kwargs: {"enabled": True, "candidates": [candidate]},
    )

    assert process_metadata_lookup_task(db_session, test_settings, task) == "COMPLETED"
    state = (
        db_session.execute(
            text(
                "SELECT author, organized, organizeStatus FROM LibraryWork WHERE id = 'work-lookup'"
            )
        )
        .mappings()
        .one()
    )
    assert state["author"] == "岛田庄司"
    assert state["organized"] == 1
    assert state["organizeStatus"] == "APPLIED"
    assert (
        db_session.execute(
            text("SELECT status FROM OrganizeJob WHERE id = 'job-lookup'")
        ).scalar()
        == "APPLIED"
    )


def test_lookup_applies_bangumi_candidate_when_local_title_is_an_exact_alias(
    db_session, test_settings, monkeypatch
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(
        db_session, title="鹰峰同学请穿上衣服", author="柊裕一"
    )
    candidate = {
        "id": "272395",
        "source": "bangumi",
        "title": "拜托请穿上，鹰峰同学",
        "author": "柊裕一",
        "description": "Bangumi 条目简介",
        "raw": {
            "name": "履いてください、鷹峰さん",
            "name_cn": "拜托请穿上，鹰峰同学",
            "infobox": [
                {"key": "别名", "value": [{"k": "非官方", "v": "鹰峰同学请穿上衣服"}]}
            ],
        },
    }
    monkeypatch.setattr(
        queue,
        "search_with_metadata_provider",
        lambda *_args, **_kwargs: {"enabled": True, "candidates": [candidate]},
    )

    assert process_metadata_lookup_task(db_session, test_settings, task) == "COMPLETED"
    work = (
        db_session.execute(
            text(
                "SELECT title, description, organized, organizeStatus FROM LibraryWork WHERE id = 'work-lookup'"
            )
        )
        .mappings()
        .one()
    )
    assert dict(work) == {
        "title": "拜托请穿上，鹰峰同学",
        "description": "Bangumi 条目简介",
        "organized": 1,
        "organizeStatus": "APPLIED",
    }
    assert (
        db_session.execute(
            text("SELECT status FROM OrganizeJob WHERE id = 'job-lookup'")
        ).scalar()
        == "APPLIED"
    )


def test_cached_bangumi_candidate_matches_alias_from_raw_infobox():
    candidate = {
        "title": "拜托请穿上，鹰峰同学",
        "raw": {
            "infobox": [
                {"key": "别名", "value": [{"k": "非官方", "v": "鹰峰同学请穿上衣服"}]}
            ]
        },
    }

    assert metadata_candidate_title_exact_match("鹰峰同学请穿上衣服", candidate) is True
    assert (
        metadata_candidate_title_exact_match("鹰峰同学请穿上衣服 第二季", candidate)
        is False
    )


def test_lookup_uses_provider_order_and_author_to_disambiguate(
    db_session, test_settings, monkeypatch
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(db_session, local_cover=None)
    calls = []

    def search(_db, _context, provider, *_args, **_kwargs):
        calls.append(provider)
        if provider == "douban":
            return {
                "enabled": True,
                "candidates": [{"title": "近似标题", "author": "岛田庄司"}],
            }
        return {
            "enabled": True,
            "candidates": [
                {
                    "id": "wrong",
                    "title": "黑暗坡食人树",
                    "author": "他人",
                    "description": "错误",
                },
                {
                    "id": "right",
                    "title": "黑暗坡食人树",
                    "author": "岛田庄司",
                    "description": "正确",
                },
            ],
        }

    monkeypatch.setattr(queue, "search_with_metadata_provider", search)

    assert process_metadata_lookup_task(db_session, test_settings, task) == "COMPLETED"
    assert calls == ["douban", "bangumi"]
    assert (
        db_session.execute(
            text("SELECT description FROM LibraryWork WHERE id = 'work-lookup'")
        ).scalar()
        == "正确"
    )
    assert (
        db_session.execute(
            text("SELECT resultSource FROM MetadataLookupTask WHERE id = 'lookup-1'")
        ).scalar()
        == "bangumi"
    )


def test_lookup_keeps_ambiguous_exact_candidates_for_review(
    db_session, test_settings, monkeypatch
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(db_session)
    ambiguous = [
        {"id": "a", "title": "黑暗坡食人树", "author": "甲"},
        {"id": "b", "title": "黑暗坡食人树", "author": "乙"},
    ]
    monkeypatch.setattr(
        queue,
        "search_with_metadata_provider",
        lambda *_args, **_kwargs: {"enabled": True, "candidates": ambiguous},
    )

    assert process_metadata_lookup_task(db_session, test_settings, task) == "NO_MATCH"
    assert (
        db_session.execute(
            text("SELECT status FROM MetadataLookupTask WHERE id = 'lookup-1'")
        ).scalar()
        == "NO_MATCH"
    )
    assert (
        db_session.execute(
            text("SELECT organizeStatus FROM LibraryWork WHERE id = 'work-lookup'")
        ).scalar()
        == "REVIEWING"
    )
    assert (
        db_session.execute(
            text("SELECT status FROM OrganizeJob WHERE id = 'job-lookup'")
        ).scalar()
        == "FAILED"
    )


def test_lookup_returns_no_provider_when_all_sources_are_disabled(
    db_session, test_settings
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(db_session)

    assert (
        process_metadata_lookup_task(db_session, test_settings, task) == "NO_PROVIDER"
    )
    row = (
        db_session.execute(
            text(
                "SELECT status, errorSummary FROM MetadataLookupTask WHERE id = 'lookup-1'"
            )
        )
        .mappings()
        .first()
    )
    assert row["status"] == "NO_PROVIDER"
    assert "均未启用" in row["errorSummary"]
    assert (
        db_session.execute(
            text("SELECT organizeStatus FROM LibraryWork WHERE id = 'work-lookup'")
        ).scalar()
        == "REVIEWING"
    )
    assert (
        db_session.execute(
            text("SELECT status FROM OrganizeJob WHERE id = 'job-lookup'")
        ).scalar()
        == "FAILED"
    )


def test_cancelled_lookup_and_parent_cannot_be_reopened_by_stale_worker(
    db_session, test_settings
):
    create_worker_tables(db_session)
    stale_task = _insert_lookup_fixture(db_session)
    db_session.execute(
        text(
            "UPDATE MetadataLookupTask SET status = 'CANCELLED', finishedAt = 'now' WHERE id = 'lookup-1'"
        )
    )
    db_session.execute(
        text(
            "UPDATE OrganizeJob SET status = 'CANCELLED', summary = '已取消' WHERE id = 'job-lookup'"
        )
    )
    db_session.commit()

    assert (
        process_metadata_lookup_task(db_session, test_settings, stale_task)
        == "CANCELLED"
    )
    assert (
        db_session.execute(
            text("SELECT status FROM MetadataLookupTask WHERE id = 'lookup-1'")
        ).scalar()
        == "CANCELLED"
    )
    job = (
        db_session.execute(
            text("SELECT status, summary FROM OrganizeJob WHERE id = 'job-lookup'")
        )
        .mappings()
        .one()
    )
    assert dict(job) == {"status": "CANCELLED", "summary": "已取消"}


def test_lookup_uses_three_retry_delays_then_fails(
    db_session, test_settings, monkeypatch
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(db_session)
    monkeypatch.setattr(
        queue,
        "search_with_metadata_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError("gateway timeout")
        ),
    )

    expected = ["PENDING", "PENDING", "PENDING", "FAILED"]
    for expected_status in expected:
        assert (
            process_metadata_lookup_task(db_session, test_settings, task)
            == expected_status
        )
        task = dict(
            db_session.execute(
                text("SELECT * FROM MetadataLookupTask WHERE id = 'lookup-1'")
            )
            .mappings()
            .first()
        )
        expected_organize_status = (
            "FAILED" if expected_status == "FAILED" else "LOOKUP_PENDING"
        )
        assert (
            db_session.execute(
                text("SELECT status FROM OrganizeJob WHERE id = 'job-lookup'")
            ).scalar()
            == expected_organize_status
        )

    assert task["attempts"] == 4
    assert task["nextAttemptAt"] is None
    assert "gateway timeout" in task["errorSummary"]
    assert (
        db_session.execute(
            text("SELECT organizeStatus FROM LibraryWork WHERE id = 'work-lookup'")
        ).scalar()
        == "REVIEWING"
    )


def test_lookup_keeps_existing_identity_when_overwrite_is_disabled_and_fills_other_gaps(
    db_session, test_settings, monkeypatch
):
    create_worker_tables(db_session)
    task = _insert_lookup_fixture(
        db_session, title="鹰峰同学请穿上衣服", author="柊裕一"
    )
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS OrganizePolicy (id TEXT PRIMARY KEY, overwriteTitleAuthor INTEGER NOT NULL DEFAULT 1)"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO OrganizePolicy "
            "(id, overwriteTitleAuthor, createdAt, updatedAt) "
            "VALUES ('default', 0, 'now', 'now')"
        )
    )
    db_session.commit()
    candidate = {
        "id": "douban-auto-apply-off",
        "source": "douban",
        "title": "拜托请穿上，鹰峰同学",
        "author": "柊裕二",
        "description": "应自动补全的简介",
        "tags": ["推理"],
        "raw": {
            "infobox": [
                {"key": "别名", "value": [{"k": "非官方", "v": "鹰峰同学请穿上衣服"}]}
            ],
        },
    }
    monkeypatch.setattr(
        queue,
        "search_with_metadata_provider",
        lambda *_args, **_kwargs: {"enabled": True, "candidates": [candidate]},
    )

    assert process_metadata_lookup_task(db_session, test_settings, task) == "COMPLETED"

    work = (
        db_session.execute(
            text(
                "SELECT title, author, description, tags, organized FROM LibraryWork WHERE id = 'work-lookup'"
            )
        )
        .mappings()
        .one()
    )
    assert dict(work) == {
        "title": "鹰峰同学请穿上衣服",
        "author": "柊裕一",
        "description": "应自动补全的简介",
        "tags": '["epub"]',
        "organized": 1,
    }
    lookup = db_session.execute(
        text("SELECT appliedFields FROM MetadataLookupTask WHERE id = 'lookup-1'")
    ).scalar()
    assert json.loads(lookup) == ["description"]
    assert (
        db_session.execute(
            text("SELECT status FROM OrganizeJob WHERE id = 'job-lookup'")
        ).scalar()
        == "APPLIED"
    )
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM LibraryMetadata WHERE volumeId = 'volume-lookup'"
            )
        ).scalar()
        == 1
    )


def test_stale_running_lookup_is_recovered(db_session):
    create_worker_tables(db_session)
    _insert_lookup_fixture(db_session)
    db_session.execute(
        text(
            "UPDATE MetadataLookupTask SET startedAt = 946684800000 WHERE id = 'lookup-1'"
        )
    )
    db_session.commit()

    assert recover_stale_metadata_lookup_tasks(db_session) == 1
    row = (
        db_session.execute(
            text(
                "SELECT status, startedAt FROM MetadataLookupTask WHERE id = 'lookup-1'"
            )
        )
        .mappings()
        .first()
    )
    assert row["status"] == "PENDING"
    assert row["startedAt"] is None


def test_provider_enabled_flags_cannot_be_bypassed_with_force(db_session):
    context = {
        "work": {"title": "测试图书", "workType": "EPUB"},
        "mediaVersions": [],
        "files": [],
        "metadata": [],
    }

    douban = run_douban_metadata_provider(
        db_session,
        context,
        {"metadata.douban.enabled": "false"},
        force=True,
        query="测试图书",
    )
    bangumi = run_bangumi_metadata_provider(
        db_session,
        context,
        {"metadata.bangumi.enabled": "false"},
        force=True,
        query="测试图书",
    )

    assert douban["enabled"] is False
    assert bangumi["enabled"] is False


@pytest.mark.parametrize("provider", ["douban", "bangumi"])
def test_external_metadata_cache_only_saves_successful_non_empty_results(
    db_session, provider
):
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ExternalMetadataCache (
                id TEXT PRIMARY KEY, provider TEXT, queryKey TEXT, rawJson TEXT, expiresAt TEXT,
                createdAt TEXT, updatedAt TEXT, UNIQUE(provider, queryKey)
            )
            """
        )
    )
    db_session.commit()

    external_metadata_cache_put(
        db_session,
        provider,
        "活着",
        {"candidates": [{"title": "活着"}], "message": None},
    )
    success_hours = db_session.execute(
        text(
            "SELECT (CAST(expiresAt AS INTEGER) - CAST(updatedAt AS INTEGER)) / 3600000.0 FROM ExternalMetadataCache"
        )
    ).scalar()
    assert 23.9 < success_hours < 24.1
    assert (
        external_metadata_cache_get(db_session, provider, "活着")["candidates"][0][
            "title"
        ]
        == "活着"
    )

    external_metadata_cache_put(
        db_session, provider, "活着", {"candidates": [], "message": "empty"}
    )
    external_metadata_cache_put(
        db_session,
        provider,
        "活着",
        {"candidates": [{"id": "empty"}], "error": "timeout"},
    )
    assert (
        external_metadata_cache_get(db_session, provider, "活着")["candidates"][0][
            "title"
        ]
        == "活着"
    )
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM ExternalMetadataCache")).scalar()
        == 1
    )

    db_session.execute(
        text(
            "UPDATE ExternalMetadataCache SET rawJson = :raw_json WHERE provider = :provider AND queryKey = '活着'"
        ),
        {
            "provider": provider,
            "raw_json": json.dumps({"candidates": [], "message": "legacy empty cache"}),
        },
    )
    db_session.commit()
    assert external_metadata_cache_get(db_session, provider, "活着") is None


def test_ai_metadata_cache_reuses_only_non_empty_successes(db_session, monkeypatch):
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ExternalMetadataCache (
                id TEXT PRIMARY KEY, provider TEXT, queryKey TEXT, rawJson TEXT, expiresAt TEXT,
                createdAt TEXT, updatedAt TEXT, UNIQUE(provider, queryKey)
            )
            """
        )
    )
    db_session.commit()
    context = {
        "work": {"title": "AI 测试图书", "workType": "EPUB"},
        "mediaVersions": [],
        "files": [],
        "metadata": [],
    }
    calls = []

    def successful_ai(*_args, **_kwargs):
        calls.append("success")
        return {
            "provider": "ai",
            "enabled": True,
            "cacheHit": False,
            "suggestions": [
                {"field": "title", "suggestedValue": "AI 规范书名", "confidence": 0.9}
            ],
        }

    monkeypatch.setattr(
        "app.services.organize_service.run_ai_metadata_provider", successful_ai
    )
    first = metadata_search_candidates(db_session, context, "ai")
    second = metadata_search_candidates(db_session, context, "ai")

    assert first["cacheHit"] is False
    assert second["cacheHit"] is True
    assert second["candidates"][0]["title"] == "AI 规范书名"
    assert calls == ["success"]

    db_session.execute(text("DELETE FROM ExternalMetadataCache"))
    db_session.commit()
    monkeypatch.setattr(
        "app.services.organize_service.run_ai_metadata_provider",
        lambda *_args, **_kwargs: {
            "provider": "ai",
            "enabled": True,
            "cacheHit": False,
            "suggestions": [],
        },
    )
    assert metadata_search_candidates(db_session, context, "ai")["candidates"] == []
    assert external_metadata_cache_get(db_session, "ai", "ai测试图书") is None

    monkeypatch.setattr(
        "app.services.organize_service.run_ai_metadata_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError("AI gateway timeout")
        ),
    )
    with pytest.raises(TimeoutError, match="AI gateway timeout"):
        metadata_search_candidates(db_session, context, "ai")
    assert external_metadata_cache_get(db_session, "ai", "ai测试图书") is None
