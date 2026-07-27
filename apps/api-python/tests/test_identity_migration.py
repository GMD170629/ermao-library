from sqlalchemy import text

from app.db.bootstrap import backfill_library_identity_keys
from app.services.book_identity import identity_merge_key
from tests.test_worker_importer import create_worker_tables


def _insert_work(db, work_id, title, author, merge_key, created_at, hidden=0):
    db.execute(
        text(
            """
            INSERT INTO LibraryWork (
                id, origin, title, normalizedTitle, author, normalizedAuthor, workType, status,
                publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverStatus,
                hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                :id, 'MANUAL', :title, 'legacy-title', :author, 'legacy-author', 'EPUB', 'WANT',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'APPLIED', 'PENDING', :hidden, 1,
                :merge_key, :created_at, :created_at
            )
            """
        ),
        {
            "id": work_id,
            "title": title,
            "author": author,
            "hidden": hidden,
            "merge_key": merge_key,
            "created_at": created_at,
        },
    )


def test_identity_backfill_selects_earliest_visible_canonical_without_merging_records(db_session):
    create_worker_tables(db_session)
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS DuplicateCandidate (
                id TEXT PRIMARY KEY, jobId TEXT, targetWorkId TEXT, reasons TEXT, confidence REAL,
                suggestedAction TEXT, status TEXT, createdAt TEXT, updatedAt TEXT
            )
            """
        )
    )
    db_session.execute(text("CREATE TABLE IF NOT EXISTS LibraryReadingProgress (id TEXT PRIMARY KEY, workId TEXT, position TEXT)"))
    desired = identity_merge_key("同一本书", "同一作者")
    _insert_work(db_session, "hidden-oldest", "同一本书", "同一作者", "ebook:legacy-hidden", "2020-01-01", hidden=1)
    _insert_work(db_session, "visible-canonical", "同一本书", "同一作者", "ebook:legacy-visible", "2021-01-01")
    _insert_work(db_session, "visible-duplicate", "同一本书", "同一作者", desired, "2022-01-01")
    _insert_work(db_session, "unique-work", "另一本书", "另一作者", "comic:legacy-unique", "2023-01-01")
    db_session.execute(text("INSERT INTO LibraryReadingProgress (id, workId, position) VALUES ('progress-1', 'visible-duplicate', '42')"))
    db_session.commit()

    backfill_library_identity_keys(db_session)
    db_session.commit()

    rows = {
        row["id"]: dict(row)
        for row in db_session.execute(text("SELECT id, normalizedTitle, normalizedAuthor, mergeKey, hidden FROM LibraryWork")).mappings()
    }
    assert rows["visible-canonical"]["mergeKey"] == desired
    assert rows["hidden-oldest"]["mergeKey"] == "ebook:legacy-hidden"
    assert rows["visible-duplicate"]["mergeKey"].startswith("legacy-identity:visible-duplicate:")
    assert rows["unique-work"]["mergeKey"] == identity_merge_key("另一本书", "另一作者")
    assert rows["visible-canonical"]["normalizedTitle"] == "同一本书"
    assert rows["visible-canonical"]["normalizedAuthor"] == "同一作者"
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryWork")).scalar() == 4
    assert db_session.execute(text("SELECT workId, position FROM LibraryReadingProgress WHERE id = 'progress-1'")).first() == ("visible-duplicate", "42")

    candidates = db_session.execute(text("SELECT targetWorkId FROM DuplicateCandidate ORDER BY targetWorkId")).scalars().all()
    assert candidates == ["visible-canonical", "visible-canonical"]
    assert db_session.execute(text("SELECT COUNT(*) FROM OrganizeJob WHERE status = 'REVIEWING'")).scalar() == 2
    assert db_session.execute(text("SELECT value FROM SystemSetting WHERE `key` = 'migration.libraryIdentityVersion'")).scalar() == "1"

    db_session.execute(text("UPDATE OrganizeJob SET status = 'APPLIED'"))
    db_session.execute(text("UPDATE DuplicateCandidate SET status = 'DISMISSED'"))
    db_session.commit()
    backfill_library_identity_keys(db_session)
    db_session.commit()
    assert db_session.execute(text("SELECT COUNT(*) FROM OrganizeJob WHERE status = 'APPLIED'")).scalar() == 2
    assert db_session.execute(text("SELECT COUNT(*) FROM DuplicateCandidate WHERE status = 'DISMISSED'")).scalar() == 2
